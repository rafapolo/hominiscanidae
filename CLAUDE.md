# hominiscanidae archive

Full archival of hominiscanidae.org — a Brazilian independent music blog with ~10,583 posts. Files downloaded to `/Volumes/EXTRA/hominiscanidae/`.

## Key files

- `posts.json` — master index: every post with `url`, `title`, `download`, `status`, `downloaded_as`, `file_size`
- `posts/<slug>.md` — local HTML→markdown cache of each post body (used offline for link extraction)
- `download_all.py` — main downloader (multi-service dispatch, 16 workers)
- `scrape_posts.py` — scraper: builds/updates posts.json and posts/*.md
- `script/generate-albums/` — Rust binary that scans `unzips/` and writes `js/homi-albums.json` + `js/homi-albums.json.gz`

## Generating album metadata

```bash
cd script/generate-albums
cargo build --release
./target/release/generate-albums          # writes js/homi-albums.json + .json.gz
./target/release/generate-albums /path/to/out.json  # custom output path
```

Reads ID3 tags with the `id3` crate (parallel via rayon). Outputs both plain JSON and gzipped JSON.

## Sitemap

```
https://www.hominiscanidae.org/sitemap.xml
```

Re-scan periodically to pick up new posts:

```bash
python3 scrape_posts.py --sitemap
```

## Re-scraping a label (series)

Works **offline from local posts/**: finds matching posts by slug keywords and .md content, then re-fetches only those with missing/empty .md files.

```bash
python3 scrape_posts.py --label "https://www.hominiscanidae.org/search/label/Esquema%20Ap%C3%AA"
```

Matching logic (no network needed):
1. All label keywords found in the post slug
2. Label URL or name appears in the .md content

Note: cannot discover posts not yet in posts.json — use `--sitemap` for that.

## Downloading

```bash
# Skip mega (when quota exhausted):
python3 -u download_all.py > /dev/null 2>&1 &

# Re-enable mega: remove the "return skip-mega" line in the dispatcher (~line 517)
```

## Status lifecycle

`not_downloaded` → `downloaded` / `dead_link` / `blocked` / `failed`

- `failed` resets to `not_downloaded` on each restart (retry)
- `blocked` = EBLOCKED mega (DMCA) — permanent, skip
- `dead_link` = permanent, skip

## Periodic maintenance checklist

1. `python3 scrape_posts.py --sitemap` — pick up new posts
2. Check for empty `.md` files: `find posts/ -empty` — re-run scraper for those
3. Re-enable mega after ~6h quota reset and restart downloader
4. Posts with `status=null` and `download=null` are editorial (playlists, lists) — no file to download

## Current state (2026-05-22)

- Total posts: 10,583 | With download link: ~10,526
- Downloaded: ~4,687 (44.8%) | 283.93 GB
- Dead: ~4,375 | Blocked (EBLOCKED mega): 228
- Mega quota resets ~6h after last use
