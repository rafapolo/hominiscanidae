#!/usr/bin/env python3
"""
Fetch all missing album covers, trying multiple sources in order:
  1. Known bandcamp page (og:image)
  2. Blogger CDN URL from post .md (upgraded to s1600 or s1280)
  3. bcbits direct URL from post .md (upgraded to _0)

Saves as capa-min.jpg (400x400 JPEG) inside each unzip folder.
"""

import os, re, json, html, unicodedata, urllib.request
from PIL import Image
from io import BytesIO

UNZIP_DIR  = '/Volumes/EXTRA/hominiscanidae/unzips/'
ALBUMS_JSON = '/Users/polux/Projetos/hominiscanidae/js/homi-albums.json'
POSTS_DIR  = '/Users/polux/Projetos/hominiscanidae/posts/'
POSTS_JSON = '/Users/polux/Projetos/hominiscanidae/posts.json'

HEADERS = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}

BLOG_OLD_RE = re.compile(
    r'(https://blogger\.googleusercontent\.com[^\s\)\'"<>]+?)/s\d+/([^\s\)\'"<>]+)',
    re.I
)
BLOG_NEW_RE = re.compile(
    r'https://blogger\.googleusercontent\.com/img/[^\s\)\'"<>]{20,}',
    re.I
)
BCBITS_RE  = re.compile(r'https?://f\d\.bcbits\.com/img/[a-zA-Z0-9_]+\.(?:jpg|png)', re.I)
OGIMG_RE   = re.compile(r'property="og:image"\s+content="([^"]+)"', re.I)
OGIMG_RE2  = re.compile(r'content="([^"]+)"\s+property="og:image"', re.I)


def slugify(s):
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode('ascii').lower()
    return re.sub(r'[^a-z0-9]+', '-', s).strip('-')


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
    if m:
        return re.sub(r'_\d+\.(jpg|png)', r'_0.\1', m.group(0))
    return None


def blogger_url_from_md(md):
    m = BLOG_OLD_RE.search(md)
    if m:
        return f'{m.group(1)}/s1600/{m.group(2)}'
    m = BLOG_NEW_RE.search(md)
    return m.group(0) if m else None


def bcbits_url_from_md(md):
    m = BCBITS_RE.search(md)
    if m:
        return re.sub(r'_\d+\.(jpg|png)', r'_0.\1', m.group(0))
    return None


def download_and_resize(img_url, dest_path, size=400):
    data = fetch(img_url)
    if len(data) < 500:
        raise ValueError(f'Too small ({len(data)} bytes)')
    img = Image.open(BytesIO(data)).convert('RGB')
    img = img.resize((size, size), Image.LANCZOS)
    img.save(dest_path, 'JPEG', quality=90)
    return os.path.getsize(dest_path)


# ── Build slug index ──────────────────────────────────────────────────────────

with open(POSTS_JSON) as f:
    posts_list = json.load(f)

slug_to_post = {}
for p in posts_list:
    m = re.search(r'/(\d{4})/\d{2}/([^/]+)\.html', p.get('url', ''))
    if m:
        slug_to_post[m.group(2)] = p


def find_post_md(folder):
    fsl = slugify(folder)
    # Strip year prefix(es)
    rest = folder
    for _ in range(2):
        m = re.match(r'^\d{4}\s*-\s*(.+)', rest)
        if m:
            rest = m.group(1)
        else:
            break
    rest_sl = slugify(rest)

    for sl in [rest_sl, fsl]:
        if sl in slug_to_post:
            md_path = os.path.join(POSTS_DIR, sl + '.md')
            if os.path.exists(md_path):
                return open(md_path).read()
        for length in [24, 20, 16, 12, 10]:
            pfx = sl[:length]
            if not pfx:
                continue
            for s in slug_to_post:
                if s.startswith(pfx):
                    md_path = os.path.join(POSTS_DIR, s + '.md')
                    if os.path.exists(md_path):
                        return open(md_path).read()
    return None


# ── Source definitions for missing covers ─────────────────────────────────────
# Format: folder → list of ('bc', url) | ('auto',) for auto-detect from post

