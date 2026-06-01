#!/usr/bin/env python3
"""Re-download bandcamp albums with track gaps using yt-dlp on artist page URLs."""
import json
import gzip
import re
import subprocess
import time
import shutil
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

DEST = Path("/Volumes/EXTRA/hominiscanidae")
UNZIPS = DEST / "unzips"
ROOT = Path(__file__).resolve().parents[2]
JSON_GZ = ROOT / "data/homi-albums.json.gz"
POSTS = ROOT / "posts.json"
POSTS_DIR = ROOT / "posts"
DELAY = 6

TMP = Path("/tmp/hc-bandcamp-fix")
TMP.mkdir(parents=True, exist_ok=True)

def slugify(text):
    text = unicodedata.normalize('NFKD', text.lower()).encode('ascii', 'ignore').decode('ascii')
    text = re.sub(r'[^a-z0-9]+', '-', text).strip('-')
    return text

def get_artist_url(slug):
    md = POSTS_DIR / f"{slug}.md"
    if not md.exists():
        return None
    text = md.read_text(errors="replace")
    urls = re.findall(r'https?://[\w.-]+\.bandcamp\.com[^\s\)\]"\'<>]*', text)
    for u in dict.fromkeys([x.rstrip(".,)") for x in urls]):
        if "download" not in u:
            path = urlparse(u).path.strip("/")
            if path:
                return u
    return None

def ytdlp_download(artist_url, slug):
    out_tmpl = str(TMP / f"{slug}_%(track_number)s_%(title)s.%(ext)s")
    r = subprocess.run(
        ["yt-dlp", "--no-playlist", "--quiet", "--no-warnings",
         "--socket-timeout", "60", "-x", "--audio-format", "mp3",
         "--audio-quality", "0", "-o", out_tmpl, artist_url],
        capture_output=True, text=True, timeout=600,
    )
    files = sorted(TMP.glob(f"{slug}_*.mp3"))
    return files if files else None

def main():
    with gzip.open(JSON_GZ, "rt") as f:
        data = json.load(f)
    posts = json.loads(POSTS.read_text())

    bc_posts = {}
    for p in posts:
        dl = p.get("download", "")
        if not dl or not dl.startswith("https://bandcamp.com/download"):
            continue
        m = re.search(r"/([^/]+)\.html$", p.get("url", ""))
        if not m:
            continue
        slug = m.group(1)
        base = re.sub(r'-\d{4}(-\d+)?$', '', slug)
        bc_posts[slug] = {"post": p, "base": base}

    targets = []
    for a in data["albums"]:
        tracks = a["tracks"]
        if not tracks:
            continue
        nums = sorted([t.get("num", i+1) for i, t in enumerate(tracks)])
        if not nums or nums[0] <= 1:
            continue
        present = set(nums)
        max_n = max(nums)
        if max_n <= 1:
            continue
        expected = set(range(1, max_n + 1))
        gaps = sorted(expected - present)
        if not gaps or gaps == [max_n]:
            continue

        m = re.match(r"\d{4} - (.+)", a["path"])
        folder_base = slugify(m.group(1) if m else a["path"])

        best, best_score = None, 0
        for slug, info in bc_posts.items():
            base = info["base"]
            if base in folder_base or folder_base in base:
                score = min(len(base), len(folder_base))
                if score > best_score:
                    best_score = score
                    best = (slug, info)

        if not best:
            continue
        slug, info = best
        artist_url = get_artist_url(slug)
        if not artist_url:
            print(f"  SKIP no artist URL: {a['path']}")
            continue

        existing = sorted((UNZIPS / a["path"]).glob("*.mp3")) if (UNZIPS / a["path"]).exists() else []
        targets.append({
            "path": a["path"],
            "missing": gaps,
            "slug": slug,
            "artist_url": artist_url,
            "existing_count": len(existing),
        })

    targets.sort(key=lambda x: -len(x["missing"]))
    print(f"Bandcamp albums to fix: {len(targets)}\n")

    fixed = 0
    for i, t in enumerate(targets):
        print(f"[{i+1}/{len(targets)}] {t['path']}")
        print(f"  artist: {t['artist_url']}")
        print(f"  missing tracks: {t['missing']}, existing: {t['existing_count']} mp3s")

        dest = UNZIPS / t["path"]
        if not dest.exists():
            print(f"  SKIP: folder not found")
            continue

        downloaded = ytdlp_download(t["artist_url"], t["slug"])
        if not downloaded:
            print(f"  FAILED: no files downloaded")
            time.sleep(DELAY)
            continue
        print(f"  downloaded {len(downloaded)} tracks")

        # Parse track numbers & titles from filenames
        # Pattern: slug_TRACKNUM_Artist - Title.mp3
        pattern = re.compile(rf"{re.escape(t['slug'])}_(\d+)_(.+)\.mp3")
        tracks_info = []
        for f in downloaded:
            m = pattern.match(f.name)
            if m:
                tnum = int(m.group(1))
                title = m.group(2)
                tracks_info.append((tnum, title, f))

        # For albums with only 1 existing track (single-track download), replace all
        is_single_track = (t["existing_count"] <= 1)
        # For albums with multiple existing, only add missing tracks

        copied = 0
        for tnum, title, f in sorted(tracks_info):
            dest_name = f"{tnum:02d} {title}.mp3"
            dest_path = dest / dest_name

            if dest_path.exists():
                continue
            if is_single_track or tnum in t["missing"]:
                shutil.copy2(f, dest_path)
                copied += 1
                print(f"  + track {tnum:02d}: {dest_name}")

        if is_single_track and tracks_info:
            print(f"  replaced single-track album with {len(tracks_info)} tracks")
            fixed += 1
        elif copied:
            print(f"  added {copied} missing tracks")
            fixed += 1
        else:
            print(f"  no new tracks to add")

        for f in downloaded:
            f.unlink()
        time.sleep(DELAY)
        print()

    print(f"\nFixed: {fixed} albums")

if __name__ == "__main__":
    main()
