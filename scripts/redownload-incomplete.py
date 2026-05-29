#!/usr/bin/env python3
"""Re-download incomplete HC editions (fewer tracks than Bandcamp) and replace in S3.

Runs downloads in parallel, compares track counts, uploads replacements.

Usage:
    python3 scripts/redownload-incomplete.py [--workers N] [--dry-run] [--only NUM]
"""

import argparse, gzip, json, os, re, sys, unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, TIT2

DOWNLOAD_DIR = Path('/tmp/hc-replace')
S3_ENDPOINT  = 'https://hel1.your-objectstorage.com'
S3_BUCKET    = 'indie'
S3_REGION    = 'hel1'
ENV_FILE     = Path(__file__).parent.parent / '.env'
JSON_GZ      = Path(__file__).parent.parent / 'js' / 'homi-albums.json.gz'

INCOMPLETE = [
    {"num": 33,  "url": "https://hominiscanidae.bandcamp.com/album/hominis-canidae-33-fevereiro-2013"},
    {"num": 36,  "url": "https://hominiscanidae.bandcamp.com/album/hominis-canidae-36-mar-o-2013"},
    {"num": 42,  "url": "https://hominiscanidae.bandcamp.com/album/hominis-canidae-42-novembro"},
    {"num": 46,  "url": "https://hominiscanidae.bandcamp.com/album/hominis-canidae-46-mar-o"},
    {"num": 47,  "url": "https://hominiscanidae.bandcamp.com/album/hominis-canidae-47-abril"},
    {"num": 48,  "url": "https://hominiscanidae.bandcamp.com/album/hominis-canidae-48-maio-2014"},
    {"num": 49,  "url": "https://hominiscanidae.bandcamp.com/album/hominis-canidae-49-junho-2014"},
    {"num": 51,  "url": "https://hominiscanidae.bandcamp.com/album/hominis-canidae-51-agosto"},
    {"num": 53,  "url": "https://hominiscanidae.bandcamp.com/album/hominis-canidae-53-outubro-2014"},
    {"num": 57,  "url": "https://hominiscanidae.bandcamp.com/album/hominis-canidae-57-fevereiro-2015"},
    {"num": 60,  "url": "https://hominiscanidae.bandcamp.com/album/hominis-canidae-60-maio-2015"},
    {"num": 63,  "url": "https://hominiscanidae.bandcamp.com/album/hominis-canidae-63-agosto-2015"},
    {"num": 65,  "url": "https://hominiscanidae.bandcamp.com/album/hominis-canidae-65-outubro-2015"},
    {"num": 69,  "url": "https://hominiscanidae.bandcamp.com/album/hominis-canidae-69-fevereiro-2016"},
    {"num": 72,  "url": "https://hominiscanidae.bandcamp.com/album/hominis-canidae-72-maio-2016"},
    {"num": 76,  "url": "https://hominiscanidae.bandcamp.com/album/hominis-canidae-76-setembro"},
    {"num": 78,  "url": "https://hominiscanidae.bandcamp.com/album/hominis-canidae-78-novembro-2016"},
    {"num": 82,  "url": "https://hominiscanidae.bandcamp.com/album/hominiscanidae-82-mar-o-2017"},
    {"num": 98,  "url": "https://hominiscanidae.bandcamp.com/album/hominis-canidae-98-julho-2018"},
    {"num": 101, "url": "https://hominiscanidae.bandcamp.com/album/hominis-canidae-101-outubro-2018"},
    {"num": 104, "url": "https://hominiscanidae.bandcamp.com/album/hominis-canidae-104-janeiro-2019"},
    {"num": 108, "url": "https://hominiscanidae.bandcamp.com/album/hominis-canidae-108-maio-2019"},
    {"num": 113, "url": "https://hominiscanidae.bandcamp.com/album/hominis-canidae-113-outubro-2019"},
    {"num": 116, "url": "https://hominiscanidae.bandcamp.com/album/hominis-canidae-116-janeiro-2020"},
    {"num": 119, "url": "https://hominiscanidae.bandcamp.com/album/hominis-canidae-119-abril-2020"},
    {"num": 125, "url": "https://hominiscanidae.bandcamp.com/album/hominis-canidae-125-outubro-2020"},
    {"num": 130, "url": "https://hominiscanidae.bandcamp.com/album/hominis-canidae-130-mar-o-2021"},
    {"num": 134, "url": "https://hominiscanidae.bandcamp.com/album/hominis-canidae-134-julho-2021"},
    {"num": 135, "url": "https://hominiscanidae.bandcamp.com/album/hominis-canidae-135-agosto-2021"},
    {"num": 136, "url": "https://hominiscanidae.bandcamp.com/album/hominis-canidae-136-setembro-2021"},
    {"num": 137, "url": "https://hominiscanidae.bandcamp.com/album/hominis-canidae-137-outubro-2021"},
    {"num": 138, "url": "https://hominiscanidae.bandcamp.com/album/hominis-canidae-138-novembro-2021"},
    {"num": 141, "url": "https://hominiscanidae.bandcamp.com/album/hominis-canidae-141-fevereiro-2022"},
    {"num": 143, "url": "https://hominiscanidae.bandcamp.com/album/hominis-canidae-143-abril-2022"},
    {"num": 144, "url": "https://hominiscanidae.bandcamp.com/album/hominis-canidae-144-maio-2022"},
    {"num": 147, "url": "https://hominiscanidae.bandcamp.com/album/hominis-canidae-147-agosto-2022"},
    {"num": 150, "url": "https://hominiscanidae.bandcamp.com/album/hominis-canidae-150-novembro-2022"},
    {"num": 151, "url": "https://hominiscanidae.bandcamp.com/album/hominis-canidae-151-dezembro-2022"},
    {"num": 156, "url": "https://hominiscanidae.bandcamp.com/album/hominis-canidae-156-maio-2023"},
    {"num": 158, "url": "https://hominiscanidae.bandcamp.com/album/hominis-canidae-158-julho-2023"},
    {"num": 159, "url": "https://hominiscanidae.bandcamp.com/album/hominis-canidae-159-agosto-2023"},
    {"num": 160, "url": "https://hominiscanidae.bandcamp.com/album/hominis-canidae-160-setembro-2023"},
    {"num": 161, "url": "https://hominiscanidae.bandcamp.com/album/hominis-canidae-161-outubro-2023"},
    {"num": 168, "url": "https://hominiscanidae.bandcamp.com/album/hominis-canidae-168-maio-2024"},
    {"num": 169, "url": "https://hominiscanidae.bandcamp.com/album/hominis-canidae-169-junho-2024"},
    {"num": 172, "url": "https://hominiscanidae.bandcamp.com/album/hominis-canidae-172-setembro-2024"},
    {"num": 176, "url": "https://hominiscanidae.bandcamp.com/album/hominis-canidae-176-janeiro-2025"},
    {"num": 184, "url": "https://hominiscanidae.bandcamp.com/album/hominis-canidae-184-setembro-2025"},
    {"num": 185, "url": "https://hominiscanidae.bandcamp.com/album/hominis-canidae-185-outubro-2025"},
    {"num": 187, "url": "https://hominiscanidae.bandcamp.com/album/hominis-canidae-187-dezembro-2025"},
]


