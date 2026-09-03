#!/usr/bin/env python3
"""Scrape all albums from a Bandcamp artist page, filter by min track count,
download MP3s + cover, upload to S3, then prompt to regenerate homi-albums.json.gz.

Usage:
    python3 scripts/download/scrape_bandcamp_artist.py [ARTIST_URL] [--min-tracks N] [--dry-run]

Defaults:
    ARTIST_URL  = https://azymuth.bandcamp.com/
    --min-tracks 7  (more than 6)
"""

import json
import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

UNZIPS       = Path("/Volumes/EXTRA/hominiscanidae/unzips")
ENV_FILE     = Path(__file__).resolve().parents[2].parent / "tocador" / ".env"
S3_ENDPOINT  = "https://hel1.your-objectstorage.com"
S3_BUCKET    = "indie"
S3_REGION    = "hel1"
S3_PREFIX    = "indie/"
DELAY_BETWEEN = 5  # seconds between album downloads


def load_env():
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text().splitlines():
        m = re.match(r'^\s*([\w]+)\s*=\s*"?([^"]*)"?\s*$', line)
        if m:
            os.environ.setdefault(m.group(1), m.group(2))


def log(msg: str):
    print(msg, flush=True)


def list_albums(homepage: str) -> list[dict]:
    """Return list of dicts with url and title for all /album/ entries."""
    log(f"Listing albums from {homepage} ...")
    r = subprocess.run(
        ["yt-dlp", "--flat-playlist", "--dump-json", "--quiet",
         "--socket-timeout", "30", homepage],
        capture_output=True, text=True, timeout=120,
    )
    albums = []
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        url = entry.get("url") or entry.get("webpage_url") or ""
        title = entry.get("title") or entry.get("webpage_url_basename") or ""
        if url and "/album/" in url:
            albums.append({"url": url, "title": title})
    log(f"  Found {len(albums)} album(s)")
    return albums


def get_album_meta(url: str) -> dict | None:
    """Return year, album title, track count from a Bandcamp album URL."""
    r = subprocess.run(
        ["yt-dlp", url,
         "--print", "%(release_year)s|%(album)s|%(playlist_count)s",
         "--no-flat-playlist", "-I", "1", "--quiet"],
        capture_output=True, text=True, timeout=60,
    )
    if r.returncode != 0:
        return None
    line = (r.stdout.strip().splitlines() or [""])[0]
    parts = line.split("|", 2)
    if len(parts) < 2:
        return None
    year_str, album_raw = parts[0], parts[1]
    count_str = parts[2] if len(parts) > 2 else ""
    year = int(year_str) if year_str and year_str not in ("NA", "None") and year_str.isdigit() else None
    if not year:
        m = re.search(r"\((\d{4})\)", album_raw)
        if m:
            year = int(m.group(1))
    album = re.sub(r"\s*\(\d{4}\)\s*$", "", album_raw.strip()).strip()
    count = int(count_str) if count_str.isdigit() else None
    return {"year": year, "album": album, "count": count}


def download_tracks(url: str, dest_dir: Path) -> bool:
    dest_dir.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        ["yt-dlp", url,
         "--extract-audio", "--audio-format", "mp3", "--audio-quality", "0",
         "--embed-metadata", "--embed-thumbnail",
         "--no-write-playlist-metafiles",
         "--quiet", "--no-warnings",
         "-o", str(dest_dir / "%(track_number)02d %(title)s.%(ext)s")],
        capture_output=True, text=True, timeout=3600,
    )
    if r.returncode != 0:
        log(f"  yt-dlp error: {r.stderr[-300:]}")
        return False
    return True


