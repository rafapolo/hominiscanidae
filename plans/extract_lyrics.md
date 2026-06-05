# Extract Lyrics — Whisper Large-v3 Transcription Pipeline

Transcribe every MP3 in the acervo to extract lyrics and language metadata.
**Target: full corpus** (all 45,419 tracks → complete `lyrics.json`).

## Script

`scripts/transcribe/transcribe_lyrics.py`

## Output format

`lyrics.json` — keyed by S3 object key:

```json
{
  "indie/2020 - Teto das Nuvens - Caso Você Esteja Errado/08 Caso Você Esteja Errado.mp3": {
    "language": {"pt": 0.9825, "en": 0.0067},
    "lyrics": "Ansiedade nos olhos, um vazio sem sentido...",
    "duration": 175.8,
    "duration_after_vad": 0.0,
    "no_speech_prob": 0.097,
    "segments": 34
  }
}
```

| Field | Source | Notes |
|---|---|---|
| `language` | `info.all_language_probs` | Top-2 guesses with probability |
| `lyrics` | segment texts joined | Full decoded text |
| `duration` | `info.duration` | Audio length from model (more reliable than ID3) |
| `duration_after_vad` | `info.duration_after_vad` | Length after VAD trim (0 when VAD off) |
| `no_speech_prob` | segment avg | Near 1.0 = instrumental, near 0.0 = vocals |
| `segments` | count | Number of speech segments |

## Model

**faster-whisper** (CTranslate2) with `large-v3` weights. Same accuracy as openai-whisper, ~4× faster on CPU via int8 quantization. `num_workers=N` loads N independent replicas — concurrent `transcribe()` from N threads is officially supported and thread-safe.

## Source modes

S3 is the **authoritative file list** — it holds the complete corpus including files no longer on local disk.

| Mode | Flag | Source list | File reads |
|---|---|---|---|
| S3 (default) | — | `mc find` on S3 | every file downloaded |
| Hybrid | `--local-dir PATH` | `mc find` on S3 | local if file exists on disk, S3 download otherwise |
| Local only | `--local-dir PATH --local-only` | `rglob("*.mp3")` | local only, no S3 needed |

**Hybrid mode is recommended for Mac**: avoids re-downloading files that are still in `unzips/`, fetches the rest from S3. Files that were deleted locally after upload are transparently pulled from S3.

## Architecture

```
S3 bucket ──── mc find ──────────────────────── s3_candidates [(s3_key, s3_full), ...]
                                                        │
                               resolve_sources()        │  check local_dir for each key
                                                        ▼
                              pending [(s3_key, source), ...]
                              source = Path  → local file (no download)
                              source = str   → S3 full path (download to tempfile)
                                                        │
                                        ThreadPoolExecutor(N workers)
                                        │  each worker:
                                        │  Path → transcribe_one() directly
                                        │  str  → mc cp → tempfile → transcribe_one() → unlink
                                        │  (unique tempfile per worker, no collisions)
                                        ▼
                              lyrics dict (threading.Lock) → save every 50 → S3 push
```

### Parallelism

`WhisperModel(num_workers=N, cpu_threads=cpu_count//N)` + `ThreadPoolExecutor(N)`. N concurrent `transcribe()` calls dispatch to N independent CTranslate2 replicas. On M4 (10 cores):

| workers | cpu_threads/replica | total threads | RAM   |
|---------|---------------------|---------------|-------|
| 1       | 10                  | 10            | 1.5 GB|
| 2       | 5                   | 10            | 3 GB  |
| 3       | 3                   | 9             | 4.5 GB|
| 4       | 2                   | 8             | 6 GB  |

## Benchmark (M4, int8, CPU, 1 worker)

| Metric | Value |
|---|---|
| Model load | 3.4 s |
| Realtime factor | 2.3× (175.8s audio in 77.3s wall) |
| Language accuracy | pt 98.25% on Brazilian Portuguese |
| Lyrics quality | ~98% (minor errors: "Horizonte" → "Corizonte") |

