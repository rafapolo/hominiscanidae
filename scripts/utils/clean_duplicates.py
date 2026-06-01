#!/usr/bin/env python3
"""Find and remove duplicate-track-number MP3s across all albums.

Keeps only the "best" file per track number — preferring files where the
track number appears latest in the filename (Pattern C: "Artist - Album - NN Title.mp3"),
falling back to the shortest stem.

Usage:
    python3 scripts/utils/clean_duplicates.py
    python3 scripts/utils/clean_duplicates.py --dry-run    # preview only
    python3 scripts/utils/clean_duplicates.py --no-upload  # disk only, skip S3
"""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).parent.parent.parent
UNZIPS = Path("/Volumes/EXTRA/hominiscanidae/unzips")
ENDPOINT = "https://hel1.your-objectstorage.com"
S3_BUCKET = "indie"
S3_PREFIX = "indie"  # object keys have this prefix

# Match 1–3 digit track numbers at start of filename or after " - "
RE_TRACK_START = re.compile(r"^(\d{1,3})\s")
RE_TRACK_MID = re.compile(r" - (\d{1,3})\s")


def load_env():
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def extract_track(filename: str) -> int | None:
    m = RE_TRACK_START.match(filename)
    if m:
        return int(m.group(1))
    m = RE_TRACK_MID.search(filename)
    if m:
        return int(m.group(1))
    return None


def pick_best(candidates: list[str]) -> str:
    """Among files with the same track number, pick the best one."""
    # Prefer the file where the track number appears latest in the name
    # (Pattern C: "Artist - Album - NN Title.mp3" vs Pattern A: "NN Artist - Album - Title.mp3")
    def score(f: str) -> tuple:
        stem = Path(f).stem
        # Find position of match
        m1 = RE_TRACK_START.match(f)
        m2 = RE_TRACK_MID.search(f)
        pos = m1.end() if m1 else (m2.start() if m2 else 0)
        return (pos, -len(stem))  # higher position = better, shorter stem as tiebreak

    return max(candidates, key=score)


def s3_rm(key: str, dry_run: bool):
    if dry_run:
        return True
    r = subprocess.run(
        ["aws", "s3", "rm", f"s3://{S3_BUCKET}/{key}",
         "--endpoint-url", ENDPOINT],
        capture_output=True, text=True
    )
    if r.returncode != 0:
        print(f"  S3 ERROR: {r.stderr.strip()}", file=sys.stderr)
        return False
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="preview only, no changes")
    ap.add_argument("--no-upload", action="store_true", help="skip S3 deletion")
    args = ap.parse_args()

    load_env()

    total_freed = 0
    affected_albums = 0

    for album_dir in sorted(UNZIPS.iterdir()):
        if not album_dir.is_dir():
            continue

        mp3s = sorted([
            f.name for f in album_dir.iterdir()
            if f.suffix.lower() == ".mp3" and not f.name.startswith("._")
        ])
        if len(mp3s) < 2:
            continue

        # Map track numbers to filenames
        track_map: dict[int, list[str]] = {}
        for f in mp3s:
            tn = extract_track(f)
            if tn is not None:
                track_map.setdefault(tn, []).append(f)

        # Find duplicates
        redundant: list[str] = []
        for tn, files in track_map.items():
            if len(files) > 1:
                keep = pick_best(files)
                redundant.extend(f for f in files if f != keep)

        if not redundant:
            continue

        affected_albums += 1
        album_path = album_dir.name
        print(f"\n{album_path}")
        print(f"  {len(mp3s)} mp3s → keeping {len(mp3s) - len(redundant)}, removing {len(redundant)}")

        for fname in redundant:
            disk_path = album_dir / fname
            s3_key = f"{S3_PREFIX}/{album_path}/{fname}"

            # Disk
            if not args.dry_run:
                disk_path.unlink(missing_ok=True)
            print(f"  rm disk: {fname}")

            # S3
            if not args.no_upload:
                ok = s3_rm(s3_key, dry_run=args.dry_run)
                if ok:
                    print(f"  rm s3:   {fname}")

        total_freed += len(redundant)

    print(f"\n{'='*60}")
    print(f"Affected albums: {affected_albums}")
    print(f"Files removed:   {total_freed}")
    if args.dry_run:
        print("(dry run — no changes made)")
    print()


if __name__ == "__main__":
    main()
