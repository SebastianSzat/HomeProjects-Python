#####################################################################
## Creator  : SebastianSzat                                        ##
## Usage    : Free to use, but please give credit when applicable. ##
##            No warranty is provided. Use at your own risk.       ##
## --------------------------------------------------------------- ##
## Version  : 3.0                                                  ##
## Modified : 21-03-2026                                           ##
## --------------------------------------------------------------- ##
## mp3_metadata_from_path.py                                       ##
## Tags MP3 files with album, artist, title and tracknumber        ##
## derived from directory structure and filenames.                 ##
## Supports dry-run, recursive mode, force overwrite, filename     ##
## pattern parsing (--name-info), and a per-run summary.           ##
#####################################################################

#####################################################################
## import libraries
import os
import re
import glob
import argparse
from mutagen.easyid3 import EasyID3
from mutagen import File as MutagenFile
from mutagen.id3 import ID3NoHeaderError

#####################################################################
## constants

## Maps --name-info token names to EasyID3 tag keys.
TAG_NAME_MAP = {
    "TITLE":    "title",
    "TRACK":    "title",
    "ALBUM":    "album",
    "ARTIST":   "artist",
    "TRACKNUM": "tracknumber",
    "NUM":      "tracknumber",
}

## Regex for default title/tracknumber extraction from filename stems.
## Supported patterns:  01 - Title  /  01. Title  /  01_Title  /  01 Title
TRACK_PREFIX_RE = re.compile(
    r'^(\d{1,3})'
    r'(?:\s*[-\.]\s*|_|\s+)'
    r'(.+)$'
)

#####################################################################
## extract_tags_from_filename
## Splits a filename into (title, tracknumber) using the default regex.
## Returns tracknumber as None if no leading track number is found.
## Examples:
##   "01 - Come Together.mp3" -> ("Come Together", "01")
##   "01. Come Together.mp3"  -> ("Come Together", "01")
##   "01_Come Together.mp3"   -> ("Come Together", "01")
##   "Come Together.mp3"      -> ("Come Together", None)
def extract_tags_from_filename(filename: str) -> tuple:
    stem = os.path.splitext(filename)[0]
    match = TRACK_PREFIX_RE.match(stem)
    if match:
        return match.group(2).strip(), match.group(1)
    return stem.strip(), None

#####################################################################
## load_or_create_tags
## Returns an EasyID3-compatible object. Creates a blank ID3 header
## if the file has none (common with freshly ripped MP3s).
## Raises ValueError with a clear message if the format is unknown.
## Note: EasyID3 stores all tag values internally as lists.
##       Use audio.get(key, [None])[0] to read a single value safely.
def load_or_create_tags(file_path: str):
    try:
        return EasyID3(file_path)
    except ID3NoHeaderError:
        audio = MutagenFile(file_path, easy=True)
        if audio is None:
            raise ValueError("File format not recognized — not a valid MP3.")
        audio.add_tags()
        return audio

#####################################################################
## parse_name_pattern
## Parses a --name-info spec string into a list of alternating
## ('tag', easyid3_key) and ('delim', string) tokens.
##
## Spec format:  TOKEN||DELIM||TOKEN||DELIM||TOKEN
##   - Odd number of ||-separated parts required.
##   - Even-index parts are tag names; odd-index parts are delimiters.
##   - Valid tag names: TITLE/TRACK, ALBUM, ARTIST, TRACKNUM/NUM
##
## Raises ValueError with a clear message on malformed input.
def parse_name_pattern(spec: str) -> list:
    if not spec.strip():
        raise ValueError(
            "Empty --name-info pattern. Expected e.g. 'TRACK|| - ||ALBUM'."
        )
    parts = spec.split("||")
    if len(parts) % 2 == 0:
        raise ValueError(
            f"Invalid --name-info '{spec}': must have an odd number of "
            f"||-separated parts (e.g. TRACK|| - ||ALBUM)."
        )
    result = []
    for i, part in enumerate(parts):
        if i % 2 == 0:                          ## tag position
            key = part.strip().upper()
            if key not in TAG_NAME_MAP:
                valid = ", ".join(sorted(TAG_NAME_MAP))
                raise ValueError(
                    f"Unknown token '{part}' in --name-info. Valid: {valid}."
                )
            result.append(("tag", TAG_NAME_MAP[key]))
        else:                                    ## delimiter position
            if not part:
                raise ValueError(
                    f"Empty delimiter in --name-info '{spec}'. "
                    f"Use e.g. '|| - ||' for a space-dash-space split."
                )
            result.append(("delim", part))
    return result

