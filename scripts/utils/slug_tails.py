#!/usr/bin/env python3
"""Classify and repair "slug-tail" mp3s: a kebab-case single-file download
(artist-album-year.mp3) sitting in a folder alongside an extracted album.

generate-albums drops such a file from the index whenever the other tracks are
numbered, on the assumption that it is the same music arriving twice. That
assumption is right about two thirds of the time. When it is wrong the file is
a *different* recording that exists nowhere else, and it silently disappears
from the catalog.

Duration is too weak a signal to tell the two apart — a YouTube rescue of the
same song routinely differs by 3-10s, and two different songs routinely match.
So we fingerprint the audio with chromaprint (fpcalc) and compare.

  python3 scripts/utils/slug_tails.py --scan              # report, touch nothing
  python3 scripts/utils/slug_tails.py --scan --only-index # only 1-track albums
  python3 scripts/utils/slug_tails.py --apply             # delete dups, split distinct

Verdicts:
  dup      slug audio matches a sibling track  -> redundant, safe to delete
  album    slug audio is the whole album in one file, siblings are its tracks
  distinct slug audio is unrelated to anything in the folder -> split out
"""

import argparse
import gzip
import json
import re
import subprocess
import sys
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from functools import cmp_to_key
from pathlib import Path

ROOT   = Path(__file__).resolve().parent.parent.parent
UNZIPS = Path("/Volumes/EXTRA/hominiscanidae/unzips")
POSTS  = ROOT / "posts.json"
ALBUMS = ROOT / "data" / "homi-albums.json.gz"
STATE  = ROOT / "data" / "slug-tails.json"

# Mirrors RE_SLUG_TAIL / RE_TRACK_NUM_* in generate-albums/src/main.rs. Keep in sync —
# a file this misses is one the Rust side drops without us ever classifying it.
RE_SLUG      = re.compile(r"^[a-z][a-z0-9\-]+\.mp3$")
RE_NUM_START = re.compile(r"^\s*(\d{1,3})\s*[.\-_ ]")
RE_NUM_MID   = re.compile(r" - (\d{1,3})[.\s]")

# Chromaprint emits ~7.8 sub-fingerprints/s. 120s of audio is plenty to identify a
# track and keeps the whole archive scannable in minutes.
FP_SECONDS = 120
# Bit error rate below which two fingerprints are the same recording. Chromaprint's
# own matcher treats <0.25 as a match; we leave headroom for the re-encodes that
# yt-dlp and the flac->mp3 pass produce.
BER_MATCH = 0.22


