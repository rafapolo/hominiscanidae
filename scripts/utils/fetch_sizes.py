import json
import re
import threading
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
POSTS_JSON = ROOT / "posts.json"
WORKERS = 30

_local = threading.local()

def get_session():
    if not hasattr(_local, "session"):
        s = requests.Session()
        s.headers["User-Agent"] = "Mozilla/5.0 (compatible; sitemap-scraper/1.0)"
        _local.session = s
    return _local.session


def normalize_url(url: str) -> str:
    # Dropbox: force direct download to get Content-Length
    url = re.sub(r'[?&]dl=0', lambda m: m.group(0).replace('dl=0', 'dl=1'), url)
    # Google Drive: use export/download endpoint
    m = re.search(r'drive\.google\.com/file/d/([^/]+)', url)
    if m:
        return f"https://drive.google.com/uc?export=download&id={m.group(1)}"
    return url


def get_file_size(entry: dict) -> dict:
    url = entry.get("download")
    if not url:
        return {**entry, "file_size": None}

    fetch_url = normalize_url(url)
    session = get_session()

    try:
        resp = session.head(fetch_url, timeout=15, allow_redirects=True)
        cl = resp.headers.get("Content-Length") or resp.headers.get("content-length")
        if cl:
            return {**entry, "file_size": int(cl)}

        # Fallback: stream first bytes to get Content-Length after redirect
        resp2 = session.get(fetch_url, timeout=15, stream=True, allow_redirects=True)
        cl2 = resp2.headers.get("Content-Length") or resp2.headers.get("content-length")
        resp2.close()
        return {**entry, "file_size": int(cl2) if cl2 else None}

    except Exception:
        return {**entry, "file_size": None}


def main():
    with open(POSTS_JSON, encoding="utf-8") as f:
        posts = json.load(f)

    has_download = sum(1 for p in posts if p.get("download"))
    print(f"Posts com download: {has_download}/{len(posts)}")

    total = len(posts)
    results = [None] * total
    done = 0

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(get_file_size, p): i for i, p in enumerate(posts)}
        for future in as_completed(futures):
            idx = futures[future]
            results[idx] = future.result()
            done += 1
            if done % 1000 == 0:
                print(f"[{done}/{total}]")

    with open(POSTS_JSON, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    with_size = sum(1 for p in results if p and p.get("file_size"))
    total_bytes = sum(p["file_size"] for p in results if p and p.get("file_size"))
    print(f"\nConcluído: {with_size} com tamanho | total estimado: {total_bytes / 1e9:.2f} GB")


if __name__ == "__main__":
    main()
