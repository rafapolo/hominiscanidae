#!/usr/bin/env python3
"""
Re-download albums with track gaps into unzips/to_fix/ and extract with unar.
Fixes files silently dropped during the original extraction due to PT-BR charset.

Usage:
    python3 scripts/download/refix_charset.py
    python3 scripts/download/refix_charset.py --dry-run     # show what would be done
    python3 scripts/download/refix_charset.py --no-upload   # copy locally only, skip S3
    python3 scripts/download/refix_charset.py --workers 4
"""

import gzip, json, os, re, shutil, socket, subprocess, sys, threading, time, unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse, quote

ROOT       = Path(__file__).resolve().parents[2]
POSTS_JSON = ROOT / "posts.json"
POSTS_DIR  = ROOT / "posts"
ALBUMS_GZ  = ROOT / "js/homi-albums.json.gz"
UNZIPS     = Path("/Volumes/EXTRA/hominiscanidae/unzips")
TO_FIX     = UNZIPS / "to_fix"
DONE_FILE          = Path("/Volumes/EXTRA/hominiscanidae/_charset_done.txt")
IRRECOVERABLE_FILE = Path("/Volumes/EXTRA/hominiscanidae/_charset_irrecoverable.txt")

AUDIO_EXTS = {".mp3", ".flac", ".ogg", ".m4a", ".aac", ".wav", ".opus", ".wma"}

DRY_RUN        = "--dry-run" in sys.argv
NO_UPLOAD      = "--no-upload" in sys.argv
USE_TOR        = "--tor" in sys.argv
FILTER_DOMAINS = []   # --domain=x,y  → only these
EXCLUDE_DOMAINS = []  # --exclude-domain=x,y  → skip these
WORKERS        = 16
for arg in sys.argv:
    if arg.startswith("--workers="):
        WORKERS = int(arg.split("=")[1])
    if arg.startswith("--domain="):
        FILTER_DOMAINS = [d.strip() for d in arg.split("=", 1)[1].lower().split(",")]
    if arg.startswith("--exclude-domain="):
        EXCLUDE_DOMAINS = [d.strip() for d in arg.split("=", 1)[1].lower().split(",")]

_log_lock  = threading.Lock()
_done_lock = threading.Lock()

def log(msg):
    with _log_lock:
        print(msg, flush=True)

# ── done tracking ─────────────────────────────────────────────────────────────

def load_done():
    done = set(DONE_FILE.read_text().splitlines()) if DONE_FILE.exists() else set()
    if IRRECOVERABLE_FILE.exists():
        # strip the tab-separated missing-track list if present
        done |= {line.split('\t')[0] for line in IRRECOVERABLE_FILE.read_text().splitlines() if line}
    return done

def mark_done(album_path):
    with _done_lock:
        with open(DONE_FILE, "a") as f:
            f.write(album_path + "\n")

# ── slugify ───────────────────────────────────────────────────────────────────

def slugify(s):
    s = unicodedata.normalize("NFKD", s)
    s = s.encode("ascii", "ignore").decode("ascii")
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")

# ── load posts ────────────────────────────────────────────────────────────────

with open(POSTS_JSON) as f:
    _posts = json.load(f)

slug_to_post = {}
for p in _posts:
    url = p.get("url", "")
    m = re.search(r"/(\d{4})/\d{2}/([^/]+)\.html", url)
    if m:
        slug_to_post[m.group(2)] = {**p, "year": m.group(1)}

# ── find post for album folder ────────────────────────────────────────────────

