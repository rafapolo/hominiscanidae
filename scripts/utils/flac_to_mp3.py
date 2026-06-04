#!/usr/bin/env python3
"""Convert all FLAC and WAV files in unzips/ and DEST root to MP3. Run before generate-albums."""
import subprocess, sys
from pathlib import Path

DEST   = Path("/Volumes/EXTRA/hominiscanidae")
UNZIPS = DEST / "unzips"


def convert(src: Path):
    mp3 = src.with_suffix(".mp3")
    r = subprocess.run(
        ["ffmpeg", "-y", "-i", str(src), "-q:a", "2", "-map", "a", str(mp3)],
        capture_output=True,
    )
    if r.returncode == 0 and mp3.exists() and mp3.stat().st_size > 0:
        src.unlink()
        print(f"OK   {src.name}  →  {mp3.name}  ({mp3.stat().st_size/1e6:.1f} MB)")
    else:
        print(f"FAIL {src}: {r.stderr.decode()[-200:]}")


sources = (
    list(DEST.glob("*.flac")) + list(UNZIPS.rglob("*.flac")) +
    list(DEST.glob("*.wav"))  + list(UNZIPS.rglob("*.wav"))
)
if not sources:
    print("No FLAC or WAV files found.")
    sys.exit(0)

print(f"Found {len(sources)} file(s) to convert")
for f in sources:
    convert(f)
