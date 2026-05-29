#!/usr/bin/env python3
"""
Fix unzip folder names: add year prefix and normalize to "YYYY - Artist - Album".

Sources of truth (in priority order):
  Year:        (YYYY) in download filename > post URL year
  Artist/Album: download link filename > Bandcamp URL > slug split

Usage:
  python3 fix_unzip_names.py            # dry-run: print proposed renames
  python3 fix_unzip_names.py --apply    # apply renames
  python3 fix_unzip_names.py --uncertain  # show only uncertain cases
"""

import json, os, re, sys, unicodedata
from pathlib import Path

try:
    from mutagen.id3 import ID3 as MutagenID3
    HAS_MUTAGEN = True
except ImportError:
    HAS_MUTAGEN = False

POSTS_JSON = '/Users/polux/Projetos/hominiscanidae/posts.json'
POSTS_DIR  = '/Users/polux/Projetos/hominiscanidae/posts/'
UNZIP_DIR  = '/Volumes/EXTRA/hominiscanidae/unzips/'

APPLY     = '--apply' in sys.argv
UNCERTAIN = '--uncertain' in sys.argv

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ARTICLES = {'a', 'an', 'the', 'o', 'a', 'os', 'as', 'um', 'uma', 'uns', 'umas',
             'de', 'do', 'da', 'dos', 'das', 'e', 'y', 'el', 'la', 'los', 'las'}

def slugify(s):
    s = unicodedata.normalize('NFKD', s)
    s = s.encode('ascii', 'ignore').decode('ascii')
    s = s.lower()
    s = re.sub(r'[^a-z0-9]+', '-', s)
    return s.strip('-')

def title_from_slug(slug):
    return ' '.join(w.capitalize() for w in slug.split('-') if w)

def clean(s):
    s = s.strip(' .*_')
    s = re.sub(r'\s+', ' ', s)
    return s

def safe_folder(s):
    s = re.sub(r'[/\x00]', '-', s)
    s = s.strip('. ')
    return s or 'Unknown'

def strip_year(s):
    """Remove trailing (YYYY) from name. Return (name, year_or_None)."""
    m = re.search(r'\s*\((\d{4})\)\s*$', s)
    if m and 1960 <= int(m.group(1)) <= 2030:
        return s[:m.start()].strip(), m.group(1)
    return s, None

# ---------------------------------------------------------------------------
# Load posts
# ---------------------------------------------------------------------------

with open(POSTS_JSON) as f:
    posts = json.load(f)

slug_to_post = {}
for p in posts:
    url = p.get('url', '')
    m = re.search(r'/(\d{4})/\d{2}/([^/]+)\.html', url)
    if m:
        slug_to_post[m.group(2)] = {**p, 'year': m.group(1)}

# ---------------------------------------------------------------------------
# Parse .md content
# ---------------------------------------------------------------------------

_md_cache = {}
def load_md(slug):
    if slug not in _md_cache:
        path = os.path.join(POSTS_DIR, slug + '.md')
        try:
            _md_cache[slug] = open(path).read()
        except FileNotFoundError:
            _md_cache[slug] = ''
    return _md_cache[slug]

def extract_download_name(md):
    """
    Return the raw download filename (with extension) from .md content.
    Handles:
      [FILENAME.ext](url)          — display text has extension
      [**FILENAME.ext**](url)      — bold display text in brackets
      **FILENAME.ext**             — standalone bold (no link)
    Returns the stem (without extension), or None.
    """
    EXT = r'\.(?:rar|zip|7z)'

    # Bold inside brackets: [**NAME.ext**](url) or [**NAME.ext**]
    for m in re.finditer(r'\[\*\*([^\*\n]{2,120}?' + EXT + r')\*\*\]', md, re.I):
        cand = m.group(1).strip()
        if not re.search(r'https?://', cand):
            return re.sub(EXT + r'$', '', cand, flags=re.I).strip()

    # Plain display text in brackets: [NAME.ext](url)
    for m in re.finditer(r'\[([^\]\n]{2,120}?' + EXT + r')\]', md, re.I):
        cand = m.group(1).strip('*_ ')
        if not re.search(r'https?://', cand):
            return re.sub(EXT + r'$', '', cand, flags=re.I).strip()

    # URL itself ends in extension: [ANY](url.ext)
    for m in re.finditer(r'\[([^\]\n]{2,120}?)\]\([^)]+' + EXT + r'[^)]*\)', md, re.I):
        cand = m.group(1).strip('*_ ')
        if not re.search(r'(https?://|\.jpg|\.png|\.gif)', cand, re.I):
            return re.sub(EXT + r'$', '', cand, flags=re.I).strip()

    # Standalone bold: **NAME.ext**
    for m in re.finditer(r'\*\*([^\*\n]{2,120}?' + EXT + r')\*\*', md, re.I):
        return m.group(1).strip()

    return None

