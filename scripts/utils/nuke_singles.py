#!/usr/bin/env python3
"""Nuke all single-track albums: delete from S3, local unzips/, and reset posts.json."""

import json, os, shutil, subprocess, sys
from pathlib import Path
from dotenv import dotenv_values

ROOT   = Path(__file__).parent.parent.parent
UNZIPS = Path('/Volumes/EXTRA/hominiscanidae/unzips')
S3_ENDPOINT = 'https://hel1.your-objectstorage.com'
S3_BUCKET   = 'indie'

# Load credentials
env_file = ROOT / '.env' if (ROOT / '.env').exists() else ROOT.parent / 'tocador' / '.env'
env = dotenv_values(env_file)
os.environ['AWS_ACCESS_KEY_ID']     = env['AWS_ACCESS_KEY_ID']
os.environ['AWS_SECRET_ACCESS_KEY'] = env['AWS_SECRET_ACCESS_KEY']

with open(ROOT / 'posts.json') as f:
    posts = json.load(f)

by_mp3 = {}
for i, p in enumerate(posts):
    da = p.get('downloaded_as') or ''
    if da:
        by_mp3[os.path.basename(da)] = i

singles = []
for d in sorted(os.listdir(UNZIPS)):
    path = UNZIPS / d
    if not path.is_dir(): continue
    mp3s = [f for f in os.listdir(path) if f.endswith('.mp3')]
    if len(mp3s) == 1:
        singles.append((d, mp3s[0]))

print(f'Nuking {len(singles)} single-track albums...')

s3_deleted = local_deleted = posts_reset = 0
errors = []

for folder, mp3name in singles:
    # Delete from S3
    s3_path = f's3://{S3_BUCKET}/{folder}/'
    r = subprocess.run(
        ['aws', 's3', 'rm', s3_path, '--recursive',
         '--endpoint-url', S3_ENDPOINT],
        capture_output=True, text=True
    )
    if r.returncode == 0:
        s3_deleted += 1
    else:
        errors.append(f'S3 error for {folder}: {r.stderr.strip()}')

    # Delete local
    local_path = UNZIPS / folder
    try:
        shutil.rmtree(local_path)
        local_deleted += 1
    except Exception as e:
        errors.append(f'Local error for {folder}: {e}')

    # Reset posts.json
    idx = by_mp3.get(mp3name)
    if idx is not None:
        posts[idx]['status'] = 'not_downloaded'
        posts[idx]['downloaded_as'] = None
        posts_reset += 1

print(f'S3 deleted: {s3_deleted}')
print(f'Local deleted: {local_deleted}')
print(f'posts.json reset: {posts_reset}')

with open(ROOT / 'posts.json', 'w') as f:
    json.dump(posts, f, ensure_ascii=False, indent=2)
print('posts.json saved.')

if errors:
    print(f'\n{len(errors)} errors:')
    for e in errors[:20]:
        print(' ', e)