def find_post(folder_no_year, year=None):
    """Map 'Artist - Album' folder to a post. Returns post dict or None.
    If year is given, prefers posts from that year but falls back to any year.
    """
    if " - " not in folder_no_year:
        return None
    parts  = folder_no_year.split(" - ", 1)
    art_sl = slugify(parts[0])
    alb_sl = slugify(parts[1])
    a_len  = min(8, len(art_sl))

    def _best(candidates):
        if not candidates:
            return None
        if year:
            yr = [p for p in candidates if p.get("year") == year]
            if yr:
                return min(yr, key=lambda p: len(p.get("url", "")))
        return min(candidates, key=lambda p: len(p.get("url", "")))

    for b in [min(8, len(alb_sl)), 6, 5, 4]:
        if b < 4:
            break
        frag = alb_sl[:b]
        hits = [post for slug, post in slug_to_post.items()
                if slug.startswith(art_sl[:a_len]) and frag in slug]
        p = _best(hits)
        if p:
            return p

    hits = [post for slug, post in slug_to_post.items()
            if slug.startswith(art_sl + "-") and len(slug) > len(art_sl) + 1]
    p = _best(hits)
    if p:
        return p

    hits = [post for slug, post in slug_to_post.items()
            if slug.startswith(art_sl[:a_len])]
    p = _best(hits)
    if p:
        return p

    art_first = art_sl.split("-")[0]
    if len(art_first) >= 4:
        for b in [min(6, len(alb_sl)), 4]:
            if b < 4:
                break
            frag = alb_sl[:b]
            hits = [post for slug, post in slug_to_post.items()
                    if slug.startswith(art_first) and frag in slug]
            p = _best(hits)
            if p:
                return p

    if len(alb_sl) >= 6:
        frag     = alb_sl[:6]
        keywords = [slugify(w) for w in re.split(r"[\s&,+]+", folder_no_year) if len(w) >= 5]
        hits = [post for slug, post in slug_to_post.items()
                if frag in slug and any(k in slug for k in keywords)]
        p = _best(hits)
        if p:
            return p

    # fuzzy fallback: score all slugs against the full normalized folder name
    target = (art_sl + "-" + alb_sl)[:60]
    best_score, best_post = 0.0, None
    for slug, post in slug_to_post.items():
        score = SequenceMatcher(None, target, slug[:60]).ratio()
        if year and post.get("year") == year:
            score += 0.04
        if score > best_score:
            best_score, best_post = score, post
    if best_score >= 0.75:
        return best_post

    return None

# ── .env loader ──────────────────────────────────────────────────────────────

def load_env(path=ROOT / ".env"):
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        m = re.match(r'^\s*([\w]+)\s*=\s*"?([^"]*)"?\s*$', line)
        if m:
            os.environ.setdefault(m.group(1), m.group(2))

# ── S3 client ─────────────────────────────────────────────────────────────────

_s3_client = None
_s3_lock   = threading.Lock()

def get_s3():
    global _s3_client
    if _s3_client:
        return _s3_client
    with _s3_lock:
        if _s3_client:
            return _s3_client
        import boto3
        _s3_client = boto3.client(
            "s3",
            endpoint_url=os.environ.get("S3_ENDPOINT", "https://hel1.your-objectstorage.com"),
            aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
            aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
            region_name="hel1",
        )
    return _s3_client

def upload_file(local_path, bucket, key):
    ext = local_path.suffix.lower()
    ct  = "audio/mpeg" if ext == ".mp3" else "application/octet-stream"
    with open(local_path, "rb") as f:
        get_s3().put_object(Bucket=bucket, Key=key, Body=f, ContentType=ct)

# ── gap album detection ───────────────────────────────────────────────────────

def get_gap_albums():
    with gzip.open(ALBUMS_GZ) as f:
        data = json.load(f)
    albums = data if isinstance(data, list) else data.get("albums", [])
    result = []
    for a in albums:
        tracks = a.get("tracks", [])
        nums   = [t.get("num") for t in tracks if t.get("num")]
        if not nums:
            continue
        hi = max(nums)
        if hi <= 1:
            continue
        if set(range(min(nums), hi + 1)) - set(nums):
            result.append(a["path"])
    return result

# ── mega proxy rotation ───────────────────────────────────────────────────────

MEGA_PROXY_HOSTS = [None, "livre", "finland", "tor"]
MEGA_PROXY_PORT  = 1080
MEGA_TOR_PORT    = 9050

_mega_dl_count  = 0      # round-robin counter per download
_mega_cur_host  = None   # currently active SSH host
_mega_proxy_lock = threading.Lock()

