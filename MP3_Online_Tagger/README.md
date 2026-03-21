# mp3_online_tagger

A Python script that identifies MP3 files using audio fingerprinting and online music databases, and fills in their ID3 metadata tags automatically.

For full documentation see [MANUAL.md](./MANUAL.md).

---

## Background

In early 2025 I helped my landlord digitise his music collection. He had a large stack of old CDs and a new car radio that could play MP3s from a USB stick (but no CD player) — the problem was getting the files onto that stick with proper metadata so the radio could display artist and album names instead of a wall of `Unknown Album - Unknown Track / Unknown Artist`.

The ripping process produced files, but the metadata situation was a mess. Some discs had no embedded tags at all, others had partial or garbled information from whoever encoded them years ago. So I built a small tool to strip it all out and start clean: [MP3_Metadata_Cleaner](../MP3_Metadata_Cleaner/).

With a clean slate, the next step was filling the tags back in. Most of the albums were ripped into a tidy folder structure — `Artist/Album/01 - Track.mp3` — so I built a second script that reads the folder and filename structure and derives the metadata from it: [mp3_metadata_from_path](../MP3_metadata_from_path/).

That covered the bulk of the collection, but there were always awkward cases: files with no meaningful folder structure, unknown rips, duplicates with no proper names. I wanted a third step that could go further — actually *identify* the audio and pull proper metadata from an online music database.

The first attempt at that third script did not go well. The approach I tried at the time was too fragile, the API handling was messy, and the results were unreliable. I shelved it.

A year later I picked it up again, this time working with Claude Code. The AI suggested a much better technical approach: use **AcoustID** with the **fpcalc** audio fingerprinting binary from the Chromaprint project to generate an acoustic fingerprint of each file, look it up in the AcoustID database to get MusicBrainz recording IDs, then query the **MusicBrainz API** for the full tag set. I wanted to keep my older text-based search approach too, as a cross-check and fallback.

From there we worked through a lot of design decisions together: how the confidence scoring should work, when to prompt the user versus auto-write, how to handle files where fingerprinting returns a wrong result (the AcoustID database itself occasionally has errors), what the config file should look like, and how to implement a restore system so any run can be undone Altogether it was around 35 decisions and modifications. A few test runs against a real album exposed problems I had not anticipated — three tracks were confidently misidentified as songs by completely different artists because the fingerprint database was wrong for those recordings. That led to blending the AcoustID confidence score with a fuzzy filename-match score, and always running text search in parallel rather than as a last resort. That combination solved it. I asked the assisstant to comment the code, and create a manual.

It is not a perfect tool — no online lookup ever will be — but it works well enough form me to be useful, and I enjoyed building and tuning it.

---

## How It Works

1. Collects all MP3 files in the specified directory (or directories, recursively with `--recursive`)
2. For each file, extracts hints from the filename and folder structure (track number, title, artist, album)
3. If **fpcalc** is available and an AcoustID API key is configured: generates an audio fingerprint and queries the AcoustID database for candidate recordings
4. Always runs a parallel text-based search against MusicBrainz using the filename hints
5. Merges both candidate pools, deduplicates by MusicBrainz recording ID, and blends the AcoustID confidence score with a fuzzy filename-match score
6. Depending on the configured mode (`semi-auto`, `confirm`, or `auto`) and the confidence level: writes the best match automatically, or prompts the user to choose from a numbered list, or offers manual entry if nothing is found
7. Saves a restore map (JSON) so any run can be fully or partially undone
8. Optionally downloads and embeds cover art from the Cover Art Archive

---

## Requirements

### Python version

Python 3.10 or later.

### Python packages

| Package | Purpose | Install |
|---------|---------|---------|
| `mutagen` | Reading and writing MP3 ID3 tags | `pip install mutagen` |
| `requests` | HTTP calls to AcoustID, MusicBrainz, Cover Art Archive | `pip install requests` |
| `rapidfuzz` | Fuzzy string matching for filename-based candidate scoring | `pip install rapidfuzz` |
| `tqdm` | Progress bar | `pip install tqdm` |

```bash
pip install -r requirements.txt
```

Or in a virtual environment (recommended):

```bash
python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate     # Linux / macOS
pip install -r requirements.txt
```

### External binary: fpcalc (Chromaprint)

fpcalc is required for audio fingerprinting. Without it the script falls back to text search only — still functional, but less accurate.

**Windows:** Download from https://acoustid.org/chromaprint, extract `fpcalc.exe`, then either add it to your PATH or set `fpcalc_path` in the INI config.

**Linux / macOS:**
```bash
sudo apt install libchromaprint-utils   # Ubuntu / Debian
brew install chromaprint                # macOS (Homebrew)
```

### AcoustID API key

Required for fingerprint lookups. Free registration, and generating an application api key at https://acoustid.org/my-applications. Set the key in the INI config under `[credentials]`.

---

## Quick Start

### 1. Create a config file

On first run the script creates `mp3_online_tagger.ini` in the current directory with every field and inline comments. Edit it to add your AcoustID API key and fpcalc path.

### 2. Dry run first

```bash
python mp3_online_tagger.py "path/to/album" --dry-run
```

No files are modified. Review what the script intends to write.

### 3. Run for real

```bash
python mp3_online_tagger.py "path/to/album"
```

### 4. Undo if needed

```bash
python mp3_online_tagger.py --restore-last
```

---

## Parameters

| Argument / Flag | Default | Description |
|-----------------|---------|-------------|
| `PATH` (positional, one or more) | — | Directory path(s) containing MP3 files to process. Glob wildcards supported. |
| `-r`, `--recursive` | off | Recurse into all subdirectories. |
| `--config FILE` | `mp3_online_tagger.ini` | Path to the INI configuration file. |
| `--dry-run` | off | Preview changes without writing any files. |
| `--force` | off | Overwrite tags that are already set. Default: only fill empty tags. |
| `--mode MODE` | INI value | Override the operating mode: `semi-auto`, `confirm`, or `auto`. |
| `--restore FILE` | — | Restore tags from a specific restore map JSON file. |
| `--restore-last` | — | Restore from the most recent restore map in `restore_dir`. |
| `--file FILE` | — | Limit `--restore` / `--restore-last` to a single file path. |

For the full reference — INI config, confidence scoring, restore system, cover art, troubleshooting — see [MANUAL.md](./MANUAL.md).

---

## Notes

- Only `.mp3` files are processed; other audio formats are ignored
- MusicBrainz enforces a rate limit of 1 request per second — processing large collections takes time by design
- The restore map is always written, even in `--dry-run` mode, as a preview of what would have changed
- Always dry-run first when tagging a new collection
