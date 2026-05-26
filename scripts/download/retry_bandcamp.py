#!/usr/bin/env python3
"""Retry bandcamp dead_links via yt-dlp on artist page URLs from local .md files."""
import json
import re
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

DEST = Path("/Volumes/EXTRA/hominiscanidae")
ROOT = Path(__file__).resolve().parents[2]
POSTS_JSON = ROOT / "posts.json"
POSTS_DIR = ROOT / "posts"
DELAY = 4  # seconds between yt-dlp calls (avoid 429)


def extract_artist_urls(slug):
    md = POSTS_DIR / f"{slug}.md"
    if not md.exists():
        return []
    text = md.read_text(errors="replace")
    urls = re.findall(r'https?://[\w.-]+\.bandcamp\.com[^\s\)\]"\'<>]*', text)
    urls += re.findall(r'http://[\w.-]+\.bandcamp\.com[^\s\)\]"\'<>]*', text)
    result = []
    for u in urls:
        u = u.rstrip(".,)")
        if "bandcamp.com/download" in u:
            continue
        # Skip bare artist homepages (e.g. artist.bandcamp.com/ or artist.bandcamp.com)
        # yt-dlp hangs trying to enumerate full discography
        path = urlparse(u).path.strip("/")
        if not path:
            continue
        result.append(u)
    return list(dict.fromkeys(result))


def try_ytdlp(url, slug):
    out_tmpl = str(DEST / f"{slug}.%(ext)s")
    r = subprocess.run(
        ["yt-dlp", "--no-playlist", "--quiet", "--no-warnings",
         "--socket-timeout", "30", "-o", out_tmpl, url],
        capture_output=True, text=True, timeout=120,
    )
    files = [f for f in DEST.glob(f"{slug}.*") if f.is_file() and f.stat().st_size > 0]
    if files:
        return files[0]
    return None


def main():
    with open(POSTS_JSON) as f:
        posts = json.load(f)

    slug_to_idx = {}
    for i, p in enumerate(posts):
        m = re.search(r"/([^/]+)\.html$", p["url"])
        if m:
            slug_to_idx[m.group(1)] = i

    bc_dead = [
        p for p in posts
        if p.get("status") == "dead_link"
        and p.get("download")
        and "bandcamp" in p["download"]
    ]
    print(f"Bandcamp dead_link: {len(bc_dead)}")

    targets = []
    for p in bc_dead:
        m = re.search(r"/([^/]+)\.html$", p["url"])
        if not m:
            continue
        slug = m.group(1)
        artist_urls = extract_artist_urls(slug)
        if artist_urls:
            targets.append((slug, artist_urls))

    print(f"Com URL de artista: {len(targets)} | delay {DELAY}s entre tentativas\n")

    ok = fail = skip = 0
    for i, (slug, artist_urls) in enumerate(targets):
        # Skip if already downloaded (parallel downloader may have got it)
        existing = list(DEST.glob(f"{slug}.*"))
        existing = [f for f in existing if f.is_file() and f.stat().st_size > 0]
        if existing:
            skip += 1
            continue

        dest = None
        for bc_url in artist_urls:
            dest = try_ytdlp(bc_url, slug)
            if dest:
                break
            time.sleep(DELAY)

        if dest:
            idx = slug_to_idx.get(slug)
            if idx is not None:
                posts[idx]["status"] = "downloaded"
                posts[idx]["downloaded_as"] = dest.name
                posts[idx]["file_size"] = dest.stat().st_size
            ok += 1
            print(f"OK  [{slug}] → {dest.name} ({dest.stat().st_size/1e6:.1f} MB)")
        else:
            fail += 1
            if (i + 1) % 50 == 0:
                print(f"[{i+1}/{len(targets)}] ok={ok} fail={fail} skip={skip}")

        if ok % 10 == 0 and ok > 0:
            with open(POSTS_JSON, "w") as f:
                json.dump(posts, f, ensure_ascii=False, indent=2)

        time.sleep(DELAY)

    with open(POSTS_JSON, "w") as f:
        json.dump(posts, f, ensure_ascii=False, indent=2)

    print(f"\nConcluído: ok={ok} fail={fail} skip={skip}")


if __name__ == "__main__":
    main()
