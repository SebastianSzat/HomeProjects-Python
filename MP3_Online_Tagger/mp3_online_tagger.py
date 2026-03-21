#####################################################################
## Creator  : SebastianSzat                                        ##
## Usage    : Free to use, but please give credit when applicable. ##
##            No warranty is provided. Use at your own risk.       ##
## --------------------------------------------------------------- ##
## Version  : 1.0                                                  ##
## Modified : 21-03-2026                                           ##
## --------------------------------------------------------------- ##
## mp3_online_tagger.py                                            ##
## Fills MP3 metadata by audio fingerprinting (AcoustID/fpcalc)   ##
## and online lookup (MusicBrainz). Falls back to text search     ##
## when fingerprinting yields no result. Supports dry-run,        ##
## recursive mode, force overwrite, auto/semi-auto/confirm        ##
## interaction modes, cover art embedding, and per-run restore.   ##
#####################################################################

#####################################################################
## import libraries
import os, re, sys, json, time, glob, shutil, subprocess
import argparse, datetime, configparser
from mutagen.id3 import (ID3, ID3NoHeaderError,
    TIT2, TPE1, TALB, TRCK, TDRC, TCON, TPE2, TCOM, TPOS, APIC)
from mutagen.mp3 import MP3
import requests
from rapidfuzz import fuzz
from tqdm import tqdm

#####################################################################
## constants

MUSICBRAINZ_API     = "https://musicbrainz.org/ws/2"
ACOUSTID_API        = "https://api.acoustid.org/v2/lookup"
COVERART_API        = "https://coverartarchive.org/release"
MB_RATE_LIMIT       = 1.1    ## seconds between MusicBrainz requests (their policy)
ACOUSTID_RATE       = 0.35   ## seconds between AcoustID requests
DEFAULT_CONFIG      = "mp3_online_tagger.ini"
RESTORE_PREFIX      = "restore_"
TEXT_TAGS           = ["title", "artist", "album", "tracknumber", "totaltracks",
                       "year", "genre", "albumartist", "composer", "discnumber"]
TAG_FRAME_MAP = {
    "title":       TIT2,
    "artist":      TPE1,
    "album":       TALB,
    "tracknumber": TRCK,
    "year":        TDRC,
    "genre":       TCON,
    "albumartist": TPE2,
    "composer":    TCOM,
    "discnumber":  TPOS,
}

DEFAULT_INI_CONTENT = """\
[credentials]
# Your AcoustID API key. Register for a free key at: https://acoustid.org/api-key
acoustid_api_key =

# MusicBrainz requires a User-Agent header identifying your application.
# Format: AppName/Version (contact-email)
# Example: mp3_online_tagger/1.0 (your@email.com)
musicbrainz_user_agent = mp3_online_tagger/1.0 (your@email.com)

[behavior]
# Processing mode: auto, semi-auto, or confirm
#   auto      - always write best match without prompting
#   semi-auto - prompt on low confidence, multiple close candidates, or tag mismatch (default)
#   confirm   - always prompt before writing anything
mode = semi-auto

# Confidence threshold for semi-auto mode (0.0 to 1.0)
# Matches at or above this score are written automatically in semi-auto.
# Matches below it will trigger an interactive prompt.
confidence_threshold = 0.85

# Maximum number of candidates to show when prompting (1-10)
max_candidates = 5

# How close the top two candidates must be (score difference) to trigger a
# "multiple close candidates" prompt in semi-auto. E.g. 0.05 = within 5%.
close_candidate_margin = 0.05

[tags]
# Set true/false to enable or disable writing each tag field.
title       = true
artist      = true
album       = true
tracknumber = true
year        = true
genre       = true
albumartist = true
composer    = false
discnumber  = false
totaltracks = false

# Fetch and embed album cover art from the Cover Art Archive.
# A confirmation prompt is shown at startup when this is true.
# Override at runtime with --cover-art or --no-cover-art flags.
cover_art = true

[paths]
# Path to the fpcalc (Chromaprint) binary.
# Leave empty to search the system PATH automatically.
# Windows example: C:\\Tools\\fpcalc.exe
# Linux example:   /usr/bin/fpcalc
fpcalc_path =

# Directory where per-run restore map files are saved.
# Leave empty to save them in the same directory as this script.
restore_dir =
"""