def extract_bandcamp(md):
    """Return (artist_handle, album_slug) or (None, None)."""
    m = re.search(r'https?://([a-z0-9][a-z0-9-]+)\.bandcamp\.com/album/([a-z0-9][a-z0-9-]+)', md)
    if m:
        return m.group(1), m.group(2)
    return None, None

# ---------------------------------------------------------------------------
# Album-in-slug split
# ---------------------------------------------------------------------------

def find_album_in_slug(post_slug, album_name):
    """
    Given album_name (may have leading articles), find where album starts in
    post_slug and return (artist_slug, clean_album_name).
    Returns (None, None) if not found.
    """
    album_stripped, _ = strip_year(album_name)
    album_slug = slugify(album_stripped)
    album_words = album_slug.split('-')

    def _first_valid(target):
        """Find first occurrence with non-empty artist prefix."""
        start = 0
        while True:
            idx = post_slug.find(target, start)
            if idx < 0:
                break
            if idx > 0:
                return post_slug[:idx].strip('-')
            start = idx + 1
        return None

    # Try full album slug
    r = _first_valid(album_slug)
    if r is not None:
        return r, album_stripped

    # Strip leading articles one at a time and retry with progressively shorter prefix
    while album_words and album_words[0] in ARTICLES:
        album_words = album_words[1:]
        if album_words:
            trimmed = '-'.join(album_words)
            r = _first_valid(trimmed)
            if r is not None:
                return r, album_stripped

    # Try progressively shorter prefixes (12, 8, 5 chars) of article-stripped slug
    if album_words:
        joined = '-'.join(album_words)
        for length in (12, 8, 5):
            short = joined[:min(length, len(joined))]
            if len(short) >= 4:
                r = _first_valid(short)
                if r is not None:
                    return r, album_stripped

        # Try first significant word (≥4 chars, skip articles)
        for w in album_words:
            if len(w) >= 4 and w not in ARTICLES:
                pat = '-' + w  # word-boundary: preceded by hyphen
                idx = post_slug.find(pat)
                if idx > 0:
                    return post_slug[:idx].strip('-'), album_stripped
                break  # only try first significant word

    return None, None

# ---------------------------------------------------------------------------
# Strategy: slug-like folder
# ---------------------------------------------------------------------------

def name_for_slug_folder(post_slug, year, md):
    """
    Returns (year, artist, album) or (year, None, title_cased_slug).
    """
    dl_raw = extract_download_name(md)
    bc_art, bc_alb = extract_bandcamp(md)

    if dl_raw:
        dl_clean, yr_in = strip_year(dl_raw)
        use_year = yr_in or year

        if ' - ' in dl_clean:
            # "Artist - Album" already split in filename
            parts = dl_clean.split(' - ', 1)
            return use_year, parts[0].strip(), parts[1].strip()

        # Album only in filename; try to find split in slug
        artist_slug, album = find_album_in_slug(post_slug, dl_clean)
        if artist_slug:
            artist = title_from_slug(artist_slug)
            return use_year, artist, album

        # Can't find album in slug; use download filename as album title
        # and slug-derived artist (try to guess: common slug prefix if multiple albums)
        return use_year, None, dl_clean

    if bc_art and bc_alb:
        album = title_from_slug(bc_alb)
        artist_slug, _ = find_album_in_slug(post_slug, album)
        if artist_slug:
            return year, title_from_slug(artist_slug), album
        return year, title_from_slug(bc_art), album

    return year, None, None

