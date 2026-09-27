#!/usr/bin/env python3
"""
Transcribe every MP3 using Whisper Large-v3 (faster-whisper / CTranslate2).

Source modes:
  (default)          list from S3, download every file via mc CLI
  --local-dir PATH   list from S3, use local copy when it exists, download the rest
  --local-only       list and read from --local-dir only (no S3 needed — offline/test)

Parallel workers:
  --workers N        N concurrent Whisper instances (default: 1)
                     cpu_threads auto-set to cpu_count // N per replica
                     RAM: ~1.5 GB × N  (large-v3 int8)

Benchmark (M4, int8, 1 worker): 175s audio → 77s wall = 2.3× realtime
Estimated parallel scaling (M4, 10-core, 4P + 6E):
  2 workers → ~3.5× aggregate    3 workers → ~4.3×    4 workers → ~4.8×

Usage:
    # one-time setup
    python3 scripts/transcribe/transcribe_lyrics.py --setup

    # Mac: list from S3, serve local copies, download the rest — 3 workers
    python3 scripts/transcribe/transcribe_lyrics.py \\
        --local-dir /Volumes/EXTRA/hominiscanidae/unzips \\
        --workers 3 --resume

    # Hetzner GPU: pure S3, float16, 4 workers
    python3 scripts/transcribe/transcribe_lyrics.py \\
        --workers 4 --device cuda --compute-type float16 --resume

    # offline test (local files only, no S3 needed)
    python3 scripts/transcribe/transcribe_lyrics.py \\
        --local-dir /Volumes/EXTRA/hominiscanidae/unzips --local-only --limit 10

Environment (.env or exported):
    AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY  S3 credentials
    S3_BUCKET       default: indie
    S3_PREFIX       default: indie/
    MC_ALIAS        default: s3
    LYRICS_S3_KEY   default: lyrics.json
    UNZIPS_DIR      local unzips path (overridden by --local-dir)
"""

import argparse
import json
import logging
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

log = logging.getLogger("transcribe")
log.setLevel(logging.INFO)
_h = logging.StreamHandler(sys.stderr)
_h.setFormatter(logging.Formatter(
    "%(asctime)s  %(levelname)-7s  %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
))
log.addHandler(_h)

# ── graceful shutdown ──────────────────────────────────────────────────────

_shutdown = threading.Event()


def _on_signal(signum, frame):
    if _shutdown.is_set():
        log.warning("Second interrupt — forcing exit")
        sys.exit(1)
    _shutdown.set()
    log.warning("Graceful shutdown — finishing in-flight tracks...")


signal.signal(signal.SIGINT, _on_signal)
signal.signal(signal.SIGTERM, _on_signal)

# ── helpers ────────────────────────────────────────────────────────────────


def nfc(s):
    return unicodedata.normalize("NFC", s)


def mc(*args, timeout=300):
    try:
        return subprocess.run(
            ["mc"] + list(args),
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        log.error("mc timed out: %s", " ".join(args))
        return None
    except FileNotFoundError:
        log.error("mc not found — install: brew install minio/stable/mc")
        sys.exit(1)


def load_env():
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def load_lyrics_json(path):
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                log.info("Loaded %d entries from %s", len(data), path)
                return data
        except (json.JSONDecodeError, OSError) as e:
            log.warning("Could not load %s: %s", path, e)
    return {}


def save_lyrics_json(path, data):
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")),
                   encoding="utf-8")
    tmp.rename(path)


def push_lyrics_json(s3_path, local_path):
    r = mc("cp", "--no-progress", str(local_path), s3_path)
    if r and r.returncode == 0:
        log.info("Pushed lyrics.json → %s", s3_path)
    else:
        log.error("Push failed → %s", s3_path)


def pull_lyrics_json(s3_path, local_path):
    r = mc("cp", "--no-progress", s3_path, str(local_path))
    if r and r.returncode == 0:
        log.info("Pulled lyrics.json ← %s", s3_path)
        return True
    log.info("No existing lyrics.json at %s", s3_path)
    return False


# ── file listing ──────────────────────────────────────────────────────────


