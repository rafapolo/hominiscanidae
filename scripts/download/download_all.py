import json
import os
import random
import re
import socket
import subprocess
import threading
import time
import html as html_module
import requests
import gdown
from pathlib import Path
from bs4 import BeautifulSoup
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed

DEST = Path("/Volumes/EXTRA/hominiscanidae")
ROOT = Path(__file__).resolve().parents[2]
POSTS_JSON = ROOT / "posts.json"
LOG = ROOT / "download.log"
WORKERS = 64
MEGA_PROXY_HOSTS = [None, "finland", "livre", "tor"]  # local first, escalate on quota
MEGA_PROXY_PORT = 1080
MEGA_TOR_PORT = 9050  # brew tor default port
MEGA_ROTATE_AFTER = 5  # falhas consecutivas antes de rotacionar
_mega_proxy_idx = 0
_mega_proxy_lock = threading.Lock()
_mega_fail_count = 0

DEAD_SERVICES = {
    "rapidshare.com", "hotfile.com", "copy.com", "firedrive.com",
    "mirrorcreator.com", "mir.cr", "zippyshare.com", "divshare.com",
    "sendspace.com", "badongo.com", "uploading.com", "depositfiles.com",
    "multiupload.com", "sharebee.com", "wupload.com",
    "goo.gl", "ow.ly",          # Google/Hootsuite shorteners — shut down
    "dgs.wixapps.net",          # Wix file hosting — consistently dead
    "miojoindie.com.br",        # Brazilian music blog — offline
    "upload.com.br",            # File hosting — offline
    "freemusicarchive.org",     # FMA — links no longer work
    "noisey.vice.com",          # Vice Noisey — shut down
    "dosol.com.br",             # Brazilian festival — WP download-monitor, no snapshots
    "s3-sa-east-1.amazonaws.com",  # Expired pre-signed S3 URLs
    "dl.orangedox.com",         # Orangedox — shut down
    "cashmusic.org",            # CASHMusic — shut down
}
BLOCKED_SERVICES = {
    "uploaded.net", "ul.to", "turbobit.net", "keep2share.cc",
    "nitroflare.com", "katfile.com", "ddownload.com", "filefactory.com",
}
SHORT_LINKS = {"bit.ly", "tinyurl.com", "t.co"}

_local = threading.local()
_log_lock = threading.Lock()
_json_lock = threading.Lock()

posts_data = []
slug_to_idx = {}