def _ssh_tunnel_alive():
    try:
        s = socket.socket()
        s.settimeout(2)
        s.connect(("127.0.0.1", MEGA_PROXY_PORT))
        s.close()
        return True
    except Exception:
        return False

def _start_mega_tunnel(host):
    global _mega_cur_host
    if host in (None, "tor"):
        if _mega_cur_host not in (None, "tor"):
            subprocess.run(["pkill", "-f", f"ssh.*-D.*{MEGA_PROXY_PORT}"], capture_output=True)
        _mega_cur_host = host
        return True
    if host == _mega_cur_host and _ssh_tunnel_alive():
        return True
    subprocess.run(["pkill", "-f", f"ssh.*-D.*{MEGA_PROXY_PORT}"], capture_output=True)
    time.sleep(0.5)
    subprocess.run([
        "ssh", "-D", str(MEGA_PROXY_PORT), "-f", "-N",
        "-o", "ExitOnForwardFailure=yes",
        "-o", "ServerAliveInterval=30",
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=10",
        host,
    ], capture_output=True, timeout=20)
    time.sleep(0.5)
    ok = _ssh_tunnel_alive()
    if ok:
        _mega_cur_host = host
    return ok

def _pick_mega_proxy():
    """Round-robin: cada download pega o próximo proxy da lista."""
    global _mega_dl_count
    with _mega_proxy_lock:
        host = MEGA_PROXY_HOSTS[_mega_dl_count % len(MEGA_PROXY_HOSTS)]
        _mega_dl_count += 1
        _start_mega_tunnel(host)
    return host

# ── download ──────────────────────────────────────────────────────────────────

def _encode_url(url):
    parts = url.split("?", 1)
    return quote(parts[0], safe="/:@!$&'()*+,;=%-._~") + ("?" + parts[1] if len(parts) > 1 else "")

def dl_mega(url, tmp_dir):
    work = tmp_dir / "_mega"
    work.mkdir(exist_ok=True)
    try:
        host = _pick_mega_proxy()
        cmd  = ["megadl", "--no-ask-password", "--path", str(work)]
        if host == "tor":
            token    = str(int(time.time() * 1000) % 100000)
            slug_tok = re.sub(r"[^a-z0-9]", "", url[-10:]) + token
            cmd     += [f"--proxy=socks5h://{slug_tok}:x@127.0.0.1:{MEGA_TOR_PORT}"]
            dl_timeout = 600
        elif host is not None:
            cmd     += [f"--proxy=socks5h://127.0.0.1:{MEGA_PROXY_PORT}"]
            dl_timeout = 180
        else:
            dl_timeout = 120
        cmd += [url]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=dl_timeout)
        files = [f for f in work.iterdir() if f.is_file() and f.stat().st_size > 0]
        if not files:
            err = r.stderr.strip()
            if ("509" in err or "over quota" in err.lower() or "mega:timeout" in err.lower()
                    or "ETOOMANY" in err or "ETIME" in err or "ERATELIMIT" in err
                    or "EAGAIN" in err):
                return None, "mega:quota"
            if "EBLOCKED" in err:
                return None, "blocked:EBLOCKED"
            if "ENOENT" in err:
                return None, "dead:ENOENT"
            dead = any(k in err.lower() for k in ("not found", "no longer", "expired", "invalid"))
            return None, ("dead:" + err) if dead else (err or "megadl: no output")
        dst = tmp_dir / files[0].name
        files[0].rename(dst)
        return dst, None
    except subprocess.TimeoutExpired:
        return None, "mega:timeout"
    except Exception as e:
        return None, str(e)
    finally:
        shutil.rmtree(work, ignore_errors=True)

def dl_mediafire(url, tmp_dir, slug):
    import requests
    try:
        s = requests.Session()
        s.headers["User-Agent"] = "Mozilla/5.0"
        r = s.get(url, timeout=20)
        if r.status_code == 404:
            return None, "dead:404"
        m = re.search(r'"url"\s*:\s*"(https?://download\d*\.mediafire\.com[^"]+)"', r.text)
        if not m:
            from bs4 import BeautifulSoup
            btn = BeautifulSoup(r.text, "html.parser").select_one("a#downloadButton")
            direct = btn["href"] if btn else None
        else:
            direct = m.group(1).replace("\\/", "/")
        if not direct:
            return None, "mediafire: no direct link"
        return dl_aria2c(direct, tmp_dir, slug)
    except Exception as e:
        return None, str(e)

