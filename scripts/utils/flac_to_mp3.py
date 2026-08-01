#!/usr/bin/env python3
"""Convert every non-MP3 audio file in unzips/ and DEST root to MP3.

The whole pipeline downstream is MP3-only: generate-albums reads ID3 tags with
the `id3` crate, and sync-to-bucket.js refuses any extension outside its
ALLOWED_EXTS. Anything left as .m4a/.flac/.ogg/… is downloaded but invisible —
it never reaches the index and never reaches S3. So: convert everything.

Run before generate-albums (unzip.py calls this automatically).
"""
import subprocess
import sys
from pathlib import Path

DEST   = Path("/Volumes/EXTRA/hominiscanidae")
UNZIPS = DEST / "unzips"

# Everything ffmpeg can decode that the pipeline can't publish as-is.
SOURCE_EXTS = [".flac", ".wav", ".wma", ".m4a", ".aac", ".ogg", ".opus",
               ".alac", ".aiff", ".aif", ".mp4", ".webm"]


def convert(src: Path) -> bool:
    mp3 = src.with_suffix(".mp3")
    if mp3.exists() and mp3.stat().st_size > 0:
        src.unlink()            # already converted on an earlier run
        print(f"SKIP {src.name} (mp3 already present)")
        return True
    r = subprocess.run(
        ["ffmpeg", "-y", "-i", str(src), "-q:a", "2", "-map", "a",
         "-map_metadata", "0", "-id3v2_version", "3", str(mp3)],
        capture_output=True,
    )
    if r.returncode == 0 and mp3.exists() and mp3.stat().st_size > 0:
        src.unlink()
        print(f"OK   {src.name}  →  {mp3.name}  ({mp3.stat().st_size/1e6:.1f} MB)")
        return True
    mp3.unlink(missing_ok=True)
    print(f"FAIL {src}: {r.stderr.decode()[-200:]}")
    return False


def main():
    sources = []
    for ext in SOURCE_EXTS:
        sources += list(DEST.glob(f"*{ext}")) + list(UNZIPS.rglob(f"*{ext}"))
    sources = sorted(set(sources))

    if not sources:
        print("No non-MP3 audio found — everything is already MP3.")
        return 0

    print(f"Found {len(sources)} file(s) to convert")
    ok = sum(convert(f) for f in sources)
    print(f"\nConverted {ok}/{len(sources)}")
    return 0 if ok == len(sources) else 1


if __name__ == "__main__":
    sys.exit(main())
