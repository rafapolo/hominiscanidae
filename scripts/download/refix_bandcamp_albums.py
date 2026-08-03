#!/usr/bin/env python3
"""Re-fetch Bandcamp albums that were truncated to a single track.

`dl_bandcamp` used to treat every `bandcamp.com/download?` URL as an expired
token without requesting it, so those posts fell through to `dl_ytdlp`. That
fallback wrote every track of the album to one filename, appending each track's
bytes behind the first track's container; `flac_to_mp3.py` then transcoded only
what the MP4 header described (track 1) and deleted the source.

Both bugs are fixed upstream. This repairs the albums already damaged: it pulls
the real album ZIP through the fixed path and swaps it in for the stub folder.

    python3 scripts/download/refix_bandcamp_albums.py --list
    python3 scripts/download/refix_bandcamp_albums.py --dry-run
    python3 scripts/download/refix_bandcamp_albums.py
"""

import json
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "utils"))

import download_all as dl
from unzip import safe_folder, load_state, save_state, UNAR, UNRAR

ROOT = Path(__file__).resolve().parents[2]
POSTS = ROOT / "posts.json"
DEST = dl.DEST
UNZIPS = DEST / "unzips"

DRY = "--dry-run" in sys.argv
LIST_ONLY = "--list" in sys.argv
# Repair a slug the detector no longer flags — e.g. one already replaced by a
# whole-discography dump, which has plenty of tracks but is still the wrong album.
ONLY = next((a.split("=", 1)[1].split(",") for a in sys.argv
             if a.startswith("--only=")), None)


def find_damaged(posts):
    """Folders holding exactly one mp3 that is a fraction of the recorded download."""
    by_stem = {}
    for p in posts:
        da = p.get("downloaded_as")
        if da:
            by_stem.setdefault(Path(da).stem, p)

    out = []
    for d in sorted(UNZIPS.iterdir()):
        if not d.is_dir():
            continue
        mp3s = list(d.glob("*.mp3"))
        if len(mp3s) != 1:
            continue
        p = by_stem.get(mp3s[0].stem)
        if not p:
            continue
        # A flat <slug>.m4a is the yt-dlp fallback's signature — the original
        # download URL may be some dead host that the blog-scrape bypassed.
        if "bandcamp.com" not in (p.get("download") or "") \
                and not (p.get("downloaded_as") or "").endswith(".m4a"):
            continue
        recorded = p.get("file_size") or 0
        actual = mp3s[0].stat().st_size
        if recorded > 3 * actual and recorded > 10_000_000:
            out.append((p, d, recorded, actual))
    return out


def extract_zip(archive: Path, target: Path) -> int:
    """Extract into target, replacing whatever was there. Returns track count."""
    with tempfile.TemporaryDirectory(dir=str(DEST), prefix=".refix-") as tmpd:
        tmp = Path(tmpd)
        ok, msg = dl_run([UNAR, "-q", "-o", str(tmp), str(archive)])
        if not ok:
            for f in tmp.iterdir():
                shutil.rmtree(f, ignore_errors=True) if f.is_dir() else f.unlink()
            ok, msg = dl_run([UNRAR, "x", "-y", "-kb", "-o+", str(archive), str(tmp) + "/"])
        if not ok:
            raise RuntimeError(f"extract failed: {msg}")

        produced = [p for p in tmp.iterdir() if not p.name.startswith(".")]
        if not produced:
            raise RuntimeError("archive produced nothing")

        # Bandcamp ZIPs hold loose tracks; other sources may wrap them in a folder.
        if len(produced) == 1 and produced[0].is_dir():
            src = produced[0]
        else:
            src = tmp / "__wrap__"
            src.mkdir()
            for p in produced:
                shutil.move(str(p), str(src / p.name))

        shutil.rmtree(target, ignore_errors=True)
        shutil.move(str(src), str(target))

    for f in list(target.rglob("*")):
        if f.is_file() and f.stat().st_size == 0:
            f.unlink()
    return len(list(target.rglob("*.mp3")))


def bandcamp_urls(p, slug):
    """Every Bandcamp URL for this post: the recorded download plus any in the .md."""
    urls = []
    if "bandcamp.com" in (p.get("download") or ""):
        urls.append(p["download"])
    md = ROOT / "posts" / f"{slug}.md"
    if md.exists():
        urls += [u.rstrip(".,)") for u in re.findall(
            r'https?://[\w.-]*bandcamp\.com[^\s\)\]"\'<>]*',
            md.read_text(errors="replace"))]
    return list(dict.fromkeys(urls))


def norm(s):
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", s.lower())
                  .encode("ascii", "ignore").decode())


def md_album_name(slug):
    """Album name from the post's `Download: [<name>.zip]` link text.

    posts.json titles are truncated ("Nosso Querido Figueiredo Nos Tambem Nao");
    the .md carries the real one ("Nós Também Não EP (2015)").
    """
    md = ROOT / "posts" / f"{slug}.md"
    if not md.exists():
        return None
    m = re.search(r"\[([^\]]+?)\.(?:zip|rar|7z)\]\(", md.read_text(errors="replace"))
    return re.sub(r"\s*\(\d{4}\)\s*$", "", m.group(1)).strip() if m else None