SOURCES = {
    # Already handled by first run - but included for idempotency
    '2022 - Resp - Hominis Canidae #149 - Outubro': [
        ('bc', 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-149-outubro-2022'),
    ],
    '2023 - Tori - Hominis Canidae #153 - Fevereiro': [
        ('bc', 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-153-fevereiro-2023'),
    ],
    # Auto-detect from post .md
    '2013 - Le Degout - Split com Atrás do Pensamento': [('auto',)],
    "2013 - Ume - 2013-07-23 Maxwell's, Hoboken, NJ": [('auto',)],
    '2016 - (dell.tree) - deus odeia publicitários parte 2': [
        ('bc', 'https://delltree.bandcamp.com/'),
        ('auto',),
    ],
    '2016 - vermes-do-limbo-ep-vrmsxx-2016': [
        ('bc', 'https://vermesdolimbo.bandcamp.com/'),
        ('auto',),
    ],
    '2023 - Trekking At The End Of The World': [('auto',)],
    '2024 - Tatiana Dauster - Origami': [('auto',)],
    '2024 - Tecnoplanta - Tecnicolor Sensação': [
        ('bc', 'https://tecnoplanta.bandcamp.com/album/tecnicolor-sensa-o'),
        ('auto',),
    ],
    # Phantom Pain post is a different album — try bandcamp
    '2016 - Phantom Pain': [
        ('bc', 'https://phantompain.bandcamp.com/'),
    ],
    # These have no post and no known bandcamp — will remain unfound
    '1973 - Cilibrinas Do Eden - Cilibrinas Do Eden': [],
    '2013 - G.R.E.P. Unidos do Faça Você Mesmo - Death Samba': [],
    '2015 - insonia-demo-2015': [('auto',)],
    '2015 - ki nu - Amigo': [],
}


# ── Main ──────────────────────────────────────────────────────────────────────

with open(ALBUMS_JSON) as f:
    albums = json.load(f)

missing = {a['folder'] for a in albums if not a.get('cover')}

print(f'Albums missing cover in JSON: {len(missing)}')
print()

results = {}

for folder, sources in SOURCES.items():
    if folder not in missing:
        continue

    album_path = os.path.join(UNZIP_DIR, folder)
    dest = os.path.join(album_path, 'capa-min.jpg')

    # Skip if already downloaded
    if os.path.exists(dest):
        print(f'SKIP (exists): {folder}')
        results[folder] = ('exists', dest)
        continue

    if not os.path.isdir(album_path):
        print(f'SKIP (no folder): {folder}')
        results[folder] = ('no_folder', '')
        continue

    if not sources:
        print(f'SKIP (no source): {folder}')
        results[folder] = ('no_source', '')
        continue

    print(f'Processing: {folder}')
    ok = False

    for src in sources:
        if src[0] == 'bc':
            bc_url = src[1]
            print(f'  BC page: {bc_url}')
            try:
                img_url = og_image_from_page(bc_url)
                if not img_url:
                    print(f'  → no og:image')
                    continue
                print(f'  → {img_url}')
                sz = download_and_resize(img_url, dest)
                print(f'  OK ({sz:,} bytes)')
                results[folder] = ('ok', dest)
                ok = True
                break
            except Exception as e:
                print(f'  → ERR: {e}')

        elif src[0] == 'auto':
            md = find_post_md(folder)
            if not md:
                print(f'  → no post .md found')
                continue
            img_url = blogger_url_from_md(md) or bcbits_url_from_md(md)
            if not img_url:
                print(f'  → no image URL in .md')
                continue
            print(f'  Post img: {img_url}')
            try:
                sz = download_and_resize(img_url, dest)
                print(f'  OK ({sz:,} bytes)')
                results[folder] = ('ok', dest)
                ok = True
                break
            except Exception as e:
                print(f'  → ERR: {e}')

    if not ok and folder not in results:
        results[folder] = ('failed', '')

print()
print('─' * 60)
ok_count   = sum(1 for s, _ in results.values() if s in ('ok', 'exists'))
fail_count = sum(1 for s, _ in results.values() if s == 'failed')
skip_count = sum(1 for s, _ in results.values() if s in ('no_folder', 'no_source'))
print(f'Done: ok={ok_count}, failed={fail_count}, skipped={skip_count}')
if fail_count:
    print('Failed:')
    for f, (s, _) in results.items():
        if s == 'failed':
            print(f'  {f}')
if skip_count:
    print('No source / no folder:')
    for f, (s, _) in results.items():
        if s in ('no_folder', 'no_source'):
            print(f'  {f}')
