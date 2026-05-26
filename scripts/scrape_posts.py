import json
import re
import sys
import requests
import html2text
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urljoin, urlparse

POSTS_DIR = Path(__file__).parent / "posts"
POSTS_JSON = Path(__file__).parent / "posts.json"
SITEMAP_URL = "https://www.hominiscanidae.org/sitemap.xml"
WORKERS = 20

h = html2text.HTML2Text()
h.ignore_links = False
h.ignore_images = False
h.body_width = 0

import threading
_local = threading.local()


def get_session():
    if not hasattr(_local, "session"):
        s = requests.Session()
        s.headers["User-Agent"] = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        _local.session = s
    return _local.session


def slug_from_url(url: str) -> str | None:
    m = re.search(r"/([^/]+)\.html$", url)
    return m.group(1) if m else None


def extract_download(md_text: str) -> str | None:
    for line in md_text.splitlines():
        if "Download" in line:
            links = re.findall(r'\[([^\]]*)\]\(([^)]+)\)', line)
            non_yt = [url for _, url in links
                      if "youtube.com" not in url and "youtu.be" not in url]
            if non_yt:
                return non_yt[-1]
    return None


def fetch_post(entry: dict, force: bool = False) -> dict:
    url = entry["url"]
    slug = slug_from_url(url)
    if not slug:
        return {**entry, "title": None, "download": None}

    dest = POSTS_DIR / f"{slug}.md"
    result = {**entry}
    session = get_session()

    # Re-use existing .md unless it's empty or force-refetch
    if dest.exists() and dest.stat().st_size > 0 and not force:
        md_text = dest.read_text(encoding="utf-8")
        result["download"] = extract_download(md_text)
        try:
            resp = session.get(url, timeout=(5, 10))
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            title_el = (soup.select_one(".post-title .entry-title")
                        or soup.select_one(".entry-title"))
            result["title"] = title_el.get_text(strip=True) if title_el else entry.get("title")
        except Exception:
            pass
        return result

    try:
        resp = session.get(url, timeout=(5, 10))
        resp.raise_for_status()
    except Exception as e:
        result["title"] = entry.get("title")
        result["download"] = entry.get("download")
        result["error"] = str(e)
        return result

    soup = BeautifulSoup(resp.text, "html.parser")

    title_el = (soup.select_one(".post-title .entry-title")
                or soup.select_one(".entry-title"))
    result["title"] = title_el.get_text(strip=True) if title_el else entry.get("title")

    content = (soup.select_one(".post-body .entry-content")
               or soup.select_one(".entry-content")
               or soup.select_one(".post-body"))
    if content:
        md_text = h.handle(str(content)).strip()
        dest.write_text(md_text, encoding="utf-8")
        result["download"] = extract_download(md_text)
    else:
        result["download"] = entry.get("download")

    return result


def find_posts_by_label_local(label_url: str, posts: list[dict]) -> list[dict]:
    """Find posts matching a label using only local posts/*.md and posts.json.

    Matches by:
    1. Slug contains all keywords from the label name (accent-normalized)
    2. Any .md file contains the label URL or label name as text
    """
    import unicodedata
    from urllib.parse import unquote

    def to_ascii(s: str) -> str:
        return unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode()

    # Extract label name from URL: .../search/label/Foo%20Bar → "foo bar"
    m = re.search(r"/search/label/(.+)$", label_url)
    label_name = unquote(m.group(1)).lower() if m else label_url.lower()
    # Normalize accents for slug matching (slugs are always ASCII)
    label_ascii = to_ascii(label_name)
    keywords = [k for k in re.split(r"[\s%+\-]+", label_ascii) if k]

    label_url_norm = label_url.lower()
    matched = []
    matched_urls = set()

    for p in posts:
        url = p["url"]
        if url in matched_urls:
            continue
        slug = slug_from_url(url) or ""
        slug_lower = slug.lower()

        # Match 1: all keywords present in slug
        if all(k in slug_lower for k in keywords):
            matched.append(p)
            matched_urls.add(url)
            continue

        # Match 2: label URL or name appears in .md content
        md_file = POSTS_DIR / f"{slug}.md"
        if md_file.exists() and md_file.stat().st_size > 0:
            try:
                text = md_file.read_text(errors="replace").lower()
                if label_url_norm in text or label_name in text:
                    matched.append(p)
                    matched_urls.add(url)
            except Exception:
                pass

    return matched