Total audio in corpus: 45,419 tracks × ~175.8s avg ≈ 92 days of audio.

**VAD is off by default** — Silero VAD breaks on music with background instruments (falsely filters all audio, caused "nn"/Nynorsk misdetection in tests). `--vad` to re-enable.

## ETA — full corpus (45,419 tracks)

### Mac M4, hybrid mode (`--local-dir + --workers N`)

| workers | Est. aggregate × | Wall time | RAM   |
|---------|-----------------|-----------|-------|
| 1       | 2.3×            | 41 days   | 1.5 GB|
| 2       | ~3.5×           | ~27 days  | 3 GB  |
| **3**   | **~4.3×**       | **~22 days** | **4.5 GB** |
| 4       | ~4.8×           | ~20 days  | 6 GB  |

Scaling is sublinear: P-cores and AMX engine are shared. 3 workers is the recommended M4 sweet spot (9 of 10 threads used, E-cores contribute less per thread). **Benchmark first: `--workers 3 --limit 60`** — measure actual `tracks/min` and extrapolate.

### Hetzner GEX44 (RTX 4000 SFF Ada, 20 GB VRAM, S3 mode)

GPU inference: `--device cuda --compute-type float16`. Realtime factor ~20-25× per GPU.
large-v3 float16 ≈ 3 GB VRAM → up to 6 replicas fit; keep `--workers 4` for safety margin.

| workers | Est. aggregate × | Wall time  | Cost (€0.89/hr) |
|---------|-----------------|------------|-----------------|
| 1       | ~22×            | ~4.2 days  | ~€90            |
| 2       | ~40×            | ~2.3 days  | ~€49            |
| **4**   | **~70×**        | **~1.3 days** | **~€28**     |

S3 bucket is in Hetzner HEL1 — download latency is local (~100 MB/s), not a bottleneck.

### VPS 4-core (no GPU)

~190 days. Not viable.

## Infrastructure decision

| Goal | Recommendation | Time | Cost |
|---|---|---|---|
| Full corpus, fastest | Hetzner GEX44, `--workers 4`, float16 | **~1.3 days** | **~€28** |
| Full corpus, free | Mac M4, `--local-dir --workers 3` | **~22 days** | free |
| No spend, background | Mac M4, run overnight unattended | ~22 days | free |

Hetzner is the clear winner for the full 45K run: €28 total, done in 32 hours.

## Usage

```bash
# one-time setup (download model + configure mc alias)
python3 scripts/transcribe/transcribe_lyrics.py --setup

# benchmark parallel scaling — run 60 tracks, measure tracks/min
python3 scripts/transcribe/transcribe_lyrics.py \
    --local-dir /Volumes/EXTRA/hominiscanidae/unzips \
    --workers 3 --limit 60

# Mac: full corpus, hybrid mode (local when available, S3 otherwise)
python3 scripts/transcribe/transcribe_lyrics.py \
    --local-dir /Volumes/EXTRA/hominiscanidae/unzips \
    --workers 3 --resume

# Hetzner GPU: full corpus, pure S3, float16, 4 workers
python3 scripts/transcribe/transcribe_lyrics.py \
    --workers 4 --device cuda --compute-type float16 --resume

# dry-run: see what would be processed and which files are local vs S3
python3 scripts/transcribe/transcribe_lyrics.py \
    --local-dir /Volumes/EXTRA/hominiscanidae/unzips --dry-run | head -20

# offline test (no S3 needed)
python3 scripts/transcribe/transcribe_lyrics.py \
    --local-dir /Volumes/EXTRA/hominiscanidae/unzips --local-only --limit 10
```

Set `UNZIPS_DIR=/Volumes/EXTRA/hominiscanidae/unzips` in `.env` to avoid repeating `--local-dir`.

## Next steps

- [ ] Benchmark `--workers 3` with `--limit 60` on M4 — confirm actual aggregate realtime factor
- [ ] Integrate `lyrics.json` into `generate-albums` Rust binary — expose language filter + lyric search in player
- [ ] Consider segment-level timestamps for karaoke-style display
