#!/usr/bin/env python3
"""Fetch covers for 102 ghost Hominis Canidae albums (in JSON but not on S3).

For each album: fetches og:image from Bandcamp, resizes to 200px, uploads to S3.
Derives Bandcamp URL from MISSING_ALBUMS list first, then posts.json, then pattern.
"""

import gzip, json, os, re, subprocess, sys, tempfile, unicodedata
import urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO      = Path(__file__).parent.parent.parent
JSON_GZ   = REPO / 'js' / 'homi-albums.json.gz'
POSTS_JSON = REPO / 'posts.json'
POSTS_DIR  = REPO / 'posts'
ENV_FILE   = REPO / '.env'
S3_ENDPOINT = 'https://hel1.your-objectstorage.com'
S3_BUCKET   = 'indie'
S3_REGION   = 'hel1'
WORKERS     = 6

OGIMG_RE = re.compile(
    r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\'](https?://[^"\']+)["\']'
    r'|<meta[^>]+content=["\'](https?://[^"\']+)["\'][^>]+property=["\']og:image["\']',
    re.I
)
BC_RE = re.compile(r'https?://hominiscanidae\.bandcamp\.com/album/[^\s\)\"<>]+', re.I)

# Known Bandcamp URLs from sync-bandcamp-hc.py
KNOWN_URLS = {
    3:   'https://hominiscanidae.bandcamp.com/album/hominis-canidae-3',
    4:   'https://hominiscanidae.bandcamp.com/album/hominis-canidae-4',
    5:   'https://hominiscanidae.bandcamp.com/album/hominis-canidae-5',
    6:   'https://hominiscanidae.bandcamp.com/album/hominis-canidae-6',
    7:   'https://hominiscanidae.bandcamp.com/album/hominis-canidae-7',
    8:   'https://hominiscanidae.bandcamp.com/album/hominis-canidae-8',
    9:   'https://hominiscanidae.bandcamp.com/album/hominis-canidae-9',
    11:  'https://hominiscanidae.bandcamp.com/album/hominis-canidae-11',
    12:  'https://hominiscanidae.bandcamp.com/album/hominis-canidae-12',
    14:  'https://hominiscanidae.bandcamp.com/album/hominis-canidae-14',
    15:  'https://hominiscanidae.bandcamp.com/album/hominis-canidae-15',
    16:  'https://hominiscanidae.bandcamp.com/album/hominis-canidae-16',
    17:  'https://hominiscanidae.bandcamp.com/album/hominis-canidae-17',
    19:  'https://hominiscanidae.bandcamp.com/album/hominis-canidae-19',
    20:  'https://hominiscanidae.bandcamp.com/album/hominis-canidae-20',
    22:  'https://hominiscanidae.bandcamp.com/album/hominis-canidae-22',
    23:  'https://hominiscanidae.bandcamp.com/album/hominis-canidae-23',
    24:  'https://hominiscanidae.bandcamp.com/album/hominis-canidae-24',
    25:  'https://hominiscanidae.bandcamp.com/album/hominis-canidae-25',
    27:  'https://hominiscanidae.bandcamp.com/album/hominis-canidae-27',
    32:  'https://hominiscanidae.bandcamp.com/album/hominis-canidae-32',
    34:  'https://hominiscanidae.bandcamp.com/album/hominis-canidae-34-mar-o-2013',
    35:  'https://hominiscanidae.bandcamp.com/album/hominis-canidae-35-abril-2013',
    37:  'https://hominiscanidae.bandcamp.com/album/hominis-canidae-37-junho-2013',
    38:  'https://hominiscanidae.bandcamp.com/album/hominis-canidae-38-julho-2013',
    39:  'https://hominiscanidae.bandcamp.com/album/hominis-canidae-39-agosto-2013',
    41:  'https://hominiscanidae.bandcamp.com/album/hominis-canidae-41-outubro-2013',
    43:  'https://hominiscanidae.bandcamp.com/album/hominis-canidae-43-dezembro',
    45:  'https://hominiscanidae.bandcamp.com/album/hominis-canidae-45-fevereiro',
    52:  'https://hominiscanidae.bandcamp.com/album/hominis-canidae-52-setembro-2',
    54:  'https://hominiscanidae.bandcamp.com/album/hominis-canidae-54-novembro',
    55:  'https://hominiscanidae.bandcamp.com/album/hominis-canidae-55-dezembro-2014',
    59:  'https://hominiscanidae.bandcamp.com/album/hominis-canidae-59-abril-2015',
    61:  'https://hominiscanidae.bandcamp.com/album/hominis-canidae-61-junho-2015',
    62:  'https://hominiscanidae.bandcamp.com/album/hominis-canidae-62-julho-2015',
    67:  'https://hominiscanidae.bandcamp.com/album/hominis-canidae-67-dezembro-2015',
    68:  'https://hominiscanidae.bandcamp.com/album/hominis-canidae-68-janeiro-2016-2',
    93:  'https://hominiscanidae.bandcamp.com/album/hominis-canidae-93-fevereiro-2018',
    101: 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-101-outubro-2018',
    102: 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-102-novembro-2018',
    104: 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-104-janeiro-2019',
    108: 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-108-maio-2019',
    113: 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-113-outubro-2019',
    116: 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-116-janeiro-2020',
    119: 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-119-abril-2020',
    121: 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-121-junho-2020',
    125: 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-125-outubro-2020',
    130: 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-130-mar-o-2021',
    134: 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-134-julho-2021',
    135: 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-135-agosto-2021',
    136: 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-136-setembro-2021',
    137: 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-137-outubro-2021',
    138: 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-138-novembro-2021',
    141: 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-141-fevereiro-2022',
    143: 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-143-abril-2022',
    144: 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-144-maio-2022',
    145: 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-145-junho-2022',
    147: 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-147-agosto-2022',
    150: 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-150-novembro-2022',
    151: 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-151-dezembro-2022',
    156: 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-156-maio-2023',
    158: 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-158-julho-2023',
    159: 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-159-agosto-2023',
    160: 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-160-setembro-2023',
    161: 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-161-outubro-2023',
    162: 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-162-novembro-2023',
    166: 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-166-mar-o-2024',
    168: 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-168-maio-2024',
    169: 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-169-junho-2024',
    172: 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-172-setembro-2024',
    173: 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-173-outubro-2024',
    174: 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-174-novembro-2024',
    176: 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-176-janeiro-2025',
    177: 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-177-fevereiro-2025',
    181: 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-181-junho-2025',
    182: 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-182-julho-2025',
    183: 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-183-agosto-2025',
    184: 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-184-setembro-2025',
    185: 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-185-outubro-2025',
    187: 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-187-dezembro-2025',
    188: 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-188-janeiro-2026',
    189: 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-189-fevereiro-2026',
    190: 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-190-mar-o-2026',
    # Derived from path month/year
    33:  'https://hominiscanidae.bandcamp.com/album/hominis-canidae-33-fevereiro',
    36:  'https://hominiscanidae.bandcamp.com/album/hominis-canidae-36-mar-o-2013',
    42:  'https://hominiscanidae.bandcamp.com/album/hominis-canidae-42-novembro-2013',
    46:  'https://hominiscanidae.bandcamp.com/album/hominis-canidae-46-mar-o-2014',
    47:  'https://hominiscanidae.bandcamp.com/album/hominis-canidae-47-abril-2014',
    48:  'https://hominiscanidae.bandcamp.com/album/hominis-canidae-48-maio-2014',
    49:  'https://hominiscanidae.bandcamp.com/album/hominis-canidae-49-junho-2014',
    51:  'https://hominiscanidae.bandcamp.com/album/hominis-canidae-51-agosto-2014',
    53:  'https://hominiscanidae.bandcamp.com/album/hominis-canidae-53-outubro-2014',
    57:  'https://hominiscanidae.bandcamp.com/album/hominis-canidae-57-fevereiro-2015',
    60:  'https://hominiscanidae.bandcamp.com/album/hominis-canidae-60-maio-2015',
    63:  'https://hominiscanidae.bandcamp.com/album/hominis-canidae-63-agosto-2015',
    65:  'https://hominiscanidae.bandcamp.com/album/hominis-canidae-65-outubro-2015',
    69:  'https://hominiscanidae.bandcamp.com/album/hominis-canidae-69-fevereiro-2016',
    72:  'https://hominiscanidae.bandcamp.com/album/hominis-canidae-72-maio-2016',
    76:  'https://hominiscanidae.bandcamp.com/album/hominis-canidae-76-setembro-2016',
    78:  'https://hominiscanidae.bandcamp.com/album/hominis-canidae-78-novembro-2016',
    82:  'https://hominiscanidae.bandcamp.com/album/hominis-canidae-82-mar-o-2017',
    98:  'https://hominiscanidae.bandcamp.com/album/hominis-canidae-98-julho-2018',
}


