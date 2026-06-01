#!/usr/bin/env python3
"""Convert all FLAC files in unzips/ and DEST root to MP3. Run before generate-albums."""
import subprocess, sys
from pathlib import Path

DEST   = Path("/Volumes/EXTRA/hominiscanidae")
UNZIPS = DEST / "unzips"


def convert(flac: Path):
    mp3 = flac.with_suffix(".mp3")
    r = subprocess.run(
        ["ffmpeg", "-y", "-i", str(flac), "-q:a", "0", "-map", "a", str(mp3)],
        capture_output=True,
    )
    if r.returncode == 0 and mp3.exists() and mp3.stat().st_size > 0:
        flac.unlink()
        print(f"OK   {flac}  →  {mp3.name}  ({mp3.stat().st_size/1e6:.1f} MB)")
    else:
        print(f"FAIL {flac}: {r.stderr.decode()[-200:]}")


flacs = list(DEST.glob("*.flac")) + list(UNZIPS.rglob("*.flac"))
if not flacs:
    print("No FLAC files found.")
    sys.exit(0)

print(f"Found {len(flacs)} FLAC file(s)")
for f in flacs:
    convert(f)