def dl_aria2c(url, tmp_dir, slug, default_ext=".rar"):
    ext = re.search(r"\.(rar|zip|7z|mp3|flac)(\?|$)", url, re.I)
    ext = ("." + ext.group(1).lower()) if ext else default_ext
    out = f"{slug}{ext}"
    r   = subprocess.run(
        ["aria2c", "-x", "8", "-s", "8", "--quiet=true",
         "--auto-file-renaming=false", "--allow-overwrite=false",
         "--connect-timeout=30", "--timeout=300", "--max-tries=3",
         "-d", str(tmp_dir), "-o", out, _encode_url(url)],
        capture_output=True, text=True, timeout=1200,
    )
    dest = tmp_dir / out
    if dest.exists() and dest.stat().st_size > 0:
        return dest, None
    return None, r.stderr.strip() or "aria2c: empty"

def dl_dropbox(url, tmp_dir, slug):
    direct = re.sub(r"[?&]dl=0", lambda m: m.group(0).replace("dl=0", "dl=1"), url)
    if "dl=1" not in direct:
        direct += ("&" if "?" in direct else "?") + "dl=1"
    return dl_aria2c(direct, tmp_dir, slug)

def dl_gdrive(url, tmp_dir, slug):
    m = re.search(r"/d/([a-zA-Z0-9_-]+)", url)
    if not m:
        return None, "gdrive: no file ID"
    file_id = m.group(1)
    out = str(tmp_dir / slug)
    # gdown 6.x: posicional url_or_id, sem --id nem --fuzzy
    r = subprocess.run(
        ["gdown", f"https://drive.google.com/uc?id={file_id}", "-O", out],
        capture_output=True, text=True, timeout=600,
    )
    files = [f for f in tmp_dir.iterdir()
             if f.is_file() and f.stat().st_size > 0 and not f.name.startswith("_")]
    if files:
        return files[0], None
    err = (r.stderr + r.stdout).strip()
    # fallback: yt-dlp
    subprocess.run(
        ["yt-dlp", "--no-playlist", "-o", str(tmp_dir / f"{slug}.%(ext)s"), url],
        capture_output=True, text=True, timeout=600,
    )
    files = [f for f in tmp_dir.iterdir()
             if f.is_file() and f.stat().st_size > 0 and not f.name.startswith("_")]
    if files:
        return files[0], None
    return None, err or "gdrive: download failed"

def dl_bandcamp(url, tmp_dir, slug):
    """Open Bandcamp download page with Playwright, click the JS-generated Download
    link, extract the real zip URL, then fetch with aria2c.
    Falls back to yt-dlp streaming if no free download link is found."""
    album_url = url
    direct = None
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=30000)
            album_url = page.url  # follow any redirects
            try:
                page.wait_for_selector("a[href*='bcbits.com']", timeout=15000)
            except PWTimeout:
                pass
            el = (page.query_selector("a[href*='bcbits.com']") or
                  page.query_selector("a:has-text('Download')"))
            direct = el.get_attribute("href") if el else None
            browser.close()
    except Exception as e:
        pass  # Playwright unavailable — fall through to yt-dlp

    if direct:
        return dl_aria2c(direct, tmp_dir, slug, default_ext=".zip")

    # yt-dlp fallback: stream-download all tracks from the album page
    yt_dir = tmp_dir / "_ytdlp"
    yt_dir.mkdir(exist_ok=True)
    r = subprocess.run(
        ["yt-dlp", "-x", "--audio-format", "mp3", "--audio-quality", "0",
         "-o", str(yt_dir / "%(playlist_index)02d %(uploader)s - %(title)s.%(ext)s"),
         album_url],
        capture_output=True, text=True, timeout=600,
    )
    files = [f for f in yt_dir.iterdir() if f.is_file() and f.stat().st_size > 0]
    if files:
        return yt_dir, None  # directory — extract() handles it
    return None, f"bandcamp: no download link found; yt-dlp: {r.stderr[-200:].strip()}"

