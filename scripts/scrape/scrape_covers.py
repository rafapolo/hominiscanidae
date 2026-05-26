#!/usr/bin/env python3
"""
Scrape cover images from posts/*.md, resize to 500x500 with title overlay,
save to /Volumes/EXTRA/hominiscanidae/covers/{slug}.jpg
"""

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps

POSTS_DIR = Path("/Users/polux/Projetos/hominiscanidae/posts")
COVERS_DIR = Path("/Volumes/EXTRA/hominiscanidae/covers")
POSTS_JSON = Path("/Users/polux/Projetos/hominiscanidae/posts.json")
WORKERS = 64
SIZE = (500, 500)

IMG_LINK_RE = re.compile(r'\[!\[[^\]]*\]\([^)]+\)\]\(([^)]+)\)')

FONT = None
for _fp in [
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
]:
    if os.path.exists(_fp):
        try:
            FONT = ImageFont.truetype(_fp, 13)
            break
        except Exception:
            pass
if FONT is None:
    FONT = ImageFont.load_default()


def upgrade_url(url):
    return re.sub(r'/s\d+/', '/s1600/', url)


def extract_cover_url(md_path):
    text = md_path.read_text(errors="replace")
    m = IMG_LINK_RE.search(text)
    return upgrade_url(m.group(1)) if m else None


def add_title_overlay(img, title):
    draw = ImageDraw.Draw(img)
    max_width = img.width - 10
    words = title.split()
    lines, current = [], ""
    for word in words:
        test = (current + " " + word).strip()
        bbox = draw.textbbox((0, 0), test, font=FONT)
        if bbox[2] > max_width and current:
            lines.append(current)
            current = word
        else:
            current = test
    if current:
        lines.append(current)

    line_h = 17
    banner_h = line_h * len(lines) + 8
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    y0 = img.height - banner_h
    odraw.rectangle([(0, y0), (img.width, img.height)], fill=(0, 0, 0, 185))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")

    draw = ImageDraw.Draw(img)
    y = img.height - banner_h + 4
    for line in lines:
        draw.text((5, y), line, fill=(255, 255, 255), font=FONT)
        y += line_h
    return img


def process(slug, url, title):
    out = COVERS_DIR / f"{slug}.jpg"
    if out.exists():
        return "skip"
    try:
        resp = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        img = Image.open(BytesIO(resp.content)).convert("RGB")
        img = ImageOps.fit(img, SIZE, method=Image.LANCZOS)
        if title:
            img = add_title_overlay(img, title)
        img.save(out, "JPEG", quality=90)
        return "ok"
    except Exception as e:
        return f"err: {e}"


def main():
    COVERS_DIR.mkdir(parents=True, exist_ok=True)

    posts = json.loads(POSTS_JSON.read_text())
    slug_to_title = {}
    for p in posts:
        url = p.get("url", "")
        slug = url.rstrip("/").split("/")[-1].replace(".html", "")
        slug_to_title[slug] = p.get("title", "")

    tasks = []
    for md in sorted(POSTS_DIR.glob("*.md")):
        url = extract_cover_url(md)
        if url:
            tasks.append((md.stem, url, slug_to_title.get(md.stem, "")))

    total = len(tasks)
    print(f"Posts with cover: {total}")

    done = skip = err = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures = {ex.submit(process, s, u, t): s for s, u, t in tasks}
        for i, fut in enumerate(as_completed(futures), 1):
            result = fut.result()
            if result == "ok":
                done += 1
            elif result == "skip":
                skip += 1
            else:
                err += 1
            if i % 200 == 0 or i == total:
                pct = i / total * 100
                print(f"[{i}/{total} {pct:.1f}%] done={done} skip={skip} err={err}", flush=True)

    print(f"\nDone. downloaded={done} skipped={skip} errors={err}")


if __name__ == "__main__":
    main()
