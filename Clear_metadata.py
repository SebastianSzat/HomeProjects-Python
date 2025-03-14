#####################################################################
## Creator  : SebastianSzat                                        ##
## Usage    : Free to use, but please give credit when applicable. ##
##            No warranty is provided. Use at your own risk.       ##
## --------------------------------------------------------------- ##
## Version  : 0.2                                                  ##
## Modified : 14-03-2025                                           ##
## --------------------------------------------------------------- ##
## Clear_metadata.py                                               ##
## The script asks the user for a directory path to process.       ##
## All mp3 type files will be processed.                           ##
## User selected metadata information will be cleared.             ##
#####################################################################

#####################################################################
## import libraries
import os
import mutagen
import mutagen.mp3
import datetime
import glob

#####################################################################
## Get the directory path (supports wildcards)
directory_pattern = input("Enter the directory path to mp3 files (supports wildcards *): ").strip()
directories = [d for d in glob.glob(directory_pattern, recursive=True) if os.path.isdir(d)]
if not directories:
    print("No matching directories found.")
    exit(1)

#####################################################################
## Define metadata fields to check and remove
metadata_full_names = {
    'TIT2': 'Title',
    'TIT3': 'Subtitle/Description',
    'TXXX:Rating': 'Rating',
    'COMM': 'Comments',
    'TPE1': 'Contributing Artist',
    'TPE2': 'Album Artist',
    'TALB': 'Album',
    'TYER': 'Year (ID3v2.3)',
    'TDRC': 'Year (ID3v2.4)',
    'TRCK': 'Track Number',
    'TCON': 'Genre'
}
relevant_metadata = list(metadata_full_names.keys())

#####################################################################
## Full metadata list
'''
'TIT1': 'Content group description',
'TIT2': 'Title',
'TIT3': 'Subtitle/Description',
'TXXX': 'User-defined text information',
'COMM': 'Comments',
'TP1': 'Lead performer(s)/Soloist(s)',
'TP2': 'Band/Orchestra/Accompaniment',
'TP3': 'Conductor/Performer refinement',
'TP4': 'Interpreted, remixed, or otherwise modified by',
'TPE1': 'Contributing Artist',
'TPE2': 'Album Artist',
'TALB': 'Album',
'TYER': 'Year (ID3v2.3)',
'TDRC': 'Year (ID3v2.4)',
'TRCK': 'Track Number',
'TCON': 'Genre',
'TCOM': 'Composer',
'TCOP': 'Copyright message',
'TMED': 'Media type',
'TLEN': 'Length (duration)',
'TSSE': 'Software/Hardware and settings used for encoding',
'USLT': 'Unsynchronized lyrics/text transcription',
'UFID': 'Unique file identifier',
'APIC': 'Attached picture (e.g., album art)',
'PRIV': 'Private frame',
'WXXX': 'URL link frame',
'WCOM': 'Commercial information',
'WCOP': 'Copyright/Legal information URL',
'WPAY': 'Payment URL'
'''

#####################################################################
## Ask user which metadata to clear
clear_metadata = {}
print("Select metadata to clear:")
for key in relevant_metadata:
    full_name = metadata_full_names[key]
    choice = input(f"{full_name} (y/N)? ").strip().lower()
    clear_metadata[key] = choice == 'y'

timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
log_filename = f"Clear_metadata_{timestamp}.log"
log_filepath = os.path.join(os.getcwd(), log_filename)

#####################################################################
## Function to log and print
def log(message):
    print(message)
    with open(log_filepath, "a", encoding="utf-8") as log_file:
        log_file.write(message + "\n")

#####################################################################
## Log the start of the process
log("\nClear metadata")
log(f"Directories scanned: {', '.join(directories)}")
for key, clear in clear_metadata.items():
    full_name = metadata_full_names[key]
    log(f"{full_name} - {'to be cleared' if clear else 'no changes'}")

#####################################################################
## Collect all mp3 files in directory
mp3_files = []
for directory in directories:
    for root, _, files in os.walk(directory):
        for file in files:
            if file.lower().endswith(".mp3"):
                mp3_files.append(os.path.join(root, file))

log(f"\nTracks: (total {len(mp3_files)})")

#####################################################################
## Process each file
for i, file_path in enumerate(mp3_files, 1):
    try:
        audio = mutagen.mp3.MP3(file_path)
        if audio.tags is None:
            audio.add_tags()
        modified = False
        
        for key in relevant_metadata:
            if clear_metadata[key] and key in audio.tags:
                del audio.tags[key]
                modified = True
        
        if modified:
            audio.save()
            modified_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log(f"{i}/{len(mp3_files)} - '{os.path.basename(file_path)}' - Modified at {modified_time}")
        else:
            log(f"{i}/{len(mp3_files)} - '{os.path.basename(file_path)}' - No changes made")
    except Exception as e:
        log(f"{i}/{len(mp3_files)} - '{os.path.basename(file_path)}' - Error: {e}")

#####################################################################
## Log completion
timestamp_done = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
log(f"Clear metadata script done at {timestamp_done}")

#####################################################################
## End
