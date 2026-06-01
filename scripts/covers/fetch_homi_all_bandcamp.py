#!/usr/bin/env python3
"""
Fetch ALL Hominis Canidae album covers from hominiscanidae.bandcamp.com.
Saves as capa-min.jpg (400x400 JPEG) in each unzip folder.
Overwrites existing files.

Run: python3 scripts/covers/fetch_homi_all_bandcamp.py
"""

import os, re, json, gzip, html, unicodedata, urllib.request, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image
from io import BytesIO

UNZIP_DIR   = '/Volumes/EXTRA/hominiscanidae/unzips/'
ALBUMS_GZ   = '/Users/polux/Projetos/hominiscanidae/data/homi-albums.json.gz'
BC_BASE     = 'https://hominiscanidae.bandcamp.com'
WORKERS     = 6

HEADERS = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}
OGIMG_RE  = re.compile(r'property="og:image"\s+content="([^"]+)"', re.I)
OGIMG_RE2 = re.compile(r'content="([^"]+)"\s+property="og:image"', re.I)
BCBITS_RE = re.compile(r'f\d\.bcbits\.com/img/[a-zA-Z0-9_]+\.(?:jpg|png)', re.I)

MONTH_MAP = {
    'janeiro': 'janeiro', 'fevereiro': 'fevereiro', 'marco': 'mar-o',
    'março': 'mar-o', 'abril': 'abril', 'maio': 'maio', 'junho': 'junho',
    'julho': 'julho', 'agosto': 'agosto', 'setembro': 'setembro',
    'outubro': 'outubro', 'novembro': 'novembro', 'dezembro': 'dezembro',
}


def slugify(s):
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode('ascii').lower()
    return re.sub(r'[^a-z0-9]+', '-', s).strip('-')


def bc_slug_candidates(path, title):
    """Generate bandcamp URL slug candidates for a Hominis Canidae album."""
    m = re.search(r'#(\d+)\s*[-–]\s*(\w+)', path + ' ' + title, re.I)
    if not m:
        return []
    num = m.group(1)
    month_raw = m.group(2).lower()
    month_bc = MONTH_MAP.get(month_raw, slugify(month_raw))

    year_m = re.search(r'^(\d{4})', path)
    year = year_m.group(1) if year_m else ''

    candidates = [
        f'hominis-canidae-{num}-{month_bc}-{year}',
        f'hominis-canidae-{num}-{month_bc}',
        f'hominis-canidae-{num}-{month_raw}-{year}',
        f'hominis-canidae-{num}-{month_raw}',
    ]
    return candidates


def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers=HEADERS)
    return urllib.request.urlopen(req, timeout=timeout).read()


def og_image_from_page(page_url):
    data = fetch(page_url, timeout=25)
    text = data.decode('utf-8', errors='replace')
    m = OGIMG_RE.search(text) or OGIMG_RE2.search(text)
    if m:
        img = html.unescape(m.group(1))
        img = re.sub(r'_\d+\.(jpg|png)', r'_0.\1', img)
        return img
    m = BCBITS_RE.search(text)
    return f'https://{m.group(0)}' if m else None


def download_and_resize(img_url, dest, size=400):
    data = fetch(img_url)
    if len(data) < 500:
        raise ValueError(f'Too small ({len(data)} bytes)')
    img = Image.open(BytesIO(data)).convert('RGB')
    img = img.resize((size, size), Image.LANCZOS)
    img.save(dest, 'JPEG', quality=90)
    return os.path.getsize(dest)


def process(album):
    path = album['path']
    title = album.get('title', '')
    folder_path = os.path.join(UNZIP_DIR, path)
    dest = os.path.join(folder_path, 'capa-min.jpg')

    if not os.path.isdir(folder_path):
        return 'no_folder', path, ''

    candidates = bc_slug_candidates(path, title)
    if not candidates:
        return 'no_slug', path, ''

    last_err = ''
    for slug in candidates:
        bc_url = f'{BC_BASE}/album/{slug}'
        try:
            img_url = og_image_from_page(bc_url)
            if not img_url:
                continue
            sz = download_and_resize(img_url, dest)
            return 'ok', path, f'{slug} ({sz:,} bytes)'
        except urllib.error.HTTPError as e:
            if e.code == 404:
                continue
            last_err = str(e)
        except Exception as e:
            last_err = str(e)
            time.sleep(0.5)

    return 'not_found', path, last_err


# ── Load Hominis Canidae albums ───────────────────────────────────────────────

with gzip.open(ALBUMS_GZ) as f:
    db = json.load(f)

homi = [a for a in db['albums']
        if 'Hominis Canidae' in (a.get('title', '') + a.get('path', ''))]

print(f'Hominis Canidae albums: {len(homi)}')
print(f'Workers: {WORKERS}')
print()

ok = not_found = no_folder = no_slug = 0

with ThreadPoolExecutor(max_workers=WORKERS) as ex:
    futs = {ex.submit(process, a): a for a in homi}
    for i, fut in enumerate(as_completed(futs), 1):
        status, path, info = fut.result()
        if status == 'ok':
            ok += 1
            print(f'  OK  [{i}/{len(homi)}] {path}: {info}')
        elif status == 'not_found':
            not_found += 1
            print(f'  404 [{i}/{len(homi)}] {path}')
        elif status == 'no_folder':
            no_folder += 1
        elif status == 'no_slug':
            no_slug += 1
            print(f'  SLG [{i}/{len(homi)}] {path}')

print()
print(f'Done. ok={ok}, not_found={not_found}, no_folder={no_folder}, no_slug={no_slug}')