# ---------------------------------------------------------------------------
# Strategy: "Artist - Album" folder (needs year)
# ---------------------------------------------------------------------------

def name_for_artist_album_folder(folder, year, md):
    parts = folder.split(' - ', 1)
    artist = clean(parts[0])
    album  = clean(parts[1]) if len(parts) > 1 else folder

    # Year from download filename overrides post year
    dl_raw = extract_download_name(md)
    if dl_raw:
        _, yr_in = strip_year(dl_raw)
        if yr_in:
            year = yr_in

    return year, artist, album

# ---------------------------------------------------------------------------
# Match non-slug folders to posts
# ---------------------------------------------------------------------------

def find_post_for_folder(folder):
    """Tries slugified artist+album matching. Returns (post_slug, post) or (None,None)."""
    if ' - ' in folder:
        parts = folder.split(' - ', 1)
        art_sl = slugify(parts[0])
        alb_sl = slugify(parts[1])
        a_len = min(8, len(art_sl))

        # Phase 1: artist prefix + progressively shorter album fragment
        for b_try in [min(8, len(alb_sl)), 6, 5, 4]:
            if b_try < 4:
                break
            alb_frag = alb_sl[:b_try]
            best = None
            for slug, post in slug_to_post.items():
                if slug.startswith(art_sl[:a_len]) and alb_frag in slug:
                    if best is None or len(slug) < len(best[0]):
                        best = (slug, post)
            if best:
                return best

        # Phase 2: artist slug as full prefix (any album after it)
        for slug, post in slug_to_post.items():
            if slug.startswith(art_sl + '-') and len(slug) > len(art_sl) + 1:
                return slug, post

        # Phase 3: artist prefix only
        for slug, post in slug_to_post.items():
            if slug.startswith(art_sl[:a_len]):
                return slug, post

        # Phase 4: first word of artist (≥4 chars) + album fragment
        art_first = art_sl.split('-')[0]
        if len(art_first) >= 4:
            for b_try in [min(6, len(alb_sl)), 4]:
                if b_try < 4:
                    break
                alb_frag = alb_sl[:b_try]
                for slug, post in slug_to_post.items():
                    if slug.startswith(art_first) and alb_frag in slug:
                        return slug, post

        # Phase 5: album fragment anywhere in slug (very loose, last resort)
        if len(alb_sl) >= 6:
            alb_frag = alb_sl[:6]
            # Also try any keyword from the folder (for reordered slugs like ex-exus-bukake...)
            keywords = [slugify(w) for w in re.split(r'[\s&,+]+', folder) if len(w) >= 5]
            for slug, post in slug_to_post.items():
                if alb_frag in slug and any(k in slug for k in keywords):
                    return slug, post

    else:
        fsl = slugify(folder)
        if fsl in slug_to_post:
            return fsl, slug_to_post[fsl]
        # Prefix match (handles belonave → belonave-belonave-2015)
        for slug, post in slug_to_post.items():
            if slug.startswith(fsl + '-') or slug.startswith(fsl[:min(10, len(fsl))]):
                return slug, post
        # Keyword match for special characters / reordered slugs
        keywords = [slugify(w) for w in re.split(r'[\s&,+\[\]]+', folder) if len(slugify(w)) >= 4]
        for slug, post in slug_to_post.items():
            if sum(1 for k in keywords if k in slug) >= min(2, len(keywords)):
                return slug, post

    return None, None

def find_post_by_content(needle):
    """Slow: grep all .md files. Returns (post_slug, post) or (None,None)."""
    needle_l = needle.lower()
    for fn in os.listdir(POSTS_DIR):
        if not fn.endswith('.md'):
            continue
        slug = fn[:-3]
        if slug not in slug_to_post:
            continue
        try:
            if needle_l in open(os.path.join(POSTS_DIR, fn)).read().lower():
                return slug, slug_to_post[slug]
        except Exception:
            pass
    return None, None

