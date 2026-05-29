#!/usr/bin/env python3
"""Merge downloaded albums from /tmp/hc-bandcamp-sync into homi-albums.json.gz.

Reads ID3 tags from downloaded MP3 files, constructs album entries,
and adds them to the existing acervo JSON (deduplicating by album path).

Usage:
    python3 scripts/merge-downloads-to-json.py [--download-dir PATH] [--dry-run]
"""

import argparse, gzip, json, os, re, sys
from pathlib import Path
from mutagen.mp3 import MP3
from mutagen.id3 import ID3

DEFAULT_DOWNLOAD_DIR = Path('/tmp/hc-bandcamp-sync')
JSON_GZ = Path(__file__).parent.parent / 'js' / 'homi-albums.json.gz'


def load_env(file: Path):
    if not file.exists():
        return
    for line in file.read_text().splitlines():
        m = re.match(r'^\s*([\w]+)\s*=\s*"?([^"]*)"?\s*$', line)
        if m:
            os.environ.setdefault(m.group(1), m.group(2))


def read_tracks_from_dir(album_dir: Path) -> list[dict]:
    """Read ID3 tags from all MP3 files sorted by track number."""
    tracks = []
    for mp3_file in sorted(album_dir.glob('*.mp3')):
        try:
            audio = MP3(mp3_file, ID3=ID3)
            tags = audio.tags or {}
            title = str(tags.get('TIT2', mp3_file.stem))
            artist = str(tags.get('TPE1', ''))
            track_num_raw = str(tags.get('TRCK', '0'))
            track_num = int(track_num_raw.split('/')[0]) if track_num_raw else 0
            duration = int(audio.info.length)
            track = {
                'title': title,
                'file': mp3_file.name,
                'duration': duration,
            }
            if track_num:
                track['num'] = track_num
            if artist:
                track['artists'] = artist
            tracks.append(track)
        except Exception as e:
            print(f'  warn: could not read {mp3_file.name}: {e}', file=sys.stderr)
    return tracks


def build_album_entry(album_dir: Path) -> dict | None:
    """Build a JSON album entry from a downloaded album directory."""
    folder_name = album_dir.name

    # Parse folder: "{year} - {artist} - {title}" or "{year} - {title}"
    m = re.match(r'^(\d{4})\s+-\s+(.+?)\s+-\s+(.+)$', folder_name)
    if m:
        year, artist, title = int(m.group(1)), m.group(2), m.group(3)
    else:
        m2 = re.match(r'^(\d{4})\s+-\s+(.+)$', folder_name)
        if m2:
            year, title = int(m2.group(1)), m2.group(2)
            artist = ''
        else:
            print(f'  warn: could not parse folder name: {folder_name}', file=sys.stderr)
            return None

    tracks = read_tracks_from_dir(album_dir)
    if not tracks:
        print(f'  warn: no tracks in {folder_name}', file=sys.stderr)
        return None

    has_cover = (album_dir / 'capa-min.jpg').exists()

    entry = {
        'title': title,
        'year': year,
        'path': folder_name,
        'has_cover': has_cover,
        'tracks': tracks,
    }
    if artist:
        entry['artist'] = artist

    return entry


def merge(download_dir: Path, json_gz: Path, dry_run: bool = False):
    # Load existing JSON
    with gzip.open(json_gz) as f:
        db = json.load(f)

    existing_paths = {a['path'] for a in db['albums']}
    print(f'Existing acervo: {len(db["albums"])} albums')
    print(f'Download dir: {download_dir}')

    new_entries = []
    updated = 0

    for album_dir in sorted(download_dir.iterdir()):
        if not album_dir.is_dir():
            continue
        folder_name = album_dir.name

        entry = build_album_entry(album_dir)
        if not entry:
            continue

        if folder_name in existing_paths:
            print(f'  SKIP (already in acervo): {folder_name}')
        else:
            print(f'  ADD ({len(entry["tracks"])} tracks, cover={entry["has_cover"]}): {folder_name}')
            new_entries.append(entry)
            updated += 1

    if not new_entries:
        print('No new albums to add.')
        return

    print(f'\nAdding {len(new_entries)} new albums to acervo...')

    if dry_run:
        print('DRY RUN — not writing to file.')
        return

    db['albums'].extend(new_entries)

    # Sort by year desc, then title
    db['albums'].sort(key=lambda a: (-a.get('year', 0), a.get('title', '')))

    # Write back
    with gzip.open(json_gz, 'wt', encoding='utf-8') as f:
        json.dump(db, f, ensure_ascii=False, separators=(',', ':'))

    print(f'Written: {json_gz}')
    print(f'Total albums now: {len(db["albums"])}')

    # Count tracks
    total_tracks = sum(len(a.get('tracks', [])) for a in db['albums'])
    print(f'Total tracks: {total_tracks}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--download-dir', type=Path, default=DEFAULT_DOWNLOAD_DIR)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    load_env(Path(__file__).parent.parent / '.env')
    merge(args.download_dir, JSON_GZ, dry_run=args.dry_run)


if __name__ == '__main__':
    main()
