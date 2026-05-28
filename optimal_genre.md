# Genre extraction: discogs519

## The pipeline

```
MonoLoader → TensorflowPredictMAEST → genre_discogs519 classifier
```

Processes each track of every album in `unzips/` through the MAEST model, producing top-5 Discogs genre predictions per track.

## Model used

- Feature extractor: `discogs-maest-30s-pw-519l-1.pb` (351 MB)
- Classifier head: `genre_discogs519-discogs-maest-30s-pw-519l-1.pb` (1.6 MB)
- Outputs: 519 Discogs style labels

## Problems fixed

### 1. Invalid GraphDef

The standalone tocador repo (`/Users/polux/Projetos/tocador/script/models/`) had a corrupted MAEST model — 65 MB instead of the correct 351 MB. Happened because the model URL redirects to an ONNX file on newer downloads. Fixed by copying the good model from the submodule (`hominiscanidae/tocador/script/models/`).

### 2. MonoLoader hangs on corrupted MP3s

Some MP3 files cause Essentia's `MonoLoader` to hang indefinitely inside FFmpeg's swresample library. The original script used `threading.Thread.join(timeout)` which cannot interrupt C-level deadlocks — Python signal handlers are deferred until the C call returns, which never happens.

Fixed with `multiprocessing.Process.terminate()` — launches audio loading in a child process, hard-kills it after 15s timeout. `mp.Queue` is read before `Process.join()` to avoid the classic pickle/pipe deadlock.

## Script location

`/Users/polux/Projetos/tocador/script/extract-genres.py`

## How to run (M4, resumeable)

```bash
ARCHIVE_DIR=/Volumes/EXTRA/hominiscanidae/unzips \
OUTPUT_FILE=/Users/polux/Projetos/hominiscanidae/genres.json \
nohup python3 -u /Users/polux/Projetos/tocador/script/extract-genres.py \
  --model discogs519 \
  > extract-genres.log 2>&1 &
```

Workers default to `cpu_count - 2` (capped at 5). On M4 (10 cores) this gives **8 workers**... actually capped to 5. To override:

```bash
# explicit worker count:
  --workers 4    # conservative (safe with 16 GB RAM)
  --workers 5    # max safe (5 × ~450 MB ≈ 2.2 GB model RAM)
  --workers 1    # single-process (debug / low-heat)
```

| Env var | Purpose |
|---------|---------|
| `ARCHIVE_DIR` | Where `unzips/` lives (with album dirs) |
| `OUTPUT_FILE` | JSON output, read once at start to resume |

## Resume behavior

On restart the script reads `genres.json` once, skips any album already present in it, and continues from where it left off. Progress is saved atomically after each album (tmp file → rename), so a crash never corrupts the output.

## Test a single album

```bash
ARCHIVE_DIR=/Volumes/EXTRA/hominiscanidae/unzips \
python3 /Users/polux/Projetos/tocador/script/extract-genres.py \
  --model discogs519 \
  --albums "1963 - Jorge Ben Jor - Samba Esquema Novo"
```

## Monitor progress

```bash
tail -f extract-genres.log
python3 -c "import json; d=json.load(open('genres.json')); print(f'{len(d)} albums done')"
```

Log lines include rate and ETA, e.g.:
```
[120/6686] 2019 - Dirimbó - Tempo Covarde
  → 7 tracks  Latin---MPB  [8.1/min | ETA 13h22m]
```

## Current status (2026-05-27)

| Metric | Value |
|--------|-------|
| Total albums | 6,951 |
| Already done | ~48 |
| Remaining | ~6,640 |
| Speed (single) | ~2 albums/min |
| Speed (4 workers, M4) | ~8 albums/min |
| ETA (4 workers) | ~14 h |

## Optimization notes

### Worker count on M4

The M4 has 10 cores and 16 GB RAM. Each worker loads ~450 MB (MAEST model + audio buffers). Safe ceiling:

| Workers | Model RAM | Wall ETA |
|---------|-----------|----------|
| 1       | 0.45 GB   | ~56 h    |
| 3       | 1.35 GB   | ~19 h    |
| 4       | 1.8 GB    | ~14 h    |
| 5       | 2.2 GB    | ~11 h    |

Default auto-selection: `min(cpu_count - 2, 5)` = **5** on M4.

### Why not more workers?

6 workers caused `BrokenProcessPool` in earlier testing (likely OOM with model × 6 + concurrent audio subprocess spawns). 5 workers leaves room for the OS + audio subprocesses.

### Pre-scan corrupted files (optional speedup)

Files that cause the 15s MonoLoader timeout can be pre-identified with `ffprobe` to skip them instantly:

```bash
ffprobe -v quiet -print_format json -show_format "$mp3"
```

Files causing "swresample context" errors are identifiable and can be pre-skipped or re-encoded before the main run.
