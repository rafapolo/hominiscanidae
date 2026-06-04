#!/usr/bin/env python3
"""
Re-download 1-track YouTube-rescued albums from Bandcamp when the full album
is available there.

  python3 scripts/utils/redownload_single_track.py --dry-run  # show candidates
  python3 scripts/utils/redownload_single_track.py            # download & replace

Finds all 1-track albums in homi-albums.json.gz that were rescued via ytdlp_youtube
AND have a Bandcamp URL in their posts/*.md. Fetches the Bandcamp artist page, finds
the matching album (by title fuzzy match), downloads it if track count > 1.
"""

import argparse
import gzip
import json
import re
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

# Reuse helper functions from scrape_bandcamp_artist
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "download"))
from scrape_bandcamp_artist import (
    list_albums, get_album_meta, download_tracks, download_cover, upload_folder, log, load_env
)

ROOT      = Path(__file__).resolve().parent.parent.parent
ALBUMS_GZ = ROOT / "data" / "homi-albums.json.gz"
POSTS_DIR = ROOT / "posts"
POSTS_JSON = ROOT / "posts.json"
UNZIPS    = Path("/Volumes/EXTRA/hominiscanidae/unzips")


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9 ]+", " ", s.lower()).strip()

def _overlap(a: str, b: str) -> float:
    ta = set(_norm(a).split())
    tb = set(_norm(b).split())
    if not ta:
        return 0.0
    return len(ta & tb) / len(ta)


def find_candidates(albums: list, slug_to_post: dict) -> list[dict]:
    candidates = []
    for album in albums:
        if len(album["tracks"]) != 1:
            continue
        slug = re.sub(r'^\d{4} - ', '', album["path"])
        post = slug_to_post.get(slug)
        if not post:
            continue
        rescue = post.get("rescue_source", "")
        if "ytdlp" not in rescue:
            continue
        md_path = POSTS_DIR / f"{slug}.md"
        if not md_path.exists():
            continue
        md = md_path.read_text(errors="replace")
        bc_m = re.search(r'https?://([a-z0-9]+)\.bandcamp\.com', md)
        if not bc_m:
            continue
        bc_url = bc_m.group(0).rstrip("/") + "/"
        candidates.append({
            "album": album,
            "post": post,
            "slug": slug,
            "bandcamp_url": bc_url,
        })
    return candidates


def _bc_album_slug(s: str) -> str:
    """Derive a Bandcamp-style album slug from a title."""
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^a-z0-9 -]+", "", s.lower())
    s = re.sub(r"[\s-]+", "-", s).strip("-")
    return s


def _try_bc_url(url: str) -> dict | None:
    """Return album info if yt-dlp can read the URL, else None."""
    meta = get_album_meta(url)
    if meta and meta.get("album"):
        return {"url": url, "title": meta["album"], **meta}
    return None


