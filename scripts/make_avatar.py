#!/usr/bin/env python3
"""Turn a portrait into the LED dot-matrix avatar used in the header.

  python scripts/make_avatar.py
      Uses avatar/portrait.png (transparent cut-out, already cropped).

  python scripts/make_avatar.py path/to/image.png --remove-bg --eyes 0.42,0.41,0.62,0.41
      Uses another image. --remove-bg flood-fills light, grey background
      (white, or a baked-in transparency checkerboard) in from the edges and
      saves the cut-out as avatar/portrait.png. --eyes is the normalised x,y
      of each eye centre in the cropped picture, used for the blink.

Styles (--style):
  dots   for pixel or dot art: average colour per cell, brightened by one
         global gain so the dark gaps between source dots do not dim it (default)
  photo  average colour per cell
  flat   dominant colour per cell (flat illustrations)

Writes avatar/pixels.json, read by scripts/generate.py. Needs Pillow.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, deque
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "avatar" / "pixels.json"
DEFAULT = ROOT / "avatar" / "portrait.png"
# Eye centres of the bundled portrait, as fractions of the cropped image.
DEFAULT_EYES = (0.384, 0.407, 0.572, 0.406)


def hexc(rgb) -> str:
    return "#%02x%02x%02x" % tuple(rgb[:3])


def lum(p) -> float:
    return 0.2126 * p[0] + 0.7152 * p[1] + 0.0722 * p[2]


def remove_background(img):
    """Flood-fill light, low-saturation pixels from the borders into transparency."""
    W, H = img.size
    px = img.load()

    def bgish(p):
        return max(p[:3]) >= 150 and max(p[:3]) - min(p[:3]) <= 22

    seen = bytearray(W * H)
    q = deque([(x, y) for x in range(W) for y in (0, H - 1)] + [(x, y) for y in range(H) for x in (0, W - 1)])
    while q:
        x, y = q.popleft()
        i = y * W + x
        if seen[i] or not bgish(px[x, y]):
            continue
        seen[i] = 1
        if x > 0: q.append((x - 1, y))
        if x < W - 1: q.append((x + 1, y))
        if y > 0: q.append((x, y - 1))
        if y < H - 1: q.append((x, y + 1))
    for y in range(H):
        for x in range(W):
            if seen[y * W + x]:
                r, g, b, _ = px[x, y]
                px[x, y] = (r, g, b, 0)
    return img


def auto_crop(img, aspect: float):
    """Crop to the subject: small headroom on top, bottom kept, centred on the head."""
    W, H = img.size
    alpha = img.getchannel("A")
    l, t, r, b = alpha.getbbox()
    head_rows = t + int((b - t) * 0.45)
    px = alpha.load()
    xs = [x for y in range(t, head_rows, 4) for x in range(l, r, 4) if px[x, y] > 128]
    cx = sum(xs) / len(xs) if xs else (l + r) / 2
    top = max(0, t - int((b - t) * 0.02))
    height = b - top
    width = height * aspect
    left = int(max(0, min(W - width, cx - width / 2)))
    return img.crop((left, top, int(left + width), b))


def main() -> None:
    try:
        from PIL import Image, ImageOps
    except ImportError:
        sys.exit("Pillow is required: pip install pillow")

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image", nargs="?", type=Path, default=DEFAULT)
    ap.add_argument("--cols", type=int, default=72, help="LEDs across")
    ap.add_argument("--rows", type=int, default=86, help="LEDs down")
    ap.add_argument("--style", choices=["dots", "photo", "flat"], default="dots")
    ap.add_argument("--remove-bg", action="store_true", help="cut out a light or checkerboard background")
    ap.add_argument("--eyes", type=str, default=None, help="lx,ly,rx,ry normalised eye centres")
    args = ap.parse_args()
    bundled = args.image.resolve() == DEFAULT.resolve()

    img = ImageOps.exif_transpose(Image.open(args.image)).convert("RGBA")
    if args.remove_bg:
        img = auto_crop(remove_background(img), args.cols / args.rows)
        img.save(DEFAULT)
        print(f"saved cut-out to {DEFAULT.relative_to(ROOT)} ({img.size[0]}x{img.size[1]})")

    W, H = img.size
    cols, rows = args.cols, args.rows
    cw, ch = W / cols, H / rows
    px = img.load()

    grid: list[list] = []
    ratios: list[float] = []
    for r in range(rows):
        row = []
        for c in range(cols):
            x0, y0 = int(c * cw), int(r * ch)
            x1, y1 = min(W, int((c + 1) * cw)), min(H, int((r + 1) * ch))
            samples = [px[x, y] for y in range(y0, y1) for x in range(x0, x1)]
            fg = [p for p in samples if p[3] >= 128]
            if not samples or len(fg) / len(samples) < 0.5:
                row.append(None)
                continue
            if args.style == "dots":
                # mean keeps thin dark features (outlines, moustache); the gain below
                # undoes the dimming from the dark gaps between the source dots
                fg.sort(key=lum)
                top = fg[len(fg) // 2:]
                mean = [sum(p[i] for p in fg) / len(fg) for i in range(3)]
                bright = [sum(p[i] for p in top) / len(top) for i in range(3)]
                ratios.append(lum(bright) / max(1.0, lum(mean)))
                row.append(mean)
            elif args.style == "flat":
                row.append(hexc(Counter(p[:3] for p in fg).most_common(1)[0][0]))
            else:
                row.append(hexc([sum(p[i] for p in fg) // len(fg) for i in range(3)]))
        grid.append(row)

    if args.style == "dots" and ratios:
        gain = min(1.5, sorted(ratios)[len(ratios) // 2] * 0.85)

        def lift(c):  # scale all channels together so bright colours keep their hue
            k = min(gain, 255 / max(1.0, max(c)))
            return hexc([int(v * k) for v in c])
        grid = [[lift(c) if isinstance(c, list) else c for c in row] for row in grid]

    eyes = tuple(float(v) for v in args.eyes.split(",")) if args.eyes else (DEFAULT_EYES if bundled else None)
    blink = []
    if eyes:
        for ex, ey in ((eyes[0], eyes[1]), (eyes[2], eyes[3])):
            ec, er = int(ex * cols), int(ey * rows)
            skin = grid[min(rows - 1, er + 4)][ec] or "#e8ad84"
            lash = "#2a1d1a"
            for dr in (-2, -1, 0, 1, 2):
                for dc in range(-4, 5):
                    r, c = er + dr, ec + dc
                    if 0 <= r < rows and 0 <= c < cols and grid[r][c]:
                        closed_line = dr == 1 and abs(dc) <= 3
                        blink.append([r, c, lash if closed_line else skin])

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"cols": cols, "rows": rows, "pixels": grid, "blink": blink}))
    print(f"wrote {OUT.relative_to(ROOT)} ({cols}x{rows}, {args.style}, {len(blink)} blink dots)")


if __name__ == "__main__":
    main()
