#!/usr/bin/env python3
"""Complete albums that reached the archive as a single track.

Many folders hold exactly one mp3 not because the release is a single, but because
the download fell back to one track — a YouTube rescue, or a Bandcamp page that only
yielded the featured song. Where the post still points at a Bandcamp album that has
more tracks, fetch the rest.

Two ways in, tried in order:
  1. the post links a bandcamp .../album/... URL directly
  2. the post links the artist's Bandcamp, and the album is found on their page by
     title match (the one-shot bandcamp.com/download?id=... links all expired years ago)

  python3 scripts/download/complete_singles.py --dry-run   # list candidates
  python3 scripts/download/complete_singles.py             # download
  python3 scripts/download/complete_singles.py --limit 10

The existing single is kept unless chromaprint says one of the new tracks is the same
recording, in which case it is moved to DEST/.slug-tail-trash rather than deleted.
"""

import argparse
import json
import re
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

ROOT   = Path(__file__).resolve().parent.parent.parent
UNZIPS = Path("/Volumes/EXTRA/hominiscanidae/unzips")
POSTS_JSON = ROOT / "posts.json"
POSTS_DIR  = ROOT / "posts"
LOG = ROOT / "complete_singles.log"

sys.path.insert(0, str(ROOT / "scripts" / "utils"))
from slug_tails import fingerprint, ber, BER_MATCH, discard  # noqa: E402

RE_BC = re.compile(r'https?://[a-zA-Z0-9][a-zA-Z0-9.-]*\.bandcamp\.com[^\s)"\'<>\]]*')


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with LOG.open("a") as f:
        f.write(line + "\n")


def norm(s):
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9 ]+", " ", s.lower()).split()


def overlap(a, b):
    ta, tb = set(norm(a)), set(norm(b))
    return len(ta & tb) / len(ta) if ta else 0.0


def clean_bc(u):
    # Post bodies are markdown, so URLs arrive wearing emphasis and link syntax.
    for sep in ("](", '"', "'", "<", ">"):
        u = u.split(sep)[0]
    u = re.sub(r"[*_)\].,;:!?]+$", "", u).rstrip("/")
    return u.replace("http://", "https://", 1) if u.startswith("http://") else u


def bandcamp_urls(post) -> list[str]:
    """Every Bandcamp URL tied to a post, album URLs first."""
    seen, out = set(), []
    sources = [post.get("download") or ""]
    slug = post["url"].rstrip("/").split("/")[-1].replace(".html", "")
    md = POSTS_DIR / f"{slug}.md"
    if md.exists():
        sources.append(md.read_text(errors="replace"))
    for src in sources:
        for raw in RE_BC.findall(src):
            u = clean_bc(raw)
            if u not in seen:
                seen.add(u)
                out.append(u)
    out.sort(key=lambda u: 0 if "/album/" in u else 1 if "/track/" in u else 2)
    return out


def ytdlp_json(url, flat=False):
    cmd = ["yt-dlp", "-J", "--no-warnings", "--ignore-errors", "--socket-timeout", "20"]
    if flat:
        cmd.append("--flat-playlist")
    cmd.append(url)
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        return None
    if out.returncode != 0 or not out.stdout.strip():
        return None
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError:
        return None


def album_entries(url):
    """Album URLs on an artist's Bandcamp page."""
    base = re.match(r"(https://[a-z0-9-]+\.bandcamp\.com)", url)
    if not base:
        return []
    data = ytdlp_json(base.group(1) + "/music", flat=True)
    if not data:
        return []
    return [e for e in (data.get("entries") or []) if e.get("url")]


def find_album(post, want_title):
    """A Bandcamp album URL for this post with more than one track."""
    for u in bandcamp_urls(post):
        if "/album/" in u:
            info = ytdlp_json(u)
            n = len(info.get("entries") or []) if info else 0
            if n > 1:
                return u, n, info
    # Fall back to the artist page. --flat-playlist gives no titles for Bandcamp, so
    # rank on the URL slug, then confirm against the album's real title before trusting
    # the match — a wrong album here would bury the single under someone else's record.
    for u in bandcamp_urls(post):
        scored = []
        for e in album_entries(u):
            slug = e["url"].rstrip("/").split("/")[-1].replace("-", " ")
            scored.append((max(overlap(want_title, e.get("title") or ""),
                               overlap(want_title, slug)), e))
        scored.sort(key=lambda t: -t[0])
        if not scored:
            log("    artist page listed no albums")
            break
        for score, e in scored[:3]:
            if score < 0.4:
                break
            info = ytdlp_json(e["url"])
            if not info:
                continue
            real = overlap(want_title, info.get("title") or "")
            n = len(info.get("entries") or [])
            if real < 0.6:
                log(f"    {info.get('title')!r} does not match {want_title!r} ({real:.2f}) — skipping")
                continue
            if n > 1:
                return e["url"], n, info
            log(f"    matched {info.get('title')!r} but it has {n} track — a real single")
        else:
            log(f"    no artist-page album confirmed (best slug score {scored[0][0]:.2f})")
        break   # one artist page is enough
    return None, 0, None