def pick_album(title, artist_root, alt_name=None):
    """The one /album/ on an artist page matching this post.

    Handing yt-dlp the artist root pulls the entire discography into a single
    folder — 35 tracks with five different "01"s. Match the post title instead.
    """
    base = re.sub(r"/(music|album|track)(/.*)?$", "", artist_root.rstrip("/"))
    s = dl.get_session()
    hrefs = {}
    for page in (base + "/music", base):
        try:
            r = s.get(page, timeout=20)
        except Exception:
            continue
        hrefs.update(dict.fromkeys(re.findall(r'href="(/album/[^"?#]+)"', r.text)))
        if hrefs:
            break
    if not hrefs:
        return None

    # Post titles read "<artist> <album>" while the slug is usually just the
    # album, so score every suffix of the title — that drops the artist prefix.
    # Without it "Irmãos Panarotto 2violão e 1balde" scores highest against
    # /album/irm-os-panarotto-imp-rio-da-l purely on the repeated artist name.
    words = re.split(r"[\s\-–—]+", title)
    variants = [norm(" ".join(words[i:])) for i in range(len(words))]
    if alt_name:
        variants.append(norm(alt_name))
    variants = [v for v in variants if v]

    best, score = None, 0.0
    for h in hrefs:
        cand = norm(h.rsplit("/", 1)[-1])
        if not cand:
            continue
        ratio = max(SequenceMatcher(None, v, cand).ratio() for v in variants)
        if ratio > score:
            best, score = base + h, ratio
    return best if score >= 0.7 else None


def fetch(p, slug):
    """The album ZIP — never the whole discography."""
    title = p.get("title") or slug
    urls = bandcamp_urls(p, slug)

    # Live /download? token, or a page pointing straight at one release.
    for u in urls:
        if any(k in u for k in ("/download?", "/album/", "/track/")):
            dest, _ = dl.dl_bandcamp_page(u, slug)
            if dest:
                return dest, None

    # Token expired → resolve the specific album off the artist page.
    for u in urls:
        if "/download?" in u:
            continue
        album = pick_album(title, u, md_album_name(slug))
        if not album:
            continue
        print(f"     [{slug}] token expirado, casando título -> {album}")
        dest, _ = dl.dl_bandcamp_page(album, slug)
        if dest:
            return dest, None

    return None, "nenhum álbum bandcamp resolvido"


def dl_run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    return r.returncode == 0, (r.stderr or r.stdout).strip()[:200]


def main():
    if not DEST.is_dir():
        sys.exit(f"ABORT: {DEST} não está montado")

    posts = json.loads(POSTS.read_text())
    dl.posts_data = posts
    dl.slug_to_idx = {dl.slug_from_url(p["url"]): i for i, p in enumerate(posts)}

    damaged = find_damaged(posts)
    if ONLY:
        seen = {dl.slug_from_url(p["url"]) for p, _, _, _ in damaged}
        for p in posts:
            s = dl.slug_from_url(p["url"])
            if s in ONLY and s not in seen:
                damaged.append((p, UNZIPS / safe_folder(p.get("title") or s), 0, 0))
        damaged = [d for d in damaged if dl.slug_from_url(d[0]["url"]) in ONLY]

    print(f"{len(damaged)} álbuns truncados\n")
    for p, d, rec, act in damaged:
        print(f"  {rec/1e6:7.1f}MB -> {act/1e6:5.1f}MB  {d.name}")
    if LIST_ONLY or not damaged:
        return
    print()

    state = load_state()
    ok = failed = 0
    for p, folder, rec, act in damaged:
        slug = dl.slug_from_url(p["url"])
        title = safe_folder(p.get("title") or slug)
        if DRY:
            print(f"DRY  [{slug}] baixaria {p['download'][:60]}… -> {title}/")
            continue

        dest, err = fetch(p, slug)
        if not dest:
            print(f"FAIL [{slug}] {err}")
            failed += 1
            continue

        # Measure before moving — a folder result no longer exists afterwards.
        dest_name, dest_size = dest.name, dl.path_size(dest)
        try:
            target = UNZIPS / title
            if dest.is_dir():
                # yt-dlp fallback returned a per-track folder, nothing to extract
                shutil.rmtree(target, ignore_errors=True)
                shutil.move(str(dest), str(target))
                n = len(list(target.rglob("*")))
            else:
                n = extract_zip(dest, target)
        except Exception as e:
            print(f"FAIL [{slug}] {e}")
            failed += 1
            continue

        if folder.name != title and folder.exists():
            shutil.rmtree(folder, ignore_errors=True)

        state[dest_name] = {"folder": title, "by": "refix-bandcamp"}
        dl.update_post(slug, "downloaded", dest_name, dest_size)
        print(f"OK   [{slug}] {n} faixas -> {title}/ ({dest_size/1e6:.1f} MB)")
        ok += 1
        save_state(state)
        POSTS.write_text(json.dumps(posts, ensure_ascii=False, indent=2))

    print(f"\nConcluído: {ok} recuperados, {failed} falharam")
    if ok:
        print("\nConvertendo para MP3…")
        subprocess.run([sys.executable,
                        str(ROOT / "scripts/utils/flac_to_mp3.py")], check=False)


if __name__ == "__main__":
    main()
