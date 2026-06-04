#!/usr/bin/env python3
"""
Extract downloaded archives (RAR/ZIP/7z) from DEST into unzips/ using unar.
unar auto-detects charset (CP850/Latin-1/UTF-8) — fixes PT-BR filename issues
that caused tracks with accented names to be silently dropped by unrar/Archive Utility.

Usage:
    python3 script/unzip.py            # extract all unextracted archives
    python3 script/unzip.py --force    # re-extract even if folder exists
"""

import os, re, subprocess, sys
from pathlib import Path

DEST      = Path("/Volumes/EXTRA/hominiscanidae")
UNZIPS    = DEST / "unzips"
ARCHIVES  = {".rar", ".zip", ".7z"}
FORCE     = "--force" in sys.argv

UNZIPS.mkdir(exist_ok=True)

archives = sorted(f for f in DEST.iterdir()
                  if f.is_file() and f.suffix.lower() in ARCHIVES)

if not archives:
    print("No archives found in", DEST)
    sys.exit(0)

print(f"Found {len(archives)} archives")
ok = skipped = failed = 0

for archive in archives:
    stem   = archive.stem
    # Check if already extracted (any folder in unzips whose slug overlaps)
    if not FORCE:
        existing = [d for d in UNZIPS.iterdir()
                    if d.is_dir() and stem[:20].lower() in d.name.lower()]
        if existing:
            skipped += 1
            continue

    r = subprocess.run(
        ["unar", "-o", str(UNZIPS), str(archive)],
        capture_output=True, text=True,
    )
    if r.returncode == 0:
        print(f"  OK  {archive.name}")
        ok += 1
    else:
        print(f"  FAIL {archive.name}: {r.stderr.strip()[:120]}")
        failed += 1

print(f"\nDone: {ok} extracted, {skipped} skipped, {failed} failed")

if ok > 0:
    print("\nConverting WAV/FLAC to MP3...")
    conv = Path(__file__).parent / "flac_to_mp3.py"
    subprocess.run([sys.executable, str(conv)], check=False)
