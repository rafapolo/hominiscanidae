import json
import gzip
import os
import re
import subprocess
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

UNZIPS = Path("/Volumes/EXTRA/hominiscanidae/unzips")
POSTS_DIR = Path("/Users/polux/Projetos/hominiscanidae/posts")
ALBUMS_GZ = Path("/Users/polux/Projetos/hominiscanidae/data/homi-albums.json.gz")
LOG = Path("fix_single_tracks.log")

DRY_RUN = "--dry" in sys.argv
LIMIT = None
for i, arg in enumerate(sys.argv):
    if arg == "--limit" and i + 1 < len(sys.argv):
        LIMIT = int(sys.argv[i + 1])

DONE_LOG = Path("fix_single_tracks_done.log")
processed = set()
if DONE_LOG.exists():
    for line in DONE_LOG.read_text().splitlines():
        s = line.strip()
        if s:
            processed.add(s)

BACKOFF = 0

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    with LOG.open("a") as f:
        f.write(line + "\n")
    print(line)

def classify_bc(url):
    if not url:
        return "none"
    if "/album/" in url:
        return "album"
    if "/track/" in url:
        return "track"
    return "generic"

def clean_bc_url(raw):
    raw = raw.rstrip("/")
    for sep in ["**]", "](", "**("]:
        if sep in raw:
            raw = raw.split(sep)[0]
    if raw.startswith("http://"):
        raw = "https://" + raw[7:]
    return raw

def find_bandcamp_url(md_path):
    if not md_path.exists():
        return None
    content = md_path.read_text()
    urls = re.findall(
        r'https?://[a-zA-Z0-9.-]+\.bandcamp\.com[^\s)"\'<>]+', content
    )
    for raw in urls:
        url = clean_bc_url(raw)
        if "/album/" in url or "/track/" in url:
            return url
    for raw in urls:
        return clean_bc_url(raw)
    return None

def ytdlp_download(bc_url, dest_dir):
    global BACKOFF
    os.makedirs(dest_dir, exist_ok=True)
    result = subprocess.run(
        [
            "yt-dlp", "-x", "--audio-format", "mp3", "--audio-quality", "0",
            "--sleep-interval", "1", "--max-sleep-interval", "3",
            "--retry-sleep", "60",
            "--file-access-retries", "5",
            "--fragment-retries", "5",
            "--socket-timeout", "15",
            "-o", f"{dest_dir}/%(track_number)02d. %(title)s.%(ext)s",
            "--no-overwrites", "--ignore-errors", "--no-warnings",
            "--print", "after_move:filepath",
            bc_url,
        ],
        capture_output=True, text=True, timeout=900,
    )
    stderr = result.stderr.strip() or ""
    if "HTTP Error 429" in stderr:
        BACKOFF = min(BACKOFF + 60, 600)
        log(f"  429 — backing off {BACKOFF}s")
        time.sleep(BACKOFF)
        return None
    if result.returncode != 0:
        err = stderr[:200] if stderr else (result.stdout.strip()[:200] or "unknown")
        return f"fail:{err}"
    files = sorted(dest_dir.glob("*.mp3"))
    if not files:
        return "fail:no-files"
    return f"ok:{len(files)}"

def fix_album(album):
    path = album.get("path", "")
    tracks = album.get("tracks", [])
    if len(tracks) != 1:
        return None
    folder = UNZIPS / path
    if not folder.exists():
        return None
    track_file = tracks[0].get("file", "")
    slug = track_file.replace(".mp3", "") if track_file.endswith(".mp3") else ""

    if slug in processed:
        return f"skip:already-ok"

    md_path = POSTS_DIR / f"{slug}.md"
    bc_url = find_bandcamp_url(md_path)
    if not bc_url or ("/album/" not in bc_url and "/track/" not in bc_url):
        return "skip:no-album-url"

    for attempt in range(3):
        msg = ytdlp_download(bc_url, folder)
        if msg is not None:
            break
        log(f"  retry {attempt+1} for {slug}")
    else:
        msg = "fail:exhausted-retries"

    n_new = sum(1 for f in folder.glob("*.mp3") if not f.name.startswith("._"))
    log(f"{slug}: {msg} (now {n_new} mp3s)")

    if msg and msg.startswith("ok:"):
        with DONE_LOG.open("a") as f:
            f.write(slug + "\n")
        capa = folder / "capa-min.jpg"
        if not capa.exists():
            imgs = sorted(folder.glob("cover.*")) + sorted(folder.glob("*.jpg"))
            for img in imgs:
                if img.name == "capa-min.jpg":
                    continue
                try:
                    shutil.copy2(img, capa)
                    break
                except Exception:
                    pass
    return msg

def main():
    global BACKOFF
    data = json.loads(gzip.open(ALBUMS_GZ).read().decode())
    singles = [a for a in data["albums"] if len(a.get("tracks", [])) == 1]
    log(f"Total 1-track: {len(singles)}")

    eligible = []
    for a in singles:
        tracks = a.get("tracks", [])
        track_file = tracks[0].get("file", "") if tracks else ""
        slug = track_file.replace(".mp3", "") if track_file.endswith(".mp3") else ""
        md_path = POSTS_DIR / f"{slug}.md"
        bc_url = find_bandcamp_url(md_path)
        if classify_bc(bc_url) in ("album", "track"):
            eligible.append(a)

    log(f"Eligible: {len(eligible)}")

    if DRY_RUN:
        for a in eligible[:5]:
            slug = a["tracks"][0]["file"].replace(".mp3", "")
            log(f"  {a['path']} | {find_bandcamp_url(POSTS_DIR / f'{slug}.md')}")
        return

    limit = LIMIT or len(eligible)
    to_process = eligible[:limit]
    log(f"Processing {len(to_process)} albums sequentially...")

    ok = 0
    for i, a in enumerate(to_process, 1):
        if BACKOFF:
            log(f"  backoff active: waiting {BACKOFF}s...")
            time.sleep(BACKOFF)
        BACKOFF = 0

        result = fix_album(a)
        if result and result.startswith("ok"):
            ok += 1

        log(f"  [{i}/{len(to_process)}] ok={ok}")

        if not BACKOFF:
            time.sleep(3)
        else:
            BACKOFF = max(0, BACKOFF - 60)

    log(f"\nDone. OK={ok}/{len(to_process)}")
    log("Regenerate homi-albums.json.gz with Rust binary next.")

if __name__ == "__main__":
    main()
