# mp3_metadata_from_path

A Python utility for bulk-tagging MP3 files with album, artist, title, and track number derived from the directory structure and filenames. Supports dry-run, recursive mode, force overwrite, filename pattern parsing (`--name-info`), and a per-run summary.

## Background

When ripping music from physical CDs or downloading albums, the resulting MP3 files often carry no metadata. Car stereos, media players, and music libraries all display "Unknown Artist / Unknown Album" instead of the actual track information. Manually tagging hundreds of files is tedious and error-prone.

This script automates the process by reading the information that is already implicit in a well-organised folder structure:

```
/music/Beatles/Abbey Road/01 - Come Together.mp3
         ↑         ↑        ↑      ↑
       artist    album   track#  title
```

It reads every MP3 in one or more directories, extracts tags from the folder names and filenames, and writes them into the ID3 tag block of each file — skipping any tag that is already filled unless `--force` is used.

---

## How It Works

1. One or more directory paths are provided as arguments (glob wildcards supported)
2. Optionally recurses into all subdirectories that contain MP3 files (`--recursive`)
3. For each directory, derives `album` from the folder name and `artist` from the parent folder name
4. For each MP3 file, extracts `title` and `tracknumber` from the filename stem
5. Optionally overrides any or all of these values using `--artist`, `--album`, or `--name-info`
6. Compares desired values against what is already stored in the file:
   - Default mode: only fills tags that are currently **empty**
   - `--force` mode: overwrites any tag whose stored value differs from the desired value
7. In `--dry-run` mode: prints what would change without writing anything
8. Prints a per-directory log and a run summary at the end

---

## Requirements

### Python version

Python 3.7 or later.

### Python packages

| Package | Purpose | Install |
|---------|---------|---------|
| `mutagen` | Reading and writing MP3 ID3 tags | `pip install mutagen` |

All other imports (`os`, `re`, `glob`, `argparse`) are part of the Python standard library and require no installation.

#### Install with pip

```bash
pip install mutagen
```

#### Install in a virtual environment (recommended)

```bash
python -m venv venv
source venv/bin/activate        # Linux / macOS
venv\Scripts\activate           # Windows
pip install mutagen
```

#### Install from a requirements file

A `requirements.txt` for this project contains:

```
mutagen
```

Install with:

```bash
pip install -r requirements.txt
```

---

## Parameters

| Argument / Flag | Default | Description |
|-----------------|---------|-------------|
| `PATH` (positional, one or more) | — | Directory path(s) to process. Glob wildcards supported. |
| `-r`, `--recursive` | off | Recurse into subdirectories and process every folder containing MP3 files. |
| `--dry-run` | off | Preview tag changes without writing any files. |
| `--force` | off | Overwrite existing tags. Default: only fill tags that are currently empty. |
| `--artist NAME` | Parent folder name | Override the artist tag for all processed files. |
| `--album NAME` | Folder name | Override the album tag for all processed files. When combined with `--recursive`, every folder receives the same value. |
| `--name-info PATTERN` | — | Extract tags from filenames using a pattern. See **`--name-info` Pattern Syntax** below. |

---

## Default Tag Sources

When `--name-info` is not used, tags are derived as follows:

| Tag | Source |
|-----|--------|
| `album` | Name of the folder being processed |
| `artist` | Name of the parent folder |
| `title` | Filename with the leading track number stripped |
| `tracknumber` | Leading number in the filename (1–3 digits) |

### Supported filename patterns for track number detection

| Filename | Track # | Title |
|----------|---------|-------|
| `01 - Come Together.mp3` | `01` | `Come Together` |
| `01. Come Together.mp3` | `01` | `Come Together` |
| `01_Come Together.mp3` | `01` | `Come Together` |
| `01 Come Together.mp3` | `01` | `Come Together` |
| `Come Together.mp3` | *(not set)* | `Come Together` |

---

## `--name-info` Pattern Syntax

Use `--name-info` when the tags you need are encoded in the filename itself rather than (or in addition to) the folder structure.

### Format

```
TOKEN||DELIM||TOKEN||DELIM||TOKEN
```

- The pattern must have an **odd number** of `||`-separated parts
- **Even-index parts** (0, 2, 4, …) are **token names** (tags to extract)
- **Odd-index parts** (1, 3, 5, …) are **literal delimiters** to split on (include spaces if needed)
- Splits happen **left-to-right on the first occurrence** of each delimiter
- Tags not covered by the pattern fall back to the directory structure

### Valid tokens

| Token | Tag written |
|-------|------------|
| `TITLE` or `TRACK` | `title` |
| `ALBUM` | `album` |
| `ARTIST` | `artist` |
| `TRACKNUM` or `NUM` | `tracknumber` |

### Precedence

`--name-info` takes precedence over `--artist` and `--album` for any tag it explicitly extracts. Tags not covered by the pattern still use the directory-derived values (or the `--artist` / `--album` overrides).

### WARNING: leading track numbers and the TRACK token

If your filenames start with a track number (e.g. `01 - Come Together - Abbey Road.mp3`) and you start your pattern with `TRACK`, the first split will grab `"01"` as the title.

**Correct approach:** use `TRACKNUM` as the first token instead:

```
--name-info "TRACKNUM|| - ||TRACK|| - ||ALBUM"
```

This maps `"01"` → `tracknumber`, `"Come Together"` → `title`, `"Abbey Road"` → `album`.

### Pattern examples