def get_session():
    if not hasattr(_local, "s"):
        s = requests.Session()
        s.headers["User-Agent"] = (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
        _local.s = s
    return _local.s


def log(msg):
    with _log_lock:
        print(msg, flush=True)
        with open(LOG, "a") as f:
            f.write(msg + "\n")


def save_json():
    with _json_lock:
        tmp = POSTS_JSON.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(posts_data, f, ensure_ascii=False, indent=2)
        tmp.replace(POSTS_JSON)


def update_post(slug, status, downloaded_as=None, file_size=None):
    idx = slug_to_idx.get(slug)
    if idx is None:
        return
    with _json_lock:
        posts_data[idx]["status"] = status
        if downloaded_as:
            posts_data[idx]["downloaded_as"] = downloaded_as
        if file_size is not None:
            posts_data[idx]["file_size"] = file_size


def slug_from_url(url):
    return re.search(r"/([^/]+)\.html$", url).group(1)


def ext_from_url(url):
    path = urlparse(url).path
    m = re.search(r"\.(\w{2,5})$", path)
    return ("." + m.group(1).lower()) if m else ".rar"


def already_done(slug):
    # Also check underscore variant (archive.org uses underscores, slugs use hyphens)
    variants = {slug, slug.replace("-", "_")}
    for variant in variants:
        for f in DEST.glob(f"{variant}*"):
            if f.suffix == ".aria2":
                continue
            if f.is_file() and f.stat().st_size > 0:
                return f
            if f.is_dir() and any(f.iterdir()):
                return f
    return None


def resolve_shortlink(url):
    try:
        r = get_session().head(url, timeout=10, allow_redirects=True)
        if r.status_code in (404, 410):
            return None  # target is dead
        return r.url
    except Exception:
        return url  # keep original; will fail later


# ── downloaders ──────────────────────────────────────────────────────────────

def _encode_url(url):
    """Percent-encode special chars that break aria2c (brackets, backslashes, etc.)."""
    from urllib.parse import quote, urlsplit, urlunsplit
    parts = urlsplit(url)
    safe = "/:@!$&'()*+,;=?#%-._~"
    encoded_path = quote(parts.path, safe=safe)
    encoded_query = quote(parts.query, safe=safe + "=&")
    return urlunsplit((parts.scheme, parts.netloc, encoded_path, encoded_query, parts.fragment))


def run_aria2c(url, slug, ext=None):
    if ext is None:
        ext = ext_from_url(url)
    out_name = f"{slug}{ext}"
    safe_url = _encode_url(url)
    result = subprocess.run(
        [
            "aria2c",
            "-x", "16", "-s", "16",
            "--auto-file-renaming=false",
            "--allow-overwrite=false",
            "--quiet=true",
            "--connect-timeout=15",
            "--timeout=60",
            "--max-tries=2",
            "--retry-wait=3",
            "-d", str(DEST),
            "-o", out_name,
            safe_url,
        ],
        capture_output=True, text=True, timeout=300,
    )
    dest = DEST / out_name
    if dest.exists() and dest.stat().st_size > 0:
        return dest, None
    # Fallback: requests streaming download (handles redirects aria2c misses)
    try:
        s = get_session()
        r = s.get(safe_url, stream=True, timeout=30, allow_redirects=True)
        ct = r.headers.get("content-type", "")
        if r.status_code == 200:
            if "html" in ct or "text" in ct:
                return None, "dead:html-redirect"
            with open(dest, "wb") as f:
                for chunk in r.iter_content(65536):
                    f.write(chunk)
            if dest.exists() and dest.stat().st_size > 0:
                return dest, None
        elif r.status_code in (404, 410):
            return None, f"dead:{r.status_code}"
        else:
            return None, f"dead:http-{r.status_code}"
    except Exception:
        pass
    return None, result.stderr.strip() or "aria2c: empty file"


def _mega_tunnel_alive():
    try:
        s = socket.socket()
        s.settimeout(2)
        s.connect(("127.0.0.1", MEGA_PROXY_PORT))
        s.close()
        return True
    except Exception:
        return False


def _start_mega_tunnel(host=None):
    if host is None:
        host = MEGA_PROXY_HOSTS[_mega_proxy_idx]
    if host is None:  # local IP — kill tunnel, use direct
        subprocess.run(["pkill", "-f", f"ssh.*-D.*{MEGA_PROXY_PORT}"], capture_output=True)
        return True
    if host == "tor":  # already running as system service
        return True
    subprocess.run(["pkill", "-f", f"ssh.*-D.*{MEGA_PROXY_PORT}"], capture_output=True)
    time.sleep(1)
    subprocess.run([
        "ssh", "-D", str(MEGA_PROXY_PORT), "-f", "-N",
        "-o", "ExitOnForwardFailure=yes",
        "-o", "ServerAliveInterval=30",
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=10",
        host,
    ], capture_output=True, timeout=20)
    time.sleep(1)
    return _mega_tunnel_alive()


def _rotate_mega_proxy():
    global _mega_proxy_idx, _mega_fail_count
    with _mega_proxy_lock:
        _mega_fail_count += 1
        if _mega_fail_count < MEGA_ROTATE_AFTER:
            return False
        _mega_fail_count = 0
        _mega_proxy_idx = (_mega_proxy_idx + 1) % len(MEGA_PROXY_HOSTS)
        new_host = MEGA_PROXY_HOSTS[_mega_proxy_idx]
    label = new_host or "local (sem proxy)"
    log(f"Mega quota esgotado → rotacionando proxy para {label}")
    ok = _start_mega_tunnel(new_host)
    if ok:
        port = MEGA_TOR_PORT if new_host == "tor" else MEGA_PROXY_PORT
        log(f"Proxy mega: {new_host} (porta {port})")
    else:
        log(f"AVISO: tunnel SSH para {new_host} falhou")
    return ok


def dl_mega(url, slug):
    tmp = DEST / f"_mega_{slug}"
    tmp.mkdir(exist_ok=True)
    try:
        current_host = MEGA_PROXY_HOSTS[_mega_proxy_idx]
        cmd = ["megadl", "--no-ask-password", "--path", str(tmp)]
        if current_host == "tor":
            # Stream isolation: unique slug+token → different Tor circuit → different exit IP per download
            token = str(int(time.time() * 1000) % 100000)
            cmd += [f"--proxy=socks5h://{slug}{token}:x@127.0.0.1:{MEGA_TOR_PORT}"]
            dl_timeout = 600
        elif current_host is not None:
            cmd += [f"--proxy=socks5h://127.0.0.1:{MEGA_PROXY_PORT}"]
            dl_timeout = 120
        else:
            dl_timeout = 120
        cmd += [url]
        r = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=dl_timeout,
        )
        files = [f for f in tmp.iterdir() if f.is_file() and f.stat().st_size > 0]
        if not files:
            err = r.stderr.strip()
            if ("509" in err or "over quota" in err.lower() or "mega:timeout" in err.lower()
                    or "ETOOMANY" in err or "ETIME" in err or "ERATELIMIT" in err):
                _rotate_mega_proxy()
                return None, "mega:over_quota"
            if "EBLOCKED" in err:
                return None, "blocked:EBLOCKED"
            if "ENOENT" in err:
                return None, "dead:ENOENT"
            dead = any(k in err.lower() for k in ("not found", "no longer", "expired", "invalid"))
            return None, ("dead:" + err) if dead else err
        src = files[0]
        dest = DEST / f"{slug}{src.suffix.lower() or '.rar'}"
        src.rename(dest)
        global _mega_fail_count
        _mega_fail_count = 0
        return dest, None
    except subprocess.TimeoutExpired:
        return None, "mega:timeout"
    except Exception as e:
        return None, str(e)
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def dl_mediafire(url, slug):
    s = get_session()
    try:
        r = s.get(url, timeout=20)
        if r.status_code == 404:
            return None, "dead:404"
        soup = BeautifulSoup(r.text, "html.parser")
        btn = (soup.select_one("a#downloadButton")
               or soup.select_one("a.input.popsok")
               or soup.select_one('a[aria-label*="Download"]'))
        direct = btn["href"] if btn and btn.get("href") else None
        if not direct:
            m = re.search(
                r'"url"\s*:\s*"(https?://download\d*\.mediafire\.com[^"]+)"', r.text
            )
            if m:
                direct = m.group(1).replace("\\/", "/")
        if not direct:
            if "File Not Found" in r.text or "file has been removed" in r.text.lower():
                return None, "dead:removed"
            return None, "direct url not found"
        return run_aria2c(direct, slug, ext_from_url(direct))
    except Exception as e:
        return None, str(e)