def load_env():
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text().splitlines():
        m = re.match(r'^\s*([\w]+)\s*=\s*"?([^"]*)"?\s*$', line)
        if m:
            os.environ.setdefault(m.group(1), m.group(2))


def fetch_url(url, timeout=20):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    return urllib.request.urlopen(req, timeout=timeout).read().decode('utf-8', errors='replace')


def get_og_image(bc_url):
    """Fetch og:image URL from a Bandcamp page."""
    try:
        html = fetch_url(bc_url)
        m = OGIMG_RE.search(html)
        if m:
            return m.group(1) or m.group(2)
    except Exception:
        pass
    return None


def find_bc_url_from_posts(num, posts):
    """Search posts.json for a Bandcamp URL matching HC #num."""
    pattern = re.compile(rf'hominiscanidae\.bandcamp\.com/album/[^\s\)\"<>]*{num}[^\s\)\"<>]*', re.I)
    for p in posts:
        dl = p.get('download', '') or ''
        if pattern.search(dl):
            return dl
    # Try searching .md files
    for p in posts:
        url = p.get('url', '')
        m = re.search(r'/([^/]+)\.html', url)
        if not m:
            continue
        slug = m.group(1)
        md_path = POSTS_DIR / (slug + '.md')
        if not md_path.exists():
            continue
        try:
            content = md_path.read_text(errors='replace')
        except Exception:
            continue
        m2 = BC_RE.search(content)
        if m2 and pattern.search(m2.group(0)):
            return m2.group(0)
    return None


