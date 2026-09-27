#!/usr/bin/env python3
"""
Merge genres from data/genres.json into data/homi-albums.json.gz.

For each track:
  - Direct filename match → use that track's top genre
  - No match (Bandcamp-expanded album) → fall back to album-level winner
    (majority vote across whichever tracks ARE in genres.json)

Adds a `genre` field (e.g. "Latin---MPB") to every track that has data.
"""
import json
import gzip
import shutil
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).parent.parent.parent
GENRES_FILE = ROOT / "data" / "genres.json"
ALBUMS_IN  = ROOT / "data" / "homi-albums.json.gz"
ALBUMS_OUT = ROOT / "data" / "homi-albums.json.gz"

def album_winner(track_map: dict) -> str | None:
    """Majority-vote top genre across all tracks in track_map."""
    votes: Counter = Counter()
    for tdata in track_map.values():
        gs = tdata.get("genres") or []
        top3 = sorted(gs, key=lambda x: x["score"], reverse=True)[:3]
        for g in top3:
            votes[g["label"]] += 1
    return votes.most_common(1)[0][0] if votes else None

def main():
    print(f"reading {GENRES_FILE}")
    with open(GENRES_FILE) as f:
        genres: dict = json.load(f)

    print(f"reading {ALBUMS_IN}")
    with gzip.open(ALBUMS_IN, "rb") as f:
        data = json.load(f)
    albums = data.get("albums", data) if isinstance(data, dict) else data

    stats = {"track_match": 0, "album_fallback": 0, "no_genre": 0}

    for album in albums:
        path = album.get("path", "")
        track_map: dict = genres.get(path, {})
        winner = album_winner(track_map) if track_map else None

        for track in album.get("tracks", []):
            fname = track.get("file", "")
            tdata = track_map.get(fname)
            if tdata:
                gs = tdata.get("genres") or []
                top = sorted(gs, key=lambda x: x["score"], reverse=True)
                track["genre"] = top[0]["label"] if top else tdata.get("top")
                stats["track_match"] += 1
            elif winner:
                track["genre"] = winner
                stats["album_fallback"] += 1
            else:
                stats["no_genre"] += 1

    tmp = ALBUMS_OUT.with_suffix(".json.gz.tmp")
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    with gzip.open(tmp, "wb", compresslevel=6) as f:
        f.write(payload.encode())
    shutil.move(tmp, ALBUMS_OUT)

    total = stats["track_match"] + stats["album_fallback"] + stats["no_genre"]
    print(f"done — {total} tracks total")
    print(f"  {stats['track_match']:>6} direct track match")
    print(f"  {stats['album_fallback']:>6} album fallback (expanded Bandcamp albums)")
    print(f"  {stats['no_genre']:>6} no genre data")

if __name__ == "__main__":
    main()
