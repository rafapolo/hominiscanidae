#!/usr/bin/env python3
"""
Fix slugified album metadata from posts/*.md + iTunes Search API fallback.

  python3 scripts/utils/fix_slugified_metadata.py           # dry run, show all changes
  python3 scripts/utils/fix_slugified_metadata.py --apply   # patch data/homi-albums.json.gz
  python3 scripts/utils/fix_slugified_metadata.py --apply --re-query   # ignore iTunes cache
  python3 scripts/utils/fix_slugified_metadata.py --limit 10           # test first 10
"""

import argparse
import gzip
import json
import re
import time
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

ROOT        = Path(__file__).resolve().parent.parent.parent
ALBUMS_GZ   = ROOT / "data" / "homi-albums.json.gz"
OVERRIDES   = ROOT / "data" / "itunes_overrides.json"
POSTS_DIR   = ROOT / "posts"
POSTS_JSON  = ROOT / "posts.json"

def _path_to_slug(path: str, year: int, slug_index: dict, year_slugs: dict) -> str | None:
    """Find the posts/* slug matching an album path using several fallback strategies."""
    raw = re.sub(r'^\d{4} - ', '', path)

    # 1. direct match
    if raw in slug_index:
        return raw

    # 2. normalise (lowercase, spaces/separator → single dash)
    norm_slug = re.sub(r'\s+-\s+|-\s+|\s+-', '-', raw).lower()
    norm_slug = re.sub(r'\s+', '-', norm_slug)
    norm_slug = re.sub(r'-+', '-', norm_slug).strip('-')
    if norm_slug in slug_index:
        return norm_slug

    # 3. normalised + year suffix
    norm_year = f"{norm_slug}-{year}"
    if norm_year in slug_index:
        return norm_year

    # 4. token-overlap fuzzy search restricted to the same year
    path_tokens = _tokens(raw.replace('-', ' '))
    if not path_tokens:
        return None
    best_slug, best_s = None, 0.0
    for slug in year_slugs.get(year, []):
        s = _overlap(path_tokens, slug.replace('-', ' '))
        if s > best_s:
            best_s, best_slug = s, slug
    if best_s >= 0.5:
        return best_slug

    return None

ITUNES_API  = "https://itunes.apple.com/search"
MIN_SCORE   = 0.45
RATE        = 0.35  # seconds between iTunes requests

STOP = {"a","as","o","os","e","de","do","da","dos","das","um","uma","em","no","na",
        "the","of","and","an","in","is","it","by","para","por","com"}

GENERIC = {"ep","lp","st","s/t","demo","split","single","compil","compilacao","coletanea"}


# ── helpers ──────────────────────────────────────────────────────────────────

def _clean(s: str) -> str:
    return re.sub(r'[​‌‍﻿]', '', s).strip()

def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9 ]+", " ", s.lower()).strip()

def _tokens(s: str) -> set:
    return {t for t in _norm(s).split() if t not in STOP and len(t) > 1}

def _overlap(query_tokens: set, candidate: str) -> float:
    if not query_tokens:
        return 0.0
    return len(query_tokens & _tokens(candidate)) / len(query_tokens)

def _is_slug(s: str) -> bool:
    return bool(re.search(r"[a-z]-[a-z]", s)) and " " not in s

def _is_generic(s: str) -> bool:
    return _norm(s).strip() in GENERIC or len(s.strip()) <= 2


# ── .md extraction ───────────────────────────────────────────────────────────