def load_env():
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text().splitlines():
        m = re.match(r'^\s*([\w]+)\s*=\s*"?([^"]*)"?\s*$', line)
        if m:
            os.environ.setdefault(m.group(1), m.group(2))


def clean_album_title(title: str) -> str:
    t = title.strip()
    t = re.sub(r'[​‌‍﻿]', '', t)
    t = re.sub(r'[\.…]{2,}\s*$', '', t).strip()
    t = re.sub(r'\s*\.\.\.\s*$', '', t).strip()
    t = re.sub(r'\s*\(\d{4}\)\s*$', '', t).strip()
    return t


def strip_artist_prefix(title: str, artist: str) -> str:
    if not artist:
        return title
    prefix = artist.strip() + ' - '
    if title.startswith(prefix):
        return title[len(prefix):]
    if title.lower().startswith(prefix.lower()):
        return title[len(prefix):]
    return title


def get_bandcamp_track_count(url: str) -> int:
    import subprocess
    r = subprocess.run(
        ['yt-dlp', url, '--print', '%(playlist_count)s', '--no-flat-playlist', '-I', '1'],
        capture_output=True, text=True, timeout=30
    )
    try:
        return int(r.stdout.strip().splitlines()[0])
    except Exception:
        return 0


def get_album_meta(url: str) -> dict | None:
    import subprocess, time, random
    time.sleep(random.uniform(1, 4))  # stagger to avoid rate-limiting
    r = subprocess.run(
        ['yt-dlp', url, '--print', '%(release_year)s|%(album)s|%(playlist_count)s',
         '--no-flat-playlist', '-I', '1',
         '--sleep-interval', '2', '--max-sleep-interval', '5'],
        capture_output=True, text=True, timeout=120
    )
    if r.returncode != 0:
        return None
    line = r.stdout.strip().splitlines()[0] if r.stdout.strip() else ''
    parts = line.split('|', 2)
    if len(parts) < 2:
        return None
    year_str, album_raw = parts[0], parts[1]
    count_str = parts[2] if len(parts) > 2 else ''
    year = int(year_str) if year_str and year_str.isdigit() else None
    if not year:
        m = re.search(r'\((\d{4})\)', album_raw)
        if m:
            year = int(m.group(1))
    return {
        'year': year,
        'album': clean_album_title(album_raw),
        'count': int(count_str) if count_str.isdigit() else 0,
    }


