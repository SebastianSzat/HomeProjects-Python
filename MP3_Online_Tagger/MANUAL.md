# mp3_online_tagger — Manual

Full reference for `mp3_online_tagger.py`.

For background and a quick introduction see [README.md](./README.md).

---

## Table of Contents

1. [Installation](#installation)
2. [Configuration File (INI)](#configuration-file-ini)
3. [Command-Line Arguments](#command-line-arguments)
4. [Operating Modes](#operating-modes)
5. [How Candidates Are Found and Scored](#how-candidates-are-found-and-scored)
6. [Interactive Prompt](#interactive-prompt)
7. [Cover Art](#cover-art)
8. [Restore System](#restore-system)
9. [Dry-Run Mode](#dry-run-mode)
10. [Output and Status Codes](#output-and-status-codes)
11. [Test Environment Setup](#test-environment-setup)
12. [Troubleshooting](#troubleshooting)

---

## Installation

### Python packages

```bash
pip install -r requirements.txt
```

Contents of `requirements.txt`:

```
mutagen
requests
rapidfuzz
tqdm
```

Install in a virtual environment (recommended):

```bash
python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate     # Linux / macOS
pip install -r requirements.txt
```

### fpcalc (Chromaprint)

fpcalc is an external binary that generates acoustic fingerprints from audio files. It is required for AcoustID lookups. Without it the script falls back to text search only — this still works but is less accurate, particularly for files with ambiguous or missing filename information.

**Windows:**

1. Download the Windows ZIP from https://acoustid.org/chromaprint
2. Extract `fpcalc.exe` to any folder (e.g. `C:\Tools\fpcalc\`)
3. Either add that folder to your system PATH, or set the full path in the INI config:
   ```ini
   fpcalc_path = C:\Tools\fpcalc\fpcalc.exe
   ```

**Ubuntu / Debian:**

```bash
sudo apt install libchromaprint-utils
```

**macOS (Homebrew):**

```bash
brew install chromaprint
```

After installing, verify it works:

```bash
fpcalc --version
```

### AcoustID API key

1. Register at https://acoustid.org/api-key (free, requires only an email address)
2. Copy the key into the INI config under `[credentials]` → `acoustid_api_key`

Without an API key, AcoustID fingerprint lookups are skipped entirely. The script will still run using text search only.

---

## Configuration File (INI)

On first run the script creates `mp3_online_tagger.ini` in the current directory with every field present and documented by inline comments. A different config path can be specified with `--config`.

### `[credentials]`

| Key | Description |
|-----|-------------|
| `acoustid_api_key` | Your AcoustID API key. Required for fingerprint lookups. |
| `musicbrainz_user_agent` | User-Agent string sent to MusicBrainz. Required by the MusicBrainz API policy. Format: `AppName/Version (your@email.com)`. |

### `[behavior]`

| Key | Default | Description |
|-----|---------|-------------|
| `mode` | `semi-auto` | Operating mode: `semi-auto`, `confirm`, or `auto`. See [Operating Modes](#operating-modes). |
| `confidence_threshold` | `0.85` | In `semi-auto` mode, candidates with a blended score above this value are written automatically. Range: `0.0`–`1.0`. |
| `max_candidates` | `5` | Maximum number of candidates to present when prompting the user. |
| `close_candidate_margin` | `0.05` | If the top two candidates are within this score margin of each other, the user is prompted even if the top score exceeds `confidence_threshold`. Prevents silent auto-writes when two results are nearly tied. |

### `[tags]`

Controls which metadata fields are written. Each key accepts `true` or `false`.

| Key | Default | Tag written |
|-----|---------|-------------|
| `title` | `true` | Track title |
| `artist` | `true` | Track artist |
| `album` | `true` | Album name |
| `tracknumber` | `true` | Track number |
| `year` | `true` | Release year |
| `genre` | `true` | Genre |
| `albumartist` | `true` | Album artist (used when the track artist differs from the release artist, e.g. compilations) |
| `composer` | `false` | Composer |
| `discnumber` | `false` | Disc number |
| `totaltracks` | `false` | Total number of tracks on the disc |
| `cover_art` | `true` | Download and embed front cover art from the Cover Art Archive |

### `[paths]`

| Key | Description |
|-----|-------------|
| `fpcalc_path` | Full path to the `fpcalc` binary. Leave empty if `fpcalc` is on your system PATH. |
| `restore_dir` | Directory where restore map JSON files are saved. Defaults to a `restore/` subfolder next to the script. |

### Full example config

```ini
[credentials]
acoustid_api_key = your-key-here
musicbrainz_user_agent = mp3_online_tagger/1.0 (your@email.com)

[behavior]
mode = semi-auto
confidence_threshold = 0.85
max_candidates = 5
close_candidate_margin = 0.05

[tags]
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
cover_art   = true

[paths]
fpcalc_path =
restore_dir =
```

---

## Command-Line Arguments

| Argument / Flag | Default | Description |
|-----------------|---------|-------------|
| `PATH` (positional, one or more) | — | One or more directory paths containing MP3 files. Glob wildcards supported. |
| `-r`, `--recursive` | off | Recurse into all subdirectories that contain MP3 files. |
| `--config FILE` | `mp3_online_tagger.ini` | Path to the INI configuration file. |
| `--dry-run` | off | Preview what would be changed without writing any files. |
| `--force` | off | Overwrite tags that are already set. Default: only fill tags that are currently empty or missing. |
| `--mode MODE` | INI value | Override the operating mode for this run without changing the config: `semi-auto`, `confirm`, or `auto`. |
| `--restore FILE` | — | Restore all files listed in the specified restore map JSON file. |
| `--restore-last` | — | Find the most recent restore map in `restore_dir` and restore from it. |
| `--file FILE` | — | When used with `--restore` or `--restore-last`, restore only the specified file instead of all files in the map. |

### Combining restore flags

```bash
# Undo the entire last run
python mp3_online_tagger.py --restore-last

# Undo just one track from the last run
python mp3_online_tagger.py --restore-last --file "path/to/track.mp3"

# Undo from a specific restore file
python mp3_online_tagger.py --restore restore/restore_20260321_212222.json

# Undo one track from a specific restore file
python mp3_online_tagger.py --restore restore/restore_20260321_212222.json --file "path/to/track.mp3"
```

---

## Operating Modes

### `semi-auto` (default)

The most practical mode for general use. The script writes the best candidate automatically when confident, and only interrupts when it is not sure.

Auto-write happens when:
- The top blended score is at or above `confidence_threshold`, **and**
- The top two candidates are not within `close_candidate_margin` of each other

The user is prompted when:
- The top score is below `confidence_threshold`
- The top two candidates are too close to call (within `close_candidate_margin`)
- No candidates were found (skip is offered; manual entry is not offered in this mode)

### `confirm`

The user is prompted for every file without exception, regardless of the confidence score. Useful for reviewing an entire album before committing, or for collections where automatic scoring cannot be trusted (e.g. unusual genres, live recordings, bootlegs).

When no candidates are found in `confirm` mode, the script offers manual entry rather than silently skipping.

### `auto`

The top-scoring candidate is always written automatically, with no prompts. Use with care — fingerprint databases can return incorrect results, and `auto` mode will write those results silently.

Recommended only for large collections of commercially released albums where AcoustID coverage is reliable, combined with `--dry-run` first to check results.

### Overriding the mode for a single run

```bash
python mp3_online_tagger.py "path/to/album" --mode confirm
```

The `--mode` flag overrides the INI setting without modifying the config file.

---

## How Candidates Are Found and Scored

### Step 1 — Extract filename hints

For each file the script parses the filename and surrounding folder structure to build an initial set of hints used for text search and scoring.

**Folder structure:**

- If the album folder name matches the pattern `Artist - Album` (e.g. `Powerwolf - Bible Of The Beast`), artist and album are read directly from it.
- Otherwise the folder name is treated as the album and the parent folder as the artist.

**Filename:**

- A leading track number (1–3 digits optionally followed by `.`, `-`, or a space) is extracted as `tracknumber`.
- If the filename contains `Artist - Title` and the artist matches the folder-derived artist, the artist prefix is stripped to leave a clean title.

### Step 2 — AcoustID fingerprint lookup

If `fpcalc` is available and an API key is configured:

1. `fpcalc` reads the audio file and outputs a binary fingerprint and duration.
2. The fingerprint is submitted to the AcoustID API (`https://api.acoustid.org/v2/lookup`).
3. AcoustID returns a list of MusicBrainz recording IDs with confidence scores (0.0–1.0).
4. Each recording ID is looked up in the MusicBrainz API (`/recording/{id}?inc=releases+artist-credits+genres`) to retrieve the full tag set.

AcoustID requests are rate-limited to one every 0.35 seconds. MusicBrainz requests are rate-limited to one every 1.1 seconds (API policy requires a maximum of 1 per second).

### Step 3 — MusicBrainz text search

A Lucene-style query is sent to the MusicBrainz search API:

```
/recording/?query=recording:"<title>" AND artist:"<artist>"
```

This runs for every file regardless of whether fingerprinting succeeded. MusicBrainz returns candidates with its own relevance scores.

### Step 4 — Merge and deduplicate

Both candidate pools (fingerprint results and text search results) are combined. Where the same MusicBrainz recording ID appears in both pools, the entry with the higher native score is kept.

### Step 5 — Blended scoring

Each candidate receives a blended score:

```
blended_score = native_score × 0.6 + fuzzy_score × 0.4
```

- **native_score** — AcoustID confidence or MusicBrainz relevance, normalised to 0.0–1.0.
- **fuzzy_score** — fuzzy string similarity between the candidate's tags and the filename hints, weighted as: title 50%, artist 35%, album 15%.

The 40% fuzzy weight means a fingerprint match that is wrong (and therefore scores poorly on fuzzy) can be outscored by a correct text-search match (which scores well on fuzzy). This corrects for cases where the AcoustID database itself contains an error for a particular recording.

Candidates are sorted descending by blended score and truncated to `max_candidates`.

---

## Interactive Prompt

When user input is required the progress bar is cleared and a bordered block is printed:

```
======================================================================
| FILE   : test_env\Powerwolf - Bible Of The Beast\04 Powerwolf - Panic In The Pentagram.mp3
| REASON : Top candidates are close: 100% vs 99%.
|
| Current tags:
|   (none)
|
| Candidates:
|   [1] Artist: Powerwolf | Title: Panic in the Pentagram | Album: Bible of the Beast | Year: 2009 | Score: 100% | Source: musicbrainz_text
|   [2] Artist: Powerwolf | Title: Panic in the Pentagram | Album: Bible of the Beast | Year: 2009 | Score: 99%  | Source: acoustid
|
| Enter number to select, 'm' for manual entry, or ENTER to skip:
> 1
| Chosen by user: [1] Artist: Powerwolf | Title: Panic in the Pentagram | Album: Bible of the Beast | Year: 2009 | Score: 100% | Source: musicbrainz_text
======================================================================

  [UPDATED]  04 Powerwolf - Panic In The Pentagram.mp3  |  set: ...
```

The progress bar resumes automatically when the loop continues to the next file.

### Input options

| Input | Action |
|-------|--------|
| `1`, `2`, … | Select that numbered candidate and write its tags |
| `m` | Open manual entry — enter each field interactively |
| ENTER | Skip this file — no tags are written |

### Prompt reasons

| Reason shown | Cause |
|---|---|
| `Low confidence (N% < threshold%)` | Top blended score is below `confidence_threshold` |
| `Top candidates are close: N% vs M%` | Top two candidates are within `close_candidate_margin` |
| `No candidates found.` | Neither AcoustID nor text search returned any results (`confirm` mode only) |
| `Confirm mode — always prompting.` | Running in `confirm` mode |

### Manual entry

Pressing `m` opens the manual entry block. Each enabled tag field is prompted individually. The current stored value (if any) is shown in square brackets. Press ENTER to keep the existing value; type a new value to replace it.

```
======================================================================
| MANUAL ENTRY : test_env\Powerwolf - Bible Of The Beast\Unknown.mp3
| Press ENTER to keep existing value, type a new value to override.
|
| title          []: Raise Your Fist Evangelist
| artist         []: Powerwolf
| album          []: Bible of the Beast
| tracknumber    []: 02
| year           []: 2009
| genre          []: power metal
| albumartist    []: Powerwolf
|
======================================================================
```

Only fields where a value was typed are written. Pressing ENTER on an empty field leaves it unchanged — the script never writes an empty string into a tag.

---

## Cover Art

When `cover_art = true` in the INI config, the script downloads the front cover image from the [Cover Art Archive](https://coverartarchive.org) for each matched release and embeds it as an APIC (Attached Picture) ID3 frame.

### Confirmation prompt

At the start of each run (when cover art is enabled in the config) a confirmation is shown:

```
Cover art embedding is enabled.
This will download images from the Cover Art Archive for matched releases.
Proceed with cover art downloads? [y/N]:
```

Answering `n` disables cover art for that run only. The INI config is not changed.

### Force overwrite

If a file already has embedded cover art, it is only overwritten when `--force` is used.

### Missing cover art

Some releases have no image in the Cover Art Archive. When a cover cannot be fetched the script continues without it — no error is raised and the other tags are still written.

---

## Restore System

Every run (including `--dry-run`) saves a JSON restore map to `restore_dir`. The file is named `restore_YYYYMMDD_HHMMSS.json`.

### Restore map structure

```json
{
  "run_started": "2026-03-21T21:22:35",
  "files": {
    "path/to/track.mp3": {
      "status": "updated",
      "before": {
        "title": "",
        "artist": "",
        "album": ""
      },
      "after": {
        "title": "Panic in the Pentagram",
        "artist": "Powerwolf",
        "album": "Bible of the Beast"
      }
    }
  }
}
```

The `before` snapshot records the exact tag values at the time the script ran. Restoring a file writes the `before` values back. Tags that were empty before the run are cleared.

### Restore commands

```bash
# Undo the entire last run
python mp3_online_tagger.py --restore-last --config myconfig.ini

# Undo from a specific restore file
python mp3_online_tagger.py --restore restore/restore_20260321_212222.json

# Undo just one track from the last run
python mp3_online_tagger.py --restore-last --file "path/to/track.mp3" --config myconfig.ini

# Undo just one track from a specific restore file
python mp3_online_tagger.py --restore restore/restore_20260321_212222.json --file "path/to/track.mp3"
```

### Restore directory

The default `restore_dir` is a `restore/` subfolder next to the script. It is created automatically on first run. The path can be overridden in the INI config — useful when running against a test environment.

---

## Dry-Run Mode

`--dry-run` reports exactly what the script would do without writing any files.

```bash
python mp3_online_tagger.py "path/to/album" --dry-run
```

- All output lines are prefixed with `[DRY-RUN]` instead of `[UPDATED]`
- Interactive prompts still appear in `semi-auto` and `confirm` modes
- The restore map is still written as a preview of what would have changed

Combining with `--force` shows what a force-overwrite run would change:

```bash
python mp3_online_tagger.py "path/to/album" --dry-run --force
```

Always run with `--dry-run` first when tagging a new collection or testing a new config.

---

## Output and Status Codes

Each processed file produces one output line:

| Prefix | Meaning |
|--------|---------|
| `[UPDATED]` | Tags were written successfully |
| `[SKIP]` | File already has all requested tags and `--force` was not used |
| `[DRY-RUN]` | Would be updated; no write performed |
| `[NO MATCH]` | No candidate found and no manual entry was provided |
| `[FAILED]` | An error occurred while reading or writing the file |

### Summary block

Printed at the end of every run:

```
==================================================
Summary
==================================================
  Updated      : 12
  Skipped      : 1
  No match     : 0
  Failed       : 0
  Restore map  : C:\...\restore\restore_20260321_212222.json
```

In dry-run mode `Updated` is replaced by `Would update`.

---

## Test Environment Setup

It is strongly recommended to test against a copy of your files before running on originals. The following steps describe a safe isolated test environment.

### 1. Copy a test album

```bash
# Windows (PowerShell)
Copy-Item -Recurse "C:\Music\Artist\Album" "C:\test_env\Album"

# Linux / macOS
cp -r "/music/Artist/Album" "/tmp/test_env/Album"
```

### 2. Clean the metadata (optional)

Run [MP3_Metadata_Cleaner](../MP3_Metadata_Cleaner/) against the test copy to simulate files with no existing tags, matching the real-world starting condition.

### 3. Create a test config

Copy your main INI file and adjust `restore_dir` to point inside the test environment folder so restore maps do not mix with production runs:

```ini
restore_dir = C:\test_env\restore
```

### 4. Dry run

```bash
python mp3_online_tagger.py "C:\test_env\Album" --config test_env\mytest.ini --dry-run
```

Review the output. Verify titles, artists, and albums look correct.

### 5. Run for real

```bash
python mp3_online_tagger.py "C:\test_env\Album" --config test_env\mytest.ini
```

### 6. Restore if needed

```bash
python mp3_online_tagger.py --restore-last --config test_env\mytest.ini
```

---

## Troubleshooting

### All files return NO MATCH

- Verify that your AcoustID API key is correct and active at https://acoustid.org
- Check that `fpcalc_path` in the INI points to the actual binary file, not just its containing directory
- Confirm the filenames follow a recognisable pattern (e.g. `01 Artist - Title.mp3`) so text search has useful hints to work with
- Run with `--dry-run` and check terminal output for API error messages

### Wrong track identified

The AcoustID database occasionally contains errors — a fingerprint may match the wrong recording. The script mitigates this by weighting the blended score 40% on fuzzy filename similarity, so a wrong fingerprint match will lose to a correct text-search result when the filename is informative. If misidentification still occurs:

- Lower `confidence_threshold` (e.g. to `0.75`) so the script prompts instead of auto-writing
- Switch to `confirm` mode to review every result manually
- Rename the file to include the correct artist and title before tagging — the text search will then score the right result highly

### MusicBrainz 503 / rate limit errors

MusicBrainz enforces a hard limit of 1 request per second. The script enforces a 1.1-second delay between calls. 503 responses during normal operation indicate the server is temporarily overloaded — wait a moment and re-run; the restore system means you can safely re-run from where you left off.

### Cover art not embedding

- Confirm `cover_art = true` in the INI config
- Answer `y` at the confirmation prompt at the start of the run
- If the file already has embedded cover art, use `--force` to overwrite it
- Some releases have no image in the Cover Art Archive — the script skips those silently; this is not an error

### fpcalc not found

If the script logs that fpcalc could not be found, either:

- Add the folder containing `fpcalc.exe` / `fpcalc` to your system PATH, or
- Set the full path explicitly in the INI:
  ```ini
  fpcalc_path = C:\Tools\fpcalc\fpcalc.exe
  ```

### Progress bar renders incorrectly on Windows

The legacy `cmd.exe` prompt has limited ANSI support. Run the script in **Windows Terminal** or the **VS Code integrated terminal** for correct rendering.
