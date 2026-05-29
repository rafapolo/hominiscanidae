# hominiscanidae archive

Full archival of hominiscanidae.org — a Brazilian independent music blog with ~10,583 posts. Files downloaded to `/Volumes/EXTRA/hominiscanidae/`.

## Key files

- `posts.json` — master index: every post with `url`, `title`, `download`, `status`, `downloaded_as`, `file_size`
- `posts/<slug>.md` — local HTML→markdown cache of each post body (used offline for link extraction)
- `scripts/download/download_all.py` — main downloader (multi-service dispatch, 16 workers)
- `scripts/scrape/scrape_posts.py` — scraper: builds/updates posts.json and posts/*.md
- `tocador/script/generate-albums/` — Rust binary that scans `unzips/` and writes `js/homi-albums.json` + `js/homi-albums.json.gz`

## Generating album metadata

The binary lives in the **parent tocador repo** (`/Users/polux/Projetos/tocador/script/generate-albums/`). The submodule at `tocador/script/generate-albums/` is a mirror — changes must be committed in both.

```bash
cd /Users/polux/Projetos/tocador/script/generate-albums
cargo build --release
./target/release/generate-albums /Volumes/EXTRA/hominiscanidae/unzips \
  /Users/polux/Projetos/hominiscanidae/js/homi-albums.json.gz \
  --title "Hominiscanidae" \
  --subtitle "Música Independente Brasileira" \
  --base-url "https://cdn.tocador.cc/indie" \
  --sitemap-url "https://tocador.cc"
```

`--sitemap-url` triggers automatic `sitemap.xml` generation alongside the `.json.gz`. URLs use `?album=...&artist=...` query params (form-encoded, spaces as `+`), `<lastmod>` = today, priority by decade.

Reads ID3 tags with the `id3` crate (parallel via rayon). Only `.json.gz` matters — the player loads it via GitHub raw URL. The `js/homi-albums.json` plain file is a legacy artifact with a different schema; ignore it.

## Sitemap

```
https://www.hominiscanidae.org/sitemap.xml
```

Re-scan periodically to pick up new posts:

```bash
python3 scripts/scrape/scrape_posts.py --sitemap
```

## Re-scraping a label (series)

Works **offline from local posts/**: finds matching posts by slug keywords and .md content, then re-fetches only those with missing/empty .md files.

```bash
python3 scripts/scrape/scrape_posts.py --label "https://www.hominiscanidae.org/search/label/Esquema%20Ap%C3%AA"
```

Matching logic (no network needed):
1. All label keywords found in the post slug
2. Label URL or name appears in the .md content

Note: cannot discover posts not yet in posts.json — use `--sitemap` for that.

## Downloading

```bash
# Skip mega (when quota exhausted):
python3 -u scripts/download/download_all.py > /dev/null 2>&1 &

# Re-enable mega: remove the "return skip-mega" line in the dispatcher (~line 517)
```

## Extracting archives

**Always use `unar`** — `unrar` and macOS Archive Utility silently drop files whose names use PT-BR characters (ã, ô, ç, etc.) encoded as Latin-1/CP850 inside RAR files. `unar` auto-detects charset and extracts all tracks correctly.

```bash
python3 scripts/utils/unzip.py          # extract all archives in DEST → unzips/
python3 scripts/utils/unzip.py --force  # re-extract even if folder exists
```

## Fixing charset gaps in existing albums

1,805 albums in `unzips/` had missing tracks due to PT-BR charset. The fix:

```bash
# Re-download and re-extract with unar; copies missing tracks to unzips/ and uploads to S3
python3 scripts/download/refix_charset.py --tor

# Track progress
tail -f refix_charset.log

# Status CSV (regenerate anytime)
# unzips/to_fix/to_fix.csv — title, download_url, status for all 1805 gap albums
```

## Status lifecycle

`not_downloaded` → `downloaded` / `dead_link` / `blocked` / `failed`

- `failed` resets to `not_downloaded` on each restart (retry)
- `blocked` = EBLOCKED mega (DMCA) — permanent, skip
- `dead_link` = permanent, skip

## Periodic maintenance checklist

1. `python3 scripts/scrape/scrape_posts.py --sitemap` — pick up new posts
2. Check for empty `.md` files: `find posts/ -empty` — re-run scraper for those
3. Re-enable mega after ~6h quota reset and restart downloader
4. Posts with `status=null` and `download=null` are editorial (playlists, lists) — no file to download
5. After any change to `unzips/`, regenerate `js/homi-albums.json.gz` (command above)

## Albums with 1 track

Not a bug. Many blog posts linked a single MP3 (not a ZIP with tracks). These appear in the player with 1 faixa — that's all there is on disk.

## Current state (2026-05-29)

- Total posts: 10,583 | With download link: ~10,526
- Downloaded: ~6,937 | Dead: ~3,646 | Blocked (EBLOCKED mega): 228
- Published to S3 + player: **6,909 álbuns**, noyear = 0
- Mega quota resets ~6h after last use