#####################################################################
## apply_name_pattern
## Applies a parsed pattern to a filename stem. Returns a dict of
## {easyid3_key: value} for each matched segment, or an empty dict
## if any delimiter is not found (pattern does not match this file).
## Splits are left-to-right on the first occurrence of each delimiter.
def apply_name_pattern(stem: str, pattern: list) -> dict:
    tag_keys   = [v for t, v in pattern if t == "tag"]
    delimiters = [v for t, v in pattern if t == "delim"]

    tags      = {}
    remaining = stem

    for i, delim in enumerate(delimiters):
        idx = remaining.find(delim)
        if idx == -1:
            return {}                            ## delimiter not found — no match
        value = remaining[:idx].strip()
        if value:
            tags[tag_keys[i]] = value
        remaining = remaining[idx + len(delim):]

    ## Last remaining segment maps to the final tag
    last_value = remaining.strip()
    if tag_keys and last_value:
        tags[tag_keys[-1]] = last_value

    return tags

#####################################################################
## process_file
## Builds the desired tag set, compares it against stored values,
## and writes only what needs updating.
## Returns a (status_code, display_string) tuple.
## status_code is one of: "updated", "skipped", "failed", "dryrun".
def process_file(
    file_path:    str,
    album:        str,
    artist:       str,
    dry_run:      bool,
    force:        bool,
    name_pattern: list,
) -> tuple:
    filename = os.path.basename(file_path)
    stem     = os.path.splitext(filename)[0]

    title, tracknumber = extract_tags_from_filename(filename)

    ## Start with directory-derived values as the baseline.
    ## tracknumber is only added when the filename regex found one,
    ## because None would otherwise overwrite a legitimate stored value.
    desired = {"album": album, "artist": artist, "title": title}
    if tracknumber is not None:
        desired["tracknumber"] = tracknumber

    ## --name-info pattern overrides directory-derived values per file.
    ## pattern_miss=True means the delimiter was not found in this filename,
    ## so the directory-derived values are used and a note is appended to output.
    pattern_miss = False
    if name_pattern:
        pattern_tags = apply_name_pattern(stem, name_pattern)
        if pattern_tags:
            desired.update(pattern_tags)
        else:
            pattern_miss = True

    ## Remove empty strings — never write a blank tag.
    ## This guards against shallow paths where os.path.basename returns "".
    desired = {k: v for k, v in desired.items() if v}

    if not desired:
        return "skipped", f"  [SKIP]     {filename}"

    try:
        audio = load_or_create_tags(file_path)

        ## --force: overwrite any tag whose stored value differs from desired.
        ## Default: only fill tags that are currently empty (falsy stored value).
        ## audio.get(k, [None])[0] — EasyID3 stores values as lists internally;
        ## [0] unpacks the first element, [None] is the default when the key is absent.
        if force:
            updates = {
                k: v for k, v in desired.items()
                if audio.get(k, [None])[0] != v
            }
        else:
            updates = {
                k: v for k, v in desired.items()
                if not audio.get(k, [None])[0]
            }

        miss_note = "  (pattern not matched — used directory values)" if pattern_miss else ""

        if not updates:
            return "skipped", f"  [SKIP]     {filename}{miss_note}"

        changes_str = ", ".join(f'{k}="{v}"' for k, v in updates.items())

        if dry_run:
            return "dryrun", f"  [DRY-RUN]  {filename}  |  would set: {changes_str}{miss_note}"

        for k, v in updates.items():
            audio[k] = v
        audio.save()

        return "updated", f"  [UPDATED]  {filename}  |  set: {changes_str}{miss_note}"

    except Exception as e:
        return "failed", f"  [FAILED]   {filename}  |  {e}"