def download(url, dest: Path) -> list[Path]:
    subprocess.run(
        ["yt-dlp", "-x", "--audio-format", "mp3", "--audio-quality", "0",
         "--sleep-interval", "2", "--max-sleep-interval", "5",
         "--retry-sleep", "60", "--fragment-retries", "5", "--socket-timeout", "20",
         "--no-overwrites", "--ignore-errors", "--no-warnings",
         "-o", str(dest / "%(track_number)02d - %(artist)s - %(title)s.%(ext)s"), url],
        capture_output=True, text=True, timeout=1800,
    )
    return sorted(f for f in dest.glob("*.mp3") if not f.name.startswith("._"))


def single_track_folders():
    for folder in sorted(UNZIPS.iterdir()):
        if not folder.is_dir():
            continue
        mp3s = [f for f in folder.iterdir()
                if f.is_file() and f.suffix.lower() == ".mp3" and not f.name.startswith("._")]
        if len(mp3s) == 1:
            yield folder, mp3s[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    if not UNZIPS.exists():
        sys.exit(f"{UNZIPS} not mounted — refusing to run")

    posts = json.loads(POSTS_JSON.read_text())
    by_slug = {p["url"].rstrip("/").split("/")[-1].replace(".html", ""): p for p in posts}
    by_key = {}
    for p in posts:
        k = "".join(norm(p.get("title") or ""))
        if k:
            by_key.setdefault(k, p)

    def post_for(folder, mp3):
        p = by_slug.get(mp3.stem)
        if p:
            return p
        name = re.sub(r"^(19|20)\d{2} - ", "", folder.name)
        return by_key.get("".join(norm(name)))

    candidates = []
    for folder, mp3 in single_track_folders():
        post = post_for(folder, mp3)
        if not post or not bandcamp_urls(post):
            continue
        candidates.append((folder, mp3, post))

    log(f"1-track folders with a Bandcamp lead: {len(candidates)}")
    if args.limit:
        candidates = candidates[:args.limit]

    completed = skipped = failed = 0
    for i, (folder, mp3, post) in enumerate(candidates, 1):
        title = re.sub(r"^(19|20)\d{2} - ", "", folder.name)
        log(f"[{i}/{len(candidates)}] {folder.name}")

        if args.dry_run:
            log(f"    urls: {bandcamp_urls(post)[:3]}")
            continue

        url, n, _ = find_album(post, title)
        if not url:
            log("    no multi-track Bandcamp album found")
            skipped += 1
            continue
        log(f"    {n} tracks at {url}")

        before = {f.name for f in folder.glob("*.mp3")}
        try:
            after = download(url, folder)
        except subprocess.TimeoutExpired:
            log("    download timed out")
            failed += 1
            continue
        new = [f for f in after if f.name not in before]
        if not new:
            log("    nothing downloaded")
            failed += 1
            continue
        log(f"    +{len(new)} tracks")

        # The original single is usually one of the tracks we just fetched.
        fp_old = fingerprint(mp3)
        if fp_old and any(ber(fp_old, fp) <= BER_MATCH
                          for fp in filter(None, (fingerprint(f) for f in new))):
            discard(mp3)
            log(f"    original single was a duplicate — moved to trash")

        post["rescue_source"] = f"bandcamp_complete_{time.strftime('%Y%m%d')}"
        completed += 1
        POSTS_JSON.write_text(json.dumps(posts, indent=2, ensure_ascii=False))
        time.sleep(4)

    log(f"\ncompleted {completed}  skipped {skipped}  failed {failed}")
    if completed:
        log("next: resize covers, sync to S3, regenerate the index")


if __name__ == "__main__":
    main()