def list_s3_mp3s(mc_alias, bucket, prefix, one_per_album=False):
    """List MP3s from S3. Returns [(s3_key, s3_full_path), ...]."""
    path = f"{mc_alias}/{bucket}/{prefix}"
    log.info("Listing S3 MP3s in %s ...", path)
    t0 = time.time()
    r = mc("find", path, "--name", "*.mp3", timeout=600)
    if not r or r.returncode != 0:
        log.error("mc find failed")
        return []
    lines = [l.strip() for l in r.stdout.splitlines()
             if l.strip().lower().endswith(".mp3")]
    log.info("Found %d S3 MP3s in %.1fs", len(lines), time.time() - t0)

    candidates, seen = [], set()
    for s3_full in lines:
        parts = s3_full.split(f"/{bucket}/", 1)
        s3_key = nfc(parts[1] if len(parts) == 2 else s3_full)
        if one_per_album:
            album = "/".join(s3_key.split("/")[:-1])
            if album in seen:
                continue
            seen.add(album)
        candidates.append((s3_key, s3_full))
    return candidates


def list_local_mp3s(base_dir, prefix, one_per_album=False):
    """List MP3s from local filesystem. Returns [(s3_key, Path), ...]."""
    base = Path(base_dir)
    log.info("Scanning local MP3s in %s ...", base)
    t0 = time.time()
    mp3s = sorted(base.rglob("*.mp3"))
    log.info("Found %d local MP3s in %.1fs", len(mp3s), time.time() - t0)

    candidates, seen = [], set()
    for mp3 in mp3s:
        rel = mp3.relative_to(base)
        s3_key = nfc(f"{prefix}{rel}")
        if one_per_album:
            album = str(rel.parent)
            if album in seen:
                continue
            seen.add(album)
        candidates.append((s3_key, mp3))
    return candidates


def resolve_sources(s3_candidates, local_dir, prefix):
    """
    Map each S3 file to a local Path when the file exists on disk, otherwise
    keep the S3 full-path string. Returns [(s3_key, source), ...] where source
    is Path (local, no download) or str (S3 full path, must download).
    """
    if not local_dir:
        return [(k, p) for k, p in s3_candidates]

    base = Path(local_dir)
    resolved = []
    local_hits = 0
    for s3_key, s3_full in s3_candidates:
        rel = s3_key.removeprefix(prefix)
        local = base / rel
        if local.exists() and local.stat().st_size > 0:
            resolved.append((s3_key, local))
            local_hits += 1
        else:
            resolved.append((s3_key, s3_full))
    s3_hits = len(s3_candidates) - local_hits
    log.info("Sources: %d local  %d need S3 download", local_hits, s3_hits)
    return resolved


# ── transcription core ────────────────────────────────────────────────────


def transcribe_one(model, local_path, vad):
    segs, info = model.transcribe(
        str(local_path),
        language=None,
        vad_filter=vad,
        condition_on_previous_text=False,
    )
    texts, no_speech_sum, seg_count = [], 0.0, 0
    for seg in segs:
        texts.append(seg.text.strip())
        no_speech_sum += getattr(seg, "no_speech_prob", 0.0)
        seg_count += 1

    lang_probs = getattr(info, "all_language_probs", None)
    if lang_probs:
        language = {lc: round(p, 4)
                    for lc, p in sorted(lang_probs, key=lambda x: x[1], reverse=True)[:2]}
    else:
        language = {info.language: round(info.language_probability, 4)}

    return {
        "language": language,
        "lyrics": " ".join(t for t in texts if t),
        "duration": round(info.duration, 1),
        "duration_after_vad": round(getattr(info, "duration_after_vad", 0), 1),
        "no_speech_prob": round(no_speech_sum / seg_count, 4) if seg_count else 0.0,
        "segments": seg_count,
    }


# ── worker factory ────────────────────────────────────────────────────────


def make_worker(model, work_dir, vad, lyrics, lock):
    """
    Return a task callable for ThreadPoolExecutor.

    source is Path  → local file, read directly, never deleted
    source is str   → S3 full path, downloaded to a unique tempfile, deleted after
    """

    def run(s3_key, source):
        t0 = time.time()
        local_path = None
        owned = False
        try:
            if isinstance(source, Path):
                local_path = source
            else:
                fd, tmp = tempfile.mkstemp(dir=work_dir, suffix=".mp3")
                os.close(fd)
                local_path = Path(tmp)
                owned = True
                r = mc("cp", "--no-progress", source, str(local_path))
                if (not r or r.returncode != 0
                        or not local_path.exists()
                        or local_path.stat().st_size == 0):
                    msg = (r.stderr or "").strip() if r else "mc timeout"
                    raise RuntimeError(f"download failed: {msg}")

            entry = transcribe_one(model, local_path, vad)

        except Exception as e:
            entry = {"language": {}, "lyrics": None, "error": str(e)}

        finally:
            if owned and local_path and local_path.exists():
                local_path.unlink(missing_ok=True)

        with lock:
            lyrics[s3_key] = entry

        return s3_key, time.time() - t0, entry.get("error")

    return run


