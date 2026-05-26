#!/usr/bin/env python3
"""
Fetch missing covers for the 632 remaining no-cover folders.

Sources tried in order:
  1. Blogger CDN URLs (any /sNNN/ size → rewritten to s1600)
  2. Bandcamp album page → og:image
  3. Direct bcbits.com image URLs from .md
"""

import os, re, json, unicodedata, urllib.request, urllib.error, html
from concurrent.futures import ThreadPoolExecutor, as_completed

UNZIP_DIR = '/Volumes/EXTRA/hominiscanidae/unzips/'
POSTS_DIR = '/Users/polux/Projetos/hominiscanidae/posts/'
WORKERS   = 8

IMAGE_EXT = {'.jpg','.jpeg','.png','.gif','.webp','.bmp','.tiff','.tif'}
AUDIO_EXT = {'.mp3','.flac','.ogg','.m4a','.aac','.wav','.opus','.wma'}

# Blogger old format: /sNNN/filename — rewrite to s1600
BLOG_OLD_RE = re.compile(
    r'(https://blogger\.googleusercontent\.com[^\s\)\"<>]+?)/s\d+/([^\s\)\"<>]+)',
    re.I
)
# Blogger new format (2021+): /img/a/TOKEN — no size component, download as-is
BLOG_NEW_RE = re.compile(
    r'https://blogger\.googleusercontent\.com/img/a/[^\s\)\"<>]{20,}',
    re.I
)
BC_RE    = re.compile(r'https?://([a-zA-Z0-9-]+)\.bandcamp\.com/album/([a-zA-Z0-9-]+)', re.I)
BCBIT_RE = re.compile(r'https?://f\d\.bcbits\.com/img/[^\s\)\"<>]+', re.I)
OGIMG_RE = re.compile(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\'](https?://[^"\']+)["\']', re.I)
OGIMG_RE2= re.compile(r'<meta[^>]+content=["\'](https?://[^"\']+)["\'][^>]+property=["\']og:image["\']', re.I)

with open('/Users/polux/Projetos/hominiscanidae/posts.json') as f:
    posts = json.load(f)

slug_to_post = {}
for p in posts:
    m = re.search(r'/(\d{4})/\d{2}/([^/]+)\.html', p.get('url', ''))
    if m:
        slug_to_post[m.group(2)] = p

def slugify(s):
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode('ascii').lower()
    return re.sub(r'[^a-z0-9]+', '-', s).strip('-')

def find_slug(folder, audio_files):
    # Strip YYYY prefix (and double-YYYY)
    rest = folder
    for _ in range(2):
        m = re.match(r'^\d{4}\s*-\s*(.+)', rest)
        if m:
            rest = m.group(1)
        else:
            break
    rest_sl = slugify(rest)
    if rest_sl in slug_to_post:
        return rest_sl
    for length in [20, 16, 12, 8, 6]:
        pfx = rest_sl[:length]
        if not pfx:
            continue
        for s in slug_to_post:
            if s.startswith(pfx):
                return s

    fsl = slugify(folder)
    if fsl in slug_to_post:
        return fsl
    for length in [14, 10]:
        pfx = fsl[:length]
        for s in slug_to_post:
            if s.startswith(pfx):
                return s

    for af in audio_files:
        stem = re.sub(r'\.(mp3|flac|ogg|m4a|aac|wav|opus|wma)$',
                      '', os.path.basename(af), flags=re.I)
        if stem in slug_to_post:
            return stem
        stem_sl = slugify(stem)
        if stem_sl in slug_to_post:
            return stem_sl
        for length in [20, 16, 12]:
            pfx = stem_sl[:length]
            if not pfx:
                continue
            for s in slug_to_post:
                if s.startswith(pfx):
                    return s
    return None

def blogger_url(md):
    m = BLOG_OLD_RE.search(md)
    if m:
        return f'{m.group(1)}/s1600/{m.group(2)}'
    m = BLOG_NEW_RE.search(md)
    if m:
        return m.group(0)
    return None

def bandcamp_url(md):
    m = BC_RE.search(md)
    if m:
        return f'https://{m.group(1)}.bandcamp.com/album/{m.group(2)}'
    return None

def bcbits_url(md):
    m = BCBIT_RE.search(md)
    if m:
        return m.group(0)
    return None

HEADERS = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}

def fetch_url(url, timeout=20):
    req = urllib.request.Request(url, headers=HEADERS)
    data = urllib.request.urlopen(req, timeout=timeout).read()
    return data

def og_image_from_bandcamp(bc_page_url):
    data = fetch_url(bc_page_url, timeout=25)
    text = data.decode('utf-8', errors='replace')
    m = OGIMG_RE.search(text) or OGIMG_RE2.search(text)
    if m:
        img_url = html.unescape(m.group(1))
        # Upgrade to highest quality: replace _5 with _0 (original)
        img_url = re.sub(r'_\d+\.(jpg|png|jpeg)', r'_0.\1', img_url)
        return img_url
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

    url = blogger_url(md)
    src = 'blogger'
    if not url:
        bc = bandcamp_url(md)
        if bc:
            url = bc
            src = 'bandcamp'
    if not url:
        url = bcbits_url(md)
        if url:
            src = 'bcbits'
    if not url:
        continue
    jobs.append((path, url, src))

print(f'Covers to fetch: {len(jobs)}  '
      f'(blogger={sum(1 for _,_,s in jobs if s=="blogger")}, '
      f'bandcamp={sum(1 for _,_,s in jobs if s=="bandcamp")}, '
      f'bcbits={sum(1 for _,_,s in jobs if s=="bcbits")})')

def fetch(args):
    folder_path, url, src = args
    dest = os.path.join(folder_path, 'cover.jpg')
    try:
        if src == 'bandcamp':
            img_url = og_image_from_bandcamp(url)
            if not img_url:
                return 'skip', f'{folder_path}: no og:image on {url}'
            data = fetch_url(img_url)
        else:
            data = fetch_url(url)
        if len(data) < 500:
            return 'skip', f'{folder_path}: too small ({len(data)}b)'
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
            print(f'  SKIP: {info}')
        else:
            err += 1
            print(f'  ERR: {info}')
        if i % 50 == 0:
            print(f'  {i}/{len(jobs)}  ok={ok} err={err} skip={skip}')

print(f'\nDone. ok={ok}, err={err}, skip={skip}')