#####################################################################
## _write_default_config
## Writes the full default INI content (with all inline comments) to
## the given path. Called automatically when the config file is absent.
def _write_default_config(path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(DEFAULT_INI_CONTENT)
    print(f"Created default config: {path}")
    print("Please edit it and add your AcoustID API key before running again.")

#####################################################################
## load_config
## Loads the INI config from config_path. If the file does not exist,
## calls _write_default_config to create it and then exits, prompting
## the user to fill in their credentials. Returns a ConfigParser object.
def load_config(config_path: str) -> configparser.ConfigParser:
    if not os.path.isfile(config_path):
        _write_default_config(config_path)
        raise SystemExit(0)
    cfg = configparser.ConfigParser()
    cfg.read(config_path, encoding="utf-8")
    return cfg

#####################################################################
## get_enabled_tags
## Reads the [tags] section of the config and returns a set of tag
## names whose value is "true". Ignores "cover_art" (handled separately).
def get_enabled_tags(cfg: configparser.ConfigParser) -> set:
    enabled = set()
    if cfg.has_section("tags"):
        for tag in TEXT_TAGS:
            if cfg.getboolean("tags", tag, fallback=False):
                enabled.add(tag)
    return enabled

#####################################################################
## extract_hints_from_path
## Derives title, artist, album, and tracknumber hints from the file's
## path without touching the audio content.
##
## Filename patterns supported:
##   "01 - Title"  /  "01. Title"  /  "01_Title"  /  "01 Title"
##   "Artist - Title"  (detected when no leading track number)
## Falls back to treating the full stem as title.
## Album  -> parent directory name.
## Artist -> grandparent directory name.
## Returns a dict with any non-empty string values.
def extract_hints_from_path(file_path: str) -> dict:
    hints = {}
    abs_path  = os.path.abspath(file_path)
    filename  = os.path.basename(abs_path)
    stem      = os.path.splitext(filename)[0]
    parent    = os.path.dirname(abs_path)
    album_dir = os.path.basename(parent)
    artist_dir = os.path.basename(os.path.dirname(parent))

    ## Check if album folder uses "Artist - Album" format.
    ## This is more reliable than the grandparent folder when the music
    ## sits inside a staging/test directory (e.g. test_env/Artist - Album/).
    artist_album_re = re.compile(r'^(.+?)\s+-\s+(.+)$')
    aam = artist_album_re.match(album_dir)
    if aam:
        hints["artist"] = aam.group(1).strip()
        hints["album"]  = aam.group(2).strip()
    else:
        ## Plain folder name — use as album and fall back to grandparent for artist
        if album_dir:
            hints["album"] = album_dir
        if artist_dir:
            hints["artist"] = artist_dir

    ## Try leading track-number patterns first
    track_re = re.compile(
        r'^(\d{1,3})'
        r'(?:\s*[-\.]\s*|_|\s+)'
        r'(.+)$'
    )
    m = track_re.match(stem)
    if m:
        hints["tracknumber"] = m.group(1)
        title_raw = m.group(2).strip()
        ## Strip "Artist - " prefix from title when the artist is already
        ## known from the folder name (e.g. "03 Powerwolf - Moscow After Dark").
        known_artist = hints.get("artist", "")
        if known_artist:
            artist_prefix_re = re.compile(
                r'^' + re.escape(known_artist) + r'\s*-\s*', re.IGNORECASE
            )
            title_raw = artist_prefix_re.sub("", title_raw).strip()
        hints["title"] = title_raw
    else:
        ## Try "Artist - Title" split (dash with optional spaces)
        dash_re = re.compile(r'^(.+?)\s+-\s+(.+)$')
        dm = dash_re.match(stem)
        if dm:
            hints["artist"] = dm.group(1).strip()
            hints["title"]  = dm.group(2).strip()
        else:
            hints["title"] = stem.strip()

    return {k: v for k, v in hints.items() if v}

#####################################################################
## fingerprint_file
## Calls the fpcalc binary with the -json flag and parses its output.
## fpcalc_path can be an explicit path or empty/None to use PATH lookup.
## Returns (fingerprint_string, duration_int) on success, None on any
## failure (binary not found, non-zero exit, parse error, etc.).
def fingerprint_file(file_path: str, fpcalc_path: str) -> tuple | None:
    binary = fpcalc_path if fpcalc_path else shutil.which("fpcalc")
    if not binary:
        return None
    try:
        result = subprocess.run(
            [binary, "-json", file_path],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            return None
        data = json.loads(result.stdout)
        fingerprint = data.get("fingerprint", "")
        duration    = int(data.get("duration", 0))
        if not fingerprint or not duration:
            return None
        return fingerprint, duration
    except Exception:
        return None

#####################################################################
## _rate_limit
## Checks rate_state[key] (last request timestamp) and sleeps if the
## elapsed time is less than min_interval seconds. Updates rate_state[key]
## to the current time after sleeping (or immediately if no sleep needed).
def _rate_limit(rate_state: dict, key: str, min_interval: float) -> None:
    last = rate_state.get(key, 0.0)
    elapsed = time.time() - last
    if elapsed < min_interval:
        time.sleep(min_interval - elapsed)
    rate_state[key] = time.time()

#####################################################################
## query_acoustid
## POSTs to the AcoustID API with the given fingerprint and duration.
## For each result returned (up to max_candidates), calls
## query_musicbrainz_recording to enrich with full metadata.
## Returns a list of candidate dicts, each containing a "score" key
## (from AcoustID, 0.0–1.0) and "source"="acoustid".
def query_acoustid(
    fingerprint:   str,
    duration:      int,
    api_key:       str,
    user_agent:    str,
    rate_state:    dict,
    enabled_tags:  set,
    max_candidates: int,
) -> list:
    _rate_limit(rate_state, "acoustid", ACOUSTID_RATE)
    try:
        resp = requests.post(
            ACOUSTID_API,
            data={
                "client":       api_key,
                "fingerprint":  fingerprint,
                "duration":     duration,
                "meta":         "recordings releasegroups releases tracks",
            },
            headers={"User-Agent": user_agent},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return []

    if data.get("status") != "ok":
        return []

    candidates = []
    results = data.get("results", [])
    for result in results[:max_candidates]:
        score          = float(result.get("score", 0.0))
        recordings     = result.get("recordings", [])
        for rec_stub in recordings[:1]:
            rec_id = rec_stub.get("id")
            if not rec_id:
                continue
            candidate = query_musicbrainz_recording(
                rec_id, user_agent, rate_state, enabled_tags
            )
            if candidate:
                candidate["score"]  = score
                candidate["source"] = "acoustid"
                candidates.append(candidate)

    return candidates

#####################################################################
## query_musicbrainz_recording
## Fetches full recording detail from the MusicBrainz API and parses
## it via _parse_mb_recording. Returns a candidate dict or None on
## any network / parse failure.
def query_musicbrainz_recording(
    recording_id: str,
    user_agent:   str,
    rate_state:   dict,
    enabled_tags: set,
) -> dict | None:
    _rate_limit(rate_state, "musicbrainz", MB_RATE_LIMIT)
    url    = f"{MUSICBRAINZ_API}/recording/{recording_id}"
    params = {"fmt": "json", "inc": "releases+artist-credits+genres"}
    try:
        resp = requests.get(
            url,
            params=params,
            headers={"User-Agent": user_agent},
            timeout=30,
        )
        resp.raise_for_status()
        rec = resp.json()
    except Exception:
        return None

    return _parse_mb_recording(rec, enabled_tags)

#####################################################################
## _parse_mb_recording
## Converts a raw MusicBrainz recording JSON object into a flat
## candidate dict. Extracts artist from artist-credit[0], release data
## from releases[0], track position from media[0], and the top genre
## by vote count. Returns None if essential fields are missing.
def _parse_mb_recording(rec: dict, enabled_tags: set) -> dict | None:
    if not rec:
        return None

    candidate = {
        "title":        "",
        "artist":       "",
        "album":        "",
        "year":         "",
        "tracknumber":  "",
        "totaltracks":  "",
        "discnumber":   "",
        "genre":        "",
        "albumartist":  "",
        "composer":     "",
        "recording_id": rec.get("id", ""),
        "release_id":   "",
        "score":        0.0,
        "source":       "musicbrainz",
    }

    candidate["title"] = rec.get("title", "")

    ## Artist from artist-credit
    artist_credits = rec.get("artist-credit", [])
    if artist_credits:
        first = artist_credits[0]
        if isinstance(first, dict):
            artist_obj = first.get("artist", {})
            candidate["artist"] = artist_obj.get("name", "")
            candidate["albumartist"] = artist_obj.get("name", "")

    ## Release data from first release
    releases = rec.get("releases", [])
    if releases:
        rel = releases[0]
        candidate["release_id"] = rel.get("id", "")
        candidate["album"]      = rel.get("title", "")

        ## Year from release-event or date field
        date_str = rel.get("date", "")
        if date_str:
            candidate["year"] = date_str[:4]

        ## Track position and total from media[0]
        media_list = rel.get("media", [])
        if media_list:
            media = media_list[0]
            track_count = str(media.get("track-count", ""))
            candidate["totaltracks"] = track_count
            candidate["discnumber"]  = str(media.get("position", ""))
            tracks = media.get("tracks", [])
            if tracks:
                track_obj = tracks[0]
                candidate["tracknumber"] = str(track_obj.get("number", ""))

    ## Genre: pick the one with the highest vote count
    genres = rec.get("genres", [])
    if genres:
        top_genre = max(genres, key=lambda g: g.get("count", 0))
        candidate["genre"] = top_genre.get("name", "")

    return candidate

#####################################################################
## query_musicbrainz_text
## Performs a Lucene text search on the MusicBrainz recording endpoint
## using hints (title, artist, album). Normalises the MB score field
## (0–100) to a 0.0–1.0 float. Returns a list of candidate dicts
## with source="musicbrainz_text".
def query_musicbrainz_text(
    hints:          dict,
    user_agent:     str,
    rate_state:     dict,
    enabled_tags:   set,
    max_candidates: int,
) -> list:
    ## Build Lucene query from non-empty hints
    parts = []
    if hints.get("title"):
        safe_title = hints["title"].replace('"', '\\"')
        parts.append(f'recording:"{safe_title}"')
    if hints.get("artist"):
        safe_artist = hints["artist"].replace('"', '\\"')
        parts.append(f'artist:"{safe_artist}"')
    if hints.get("album"):
        safe_album = hints["album"].replace('"', '\\"')
        parts.append(f'release:"{safe_album}"')

    if not parts:
        return []

    query_str = " AND ".join(parts)

    _rate_limit(rate_state, "musicbrainz", MB_RATE_LIMIT)
    url    = f"{MUSICBRAINZ_API}/recording/"
    params = {"query": query_str, "fmt": "json", "limit": max_candidates}
    try:
        resp = requests.get(
            url,
            params=params,
            headers={"User-Agent": user_agent},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return []

    candidates = []
    for rec in data.get("recordings", []):
        candidate = _parse_mb_recording(rec, enabled_tags)
        if not candidate:
            continue
        ## Normalise MB score (0–100) to 0.0–1.0
        mb_score = float(rec.get("score", 0)) / 100.0
        candidate["score"]  = mb_score
        candidate["source"] = "musicbrainz_text"
        candidates.append(candidate)

    return candidates

#####################################################################
## score_candidate
## Computes a fuzzy similarity score between a candidate and the hints
## extracted from the file path. Uses fuzz.ratio on title (weight 0.5),
## artist (0.35), album (0.15). Fields missing from either side
## contribute 0 to the weighted sum. Returns a float 0.0–1.0.
def score_candidate(candidate: dict, hints: dict) -> float:
    def _ratio(a: str, b: str) -> float:
        if not a or not b:
            return 0.0
        return fuzz.ratio(a.lower(), b.lower()) / 100.0

    title_score  = _ratio(candidate.get("title",  ""), hints.get("title",  ""))
    artist_score = _ratio(candidate.get("artist", ""), hints.get("artist", ""))
    album_score  = _ratio(candidate.get("album",  ""), hints.get("album",  ""))

    return title_score * 0.5 + artist_score * 0.35 + album_score * 0.15

#####################################################################
## fetch_cover_art
## GETs the front cover image from the Cover Art Archive for the given
## MusicBrainz release_id. Follows redirects automatically. Detects
## MIME type from the Content-Type response header, defaulting to
## "image/jpeg". Returns (bytes, mime_type) or (None, None) on failure.
def fetch_cover_art(release_id: str, user_agent: str) -> tuple:
    if not release_id:
        return None, None
    url = f"{COVERART_API}/{release_id}/front"
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": user_agent},
            allow_redirects=True,
            timeout=30,
        )
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "image/jpeg")
        ## Strip charset or boundary parameters if present
        mime_type = content_type.split(";")[0].strip()
        if not mime_type.startswith("image/"):
            mime_type = "image/jpeg"
        return resp.content, mime_type
    except Exception:
        return None, None

#####################################################################
## read_tags
## Reads all TEXT_TAGS from a file's ID3 header using mutagen.id3.ID3.
## Returns a dict with all TEXT_TAGS keys (empty string if absent).
## TRCK is split on "/" into tracknumber and totaltracks.
## "cover_art" key is True if at least one APIC frame is present.
## Returns a blank dict on ID3NoHeaderError (file has no ID3 tags).
def read_tags(file_path: str) -> dict:
    blank = {tag: "" for tag in TEXT_TAGS}
    blank["cover_art"] = False
    try:
        audio = ID3(file_path)
    except ID3NoHeaderError:
        return blank
    except Exception:
        return blank

    result = {tag: "" for tag in TEXT_TAGS}
    result["cover_art"] = bool(audio.getall("APIC"))

    ## Title
    if audio.get("TIT2"):
        result["title"] = str(audio["TIT2"])

    ## Artist
    if audio.get("TPE1"):
        result["artist"] = str(audio["TPE1"])

    ## Album
    if audio.get("TALB"):
        result["album"] = str(audio["TALB"])

    ## Track number / total tracks
    if audio.get("TRCK"):
        trck_str = str(audio["TRCK"])
        if "/" in trck_str:
            parts = trck_str.split("/", 1)
            result["tracknumber"] = parts[0].strip()
            result["totaltracks"] = parts[1].strip()
        else:
            result["tracknumber"] = trck_str.strip()

    ## Year
    if audio.get("TDRC"):
        result["year"] = str(audio["TDRC"])

    ## Genre
    if audio.get("TCON"):
        result["genre"] = str(audio["TCON"])

    ## Album artist
    if audio.get("TPE2"):
        result["albumartist"] = str(audio["TPE2"])

    ## Composer
    if audio.get("TCOM"):
        result["composer"] = str(audio["TCOM"])

    ## Disc number
    if audio.get("TPOS"):
        result["discnumber"] = str(audio["TPOS"])

    return result

#####################################################################
## build_updates
## Computes which tags need to be written to the file.
## Default (force=False): only tags where the current stored value is
##   empty (falsy) and the desired value is non-empty.
## Force (force=True): tags where the current stored value differs from
##   the desired value (and desired is non-empty).
## Only tags present in enabled_tags are included. Returns a dict of
## {tag_name: desired_value} for the tags that should be written.
def build_updates(
    candidate:    dict,
    current:      dict,
    force:        bool,
    enabled_tags: set,
) -> dict:
    updates = {}
    for tag in TEXT_TAGS:
        if tag not in enabled_tags:
            continue
        desired = candidate.get(tag, "")
        if not desired:
            continue
        existing = current.get(tag, "")
        if force:
            if existing != desired:
                updates[tag] = desired
        else:
            if not existing:
                updates[tag] = desired
    return updates

#####################################################################
## write_tags
## Writes a dict of tag updates to the file's ID3 header using direct
## ID3 frame classes from TAG_FRAME_MAP. Merges tracknumber and
## totaltracks into a single TRCK "N/M" frame (or "N" if no total).
## For cover art: removes all existing APIC frames and embeds the new
## image as a type-3 (front cover) APIC frame. Creates the ID3 header
## if the file has none (ID3NoHeaderError).
def write_tags(
    file_path:       str,
    updates:         dict,
    cover_art_data:  bytes | None,
    cover_art_mime:  str  | None,
) -> None:
    try:
        audio = ID3(file_path)
    except ID3NoHeaderError:
        audio = ID3()

    ## Write text tags — handle TRCK specially (merge tracknumber/totaltracks)
    trck_written = False
    for tag, value in updates.items():
        if tag in ("tracknumber", "totaltracks"):
            if not trck_written:
                tracknum = updates.get("tracknumber", "")
                totaltracks = updates.get("totaltracks", "")
                if tracknum and totaltracks:
                    trck_val = f"{tracknum}/{totaltracks}"
                elif tracknum:
                    trck_val = tracknum
                else:
                    trck_val = totaltracks
                audio.delall("TRCK")
                audio.add(TRCK(encoding=3, text=trck_val))
                trck_written = True
        else:
            frame_class = TAG_FRAME_MAP.get(tag)
            if frame_class:
                frame_id = frame_class.__name__
                audio.delall(frame_id)
                audio.add(frame_class(encoding=3, text=value))

    ## Embed cover art
    if cover_art_data:
        mime = cover_art_mime or "image/jpeg"
        audio.delall("APIC")
        audio.add(APIC(
            encoding=3,
            mime=mime,
            type=3,
            desc="Cover",
            data=cover_art_data,
        ))

    audio.save(file_path)

#####################################################################
## should_prompt
## Determines whether interactive prompting is needed in semi-auto mode.
## Returns (True, reason_string) in any of these cases:
##   1. Best candidate's score is below confidence_threshold.
##   2. Top two candidates are within close_margin of each other.
##   3. force=True AND at least one existing non-empty tag would be overwritten.
## Returns (False, "") when automatic writing is safe.
def should_prompt(
    candidates:          list,
    current:             dict,
    force:               bool,
    confidence_threshold: float,
    close_margin:        float,
) -> tuple:
    if not candidates:
        return True, "No matching candidates found."

    best = candidates[0]
    best_score = best.get("score", 0.0)

    ## Low confidence
    if best_score < confidence_threshold:
        pct = int(best_score * 100)
        return True, f"Low confidence ({pct}% < {int(confidence_threshold * 100)}% threshold)."

    ## Two candidates within close margin of each other
    if len(candidates) >= 2:
        second_score = candidates[1].get("score", 0.0)
        if (best_score - second_score) <= close_margin:
            return True, (
                f"Top candidates are close: "
                f"{int(best_score * 100)}% vs {int(second_score * 100)}%."
            )

    ## Force overwrite with existing non-empty tags
    if force:
        for tag in TEXT_TAGS:
            if current.get(tag, ""):
                return True, "Force mode would overwrite existing tags."

    return False, ""

#####################################################################
## format_candidate
## Returns a formatted single-line string describing a candidate for
## display in the interactive prompt list.
## Format: [N] Artist: X | Title: Y | Album: Z | Year: W | Score: 85% | Source: acoustid
def format_candidate(candidate: dict, index: int) -> str:
    score_pct = int(candidate.get("score", 0.0) * 100)
    artist    = candidate.get("artist",  "") or "(unknown)"
    title     = candidate.get("title",   "") or "(unknown)"
    album     = candidate.get("album",   "") or "(unknown)"
    year      = candidate.get("year",    "") or "????"
    source    = candidate.get("source",  "unknown")
    return (
        f"[{index}] Artist: {artist} | Title: {title} | "
        f"Album: {album} | Year: {year} | "
        f"Score: {score_pct}% | Source: {source}"
    )

#####################################################################
## prompt_candidates
## Displays the file path, reason for prompting, current tags, and
## numbered candidate list using tqdm.write(). Reads user input and
## returns the chosen candidate dict, the string "manual" if the user
## wants to type tags manually, or None to skip the file.
## Handles an empty candidates list (no match found).
def prompt_candidates(
    file_path:  str,
    candidates: list,
    current:    dict,
    reason:     str,
    pbar=None,
) -> dict | str | None:
    SEP = "=" * 70
    P   = "| "

    ## Clear the tqdm bar and use plain print() for all output in this
    ## block — tqdm.write() redraws the bar after every call, which puts
    ## it back before the input() prompt. print() leaves it cleared.
    if pbar is not None:
        pbar.clear()

    print("")
    print(SEP)
    print(f"{P}FILE   : {file_path}")
    print(f"{P}REASON : {reason}")
    print(P)
    print(f"{P}Current tags:")
    has_tags = False
    for tag in TEXT_TAGS:
        val = current.get(tag, "")
        if val:
            print(f"{P}  {tag:<14}: {val}")
            has_tags = True
    if not has_tags:
        print(f"{P}  (none)")

    print(P)
    if not candidates:
        print(f"{P}No candidates found.")
    else:
        print(f"{P}Candidates:")
        for i, cand in enumerate(candidates, start=1):
            print(f"{P}  {format_candidate(cand, i)}")

    print(P)
    print(f"{P}Enter number to select, 'm' for manual entry, or ENTER to skip:")
    try:
        choice = input("> ").strip()
    except (EOFError, KeyboardInterrupt):
        print(f"{P}(interrupted — skipping)")
        print(SEP)
        print("")
        return None

    if not choice:
        print(f"{P}Skipped.")
        print(SEP)
        print("")
        return None

    if choice.lower() == "m":
        print(f"{P}Manual entry selected.")
        print(SEP)
        print("")
        return "manual"

    if choice.isdigit():
        idx = int(choice)
        if 1 <= idx <= len(candidates):
            chosen_cand = candidates[idx - 1]
            print(f"{P}Chosen by user: {format_candidate(chosen_cand, idx)}")
            print(SEP)
            print("")
            return chosen_cand
        print(f"{P}Invalid selection '{choice}' — skipping.")
        print(SEP)
        print("")
        return None

    print(f"{P}Unrecognised input '{choice}' — skipping.")
    print(SEP)
    print("")
    return None

#####################################################################
## prompt_manual_entry
## Prompts the user to type a value for each enabled tag field
## interactively. Shows the current stored value in brackets.
## Empty input means skip (do not write that field). Returns a dict
## of {tag: entered_value} containing only non-empty entries.
def prompt_manual_entry(
    file_path:    str,
    current:      dict,
    enabled_tags: set,
    pbar=None,
) -> dict:
    SEP = "=" * 70
    P   = "| "

    ## Clear the tqdm bar and use plain print() — same reason as
    ## prompt_candidates: tqdm.write() redraws the bar after every call.
    if pbar is not None:
        pbar.clear()

    print(SEP)
    print(f"{P}MANUAL ENTRY : {file_path}")
    print(f"{P}Press ENTER to keep existing value, type a new value to override.")
    print(P)
    result = {}
    for tag in TEXT_TAGS:
        if tag not in enabled_tags:
            continue
        current_val = current.get(tag, "")
        prompt_str  = f"| {tag:<14} [{current_val}]: "
        try:
            entered = input(prompt_str).strip()
        except (EOFError, KeyboardInterrupt):
            print(f"{P}(interrupted)")
            break
        if entered:
            result[tag] = entered
    print(P)
    print(SEP)
    print("")
    return result

#####################################################################
## restore_files
## Reads a restore JSON map file and reverts each file's ID3 tags to
## the values recorded in the "before" snapshot. If the file had no
## cover art before and cover art was added during the run, the APIC
## frame is removed (original image cannot be restored from the map).
## Prints [RESTORED] or [FAILED] per file, followed by a summary.
## If target_file is specified, only that file is restored.
def restore_files(restore_path: str, target_file: str | None) -> None:
    if not os.path.isfile(restore_path):
        print(f"ERROR: Restore map not found: {restore_path}")
        return

    try:
        with open(restore_path, "r", encoding="utf-8") as fh:
            restore_map = json.load(fh)
    except Exception as e:
        print(f"ERROR: Could not read restore map: {e}")
        return

    files_data = restore_map.get("files", {})
    if target_file:
        target_abs = os.path.abspath(target_file)
        files_data = {
            k: v for k, v in files_data.items()
            if os.path.abspath(k) == target_abs
        }
        if not files_data:
            print(f"File not found in restore map: {target_file}")
            return

    restored = 0
    failed   = 0

    for file_path, entry in files_data.items():
        before = entry.get("before", {})
        after  = entry.get("after",  {})

        if not os.path.isfile(file_path):
            print(f"  [FAILED]   {file_path}  (file not found)")
            failed += 1
            continue

        try:
            try:
                audio = ID3(file_path)
            except ID3NoHeaderError:
                audio = ID3()

            ## Restore text tags
            for tag in TEXT_TAGS:
                frame_class = TAG_FRAME_MAP.get(tag)
                if not frame_class:
                    continue
                if tag in ("tracknumber", "totaltracks"):
                    continue
                frame_id = frame_class.__name__
                audio.delall(frame_id)
                old_val = before.get(tag, "")
                if old_val:
                    audio.add(frame_class(encoding=3, text=old_val))

            ## Restore TRCK from tracknumber + totaltracks
            audio.delall("TRCK")
            old_tracknum   = before.get("tracknumber", "")
            old_totaltracks = before.get("totaltracks", "")
            if old_tracknum and old_totaltracks:
                audio.add(TRCK(encoding=3, text=f"{old_tracknum}/{old_totaltracks}"))
            elif old_tracknum:
                audio.add(TRCK(encoding=3, text=old_tracknum))

            ## Handle cover art restoration
            cover_art_was_present = before.get("cover_art", False)
            cover_art_was_added   = after.get("cover_art_added", False)
            if not cover_art_was_present and cover_art_was_added:
                audio.delall("APIC")
                print(f"  [NOTE]     Cover art removed (original image cannot be restored).")

            audio.save(file_path)
            print(f"  [RESTORED] {file_path}")
            restored += 1

        except Exception as e:
            print(f"  [FAILED]   {file_path}  ({e})")
            failed += 1

    print()
    print(f"Restore complete — Restored: {restored}  |  Failed: {failed}")

#####################################################################
## find_latest_restore_map
## Globs restore_*.json files in restore_dir and returns the path of
## the most recent one (by filename sort, which sorts by timestamp
## because the format is restore_YYYYMMDD_HHMMSS.json). Returns None
## if no restore maps are found.
def find_latest_restore_map(restore_dir: str) -> str | None:
    pattern = os.path.join(restore_dir, f"{RESTORE_PREFIX}*.json")
    matches = sorted(glob.glob(pattern))
    if not matches:
        return None
    return matches[-1]

#####################################################################
## save_restore_map
## Writes the restore map dict to a timestamped JSON file in restore_dir.
## Filename format: restore_YYYYMMDD_HHMMSS.json.
## Returns the full path to the written file.
def save_restore_map(restore_map: dict, restore_dir: str) -> str:
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename  = f"{RESTORE_PREFIX}{timestamp}.json"
    out_path  = os.path.join(restore_dir, filename)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(restore_map, fh, indent=2, ensure_ascii=False)
    return out_path

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
## process_file
## Full pipeline for a single MP3 file:
##   1. Read current tags.
##   2. Extract path-based hints.
##   3. Fingerprint → AcoustID → MusicBrainz recording lookups (if key set).
##   4. Text-search fallback if fingerprinting produced no candidates.
##   5. Blend scores: native*0.7 + fuzzy*0.3. Sort and truncate.
##   6. Decide action per mode (auto / semi-auto / confirm).
##   7. Build tag updates from chosen candidate.
##   8. Fetch cover art if enabled and cover not already present (or force).
##   9. Skip if nothing to write.
##  10. Record in restore_map.
##  11. Dry-run: log and return "dryrun".
##  12. Write tags. Log and return "updated".
## Returns status string: "updated", "skipped", "dryrun", "no_match", "failed".
def process_file(
    file_path:   str,
    cfg:         configparser.ConfigParser,
    args:        argparse.Namespace,
    enabled_tags: set,
    restore_map: dict,
    rate_state:  dict,
    pbar:        tqdm,
) -> str:
    ## ----------------------------------------------------------------
    ## Config values
    api_key       = cfg.get("credentials", "acoustid_api_key", fallback="").strip()
    user_agent    = cfg.get("credentials", "musicbrainz_user_agent",
                            fallback="mp3_online_tagger/1.0 (your@email.com)").strip()
    mode          = getattr(args, "mode", "semi-auto")
    confidence    = cfg.getfloat("behavior", "confidence_threshold", fallback=0.85)
    close_margin  = cfg.getfloat("behavior", "close_candidate_margin", fallback=0.05)
    max_candidates = cfg.getint("behavior", "max_candidates", fallback=5)
    fpcalc_path   = cfg.get("paths", "fpcalc_path", fallback="").strip()
    cover_art_cfg  = cfg.getboolean("tags", "cover_art", fallback=True)

    ## CLI overrides for mode
    if getattr(args, "auto", False):
        mode = "auto"
    elif getattr(args, "semi_auto", False):
        mode = "semi-auto"
    elif getattr(args, "confirm", False):
        mode = "confirm"

    ## CLI overrides for cover art
    if getattr(args, "no_cover_art", False):
        cover_art_enabled = False
    elif getattr(args, "cover_art_flag", False):
        cover_art_enabled = True
    else:
        cover_art_enabled = cover_art_cfg

    force   = getattr(args, "force",   False)
    dry_run = getattr(args, "dry_run", False)

    try:
        ## 1. Read current tags
        current = read_tags(file_path)

        ## 2. Extract hints from path
        hints = extract_hints_from_path(file_path)

        ## 3. Fingerprint + AcoustID lookup
        candidates_fp = []
        if api_key:
            fp_result = fingerprint_file(file_path, fpcalc_path)
            if fp_result:
                fingerprint, duration = fp_result
                candidates_fp = query_acoustid(
                    fingerprint, duration, api_key, user_agent,
                    rate_state, enabled_tags, max_candidates,
                )

        ## 4. Always run text search alongside fingerprinting.
        ## Merging both pools lets fuzzy scoring override a wrong AcoustID
        ## match (e.g. fingerprint DB error returning the wrong artist/title).
        candidates_text = query_musicbrainz_text(
            hints, user_agent, rate_state, enabled_tags, max_candidates
        )

        ## 5. Merge pools — deduplicate by recording_id, keep highest native score.
        seen_ids   = {}
        for cand in candidates_fp + candidates_text:
            rid = cand.get("recording_id", "")
            if not rid or rid not in seen_ids:
                seen_ids[rid] = cand
            elif cand.get("score", 0.0) > seen_ids[rid].get("score", 0.0):
                seen_ids[rid] = cand
        candidates = list(seen_ids.values())

        ## 6. Blend and sort: native_score * 0.6 + fuzzy * 0.4.
        ## Giving fuzzy 40% weight means a wrong AcoustID fingerprint match
        ## (low fuzzy) will be beaten by a correct text-search match (high fuzzy).
        for cand in candidates:
            native_score = cand.get("score", 0.0)
            fuzzy_score  = score_candidate(cand, hints)
            cand["score"] = native_score * 0.6 + fuzzy_score * 0.4
        candidates.sort(key=lambda c: c.get("score", 0.0), reverse=True)
        candidates = candidates[:max_candidates]

        ## 6. Decide action
        chosen = None

        if not candidates:
            if mode == "confirm":
                result = prompt_candidates(file_path, [], current, "No candidates found.", pbar)
                if result == "manual":
                    manual_updates = prompt_manual_entry(file_path, current, enabled_tags, pbar)
                    if manual_updates:
                        chosen = manual_updates
            ## Only bail out as no_match if manual entry also yielded nothing
            if not chosen:
                fname = os.path.basename(file_path)
                tqdm.write(f"  [NO MATCH] {fname}")
                restore_map["files"][file_path] = {"status": "no_match", "before": current, "after": {}}
                return "no_match"
            ## else: fall through with chosen set from manual entry

        if mode == "auto":
            chosen = candidates[0]

        elif mode == "confirm":
            result = prompt_candidates(file_path, candidates, current, "Confirm mode — always prompting.", pbar)
            if result == "manual":
                manual_updates = prompt_manual_entry(file_path, current, enabled_tags, pbar)
                chosen = manual_updates if manual_updates else None
            elif result is None:
                restore_map["files"][file_path] = {"status": "skipped", "before": current, "after": {}}
                return "skipped"
            else:
                chosen = result

        else:  ## semi-auto
            do_prompt, reason = should_prompt(candidates, current, force, confidence, close_margin)
            if do_prompt:
                result = prompt_candidates(file_path, candidates, current, reason, pbar)
                if result == "manual":
                    manual_updates = prompt_manual_entry(file_path, current, enabled_tags, pbar)
                    chosen = manual_updates if manual_updates else None
                elif result is None:
                    restore_map["files"][file_path] = {"status": "skipped", "before": current, "after": {}}
                    return "skipped"
                else:
                    chosen = result
            else:
                chosen = candidates[0]

        if not chosen:
            restore_map["files"][file_path] = {"status": "no_match", "before": current, "after": {}}
            return "no_match"

        ## 7. Build updates
        ## chosen may be a raw manual dict (from prompt_manual_entry) or a candidate dict
        if isinstance(chosen, dict) and "score" not in chosen:
            ## Manual entry dict — use directly as updates
            updates = {k: v for k, v in chosen.items() if k in enabled_tags and v}
        else:
            updates = build_updates(chosen, current, force, enabled_tags)

        ## 8. Fetch cover art
        cover_art_data = None
        cover_art_mime = None
        cover_art_added = False

        if cover_art_enabled:
            needs_art = force or not current.get("cover_art", False)
            if needs_art:
                release_id = chosen.get("release_id", "") if isinstance(chosen, dict) else ""
                if release_id:
                    cover_art_data, cover_art_mime = fetch_cover_art(release_id, user_agent)
                    if cover_art_data:
                        cover_art_added = True

        ## 9. Skip if nothing to do
        if not updates and not cover_art_data:
            restore_map["files"][file_path] = {"status": "skipped", "before": current, "after": {}}
            return "skipped"

        ## 10. Record restore entry
        after_record = dict(updates)
        after_record["cover_art_added"] = cover_art_added
        restore_map["files"][file_path] = {
            "status": "updated" if not dry_run else "dryrun",
            "before": current,
            "after":  after_record,
        }

        ## 11. Dry-run
        if dry_run:
            changes_str = ", ".join(
                f'{k}="{v}"' for k, v in updates.items()
            )
            if cover_art_added:
                changes_str += (", cover_art" if changes_str else "cover_art")
            fname = os.path.basename(file_path)
            tqdm.write(f"  [DRY-RUN]  {fname}  |  would set: {changes_str}")
            return "dryrun"

        ## 12. Write
        write_tags(file_path, updates, cover_art_data, cover_art_mime)
        changes_str = ", ".join(f'{k}="{v}"' for k, v in updates.items())
        if cover_art_added:
            changes_str += (", cover_art" if changes_str else "cover_art")
        fname = os.path.basename(file_path)
        tqdm.write(f"  [UPDATED]  {fname}  |  set: {changes_str}")
        return "updated"

    except Exception as e:
        fname = os.path.basename(file_path)
        tqdm.write(f"  [FAILED]   {fname}  |  {e}")
        restore_map["files"][file_path] = {"status": "failed", "before": {}, "after": {}}
        return "failed"

#####################################################################
## main
## Entry point. Parses CLI flags, loads config, handles restore mode,
## collects directories, runs the per-file tqdm pipeline, saves the
## restore map, and prints a run summary.
def main():
    parser = argparse.ArgumentParser(
        prog="mp3_online_tagger.py",
        description=(
            "Fill MP3 metadata by audio fingerprinting (AcoustID/fpcalc) "
            "and online lookup (MusicBrainz). Falls back to text search "
            "when fingerprinting yields no result."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python mp3_online_tagger.py "/music/Beatles/Abbey Road"
  python mp3_online_tagger.py "/music" --recursive --dry-run
  python mp3_online_tagger.py "/music" -r --force --auto
  python mp3_online_tagger.py --restore-last
  python mp3_online_tagger.py --restore restore_20260321_120000.json --file "/music/song.mp3"
        """
    )

    parser.add_argument(
        "paths", nargs="*", metavar="PATH",
        help="Directory path(s) to process. Glob wildcards supported."
    )
    parser.add_argument(
        "-r", "--recursive", action="store_true",
        help="Recurse into subdirectories."
    )

    ## Mode group (mutually exclusive)
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--auto", action="store_true", dest="auto",
        help="Always write best match without prompting."
    )
    mode_group.add_argument(
        "--semi-auto", action="store_true", dest="semi_auto",
        help="Prompt only on low confidence or ambiguity (default)."
    )
    mode_group.add_argument(
        "--confirm", action="store_true", dest="confirm",
        help="Always prompt before writing anything."
    )

    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview changes without writing any files."
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Overwrite existing tags (default: only fill empty tags)."
    )

    ## Cover art group (mutually exclusive)
    art_group = parser.add_mutually_exclusive_group()
    art_group.add_argument(
        "--cover-art", action="store_true", dest="cover_art_flag",
        help="Fetch and embed cover art (overrides config)."
    )
    art_group.add_argument(
        "--no-cover-art", action="store_true", dest="no_cover_art",
        help="Disable cover art embedding (overrides config)."
    )

    parser.add_argument(
        "--config", metavar="FILE", default=None,
        help=f"Path to INI config file (default: {DEFAULT_CONFIG} next to script)."
    )
    parser.add_argument(
        "--acoustid-key", metavar="KEY", default=None,
        help="AcoustID API key (overrides config)."
    )
    parser.add_argument(
        "--user-agent", metavar="STRING", default=None,
        help="MusicBrainz User-Agent string (overrides config)."
    )
    parser.add_argument(
        "--file", metavar="MP3_PATH", default=None,
        help="Single file to target (only used with --restore / --restore-last)."
    )

    ## Restore group (mutually exclusive)
    restore_group = parser.add_mutually_exclusive_group()
    restore_group.add_argument(
        "--restore", metavar="FILE", default=None,
        help="Path to restore map JSON to revert tags from."
    )
    restore_group.add_argument(
        "--restore-last", action="store_true",
        help="Automatically find and use the most recent restore map."
    )

    args = parser.parse_args()

    ## --file is only valid with restore flags
    if args.file and not (args.restore or args.restore_last):
        parser.error("--file can only be used with --restore or --restore-last.")

    ## ----------------------------------------------------------------
    ## Load config
    if args.config:
        config_path = args.config
    else:
        script_dir  = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(script_dir, DEFAULT_CONFIG)

    cfg = load_config(config_path)

    ## Apply CLI credential overrides
    if args.acoustid_key:
        if not cfg.has_section("credentials"):
            cfg.add_section("credentials")
        cfg.set("credentials", "acoustid_api_key", args.acoustid_key)

    if args.user_agent:
        if not cfg.has_section("credentials"):
            cfg.add_section("credentials")
        cfg.set("credentials", "musicbrainz_user_agent", args.user_agent)

    ## ----------------------------------------------------------------
    ## Determine restore dir
    restore_dir_cfg = cfg.get("paths", "restore_dir", fallback="").strip()
    if restore_dir_cfg:
        restore_dir = restore_dir_cfg
    else:
        restore_dir = os.path.dirname(os.path.abspath(__file__))

    ## ----------------------------------------------------------------
    ## Handle restore mode
    if args.restore or args.restore_last:
        if args.restore_last:
            restore_path = find_latest_restore_map(restore_dir)
            if not restore_path:
                print(f"ERROR: No restore maps found in: {restore_dir}")
                raise SystemExit(1)
            print(f"Using latest restore map: {restore_path}")
        else:
            restore_path = args.restore

        restore_files(restore_path, args.file)
        return

    ## ----------------------------------------------------------------
    ## Normal processing mode

    ## Determine effective mode string for display
    if args.auto:
        effective_mode = "auto"
    elif args.confirm:
        effective_mode = "confirm"
    else:
        effective_mode = cfg.get("behavior", "mode", fallback="semi-auto")
        if args.semi_auto:
            effective_mode = "semi-auto"
    args.mode = effective_mode

    ## Cover art startup confirmation
    cover_art_cfg     = cfg.getboolean("tags", "cover_art", fallback=True)
    cover_art_enabled = cover_art_cfg
    if args.no_cover_art:
        cover_art_enabled = False
    elif args.cover_art_flag:
        cover_art_enabled = True

    if cover_art_enabled and not args.dry_run:
        print()
        print("Cover art embedding is enabled.")
        print("This will download images from the Cover Art Archive for matched releases.")
        try:
            confirm = input("Proceed with cover art downloads? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            confirm = "n"
        if confirm not in ("y", "yes"):
            print("Cover art disabled for this run.")
            args.no_cover_art = True

    ## AcoustID key warning
    api_key = cfg.get("credentials", "acoustid_api_key", fallback="").strip()
    if not api_key:
        print()
        print("WARNING: No AcoustID API key configured. Fingerprinting disabled.")
        print("         Text search only. Register at https://acoustid.org/api-key")

    ## Mode / dry-run / force banners
    print()
    print(f"[MODE: {effective_mode.upper()}]")
    if args.dry_run:
        print("[DRY-RUN MODE -- no files will be modified]")
    if args.force:
        print("[FORCE MODE -- existing tags will be overwritten]")

    ## ----------------------------------------------------------------
    ## Collect files
    if not args.paths:
        parser.error("At least one PATH is required (or use --restore / --restore-last).")

    directories = collect_directories(args.paths, args.recursive)

    if not directories:
        print("ERROR: No valid directories found.")
        raise SystemExit(1)

    all_files = []
    for directory in directories:
        try:
            mp3_files = sorted(
                os.path.join(directory, f)
                for f in os.listdir(directory)
                if f.lower().endswith(".mp3")
            )
            all_files.extend(mp3_files)
        except OSError as e:
            print(f"WARNING: Cannot read directory '{directory}': {e}")

    if not all_files:
        print("ERROR: No MP3 files found.")
        raise SystemExit(1)

    print(f"\nFound {len(all_files)} MP3 file(s) across {len(directories)} director(y/ies).\n")

    ## ----------------------------------------------------------------
    ## Processing loop
    enabled_tags = get_enabled_tags(cfg)
    restore_map  = {"created": datetime.datetime.now().isoformat(), "files": {}}
    rate_state   = {}
    counts       = {"updated": 0, "skipped": 0, "dryrun": 0, "no_match": 0, "failed": 0}

    with tqdm(total=len(all_files), unit="file", leave=False) as pbar:
        for file_path in all_files:
            short_name = os.path.basename(file_path)[:40]
            pbar.set_description(short_name)

            status = process_file(
                file_path, cfg, args, enabled_tags, restore_map, rate_state, pbar
            )
            counts[status] = counts.get(status, 0) + 1
            pbar.update(1)

    ## Move cursor past the tqdm bar so summary prints on a clean line
    print()

    ## ----------------------------------------------------------------
    ## Save restore map
    restore_path = save_restore_map(restore_map, restore_dir)

    ## ----------------------------------------------------------------
    ## Summary
    print()
    print("=" * 50)
    print("Summary")
    print("=" * 50)
    if args.dry_run:
        print(f"  Would update : {counts['dryrun']}")
    else:
        print(f"  Updated      : {counts['updated']}")
    print(f"  Skipped      : {counts['skipped']}")
    print(f"  No match     : {counts['no_match']}")
    print(f"  Failed       : {counts['failed']}")
    print(f"  Restore map  : {restore_path}")
    print()

#####################################################################
## entry point
if __name__ == "__main__":
    main()