def id3_meta(folder_path):
    """Read year, artist, album from the first MP3 in folder_path via ID3 tags.
    Returns (year_int_or_None, artist_or_None, album_or_None).
    """
    if not HAS_MUTAGEN:
        return None, None, None
    mp3s = sorted(Path(folder_path).glob('*.mp3'))
    if not mp3s:
        return None, None, None
    try:
        tags = MutagenID3(mp3s[0])
        year = None
        for frame in ('TDRC', 'TYER'):
            if frame in tags:
                raw = str(tags[frame]).strip()[:4]
                if raw.isdigit() and 1950 <= int(raw) <= 2030:
                    year = int(raw)
                    break
        artist = str(tags['TPE1']).strip() if 'TPE1' in tags else None
        album  = str(tags['TALB']).strip() if 'TALB' in tags else None
        return year, artist, album
    except Exception:
        return None, None, None

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

YEAR_RE      = re.compile(r'^\d{4}\s*[-–]')
YEAR_PAREN   = re.compile(r'\((\d{4})\)')  # also catches "Artist - Album (YYYY)"
SLUG_RE      = re.compile(r'^[a-z0-9][a-z0-9-]+$')
SKIP         = {'.DS_Store', 'Artist - Album', 'to_fix', 'acervo.json'}

# Collect folders from top-level unzips/ and from unzips/to_fix/
def _scan_dir(base, prefix=''):
    result = []
    try:
        for name in sorted(os.listdir(base)):
            if name in SKIP or name.startswith('.') or name.startswith('_'):
                continue
            path = os.path.join(base, name)
            if os.path.isdir(path):
                result.append((prefix + name, path))
    except Exception:
        pass
    return result

top_level = _scan_dir(UNZIP_DIR)
to_fix    = _scan_dir(os.path.join(UNZIP_DIR, 'to_fix'), prefix='to_fix/')
all_folders = top_level + to_fix

todo = [(rel, path) for rel, path in all_folders
        if not YEAR_RE.match(os.path.basename(rel))
        and not YEAR_PAREN.search(os.path.basename(rel))]

renames   = []   # (rel_path, folder_path, new_basename, confident)
uncertain = []   # (rel_path, reason)

