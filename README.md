# HomeProjects-Python

A small Python utility to help clean and manage MP3 file metadata (ID3 tags).

## Background

Created in 2025 as a personal project to help my landlord digitise his music collection. He had a large collection of old music discs but a new MP3-capable car radio. I helped him convert the discs to MP3 format, but the resulting files came with messy or incorrect metadata. This tool was built to clean that metadata out, so it could later be properly filled in using other tools.

## What It Does

`Clear_mp3_metadata.py` is an interactive command-line script that lets you selectively remove ID3 metadata tags from MP3 files across a directory (or multiple directories using wildcard patterns).

### Features

- Recursively scans a directory for all `.mp3` files
- Lets you choose **which metadata fields to clear** via interactive prompts
- Supports wildcard patterns in directory paths (e.g. `C:/Music/Rock*`)
- Logs all actions to a timestamped log file for traceability

### Metadata Fields You Can Clear

| Tag | Field |
|-----|-------|
| TIT2 | Title |
| TIT3 | Subtitle / Description |
| TXXX:Rating | Rating |
| COMM | Comments |
| TPE1 | Contributing Artist |
| TPE2 | Album Artist |
| TALB | Album |
| TYER / TDRC | Year (ID3v2.3 / ID3v2.4) |
| TRCK | Track Number |
| TCON | Genre |

## Requirements

Install the required Python packages:

```bash
pip install mutagen requests tqdm
```

## Usage

```bash
python Clear_mp3_metadata.py
```

The script will prompt you for:
1. The directory path containing your MP3 files
2. Which metadata fields you want to clear (yes/no for each)

A log file (`Clear_metadata_YYYYMMDD_HHMMSS.log`) will be created in the working directory with a full record of what was processed.

## Notes

- Files are modified **in place** — consider making a backup before running
- If a file fails to process, the error is logged and the script continues with the remaining files
- Provided as-is, without warranty — use at your own risk

## Full Metadata List

All known ID3 metadata tags and their descriptions:

| Tag | Field |
|-----|-------|
| TIT1 | Content group description |
| TIT2 | Title |
| TIT3 | Subtitle / Description |
| TXXX | User-defined text information |
| COMM | Comments |
| TP1 | Lead performer(s) / Soloist(s) |
| TP2 | Band / Orchestra / Accompaniment |
| TP3 | Conductor / Performer refinement |
| TP4 | Interpreted, remixed, or otherwise modified by |
| TPE1 | Contributing Artist |
| TPE2 | Album Artist |
| TALB | Album |
| TYER | Year (ID3v2.3) |
| TDRC | Year (ID3v2.4) |
| TRCK | Track Number |
| TCON | Genre |
| TCOM | Composer |
| TCOP | Copyright message |
| TMED | Media type |
| TLEN | Length (duration) |
| TSSE | Software / Hardware and settings used for encoding |
| USLT | Unsynchronized lyrics / text transcription |
| UFID | Unique file identifier |
| APIC | Attached picture (e.g. album art) |
| PRIV | Private frame |
| WXXX | URL link frame |
| WCOM | Commercial information |
| WCOP | Copyright / Legal information URL |
| WPAY | Payment URL |
