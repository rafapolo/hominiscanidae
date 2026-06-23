# Workflow: Add New Albums from hominiscanidae.org

Full pipeline to scrape new posts, download, extract, cover, sync and publish.

## 1 — Scrape new posts

```bash
cd /Users/polux/Projetos/hominiscanidae
python3 scripts/scrape/scrape_posts.py --sitemap
```

Adds new posts to `posts.json` and fetches their `.md` files. Null-status posts
with a download link are automatically set to `not_downloaded` on next downloader start.

## 2 — Download

```bash
# Background (default — Mega proxy escalation enabled):
nohup python3 -u scripts/download/download_all.py > /tmp/homi-download.log 2>&1 &

# Skip Mega (when quota exhausted):
# comment out the mega dispatcher block in download_all.py (~line 517)

# Monitor:
tail -f /tmp/homi-download.log
```

Archives land in `/Volumes/EXTRA/hominiscanidae/` as `.rar`/`.zip`/`.mp3`.

## 3 — Extract archives

```bash
python3 scripts/utils/unzip.py
# re-extract all:  python3 scripts/utils/unzip.py --force
```

Uses `unar` (not `unrar`) — auto-detects CP850/Latin-1 for PT-BR filenames.
Extracts to `/Volumes/EXTRA/hominiscanidae/unzips/`.

Google Drive folder posts require manual `gdown`:
```bash
gdown --folder "https://drive.google.com/drive/folders/FOLDER_ID" \
  -O /Volumes/EXTRA/hominiscanidae/unzips/nome-do-album
```

## 4 — Fetch missing covers from blog

```bash
# From Blogger CDN / Bandcamp / bcbits URLs in .md posts:
python3 scripts/covers/fetch_covers2.py

# For HC# compilation ghost albums (Bandcamp known URLs):
python3 scripts/covers/fetch_hc_ghost_covers.py
```

Saves `cover.jpg` locally inside each album folder.

## 5 — Resize cover.jpg → capa-min.jpg

Run this Python snippet (no extra deps, uses ffmpeg):

```bash
python3 - <<'EOF'
import os, subprocess
from pathlib import Path

UNZIPS = Path('/Volumes/EXTRA/hominiscanidae/unzips')
COVER_NAMES = ('cover','capa','folder','front','artwork','albumart')
IMAGE_EXTS  = ('.jpg','.jpeg','.png','.webp')

resized = errors = 0
for folder in sorted(UNZIPS.iterdir()):
    if not folder.is_dir(): continue
    capa_min = folder / 'capa-min.jpg'
    if capa_min.exists(): continue
    src = next(
        (f for f in folder.iterdir()
         if f.is_file()
         and f.suffix.lower() in IMAGE_EXTS
         and any(f.stem.lower().startswith(p) for p in COVER_NAMES)),
        None
    )
    if not src: continue
    r = subprocess.run(
        ['ffmpeg','-y','-i',str(src),'-vf','scale=200:-1','-q:v','4',str(capa_min)],
        capture_output=True
    )
    if r.returncode == 0 and capa_min.stat().st_size > 500:
        resized += 1
    else:
        errors += 1; print(f'FAIL: {folder.name}')
print(f'Resized: {resized}  errors: {errors}')
EOF
```

## 6 — Upload covers to S3

```bash
cd /Users/polux/Projetos/tocador
node script/sync-covers-homi.js
```

Uploads all `capa-min.jpg` files not yet on S3 (`indie/` bucket prefix).

## 7 — Upload audio to S3

```bash
cd /Users/polux/Projetos/tocador
export $(grep -v '^#' /Users/polux/Projetos/hominiscanidae/.env | xargs)
ARCHIVE_DIR=/Volumes/EXTRA/hominiscanidae/unzips S3_PREFIX=indie/ \
  node script/sync-to-bucket.js > /tmp/homi-s3-sync.log 2>&1 &

tail -f /tmp/homi-s3-sync.log
```

Skips files already on S3 (size-based diff), 20 concurrent workers.

## 8 — Regenerate acervo JSON

```bash
cd /Users/polux/Projetos/tocador/script/generate-albums
cargo build --release   # only needed after Rust source changes

./target/release/generate-albums \
  /Volumes/EXTRA/hominiscanidae/unzips \
  /Users/polux/Projetos/hominiscanidae/data/homi-albums.json.gz \
  --sitemap-out /Users/polux/Projetos/hominiscanidae/sitemap.xml \
  --sitemap-url "https://tocador.cc"
```

## 9 — Rebuild genre index

```bash
cd /Users/polux/Projetos/tocador
bun script/build-genre-index.js
```

Reads `../hominiscanidae/data/genres.json`, writes `homi-genres.json.gz`.

## 10 — Commit and push hominiscanidae

```bash
cd /Users/polux/Projetos/hominiscanidae
git add data/homi-albums.json.gz data/homi-genres.json.gz \
        posts.json sitemap.xml sitemap-albums.xml sitemap-artists.xml
git commit -m "chore: regenerate homi json+sitemap — NNN albums"
git push origin main
```

## 11 — Rebuild 3D cover atlas

Must run **after** pushing the JSON to GitHub (atlas fetches from raw.githubusercontent.com).

```bash
cd /Users/polux/Projetos/tocador
node script/build-3d-atlas.js --acervo=homi
```

Packs 64×64 tiles into 4096×4096 WebP sheets, uploads to `indie/3d-atlas/` on S3.

---

## Fix a single missing cover

If one album shows no cover in the player (`?album=Artist+-+Title+%28YEAR%29`):

```bash
# 1. Find the cover locally (usually cover.jpg)
ls "/Volumes/EXTRA/hominiscanidae/unzips/Artist - Title (YEAR)/"

# 2. Resize and upload
ffmpeg -y -i cover.jpg -vf scale=200:-1 -q:v 4 capa-min.jpg
export $(grep -v '^#' /Users/polux/Projetos/hominiscanidae/.env | xargs)
aws s3 cp capa-min.jpg "s3://indie/Artist - Title (YEAR)/capa-min.jpg" \
  --endpoint-url https://hel1.your-objectstorage.com --region hel1
```

No JSON regeneration needed — the player reads `has_cover` from JSON but loads
`capa-min.jpg` from S3 regardless. The fix is live immediately.

---

## Periodic maintenance checklist

1. `python3 scripts/scrape/scrape_posts.py --sitemap` — pick up new posts
2. `find posts/ -empty` — re-scrape posts with empty .md files
3. Run downloader; re-enable Mega after ~6h quota reset
4. After extraction: resize covers → sync covers → sync audio
5. Regenerate JSON → push → rebuild 3D atlas
6. `python3 scripts/utils/clean_s3.py` — audit S3 for orphans (dry run first)