for rel, folder_path in todo:
    folder = os.path.basename(rel)   # just the directory name, no prefix
    subfolder = rel != folder        # True if inside to_fix/

    # --- Slug-like ---
    if SLUG_RE.match(folder):
        if folder in slug_to_post:
            post_slug_key = folder
        else:
            # Prefix match (e.g. 'belonave' → 'belonave-belonave-2015')
            post_slug_key = None
            for slug in slug_to_post:
                if slug.startswith(folder + '-'):
                    post_slug_key = slug
                    break

        if post_slug_key:
            post  = slug_to_post[post_slug_key]
            year  = post['year']
            md    = load_md(post_slug_key)
            use_year, artist, album = name_for_slug_folder(post_slug_key, year, md)

            if artist and album:
                new = safe_folder(f'{use_year} - {artist} - {album}')
                renames.append((rel, folder_path, new, True))
            elif album:
                new = safe_folder(f'{use_year} - {album}')
                renames.append((rel, folder_path, new, False))
                uncertain.append((rel, f'no artist split → {new}'))
            else:
                new = safe_folder(f'{use_year} - {title_from_slug(folder)}')
                renames.append((rel, folder_path, new, False))
                uncertain.append((rel, f'no info → {new}'))
        else:
            # No post found — try ID3 tags
            id3_year, id3_artist, id3_album = id3_meta(folder_path)
            if id3_year and id3_artist and id3_album:
                new = safe_folder(f'{id3_year} - {id3_artist} - {id3_album}')
                renames.append((rel, folder_path, new, True))
            elif id3_year:
                new = safe_folder(f'{id3_year} - {title_from_slug(folder)}')
                renames.append((rel, folder_path, new, False))
                uncertain.append((rel, f'id3 year only → {new}'))
            else:
                uncertain.append((rel, 'slug-like but no matching post and no ID3 year'))
        continue

    # --- Artist - Album or misc ---
    if ' - ' in folder:
        post_slug, post = find_post_for_folder(folder)
        if post:
            year = post['year']
            md   = load_md(post_slug)
            use_year, artist, album = name_for_artist_album_folder(folder, year, md)
            new  = safe_folder(f'{use_year} - {artist} - {album}')
            renames.append((rel, folder_path, new, True))
        else:
            # No post found — try ID3 tags
            id3_year, id3_artist, id3_album = id3_meta(folder_path)
            if id3_year:
                use_year, artist, album = name_for_artist_album_folder(folder, str(id3_year), None)
                new = safe_folder(f'{use_year} - {artist} - {album}')
                renames.append((rel, folder_path, new, False))
                uncertain.append((rel, f'id3 year (no post) → {new}'))
            else:
                uncertain.append((rel, 'Artist-Album: could not find post and no ID3 year'))
    else:
        # Misc single-name
        post_slug, post = find_post_for_folder(folder)
        if not post:
            post_slug, post = find_post_by_content(folder)
        if post:
            year  = post['year']
            md    = load_md(post_slug)
            dl_raw = extract_download_name(md)
            if dl_raw and ' - ' in dl_raw:
                dl_clean, yr_in = strip_year(dl_raw)
                use_year = yr_in or year
                parts = dl_clean.split(' - ', 1)
                new = safe_folder(f'{use_year} - {parts[0].strip()} - {parts[1].strip()}')
            elif dl_raw:
                dl_clean, yr_in = strip_year(dl_raw)
                use_year = yr_in or year
                artist_slug, album = find_album_in_slug(post_slug, dl_clean)
                if artist_slug:
                    new = safe_folder(f'{use_year} - {title_from_slug(artist_slug)} - {album}')
                else:
                    new = safe_folder(f'{use_year} - {folder}')
            else:
                new = safe_folder(f'{year} - {folder}')
            renames.append((rel, folder_path, new, True))
        else:
            # No post found — try ID3 tags
            id3_year, id3_artist, id3_album = id3_meta(folder_path)
            if id3_year and id3_artist and id3_album:
                new = safe_folder(f'{id3_year} - {id3_artist} - {id3_album}')
                renames.append((rel, folder_path, new, True))
            elif id3_year:
                new = safe_folder(f'{id3_year} - {folder}')
                renames.append((rel, folder_path, new, False))
                uncertain.append((rel, f'id3 year only → {new}'))
            else:
                uncertain.append((rel, 'misc: no post found and no ID3 year'))

# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

confident   = [(r, p, n) for r, p, n, c in renames if c and os.path.basename(r) != n]
approx      = [(r, p, n) for r, p, n, c in renames if not c and os.path.basename(r) != n]
same        = sum(1 for r, p, n, _ in renames if os.path.basename(r) == n)

if not UNCERTAIN:
    print(f'=== Confident renames ({len(confident)}) ===')
    for rel, _, new in confident:
        print(f'  [{rel}]\n   → [{new}]')

    print(f'\n=== Approximate renames (year only, no artist/album split) ({len(approx)}) ===')
    for rel, _, new in approx:
        print(f'  [{rel}]\n   → [{new}]')

    print(f'\n  ({same} already correct)')

print(f'\n=== Uncertain / unmatched ({len(uncertain)}) ===')
for rel, reason in uncertain:
    print(f'  [{rel}]  — {reason}')

if APPLY:
    print('\n=== Applying renames ===')
    applied = errors = skipped = 0
    for rel, folder_path, new, _ in renames:
        if os.path.basename(rel) == new:
            continue
        dst = os.path.join(os.path.dirname(folder_path), new)
        if os.path.exists(dst):
            print(f'  SKIP (exists): {rel!r} → {new!r}')
            skipped += 1
            continue
        try:
            os.rename(folder_path, dst)
            applied += 1
            print(f'  OK  {rel} → {new}')
        except Exception as e:
            print(f'  ERROR: {rel!r}: {e}')
            errors += 1
    print(f'  Applied: {applied}, Skipped: {skipped}, Errors: {errors}')
else:
    total = len(confident) + len(approx)
    print(f'\nDry run: {total} renames pending. Run with --apply to rename.')
