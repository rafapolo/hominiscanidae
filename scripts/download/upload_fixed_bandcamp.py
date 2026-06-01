#!/usr/bin/env python3
"""Upload fixed bandcamp album MP3s to S3 and regenerate JSON."""
import json, os
import subprocess
import re
import unicodedata
from pathlib import Path
from datetime import datetime, timezone

ENV_FILE = Path(__file__).resolve().parents[2].parent / 'tocador' / '.env'

# Load env vars
if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        m = re.match(r'^(\w+)=(?:"?([^"]*?)"?)$', line.strip())
        if m:
            os.environ.setdefault(m.group(1), m.group(2))

S3_ENDPOINT = os.environ.get('S3_ENDPOINT', 'https://hel1.your-objectstorage.com')
S3_BUCKET = os.environ.get('S3_BUCKET', 'indie')
S3_REGION = 'hel1'
UNZIPS = Path("/Volumes/EXTRA/hominiscanidae/unzips")

# Albums fixed by fix_bandcamp_gaps.py (new files added today)
today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
fixed_dirs = []
for d in sorted(UNZIPS.iterdir()):
    if not d.is_dir():
        continue
    new_mp3s = [f for f in d.glob("*.mp3")
                if f.stat().st_mtime > 0 and
                datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc).strftime('%Y-%m-%d') == today]
    if new_mp3s:
        fixed_dirs.append((d, new_mp3s))

print(f"Directories with new files today: {len(fixed_dirs)}")

total = 0
for d, new_mp3s in fixed_dirs:
    album_key = d.name
    # Normalize path to NFC
    album_key_nfc = unicodedata.normalize('NFC', album_key)
    ok = 0
    for f in new_mp3s:
        fname_nfc = unicodedata.normalize('NFC', f.name)
        s3_dest = f's3://{S3_BUCKET}/{album_key_nfc}/{fname_nfc}'
        r = subprocess.run(
            ['aws', 's3', 'cp', str(f), s3_dest,
             '--endpoint-url', S3_ENDPOINT, '--region', S3_REGION],
            capture_output=True, text=True, timeout=300
        )
        if r.returncode == 0:
            ok += 1
        else:
            print(f"  FAIL: {f.name} - {r.stderr.strip()}")
    if ok:
        print(f"  {album_key}: {ok}/{len(new_mp3s)} uploaded")
        total += ok

print(f"\nTotal MP3s uploaded: {total}")
print("Done! Run generate-albums next.")
