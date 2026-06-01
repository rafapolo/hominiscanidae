import json, gzip, re, subprocess, shutil, time, sys
from pathlib import Path

UNZIPS = Path("/Volumes/EXTRA/hominiscanidae/unzips")
POSTS_JSON = Path("/Users/polux/Projetos/hominiscanidae/posts.json")
ALBUMS_GZ = Path("/Users/polux/Projetos/hominiscanidae/data/homi-albums.json.gz")
LOG = Path("fix_nonbc.log")

data = json.loads(gzip.open(ALBUMS_GZ).read().decode())
singles = [a for a in data["albums"] if len(a.get("tracks", [])) == 1]

posts = json.load(open(POSTS_JSON))
slug_to_post = {}
for p in posts:
    url = p.get("url", "")
    m = re.search(r"/([^/]+)\.html$", url)
    if m:
        slug_to_post[m.group(1)] = p

def log(msg):
    print(msg)
    with open(LOG, "a") as f:
        f.write(msg + "\n")

def dl_mega(url, dest):
    r = subprocess.run(
        ["megadl", "--path", str(dest), url],
        capture_output=True, text=True, timeout=300,
    )
    if r.returncode == 0:
        return True
    return False

def dl_aria2(url, dest):
    r = subprocess.run(
        ["aria2c", "-x3", "-s3", "--dir", str(dest.parent), "--out", dest.name, url],
        capture_output=True, text=True, timeout=120,
    )
    return r.returncode == 0 and dest.exists()

candidates = []
for a in singles:
    track_file = a["tracks"][0].get("file", "")
    slug = track_file.replace(".mp3", "") if track_file.endswith(".mp3") else ""
    post = slug_to_post.get(slug, {})
    dl = post.get("download") or ""
    if not dl or "bandcamp.com" in dl:
        continue
    if post.get("status") in ("dead_link", "blocked"):
        continue
    candidates.append((slug, a.get("path", ""), dl))

log(f"Candidates: {len(candidates)}")
ok = 0
for slug, path, url in candidates:
    folder = UNZIPS / path
    if not folder.exists():
        continue

    log(f"\n{slug}")
    log(f"  {url[:100]}")

    # Determine file extension
    ext = ".zip"
    if "mega.nz" in url or "mega.co.nz" in url:
        ext = ".rar"
    elif url.endswith(".zip"):
        ext = ".zip"
    elif url.endswith(".rar"):
        ext = ".rar"
    elif url.endswith(".mp3"):
        ext = ".mp3"

    dest = Path(f"/tmp/nonbc_{slug}{ext}")

    if "mega" in url:
        ok_flag = dl_mega(url, dest.parent)
    else:
        ok_flag = dl_aria2(url, dest)

    if not ok_flag or not dest.exists():
        log(f"  DL_FAIL")
        continue

    # Extract
    extract_dir = Path(f"/tmp/nonbc_extract_{slug}")
    if extract_dir.exists():
        shutil.rmtree(extract_dir)
    extract_dir.mkdir()

    r = subprocess.run(
        ["unar", "-o", str(extract_dir), "-q", str(dest)],
        capture_output=True, text=True, timeout=120,
    )
    if r.returncode != 0:
        log(f"  EX_FAIL")
        dest.unlink(missing_ok=True)
        continue

    # Find MP3s in extract
    mp3s = sorted(extract_dir.rglob("*.mp3"))
    if not mp3s:
        log(f"  EXTRACTED_NO_MP3")
        shutil.rmtree(extract_dir)
        dest.unlink(missing_ok=True)
        continue

    # Remove old single MP3 in folder, copy new tracks
    for f in list(folder.glob("*.mp3")):
        f.unlink(missing_ok=True)
    for f in mp3s:
        shutil.copy2(f, folder / f.name)

    # Copy cover
    imgs = list(extract_dir.rglob("*.jpg")) + list(extract_dir.rglob("*.png"))
    capa = folder / "capa-min.jpg"
    if imgs and not capa.exists():
        shutil.copy2(imgs[0], capa)

    shutil.rmtree(extract_dir)
    dest.unlink(missing_ok=True)

    n = len(mp3s)
    ok += 1
    log(f"  OK: {n} tracks")

    time.sleep(2)

log(f"\nDone. OK={ok}/{len(candidates)}")
