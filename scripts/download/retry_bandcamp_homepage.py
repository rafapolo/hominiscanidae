#!/usr/bin/env python3
"""Recover dead_link posts that only have a bare Bandcamp artist homepage.

Strategy:
  1. yt-dlp --flat-playlist on the homepage to list album URLs + titles
  2. Fuzzy-match post title against album titles (word overlap + sequence ratio)
  3. Download the best match if score >= threshold
"""
import json
import re
import subprocess
import time
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urlparse

DEST = Path("/Volumes/EXTRA/hominiscanidae")
ROOT = Path(__file__).resolve().parents[2]
POSTS_JSON = ROOT / "posts.json"
POSTS_DIR = ROOT / "posts"
DELAY = 5       # seconds between yt-dlp calls
MATCH_THRESHOLD = 0.28  # minimum similarity score to attempt download

BANDCAMP_RE = re.compile(
    r'https?://[\w.-]+\.bandcamp\.com[^\s\)\]"\'<>]*', re.IGNORECASE
)


STOPWORDS = {"de", "do", "da", "dos", "das", "e", "a", "o", "os", "as", "ep", "lp",
             "vol", "ao", "em", "um", "uma", "com", "para", "por", "the", "of", "and"}
YEAR_RE = re.compile(r"^(19|20)\d{2}$")


def normalize(s):
    s = unicodedata.normalize("NFKD", s)
    s = s.encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9 ]", " ", s.lower())
    return [w for w in s.split() if w not in STOPWORDS and not YEAR_RE.match(w)]


def similarity(post_words, album_words):
    """Score how well album_words (from URL slug) matches post_words (from slug/title).

    Primary: fraction of album words found in post (avoids penalising long post slugs).
    Secondary: fraction of post words matched (prevents trivially short album slugs winning).
    Cat: character-level ratio on concatenated words — catches accented chars that Bandcamp
         encodes as hyphens in slugs (e.g. "molécula" → "mol-cula" → words ["mol","cula"]).
    """
    post_set, album_set = set(post_words), set(album_words)
    if not album_set:
        return 0.0
    primary = len(post_set & album_set) / len(album_set)
    secondary = len(post_set & album_set) / max(len(post_set), 1)
    word_score = primary * 0.7 + secondary * 0.3
    cat_score = SequenceMatcher(None, "".join(post_words), "".join(album_words)).ratio()
    return max(word_score, cat_score * 0.85)


def list_albums(homepage):
    """Return list of (album_url, album_basename_words) from yt-dlp flat playlist.

    yt-dlp flat-playlist returns no titles for Bandcamp discography pages, so we
    match on the URL slug (webpage_url_basename) instead.
    """
    try:
        r = subprocess.run(
            ["yt-dlp", "--flat-playlist", "--quiet", "--no-warnings",
             "--dump-json", "--socket-timeout", "30", homepage],
            capture_output=True, text=True, timeout=60,
        )
    except subprocess.TimeoutExpired:
        return []
    albums = []
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        url = entry.get("url") or entry.get("webpage_url") or ""
        basename = entry.get("webpage_url_basename") or url.rstrip("/").split("/")[-1]
        # Only keep /album/ paths (skip individual tracks)
        if url and "/album/" in url:
            albums.append((url, normalize(basename.replace("-", " "))))
    return albums


def try_ytdlp(url, slug):
    out_tmpl = str(DEST / f"{slug}.%(ext)s")
    try:
        subprocess.run(
            ["yt-dlp", "--no-playlist", "--quiet", "--no-warnings",
             "--socket-timeout", "30", "-o", out_tmpl, url],
            capture_output=True, text=True, timeout=300,
        )
    except subprocess.TimeoutExpired:
        pass
    files = [f for f in DEST.glob(f"{slug}.*") if f.is_file() and f.stat().st_size > 0]
    return files[0] if files else None


def extract_bare_homepages(slug):
    md = POSTS_DIR / f"{slug}.md"
    if not md.exists():
        return []
    text = md.read_text(errors="replace")
    urls = [u.rstrip(".,)") for u in BANDCAMP_RE.findall(text)]
    result = []
    for u in urls:
        if "bandcamp.com/download" in u:
            continue
        path = urlparse(u).path.strip("/")
        if path:
            continue  # has album path — handled by retry_bandcamp.py
        result.append(u)
    return list(dict.fromkeys(result))


def main():
    with open(POSTS_JSON) as f:
        posts = json.load(f)

    slug_to_idx = {}
    for i, p in enumerate(posts):
        m = re.search(r"/([^/]+)\.html$", p["url"])
        if m:
            slug_to_idx[m.group(1)] = i

    dead = [p for p in posts if p.get("status") == "dead_link"]

    targets = []
    for p in dead:
        m = re.search(r"/([^/]+)\.html$", p["url"])
        if not m:
            continue
        slug = m.group(1)
        homepages = extract_bare_homepages(slug)
        if homepages:
            targets.append((slug, p.get("title", ""), homepages[0]))

    print(f"Bare-homepage targets: {len(targets)}\n")

    ok = fail = skip = no_albums = low_score = 0

    for i, (slug, title, homepage) in enumerate(targets):
        # Skip if already on disk
        existing = [f for f in DEST.glob(f"{slug}.*") if f.is_file() and f.stat().st_size > 0]
        if existing:
            skip += 1
            continue

        albums = list_albums(homepage)
        time.sleep(DELAY)

        if not albums:
            no_albums += 1
            print(f"NO_ALBUMS [{slug}] {homepage}")
            continue

        # Match using both slug words and title words for broader coverage
        slug_words = normalize(slug.replace("-", " "))
        title_words = normalize(title)
        post_words = list(dict.fromkeys(slug_words + title_words))

        best_url, best_score, best_basename = None, 0.0, ""
        for album_url, album_words in albums:
            score = similarity(post_words, album_words)
            if score > best_score:
                best_score, best_url, best_basename = score, album_url, " ".join(album_words)

        if best_score < MATCH_THRESHOLD:
            low_score += 1
            print(f"LOW_SCORE [{slug}] score={best_score:.2f} best='{best_basename}'")
            for au, aw in albums[:5]:
                print(f"  candidate: {' '.join(aw)!r} → {au}")
            continue

        print(f"TRY [{slug}] score={best_score:.2f} '{best_basename}' → {best_url}")
        dest = try_ytdlp(best_url, slug)
        time.sleep(DELAY)

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
            print(f"FAIL [{slug}]")

        if ok % 10 == 0 and ok > 0:
            with open(POSTS_JSON, "w") as f:
                json.dump(posts, f, ensure_ascii=False, indent=2)

    with open(POSTS_JSON, "w") as f:
        json.dump(posts, f, ensure_ascii=False, indent=2)

    print(f"\nConcluído: ok={ok} fail={fail} skip={skip} no_albums={no_albums} low_score={low_score}")


if __name__ == "__main__":
    main()