def _normalize_gdrive_url(url):
    m = re.search(r'/file/d/([a-zA-Z0-9_-]+)', url)
    if m:
        return f"https://drive.google.com/uc?id={m.group(1)}"
    m = re.search(r'[?&]id=([a-zA-Z0-9_-]+)', url)
    if m:
        return f"https://drive.google.com/uc?id={m.group(1)}"
    return url


def dl_gdrive(url, slug):
    import io, sys
    try:
        dest = DEST / f"{slug}.rar"
        normalized = _normalize_gdrive_url(url)
        buf = io.StringIO()
        old_err = sys.stderr
        sys.stderr = buf
        try:
            out = gdown.download(normalized, str(dest), quiet=False)
        finally:
            sys.stderr = old_err
        captured = buf.getvalue().lower()
        dead_phrases = ("cannot retrieve", "permission", "no such file", "access denied", "403", "404")
        if not out or not Path(out).exists() or Path(out).stat().st_size == 0:
            if any(p in captured for p in dead_phrases):
                return None, "dead:gdrive-" + captured[:80].strip()
            return None, "gdown: empty or failed"
        p = Path(out)
        if p != dest:
            final = DEST / f"{slug}{p.suffix or '.rar'}"
            p.rename(final)
            return final, None
        return dest, None
    except Exception as e:
        err = str(e)
        if "404" in err or "permission" in err.lower():
            return None, "dead:" + err
        return None, err


