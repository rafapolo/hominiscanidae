#!/usr/bin/env python3
"""
Download missing album covers from Blogger CDN URLs embedded in posts/*.md.
Saves as cover.jpg inside each unzip folder that has audio but no cover.
"""

import os, re, json, unicodedata, urllib.request, urllib.error, time
from concurrent.futures import ThreadPoolExecutor, as_completed

UNZIP_DIR = '/Volumes/EXTRA/hominiscanidae/unzips/'
POSTS_DIR = '/Users/polux/Projetos/hominiscanidae/posts/'
WORKERS   = 10

IMAGE_EXT = {'.jpg','.jpeg','.png','.gif','.webp','.bmp','.tiff','.tif'}
AUDIO_EXT = {'.mp3','.flac','.ogg','.m4a','.aac','.wav','.opus','.wma'}

IMG_RE = re.compile(
    r'https://blogger\.googleusercontent\.com[^\s\)\"<>]+?/s1600/[^\s\)\"<>]+',
    re.I
)

with open('/Users/polux/Projetos/hominiscanidae/posts.json') as f:
    posts = json.load(f)

slug_to_post = {}
for p in posts:
    m = re.search(r'/(\d{4})/\d{2}/([^/]+)\.html', p.get('url',''))
    if m:
        slug_to_post[m.group(2)] = p

rescue_stems = {}
for slug, p in slug_to_post.items():
    if p.get('rescue_source'):
        da = p.get('downloaded_as','') or ''
        stem = re.sub(r'\.(mp3|flac|ogg|m4a|aac|wav|opus|wma|rar|zip|7z)$',
                      '', os.path.basename(da), flags=re.I)
        if stem:
            rescue_stems[stem] = slug

def slugify(s):
    s = unicodedata.normalize('NFKD', s).encode('ascii','ignore').decode('ascii').lower()
    return re.sub(r'[^a-z0-9]+', '-', s).strip('-')

def find_slug(folder, audio_files):
    fsl = slugify(folder)
    if fsl in slug_to_post:
        return fsl
    for s in slug_to_post:
        if s.startswith(fsl[:min(14, len(fsl))]):
            return s
    for af in audio_files:
        stem = re.sub(r'\.(mp3|flac|ogg|m4a|aac|wav|opus|wma)$',
                      '', os.path.basename(af), flags=re.I)
        if stem in slug_to_post:
            return stem
        if stem in rescue_stems:
            return rescue_stems[stem]
    return None

# Build work list
jobs = []
for folder in sorted(os.listdir(UNZIP_DIR)):
    path = os.path.join(UNZIP_DIR, folder)
    if not os.path.isdir(path):
        continue
    files = []
    for root, _, fns in os.walk(path):
        for f in fns:
            files.append(os.path.join(root, f))
    audio  = [f for f in files if os.path.splitext(f)[1].lower() in AUDIO_EXT]
    images = [f for f in files if os.path.splitext(f)[1].lower() in IMAGE_EXT]
    if not audio or images:
        continue
    slug = find_slug(folder, audio)
    if not slug:
        continue
    md_path = os.path.join(POSTS_DIR, slug + '.md')
    try:
        md = open(md_path).read()
    except FileNotFoundError:
        continue
    m = IMG_RE.search(md)
    if not m:
        continue
    jobs.append((path, m.group(0)))

print(f'Covers to fetch: {len(jobs)}')

def fetch(args):
    folder_path, url = args
    dest = os.path.join(folder_path, 'cover.jpg')
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        data = urllib.request.urlopen(req, timeout=15).read()
        if len(data) < 500:
            return 'skip', folder_path
        with open(dest, 'wb') as f:
            f.write(data)
        return 'ok', folder_path
    except Exception as e:
        return 'err', f'{folder_path}: {e}'

ok = err = skip = 0
with ThreadPoolExecutor(max_workers=WORKERS) as ex:
    futs = {ex.submit(fetch, job): job for job in jobs}
    for i, fut in enumerate(as_completed(futs), 1):
        status, info = fut.result()
        if status == 'ok':
            ok += 1
        elif status == 'skip':
            skip += 1
        else:
            err += 1
            print(f'  ERR: {info}')
        if i % 100 == 0:
            print(f'  {i}/{len(jobs)}  ok={ok} err={err} skip={skip}')

print(f'\nDone. ok={ok}, err={err}, skip={skip}')
