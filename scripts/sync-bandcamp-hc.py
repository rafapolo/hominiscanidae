#!/usr/bin/env python3
"""Download missing Hominis Canidae Bandcamp editions and upload to S3.

Usage:
    python3 scripts/sync-bandcamp-hc.py [--dry-run] [--only NUM]
"""

import os, re, sys, json, shutil, subprocess, argparse
from pathlib import Path
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, TIT2

DOWNLOAD_DIR = Path('/tmp/hc-bandcamp-sync')
S3_ENDPOINT  = 'https://hel1.your-objectstorage.com'
S3_BUCKET    = 'indie'
S3_REGION    = 'hel1'
ENV_FILE     = Path(__file__).parent.parent / '.env'

MISSING_ALBUMS = [
    {'num': 4,   'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-4'},
    {'num': 7,   'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-7'},
    {'num': 8,   'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-8'},
    {'num': 11,  'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-11'},
    {'num': 14,  'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-14'},
    {'num': 16,  'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-16'},
    {'num': 17,  'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-17'},
    {'num': 19,  'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-19'},
    {'num': 20,  'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-20'},
    {'num': 22,  'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-22'},
    {'num': 23,  'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-23'},
    {'num': 24,  'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-24'},
    {'num': 25,  'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-25'},
    {'num': 27,  'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-27'},
    {'num': 32,  'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-32'},
    {'num': 34,  'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-34-mar-o-2013'},
    {'num': 35,  'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-35-abril-2013'},
    {'num': 37,  'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-37-junho-2013'},
    {'num': 38,  'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-38-julho-2013'},
    {'num': 39,  'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-39-agosto-2013'},
    {'num': 41,  'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-41-outubro-2013'},
    {'num': 43,  'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-43-dezembro'},
    {'num': 45,  'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-45-fevereiro'},
    {'num': 52,  'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-52-setembro-2'},
    {'num': 54,  'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-54-novembro'},
    {'num': 55,  'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-55-dezembro-2014'},
    {'num': 59,  'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-59-abril-2015'},
    {'num': 61,  'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-61-junho-2015'},
    {'num': 62,  'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-62-julho-2015'},
    {'num': 67,  'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-67-dezembro-2015'},
    {'num': 68,  'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-68-janeiro-2016-2'},
    {'num': 93,  'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-93-fevereiro-2018'},
    {'num': 102, 'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-102-novembro-2018'},
    {'num': 121, 'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-121-junho-2020'},
    {'num': 162, 'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-162-novembro-2023'},
    {'num': 166, 'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-166-mar-o-2024'},
    {'num': 173, 'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-173-outubro-2024'},
    {'num': 174, 'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-174-novembro-2024'},
    {'num': 177, 'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-177-fevereiro-2025'},
    {'num': 181, 'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-181-junho-2025'},
    {'num': 182, 'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-182-julho-2025'},
    {'num': 183, 'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-183-agosto-2025'},
    {'num': 188, 'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-188-janeiro-2026'},
    {'num': 189, 'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-189-fevereiro-2026'},
    {'num': 190, 'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-190-mar-o-2026'},
    {'num': 3,   'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-3'},
    {'num': 5,   'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-5'},
    {'num': 6,   'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-6'},
    {'num': 9,   'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-9'},
    {'num': 12,  'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-12'},
    {'num': 15,  'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-15'},
    {'num': 145, 'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-145-junho-2022'},
    # Added to cover all ghost albums
    {'num': 36,  'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-36-mar-o-2013'},
    {'num': 48,  'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-48-maio-2014'},
    {'num': 49,  'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-49-junho-2014'},
    {'num': 53,  'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-53-outubro-2014'},
    {'num': 57,  'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-57-fevereiro-2015'},
    {'num': 60,  'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-60-maio-2015'},
    {'num': 63,  'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-63-agosto-2015'},
    {'num': 65,  'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-65-outubro-2015'},
    {'num': 69,  'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-69-fevereiro-2016'},
    {'num': 72,  'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-72-maio-2016'},
    {'num': 78,  'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-78-novembro-2016'},
    {'num': 98,  'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-98-julho-2018'},
    {'num': 101, 'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-101-outubro-2018'},
    {'num': 104, 'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-104-janeiro-2019'},
    {'num': 108, 'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-108-maio-2019'},
    {'num': 113, 'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-113-outubro-2019'},
    {'num': 116, 'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-116-janeiro-2020'},
    {'num': 119, 'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-119-abril-2020'},
    {'num': 125, 'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-125-outubro-2020'},
    {'num': 130, 'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-130-mar-o-2021'},
    {'num': 134, 'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-134-julho-2021'},
    {'num': 135, 'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-135-agosto-2021'},
    {'num': 136, 'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-136-setembro-2021'},
    {'num': 137, 'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-137-outubro-2021'},
    {'num': 138, 'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-138-novembro-2021'},
    {'num': 141, 'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-141-fevereiro-2022'},
    {'num': 143, 'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-143-abril-2022'},
    {'num': 144, 'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-144-maio-2022'},
    {'num': 147, 'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-147-agosto-2022'},
    {'num': 150, 'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-150-novembro-2022'},
    {'num': 151, 'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-151-dezembro-2022'},
    {'num': 156, 'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-156-maio-2023'},
    {'num': 158, 'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-158-julho-2023'},
    {'num': 159, 'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-159-agosto-2023'},
    {'num': 160, 'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-160-setembro-2023'},
    {'num': 161, 'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-161-outubro-2023'},
    {'num': 168, 'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-168-maio-2024'},
    {'num': 169, 'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-169-junho-2024'},
    {'num': 172, 'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-172-setembro-2024'},
    {'num': 176, 'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-176-janeiro-2025'},
    {'num': 184, 'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-184-setembro-2025'},
    {'num': 185, 'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-185-outubro-2025'},
    {'num': 187, 'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-187-dezembro-2025'},
]


