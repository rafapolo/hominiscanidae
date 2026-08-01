# hominiscanidae archive

Full archival of hominiscanidae.org — a Brazilian independent music blog with ~10,583 posts. Files downloaded to `/Volumes/EXTRA/hominiscanidae/`.

## Key files

- `posts.json` — master index: every post with `url`, `title`, `download`, `status`, `downloaded_as`, `file_size`
- `posts/<slug>.md` — local HTML→markdown cache of each post body (used offline for link extraction)
- `scripts/download/download_all.py` — main downloader (multi-service dispatch, 16 workers)
- `scripts/scrape/scrape_posts.py` — scraper: builds/updates posts.json and posts/*.md
- `tocador/script/generate-albums/` — Rust binary that scans `unzips/` and writes `data/homi-albums.json.gz`

## Generating album metadata

The binary lives in the **parent tocador repo** (`/Users/polux/Projetos/tocador/script/generate-albums/`). The submodule at `tocador/script/generate-albums/` is a mirror — changes must be committed in both.

```bash
cd /Users/polux/Projetos/tocador/script/generate-albums
cargo build --release
./target/release/generate-albums /Volumes/EXTRA/hominiscanidae/unzips \
  /Users/polux/Projetos/hominiscanidae/data/homi-albums.json.gz \
  --title "Hominiscanidae" \
  --subtitle "Música Independente Brasileira" \
  --base-url "https://cdn.tocador.cc/indie" \
  --sitemap-url "https://tocador.cc"
```

`--sitemap-url` triggers automatic `sitemap.xml` generation alongside the `.json.gz`. URLs use `?album=...&artist=...` query params (form-encoded, spaces as `+`), `<lastmod>` = today, priority by decade.

Reads ID3 tags with the `id3` crate (parallel via rayon). Only `.json.gz` matters — the player loads it via GitHub raw URL. The `data/homi-albums.json` plain file is a legacy artifact with a different schema; ignore it.

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

```bash
python3 scripts/utils/unzip.py            # extract archives in DEST → unzips/, then folder singles
python3 scripts/utils/unzip.py --dry-run  # show what would happen, touch nothing
python3 scripts/utils/unzip.py --force    # re-extract even if folder exists
python3 scripts/utils/unzip.py --singles  # only folder loose audio files
```

**`unar` is the primary extractor** — plain `unrar` and macOS Archive Utility silently
drop files whose names use PT-BR characters (ã, ô, ç) encoded as Latin-1/CP850 inside
**RAR4** archives. `unar` auto-detects charset and gets all tracks.

**`unrar` is the fallback for RAR5.** `unar` 1.10.7 cannot decode some RAR5 compression
methods ("Error on decrunching"); p7zip and 7zz fail them too. RARLAB `unrar` is the only
thing that reads them. RAR5 stores names as UTF-8, so the charset caveat above does not
apply on that path. `unzip.py` tries `unar` first and falls back automatically.
See "Fixing rar/unrar on macOS" below — the binaries do not work out of the box.

Partially-decoded members are kept with `-kb` and then any 0-byte file is deleted, so a
CRC-damaged track disappears instead of showing up in the player as a dead 0-second entry.

### Extraction state — do not "detect" it by name

Extraction is tracked in `DEST/.extract-state.json`, keyed by archive filename.

The old code inferred it by checking whether any folder in `unzips/` contained the first
20 chars of the archive stem. That never matches: the stem is a hyphenated-lowercase slug
(`torres-de-mello-ventvr`) and the folder is the real album title
(`Torres de Mello - VENTVRIS VENTIS (2025)`). The check fired 3 times out of 124, so every
run re-extracted everything and `unar` auto-renamed the collisions to `-1`, `-2`, `-3`…
That silently accumulated **378 duplicate album folders / 24.6 GB**, and each duplicate was
indexed as its own album. If album counts jump inexplicably, look for `<Album>-N` folders.

### Single-file downloads

Many posts link a bare `.mp3` rather than an archive. Those land in `DEST` root and, with no
folder, `generate-albums` never sees them — they are downloaded and then invisible forever.
`unzip.py` folders them into `unzips/<post title>/`, taking the title from `posts.json`
(keyed on both `downloaded_as` and its stem, so `foo.mp3` and `foo.m4a` share one folder).
This had stranded **76 files**.

## Everything must be MP3

`generate-albums` reads ID3 tags with the Rust `id3` crate and `sync-to-bucket.js` skips any
extension outside its `ALLOWED_EXTS`. Anything else is stored on disk and then silently
dropped — no error, just a missing album. 14 m4a-only albums were lost this way.

```bash
python3 scripts/utils/flac_to_mp3.py   # converts every non-MP3 audio file; unzip.py calls it
```

Covers `.flac .wav .wma .m4a .aac .ogg .opus .alac .aiff .mp4 .webm`. When a new download
source can yield another container, add the extension to `SOURCE_EXTS` there — do not
special-case it downstream.

## Fixing rar/unrar on macOS

Homebrew's `rar` cask installs unsigned RARLAB binaries carrying `com.apple.quarantine`.
macOS SIGKILLs `rar` on launch (exit 137/144, **zero output**) and XProtect *deletes*
`unrar` outright — a dangling `/opt/homebrew/bin/unrar` symlink is the tell.

```bash
cd /opt/homebrew/Caskroom/rar/*/rar
xattr -c rar unrar
codesign --force --sign - rar unrar
```

If `unrar` is already gone, restore it from the Homebrew cache first — `brew reinstall
--cask rar` just gets it deleted again:

```bash
tar xzf ~/Library/Caches/Homebrew/downloads/*rarmacos-arm*.tar.gz --strip-components=1 rar/unrar
```

## Google Drive folders

Some posts link to a Google Drive *folder* (not a direct file). `download_all.py` cannot handle these — use `gdown`:

```bash
gdown --folder "https://drive.google.com/drive/folders/FOLDER_ID" \
  -O /Volumes/EXTRA/hominiscanidae/unzips/nome-do-album
```

The folder may contain WAV or FLAC files. Convert to MP3 after:

```bash
python3 scripts/utils/flac_to_mp3.py   # converts .flac and .wav in DEST + unzips/
```

Then mark the post as `downloaded` in `posts.json` and re-run `generate-albums`.

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

Full ETL, in order — each step feeds the next:

1. `python3 scripts/scrape/scrape_posts.py --sitemap` — pick up new posts
2. `python3 -u scripts/download/download_all.py` — fetch pending downloads
3. `python3 scripts/utils/unzip.py` — extract + folder singles + convert to MP3
4. `node script/resize-cover-images.js homi` *(in tocador)* — covers → S3
5. `ARCHIVE_DIR=/Volumes/EXTRA/hominiscanidae/unzips node script/sync-to-bucket.js` *(in tocador)* — audio → S3
6. `generate-albums <unzips> data/homi-albums.json.gz --sitemap-out sitemap.xml` — index
7. `bun script/build-genre-index.js` *(in tocador)* — genre index
8. Commit `posts.json`, `data/*.json.gz`, `data/sitemap*.xml`

**Sync to S3 before regenerating the index**, not after: publishing an index whose
tracks are not in the bucket yet just yields 404s in the player.

Other notes:

- Check for empty `.md` files: `find posts/ -empty` — re-run scraper for those
- Re-enable mega after ~6h quota reset and restart downloader
- Posts with `status=null` and `download=null` are editorial (playlists, lists) — no file to download
- **Verify `/Volumes/EXTRA` is mounted before step 2.** `download_all.py` does
  `DEST.mkdir(parents=True, exist_ok=True)`, so with the drive absent it silently creates
  the tree on the boot disk, downloads there, and step 6 then regenerates the index from a
  near-empty `unzips/` — wiping the catalog.
- Before any bulk S3 upload, confirm the diff is small. A credentials or prefix problem
  makes the bucket listing come back empty and the sync will happily re-upload ~400 GB.

## Albums with 1 track

Not a bug. Many blog posts linked a single MP3 (not a ZIP with tracks). These appear in the player with 1 faixa — that's all there is on disk.

## Current state (2026-08-01)

- Total posts: 10,704 | With download link: ~10,633
- Downloaded: 7,496 | Dead: 2,931 | Blocked (EBLOCKED mega): 228
- Published to S3 + player: **6,649 álbuns**, 0 empty, noyear = 56
- Mega quota resets ~6h after last use

The album count fell from 6,909 because 499 duplicate `<Album>-N` folders were collapsed
(32 GB reclaimed) — same music, previously indexed 2–5× over. Offsetting that, 76 stranded
single-file downloads and 14 m4a-only albums were recovered into the index.

7 Dropbox RAR5 archives carry genuine CRC damage at the source; they extract with `unrar`
but 14 tracks across them are unrecoverable and were dropped.