def _bc_artist_from_slug(bc_url: str, album_slug: str) -> str | None:
    """Derive artist name from Bandcamp URL by matching against album slug parts."""
    m = re.match(r'https?://([a-z0-9]+)\.bandcamp\.com(?:/album/([a-z0-9-]+))?', bc_url)
    if not m:
        return None
    subdomain = m.group(1)
    bc_album_path = m.group(2) or ""

    # Strip year prefix/suffix from album_slug
    slug = re.sub(r'(^(19|20)\d{2}-?|-?(19|20)\d{2}$)', '', album_slug).strip('-')
    # Split into parts, removing generic words
    GENERIC_PARTS = re.compile(r'^(ep\d*|lp\d*|demo|st|vol\d*)$')
    parts = [p for p in slug.split('-') if not GENERIC_PARTS.match(p)]
    if not parts:
        return None

    # 1. Try exact or startswith match on subdomain
    for i in range(len(parts), 0, -1):
        concat = ''.join(parts[:i]).lower()
        if subdomain == concat or subdomain.startswith(concat):
            return ' '.join(p.capitalize() for p in parts[:i])

    # 2. Try matching against /album/PATH slug (label Bandcamp pages)
    if bc_album_path:
        bc_parts = [p for p in bc_album_path.split('-') if not GENERIC_PARTS.match(p)]
        # Remove trailing year
        bc_parts = [p for p in bc_parts if not re.match(r'^(19|20)\d{2}$', p)]
        for i in range(len(bc_parts), 0, -1):
            # Find these bc_parts in the album slug parts
            if bc_parts[:i] == parts[:len(bc_parts[:i])]:
                return ' '.join(p.capitalize() for p in bc_parts[:i])

    return None


def extract_md(content: str, orig_artist: str = "", album_slug: str = "") -> tuple[str | None, str | None]:
    # Strip Unicode combining strikethrough and zero-width chars
    content = re.sub(r'[̶̵​‌‍﻿]', '', content)
    content = _clean(content)

    # ── album title from download link text ──────────────────────────────────
    title = None
    for pat in [
        r'Download[^:]*:\s*\*+\[([^\]]+)\]\(',               # **[Title.zip](url)
        r'Download[^:]*:\s*\[\s*[\*_]*([^\]\*_]+?)[\*_]*\s*\]\(', # [ **Title.zip** ](url)
        r'Download[^:]*:\s*\*\*([^\*\[\n]+?)\*\*(?!\[)',      # **Title.zip** (no link)
    ]:
        m = re.search(pat, content, re.IGNORECASE)
        if m:
            t = _clean(m.group(1))
            t = re.sub(r'\.(zip|rar|mp3|flac|7z|tar\.gz)$', '', t, flags=re.IGNORECASE)
            t = re.sub(r'\s*\(?\d{4}\)?\s*[.\s]*$', '', t).strip()
            if t:
                title = t
            break

    # ── artist: targeted search when original artist is a slug ───────────────
    artist = None
    artist_tokens = _tokens(orig_artist.replace("-", " ")) if orig_artist else set()

    if artist_tokens and _is_slug(orig_artist):
        for m in re.finditer(r'\*\*([^\*\[\n]{1,80})\*\*', content):
            c = _clean(m.group(1))
            if re.search(r'https?://|www\.', c) or '@' in c:
                continue
            if not (_tokens(c) & artist_tokens):
                continue
            # Take only the part before " - " (section headers like "W-Berg - Highland Village")
            artist = c.split(" - ")[0].strip()
            break

    # ── artist fallback: first bold proper name in description body ──────────
    if not artist:
        m = re.search(r'Download[^\n]*\n+(.*)', content, re.DOTALL | re.IGNORECASE)
        body = m.group(1) if m else content
        for m in re.finditer(r'\*\*([^\*\[\n]{2,50})\*\*', body):
            c = _clean(m.group(1))
            if re.search(r'https?://|www\.', c) or '@' in c:
                continue
            if len(c.split()) > 7:
                continue
            if re.search(r'[A-ZÁÉÍÓÚÀÂÊÔÃÕÇ]', c):
                artist = c
                break

    # ── artist fallback: Bandcamp subdomain matched against album slug ────────
    if not artist and album_slug:
        bc_m = re.search(r'(https?://[a-z0-9]+\.bandcamp\.com(?:/album/[a-z0-9-]+)?)', content)
        if bc_m:
            result = _bc_artist_from_slug(bc_m.group(1), album_slug)
            if result:
                artist = result

    # ── artist last resort: “Name é uma banda/artista/grupo” pattern ─────────
    if not artist:
        # Handles: “O Padre dos Balões é uma banda...” and unquoted variants
        m = re.search(
            r'[“””]?([A-ZÁÉÍÓÚÀÂÊÔÃÕÇ][^”””.\n]{2,55}?)\s+é\s+(?:uma?\s+)?(?:banda|artista|m[úu]sic|duo|trio|grupo|cantor)',
            content, re.IGNORECASE,
        )
        if m:
            candidate = _clean(m.group(1)).strip('””“” ')
            if len(candidate.split()) <= 8 and not re.search(r'https?://|www\.', candidate):
                artist = candidate

    return artist, title


