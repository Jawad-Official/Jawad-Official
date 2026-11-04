#!/usr/bin/env python3
"""Turn a portrait into the LED dot-matrix avatar used in the header.

  python scripts/make_avatar.py
      Uses avatar/portrait.png, the bundled flat illustration (source:
      avatar/portrait.svg, cropped to the head and shoulders). Each dot takes the
      dominant flat colour of its cell, and outlines win ties, so edges stay
      crisp. Eye positions are known, so the avatar blinks.

  python scripts/make_avatar.py path/to/photo.png --style photo [--eyes 0.40,0.45,0.60,0.45]
      Uses your own photo: each dot is the average colour of its cell.
      --eyes is the normalised x,y of each eye centre (0..1), for the blink.
      A transparent PNG cut-out works best; for JPGs the background colour is
      sampled from the top corners and dropped.

Writes avatar/pixels.json, read by scripts/generate.py. Needs Pillow.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "avatar" / "pixels.json"
DEFAULT = ROOT / "avatar" / "portrait.png"
DEFAULT_EYES = ((132 - 35) / 250, (171 - 26) / 301, (188 - 35) / 250, (171 - 26) / 301)
OUTLINE = (0x1C, 0x16, 0x26)
EYE_COLOURS = {"#f6f1ec", "#7a4a2c", "#ffffff", "#1c1626"}


def hexc(rgb) -> str:
    return "#%02x%02x%02x" % tuple(rgb[:3])


def main() -> None:
    try:
        from PIL import Image, ImageOps
    except ImportError:
        sys.exit("Pillow is required: pip install pillow")

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image", nargs="?", type=Path, default=DEFAULT)
    ap.add_argument("--cols", type=int, default=64, help="dots across")
    ap.add_argument("--style", choices=["flat", "photo"], default=None,
                    help="flat: dominant colour per dot (illustrations); photo: average colour")
    ap.add_argument("--eyes", type=str, default=None, help="lx,ly,rx,ry normalised eye centres")
    args = ap.parse_args()
    bundled = args.image.resolve() == DEFAULT.resolve()
    style = args.style or ("flat" if bundled else "photo")

    img = ImageOps.exif_transpose(Image.open(args.image)).convert("RGBA")
    W, H = img.size
    cols = args.cols
    cell = W / cols
    rows = int(round(H / cell))
    px = img.load()

    has_alpha = img.getextrema()[3][0] < 250
    corners = [px[2, 2][:3], px[W - 3, 2][:3]]

    def is_bg(p):
        if has_alpha:
            return p[3] < 128
        return any(sum((a - b) ** 2 for a, b in zip(p[:3], c)) < 1200 for c in corners)

    grid: list[list[str | None]] = []
    for r in range(rows):
        row = []
        for c in range(cols):
            x0, y0 = int(c * cell), int(r * cell)
            x1, y1 = min(W, int((c + 1) * cell)), min(H, int((r + 1) * cell))
            samples = [px[x, y] for y in range(y0, y1, 2) for x in range(x0, x1, 2)]
            fg = [p for p in samples if not is_bg(p)]
            if not samples or len(fg) / len(samples) < 0.5:
                row.append(None)
                continue
            if style == "flat":
                dark = sum(1 for p in fg if sum(abs(a - b) for a, b in zip(p[:3], OUTLINE)) < 24)
                if dark / len(fg) >= 0.3:
                    row.append(hexc(OUTLINE))
                else:
                    row.append(hexc(Counter(p[:3] for p in fg).most_common(1)[0][0]))
            else:
                n = len(fg)
                row.append(hexc([sum(p[i] for p in fg) // n for i in range(3)]))
        grid.append(row)

    eyes = DEFAULT_EYES if (args.eyes is None and bundled) else None
    if args.eyes:
        eyes = tuple(float(v) for v in args.eyes.split(","))
    blink = []
    if eyes:
        for ex, ey in ((eyes[0], eyes[1]), (eyes[2], eyes[3])):
            ec, er = int(ex * cols), int(ey * rows)
            skin = grid[min(rows - 1, er + 3)][ec] or "#e8ad84"
            for dr in (-2, -1, 0, 1):
                for dc in range(-4, 5):
                    r, c = er + dr, ec + dc
                    if not (0 <= r < rows and 0 <= c < cols) or not grid[r][c]:
                        continue
                    if style == "flat" and grid[r][c] not in EYE_COLOURS:
                        continue
                    lid = r == er and abs(dc) <= 3
                    blink.append([r, c, hexc(OUTLINE) if lid else skin])

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"cols": cols, "rows": rows, "pixels": grid, "blink": blink}))
    print(f"wrote {OUT.relative_to(ROOT)} ({cols}x{rows}, {style}, {len(blink)} blink dots)")


if __name__ == "__main__":
    main()
