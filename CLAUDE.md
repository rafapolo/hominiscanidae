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

## Bandcamp: never assume a `/download?` token is expired

`dl_bandcamp` used to short-circuit any `bandcamp.com/download?` URL to
`dead:expired-token` **without making the request**. Most of those tokens are still live —
the page returns 200 with a `data-blob` offering `mp3-320`. Every one of them was instead
routed to the `dl_ytdlp` fallback.

That fallback then compounded the damage. `--no-playlist` does **not** protect an album URL:
Bandcamp's is a playlist extractor, so the flag is a no-op. With `-o "<slug>.%(ext)s"` all
tracks resumed into one file, appending each track's raw bytes behind the first track's MP4
container. `ffprobe` sees only what the `moov` atom describes — track 1 — so `flac_to_mp3.py`
transcoded 2:37 out of an 88-minute album and then **deleted the source**.

The tell is a folder with 1 track whose `posts.json` `file_size` is several times the mp3 on
disk. Reproduced byte-for-byte: a 27,836,491-byte `.m4a` holding 1 `moov`/`mdat` plus ID3
headers and 262 MPEG frame syncs after it. **13 albums** lost this way, all recovered:

```bash
python3 scripts/download/refix_bandcamp_albums.py --list     # show damaged albums
python3 scripts/download/refix_bandcamp_albums.py            # re-fetch and swap in
```

`dl_ytdlp` now writes `%(playlist_index|0)02d - %(title)s.%(ext)s` into a per-slug folder and
returns that folder when a playlist yields more than one track. `unzip.py`'s `fold_dirs()`
moves such folders from `DEST` root into `unzips/<post title>/` — without it they would be
as invisible as the loose singles above.

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

Usually not a bug: many posts linked a single MP3 rather than a ZIP, and 1 faixa is all
there is on disk. But audit them before believing that — 17 of 96 were a bug.

`generate-albums` drops a **slug-tail** (a kebab-case `artist-album-year.mp3`) whenever the
other files in the folder carry track numbers, assuming it is the same music arriving twice.
Beside a *properly extracted album* that holds. Beside a **single** numbered track it does
not: that pairing comes from a rescue that recovered one track, so the slug file is a
different recording, and dropping it deletes the only copy from the catalog. Eleven albums
were hiding a second recording that way, including whole releases masked by one stray
compilation track (`evan-heinrich-garden-of-scars`: 3:04 indexed, 47:04 dropped).

The Rust side now requires **two or more** numbered tracks before it hides a slug-tail.
Disk-level cleanup is a separate tool, because duration cannot tell a duplicate from a
different song — a YouTube rescue of the same track routinely differs by 3-10s, and two
different songs routinely match. Chromaprint can:

```bash
python3 scripts/utils/slug_tails.py --scan --only-index  # audit the 1-track albums
python3 scripts/utils/slug_tails.py --scan               # audit all of unzips/
python3 scripts/utils/slug_tails.py --apply              # trash dups, split misfiled
```

Redundant files go to `DEST/.slug-tail-trash`, never `unlink` — purge by hand after the
rebuilt index looks right. Verdicts separate cleanly: duplicates score BER ≤ 0.04,
different recordings ≥ 0.25.

Archive-wide sweep done (2026-08-03): of 1,538 slug-tail folders, **1,171 were redundant**
(963 duplicate a sibling track, 208 are the whole album in one file) and went to the trash
folder — 13 GB. Three files had been misfiled from a *different* post and were the only copy
of that release; they now have their own folders. The remaining **364 stay in place**: each
is its own post's fallback download sitting beside that post's real album, so there is no
second album to move it to and no reliable way to tell a bad YouTube match from a genuine
bonus track. `generate-albums` already hides them, and trashing them would risk audio for
no catalog gain.

Two traps when relocating, both hit during that sweep:

- **Never compare folder names by stripping non-alphanumerics.** That deletes accents rather
  than folding them, so "Máquina" becomes `mquina` and stops matching `maquina`. Twenty-eight
  relocations were about to mint near-duplicate folders. `_tokens()` NFD-folds and drops
  PT-BR articles; `same_album()` compares token sets.
- **The slug-tail is whichever file sorts last, and the Rust uses a natural sort.** A plain
  byte sort disagrees (`churrus-….mp3` vs `NA. Churrus - ….mp3`, lowercase outranks
  uppercase) and picks a file the indexer never drops. `natural_cmp()` mirrors the Rust.

### Completing singles that are really albums

```bash
python3 scripts/download/complete_singles.py --dry-run
python3 scripts/download/complete_singles.py
```

Finds 1-track folders whose post still points at a Bandcamp album with more tracks. Yield is
low — 1 of 79 — because the artist pages are mostly gone a decade later and the rest are
genuine singles. It confirms an artist-page match against the album's *real* title before
downloading; a wrong match would bury the single under someone else's record.

## Current state (2026-08-03)

- Total posts: 10,704 | With download link: ~10,633
- Downloaded: 7,496 | Dead: 2,931 | Blocked (EBLOCKED mega): 228
- Published to S3 + player: **6,652 álbuns**, 0 empty, noyear = 55
- Albums showing 1 faixa: **77** (was 96 — see "Albums with 1 track")
- Mega quota resets ~6h after last use
- `DEST/.slug-tail-trash` holds 1,181 files / 13 GB pending a manual purge

The album count fell from 6,909 because 499 duplicate `<Album>-N` folders were collapsed
(32 GB reclaimed) — same music, previously indexed 2–5× over. Offsetting that, 76 stranded
single-file downloads and 14 m4a-only albums were recovered into the index.

7 Dropbox RAR5 archives carry genuine CRC damage at the source; they extract with `unrar`
but 14 tracks across them are unrecoverable and were dropped.