#####################################################################
## process_directory
## Prints a header for the directory, processes each MP3 file, and
## returns a count dict {updated, skipped, failed, dryrun}.
## album  -> folder name  (or album_override if provided)
## artist -> parent folder name  (or artist_override if provided)
##           If the parent folder resolves to "" (e.g. a root path),
##           artist is set to "" and filtered out of desired tags downstream.
def process_directory(
    directory:       str,
    artist_override: str,
    album_override:  str,
    dry_run:         bool,
    force:           bool,
    name_pattern:    list,
) -> dict:
    counts = {"updated": 0, "skipped": 0, "failed": 0, "dryrun": 0}

    album  = album_override  or os.path.basename(os.path.normpath(directory))
    parent = os.path.dirname(os.path.normpath(directory))
    artist = artist_override or os.path.basename(parent)

    print()
    print("----------------------------------------")
    print(f"Directory : {directory}")
    print(f"Album     : {album}")
    print(f"Artist    : {artist or '(not set)'}")
    print("----------------------------------------")

    try:
        mp3_files = sorted(f for f in os.listdir(directory) if f.lower().endswith(".mp3"))
    except OSError as e:
        print(f"  [FAILED]   Cannot read directory: {e}")
        counts["failed"] += 1
        return counts

    if not mp3_files:
        print("  (no MP3 files found)")
        return counts

    for filename in mp3_files:
        file_path = os.path.join(directory, filename)
        status, message = process_file(
            file_path, album, artist, dry_run, force, name_pattern
        )
        print(message)
        counts[status] += 1

    return counts

#####################################################################
## collect_directories
## Expands glob patterns, filters to directories, optionally recurses
## into subdirectories containing MP3 files. Deduplicates via realpath.
## Non-recursive: every explicitly-given directory is included regardless
##                of whether it currently contains MP3 files.
## Recursive:     only directories that contain at least one .mp3 file
##                are included (empty subdirectories are skipped silently).
def collect_directories(paths: list, recursive: bool) -> list:
    seen   = set()
    result = []

    for path in paths:
        expanded = glob.glob(path)
        if not expanded:
            print(f"Warning: no matches found for '{path}'")
            continue

        for match in expanded:
            if not os.path.isdir(match):
                continue

            if recursive:
                for root, _dirs, files in os.walk(match):
                    if any(f.lower().endswith(".mp3") for f in files):
                        canon = os.path.realpath(root)
                        if canon not in seen:
                            seen.add(canon)
                            result.append(root)
            else:
                canon = os.path.realpath(match)
                if canon not in seen:
                    seen.add(canon)
                    result.append(match)

    return result

