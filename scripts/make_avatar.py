#!/usr/bin/env python3
"""Build the dotted pixel-art avatar used in the profile header.

The header generator reads avatar/pixels.json: a grid of hex colours (or null
for transparent cells). This script writes that file in one of two ways:

  python scripts/make_avatar.py --default
      Writes the hand-drawn pixel-art man that ships with this kit.

  python scripts/make_avatar.py path/to/photo.jpg [--cols 28] [--rows 32]
      Converts your own photo into the same dotted style. Needs Pillow
      (pip install pillow). Works best with a head-and-shoulders shot on a
      plain background; the background colour is sampled from the corners and
      dropped so the portrait floats on the card.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "avatar" / "pixels.json"

# Hand-drawn pixel man, 28 x 32. One character per cell, "." is transparent.
DEFAULT_ART = [
    "............................",
    "..........hHHHHHHh..........",
    "........HHHHHHHHHHHH........",
    ".......HHHhHHHHHhHHHH.......",
    ".......HHHHHHhHHHHHHH.......",
    ".......HHHHHHHHHHHHHH.......",
    ".......HHSSSSSSSSSSHH.......",
    ".......HSSSSSSSSSSSSH.......",
    ".......HSHHHSSSSHHHSH.......",
    ".......SSSSSSSSSSSSSS.......",
    "......sSSSWESSSSWESSSs......",
    "......sSSSEESSSSEESSSs......",
    "......sSSSSSSssSSSSSSs......",
    ".......SSSSSSssSSSSSS.......",
    ".......bSSSSSSSSSSSSb.......",
    ".......BBSSSBBBBSSSBB.......",
    ".......BBBSSMMMMSSBBB.......",
    ".......BBBBBSSSSBBBBB.......",
    "........BBBBBBBBBBBB........",
    ".........BBBBBBBBBB.........",
    "..........bBBBBBBb..........",
    "...........NNNNNN...........",
    "...........NNNNNN...........",
    "........jjjTTTTTTjjj........",
    "......jJJJJjTTTTjJJJJj......",
    "....jJJJJJJJjTTjJJJJJJJj....",
    "...jJJJJJJJJJjjJJJJJJJJJj...",
    "..jJJJJJJJJJJWWJJJJJJJJJJj..",
    "..JJJJJJJJJJJWWJJJJJJJJJJJ..",
    ".JJJJJJJJJJJJJJJJJJJJJJJJJJ.",
    ".JJJJJJJJJJJJJJJJJJJJJJJJJJ.",
    ".JJJJJJJJJJJJJJJJJJJJJJJJJJ.",
]

PALETTE = {
    "H": "#2f3a48",  # hair
    "h": "#5f7590",  # hair highlight
    "S": "#e2a878",  # skin
    "s": "#b97b52",  # skin shadow
    "E": "#0b0f14",  # eye
    "W": "#e6fffb",  # eye glint / logo
    "B": "#3d2e25",  # beard
    "b": "#6e5242",  # beard fade
    "M": "#9b4f3e",  # mouth
    "N": "#b97b52",  # neck
    "T": "#0b1220",  # t-shirt
    "J": "#0f766e",  # hoodie
    "j": "#2dd4bf",  # hoodie edge light
}


def default_grid() -> list[list[str | None]]:
    width = max(len(r) for r in DEFAULT_ART)
    grid = []
    for row in DEFAULT_ART:
        row = row.ljust(width, ".")
        grid.append([PALETTE.get(ch) for ch in row])
    return grid


def photo_grid(path: Path, cols: int, rows: int, colours: int) -> list[list[str | None]]:
    try:
        from PIL import Image, ImageEnhance, ImageOps
    except ImportError:
        sys.exit("Pillow is required for photo mode: pip install pillow")

    img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    # Centre-crop to the target aspect ratio.
    target = cols / rows
    w, h = img.size
    if w / h > target:
        nw = int(h * target)
        img = img.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
    else:
        nh = int(w / target)
        img = img.crop((0, 0, w, nh))  # keep the top: faces sit high in portraits
    img = ImageEnhance.Contrast(img).enhance(1.15)
    small = img.resize((cols, rows), Image.LANCZOS)
    small = small.quantize(colors=colours, method=Image.Quantize.MEDIANCUT).convert("RGB")

    corners = [small.getpixel(p) for p in [(0, 0), (cols - 1, 0)]]

    def near_bg(px):
        return any(sum((a - b) ** 2 for a, b in zip(px, c)) < 900 for c in corners)

    grid = []
    for y in range(rows):
        row = []
        for x in range(cols):
            px = small.getpixel((x, y))
            row.append(None if near_bg(px) else "#%02x%02x%02x" % px)
        grid.append(row)
    return grid


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("photo", nargs="?", type=Path, help="portrait photo to convert")
    ap.add_argument("--default", action="store_true", help="write the bundled pixel-art man")
    ap.add_argument("--cols", type=int, default=28)
    ap.add_argument("--rows", type=int, default=32)
    ap.add_argument("--colours", type=int, default=24, help="palette size for photo mode")
    args = ap.parse_args()

    if args.default or not args.photo:
        grid = default_grid()
    else:
        grid = photo_grid(args.photo, args.cols, args.rows, args.colours)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"cols": len(grid[0]), "rows": len(grid), "pixels": grid}))
    print(f"wrote {OUT.relative_to(ROOT)} ({len(grid[0])}x{len(grid)})")


if __name__ == "__main__":
    main()