def download_tracks(url: str, dest_dir: Path) -> bool:
    import subprocess
    dest_dir.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        ['yt-dlp', url,
         '--extract-audio', '--audio-format', 'mp3', '--audio-quality', '0',
         '--embed-metadata', '--embed-thumbnail',
         '--no-write-playlist-metafiles',
         '--sleep-interval', '2', '--max-sleep-interval', '6',
         '-o', str(dest_dir / '%(track_number)02d %(title)s.%(ext)s')],
        capture_output=True, text=True, timeout=3600
    )
    return r.returncode == 0


def extract_cover_from_mp3(mp3_path: Path, dest: Path) -> bool:
    import subprocess
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


def download_cover(url: str, dest: Path, album_dir: Path) -> bool:
    import subprocess
    for item_idx in ['1', '2', '3']:
        r = subprocess.run(
            ['yt-dlp', url,
             '--write-thumbnail', '--convert-thumbnails', 'jpg',
             '--skip-download', '--playlist-items', item_idx,
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
    # Fallback: extract from MP3
    for mp3 in sorted(album_dir.glob('*.mp3'))[:3]:
        if extract_cover_from_mp3(mp3, dest):
            return True
    return False


def fix_mp3_tags_and_rename(mp3_path: Path) -> Path:
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
        stem = mp3_path.stem
        m = re.match(r'^(\d+)\s+(.*)', stem)
        if m:
            num = m.group(1).zfill(2)
            if artist_tag and clean_title:
                new_name = f"{num} - {artist_tag} - {clean_title}.mp3"
            elif clean_title:
                new_name = f"{num} - {clean_title}.mp3"
            else:
                new_name = mp3_path.name
            new_name = re.sub(r'[/\x00]', '-', new_name)
            new_path = mp3_path.parent / new_name
            if new_path != mp3_path:
                mp3_path.rename(new_path)
                return new_path
    except Exception as e:
        pass
    return mp3_path


def upload_file(local_path: Path, s3_key: str, dry_run: bool) -> bool:
    import subprocess
    fname_nfc = unicodedata.normalize('NFC', local_path.name)
    key_nfc   = unicodedata.normalize('NFC', s3_key)
    s3_dest   = f's3://{S3_BUCKET}/{key_nfc}/{fname_nfc}'
    if dry_run:
        print(f'    (dryrun) → {s3_dest}')
        return True
    r = subprocess.run(
        ['aws', 's3', 'cp', str(local_path), s3_dest,
         '--endpoint-url', S3_ENDPOINT, '--region', S3_REGION],
        capture_output=True, text=True, timeout=300
    )
    return r.returncode == 0


def upload_album(local_dir: Path, s3_key: str, dry_run: bool) -> bool:
    ok = True
    for f in sorted(local_dir.iterdir()):
        if f.is_file() and not f.suffix == '.tmp':
            if not upload_file(f, s3_key, dry_run):
                ok = False
    return ok


def process_one(item: dict, acervo_counts: dict, dry_run: bool) -> dict:
    """Download, compare, upload if more tracks. Returns result dict."""
    num = item['num']
    url = item['url']
    acervo_count = acervo_counts.get(num, 0)
    prefix = f'[HC #{num}]'

    dest_dir = DOWNLOAD_DIR / f'HC{num:03d}'

    # Get metadata + Bandcamp count
    meta = get_album_meta(url)
    if not meta:
        return {'num': num, 'status': 'error', 'reason': 'metadata fetch failed'}

    bc_count = meta['count']
    year = meta['year'] or 'XXXX'
    album_title = meta['album']
    folder_name = f"{year} - Hominis Canidae - {album_title}"
    folder_name = re.sub(r'[:\x00]', '-', folder_name)

    if bc_count <= acervo_count:
        return {'num': num, 'status': 'skip',
                'reason': f'Bandcamp={bc_count} ≤ acervo={acervo_count}',
                'bc_count': bc_count, 'acervo_count': acervo_count}

    print(f'{prefix} replacing {acervo_count} → {bc_count} tracks | {album_title}')

    # Download (reuse if already done)
    if dest_dir.exists() and len(list(dest_dir.glob('*.mp3'))) >= bc_count:
        print(f'{prefix} already downloaded')
    else:
        if dest_dir.exists():
            import shutil; shutil.rmtree(dest_dir)
        if not download_tracks(url, dest_dir):
            return {'num': num, 'status': 'error', 'reason': 'download failed'}

    # Fix tags
    for mp3 in sorted(dest_dir.glob('*.mp3')):
        fix_mp3_tags_and_rename(mp3)

    # Cover
    capa = dest_dir / 'capa-min.jpg'
    if not capa.exists():
        if not download_cover(url, capa, dest_dir):
            print(f'{prefix} WARNING: cover missing')

    # Remove stray jpgs
    for jpg in dest_dir.glob('*.jpg'):
        if jpg.name != 'capa-min.jpg':
            jpg.unlink()

    actual_count = len(list(dest_dir.glob('*.mp3')))

    # Upload
    print(f'{prefix} uploading {actual_count} tracks to s3://{S3_BUCKET}/{folder_name}/')
    if not upload_album(dest_dir, folder_name, dry_run):
        return {'num': num, 'status': 'error', 'reason': 'upload failed'}

    return {
        'num': num, 'status': 'replaced',
        'folder': folder_name,
        'acervo_count': acervo_count,
        'bc_count': bc_count,
        'actual_count': actual_count,
        'has_cover': capa.exists(),
    }


def update_json(results: list[dict], dry_run: bool):
    """Remove old entries and add new ones for replaced albums."""
    replaced = [r for r in results if r['status'] == 'replaced']
    if not replaced:
        print('No albums replaced, JSON unchanged.')
        return

    with gzip.open(JSON_GZ) as f:
        db = json.load(f)

    replaced_nums = {r['num'] for r in replaced}
    folder_map = {r['num']: r['folder'] for r in replaced}

    # Remove old entries for replaced albums
    before = len(db['albums'])
    db['albums'] = [a for a in db['albums']
                    if not (re.search(r'#(\d+)', a.get('title', '')) and
                            int(re.search(r'#(\d+)', a['title']).group(1)) in replaced_nums)]
    removed = before - len(db['albums'])

    # Build new entries from downloaded files
    new_entries = []
    for r in replaced:
        folder = folder_map[r['num']]
        local_dir = DOWNLOAD_DIR / f"HC{r['num']:03d}"
        if not local_dir.exists():
            continue
        tracks = []
        for mp3 in sorted(local_dir.glob('*.mp3')):
            try:
                audio = MP3(mp3, ID3=ID3)
                tags = audio.tags or {}
                title = str(tags.get('TIT2', mp3.stem))
                artist = str(tags.get('TPE1', ''))
                trk_raw = str(tags.get('TRCK', '0'))
                trk_num = int(trk_raw.split('/')[0]) if trk_raw else 0
                duration = int(audio.info.length)
                trk = {'title': title, 'file': mp3.name, 'duration': duration}
                if trk_num: trk['num'] = trk_num
                if artist: trk['artists'] = artist
                tracks.append(trk)
            except Exception:
                pass

        m = re.match(r'^(\d{4})\s+-\s+.+?\s+-\s+(.+)$', folder)
        if not m:
            continue
        year_int = int(m.group(1))
        album_title = m.group(2)
        entry = {
            'title': album_title,
            'artist': 'Hominis Canidae',
            'year': year_int,
            'path': folder,
            'has_cover': (local_dir / 'capa-min.jpg').exists(),
            'tracks': tracks,
        }
        new_entries.append(entry)
        print(f'  + {folder} ({len(tracks)} tracks)')

    db['albums'].extend(new_entries)
    db['albums'].sort(key=lambda a: (-a.get('year', 0), a.get('title', '')))

    print(f'Removed {removed} old entries, added {len(new_entries)} new.')
    print(f'Total albums: {len(db["albums"])}')

    if dry_run:
        print('DRY RUN — not writing JSON.')
        return

    with gzip.open(JSON_GZ, 'wt', encoding='utf-8') as f:
        json.dump(db, f, ensure_ascii=False, separators=(',', ':'))
    print(f'Written: {JSON_GZ}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--only', type=int, nargs='+')
    args = parser.parse_args()

    load_env()
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    # Load current acervo track counts
    with gzip.open(JSON_GZ) as f:
        db = json.load(f)
    acervo_counts = {}
    for a in db['albums']:
        m = re.search(r'#(\d+)', a.get('title', ''))
        if m:
            acervo_counts[int(m.group(1))] = len(a.get('tracks', []))

    items = INCOMPLETE
    if args.only:
        items = [x for x in items if x['num'] in args.only]

    print(f'Processing {len(items)} albums with {args.workers} parallel workers')
    if args.dry_run:
        print('DRY RUN')

    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(process_one, item, acervo_counts, args.dry_run): item for item in items}
        for fut in as_completed(futures):
            r = fut.result()
            results.append(r)
            num = r['num']
            if r['status'] == 'replaced':
                print(f'  ✓ HC #{num}: {r["acervo_count"]} → {r["actual_count"]} tracks')
            elif r['status'] == 'skip':
                print(f'  = HC #{num}: {r["reason"]}')
            else:
                print(f'  ✗ HC #{num}: {r["reason"]}')

    results.sort(key=lambda x: x['num'])
    replaced = [r for r in results if r['status'] == 'replaced']
    skipped  = [r for r in results if r['status'] == 'skip']
    errors   = [r for r in results if r['status'] == 'error']

    print(f'\n{"="*60}')
    print(f'Replaced: {len(replaced)}, Skipped (already complete): {len(skipped)}, Errors: {len(errors)}')
    if errors:
        print(f'Errors: {[r["num"] for r in errors]}')
    if skipped:
        print(f'Skipped: {[(r["num"], r["reason"]) for r in skipped]}')

    # Update JSON
    update_json(results, dry_run=args.dry_run)


if __name__ == '__main__':
    main()