def do_download(url, tmp_dir, slug):
    domain = urlparse(url).netloc.lstrip("www.")
    # resolve short URLs (bit.ly, mir.cr, etc.) before dispatching
    if domain in ("bit.ly", "mir.cr", "ow.ly", "tinyurl.com", "goo.gl"):
        try:
            import urllib.request
            req = urllib.request.Request(url, method="HEAD")
            req.add_header("User-Agent", "Mozilla/5.0")
            with urllib.request.urlopen(req, timeout=10) as resp:
                url = resp.url
                domain = urlparse(url).netloc.lstrip("www.")
        except Exception:
            pass
    if "mega" in domain:
        return dl_mega(url, tmp_dir)
    elif "mediafire" in domain:
        return dl_mediafire(url, tmp_dir, slug)
    elif "dropbox" in domain:
        return dl_dropbox(url, tmp_dir, slug)
    elif "drive.google.com" in domain:
        return dl_gdrive(url, tmp_dir, slug)
    elif "bandcamp.com" in domain:
        return dl_bandcamp(url, tmp_dir, slug)
    elif "archive.org" in domain:
        return dl_aria2c(url, tmp_dir, slug, default_ext=".zip")
    else:
        return dl_aria2c(url, tmp_dir, slug)

# ── extract ───────────────────────────────────────────────────────────────────

def extract(archive, out_dir):
    """Extract archive into out_dir with unar. Returns list of top-level entries created.
    If the file is already an audio file, copies it directly (no extraction needed).
    If archive is a directory (e.g. yt-dlp output), copies all audio files from it."""
    out_dir.mkdir(parents=True, exist_ok=True)
    if archive.is_dir():
        files = [f for f in archive.iterdir() if f.is_file() and f.suffix.lower() in AUDIO_EXTS]
        if not files:
            return False, "no audio files in directory"
        entries = []
        for f in files:
            dst = out_dir / f.name
            shutil.copy2(f, dst)
            entries.append(f.name)
        return True, entries
    if archive.suffix.lower() in AUDIO_EXTS:
        dst = out_dir / archive.name
        shutil.copy2(archive, dst)
        return True, [archive.name]
    before = set(out_dir.iterdir()) if out_dir.exists() else set()
    r = subprocess.run(
        ["unar", "-o", str(out_dir), str(archive)],
        capture_output=True, text=True, timeout=600,
    )
    if not out_dir.exists():
        return False, "unar: output dir missing"
    after = set(out_dir.iterdir()) - before
    if not after:
        return False, f"unar: nothing extracted (rc={r.returncode})"
    return True, [p.name for p in after]

# ── merge extracted tracks into unzips/ and upload missing ones to S3 ─────────

def merge_and_upload(album_path, extracted_entries, s3_prefix, bucket):
    """Copy and upload only tracks missing from unzips/<album_path>/ (the pt-BR charset victims).
    Files already present locally were already in S3 — skip them entirely."""
    dest_dir = UNZIPS / album_path
    dest_dir.mkdir(parents=True, exist_ok=True)
    existing = {f.name for f in dest_dir.iterdir() if f.is_file()} if dest_dir.exists() else set()

    copied = uploaded = 0
    for entry in extracted_entries:
        src_root = TO_FIX / entry
        sources = (
            [f for f in src_root.rglob("*") if f.is_file() and f.suffix.lower() in AUDIO_EXTS]
            if src_root.is_dir()
            else ([src_root] if src_root.is_file() and src_root.suffix.lower() in AUDIO_EXTS else [])
        )
        for src in sources:
            if src.name in existing:
                continue  # already local → already in S3
            shutil.copy2(src, dest_dir / src.name)
            copied += 1
            if not NO_UPLOAD:
                upload_file(src, bucket, s3_prefix + album_path + "/" + src.name)
                uploaded += 1

    return copied, uploaded