def dl_dropbox(url, slug):
    direct = re.sub(r"[?&]dl=0", lambda m: m.group(0).replace("dl=0", "dl=1"), url)
    if "dl=1" not in direct:
        direct += ("&" if "?" in direct else "?") + "dl=1"
    return run_aria2c(direct, slug, ext_from_url(direct))


def dl_bandcamp(url, slug):
    # Expired time-limited download token → find artist page in local .md and try yt-dlp
    if "bandcamp.com/download?" in url:
        md_file = ROOT / "posts" / f"{slug}.md"
        if md_file.exists():
            text = md_file.read_text(errors="replace")
            bc_urls = re.findall(r'https?://[\w.-]+\.bandcamp\.com[^\s\)\]"\'<>]*', text)
            bc_urls += re.findall(r'http://[\w.-]+\.bandcamp\.com[^\s\)\]"\'<>]*', text)
            for bc_url in dict.fromkeys(bc_urls):
                if "bandcamp.com/download" in bc_url:
                    continue
                dest, err = dl_ytdlp(bc_url.rstrip(".,)"), slug)
                if dest:
                    return dest, None
        return None, "dead:expired-token"

    s = get_session()
    try:
        r = s.get(url, timeout=20)
        if r.status_code == 404:
            return None, "dead:404"

        blob = None
        for m in re.finditer(r'data-blob="([^"]+)"', r.text):
            try:
                d = json.loads(html_module.unescape(m.group(1)))
                if 'download_items' in d:
                    blob = d
                    break
            except Exception:
                pass

        if not blob:
            # Page exists but no free download — try yt-dlp stream
            return dl_ytdlp(url, slug)

        items = blob.get('download_items', [])
        if not items:
            return None, "dead:no download items"

        dls = items[0].get('downloads', {})
        # Prefer mp3-320, fallback to mp3-v0
        fmt_info = dls.get('mp3-320') or dls.get('mp3-v0') or next(iter(dls.values()), None)
        if not fmt_info:
            return None, "dead:no formats"

        item_url = fmt_info.get('url', '')
        if not item_url:
            return None, "dead:no item url"

        stat_url = item_url.replace("/download/", "/statdownload/")

        def parse_stat(text):
            m = re.search(r'\(\s*(\{.+\})\s*\)', text, re.DOTALL)
            return json.loads(m.group(1)) if m else None

        download_url = None
        for _ in range(10):
            rand = int(time.time() * 1000)
            clean = re.sub(r'[&?]\.rand=\d+', '', stat_url)
            sep = '&' if '?' in clean else '?'
            r2 = s.get(f"{clean}{sep}.rand={rand}&.vrs=1", timeout=20)
            data = parse_stat(r2.text)
            if not data:
                break
            if data.get('result') == 'ok':
                download_url = data.get('download_url')
                break
            retry = data.get('retry_url', '')
            if retry:
                stat_url = retry.replace("/download/", "/statdownload/")
                stat_url = re.sub(r'[&?]\.rand=\d+', '', stat_url)
            time.sleep(3)

        if not download_url:
            return dl_ytdlp(url, slug)

        return run_aria2c(download_url, slug, ".zip")
    except Exception as e:
        return None, str(e)