def find_bandcamp_match(bc_url: str, target_title: str, album_path: str, target_year: int) -> dict | None:
    """Find matching Bandcamp album by listing page + direct URL tries."""
    bc_base = bc_url.rstrip("/")

    # 1. Try constructed URL from album title
    title_slug = _bc_album_slug(target_title)
    if title_slug and title_slug not in ("ep", "lp", "demo", "st"):
        result = _try_bc_url(f"{bc_base}/album/{title_slug}")
        if result:
            log(f"  direct URL hit: {title_slug}")
            return result

    # 2. Try constructed URL from album path slug (strip year + artist prefix)
    slug = re.sub(r'^\d{4} - ', '', album_path)
    slug = re.sub(r'-(19|20)\d{2}$', '', slug)
    # Remove artist tokens that match the Bandcamp subdomain
    m = re.match(r'https?://([a-z0-9]+)\.bandcamp\.com', bc_base)
    if m:
        subdomain = m.group(1)
        parts = slug.split('-')
        while parts and ''.join(parts[:1]) == subdomain[:len(parts[0])]:
            parts = parts[1:]
        slug = '-'.join(parts)
    if slug:
        result = _try_bc_url(f"{bc_base}/album/{slug}")
        if result:
            log(f"  path slug hit: {slug}")
            return result

    # 3. Fuzzy-match against listed albums (titles may be empty but urls have slugs)
    bc_albums = list_albums(bc_base + "/")
    best, best_s = None, 0.0
    for entry in bc_albums:
        # Use URL slug as proxy for title when title is empty
        url_slug = entry["url"].rstrip("/").split("/")[-1]
        score = max(_overlap(target_title, entry.get("title", "")),
                    _overlap(target_title, url_slug.replace("-", " ")))
        if str(target_year) in entry.get("title", ""):
            score += 0.1
        if score > best_s:
            best_s, best = score, entry

    return best if best_s >= 0.35 else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="Show candidates, no download")
    ap.add_argument("--limit", type=int, default=0, help="Process only first N")
    ap.add_argument("--no-upload", action="store_true", help="Skip S3 upload")
    args = ap.parse_args()

    load_env()

    with gzip.open(ALBUMS_GZ) as f:
        data = json.load(f)
    albums = data["albums"]
    posts = json.load(POSTS_JSON.open())
    slug_to_post = {
        p["url"].rstrip("/").split("/")[-1].replace(".html", ""): p
        for p in posts
    }

    candidates = find_candidates(albums, slug_to_post)
    if args.limit:
        candidates = candidates[:args.limit]
    log(f"Candidates: {len(candidates)} 1-track YouTube rescues with Bandcamp URL")

    ok = skipped = failed = 0

    for item in candidates:
        album     = item["album"]
        post      = item["post"]
        slug      = item["slug"]
        bc_url    = item["bandcamp_url"]
        title     = album["title"]
        artist    = album["artist"]
        year      = album["year"]
        path_name = album["path"]   # folder name in unzips/

        log(f"\n{'─'*60}")
        log(f"{artist} — {title} ({year})")
        log(f"  bandcamp: {bc_url}")

        if args.dry_run:
            log("  [dry run] would search Bandcamp and re-download")
            continue

        # Find matching album on Bandcamp
        bc_match = find_bandcamp_match(bc_url, title, path_name, year)
        if not bc_match:
            log(f"  SKIP: no Bandcamp album match for {title!r}")
            skipped += 1
            continue

        log(f"  matched: {bc_match['title']!r}  ({bc_match['url']})")

        # Check track count before downloading
        meta = get_album_meta(bc_match["url"])
        if not meta:
            log("  SKIP: couldn't read album metadata")
            skipped += 1
            continue

        count = meta.get("count")
        if count and count <= 1:
            log(f"  SKIP: Bandcamp also has {count} track — not a full album")
            skipped += 1
            continue

        log(f"  tracks on Bandcamp: {count}  — downloading ...")

        # Determine destination folder
        dest_dir = UNZIPS / path_name

        # Skip if already re-downloaded (more than 1 MP3 already there)
        existing_mp3s = list(dest_dir.glob("*.mp3")) if dest_dir.exists() else []
        if len(existing_mp3s) > 1:
            log(f"  SKIP: already has {len(existing_mp3s)} tracks in {dest_dir.name}")
            skipped += 1
            continue

        dest_dir.mkdir(parents=True, exist_ok=True)

        # Remove existing single MP3 (rescue file)
        for old in dest_dir.glob("*.mp3"):
            log(f"  removing old rescue: {old.name}")
            old.unlink()

        # Download full album
        if not download_tracks(bc_match["url"], dest_dir):
            log("  FAIL: yt-dlp download failed")
            failed += 1
            continue

        mp3s = list(dest_dir.glob("*.mp3"))
        if not mp3s:
            log("  FAIL: no MP3 files after download")
            failed += 1
            continue

        log(f"  downloaded {len(mp3s)} tracks to {dest_dir}")

        # Cover art
        download_cover(bc_match["url"], dest_dir / "folder.jpg", dest_dir)

        # Update posts.json in memory
        post["rescue_source"] = f"bandcamp_redownload_{time.strftime('%Y%m%d')}"
        post["downloaded_as"] = str(dest_dir)

        # Upload to S3
        if not args.no_upload:
            ok_u, fail_u = upload_folder(dest_dir, dry_run=False)
            log(f"  S3: {ok_u} uploaded, {fail_u} failed")

        ok += 1
        time.sleep(3)

    # Save updated posts.json
    if ok > 0 and not args.dry_run:
        POSTS_JSON.write_text(json.dumps(posts, indent=2, ensure_ascii=False))
        log(f"\nUpdated posts.json for {ok} albums")

    log(f"\n{'═'*60}")
    log(f"re-downloaded: {ok}  skipped: {skipped}  failed: {failed}")

    if ok > 0:
        log("\nNext steps:")
        log("  1. python3 scripts/utils/fix_slugified_metadata.py --apply  (re-apply metadata fixes)")
        log("  2. Run generate-albums to rebuild homi-albums.json.gz")
        log("  3. python3 scripts/utils/fix_slugified_metadata.py --apply  (re-apply again after rebuild)")


if __name__ == "__main__":
    main()