def fetch_sitemap_urls(sitemap_url: str) -> list[str]:
    """Fetch all post URLs from the sitemap (handles sitemap index)."""
    session = get_session()
    urls = []

    def parse_sitemap(url):
        try:
            resp = session.get(url, timeout=(5, 30))
            resp.raise_for_status()
        except Exception as e:
            print(f"Erro ao buscar sitemap {url}: {e}")
            return
        soup = BeautifulSoup(resp.text, "xml")
        # Sitemap index: has <sitemap> tags
        for loc in soup.select("sitemap > loc"):
            parse_sitemap(loc.text.strip())
        # Regular sitemap: has <url> tags
        for loc in soup.select("url > loc"):
            u = loc.text.strip()
            if ".html" in u:
                urls.append(u)

    parse_sitemap(sitemap_url)
    return urls


def merge_urls_into_posts(new_urls: list[str], posts: list[dict]) -> tuple[list[dict], list[dict]]:
    """Add URLs not already in posts. Returns (updated_posts, new_entries)."""
    existing = {p["url"] for p in posts}
    new_entries = []
    for url in new_urls:
        if url not in existing:
            new_entries.append({
                "url": url,
                "lastmod": None,
                "title": None,
                "download": None,
                "file_size": None,
                "downloaded_as": None,
            })
    return posts + new_entries, new_entries


def process_posts(posts: list[dict], targets: list[dict] | None = None, force: bool = False):
    """Fetch/re-fetch posts. targets=None means all; otherwise only those entries."""
    work = targets if targets is not None else posts
    slug_to_idx = {p["url"]: i for i, p in enumerate(posts)}
    done = 0
    total = len(work)

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(fetch_post, p, force): p["url"] for p in work}
        for future in as_completed(futures):
            result = future.result()
            url = futures[future]
            if url in slug_to_idx:
                posts[slug_to_idx[url]] = result
            done += 1
            if done % 100 == 0:
                print(f"  [{done}/{total}]", flush=True)

    return posts


def save_posts(posts: list[dict]):
    with open(POSTS_JSON, "w", encoding="utf-8") as f:
        json.dump(posts, f, ensure_ascii=False, indent=2)


def main():
    POSTS_DIR.mkdir(exist_ok=True)

    with open(POSTS_JSON, encoding="utf-8") as f:
        posts = json.load(f)

    args = sys.argv[1:]

    # --label <url>  →  find matching posts locally, re-fetch missing/empty .md
    if args and args[0] == "--label":
        label_url = args[1] if len(args) > 1 else None
        if not label_url:
            print("Uso: scrape_posts.py --label <url>")
            sys.exit(1)
        print(f"Buscando posts do label (local): {label_url}")
        matched = find_posts_by_label_local(label_url, posts)
        print(f"  {len(matched)} posts encontrados localmente")

        targets = []
        for p in matched:
            slug = slug_from_url(p["url"])
            if not slug:
                continue
            md = POSTS_DIR / f"{slug}.md"
            if not md.exists() or md.stat().st_size == 0:
                targets.append(p)
                print(f"  .md ausente/vazio: {slug}")

        if targets:
            print(f"  Re-fetching {len(targets)} posts com .md ausentes/vazios...")
            posts = process_posts(posts, targets=targets, force=True)
            save_posts(posts)
        else:
            print("  Todos os .md presentes e não-vazios.")

    # --sitemap [url]  →  rescan sitemap, merge new posts, fetch missing
    elif args and args[0] == "--sitemap":
        sitemap_url = args[1] if len(args) > 1 else SITEMAP_URL
        print(f"Rescaneando sitemap: {sitemap_url}")
        sitemap_urls = fetch_sitemap_urls(sitemap_url)
        print(f"  {len(sitemap_urls)} URLs no sitemap")
        posts, new_entries = merge_urls_into_posts(sitemap_urls, posts)
        if new_entries:
            print(f"  {len(new_entries)} novos posts adicionados")

        # Also catch existing posts with missing/empty .md
        missing_md = []
        for p in posts:
            slug = slug_from_url(p["url"])
            if not slug:
                continue
            md = POSTS_DIR / f"{slug}.md"
            if not md.exists() or md.stat().st_size == 0:
                missing_md.append(p)

        targets = list({p["url"]: p for p in new_entries + missing_md}.values())
        print(f"  Fetching {len(targets)} posts (novos + .md ausentes/vazios)...")
        posts = process_posts(posts, targets=targets, force=True)
        save_posts(posts)

    # default: process all posts (re-use existing .md, re-fetch missing/empty)
    else:
        total = len(posts)
        print(f"Processando {total} posts (re-fetch apenas .md ausentes/vazios)...")
        posts = process_posts(posts, targets=None, force=False)
        save_posts(posts)

    errors = [p for p in posts if p.get("error")]
    no_title = sum(1 for p in posts if not p.get("title"))
    print(f"\nConcluído: {len(posts)} posts, {len(errors)} erros, {no_title} sem título")


if __name__ == "__main__":
    main()
