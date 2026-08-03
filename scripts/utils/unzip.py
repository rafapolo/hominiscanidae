#!/usr/bin/env python3
"""
Extract downloaded archives (RAR/ZIP/7z) from DEST into unzips/.

Primary extractor is `unar` — it auto-detects charset (CP850/Latin-1/UTF-8) and
fixes the PT-BR filename issues that made unrar/Archive Utility silently drop
tracks with accented names out of RAR4 archives.

`unar` (1.10.7) cannot decode some RAR5 compression methods ("Error on
decrunching"), so RARLAB `unrar` is used as a fallback. RAR5 stores names as
UTF-8, so the charset caveat above does not apply to that path.

Single-file downloads (a bare .mp3/.m4a, not an archive) are foldered into
unzips/<post title>/ so generate-albums can see them — otherwise they sit in
DEST root forever and never reach the player.

Extraction state is tracked in DEST/.extract-state.json, keyed by archive
filename. Do not infer "already extracted" by comparing the download slug to
folder names: the slug is hyphenated-lowercase and the folder is the real
album title, so the match never fires and every run re-extracts, with unar
auto-renaming to -1, -2, -3 … (this produced 378 duplicate folders / 24.6 GB).

Usage:
    python3 scripts/utils/unzip.py             # extract what is not yet extracted
    python3 scripts/utils/unzip.py --force     # re-extract even if folder exists
    python3 scripts/utils/unzip.py --dry-run   # show what would happen
    python3 scripts/utils/unzip.py --singles   # only folder the loose audio files
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

DEST     = Path("/Volumes/EXTRA/hominiscanidae")
UNZIPS   = DEST / "unzips"
STATE    = DEST / ".extract-state.json"
POSTS    = Path(__file__).resolve().parents[2] / "posts.json"

ARCHIVES = {".rar", ".zip", ".7z"}
AUDIO    = {".mp3", ".m4a", ".flac", ".wav", ".ogg", ".opus"}

FORCE    = "--force" in sys.argv
DRY      = "--dry-run" in sys.argv
SINGLES_ONLY = "--singles" in sys.argv

UNAR  = shutil.which("unar") or "unar"
UNRAR = shutil.which("unrar") or "/opt/homebrew/Caskroom/rar/7.23/rar/unrar"


def nfc(s: str) -> str:
    """macOS returns NFD from the filesystem; compare/store as NFC."""
    return unicodedata.normalize("NFC", s)


def load_state() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text())
        except json.JSONDecodeError:
            pass
    return {}


def save_state(state: dict):
    if not DRY:
        STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True))


def post_titles() -> dict:
    """downloaded_as -> post title, for naming single-file downloads.

    Keyed by both the full filename and its stem: the same album is often
    downloaded twice in different formats (foo.mp3 + foo.m4a) and only one
    extension is recorded in posts.json. Keying on the stem too keeps both
    files in one album folder instead of splitting them across two.
    """
    if not POSTS.exists():
        return {}
    out = {}
    for p in json.loads(POSTS.read_text()):
        da, title = p.get("downloaded_as"), p.get("title")
        if da and title:
            out[da] = title
            out.setdefault(Path(da).stem, title)
    return out


def safe_folder(name: str) -> str:
    """Album title -> filesystem-safe folder name."""
    name = re.sub(r"\.{3,}$", "", (name or "").strip())          # trailing ellipsis
    name = re.sub(r'[/\\:*?"<>|]', " - ", name)                  # path-hostile chars
    name = re.sub(r"\s+", " ", name).strip(" .")
    return nfc(name)[:150] or "sem-titulo"


def already_extracted(archive: Path, state: dict) -> bool:
    rec = state.get(archive.name)
    if not rec:
        return False
    folder = UNZIPS / rec["folder"]
    return folder.is_dir() and any(folder.iterdir())


def run_extractor(cmd: list, cwd: Path) -> tuple[bool, str]:
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, timeout=3600)
    except subprocess.TimeoutExpired:
        return False, "timeout"
    out = (r.stdout or "") + (r.returncode and (r.stderr or "") or "")
    # unar exits 0 even when individual members fail
    bad = "Failed!" in out or "Error on decrunching" in out or "checksum error" in out
    return (r.returncode == 0 and not bad), out.strip()[:200]


def extract_one(archive: Path, state: dict) -> str:
    """Returns 'ok' | 'partial' | 'skip' | 'fail'."""
    if not FORCE and already_extracted(archive, state):
        return "skip"

    with tempfile.TemporaryDirectory(dir=str(DEST), prefix=".unz-") as tmpd:
        tmp = Path(tmpd)
        ok, msg = run_extractor([UNAR, "-q", "-o", str(tmp), str(archive)], DEST)
        used = "unar"
        if not ok:
            # unar cannot handle some RAR5 methods; RARLAB unrar is the reference
            # implementation. -kb keeps partially-decoded members.
            for f in tmp.iterdir():
                shutil.rmtree(f, ignore_errors=True) if f.is_dir() else f.unlink()
            ok, msg = run_extractor(
                [UNRAR, "x", "-y", "-kb", "-o+", str(archive), str(tmp) + "/"], DEST)
            used = "unrar"

        produced = [p for p in tmp.iterdir() if not p.name.startswith(".")]
        if not produced:
            print(f"  FAIL  {archive.name} [{used}]: {msg}")
            return "fail"

        # Archive may hold one top folder, or loose files needing a wrapper folder.
        if len(produced) == 1 and produced[0].is_dir():
            src, folder = produced[0], safe_folder(produced[0].name)
        else:
            folder = safe_folder(archive.stem)
            src = tmp / "__wrap__"
            src.mkdir()
            for p in produced:
                shutil.move(str(p), str(src / p.name))

        target = UNZIPS / folder
        if target.exists() and not FORCE:
            # Real duplicate: same album already present. Keep the richer copy.
            def size(d):
                return sum(f.stat().st_size for f in Path(d).rglob("*") if f.is_file())
            if size(src) <= size(target):
                state[archive.name] = {"folder": folder, "by": used}
                return "skip"
            if not DRY:
                shutil.rmtree(target)

        if DRY:
            print(f"  DRY   {archive.name} [{used}] -> {folder}")
            return "ok"

        shutil.move(str(src), str(target))
        # -kb writes 0-byte members for CRC failures; they'd show as dead tracks.
        empties = [f for f in target.rglob("*") if f.is_file() and f.stat().st_size == 0]
        for f in empties:
            f.unlink()

        state[archive.name] = {"folder": folder, "by": used}
        note = f" ({len(empties)} corrupt track(s) dropped)" if empties else ""
        print(f"  OK    {archive.name} [{used}] -> {folder}{note}")
        return "partial" if empties else "ok"


def fold_singles(titles: dict, state: dict) -> int:
    """Move bare audio files in DEST root into unzips/<title>/ so they get indexed."""
    loose = sorted(f for f in DEST.iterdir()
                   if f.is_file() and f.suffix.lower() in AUDIO)
    moved = 0
    for f in loose:
        folder = safe_folder(titles.get(f.name) or titles.get(f.stem) or f.stem)
        target = UNZIPS / folder
        dest_file = target / f.name
        if dest_file.exists():
            continue
        if DRY:
            print(f"  DRY   single {f.name} -> {folder}/")
            moved += 1
            continue
        target.mkdir(parents=True, exist_ok=True)
        shutil.move(str(f), str(dest_file))
        state[f.name] = {"folder": folder, "by": "single"}
        print(f"  OK    single {f.name} -> {folder}/")
        moved += 1
    return moved


# A bare kebab-case filename is the "slug-tail" generate-albums hides when the folder
# also holds numbered tracks. Keep it in sync with RE_SLUG_TAIL in generate-albums.
RE_SLUG_NAME = re.compile(r"^[a-z][a-z0-9\-]+\.mp3$")


def fold_dirs(titles: dict, state: dict) -> int:
    """Move audio folders sitting in DEST root into unzips/<title>/.

    dl_ytdlp returns a folder when a playlist yields more than one track. Only
    unzips/ is indexed, so a folder left in DEST root is as invisible as the
    loose singles fold_singles rescues.
    """
    loose = sorted(d for d in DEST.iterdir()
                   if d.is_dir()
                   and d != UNZIPS
                   and not d.name.startswith(".")
                   and any(f.suffix.lower() in AUDIO for f in d.rglob("*")))
    moved = 0
    for d in loose:
        folder = safe_folder(titles.get(d.name) or d.name)
        target = UNZIPS / folder
        if DRY:
            print(f"  DRY   dir {d.name} -> {folder}/")
            moved += 1
            continue
        if target.exists():
            # The target usually exists because an earlier rescue landed one track
            # there. Skipping abandoned the freshly downloaded *full album* in DEST
            # root, where generate-albums never sees it — the exact invisibility this
            # function exists to prevent. Merge instead.
            n = merge_into(d, target)
            state[d.name] = {"folder": folder, "by": "dir-merge"}
            print(f"  MERGE dir {d.name} -> {folder}/ ({n} arquivos)")
        else:
            shutil.move(str(d), str(target))
            state[d.name] = {"folder": folder, "by": "dir"}
            print(f"  OK    dir {d.name} -> {folder}/")
        moved += 1
    return moved


def merge_into(src: Path, target: Path) -> int:
    """Move src's files into target, dropping exact duplicates, never overwriting."""
    moved = 0
    have = {}
    for f in target.rglob("*"):
        if f.is_file():
            have.setdefault(f.stat().st_size, []).append(f)
    for f in sorted(src.rglob("*")):
        if not f.is_file() or f.name.startswith("._"):
            continue
        digest = None
        for other in have.get(f.stat().st_size, []):
            if digest is None:
                digest = _md5(f)
            if digest != _md5(other):
                continue
            # Same audio under two names. Keep the numbered one: a bare kebab-case
            # name is the slug-tail that generate-albums hides, so keeping *that*
            # copy would drop the track from the album entirely.
            if RE_SLUG_NAME.match(other.name) and not RE_SLUG_NAME.match(f.name):
                other.unlink()
                have[f.stat().st_size].remove(other)
                continue
            f.unlink()              # already there under an equal-or-better name
            break
        else:
            dest = target / f.name
            i = 1
            while dest.exists():
                i += 1
                dest = target / f"{f.stem} ({i}){f.suffix}"
            f.rename(dest)
            have.setdefault(dest.stat().st_size, []).append(dest)
            moved += 1
    shutil.rmtree(src, ignore_errors=True)
    return moved


def _md5(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    UNZIPS.mkdir(exist_ok=True)
    state = load_state()
    titles = post_titles()

    counts = {"ok": 0, "partial": 0, "skip": 0, "fail": 0}

    if not SINGLES_ONLY:
        archives = sorted(f for f in DEST.iterdir()
                          if f.is_file() and f.suffix.lower() in ARCHIVES)
        print(f"Found {len(archives)} archives")
        for archive in archives:
            counts[extract_one(archive, state)] += 1
        save_state(state)
        print(f"\nArchives: {counts['ok']} extracted, {counts['partial']} partial, "
              f"{counts['skip']} skipped, {counts['fail']} failed")

    print("\nFoldering single-file downloads…")
    n = fold_singles(titles, state)
    n += fold_dirs(titles, state)
    save_state(state)
    print(f"Singles: {n} foldered")

    if (counts["ok"] or counts["partial"] or n) and not DRY:
        print("\nConverting WAV/FLAC to MP3...")
        conv = Path(__file__).parent / "flac_to_mp3.py"
        subprocess.run([sys.executable, str(conv)], check=False)


if __name__ == "__main__":
    main()
