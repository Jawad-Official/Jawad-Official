#!/usr/bin/env python3
"""Turn a portrait into the dotted halftone avatar used in the header.

  python scripts/make_avatar.py
      Uses avatar/portrait.png, the bundled illustration (source:
      avatar/portrait.svg). Eye positions are known, so the avatar blinks.

  python scripts/make_avatar.py path/to/photo.jpg [--eyes 0.40,0.37,0.60,0.37]
      Uses your own photo. Pass --eyes as normalised x,y of the left and right
      eye centres (0..1 of the image) to enable blinking. A transparent PNG
      works best; for JPGs the background colour is sampled from the top
      corners and dropped.

Writes avatar/pixels.json, read by scripts/generate.py. Needs Pillow.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "avatar" / "pixels.json"
DEFAULT = ROOT / "avatar" / "portrait.png"
DEFAULT_EYES = (97 / 270, 153 / 338, 175 / 270, 153 / 338)


def main() -> None:
    try:
        from PIL import Image, ImageOps
    except ImportError:
        sys.exit("Pillow is required: pip install pillow")

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image", nargs="?", type=Path, default=DEFAULT)
    ap.add_argument("--cols", type=int, default=48, help="dots across")
    ap.add_argument("--eyes", type=str, default=None, help="lx,ly,rx,ry normalised eye centres")
    args = ap.parse_args()

    img = ImageOps.exif_transpose(Image.open(args.image)).convert("RGBA")
    W, H = img.size
    cols = args.cols
    cell = W / cols
    rows = int(H / cell)

    has_alpha = img.getextrema()[3][0] < 250
    corners = [img.getpixel((2, 2))[:3], img.getpixel((W - 3, 2))[:3]]

    def is_bg(px):
        if has_alpha:
            return px[3] < 128
        return any(sum((a - b) ** 2 for a, b in zip(px[:3], c)) < 1200 for c in corners)

    grid: list[list[str | None]] = []
    for r in range(rows):
        row = []
        for c in range(cols):
            x0, y0 = int(c * cell), int(r * cell)
            x1, y1 = int((c + 1) * cell), int((r + 1) * cell)
            acc = [0, 0, 0]
            n = tot = 0
            for y in range(y0, y1, 2):
                for x in range(x0, x1, 2):
                    tot += 1
                    px = img.getpixel((x, y))
                    if is_bg(px):
                        continue
                    n += 1
                    for i in range(3):
                        acc[i] += px[i]
            if tot and n / tot >= 0.45:
                row.append("#%02x%02x%02x" % tuple(v // n for v in acc))
            else:
                row.append(None)
        grid.append(row)

    eyes = DEFAULT_EYES if args.eyes is None and args.image == DEFAULT else None
    if args.eyes:
        eyes = tuple(float(v) for v in args.eyes.split(","))
    blink = []
    if eyes:
        for ex, ey in ((eyes[0], eyes[1]), (eyes[2], eyes[3])):
            ec, er = int(ex * cols), int(ey * rows)
            lid = grid[min(rows - 1, er + 3)][ec] or "#d9a07a"  # skin just under the eye
            for dr in (-1, 0, 1):
                for dc in (-3, -2, -1, 0, 1, 2, 3):
                    r, c = er + dr, ec + dc
                    if 0 <= r < rows and 0 <= c < cols and grid[r][c]:
                        blink.append([r, c, lid])

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"cols": cols, "rows": rows, "pixels": grid, "blink": blink}))
    print(f"wrote {OUT.relative_to(ROOT)} ({cols}x{rows}, {len(blink)} blink dots)")


if __name__ == "__main__":
    main()
