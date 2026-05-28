#!/usr/bin/env python3
"""Rename YYYY - YYYY - Name folders to YYYY - Artist - Name using ID3 tags, or YYYY - Name if no artist."""
import os, re, sys
from pathlib import Path

try:
    from mutagen.mp3 import MP3
    from mutagen.id3 import ID3, ID3NoHeaderError
    HAS_MUTAGEN = True
except ImportError:
    HAS_MUTAGEN = False
    print("mutagen not found — install with: pip3 install mutagen")
    print("Falling back to YYYY - Name (no artist lookup)\n")

UNZIPS = Path("/Volumes/EXTRA/hominiscanidae/unzips")
PAT = re.compile(r'^(\d{4}) - \1 - (.+)$')

def get_artist(folder):
    if not HAS_MUTAGEN:
        return None
    for f in sorted(folder.iterdir()):
        if f.suffix.lower() == '.mp3':
            try:
                tags = ID3(f)
                artist = tags.get('TPE1') or tags.get('TPE2')
                if artist:
                    val = str(artist).strip()
                    if val and val.lower() not in ('unknown', 'various artists', ''):
                        return val
            except Exception:
                pass
    return None

dry_run = '--dry-run' in sys.argv
renames = []

for entry in sorted(UNZIPS.iterdir()):
    if not entry.is_dir():
        continue
    m = PAT.match(entry.name)
    if not m:
        continue
    year, rest = m.group(1), m.group(2)
    artist = get_artist(entry)
    new_name = f"{year} - {artist} - {rest}" if artist else f"{year} - {rest}"
    new_path = UNZIPS / new_name
    renames.append((entry, new_path))

print(f"Found {len(renames)} folders to rename\n")

for old, new in renames:
    if dry_run:
        print(f"  {old.name}\n  → {new.name}\n")
    else:
        if new.exists():
            print(f"  SKIP (target exists): {new.name}")
        else:
            os.rename(old, new)
            print(f"  ✓ {old.name} → {new.name}")

if dry_run:
    print(f"\nDry run — pass no args to apply.")
else:
    print(f"\nDone — {len(renames)} folders renamed.")