def download_cover(url: str, dest: Path, album_dir: Path | None = None) -> bool:
    """Download album cover via yt-dlp thumbnail; fallback to extracting from MP3."""
    for item in ["1", "2", "3"]:
        cover_orig = dest.parent / "_cover_orig.jpg"
        r = subprocess.run(
            ["yt-dlp", url,
             "--write-thumbnail", "--convert-thumbnails", "jpg",
             "--skip-download", "--playlist-items", item,
             "--quiet", "--no-warnings",
             "-o", str(dest.parent / "_cover_orig.%(ext)s")],
            capture_output=True, text=True, timeout=60,
        )
        if cover_orig.exists() and cover_orig.stat().st_size > 1000:
            r2 = subprocess.run(
                ["ffmpeg", "-y", "-i", str(cover_orig),
                 "-vf", "scale=200:-1", "-q:v", "4", str(dest)],
                capture_output=True,
            )
            cover_orig.unlink(missing_ok=True)
            if dest.exists() and dest.stat().st_size > 500:
                return True
        cover_orig.unlink(missing_ok=True)

    # Fallback: extract from embedded thumbnail in first MP3
    if album_dir:
        for mp3 in sorted(album_dir.glob("*.mp3"))[:3]:
            tmp = dest.parent / "_cover_extracted.jpg"
            r = subprocess.run(
                ["ffmpeg", "-y", "-i", str(mp3), "-an", "-vcodec", "mjpeg", str(tmp)],
                capture_output=True,
            )
            if tmp.exists() and tmp.stat().st_size > 1000:
                r2 = subprocess.run(
                    ["ffmpeg", "-y", "-i", str(tmp), "-vf", "scale=200:-1", "-q:v", "4", str(dest)],
                    capture_output=True,
                )
                tmp.unlink(missing_ok=True)
                if dest.exists() and dest.stat().st_size > 500:
                    return True
            tmp.unlink(missing_ok=True)

    return False


def upload_folder(local_dir: Path, dry_run: bool = False) -> tuple[int, int]:
    """Upload all files in local_dir to S3. Returns (ok, fail)."""
    folder_key = unicodedata.normalize("NFC", S3_PREFIX + local_dir.name)
    ok = fail = 0
    for f in sorted(local_dir.iterdir()):
        if not f.is_file() or f.suffix == ".tmp":
            continue
        fname_nfc = unicodedata.normalize("NFC", f.name)
        s3_dest = f"s3://{S3_BUCKET}/{folder_key}/{fname_nfc}"
        if dry_run:
            log(f"  (dryrun) would upload: {fname_nfc}")
            ok += 1
            continue
        r = subprocess.run(
            ["aws", "s3", "cp", str(f), s3_dest,
             "--endpoint-url", S3_ENDPOINT, "--region", S3_REGION],
            capture_output=True, text=True, timeout=300,
        )
        if r.returncode == 0:
            ok += 1
        else:
            log(f"  FAIL upload {f.name}: {r.stderr.strip()[-200:]}")
            fail += 1
    return ok, fail


def sanitize_folder_name(name: str) -> str:
    name = re.sub(r"[:/\x00]", "-", name)
    return name.strip()


def process_album(album_url: str, artist_name: str, min_tracks: int,
                  dry_run: bool) -> str:
    log(f"\n{'='*60}")
    log(f"Album: {album_url}")

    meta = get_album_meta(album_url)
    if not meta:
        return "error:no-meta"

    year = meta["year"] or "XXXX"
    title = meta["album"] or "Unknown"
    count = meta["count"]
    log(f"  {year} — {title} — {count} tracks")

    if count is None or count <= min_tracks - 1:
        return f"skip:tracks={count}"

    folder_name = sanitize_folder_name(f"{year} - {artist_name} - {title}")
    dest_dir = UNZIPS / folder_name

    # Skip if already exists with mp3s
    if dest_dir.exists() and list(dest_dir.glob("*.mp3")):
        log(f"  already exists: {folder_name}")
    else:
        log(f"  downloading {count} tracks to {folder_name} ...")
        if not dry_run:
            if not download_tracks(album_url, dest_dir):
                return "error:download-failed"
        else:
            log("  (dryrun) skipping actual download")

    # Cover
    capa = dest_dir / "capa-min.jpg"
    if not capa.exists() and not dry_run:
        log("  downloading cover...")
        if download_cover(album_url, capa, album_dir=dest_dir):
            log(f"  cover: {capa.stat().st_size // 1024}KB")
        else:
            log("  warn: cover download failed")

    # Remove per-track jpg thumbnails left by yt-dlp
    if not dry_run:
        for jpg in dest_dir.glob("*.jpg"):
            if jpg.name != "capa-min.jpg":
                jpg.unlink()

    # Upload to S3
    if dry_run:
        log("  (dryrun) would upload to S3")
        return f"ok:{folder_name}"
    log(f"  uploading {folder_name} to S3...")
    ok, fail = upload_folder(dest_dir, dry_run=False)
    log(f"  uploaded: {ok} ok, {fail} fail")

    return f"ok:{folder_name}"