def dl_ytdlp(url, slug):
    out_tmpl = str(DEST / f"{slug}.%(ext)s")
    r = subprocess.run(
        ["yt-dlp", "--no-playlist", "--quiet", "--no-warnings", "-o", out_tmpl, url],
        capture_output=True, text=True, timeout=300,
    )
    files = [f for f in DEST.glob(f"{slug}.*") if f.is_file() and f.stat().st_size > 0]
    if files:
        return files[0], None
    err = r.stderr.strip()
    dead = any(k in err.lower() for k in (
        "404", "not found", "removed", "expired", "unavailable",
        "unsupported url", "this video is not available",
        "unable to extract tralbum data", "does not exist",
        "private", "fan only",
    ))
    return None, ("dead:" + err[:120]) if dead else (err[:120] or "yt-dlp: no file")


def dl_archive_details(url, slug):
    """Resolve archive.org /details/ page to actual download URL."""
    s = get_session()
    try:
        identifier = url.rstrip("/").split("/details/")[-1].split("?")[0]
        # Try the standard zip download first
        zip_url = f"https://archive.org/compress/{identifier}/formats=VBR%20MP3&file=/{identifier}.zip"
        dest, err = run_aria2c(zip_url, slug, ".zip")
        if dest:
            return dest, None
        # Fall back to downloading the item directory
        meta_url = f"https://archive.org/metadata/{identifier}"
        r = s.get(meta_url, timeout=20)
        if r.status_code == 404:
            return None, "dead:archive-404"
        meta = r.json()
        files = meta.get("files", [])
        # Pick best file: prefer zip, then rar, then largest mp3
        for ext in (".zip", ".rar"):
            for f in files:
                if f.get("name", "").lower().endswith(ext):
                    dl_url = f"https://archive.org/download/{identifier}/{f['name']}"
                    return run_aria2c(dl_url, slug, ext)
        mp3s = [f for f in files if f.get("name", "").lower().endswith(".mp3")]
        if mp3s:
            best = max(mp3s, key=lambda f: int(f.get("size", 0)))
            dl_url = f"https://archive.org/download/{identifier}/{best['name']}"
            return run_aria2c(dl_url, slug, ".mp3")
        return None, "dead:archive-no-downloadable-files"
    except Exception as e:
        return None, str(e)


def _resolve_plugin_url(url):
    """Follow redirects for WordPress download plugin URLs to get the real file URL."""
    triggers = ("?wpdmdl=", "?ddownload=", "click.php?id=", "?download=", "/contador/")
    if not any(t in url for t in triggers):
        return url
    try:
        r = get_session().get(url, timeout=15, allow_redirects=True)
        final = r.url
        if final != url and any(final.lower().endswith(e) for e in (".zip", ".rar", ".mp3", ".flac", ".wav", ".ogg")):
            return final
    except Exception:
        pass
    return url


def dl_generic(url, slug):
    resolved = _resolve_plugin_url(url)
    dest, err = run_aria2c(resolved, slug)
    if dest:
        return dest, None
    return dl_wayback(resolved, slug, original_err=err)


def dl_wayback(url, slug, original_err=None):
    """Query Wayback CDX and download the closest successful snapshot."""
    s = get_session()
    try:
        cdx = (
            "https://web.archive.org/cdx/search/cdx"
            f"?url={url}&output=json&limit=1&filter=statuscode:200"
            "&fl=timestamp&collapse=digest"
        )
        r = s.get(cdx, timeout=10)
        rows = r.json()
        if len(rows) < 2:  # only header row or empty
            return None, original_err or "wayback: no snapshot"
        ts = rows[1][0]
        wb_url = f"https://web.archive.org/web/{ts}if_/{url}"
        dest, err = run_aria2c(wb_url, slug)
        if dest:
            return dest, None
        return None, original_err or err
    except Exception as e:
        return None, original_err or str(e)