def load_env():
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text().splitlines():
        m = re.match(r'^\s*([\w]+)\s*=\s*"?([^"]*)"?\s*$', line)
        if m:
            os.environ.setdefault(m.group(1), m.group(2))


def clean_album_title(title: str) -> str:
    """Remove zero-width chars, trailing ellipsis/dots, and trailing year in parens."""
    t = title.strip()
    t = re.sub(r'[​‌‍﻿]', '', t)
    t = re.sub(r'[\.…]{2,}\s*$', '', t).strip()
    t = re.sub(r'\s*\.\.\.\s*$', '', t).strip()
    t = re.sub(r'\s*\(\d{4}\)\s*$', '', t).strip()
    return t


def strip_artist_prefix(title: str, artist: str) -> str:
    """If ID3 title starts with 'Artist - ', strip it (Bandcamp compilation format)."""
    if not artist:
        return title
    prefix = artist.strip() + ' - '
    if title.startswith(prefix):
        return title[len(prefix):]
    if title.lower().startswith(prefix.lower()):
        return title[len(prefix):]
    return title


def get_album_meta(url: str) -> dict | None:
    """Get album metadata (year, title, track count) without downloading audio."""
    r = subprocess.run(
        ['yt-dlp', url, '--print', '%(release_year)s|%(album)s|%(playlist_count)s',
         '--no-flat-playlist', '-I', '1'],
        capture_output=True, text=True, timeout=60
    )
    if r.returncode != 0:
        return None
    line = r.stdout.strip().splitlines()[0] if r.stdout.strip() else ''
    parts = line.split('|', 2)
    if len(parts) < 2:
        return None
    year_str, album_raw = parts[0], parts[1]
    count_str = parts[2] if len(parts) > 2 else ''
    year = int(year_str) if year_str and year_str != 'NA' and year_str.isdigit() else None
    # Try to extract year from album title if not in metadata
    if not year:
        m = re.search(r'\((\d{4})\)', album_raw)
        if m:
            year = int(m.group(1))
    return {
        'year': year,
        'album': clean_album_title(album_raw),
        'count': int(count_str) if count_str.isdigit() else '?',
    }