def main():
    import time
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", nargs="?", default="https://azymuth.bandcamp.com/",
                        help="Bandcamp artist homepage URL")
    parser.add_argument("--min-tracks", type=int, default=7,
                        help="Minimum track count (default: 7 = more than 6)")
    parser.add_argument("--artist", default=None,
                        help="Artist display name for folder (default: auto-detected)")
    parser.add_argument("--dry-run", action="store_true",
                        help="List candidates without downloading or uploading")
    args = parser.parse_args()

    load_env()

    artist_name = args.artist
    if not artist_name:
        # Auto-detect from URL: azymuth.bandcamp.com → Azymuth
        m = re.match(r"https?://([^.]+)\.bandcamp\.com", args.url)
        artist_name = m.group(1).replace("-", " ").title() if m else "Unknown"

    log(f"Artist: {artist_name}")
    log(f"Min tracks: {args.min_tracks}")
    log(f"Dry run: {args.dry_run}")

    albums = list_albums(args.url)
    if not albums:
        log("No albums found.")
        sys.exit(1)

    results = {"ok": [], "skip": [], "error": []}

    for i, album in enumerate(albums, 1):
        log(f"\n[{i}/{len(albums)}] {album['url']}")
        result = process_album(
            album_url=album["url"],
            artist_name=artist_name,
            min_tracks=args.min_tracks,
            dry_run=args.dry_run,
        )
        if result.startswith("ok:"):
            results["ok"].append(result[3:])
        elif result.startswith("skip:"):
            results["skip"].append(f"{album['url']} ({result[5:]})")
        else:
            results["error"].append(f"{album['url']} ({result})")

        if i < len(albums):
            time.sleep(DELAY_BETWEEN)

    log(f"\n{'='*60}")
    log(f"Done: {len(results['ok'])} downloaded, {len(results['skip'])} skipped, {len(results['error'])} errors")

    if results["ok"]:
        log("\nDownloaded:")
        for name in results["ok"]:
            log(f"  {name}")

    if results["skip"]:
        log(f"\nSkipped ({len(results['skip'])} albums with < {args.min_tracks} tracks):")
        for s in results["skip"]:
            log(f"  {s}")

    if results["error"]:
        log("\nErrors:")
        for e in results["error"]:
            log(f"  {e}")

    if results["ok"] and not args.dry_run:
        log("\nNext step — regenerate homi-albums.json.gz:")
        log("  cd /Users/polux/Projetos/tocador/script/generate-albums")
        log("  cargo build --release")
        log("  ./target/release/generate-albums /Volumes/EXTRA/hominiscanidae/unzips \\")
        log("    /Users/polux/Projetos/hominiscanidae/data/homi-albums.json.gz \\")
        log('    --title "Hominiscanidae" \\')
        log('    --subtitle "Música Independente Brasileira" \\')
        log('    --base-url "https://cdn.tocador.cc/indie" \\')
        log('    --sitemap-url "https://tocador.cc"')


if __name__ == "__main__":
    main()