def fingerprint(path: Path) -> list[int] | None:
    try:
        out = subprocess.run(
            ["fpcalc", "-raw", "-length", str(FP_SECONDS), str(path)],
            capture_output=True, text=True, timeout=120,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if out.returncode != 0:
        return None
    for line in out.stdout.splitlines():
        if line.startswith("FINGERPRINT="):
            raw = line.split("=", 1)[1].strip()
            if not raw:
                return None
            return [int(x) for x in raw.split(",") if x]
    return None


def ber(a: list[int], b: list[int]) -> float:
    """Lowest bit-error rate over a sliding alignment of two raw fingerprints.

    The offset must be searched in both directions: a YouTube rip of the same song
    typically carries a fraction of a second of extra silence at the head, and
    comparing the two at offset 0 then reports a mismatch for identical audio.
    """
    if not a or not b:
        return 1.0
    best = 1.0
    # ~7.8 frames/s, so +-60 frames covers the ~8s of lead-in drift seen in practice.
    for off in range(-60, 61):
        if off >= 0:
            x, y = a, b[off:]
        else:
            x, y = a[-off:], b
        span = min(len(x), len(y), 200)
        if span < 40:            # too little overlap to judge
            continue
        bits = 0
        for i in range(span):
            bits += (x[i] ^ y[i]).bit_count()
        rate = bits / (span * 32)
        if rate < best:
            best = rate
            if best < 0.05:
                break
    return best


def natural_cmp(a: str, b: str) -> int:
    """Mirror of natural_cmp in generate-albums/src/main.rs.

    Which file counts as the slug-tail is decided by whichever sorts last, so this
    ordering must match the Rust side exactly. A plain byte sort disagrees: it puts
    "churrus-....mp3" after "NA. Churrus - Oldfield Park.mp3" because lowercase
    outranks uppercase, and we would then classify a file the indexer never drops.

    Digit runs compare numerically only when both sides are at a digit; otherwise the
    comparison is char-by-char on the lowercased character, exactly as the Rust does.
    """
    i = j = 0
    while True:
        if i >= len(a) and j >= len(b):
            return 0
        if i >= len(a):
            return -1
        if j >= len(b):
            return 1
        if a[i].isdigit() and b[j].isdigit():
            si, sj = i, j
            while i < len(a) and a[i].isdigit():
                i += 1
            while j < len(b) and b[j].isdigit():
                j += 1
            na, nb = int(a[si:i]), int(b[sj:j])
            if na != nb:
                return -1 if na < nb else 1
        else:
            ca, cb = a[i].lower(), b[j].lower()
            i += 1
            j += 1
            if ca != cb:
                return -1 if ca < cb else 1


natural_key = cmp_to_key(natural_cmp)


def slug_tail_folders(only: set[str] | None = None) -> list[dict]:
    """Folders holding a slug-tail mp3 next to numbered tracks."""
    found = []
    for folder in sorted(UNZIPS.iterdir()):
        if not folder.is_dir():
            continue
        if only is not None and folder.name not in only:
            continue
        mp3s = sorted(
            (f for f in folder.iterdir()
             if f.is_file() and f.suffix.lower() == ".mp3" and not f.name.startswith("._")),
            key=lambda f: natural_key(f.name),
        )
        if len(mp3s) < 2:
            continue
        slug = mp3s[-1]
        if not RE_SLUG.match(slug.name):
            continue
        rest = mp3s[:-1]
        if not any(RE_NUM_START.match(f.name) or RE_NUM_MID.search(f.name) for f in rest):
            continue
        found.append({"folder": folder, "slug": slug, "rest": rest})
    return found


def classify(entry: dict) -> dict:
    slug, rest = entry["slug"], entry["rest"]
    fp_slug = fingerprint(slug)
    result = {
        "folder": entry["folder"].name,
        "slug": slug.name,
        "n_rest": len(rest),
        "verdict": "unknown",
        "ber": None,
        "matched": None,
    }
    if fp_slug is None:
        return result

    best, best_name = 1.0, None
    for track in rest:
        fp = fingerprint(track)
        if fp is None:
            continue
        r = ber(fp_slug, fp)
        if r < best:
            best, best_name = r, track.name
            if best < 0.05:
                break

    result["ber"] = round(best, 4)
    result["matched"] = best_name
    if best <= BER_MATCH:
        # A slug file that matches a sibling is either that one track duplicated, or
        # the whole album in one file (which also matches its own opening track,
        # since fpcalc only reads the first FP_SECONDS). Duration separates those.
        result["verdict"] = "album" if _is_whole_album(slug, rest) else "dup"
    else:
        result["verdict"] = "distinct"
    return result


def _duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0


def _is_whole_album(slug: Path, rest: list[Path]) -> bool:
    sd = _duration(slug)
    longest = max((_duration(f) for f in rest), default=0.0)
    # Whole-album files run well past the longest single track.
    return sd > longest * 1.5 and sd > 0


def discard(path: Path) -> None:
    """Move a redundant file to a trash folder rather than deleting it.

    The classification is fingerprint-backed but not infallible, and the audio is
    unrecoverable if the source link is dead — so keep it until the catalog has
    been rebuilt and eyeballed. Purge DEST/.slug-tail-trash by hand afterwards.
    """
    trash = UNZIPS.parent / ".slug-tail-trash"
    trash.mkdir(exist_ok=True)
    dest = trash / f"{path.parent.name}__{path.name}"
    n = 1
    while dest.exists():
        n += 1
        dest = trash / f"{path.parent.name}__{n}__{path.name}"
    path.rename(dest)


def move(src: Path, folder: Path) -> Path:
    """Move src into folder without ever clobbering a file already there.

    Two posts can download the same slug filename for different recordings, so the
    destination name collides more often than it looks. Path.rename overwrites
    silently on POSIX, which destroys the audio it lands on.
    """
    dest = folder / src.name
    n = 1
    while dest.exists():
        n += 1
        dest = folder / f"{src.stem} ({n}){src.suffix}"
    src.rename(dest)
    return dest


def post_titles() -> dict:
    if not POSTS.exists():
        return {}
    out = {}
    for p in json.loads(POSTS.read_text()):
        slug = p["url"].rstrip("/").split("/")[-1].replace(".html", "")
        out[slug] = p
    return out


def safe_folder(name: str) -> str:
    name = re.sub(r"\.{3,}$", "", (name or "").strip())
    name = re.sub(r'[/\\:*?"<>|]', " - ", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name[:150] or "sem-titulo"


RE_FOLDER_YEAR = re.compile(r"^(19|20)\d{2} - ")
# Portuguese articles and prepositions: present in a folder name taken from the album
# title, absent from the one derived from a URL slug. They carry no identity.
STOPWORDS = {"a", "o", "as", "os", "e", "de", "do", "da", "dos", "das",
             "em", "no", "na", "nos", "nas", "um", "uma", "para", "por", "com"}


def _tokens(name: str) -> set[str]:
    """Identity tokens for a folder or album title.

    The same album is named three ways here: "2016 - Título" from generate-albums,
    "titulo-do-post-2016" from the download slug, and "Titulo Do Post" from the post
    title. Accents must be folded rather than stripped — dropping them outright turns
    "Máquina" into "mquina", which then fails to match "Maquina" and mints a duplicate
    album folder beside the one that was already there.
    """
    name = RE_FOLDER_YEAR.sub("", name)
    name = re.sub(r"[-\s]((?:19|20)\d{2})$", "", name)
    name = unicodedata.normalize("NFD", name)
    name = "".join(c for c in name if unicodedata.category(c) != "Mn")
    parts = re.split(r"[^a-z0-9]+", name.lower())
    return {p for p in parts if p and p not in STOPWORDS}


def same_album(a: str, b: str) -> bool:
    """Whether two names denote the same release, allowing for the three spellings."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return False
    inter = len(ta & tb)
    # Either name may be a truncation of the other (post titles are cut short), so
    # containment counts as much as overall similarity.
    return inter / min(len(ta), len(tb)) >= 0.8 or inter / len(ta | tb) >= 0.7


def _year_for(slug_stem: str, post: dict | None) -> str:
    """Year prefix for a new folder: from the slug's tail, else the post's date.

    generate-albums reads album-level year off the folder name, so a folder created
    without one lands in the player's "noyear" bucket.
    """
    m = re.search(r"-((?:19|20)\d{2})$", slug_stem)
    if m:
        return m.group(1)
    lastmod = (post or {}).get("lastmod") or ""
    return lastmod[:4] if re.match(r"^(19|20)\d{2}", lastmod) else ""


def existing_folder(title: str) -> Path | None:
    """The archive folder already holding this post's album, year prefix or not."""
    for d in sorted(UNZIPS.iterdir()):
        if d.is_dir() and same_album(d.name, title):
            return d
    return None


def indexed_single_track_folders() -> set[str]:
    if not ALBUMS.exists():
        return set()
    data = json.load(gzip.open(ALBUMS))
    return {a["path"] for a in data["albums"] if len(a.get("tracks", [])) == 1}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", action="store_true", help="classify only, change nothing")
    ap.add_argument("--apply", action="store_true", help="delete dups and split distinct")
    ap.add_argument("--only-index", action="store_true",
                    help="restrict to folders the index shows as 1-track albums")
    ap.add_argument("--from-state", action="store_true",
                    help="reuse the verdicts in data/slug-tails.json instead of "
                         "re-fingerprinting, so --apply acts on the plan you reviewed")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()
    if not (args.scan or args.apply):
        ap.error("pass --scan or --apply")

    if not UNZIPS.exists():
        sys.exit(f"{UNZIPS} not mounted — refusing to run")

    only = indexed_single_track_folders() if args.only_index else None
    entries = slug_tail_folders(only)
    print(f"slug-tail folders: {len(entries)}", file=sys.stderr)

    if args.from_state:
        cached = {(r["folder"], r["slug"]): r for r in json.loads(STATE.read_text())}
        missing = [e for e in entries if (e["folder"].name, e["slug"].name) not in cached]
        if missing:
            sys.exit(f"{len(missing)} folders are not in {STATE.name} — re-run --scan")
        results = [cached[(e["folder"].name, e["slug"].name)] for e in entries]
    else:
        with ThreadPoolExecutor(args.workers) as ex:
            results = list(ex.map(classify, entries))

    counts = {}
    for r in results:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    print(f"\n{counts}\n")

    for r in sorted(results, key=lambda x: (x["verdict"], x["folder"])):
        print(f"  {r['verdict']:8s} ber={r['ber']} {r['folder'][:50]:50s} <- {r['slug'][:45]}")

    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(results, indent=1, ensure_ascii=False))
    print(f"\nwrote {STATE}", file=sys.stderr)

    if not args.apply:
        return

    posts = post_titles()
    trashed = relocated = kept = 0
    for r, e in zip(results, entries):
        slug_path = e["slug"]
        folder = e["folder"]

        if r["verdict"] in ("dup", "album"):
            discard(slug_path)
            trashed += 1
            continue
        if r["verdict"] != "distinct":
            continue

        post = posts.get(slug_path.stem)
        title = safe_folder((post or {}).get("title") or slug_path.stem)

        # A distinct slug-tail naming the very folder it sits in is that post's own
        # fallback download, sitting beside the album it failed to replace. There is no
        # second album to move it to, and no way to tell a bad YouTube match from a real
        # bonus track, so leave the audio alone — generate-albums already hides it.
        if same_album(folder.name, title) or same_album(folder.name, slug_path.stem):
            kept += 1
            continue

        # Otherwise the file came from a *different* post and was misfiled here. It is
        # the only copy of that release, so give it the folder it belongs in.
        target = existing_folder(title)
        if target is not None and target != folder:
            fp = fingerprint(slug_path)
            present = [f for f in target.iterdir()
                       if f.is_file() and f.suffix.lower() == ".mp3"
                       and not f.name.startswith("._")]
            if fp and any(ber(fp, other) <= BER_MATCH
                          for other in filter(None, (fingerprint(f) for f in present))):
                discard(slug_path)      # that post already has this recording
                trashed += 1
                continue
        else:
            year = _year_for(slug_path.stem, post)
            target = UNZIPS / (f"{year} - {title}" if year else title)
            target.mkdir(parents=True, exist_ok=True)
        move(slug_path, target)
        relocated += 1
        print(f"  relocate {slug_path.name}  {folder.name}  ->  {target.name}")

    print(f"\ntrashed {trashed} redundant, relocated {relocated} misfiled, "
          f"kept {kept} in place (own-post fallback)", file=sys.stderr)


if __name__ == "__main__":
    main()
