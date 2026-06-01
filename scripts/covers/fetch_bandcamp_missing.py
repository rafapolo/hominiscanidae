#!/usr/bin/env python3
"""
Download missing album covers from hominiscanidae.bandcamp.com.
Saves as capa-min.jpg (400x400 JPEG) inside each unzip folder.

Targets:
  - Hominis Canidae mixtapes found on bandcamp
  - Other albums with cover=null in homi-albums.json
"""

import os, re, json, html, urllib.request
from PIL import Image
from io import BytesIO

UNZIP_DIR = '/Volumes/EXTRA/hominiscanidae/unzips/'
ALBUMS_JSON = '/Users/polux/Projetos/hominiscanidae/data/homi-albums.json'

HEADERS = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}

OGIMG_RE  = re.compile(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\'](https?://[^"\']+)["\']', re.I)
OGIMG_RE2 = re.compile(r'<meta[^>]+content=["\'](https?://[^"\']+)["\'][^>]+property=["\']og:image["\']', re.I)


def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers=HEADERS)
    return urllib.request.urlopen(req, timeout=timeout).read()


def og_image_from_page(page_url):
    data = fetch(page_url, timeout=25)
    text = data.decode('utf-8', errors='replace')
    m = OGIMG_RE.search(text) or OGIMG_RE2.search(text)
    if m:
        img_url = html.unescape(m.group(1))
        # _0 = original size on bcbits; upgrade from any thumbnail suffix
        img_url = re.sub(r'_\d+\.(jpg|jpeg|png)', r'_0.\1', img_url)
        return img_url
    return None


def download_and_resize(img_url, dest_path, size=400):
    data = fetch(img_url)
    img = Image.open(BytesIO(data)).convert('RGB')
    img = img.resize((size, size), Image.LANCZOS)
    img.save(dest_path, 'JPEG', quality=90)
    return os.path.getsize(dest_path)


# ── Known bandcamp URLs for Hominis Canidae mixtapes missing covers ───────────

KNOWN_BC_PAGES = {
    '2022 - Resp - Hominis Canidae #149 - Outubro':
        'https://hominiscanidae.bandcamp.com/album/hominis-canidae-149-outubro-2022',
    '2023 - Tori - Hominis Canidae #153 - Fevereiro':
        'https://hominiscanidae.bandcamp.com/album/hominis-canidae-153-fevereiro-2023',
}

# ── Candidate bandcamp URLs for other missing albums ─────────────────────────
# (guessed from artist/album name; will 404 gracefully if wrong)

OTHER_BC_CANDIDATES = {
    '1973 - Cilibrinas Do Eden - Cilibrinas Do Eden': [
        'https://cilibrinas.bandcamp.com/album/cilibrinas-do-eden',
        'https://cilbrinasedoeden.bandcamp.com/',
    ],
    '2013 - G.R.E.P. Unidos do Faça Você Mesmo - Death Samba': [
        'https://grepunidos.bandcamp.com/album/death-samba',
        'https://grep.bandcamp.com/album/death-samba',
    ],
    '2013 - Le Degout - Split com Atrás do Pensamento': [
        'https://ledegout.bandcamp.com/',
        'https://ledegout.bandcamp.com/album/split',
    ],
    "2013 - Ume - 2013-07-23 Maxwell's, Hoboken, NJ": [
        'https://umemusic.bandcamp.com/',
    ],
    '2015 - insonia-demo-2015': [],
    '2015 - ki nu - Amigo': [
        'https://kinu.bandcamp.com/album/amigo',
        'https://ki-nu.bandcamp.com/album/amigo',
    ],
    '2016 - (dell.tree) - deus odeia publicitários parte 2': [
        'https://delltree.bandcamp.com/',
        'https://dell-tree.bandcamp.com/',
    ],
    '2016 - Phantom Pain': [
        'https://phantompainbrasil.bandcamp.com/',
    ],
    '2016 - vermes-do-limbo-ep-vrmsxx-2016': [
        'https://vermesdolimbo.bandcamp.com/',
    ],
    '2019 - 2019 - Airplanemusic Architecture For': [
        'https://airplanemusicarchitecture.bandcamp.com/',
        'https://airplanemusic.bandcamp.com/',
    ],
    '2023 - Trekking At The End Of The World': [
        'https://trekkingattheendoftheworld.bandcamp.com/',
        'https://trekkingworld.bandcamp.com/',
    ],
    '2024 - Tatiana Dauster - Origami': [
        'https://tatianadauster.bandcamp.com/album/origami',
        'https://tatianadauster.bandcamp.com/',
    ],
    '2024 - Tecnoplanta - Tecnicolor Sensação': [
        'https://tecnoplanta.bandcamp.com/album/tecnicolor-sensa-o',
        'https://tecnoplanta.bandcamp.com/',
    ],
}

# ── Main ──────────────────────────────────────────────────────────────────────

with open(ALBUMS_JSON) as f:
    albums = json.load(f)

missing = [a for a in albums if not a.get('cover')]
missing_folders = {a['folder']: a for a in missing}

print(f'Albums missing cover: {len(missing)}')
print()

results = []

all_jobs = {**KNOWN_BC_PAGES}
for folder, candidates in OTHER_BC_CANDIDATES.items():
    if candidates:
        all_jobs[folder] = candidates[0]  # try first candidate

for folder, bc_url in all_jobs.items():
    if folder not in missing_folders:
        continue
    album_path = os.path.join(UNZIP_DIR, folder)
    if not os.path.isdir(album_path):
        print(f'SKIP (no folder): {folder}')
        results.append(('skip', folder, 'no folder'))
        continue

    dest = os.path.join(album_path, 'capa-min.jpg')
    print(f'Fetching: {folder}')
    print(f'  BC page: {bc_url}')

    try:
        img_url = og_image_from_page(bc_url)
        if not img_url:
            print(f'  SKIP: no og:image found')
            results.append(('skip', folder, 'no og:image'))
            continue
        print(f'  Image: {img_url}')
        size = download_and_resize(img_url, dest)
        print(f'  OK: {dest} ({size:,} bytes)')
        results.append(('ok', folder, dest))
    except Exception as e:
        print(f'  ERR: {e}')
        results.append(('err', folder, str(e)))

# Try alternate candidates for failures
failed = {f for s, f, _ in results if s in ('err', 'skip')}
for folder in list(failed):
    candidates = OTHER_BC_CANDIDATES.get(folder, [])
    if len(candidates) <= 1:
        continue
    for bc_url in candidates[1:]:
        album_path = os.path.join(UNZIP_DIR, folder)
        if not os.path.isdir(album_path):
            break
        dest = os.path.join(album_path, 'capa-min.jpg')
        print(f'Retry {folder}: {bc_url}')
        try:
            img_url = og_image_from_page(bc_url)
            if img_url:
                size = download_and_resize(img_url, dest)
                print(f'  OK: {size:,} bytes')
                results = [(s, f, i) for s, f, i in results if f != folder]
                results.append(('ok', folder, dest))
                failed.discard(folder)
                break
        except Exception as e:
            print(f'  ERR: {e}')

print()
print('─' * 60)
ok  = [f for s, f, _ in results if s == 'ok']
err = [(f, i) for s, f, i in results if s == 'err']
skp = [(f, i) for s, f, i in results if s == 'skip']
print(f'OK:   {len(ok)}')
print(f'SKIP: {len(skp)}')
print(f'ERR:  {len(err)}')
if err:
    print('Errors:')
    for f, msg in err:
        print(f'  {f}: {msg}')
if skp:
    print('Skipped:')
    for f, msg in skp:
        print(f'  {f}: {msg}')