def dl_scrape_blog(post_url, slug, exclude_url=None):
    """Re-scrape blog post HTML for alternative download links."""
    s = get_session()
    DOWNLOAD_HOSTS = {
        "mega.nz", "mega.co.nz", "mediafire.com", "drive.google.com",
        "dropbox.com", "archive.org", "4shared.com", "bandcamp.com",
        "dosol.com.br", "bit.ly",
    }
    try:
        r = s.get(post_url, timeout=15)
        if r.status_code != 200:
            return None, f"dead:blog-{r.status_code}"
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r.text, "html.parser")
        seen = set()
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href or href == exclude_url:
                continue
            domain = urlparse(href).netloc.lstrip("www.")
            if not any(h in domain for h in DOWNLOAD_HOSTS):
                continue
            if href in seen:
                continue
            seen.add(href)
            dest, err = None, None
            if "mega" in domain:
                dest, err = dl_mega(href, slug)
            elif "mediafire" in domain:
                dest, err = dl_mediafire(href, slug)
            elif "drive.google" in domain:
                dest, err = dl_gdrive(href, slug)
            elif "dropbox" in domain:
                dest, err = dl_dropbox(href, slug)
            elif "bandcamp" in domain:
                dest, err = dl_ytdlp(href, slug)
            elif "4shared" in domain:
                dest, err = dl_ytdlp(href, slug)
            else:
                dest, err = dl_generic(href, slug)
            if dest:
                return dest, None
        return None, "scrape: no working alt link found"
    except Exception as e:
        return None, str(e)


def dl_generic(url, slug):
    dest, err = run_aria2c(url, slug)
    if dest:
        return dest, None
    # Fallback: try Wayback Machine snapshot
    return dl_wayback(url, slug, original_err=err)


# ── dispatcher ───────────────────────────────────────────────────────────────

def download_post(post):
    url = post["url"]
    dl = post.get("download")
    slug = slug_from_url(url)

    if not dl:
        return "no-dl"

    status = post.get("status")
    if status == "downloaded":
        return "skip-done"
    if status == "dead_link":
        return "skip-dead"
    if status == "dead_soft":
        pass  # one more attempt: blog scrape only
    if status == "blocked":
        # EBLOCKED mega links — try to find alt link in blog post
        if "mega" in post.get("download", ""):
            existing = already_done(slug)
            if existing:
                update_post(slug, "downloaded", existing.name, existing.stat().st_size)
                return "skip-exists"
            dest, err = dl_scrape_blog(url, slug, exclude_url=post.get("download"))
            if dest:
                update_post(slug, "downloaded", dest.name, dest.stat().st_size)
                log(f"OK  [{slug}] → {dest.name} ({dest.stat().st_size/1e6:.1f} MB) [via blog-scrape]")
                return "ok"
        return "skip-blocked"

    # dead_soft: skip primary download, go straight to blog scrape
    if status == "dead_soft":
        dest2, _ = dl_scrape_blog(url, slug, exclude_url=dl)
        if dest2:
            update_post(slug, "downloaded", dest2.name, dest2.stat().st_size)
            log(f"OK  [{slug}] → {dest2.name} ({dest2.stat().st_size/1e6:.1f} MB) [via blog-scrape]")
            return "ok"
        update_post(slug, "dead_link")
        return "dead"

    # Resolve short links
    domain = urlparse(dl).netloc.lstrip("www.")
    if domain in SHORT_LINKS:
        dl = resolve_shortlink(dl)
        if dl is None:
            update_post(slug, "dead_link")
            return "dead"
        domain = urlparse(dl).netloc.lstrip("www.")

    # Dead services — no request needed (check exact and subdomains)
    if any(domain == d or domain.endswith("." + d) for d in DEAD_SERVICES):
        update_post(slug, "dead_link")
        return "dead"

    # Blocked services (paywall / login required) — no request needed
    if any(domain == d or domain.endswith("." + d) for d in BLOCKED_SERVICES):
        update_post(slug, "blocked")
        return "blocked"

    # Already on disk
    existing = already_done(slug)
    if existing:
        update_post(slug, "downloaded", existing.name, existing.stat().st_size)
        return "skip-exists"

    # Dispatch
    if "mega.nz" in domain or "mega.co.nz" in domain:
        dest, err = dl_mega(dl, slug)
    elif "mediafire.com" in domain:
        dest, err = dl_mediafire(dl, slug)
    elif "drive.google.com" in domain or "docs.google.com" in domain:
        dest, err = dl_gdrive(dl, slug)
    elif "dropbox.com" in domain or "dl.dropbox.com" in domain:
        dest, err = dl_dropbox(dl, slug)
    elif "bandcamp.com" in domain:
        dest, err = dl_bandcamp(dl, slug)
    elif "4shared.com" in domain:
        dest, err = dl_ytdlp(dl, slug)
    elif "archive.org" in domain and "/details/" in dl:
        dest, err = dl_archive_details(dl, slug)
    else:
        dest, err = dl_generic(dl, slug)

    if dest:
        update_post(slug, "downloaded", dest.name, dest.stat().st_size)
        log(f"OK  [{slug}] → {dest.name} ({dest.stat().st_size/1e6:.1f} MB)")
        return "ok"

    is_dead = err and err.startswith("dead:")
    is_blocked = err and err.startswith("blocked:")

    # Last resort: re-scrape blog post for alternative download links
    # Runs for all failures including dead: (but not blocked:)
    if not is_blocked:
        dest2, _ = dl_scrape_blog(url, slug, exclude_url=dl)
        if dest2:
            update_post(slug, "downloaded", dest2.name, dest2.stat().st_size)
            log(f"OK  [{slug}] → {dest2.name} ({dest2.stat().st_size/1e6:.1f} MB) [via blog-scrape]")
            return "ok"

    if is_dead:
        # dead_soft had its blog scrape chance — now permanently dead
        new_status = "dead_link"
        label = "DEAD"
    elif is_blocked:
        new_status = "blocked"
        label = "BLKD"
    else:
        new_status = "failed"
        label = "FAIL"
    update_post(slug, new_status)
    log(f"{label} [{slug}] {domain}: {err}")
    return new_status