def resize_and_save(img_data, dest_path):
    """Resize image to 200px wide using ffmpeg."""
    with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp_in:
        tmp_in.write(img_data)
        tmp_in_path = tmp_in.name
    try:
        r = subprocess.run(
            ['ffmpeg', '-y', '-i', tmp_in_path, '-vf', 'scale=200:-1', '-q:v', '4', str(dest_path)],
            capture_output=True, timeout=30
        )
        return r.returncode == 0 and dest_path.exists() and dest_path.stat().st_size > 500
    finally:
        os.unlink(tmp_in_path)


def upload_to_s3(local_path, s3_key):
    key_nfc = unicodedata.normalize('NFC', s3_key)
    r = subprocess.run(
        ['aws', 's3', 'cp', str(local_path), f's3://{S3_BUCKET}/{key_nfc}',
         '--endpoint-url', S3_ENDPOINT, '--region', S3_REGION],
        capture_output=True, text=True, timeout=120,
        env={**os.environ, 'AWS_ACCESS_KEY_ID': os.environ['AWS_ACCESS_KEY_ID'],
             'AWS_SECRET_ACCESS_KEY': os.environ['AWS_SECRET_ACCESS_KEY']}
    )
    return r.returncode == 0


def process_album(path, num, posts):
    """Fetch cover for one ghost album and upload to S3. Returns (status, detail)."""
    # Find Bandcamp URL
    bc_url = KNOWN_URLS.get(num)
    if not bc_url:
        bc_url = find_bc_url_from_posts(num, posts)
    if not bc_url:
        return 'no_url', path

    # Get og:image URL
    img_url = get_og_image(bc_url)
    if not img_url:
        return 'no_image', f'{path} ({bc_url})'

    # Fetch image
    try:
        img_req = urllib.request.Request(img_url, headers={'User-Agent': 'Mozilla/5.0'})
        img_data = urllib.request.urlopen(img_req, timeout=20).read()
    except Exception as e:
        return 'fetch_err', f'{path}: {e}'

    if len(img_data) < 500:
        return 'too_small', path

    # Resize and save to temp file
    with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        ok = resize_and_save(img_data, tmp_path)
        if not ok:
            # Fallback: upload original without resize
            tmp_path.write_bytes(img_data)

        s3_key = f'{path}/capa-min.jpg'
        if upload_to_s3(tmp_path, s3_key):
            return 'ok', path
        else:
            return 'upload_err', path
    finally:
        tmp_path.unlink(missing_ok=True)


def main():
    load_env()

    with gzip.open(JSON_GZ, 'rb') as f:
        db = json.load(f)

    with open(POSTS_JSON) as f:
        posts = json.load(f)

    ghosts = [(a['path'], int(m.group(1)))
              for a in db['albums'] if a.get('has_cover') == True
              for m in [re.search(r'#(\d+)', a['path'])] if m]

    print(f'Ghost HC albums to fix: {len(ghosts)}')

    ok, no_url, no_img, errors = [], [], [], []

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(process_album, path, num, posts): (path, num) for path, num in ghosts}
        done = 0
        for fut in as_completed(futs):
            status, detail = fut.result()
            done += 1
            if status == 'ok':
                ok.append(detail)
                print(f'  [{done}/{len(ghosts)}] OK: {detail}')
            elif status == 'no_url':
                no_url.append(detail)
                print(f'  [{done}/{len(ghosts)}] NO_URL: {detail}')
            else:
                errors.append((status, detail))
                print(f'  [{done}/{len(ghosts)}] {status.upper()}: {detail}')

    print(f'\nDone: ok={len(ok)}  no_url={len(no_url)}  errors={len(errors)}')
    if no_url:
        print('Albums with no URL found:')
        for p in no_url: print(f'  {p}')
    if errors:
        print('Errors:')
        for s, d in errors: print(f'  {s}: {d}')


if __name__ == '__main__':
    main()
