#!/usr/bin/env python3
"""Audit and clean S3 bucket against the acervo catalog.

Compares the live S3 folders under s3://$S3_BUCKET/ with the album paths in
homi-albums.json.gz and reports (or removes) orphans in both directions.
Also detects nested duplicate subdirectories inside unzips/ album folders —
these create phantom slash-separated paths in the acervo (e.g.
"2024 - Artist - Album/Artist - Album (2024)") that should be removed.

Usage:
    python3 scripts/utils/clean_s3.py              # audit only (dry run)
    python3 scripts/utils/clean_s3.py --delete     # delete S3 orphans
    python3 scripts/utils/clean_s3.py --fix-nested # remove nested subdirs from unzips/
    python3 scripts/utils/clean_s3.py --delete --fix-nested

S3 orphan categories removed by --delete:
  - Folders ending in " (2)", " (3)" etc. whose base name is in the acervo
  - Any folder present on S3 but absent from the acervo
"""

import argparse, gzip, json, os, shutil, subprocess, sys, unicodedata
from pathlib import Path

ROOT       = Path(__file__).parent.parent.parent
ENV_FILE   = ROOT / '.env'
JSON_GZ    = ROOT / 'data' / 'homi-albums.json.gz'
UNZIPS     = Path('/Volumes/EXTRA/hominiscanidae/unzips')
S3_ENDPOINT = 'https://hel1.your-objectstorage.com'
S3_BUCKET   = 'indie'
SKIP_KEYS   = {'homi-albums.json.gz', 'indie', 'uqt'}  # non-album root objects


def load_env():
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            os.environ.setdefault(k.strip(), v.strip())


def nfc(s):
    return unicodedata.normalize('NFC', s)


def list_s3_folders():
    result = subprocess.run(
        ['aws', 's3', 'ls', f's3://{S3_BUCKET}/',
         '--endpoint-url', S3_ENDPOINT],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print('ERROR listing S3:', result.stderr.strip(), file=sys.stderr)
        sys.exit(1)
    folders = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line.startswith('PRE '):
            continue
        name = line[4:].rstrip('/')
        name = name.strip('"')
        folders.append(name)
    return folders


def load_acervo():
    d = json.load(gzip.open(JSON_GZ))
    return [a['path'] for a in d.get('albums', d if isinstance(d, list) else [])]


def s3_rm(folder, dry_run):
    prefix = f's3://{S3_BUCKET}/{folder}'
    if dry_run:
        print(f'  [dry-run] would delete {prefix}')
        return
    r = subprocess.run(
        ['aws', 's3', 'rm', prefix, '--recursive',
         '--endpoint-url', S3_ENDPOINT],
        capture_output=True, text=True
    )
    if r.returncode != 0:
        print(f'  ERROR deleting {prefix}: {r.stderr.strip()}', file=sys.stderr)
    else:
        print(f'  deleted: {folder}')


def find_nested_subdirs():
    """Return list of (album_folder, nested_subdir) pairs that are duplicates."""
    hits = []
    if not UNZIPS.exists():
        return hits
    for album_dir in UNZIPS.iterdir():
        if not album_dir.is_dir():
            continue
        parent_mp3s = {f.name for f in album_dir.iterdir()
                       if f.is_file() and f.suffix.lower() == '.mp3'}
        if not parent_mp3s:
            continue
        for sub in album_dir.iterdir():
            if not sub.is_dir():
                continue
            sub_mp3s = {f.name for f in sub.iterdir()
                        if f.is_file() and f.suffix.lower() == '.mp3'}
            # nested subdir with same tracks as parent = duplicate
            if sub_mp3s and sub_mp3s == parent_mp3s:
                hits.append((album_dir, sub))
    return hits


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--delete',     action='store_true', help='delete orphaned S3 folders')
    ap.add_argument('--fix-nested', action='store_true', help='remove nested duplicate subdirs from unzips/')
    args = ap.parse_args()
    dry_run = not args.delete

    load_env()

    print('Loading acervo...', end=' ', flush=True)
    acervo = load_acervo()
    acervo_set = {nfc(p) for p in acervo}
    print(f'{len(acervo_set)} albums')

    print('Listing S3 folders...', end=' ', flush=True)
    raw_folders = list_s3_folders()
    folders = [f for f in raw_folders if f not in SKIP_KEYS and not f.endswith('.gz')]
    s3_map  = {nfc(f): f for f in folders}   # nfc → original S3 name
    s3_set  = set(s3_map)
    print(f'{len(s3_set)} folders')

    # --- orphans on S3 ---
    orphans = sorted(s3_set - acervo_set)
    missing = sorted(acervo_set - s3_set)

    print(f'\n{len(orphans)} S3 folders not in acervo:')
    if orphans:
        for p in orphans:
            print(f'  {p}')
        if args.delete:
            print('\nDeleting...')
            for nfc_path in orphans:
                s3_rm(s3_map[nfc_path], dry_run=False)
        else:
            print('\n(re-run with --delete to remove them)')

    print(f'\n{len(missing)} acervo albums missing from S3:')
    for p in missing:
        print(f'  {p}')

    # --- nested duplicate subdirs ---
    print('\nScanning unzips/ for nested duplicate subdirs...', end=' ', flush=True)
    nested = find_nested_subdirs()
    print(f'{len(nested)} found')
    if nested:
        for album_dir, sub in nested:
            print(f'  {album_dir.name} / {sub.name}')
        if args.fix_nested:
            print('\nRemoving...')
            for album_dir, sub in nested:
                shutil.rmtree(sub)
                print(f'  removed: {sub}')
        else:
            print('\n(re-run with --fix-nested to remove them)')


if __name__ == '__main__':
    main()