def download_album_tracks(url: str, dest_dir: Path) -> bool:
    """Download all tracks as MP3 with embedded metadata and thumbnail."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        ['yt-dlp', url,
         '--extract-audio', '--audio-format', 'mp3', '--audio-quality', '0',
         '--embed-metadata', '--embed-thumbnail',
         '--no-write-playlist-metafiles',
         '-o', str(dest_dir / '%(track_number)02d %(title)s.%(ext)s')],
        capture_output=True, text=True, timeout=3600
    )
    if r.returncode != 0:
        print(f'    yt-dlp error: {r.stderr[-300:]}', file=sys.stderr)
        return False
    return True


def extract_cover_from_mp3(mp3_path: Path, dest: Path) -> bool:
    """Extract embedded album art from an MP3 and resize to 200px wide."""
    tmp = dest.parent / '_cover_extracted.jpg'
    r = subprocess.run(
        ['ffmpeg', '-y', '-i', str(mp3_path), '-an', '-vcodec', 'mjpeg', str(tmp)],
        capture_output=True
    )
    if r.returncode != 0 or not tmp.exists() or tmp.stat().st_size < 1000:
        tmp.unlink(missing_ok=True)
        return False
    r2 = subprocess.run(
        ['ffmpeg', '-y', '-i', str(tmp), '-vf', 'scale=200:-1', '-q:v', '4', str(dest)],
        capture_output=True
    )
    tmp.unlink(missing_ok=True)
    return dest.exists() and dest.stat().st_size > 500


def download_album_cover(url: str, dest: Path, album_dir: Path | None = None) -> bool:
    """Download album cover via yt-dlp; fall back to extracting from MP3 thumbnails."""
    # Try downloading from Bandcamp directly
    for item in ['1', '2', '3']:
        r = subprocess.run(
            ['yt-dlp', url,
             '--write-thumbnail', '--convert-thumbnails', 'jpg',
             '--skip-download', '--playlist-items', item,
             '-o', str(dest.parent / 'cover-orig.%(ext)s')],
            capture_output=True, text=True, timeout=60
        )
        cover_orig = dest.parent / 'cover-orig.jpg'
        if cover_orig.exists() and cover_orig.stat().st_size > 1000:
            r2 = subprocess.run(
                ['ffmpeg', '-y', '-i', str(cover_orig),
                 '-vf', 'scale=200:-1', '-q:v', '4', str(dest)],
                capture_output=True
            )
            cover_orig.unlink(missing_ok=True)
            if dest.exists():
                return True
        cover_orig.unlink(missing_ok=True)

    # Fallback: extract from embedded thumbnail in first MP3
    if album_dir:
        mp3s = sorted(album_dir.glob('*.mp3'))
        for mp3 in mp3s[:3]:
            if extract_cover_from_mp3(mp3, dest):
                return True

    return False


def fix_mp3_tags_and_rename(mp3_path: Path) -> Path:
    """Strip artist prefix from title tag; return new path with clean filename."""
    try:
        audio = MP3(mp3_path, ID3=ID3)
        tags = audio.tags
        if not tags:
            return mp3_path
        title_tag = str(tags.get('TIT2', ''))
        artist_tag = str(tags.get('TPE1', ''))
        clean_title = strip_artist_prefix(title_tag, artist_tag)
        if clean_title != title_tag:
            tags['TIT2'] = TIT2(encoding=3, text=clean_title)
            audio.save()
        # Rebuild filename: keep track number, use "NN - Artist - CleanTitle.mp3"
        stem = mp3_path.stem  # e.g. "01 Ódio Mortal - Violência Inaceitável"
        m = re.match(r'^(\d+)\s+(.*)', stem)
        if m:
            num = m.group(1).zfill(2)
            if artist_tag and clean_title:
                new_name = f"{num} - {artist_tag} - {clean_title}.mp3"
            elif clean_title:
                new_name = f"{num} - {clean_title}.mp3"
            else:
                new_name = mp3_path.name
            # Sanitize for filesystem
            new_name = re.sub(r'[/\x00]', '-', new_name)
            new_path = mp3_path.parent / new_name
            if new_path != mp3_path:
                mp3_path.rename(new_path)
                return new_path
    except Exception as e:
        print(f'    warn: tag fix failed for {mp3_path.name}: {e}', file=sys.stderr)
    return mp3_path


def upload_to_s3(local_dir: Path, s3_key: str, dry_run: bool = False) -> bool:
    """Upload folder to S3 with NFC-normalized keys (macOS HFS+ stores filenames as NFD)."""
    import unicodedata
    env = {
        **os.environ,
        'AWS_ACCESS_KEY_ID': os.environ.get('AWS_ACCESS_KEY_ID', ''),
        'AWS_SECRET_ACCESS_KEY': os.environ.get('AWS_SECRET_ACCESS_KEY', ''),
    }

    s3_key_nfc = unicodedata.normalize('NFC', s3_key)
    ok = True

    for f in sorted(local_dir.iterdir()):
        if not f.is_file():
            continue
        if f.suffix == '.tmp':
            continue
        fname_nfc = unicodedata.normalize('NFC', f.name)
        s3_dest = f's3://{S3_BUCKET}/{s3_key_nfc}/{fname_nfc}'
        cmd = [
            'aws', 's3', 'cp', str(f), s3_dest,
            '--endpoint-url', S3_ENDPOINT,
            '--region', S3_REGION,
        ]
        if dry_run:
            print(f'(dryrun) upload: {f.name} to {s3_dest}')
            continue
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            print(f'  upload error for {f.name}: {r.stderr[-200:]}', file=sys.stderr)
            ok = False

    return ok


def process_album(item: dict, dry_run: bool = False) -> bool:
    num = item['num']
    url = item['url']
    print(f'\n{"="*60}')
    print(f'HC #{num}: {url}')

    # Step 1: get album metadata
    print('  fetching metadata...')
    meta = get_album_meta(url)
    if not meta:
        print('  ERROR: could not fetch metadata, skipping')
        return False

    year = meta['year'] or 'XXXX'
    album_title = meta['album']
    print(f'  year={year}  album="{album_title}"  tracks={meta["count"]}')

    folder_name = f"{year} - Hominis Canidae - {album_title}"
    # Sanitize folder name
    folder_name = re.sub(r'[:\x00]', '-', folder_name)
    local_dir = DOWNLOAD_DIR / folder_name

    # Skip if already uploaded (check if local dir already has mp3s)
    if local_dir.exists() and list(local_dir.glob('*.mp3')):
        print(f'  already downloaded → {folder_name}')
    else:
        # Step 2: download tracks
        print(f'  downloading tracks to {local_dir.name}...')
        if not download_album_tracks(url, local_dir):
            print('  ERROR: download failed')
            return False

        # Step 3: fix tags and rename files
        mp3s = sorted(local_dir.glob('*.mp3'))
        print(f'  fixing tags for {len(mp3s)} tracks...')
        for mp3 in mp3s:
            fix_mp3_tags_and_rename(mp3)

    # Step 4: album cover
    capa = local_dir / 'capa-min.jpg'
    if not capa.exists():
        print('  downloading cover...')
        if not download_album_cover(url, capa, album_dir=local_dir):
            print('  warn: cover download FAILED — album will be missing cover')
        else:
            print(f'  cover saved ({capa.stat().st_size // 1024}KB)')

    # Remove per-track jpg thumbnails (not capa-min.jpg)
    for jpg in local_dir.glob('*.jpg'):
        if jpg.name != 'capa-min.jpg':
            jpg.unlink()

    # Step 5: upload to S3
    print(f'  uploading to s3://{S3_BUCKET}/{folder_name}/ ...')
    if not upload_to_s3(local_dir, folder_name, dry_run):
        print('  ERROR: upload failed')
        return False

    print(f'  done: {folder_name}')
    return True


def verify_and_fix_covers(dry_run: bool = False):
    """Check all synced albums for missing covers and fix them."""
    print('Verifying covers in all synced albums...')
    missing = []
    for album_dir in sorted(DOWNLOAD_DIR.iterdir()):
        if not album_dir.is_dir():
            continue
        capa = album_dir / 'capa-min.jpg'
        if not capa.exists() or capa.stat().st_size < 500:
            missing.append(album_dir)
            print(f'  MISSING cover: {album_dir.name}')
        else:
            print(f'  OK ({capa.stat().st_size // 1024}KB): {album_dir.name}')

    if not missing:
        print('All albums have covers.')
        return True

    print(f'\nFixing {len(missing)} missing covers...')
    # Find matching URL for each album
    for album_dir in missing:
        # Match by folder name to MISSING_ALBUMS entry
        matched = None
        for item in MISSING_ALBUMS:
            num = item['num']
            if f'#{num}' in album_dir.name or f'HC{num:03d}' in album_dir.name:
                matched = item
                break
        if not matched:
            # Try by folder name HC number
            m = re.search(r'Hominis Canidae #(\d+)', album_dir.name)
            if m:
                n = int(m.group(1))
                matched = next((x for x in MISSING_ALBUMS if x['num'] == n), None)
        if matched:
            print(f'  Fixing cover for {album_dir.name}...')
            capa = album_dir / 'capa-min.jpg'
            if download_album_cover(matched['url'], capa, album_dir=album_dir):
                print(f'    OK ({capa.stat().st_size // 1024}KB)')
                if not dry_run:
                    # Re-upload capa-min.jpg
                    folder_name = album_dir.name
                    upload_to_s3(album_dir, folder_name, dry_run=False)
            else:
                print(f'    FAILED')
        else:
            print(f'  Could not find URL for {album_dir.name}')
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--only', type=int, help='Process only this HC edition number')
    parser.add_argument('--start-from', type=int, help='Start from this HC edition number')
    parser.add_argument('--verify-covers', action='store_true', help='Check and fix missing covers')
    args = parser.parse_args()

    load_env()
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    if args.verify_covers:
        verify_and_fix_covers(dry_run=args.dry_run)
        return

    albums = MISSING_ALBUMS
    if args.only:
        albums = [a for a in albums if a['num'] == args.only]
    elif args.start_from:
        albums = [a for a in albums if a['num'] >= args.start_from]

    print(f'Processing {len(albums)} album(s)')
    if args.dry_run:
        print('DRY RUN mode - S3 uploads will be simulated')

    ok, fail = [], []
    for item in albums:
        if process_album(item, dry_run=args.dry_run):
            ok.append(item['num'])
        else:
            fail.append(item['num'])

    print(f'\n{"="*60}')
    print(f'Done: {len(ok)} succeeded, {len(fail)} failed')
    if ok:
        print(f'  OK:   {ok}')
    if fail:
        print(f'  FAIL: {fail}')
        sys.exit(1)


if __name__ == '__main__':
    main()
# Extra albums added after initial sync
EXTRA_ALBUMS = [
    {'num': 3,   'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-3'},
    {'num': 5,   'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-5'},
    {'num': 6,   'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-6'},
    {'num': 9,   'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-9'},
    {'num': 12,  'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-12'},
    {'num': 15,  'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-15'},
    {'num': 145, 'url': 'https://hominiscanidae.bandcamp.com/album/hominis-canidae-145-junho-2022'},
]