# ── nolink scraper ───────────────────────────────────────────────────────────

def scrape_nolink_posts():
    """Read local posts/*.md files to find download links for posts missing them."""
    DOWNLOAD_HOSTS = {
        "mega.nz", "mega.co.nz", "mediafire.com", "drive.google.com",
        "docs.google.com", "dropbox.com", "dl.dropbox.com", "dl.dropboxusercontent.com",
        "archive.org", "4shared.com", "bandcamp.com", "bit.ly", "tinyurl.com",
    }
    POSTS_DIR = ROOT / "posts"
    no_link = [p for p in posts_data if not p.get("download")]
    if not no_link:
        return
    log(f"Buscando links em {len(no_link)} posts locais sem download...")
    found = 0
    for p in no_link:
        m = re.search(r"/([^/]+)\.html$", p["url"])
        if not m:
            continue
        slug = m.group(1)
        md_file = POSTS_DIR / f"{slug}.md"
        if not md_file.exists():
            continue
        text = md_file.read_text(errors="replace")
        # Extract all URLs from markdown links [text](url) and bare http links
        urls = re.findall(r'\bhttps?://[^\s\)\]"\'<>]+', text)
        for href in urls:
            href = href.rstrip(".,)")
            domain = urlparse(href).netloc.lstrip("www.")
            if any(h in domain for h in DOWNLOAD_HOSTS):
                p["download"] = href
                p["status"] = "not_downloaded"
                found += 1
                break
    if found:
        save_json()
        log(f"Encontrados links em {found} posts sem download")


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    global posts_data, slug_to_idx

    # Kill any orphaned subprocesses from previous interrupted runs
    subprocess.run(["pkill", "-f", "megadl --no-ask-password"], capture_output=True)
    subprocess.run(["pkill", "-f", f"aria2c.*{DEST}"], capture_output=True)

    # Start SSH SOCKS tunnel for Mega (routes through proxy → fresh IP quota)
    first_host = MEGA_PROXY_HOSTS[_mega_proxy_idx]
    if _start_mega_tunnel(first_host):
        port = MEGA_TOR_PORT if first_host == "tor" else MEGA_PROXY_PORT
        log(f"Proxy mega: {first_host} (porta {port})")
    else:
        log(f"AVISO: tunnel SSH para {first_host} falhou — mega sem proxy")

    DEST.mkdir(parents=True, exist_ok=True)
    with open(POSTS_JSON) as f:
        posts_data = json.load(f)

    slug_to_idx = {}
    for i, p in enumerate(posts_data):
        m = re.search(r"/([^/]+)\.html$", p["url"])
        if m:
            slug_to_idx[m.group(1)] = i

    # Initialise status field and reset failed → not_downloaded for retry
    changed = 0
    reset = 0
    for p in posts_data:
        if not p.get("download"):
            continue
        if "status" not in p:
            if p.get("downloaded_as"):
                p["status"] = "downloaded"
            else:
                p["status"] = "not_downloaded"
            changed += 1
        elif p.get("status") == "failed":
            p["status"] = "not_downloaded"
            reset += 1
        # blocked stays blocked — requires manual intervention
    if changed or reset:
        save_json()
        if changed:
            log(f"Inicializado status em {changed} posts")
        if reset:
            log(f"Reset {reset} posts failed/dead_link → not_downloaded/dead_soft para retry")

    scrape_nolink_posts()

    to_process = [p for p in posts_data
                  if p.get("download") and p.get("status") not in ("downloaded", "dead_link", "blocked", "failed", None)]
    random.shuffle(to_process)
    total = len(to_process)
    counts = {k: 0 for k in ("ok", "dead", "error", "skip-done", "skip-exists", "skip-dead")}

    already = sum(1 for p in posts_data if p.get("status") == "downloaded")
    grand_total = sum(1 for p in posts_data if p.get("download"))
    log(f"Já baixados: {already} | A processar: {total} | Total geral: {grand_total} → {DEST}")

    _progress = {"done": 0, "counts": counts}
    _stop = threading.Event()
    start_time = time.time()

    def progress_reporter():
        while not _stop.is_set():
            _stop.wait(60)
            if _stop.is_set():
                break
            d = _progress["done"]
            c = _progress["counts"]
            elapsed = time.time() - start_time
            pct_session = d / total * 100 if total else 0
            overall_done = already + c.get("ok", 0) + c.get("skip-exists", 0)
            pct_overall = overall_done / grand_total * 100 if grand_total else 0
            rate = d / elapsed * 60 if elapsed > 0 else 0
            eta_min = (total - d) / (d / elapsed) / 60 if d > 0 else 0
            log(
                f"── {pct_overall:.1f}% geral ({overall_done}/{grand_total}) │ "
                f"sessão {pct_session:.1f}% ({d}/{total}) │ "
                f"{rate:.0f}/min │ ETA ~{eta_min:.0f}min │ "
                f"ok={c.get('ok',0)} dead={c.get('dead',0)+c.get('dead_link',0)} blkd={c.get('blocked',0)} fail={c.get('failed',0)}"
            )

    reporter = threading.Thread(target=progress_reporter, daemon=True)
    reporter.start()

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(download_post, p): p for p in to_process}
        for future in as_completed(futures):
            result = future.result()
            _progress["done"] += 1
            counts[result] = counts.get(result, 0) + 1
            if _progress["done"] % 50 == 0:
                save_json()

    _stop.set()

    save_json()
    downloaded = sum(1 for p in posts_data if p.get("status") == "downloaded")
    dead = sum(1 for p in posts_data if p.get("status") in ("dead_link", "dead_soft"))
    blocked = sum(1 for p in posts_data if p.get("status") == "blocked")
    failed = sum(1 for p in posts_data if p.get("status") == "failed")
    pending = sum(1 for p in posts_data if p.get("status") == "not_downloaded")
    total_size = sum(p.get("file_size") or 0 for p in posts_data if p.get("status") == "downloaded")
    log(f"\nConcluído: downloaded={downloaded} dead={dead} blocked={blocked} failed={failed} pending={pending} | {total_size/1e9:.2f} GB")


if __name__ == "__main__":
    main()
