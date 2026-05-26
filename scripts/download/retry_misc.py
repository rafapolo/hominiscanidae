#!/usr/bin/env python3
"""Retry non-mega, non-bandcamp pending links: bit.ly, direct zips, WordPress plugins, etc."""
import json
import re
import subprocess
import time
import requests
from pathlib import Path
from urllib.parse import urlparse

DEST = Path("/Volumes/EXTRA/hominiscanidae")
ROOT = Path(__file__).resolve().parents[2]
POSTS_JSON = ROOT / "posts.json"

session = requests.Session()
session.headers["User-Agent"] = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


def resolve_url(url):
    """Follow redirects and WordPress download plugins."""
    try:
        r = session.get(url, timeout=15, allow_redirects=True)
        final = r.url
        return final
    except Exception:
        return url


def ext_from_url(url):
    path = urlparse(url).path.lower()
    for ext in (".zip", ".rar", ".mp3", ".flac", ".wav", ".ogg", ".m4a", ".tar.gz"):
        if path.endswith(ext):
            return ext
    return ".zip"


def run_aria2c(url, slug):
    ext = ext_from_url(url)
    out_name = f"{slug}{ext}"
    subprocess.run([
        "aria2c", "-x", "16", "-s", "16",
        "--auto-file-renaming=false", "--allow-overwrite=false", "--quiet=true",
        "--connect-timeout=15", "--timeout=60", "--max-tries=2",
        "-d", str(DEST), "-o", out_name, url,
    ], capture_output=True, text=True, timeout=300)
    dest = DEST / out_name
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    return None


def try_download(url, slug):
    # Resolve short links and plugins first
    resolved = resolve_url(url)
    dest = run_aria2c(resolved, slug)
    if dest:
        return dest
    # Try yt-dlp as fallback
    out_tmpl = str(DEST / f"{slug}.%(ext)s")
    subprocess.run(
        ["yt-dlp", "--no-playlist", "--quiet", "--no-warnings", "-o", out_tmpl, resolved],
        capture_output=True, text=True, timeout=300,
    )
    files = [f for f in DEST.glob(f"{slug}.*") if f.is_file() and f.stat().st_size > 0]
    return files[0] if files else None


def main():
    with open(POSTS_JSON) as f:
        posts = json.load(f)

    slug_to_idx = {}
    for i, p in enumerate(posts):
        m = re.search(r"/([^/]+)\.html$", p["url"])
        if m:
            slug_to_idx[m.group(1)] = i

    skip_domains = {"mega.nz", "mega.co.nz", "bandcamp.com"}

    targets = []
    seen_slugs = set()
    for p in posts:
        if p.get("status") != "not_downloaded" or not p.get("download"):
            continue
        dl = p["download"]
        domain = urlparse(dl).netloc.lstrip("www.")
        if any(s in domain for s in skip_domains) or any(s in domain for s in ("bandcamp",)):
            continue
        m = re.search(r"/([^/]+)\.html$", p["url"])
        if not m:
            continue
        slug = m.group(1)
        if slug in seen_slugs:
            continue
        seen_slugs.add(slug)
        targets.append((slug, dl))

    print(f"Targets não-mega não-bandcamp: {len(targets)}\n")

    ok = fail = skip = 0
    for slug, url in targets:
        existing = [f for f in DEST.glob(f"{slug}.*") if f.is_file() and f.stat().st_size > 0]
        if existing:
            idx = slug_to_idx.get(slug)
            if idx is not None:
                posts[idx]["status"] = "downloaded"
                posts[idx]["downloaded_as"] = existing[0].name
                posts[idx]["file_size"] = existing[0].stat().st_size
            skip += 1
            continue

        dest = try_download(url, slug)
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
            print(f"FAIL [{slug}]: {url[:80]}")

        if (ok + fail) % 10 == 0:
            with open(POSTS_JSON, "w") as f:
                json.dump(posts, f, ensure_ascii=False, indent=2)

    with open(POSTS_JSON, "w") as f:
        json.dump(posts, f, ensure_ascii=False, indent=2)

    print(f"\nConcluído: ok={ok} fail={fail} skip={skip}")


if __name__ == "__main__":
    main()