#####################################################################
## main
## Entry point: parses CLI arguments, validates --name-info upfront,
## collects directories, processes each one, and prints a run summary.
def main():
    parser = argparse.ArgumentParser(
        prog="mp3_metadata_from_path.py",
        description=(
            "Tag MP3 files with album, artist, title and tracknumber "
            "derived from directory structure and filenames."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Default tag sources (when --name-info is not used):
  album       -> folder name
  artist      -> parent folder name
  title       -> filename with leading track number stripped
  tracknumber -> leading number in filename

--name-info pattern syntax:
  TOKEN||DELIM||TOKEN||DELIM||TOKEN  (odd number of ||-separated parts)
  Valid tokens : TITLE or TRACK, ALBUM, ARTIST, TRACKNUM or NUM
  DELIM        : literal string to split on in the filename (include spaces if needed)
  Splits happen left-to-right on the FIRST occurrence of each delimiter.
  Tags not covered by the pattern fall back to the directory structure.
  When --name-info is combined with --artist or --album, the pattern
  takes precedence over those flags for any tag it explicitly extracts.

  WARNING: if your filenames have a leading track number (e.g. "01 - ..."),
  do NOT start the pattern with TRACK — the first split will grab "01" as
  the title. Use TRACKNUM as the first token instead:
    "TRACKNUM|| - ||TRACK|| - ||ALBUM"  for  "01 - Title - Album.mp3"

  Examples:
    --name-info "TRACK|| - ||ALBUM"
        "Come Together - Abbey Road.mp3"
         -> title="Come Together", album="Abbey Road", artist=<parent folder>

    --name-info "ARTIST|| - ||TRACK"
        "Beatles - Come Together.mp3"
         -> artist="Beatles", title="Come Together", album=<folder name>

    --name-info "ARTIST|| - ||TRACK|| - ||ALBUM"
        "Beatles - Come Together - Abbey Road.mp3"
         -> artist="Beatles", title="Come Together", album="Abbey Road"

    --name-info "TRACKNUM||. ||TRACK|| - ||ALBUM"
        "01. Come Together - Abbey Road.mp3"
         -> tracknumber="01", title="Come Together", album="Abbey Road"

Usage examples:
  python mp3_metadata_from_path.py "/music/Beatles/Abbey Road"
  python mp3_metadata_from_path.py "/music/Beatles/*" --dry-run
  python mp3_metadata_from_path.py "/music" --recursive
  python mp3_metadata_from_path.py "/music" -r --name-info "ARTIST|| - ||TRACK|| - ||ALBUM"
  python mp3_metadata_from_path.py "/music" -r --force
        """
    )

    parser.add_argument(
        "paths", nargs="+", metavar="PATH",
        help="Directory path(s) to process. Glob wildcards supported."
    )
    parser.add_argument(
        "-r", "--recursive", action="store_true",
        help="Recurse into subdirectories and process every folder containing MP3 files."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview tag changes without writing any files."
    )
    parser.add_argument(
        "--force", action="store_true",
        help=(
            "Overwrite existing tags. "
            "Default behaviour: only fill tags that are currently empty."
        )
    )
    parser.add_argument(
        "--artist", metavar="NAME", default=None,
        help=(
            "Override artist tag for all processed files (default: parent folder name). "
            "Note: --name-info takes precedence over this flag for any tag it extracts."
        )
    )
    parser.add_argument(
        "--album", metavar="NAME", default=None,
        help=(
            "Override album tag for all processed files (default: folder name). "
            "When combined with --recursive, every folder receives the same value. "
            "Note: --name-info takes precedence over this flag for any tag it extracts."
        )
    )
    parser.add_argument(
        "--name-info", metavar="PATTERN", dest="name_info", default=None,
        help=(
            "Extract tags from filenames using a pattern. "
            "Format: TOKEN||DELIM||TOKEN  (e.g. 'TRACK|| - ||ALBUM'). "
            "See the full description above."
        )
    )

    args = parser.parse_args()

    ## Validate and parse --name-info upfront so errors surface before any processing
    name_pattern = None
    if args.name_info:
        try:
            name_pattern = parse_name_pattern(args.name_info)
        except ValueError as e:
            print(f"ERROR: {e}")
            raise SystemExit(1)

    if args.dry_run:
        print("[DRY-RUN MODE -- no files will be modified]")
    if args.force:
        print("[FORCE MODE -- existing tags will be overwritten]")

    directories = collect_directories(args.paths, args.recursive)

    if not directories:
        print("Error: No valid directories found.")
        raise SystemExit(1)

    totals = {"updated": 0, "skipped": 0, "failed": 0, "dryrun": 0}

    for directory in directories:
        counts = process_directory(
            directory, args.artist, args.album,
            args.dry_run, args.force, name_pattern
        )
        for k in totals:
            totals[k] += counts[k]

    ## Run summary
    print()
    print("========================================")
    print("Summary")
    print("========================================")
    if args.dry_run:
        print(f"  Would update : {totals['dryrun']}")
    else:
        print(f"  Updated      : {totals['updated']}")
    print(f"  Skipped      : {totals['skipped']}")
    print(f"  Failed       : {totals['failed']}")
    print()

#####################################################################
## entry point
if __name__ == "__main__":
    main()