# ── iTunes ────────────────────────────────────────────────────────────────────

def _itunes_search(term: str, country: str = "BR") -> list:
    params = urllib.parse.urlencode({
        "term": term, "entity": "album", "country": country, "limit": 5,
    })
    try:
        req = urllib.request.Request(
            f"{ITUNES_API}?{params}", headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read()).get("results", [])
    except Exception as e:
        print(f"  [itunes error] {e}")
        return []

def _best_itunes(query_tokens: set, results: list, min_score: float) -> tuple:
    best, best_s = None, 0.0
    for r in results:
        s = _overlap(query_tokens, f"{r.get('artistName','')} {r.get('collectionName','')}")
        if s > best_s:
            best_s, best = s, r
    return (best, best_s) if best_s >= min_score else (None, best_s)


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply",    action="store_true", help="Write fixes to homi-albums.json.gz")
    ap.add_argument("--re-query", action="store_true", help="Ignore cached iTunes results")
    ap.add_argument("--min-score", type=float, default=MIN_SCORE)
    ap.add_argument("--country",  default="BR")
    ap.add_argument("--limit",    type=int,   default=0, help="Process only first N (testing)")
    args = ap.parse_args()

    with gzip.open(ALBUMS_GZ) as f:
        data = json.load(f)
    albums = data["albums"]

    posts = json.load(POSTS_JSON.open())
    slug_to_post = {}
    year_slugs: dict[int, list[str]] = {}
    for p in posts:
        slug = p["url"].rstrip("/").split("/")[-1].replace(".html", "")
        slug_to_post[slug] = p
        m = re.search(r'/(\d{4})/', p["url"])
        if m:
            y = int(m.group(1))
            year_slugs.setdefault(y, []).append(slug)

    overrides: dict = json.loads(OVERRIDES.read_text()) if OVERRIDES.exists() else {}

    manual_paths = {path for path, ov in overrides.items() if ov.get("source") == "manual"}
    candidates = [a for a in albums
                  if _is_slug(a["title"]) or _is_slug(a["artist"]) or a["path"] in manual_paths]
    if args.limit:
        candidates = candidates[:args.limit]

    print(f"Processing {len(candidates)} slugified albums\n")

    stats = {"md": 0, "md+itunes": 0, "itunes": 0, "no_fix": 0, "queries": 0}

    for album in candidates:
        path   = album["path"]

        # Respect manually-set overrides — don't overwrite them
        if overrides.get(path, {}).get("source") == "manual":
            ov = overrides[path]
            stats["md"] += 1
            print(f"[manual    ] {path}")
            print(f"  fix: {ov['final_artist']!r} — {ov['final_title']!r}")
            print()
            continue

        slug   = _path_to_slug(path, album["year"], slug_to_post, year_slugs)

        # ── step 1: extract from posts/*.md ──────────────────────────────────
        md_artist, md_title = None, None
        md_file = POSTS_DIR / f"{slug}.md" if slug else None
        if md_file and md_file.exists():
            md_artist, md_title = extract_md(md_file.read_text(errors="replace"), album["artist"], slug or "")

        # Accept generic title (EP, Demo…) when original title is a slug — it's still an improvement
        title_ok  = bool(md_title) and (not _is_generic(md_title) or _is_slug(album["title"]))
        artist_ok = bool(md_artist) and not _is_slug(md_artist)

        # ── step 2: iTunes fallback when md is incomplete ────────────────────
        itunes_ov = overrides.get(path, {}).get("itunes") if path in overrides else None
        need_itunes = not (title_ok and artist_ok)

        if need_itunes and (itunes_ov is None or args.re_query):
            # Build query from whatever we have
            a_part = md_artist if artist_ok else album["artist"].replace("-", " ")
            t_part = md_title  if title_ok  else album["title"].replace("-", " ")
            query  = re.sub(rf'\b{album["year"]}\b', "", f"{a_part} {t_part}").strip()
            q_tok  = _tokens(query)

            results = _itunes_search(query, args.country)
            stats["queries"] += 1
            time.sleep(RATE)

            result, score = _best_itunes(q_tok, results, args.min_score)
            if result:
                itunes_ov = {
                    "title":    result["collectionName"],
                    "artist":   result["artistName"],
                    "year":     int(result.get("releaseDate", "0")[:4]) or album["year"],
                    "artwork":  result.get("artworkUrl100", "").replace("100x100bb", "600x600bb"),
                    "score":    round(score, 3),
                    "id":       result.get("collectionId"),
                }
            else:
                itunes_ov = {"no_match": True, "score": round(score, 3) if result else 0.0}

            overrides.setdefault(path, {})["itunes"] = itunes_ov

        # ── step 3: merge sources into final values ───────────────────────────
        final_title  = md_title  if title_ok  else None
        final_artist = md_artist if artist_ok else None
        source_parts = []

        if title_ok or artist_ok:
            source_parts.append("md")

        if (not final_title or not final_artist) and itunes_ov and not itunes_ov.get("no_match"):
            if not final_title:
                final_title  = itunes_ov["title"]
            if not final_artist:
                final_artist = itunes_ov["artist"]
            source_parts.append("itunes")

        # Save final in overrides (so --apply can use it without re-running)
        if final_title or final_artist:
            ov = overrides.setdefault(path, {})
            ov.pop("no_fix", None)   # clear stale flag from any previous partial run
            ov["final_title"]  = final_title  or album["title"]
            ov["final_artist"] = final_artist or album["artist"]
            ov["source"]       = "+".join(source_parts) if source_parts else "none"
            if itunes_ov and not itunes_ov.get("no_match"):
                ov["artwork"] = itunes_ov.get("artwork", "")

            key = ov["source"]
            stats[key if key in stats else "md+itunes"] += 1

            print(f"[{ov['source']:10}] {path}")
            print(f"  was:  {album['artist']!r} — {album['title']!r}")
            print(f"  fix:  {ov['final_artist']!r} — {ov['final_title']!r}")
            if itunes_ov and not itunes_ov.get("no_match"):
                print(f"  itunes score: {itunes_ov.get('score', '?')}")
            print()
        else:
            overrides.setdefault(path, {})["no_fix"] = True
            stats["no_fix"] += 1
            print(f"[no fix    ] {path}  (artist={album['artist']!r})")

    OVERRIDES.write_text(json.dumps(overrides, indent=2, ensure_ascii=False))
    print(f"\n{'─'*60}")
    print(f"from md:       {stats['md']}")
    print(f"md + itunes:   {stats['md+itunes']}")
    print(f"itunes only:   {stats['itunes']}")
    print(f"no fix:        {stats['no_fix']}")
    print(f"itunes queries: {stats['queries']}")
    print(f"overrides saved → {OVERRIDES}")

    if not args.apply:
        print("\ndry run — use --apply to update homi-albums.json.gz")
        return

    by_path = {a["path"]: i for i, a in enumerate(albums)}
    applied = 0
    for path, ov in overrides.items():
        if "final_title" not in ov:
            continue
        if path not in by_path:
            continue
        idx = by_path[path]
        albums[idx]["title"]  = ov["final_title"]
        albums[idx]["artist"] = ov["final_artist"]
        if ov.get("artwork"):
            albums[idx]["artwork"] = ov["artwork"]
        applied += 1

    data["albums"] = albums
    with gzip.open(ALBUMS_GZ, "wt", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print(f"\napplied {applied} fixes → {ALBUMS_GZ}")


if __name__ == "__main__":
    main()