| Pattern | Filename | Result |
|---------|----------|--------|
| `TRACK\|\| - \|\|ALBUM` | `Come Together - Abbey Road.mp3` | title=`Come Together`, album=`Abbey Road` |
| `ARTIST\|\| - \|\|TRACK` | `Beatles - Come Together.mp3` | artist=`Beatles`, title=`Come Together` |
| `ARTIST\|\| - \|\|TRACK\|\| - \|\|ALBUM` | `Beatles - Come Together - Abbey Road.mp3` | artist=`Beatles`, title=`Come Together`, album=`Abbey Road` |
| `TRACKNUM\|\|. \|\|TRACK\|\| - \|\|ALBUM` | `01. Come Together - Abbey Road.mp3` | tracknumber=`01`, title=`Come Together`, album=`Abbey Road` |

---

## Fill-if-missing vs `--force`

### Default (fill-if-missing)

Only writes a tag if the file does not already have a value for it. Existing tags are never touched. Safe to re-run multiple times — files that are already fully tagged are skipped.

### `--force`

Overwrites any tag whose stored value differs from the desired value. Use this when you want to correct previously written tags or standardise naming across a batch.

---

## Dry-run Mode (`--dry-run`)

Prints what would be changed without writing anything to disk. Useful for verifying patterns and checking which files would be updated before committing to a run.

`--dry-run` and `--force` can be combined to preview what a force-overwrite run would change.

---

## Example Runs

### Single directory — fill missing tags from folder structure

```bash
python mp3_metadata_from_path.py "/music/Beatles/Abbey Road"
```

---

### Preview changes without writing (dry run)

```bash
python mp3_metadata_from_path.py "/music/Beatles/Abbey Road" --dry-run
```

---

### All albums by one artist — recursive

```bash
python mp3_metadata_from_path.py "/music/Beatles" --recursive
```

Processes every subdirectory under `/music/Beatles` that contains MP3 files. Album is derived from each subfolder name; artist is derived from the parent (`Beatles`).

---

### Entire music library — recursive

```bash
python mp3_metadata_from_path.py "/music" --recursive
```

---

### Glob wildcard — multiple artist folders at once

```bash
python mp3_metadata_from_path.py "/music/B*" --recursive --dry-run
```

---

### Override artist and album manually

```bash
python mp3_metadata_from_path.py "/music/misc_rips" --artist "The Beatles" --album "Abbey Road"
```

---

### Extract artist and title from filenames

Filenames: `Beatles - Come Together.mp3`, `Beatles - Something.mp3`

```bash
python mp3_metadata_from_path.py "/music/Abbey Road" --name-info "ARTIST|| - ||TRACK"
```

Result: artist=`Beatles`, title from filename, album from folder name.

---

### Extract all three tags from filenames

Filenames: `Beatles - Come Together - Abbey Road.mp3`

```bash
python mp3_metadata_from_path.py "/music/rips" --name-info "ARTIST|| - ||TRACK|| - ||ALBUM"
```

Result: artist=`Beatles`, title=`Come Together`, album=`Abbey Road`.

---

### Files with a leading track number, title, and album

Filenames: `01. Come Together - Abbey Road.mp3`

```bash
python mp3_metadata_from_path.py "/music/rips" --name-info "TRACKNUM||. ||TRACK|| - ||ALBUM"
```

Result: tracknumber=`01`, title=`Come Together`, album=`Abbey Road`.

---

### Force-overwrite to correct existing tags

```bash
python mp3_metadata_from_path.py "/music/Beatles" --recursive --force
```

---

### Force-overwrite with dry-run to preview corrections

```bash
python mp3_metadata_from_path.py "/music/Beatles" --recursive --force --dry-run
```

---

## Example Output

### Normal run

```
----------------------------------------
Directory : /music/Beatles/Abbey Road
Album     : Abbey Road
Artist    : Beatles
----------------------------------------
  [UPDATED]  01 - Come Together.mp3  |  set: title="Come Together", tracknumber="01"
  [SKIP]     02 - Something.mp3
  [UPDATED]  03 - Maxwell's Silver Hammer.mp3  |  set: title="Maxwell's Silver Hammer", tracknumber="03"

========================================
Summary
========================================
  Updated      : 2
  Skipped      : 1
  Failed       : 0
```

---

### Dry-run output

```
[DRY-RUN MODE -- no files will be modified]

----------------------------------------
Directory : /music/Beatles/Abbey Road
Album     : Abbey Road
Artist    : Beatles
----------------------------------------
  [DRY-RUN]  01 - Come Together.mp3  |  would set: title="Come Together", tracknumber="01"
  [DRY-RUN]  02 - Something.mp3  |  would set: title="Something", tracknumber="02"

========================================
Summary
========================================
  Would update : 2
  Skipped      : 0
  Failed       : 0
```

---

### Pattern miss — fallback to directory values

When a `--name-info` pattern does not match a filename (delimiter not found), the file is processed using directory-derived values and a note is appended:

```
  [UPDATED]  come_together.mp3  |  set: title="come_together"  (pattern not matched — used directory values)
```

---

## Notes

- Only `.mp3` files are processed; other audio formats in the same folder are ignored
- Files are processed in alphabetical order within each directory
- A tag is never written as an empty string — if a value cannot be derived it is silently omitted
- `--recursive` skips subdirectories that contain no MP3 files
- Glob wildcards in `PATH` are expanded before processing; duplicate directories (e.g. via symlinks) are de-duplicated automatically
- When `--album` is combined with `--recursive`, every subdirectory receives the same album value — use this only when all subdirectories belong to the same album