# ── process one album ─────────────────────────────────────────────────────────

def process(album_path, done_set, s3_prefix, bucket):
    if album_path in done_set:
        return f"SKIP  {album_path}"

    m = re.match(r"^(\d{4})\s*-\s*(.+)$", album_path)
    year           = m.group(1) if m else None
    folder_no_year = m.group(2) if m else album_path

    post = find_post(folder_no_year, year)
    if not post:
        return f"NO_POST {album_path}"

    url = post.get("download")
    if not url:
        return f"NO_URL {album_path}"

    domain = urlparse(url).netloc.lstrip("www.")
    if any(d in domain for d in (
        "rapidshare", "hotfile", "zippyshare", "sendspace", "divshare",
        "uploaded.net", "ul.to", "turbobit", "nitroflare",
    )):
        return f"DEAD_SVC {album_path}"

    if FILTER_DOMAINS and not any(f in domain for f in FILTER_DOMAINS):
        return f"SKIP_DOMAIN {album_path}"
    if EXCLUDE_DOMAINS and any(e in domain for e in EXCLUDE_DOMAINS):
        return f"SKIP_DOMAIN {album_path}"

    if DRY_RUN:
        return f"WOULD  {album_path}  ←  {url}"

    slug = re.search(r"/([^/]+)\.html", post.get("url", ""))
    slug = slug.group(1) if slug else slugify(album_path)[:50]

    tmp = TO_FIX / f"_tmp_{slug[:40]}"
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        archive, err = do_download(url, tmp, slug)
        if not archive:
            return f"DL_FAIL {album_path}: {err}"

        ok, entries = extract(archive, TO_FIX)
        if not ok:
            return f"EX_FAIL {album_path}: {entries}"

        copied, uploaded = merge_and_upload(album_path, entries, s3_prefix, bucket)
        mark_done(album_path)
        s3_info = "" if NO_UPLOAD else f"  +{uploaded} s3"
        return f"OK    {album_path}  +{copied} local{s3_info}"
    except Exception as e:
        return f"ERROR {album_path}: {e}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

# ── main ──────────────────────────────────────────────────────────────────────

def main():
    load_env()
    TO_FIX.mkdir(parents=True, exist_ok=True)

    # S3 config (skipped when --no-upload)
    with gzip.open(ALBUMS_GZ) as f:
        _meta = json.load(f)
    meta      = _meta.get("meta", {}) if isinstance(_meta, dict) else {}
    s3_prefix = meta.get("s3_prefix") or os.environ.get("S3_PREFIX", "indie/")
    bucket    = os.environ.get("S3_BUCKET", "indie")
    if NO_UPLOAD:
        log("S3 upload desativado (--no-upload)")
    else:
        log(f"S3 bucket={bucket}  prefix={s3_prefix}")

    if USE_TOR:
        global _mega_dl_count
        _mega_dl_count = MEGA_PROXY_HOSTS.index("tor")
    log(f"Mega proxies: {[h or 'local' for h in MEGA_PROXY_HOSTS]} (round-robin)")

    done_set = load_done()

    gap_albums = get_gap_albums()
    pending    = [a for a in gap_albums if a not in done_set]
    log(f"Gap albums: {len(gap_albums)} total, {len(pending)} to process, {len(done_set)} already done")
    if DRY_RUN:
        log("DRY RUN — no downloads will happen\n")

    counts = {k: 0 for k in ("ok", "skip", "no_post", "no_url", "dead_svc", "fail")}

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(process, a, done_set, s3_prefix, bucket): a for a in pending}
        for i, future in enumerate(as_completed(futures), 1):
            result = future.result()
            log(f"[{i}/{len(pending)}] {result}")
            key = result.split()[0].lower()
            counts[key] = counts.get(key, 0) + 1

    log(f"\nDone: ok={counts.get('ok',0)} skip={counts.get('skip',0)} "
        f"no_post={counts.get('no_post',0)} no_url={counts.get('no_url',0)} "
        f"dead_svc={counts.get('dead_svc',0)} fail={counts.get('fail',0)}")


if __name__ == "__main__":
    main()