# ── main ──────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Transcribe MP3s with Whisper Large-v3 (faster-whisper)"
    )
    parser.add_argument("--limit",         type=int,  default=0,
                        help="Process at most N files (0 = all)")
    parser.add_argument("--model",         type=str,  default="large-v3")
    parser.add_argument("--one-per-album", action="store_true",
                        help="Transcribe only the first MP3 per album folder")
    parser.add_argument("--device",        type=str,  default="auto")
    parser.add_argument("--compute-type",  type=str,  default="auto")
    parser.add_argument("--save-every",    type=int,  default=50,
                        help="Checkpoint every N completed tracks (default: 50)")
    parser.add_argument("--workers",       type=int,  default=1,
                        help="Parallel Whisper instances (default: 1; ~1.5 GB RAM each)")
    parser.add_argument("--cpu-threads",   type=int,  default=0,
                        help="CTranslate2 threads per worker (0 = cpu_count // workers)")
    parser.add_argument("--local-dir",     type=str,  default=None,
                        help="Local unzips/ path — used as cache (prefer local, download rest). "
                             "Overrides UNZIPS_DIR env var.")
    parser.add_argument("--local-only",    action="store_true",
                        help="List and read from --local-dir only; no S3 listing or download. "
                             "Requires --local-dir.")
    parser.add_argument("--dry-run",       action="store_true")
    parser.add_argument("--resume",        action="store_true",
                        help="Pull existing lyrics.json from S3 before starting")
    parser.add_argument("--no-push",       action="store_true",
                        help="Skip pushing lyrics.json to S3")
    parser.add_argument("--model-dir",     type=str,  default=None,
                        help="Whisper model cache directory")
    parser.add_argument("--setup",         action="store_true",
                        help="One-time: download model + configure mc alias, then exit")
    parser.add_argument("--vad",           action="store_true",
                        help="Enable VAD filter (off by default — breaks on music)")
    parser.add_argument("--online",        action="store_true",
                        help="Allow model download from HF Hub (offline by default)")
    args = parser.parse_args()

    load_env()

    mc_alias      = os.environ.get("MC_ALIAS",      "s3")
    bucket        = os.environ.get("S3_BUCKET",     "indie")
    prefix        = os.environ.get("S3_PREFIX",     "indie/")
    lyrics_s3_key = os.environ.get("LYRICS_S3_KEY", "lyrics.json")
    s3_endpoint   = os.environ.get("S3_ENDPOINT",   "https://hel1.your-objectstorage.com")

    local_dir  = args.local_dir or os.environ.get("UNZIPS_DIR") or None

    if args.local_only and not local_dir:
        log.error("--local-only requires --local-dir (or UNZIPS_DIR)")
        sys.exit(1)

    lyrics_local = ROOT / "lyrics.json"
    lyrics_s3    = f"{mc_alias}/{bucket}/{lyrics_s3_key}"
    work_dir     = ROOT / ".lyrics_work"

    num_workers = max(1, args.workers)
    cpu_threads = args.cpu_threads or max(1, (os.cpu_count() or 4) // num_workers)

    # ── setup ──────────────────────────────────────────────────────────
    if args.setup:
        log.info("=== SETUP MODE ===")
        ak = os.environ.get("AWS_ACCESS_KEY_ID", "")
        sk = os.environ.get("AWS_SECRET_ACCESS_KEY", "")
        if ak and sk:
            r = mc("alias", "set", mc_alias, s3_endpoint, ak, sk)
            log.info("mc alias %s", "ok ✓" if r and r.returncode == 0 else "FAILED")
        else:
            log.warning("No credentials — skipping mc alias")
        log.info("Downloading Whisper %s ...", args.model)
        from faster_whisper import WhisperModel
        WhisperModel(args.model, device="cpu", compute_type="int8")
        log.info("Model cached ✓")
        r = mc("ls", f"{mc_alias}/{bucket}/")
        log.info("S3 connection %s", "ok ✓" if r and r.returncode == 0 else "FAILED")
        return

    # ── list files ─────────────────────────────────────────────────────
    if args.local_only:
        # offline mode: list from local dir, no S3 involved
        raw_candidates = list_local_mp3s(local_dir, prefix, args.one_per_album)
        # source is already a Path — no resolve step needed
        candidates = raw_candidates
    else:
        # S3 is authoritative list; optionally serve local copies
        s3_candidates = list_s3_mp3s(mc_alias, bucket, prefix, args.one_per_album)
        candidates = resolve_sources(s3_candidates, local_dir, prefix)

    if args.limit:
        candidates = candidates[:args.limit]

    if not candidates:
        log.info("Nothing to do")
        return

    if args.dry_run:
        for s3_key, source in candidates:
            tag = "local" if isinstance(source, Path) else "s3"
            print(f"{tag}\t{s3_key}")
        log.info("dry-run: %d files listed", len(candidates))
        return

    # ── resume ─────────────────────────────────────────────────────────
    if args.resume:
        pull_lyrics_json(lyrics_s3, lyrics_local)
    lyrics = load_lyrics_json(lyrics_local)

    pending = [(k, src) for k, src in candidates if k not in lyrics]
    if skipped := len(candidates) - len(pending):
        log.info("Skipping %d already done, %d remaining", skipped, len(pending))
    if not pending:
        log.info("All transcribed — done")
        return
    total = len(pending)

    # ── load model ─────────────────────────────────────────────────────
    log.info(
        "Loading Whisper %s  device=%s  compute=%s  "
        "workers=%d  cpu_threads=%d/worker  (~%.0f GB RAM)",
        args.model, args.device, args.compute_type,
        num_workers, cpu_threads, 1.5 * num_workers,
    )
    t0 = time.time()
    from faster_whisper import WhisperModel
    model_kwargs = dict(
        device=args.device,
        compute_type=args.compute_type,
        cpu_threads=cpu_threads,
        num_workers=num_workers,
    )
    if args.model_dir:
        model_kwargs["download_root"] = args.model_dir
    if not args.online:
        model_kwargs["local_files_only"] = True
    model = WhisperModel(args.model, **model_kwargs)
    log.info("Model loaded in %.1f s", time.time() - t0)

    # ── prepare work dir (only when S3 downloads will happen) ──────────
    needs_download = any(isinstance(src, str) for _, src in pending)
    if needs_download:
        work_dir.mkdir(parents=True, exist_ok=True)
        for f in work_dir.iterdir():
            f.unlink(missing_ok=True)

    # ── transcribe ─────────────────────────────────────────────────────
    lock      = threading.Lock()
    worker_fn = make_worker(model, work_dir if needs_download else None,
                             args.vad, lyrics, lock)
    start     = time.time()
    processed = failed = 0

    local_count = sum(1 for _, src in pending if isinstance(src, Path))
    log.info(
        "Starting: %d tracks  workers=%d  local=%d  s3-download=%d",
        total, num_workers, local_count, total - local_count,
    )

    with ThreadPoolExecutor(max_workers=num_workers) as pool:
        futs = {pool.submit(worker_fn, k, src): k for k, src in pending}

        for i, fut in enumerate(as_completed(futs), 1):
            if _shutdown.is_set():
                for f in futs:
                    f.cancel()
                break

            try:
                s3_key, elapsed, error = fut.result()
            except Exception as e:
                s3_key = futs[fut]
                elapsed, error = 0.0, str(e)

            if error:
                log.error("[%d/%d] fail  %.1fs  %s  — %s", i, total, elapsed, s3_key, error)
                failed += 1
            else:
                log.info("[%d/%d] ok    %.1fs  %s", i, total, elapsed, s3_key)
                processed += 1

            if i % args.save_every == 0 or i == total or _shutdown.is_set():
                with lock:
                    snapshot = dict(lyrics)
                save_lyrics_json(lyrics_local, snapshot)
                if not args.no_push:
                    push_lyrics_json(lyrics_s3, lyrics_local)
                wall = time.time() - start
                tpm  = processed / wall * 60 if wall > 0 else 0
                log.info(
                    "Checkpoint  %d entries | %d ok  %d fail | %.1f tracks/min",
                    len(snapshot), processed, failed, tpm,
                )

    # ── cleanup ────────────────────────────────────────────────────────
    if needs_download:
        for f in work_dir.glob("*"):
            f.unlink(missing_ok=True)
        try:
            work_dir.rmdir()
        except OSError:
            pass

    save_lyrics_json(lyrics_local, lyrics)
    if not args.no_push:
        push_lyrics_json(lyrics_s3, lyrics_local)

    wall = time.time() - start
    log.info(
        "Done. %d ok  %d fail  in %.0f min  (%.1f tracks/min)",
        processed, failed, wall / 60,
        processed / (wall / 60) if wall > 0 else 0,
    )


if __name__ == "__main__":
    main()
