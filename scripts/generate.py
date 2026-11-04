#!/usr/bin/env python3
"""Render the profile dashboard SVGs from live GitHub data.

Outputs (in assets/):
  header.svg     identity, live readouts, halftone portrait
  city.svg       isometric contribution city for the last year
  panels.svg     language stack + selected work
  btn-*.svg      link buttons

Usage:
  GH_TOKEN=... python scripts/generate.py      # live data (used by the Action)
  python scripts/generate.py --demo            # sample data, no token needed

Standard library only, so the Action needs no pip install.
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import os
import random
import struct
import sys
import urllib.request
import zlib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"

# ------------------------------------------------------------------ theme
BG0 = "#080b10"   # card
BG1 = "#0d1219"   # inset surfaces
LINE = "#1b2430"  # hairlines
LINE2 = "#263243"
INK = "#e8edf2"
DIM = "#8794a5"
FAINT = "#4f5b6b"
ACC = "#3ee6c1"   # mint accent
MINT = "#a5fbe6"
WARM = "#ffb454"  # award / peak
LIVE = "#4ade80"
SANS = "-apple-system, 'Segoe UI', Ubuntu, 'Helvetica Neue', Arial, sans-serif"
MONO = "'JetBrains Mono', 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace"

PAD = -4  # cards sit 10 px inset in their canvas; -4 leaves 6 px, so stacked cards end up ~10 px apart on GitHub
GAP = 12  # space between neighbouring cards; renders ~10 px on GitHub, matching the vertical gaps
IN_L, IN_R = 40, 840  # inner content edges shared by every card (30 px card padding)

CITY_LEVELS = ["#11242c", "#0e5a50", "#119482", "#22c7a6", "#7ff5d8"]

LANG_FALLBACK = {
    "Python": "#3572A5", "TypeScript": "#3178c6", "JavaScript": "#f1e05a",
    "Jupyter Notebook": "#DA5B0B", "Markdown": "#083fa1", "Rust": "#dea584",
}

BASE_CSS = """
.fu{animation:fu .9s cubic-bezier(.2,.8,.2,1) both}
@keyframes fu{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
.fi{animation:fi 1s ease-out both}
@keyframes fi{from{opacity:0}to{opacity:1}}
.cur{animation:blink 1.05s step-end infinite}
@keyframes blink{50%{opacity:0}}
.pulse{animation:pulse 2.2s ease-in-out infinite}
@keyframes pulse{50%{opacity:.35}}
.ring{transform-box:fill-box;transform-origin:center;animation:ring 2.2s ease-out infinite}
@keyframes ring{from{transform:scale(1);opacity:.8}to{transform:scale(3.2);opacity:0}}
.gx{transform-box:fill-box;transform-origin:0 50%;animation:gx 1.4s cubic-bezier(.2,.8,.2,1) both}
@keyframes gx{from{transform:scaleX(0)}to{transform:scaleX(1)}}
.gy{transform-box:fill-box;transform-origin:50% 100%;animation:gy 1.1s cubic-bezier(.2,.8,.2,1) both}
@keyframes gy{from{transform:scaleY(0)}to{transform:scaleY(1)}}
"""


# ------------------------------------------------------------------ data
GRAPHQL = "https://api.github.com/graphql"

USER_QUERY = """
query($login: String!) {
  user(login: $login) {
    followers { totalCount }
    repositories(ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC, first: 100) {
      totalCount
      nodes {
        name
        stargazerCount
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } }
        }
      }
    }
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks { contributionDays { contributionCount date weekday } }
      }
    }
  }
}
"""

REPO_FRAGMENT = """
  r%d: repository(owner: "%s", name: "%s") {
    name description stargazerCount pushedAt isPrivate
    primaryLanguage { name color }
    languages(first: 6, orderBy: {field: SIZE, direction: DESC}) {
      totalSize edges { size node { name color } }
    }
  }
"""


def gql(token: str, query: str, variables: dict | None = None) -> dict:
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(
        GRAPHQL, data=body,
        headers={"Authorization": f"bearer {token}", "Content-Type": "application/json",
                 "User-Agent": "profile-dashboard"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.load(resp)
    for err in payload.get("errors") or []:
        # A missing or private featured repo is reported here; keep going with the rest.
        print(f"warning: {err.get('message')}", file=sys.stderr)
    if not payload.get("data"):
        sys.exit("GraphQL returned no data.")
    return payload["data"]


def fetch_live(cfg: dict, token: str) -> dict:
    login = cfg["username"]
    user = gql(token, USER_QUERY, {"login": login})["user"]
    if not user:
        sys.exit(f"User {login} not found.")

    featured_cfg = cfg.get("featured", [])
    repos_raw = {}
    if featured_cfg:
        q = "query {" + "".join(
            REPO_FRAGMENT % (i, *(f["repo"].split("/", 1) if "/" in f["repo"] else (login, f["repo"])))
            for i, f in enumerate(featured_cfg)
        ) + "}"
        repos_raw = gql(token, q)

    days = [
        {"date": d["date"], "count": d["contributionCount"], "weekday": d["weekday"]}
        for w in user["contributionsCollection"]["contributionCalendar"]["weeks"]
        for d in w["contributionDays"]
    ]

    skip = {r.lower() for r in cfg.get("exclude_repos", [])}
    lang_bytes: dict[str, int] = {}
    lang_color: dict[str, str] = {}
    stars = repos = 0
    for repo in user["repositories"]["nodes"]:
        if repo["name"].lower() in skip:
            continue
        repos += 1
        stars += repo["stargazerCount"]
        for edge in repo["languages"]["edges"]:
            n = edge["node"]["name"]
            lang_bytes[n] = lang_bytes.get(n, 0) + edge["size"]
            if edge["node"]["color"]:
                lang_color[n] = edge["node"]["color"]

    featured = []
    for i, f in enumerate(featured_cfg):
        r = repos_raw.get(f"r{i}")
        if not r or r.get("isPrivate"):
            print(f"warning: featured repo {f['repo']} is private or missing, skipped", file=sys.stderr)
            continue
        prim = r["primaryLanguage"] or {"name": "n/a", "color": FAINT}
        total = r["languages"]["totalSize"] or 1
        featured.append({
            "name": r["name"],
            "description": f.get("description") or r["description"] or "",
            "tags": f.get("tags", []),
            "stars": r["stargazerCount"],
            "pushed": r["pushedAt"],
            "language": prim["name"],
            "color": prim["color"] or FAINT,
            "mix": [(e["node"]["name"], e["node"]["color"] or FAINT, e["size"] / total)
                    for e in r["languages"]["edges"]],
        })

    return {"repos": repos, "stars": stars, "followers": user["followers"]["totalCount"],
            "days": days, "lang_bytes": lang_bytes, "lang_color": lang_color, "featured": featured}


def fetch_demo(cfg: dict) -> dict:
    """Deterministic sample data so the layout can be previewed offline."""
    rng = random.Random(7)
    end = date.today()
    start = end - timedelta(days=364 + (end.weekday() + 1) % 7)
    days, d = [], start
    while d <= end:
        wd = (d.weekday() + 1) % 7
        burst = 1.0 + 1.6 * math.sin((d - start).days / 40) ** 2
        count = 0 if rng.random() < 0.38 else int(rng.expovariate(1 / (3.5 * burst)))
        if wd in (5, 6) and rng.random() < 0.5:
            count //= 2
        days.append({"date": d.isoformat(), "count": count, "weekday": wd})
        d += timedelta(days=1)
    now = datetime.now(timezone.utc)
    mixes = [[("TypeScript", "#3178c6", .78), ("Python", "#3572A5", .2), ("CSS", "#663399", .02)],
             [("TypeScript", "#3178c6", .62), ("Python", "#3572A5", .36), ("Mako", "#7e858d", .02)],
             [("TypeScript", "#3178c6", .9), ("CSS", "#663399", .1)],
             [("Markdown", "#083fa1", .7), ("Python", "#3572A5", .3)]]
    featured = []
    for f, mix in zip(cfg["featured"], mixes):
        featured.append({
            "name": f["repo"].split("/")[-1], "description": f.get("description", ""),
            "tags": f.get("tags", []), "stars": rng.randint(0, 4), "language": mix[0][0],
            "color": mix[0][1], "mix": mix,
            "pushed": (now - timedelta(days=rng.randint(0, 40))).isoformat(),
        })
    return {"repos": 5, "stars": 6, "followers": 0, "days": days,
            "lang_bytes": {"TypeScript": 4_900_000, "Python": 1_700_000, "Markdown": 260_000,
                           "JavaScript": 120_000, "HTML": 800_000},
            "lang_color": {"TypeScript": "#3178c6", "Python": "#3572A5", "JavaScript": "#f1e05a",
                           "Markdown": "#083fa1"},
            "featured": featured}


# ------------------------------------------------------------------ helpers
def esc(s) -> str:
    return escape(str(s), {'"': "&quot;"})


def fmt(n: int) -> str:
    return f"{n/1000:.1f}k" if n >= 10_000 else f"{n:,}"


def tw(s: str, size: float, mono: bool = False) -> float:
    """Approximate text width; an SVG inside <img> cannot measure fonts."""
    return len(s) * size * (0.6 if mono else 0.55)


def shade(hex_color: str, k: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(c * k))) for c in (r, g, b))


def lum(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def mix(a: str, b: str, t: float) -> str:
    pa = [int(a.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    pb = [int(b.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    return "#%02x%02x%02x" % tuple(int(x + (y - x) * t) for x, y in zip(pa, pb))


def wrap(s: str, width: int, lines: int) -> list[str]:
    out, cur = [], ""
    for word in s.split():
        if len(cur) + len(word) + (1 if cur else 0) <= width:
            cur = f"{cur} {word}".strip()
        else:
            out.append(cur)
            cur = word
    if cur:
        out.append(cur)
    if len(out) > lines:
        out = out[:lines]
        out[-1] = out[-1][: width - 1].rstrip(" .,:") + "…"
    return out


def ago(iso: str) -> str:
    then = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    days = (datetime.now(timezone.utc) - then).days
    if days <= 0:
        return "today"
    if days < 30:
        return f"{days}d ago"
    if days < 365:
        return f"{days // 30}mo ago"
    return f"{days // 365}y ago"


def size_str(b: int) -> str:
    return f"{b/1_000_000:.1f} MB" if b >= 1_000_000 else f"{b/1000:.0f} KB"


def streaks(days: list[dict]) -> tuple[int, int]:
    longest = run = 0
    for d in days:
        run = run + 1 if d["count"] else 0
        longest = max(longest, run)
    seq = days[:-1] if days and days[-1]["count"] == 0 else days  # today may not be done yet
    cur = 0
    for d in reversed(seq):
        if not d["count"]:
            break
        cur += 1
    return cur, longest


class Svg:
    """Tiny builder that collects CSS, defs and body for one SVG file."""

    _uid = 0

    def __init__(self, w: int, h: int, title: str, pad: int = 0):
        self.w, self.h, self.title, self.pad = w, h, title, pad
        self.css = [BASE_CSS]
        self.defs: list[str] = []
        self.body: list[str] = []

    def uid(self, p: str = "u") -> str:
        Svg._uid += 1
        return f"{p}{Svg._uid}"

    def add(self, *parts: str) -> None:
        self.body.extend(parts)

    def render(self) -> str:
        # Transparent margin above and below so stacked cards breathe in the README.
        h = self.h + 2 * self.pad
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{h}" '
            f'viewBox="0 0 {self.w} {h}" role="img" aria-label="{esc(self.title)}">\n'
            f"<title>{esc(self.title)}</title>\n<style>{''.join(self.css)}</style>\n"
            f"<defs>{''.join(self.defs)}</defs>\n"
            f'<g transform="translate(0,{self.pad})">\n' + "\n".join(self.body) + "\n</g>\n</svg>\n"
        )

    # -------- shared pieces
    def card(self, x, y, w, h) -> None:
        pid = self.uid("dots")
        self.defs.append(
            f'<pattern id="{pid}" width="16" height="16" patternUnits="userSpaceOnUse">'
            f'<circle cx="1" cy="1" r=".8" fill="#ffffff" fill-opacity=".05"/></pattern>')
        self.add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="{BG0}" stroke="{LINE2}"/>',
                 f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="url(#{pid})"/>')
        k, inset = 12, 10  # corner brackets sit 10 px inside the card edge
        for cx, cy, sx, sy in [(x, y, 1, 1), (x + w, y, -1, 1), (x, y + h, 1, -1), (x + w, y + h, -1, -1)]:
            self.add(f'<path d="M{cx + sx * inset},{cy + sy * (k + inset)} V{cy + sy * inset} H{cx + sx * (k + inset)}" '
                     f'fill="none" stroke="{ACC}" stroke-width="1.6" stroke-opacity=".8"/>')

    def heading(self, x, y, fig: str, title: str, right: str = "", right_x: float | None = None) -> None:
        self.add(f'<text x="{x}" y="{y}" font-family="{MONO}" font-size="10.5" letter-spacing="1.6" fill="{ACC}">{esc(fig)}</text>',
                 f'<text x="{x + tw(fig, 10.5, True) + 22}" y="{y + 1}" font-family="{SANS}" font-size="16" font-weight="650" fill="{INK}">{esc(title)}</text>')
        if right:
            self.add(f'<text x="{right_x}" y="{y}" text-anchor="end" font-family="{MONO}" font-size="10" letter-spacing=".6" fill="{DIM}">{right}</text>')

    def hline(self, x1, x2, y, dash: bool = False) -> None:
        d = ' stroke-dasharray="2 4"' if dash else ""
        self.add(f'<path d="M{x1},{y} H{x2}" stroke="{LINE2}"{d}/>')

    def odometer(self, x, y, value: str, size: float, color: str, delay: float, weight: int = 700) -> float:
        """Rolling digits. Returns the x where the number ends."""
        cw, lh = size * 0.6, size * 1.2
        cx = x
        for i, ch in enumerate(value):
            if ch.isdigit():
                d = int(ch)
                cid, kid = self.uid("oc"), self.uid("ok")
                self.defs.append(f'<clipPath id="{cid}"><rect x="{cx - 1:.1f}" y="{y - size * .95:.1f}" width="{cw + 2:.1f}" height="{lh:.1f}"/></clipPath>')
                self.css.append(f"@keyframes {kid}{{from{{transform:translateY(0)}}to{{transform:translateY(-{(10 + d) * lh:.1f}px)}}}}")
                col = "".join(f'<tspan x="{cx:.1f}" y="{y + k * lh:.1f}">{k % 10}</tspan>' for k in range(20))
                self.add(f'<g clip-path="url(#{cid})"><g style="animation:{kid} {1.5 + i * .12:.2f}s cubic-bezier(.15,.8,.2,1) {delay:.2f}s both">'
                         f'<text font-family="{MONO}" font-size="{size}" font-weight="{weight}" fill="{color}">{col}</text></g></g>')
            else:
                self.add(f'<text x="{cx:.1f}" y="{y}" font-family="{MONO}" font-size="{size}" font-weight="{weight}" fill="{color}">{esc(ch)}</text>')
            cx += cw
        return cx


# ------------------------------------------------------------------ header
def render_header(cfg: dict, data: dict) -> str:
    W, H = 880, 340
    X0, Y0, CW, CH = 10, 10, 860, 320
    days = data["days"]
    total = sum(d["count"] for d in days)
    active = sum(1 for d in days if d["count"])
    s = Svg(W, H, f"{cfg['name']}, {cfg.get('role', '')}", PAD)
    s.card(X0, Y0, CW, CH)

    # ---- top strip
    s.add(f'<circle class="ring" cx="{IN_L + 6}" cy="31" r="3.5" fill="none" stroke="{ACC}"/>',
          f'<circle cx="{IN_L + 6}" cy="31" r="3.5" fill="{ACC}"/>',
          f'<text x="{IN_L + 18}" y="35" font-family="{MONO}" font-size="10" letter-spacing="1.6" fill="{ACC}">LIVE</text>',
          f'<text x="{IN_L + 56}" y="35" font-family="{MONO}" font-size="10" letter-spacing=".6" fill="{DIM}">{esc(cfg["username"].lower())} / profile.readme</text>')
    right = f'{esc(cfg.get("coords", ""))}  ·  {esc(cfg.get("location", "").upper())}  ·  SYNCED {date.today():%d %b %Y}'.upper()
    s.add(f'<text x="{IN_R}" y="35" text-anchor="end" font-family="{MONO}" font-size="10" letter-spacing=".6" fill="{DIM}">{right}</text>')
    s.hline(X0 + 1, X0 + CW - 1, 50)

    # ---- column grid: identity | readouts | portrait, 16 px gutters around each divider
    TOP, BOT = 66, 314
    L, L_END = IN_L, 452
    D1, RX, R_END, D2 = 470, 486, 616, 632
    PX0, PW_ = 648, IN_R - 648

    # ---- identity column
    s.add(f'<text class="fi" x="{L}" y="86" font-family="{MONO}" font-size="10.5" letter-spacing="2" fill="{ACC}">{esc(cfg.get("role", ""))}</text>')
    name = cfg["name"]
    s.css.append(".ch{animation:ch .6s cubic-bezier(.2,.8,.2,1) both}"
                 "@keyframes ch{0%{opacity:0;fill:" + ACC + "}60%{opacity:1;fill:" + ACC + "}100%{opacity:1;fill:" + INK + "}}")
    spans = "".join(f'<tspan class="ch" style="animation-delay:{.25 + i * .045:.3f}s">{esc(c)}</tspan>' for i, c in enumerate(name))
    dot = f'<tspan class="pulse" fill="{ACC}">.</tspan>'
    s.add(f'<text x="{L - 2}" y="136" font-family="{SANS}" font-size="44" font-weight="750" letter-spacing="-1" fill="{INK}">{spans}{dot}</text>')

    tag = "> " + cfg.get("tagline", "")
    twidth = tw(tag, 13, True)
    cid = s.uid("type")
    s.css.append(f"@keyframes {cid}k{{from{{width:0}}to{{width:{twidth + 4:.0f}px}}}}")
    s.defs.append(f'<clipPath id="{cid}"><rect x="{L}" y="154" height="20" width="0" style="animation:{cid}k 2.6s steps({len(tag)}) 1s both"/></clipPath>')
    s.add(f'<g clip-path="url(#{cid})"><text x="{L}" y="169" font-family="{MONO}" font-size="13" fill="{DIM}">{esc(tag)}</text></g>',
          f'<rect class="cur" x="{L + twidth + 4:.0f}" y="158" width="7" height="14" fill="{ACC}"/>')

    for i, f in enumerate(cfg.get("facts", [])[:3]):
        y = 204 + i * 30
        tone = f.get("tone")
        color = WARM if tone == "warm" else INK
        s.add(f'<g class="fu" style="animation-delay:{1.2 + i * .15:.2f}s">')
        s.add(f'<text x="{L}" y="{y}" font-family="{MONO}" font-size="9.5" letter-spacing="1.6" fill="{FAINT}">{esc(f["key"])}</text>')
        vx = L + 76
        if tone == "live":
            s.add(f'<circle class="ring" cx="{vx + 4}" cy="{y - 4}" r="3" fill="none" stroke="{LIVE}"/>',
                  f'<circle cx="{vx + 4}" cy="{y - 4}" r="3" fill="{LIVE}"/>')
            vx += 14
        s.add(f'<text x="{vx}" y="{y}" font-family="{SANS}" font-size="13" fill="{color}">{esc(f["value"])}</text>')
        s.add("</g>")
        s.hline(L, L_END, y + 11, dash=True)

    parts = []
    for i, item in enumerate(cfg.get("stack", [])):
        if i:
            parts.append(f'<tspan fill="{ACC}">  /  </tspan>')
        parts.append(f"<tspan>{esc(item)}</tspan>")
    s.add(f'<text class="fi" style="animation-delay:1.8s" x="{L}" y="{BOT - 8}" font-family="{MONO}" font-size="11" fill="{DIM}">{"".join(parts)}</text>')

    # ---- readouts column
    s.add(f'<path d="M{D1},{TOP} V{BOT}" stroke="{LINE2}"/>', f'<path d="M{D2},{TOP} V{BOT}" stroke="{LINE2}"/>')
    weeks = [sum(d["count"] for d in days[i:i + 7]) for i in range(0, len(days), 7)][-20:]
    stats = [("CONTRIBUTIONS · 1Y", total), ("ACTIVE DAYS", active),
             ("PUBLIC REPOS", data["repos"]), ("STARS EARNED", data["stars"])]
    row_h = (BOT - TOP) / 4
    for i, (label, val) in enumerate(stats):
        y = TOP + i * row_h
        s.add(f'<text x="{RX}" y="{y + 18}" font-family="{MONO}" font-size="9" letter-spacing="1.4" fill="{FAINT}">{label}</text>')
        end = s.odometer(RX, y + 46, fmt(val), 24, INK, .5 + i * .15)
        if i == 0 and weeks:
            mx = max(weeks) or 1
            gw, gh = 44, 18
            gx0 = R_END - gw
            step = gw / max(1, len(weeks) - 1)
            pts = " ".join(f"{gx0 + j * step:.1f},{y + 46 - gh * v / mx:.1f}" for j, v in enumerate(weeks))
            plen = gw * 2.4
            s.css.append(f".spark{{stroke-dasharray:{plen:.0f};animation:spark 2s ease-out 1s both}}@keyframes spark{{from{{stroke-dashoffset:{plen:.0f}}}to{{stroke-dashoffset:0}}}}")
            s.add(f'<polyline class="spark" points="{pts}" fill="none" stroke="{ACC}" stroke-width="1.5" stroke-linejoin="round"/>')
            lx, ly = pts.split()[-1].split(",")
            s.add(f'<circle class="ring" cx="{lx}" cy="{ly}" r="2" fill="none" stroke="{ACC}"/>',
                  f'<circle cx="{lx}" cy="{ly}" r="2" fill="{ACC}"/>')
        if i < 3:
            s.hline(RX, R_END, y + row_h)

    # ---- portrait
    s.add(render_portrait(s, PX0, TOP, PW_, BOT - TOP))
    return s.render()


def png_rgba(width: int, height: int, rows: list[bytes]) -> bytes:
    """Minimal PNG encoder (8-bit RGBA) so the Action needs no Pillow."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + r for r in rows)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def render_portrait(s: Svg, x0: float, y0: float, w: float, h: float) -> str:
    """LED dot-matrix portrait on a dark, starry frame. Only the figure is lit; stars drift behind it."""
    out = [f'<rect x="{x0}" y="{y0}" width="{w}" height="{h}" rx="10" fill="#06080d" stroke="{LINE2}"/>',
           f'<text x="{x0 + 12}" y="{y0 + 18}" font-family="{MONO}" font-size="8.5" letter-spacing="1.4" fill="{FAINT}">FIG. 0 — PORTRAIT</text>']
    path = ROOT / "avatar" / "pixels.json"
    if not path.exists():
        out.append(f'<text x="{x0 + w / 2}" y="{y0 + h / 2}" text-anchor="middle" font-family="{MONO}" font-size="10" fill="{DIM}">run make_avatar.py</text>')
        return "\n".join(out)
    av = json.loads(path.read_text())
    cols, prow, px = av["cols"], av["rows"], av["pixels"]
    mx, mw = x0 + 8, w - 16
    cell = mw / cols
    rows = max(prow, int((h - 36) / cell))
    mh = rows * cell
    my = y0 + h - 8 - mh
    off = rows - prow  # figure sits on the bottom edge
    out.append(f'<text x="{x0 + w - 12}" y="{y0 + 18}" text-anchor="end" font-family="{MONO}" font-size="8.5" fill="{FAINT}">{cols}×{prow} LED</text>')

    # ---- stars drifting slowly behind the figure
    frame_clip = s.uid("fc")
    s.defs.append(f'<clipPath id="{frame_clip}"><rect x="{x0 + 1}" y="{y0 + 26}" width="{w - 2}" height="{h - 27}" rx="9"/></clipPath>')
    rng = random.Random(23)
    palette = ["#ffffff", "#ffffff", "#ffd36e", "#7ab8ff", "#ff9fcb", ACC, "#c39bff"]
    drifts = [(-34, 10), (-26, -8), (-40, 4), (-20, 14)]
    for k, (dx, dy) in enumerate(drifts):
        s.css.append(f"@keyframes dr{k}{{0%{{transform:translate(0,0);opacity:0}}12%{{opacity:1}}88%{{opacity:1}}"
                     f"100%{{transform:translate({dx}px,{dy}px);opacity:0}}}}")
    s.css.append(".tw{animation:tw 3s ease-in-out infinite}@keyframes tw{0%,100%{opacity:.25}50%{opacity:1}}")
    stars = []
    for n in range(30):
        sx = rng.uniform(x0 + 10, x0 + w - 6)
        sy = rng.uniform(y0 + 30, y0 + h - 10)
        col = rng.choice(palette)
        dur = rng.uniform(16, 30)
        drift = f"animation:dr{rng.randrange(len(drifts))} {dur:.1f}s linear -{rng.uniform(0, dur):.1f}s infinite"
        tw_ = f"animation-duration:{rng.uniform(2, 4.5):.1f}s;animation-delay:-{rng.uniform(0, 4):.1f}s"
        if n < 5:  # a few four-point sparkles
            r = rng.uniform(2.6, 3.6)
            shape = (f'<path d="M{sx:.1f},{sy - r:.1f} Q{sx:.1f},{sy:.1f} {sx + r:.1f},{sy:.1f} Q{sx:.1f},{sy:.1f} {sx:.1f},{sy + r:.1f} '
                     f'Q{sx:.1f},{sy:.1f} {sx - r:.1f},{sy:.1f} Q{sx:.1f},{sy:.1f} {sx:.1f},{sy - r:.1f}Z" fill="{col}"/>')
        else:
            shape = f'<circle cx="{sx:.1f}" cy="{sy:.1f}" r="{rng.uniform(.5, 1.1):.2f}" fill="{col}"/>'
        stars.append(f'<g style="{drift}"><g class="tw" style="{tw_}">{shape}</g></g>')
    out.append(f'<g clip-path="url(#{frame_clip})">{"".join(stars)}</g>')

    # ---- the figure: one PNG pixel per LED, transparent where empty, shown through a dot mask
    png_rows = []
    for r in range(rows):
        line = bytearray()
        for c in range(cols):
            col = px[r - off][c] if r >= off else None
            line += bytes(int(col[i:i + 2], 16) for i in (1, 3, 5)) + b"\xff" if col else b"\x00\x00\x00\x00"
        png_rows.append(bytes(line))
    b64 = base64.b64encode(png_rgba(cols, rows, png_rows)).decode()

    pat, mask = s.uid("ledp"), s.uid("ledm")
    s.defs.append(f'<pattern id="{pat}" x="{mx:.2f}" y="{my:.2f}" width="{cell:.3f}" height="{cell:.3f}" patternUnits="userSpaceOnUse">'
                  f'<circle cx="{cell / 2:.3f}" cy="{cell / 2:.3f}" r="{cell * .42:.3f}" fill="#fff"/></pattern>'
                  f'<mask id="{mask}" maskUnits="userSpaceOnUse" x="{mx:.2f}" y="{my:.2f}" width="{mw:.2f}" height="{mh:.2f}">'
                  f'<rect x="{mx:.2f}" y="{my:.2f}" width="{mw:.2f}" height="{mh:.2f}" fill="url(#{pat})"/></mask>')
    s.css.append(".fig{animation:fig 1.4s ease-out .2s both}@keyframes fig{from{opacity:0}to{opacity:1}}"
                 ".bl{opacity:0;animation:bl 5.5s steps(1) 2.4s infinite}@keyframes bl{0%{opacity:0}94%{opacity:1}97%{opacity:0}}")
    layer = [f'<image href="data:image/png;base64,{b64}" x="{mx:.2f}" y="{my:.2f}" width="{mw:.2f}" height="{mh:.2f}" '
             f'preserveAspectRatio="none" style="image-rendering:pixelated;image-rendering:crisp-edges"/>']
    if av.get("blink"):  # eyelid-coloured LEDs flash over the eyes every few seconds
        layer.append('<g class="bl">' + "".join(
            f'<rect x="{mx + c * cell:.2f}" y="{my + (r + off) * cell:.2f}" width="{cell:.3f}" height="{cell:.3f}" fill="{colr}"/>'
            for r, c, colr in av["blink"]) + "</g>")
    out.append(f'<g class="fig" mask="url(#{mask})">' + "".join(layer) + "</g>")
    return "\n".join(out)


# ------------------------------------------------------------------ city
def render_city(cfg: dict, data: dict) -> str:
    W, H = 880, 430
    X0, Y0, CW, CH = 10, 10, 860, 410
    days = data["days"]
    total = sum(d["count"] for d in days)
    active = sum(1 for d in days if d["count"])
    peak = max(days, key=lambda d: d["count"]) if days else {"count": 0, "date": date.today().isoformat()}
    cur, longest = streaks(days)
    nweeks_all = max(1, math.ceil(len(days) / 7))
    s = Svg(W, H, f"Contribution city: {total} contributions in the last year", PAD)
    s.card(X0, Y0, CW, CH)
    s.heading(IN_L, 42, "FIG. 1", "Contribution city", "LAST 365 DAYS  ·  HEIGHT ∝ √CONTRIBUTIONS", IN_R)
    s.hline(X0 + 1, X0 + CW - 1, 60)

    # ---- readout column
    L, R = 40, 236
    s.add(f'<text x="{L}" y="94" font-family="{MONO}" font-size="9.5" letter-spacing="1.6" fill="{FAINT}">TOTAL</text>')
    s.odometer(L, 140, fmt(total), 40, INK, .3, 800)
    s.add(f'<text x="{L}" y="162" font-family="{SANS}" font-size="12" fill="{DIM}">contributions in the last year</text>')
    rows = [("active days", f"{active}"), ("peak day", f"{peak['count']}"),
            ("current streak", f"{cur}d"), ("longest streak", f"{longest}d"),
            ("weekly average", f"{total / nweeks_all:.1f}")]
    for i, (k, v) in enumerate(rows):
        y = 194 + i * 26
        s.add(f'<g class="fu" style="animation-delay:{.6 + i * .1:.2f}s">'
              f'<text x="{L}" y="{y}" font-family="{SANS}" font-size="12.5" fill="{DIM}">{k}</text>'
              f'<text x="{R}" y="{y}" text-anchor="end" font-family="{MONO}" font-size="12.5" fill="{INK}">{v}</text></g>')
        s.hline(L, R, y + 9, dash=True)

    # weekday rhythm
    wd = [0] * 7
    for d in days:
        wd[d["weekday"]] += d["count"]
    mx = max(wd) or 1
    s.add(f'<text x="{L}" y="342" font-family="{MONO}" font-size="9" letter-spacing="1.4" fill="{FAINT}">WEEKLY RHYTHM</text>')
    bw = (R - L - 6 * 8) / 7
    for i, v in enumerate(wd):
        bh = max(2, 36 * v / mx)
        x = L + i * (bw + 8)
        s.add(f'<rect x="{x:.1f}" y="352" width="{bw:.1f}" height="36" rx="2" fill="{BG1}"/>',
              f'<rect class="gy" style="animation-delay:{.8 + i * .06:.2f}s" x="{x:.1f}" y="{388 - bh:.1f}" width="{bw:.1f}" height="{bh:.1f}" rx="2" fill="{ACC}" fill-opacity="{.35 + .65 * v / mx:.2f}"/>',
              f'<text x="{x + bw / 2:.1f}" y="402" text-anchor="middle" font-family="{MONO}" font-size="8.5" fill="{FAINT}">{"SMTWTFS"[i]}</text>')
    s.add(f'<path d="M{R + 26},76 V402" stroke="{LINE2}"/>')

    # ---- isometric city
    weeks: dict[int, list[dict]] = {}
    first = date.fromisoformat(days[0]["date"]) if days else date.today()
    for d in days:
        weeks.setdefault((date.fromisoformat(d["date"]) - first).days // 7, []).append(d)
    nweeks = max(weeks) + 1 if weeks else 53
    ux, uy, vx, vy = 9.3, -2.85, 6.1, 3.7
    ox, oy = 292, 316
    top_h = 84
    cmax = max((d["count"] for d in days), default=0) or 1

    def P(w, d):
        return (ox + w * ux + d * vx, oy + w * uy + d * vy)

    def poly(pts, fill, extra=""):
        return f'<polygon points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in pts)}" fill="{fill}"{extra}/>'

    s.add(poly([P(-.8, -.8), P(nweeks + .8, -.8), P(nweeks + .8, 7.8), P(-.8, 7.8)], "#0b1820", f' stroke="{LINE2}"'))
    # month ticks along the front edge
    seen = set()
    for wi in sorted(weeks):
        m = date.fromisoformat(weeks[wi][0]["date"])
        key = (m.year, m.month)
        if key in seen or wi == 0:
            seen.add(key)
            continue
        seen.add(key)
        a, b = P(wi, 7.8), P(wi, 8.5)
        if b[0] + 24 > IN_R:  # keep month labels inside the card padding
            continue
        s.add(f'<path d="M{a[0]:.1f},{a[1]:.1f} L{b[0]:.1f},{b[1]:.1f}" stroke="{FAINT}"/>',
              f'<text x="{b[0] + 2:.1f}" y="{b[1] + 11:.1f}" font-family="{MONO}" font-size="8.5" letter-spacing=".8" fill="{FAINT}">{m:%b}</text>'.replace(m.strftime('%b'), m.strftime('%b').upper()))

    cells = [(wi, d["weekday"], d["count"], d["date"]) for wi, wd_ in weeks.items() for d in wd_]
    cells.sort(key=lambda c: (c[1] - c[0], c[1]))
    peak_cell = next(((c[0], c[1]) for c in cells if c[3] == peak["date"]), None)
    T, T0 = 9.0, 2.6  # sweep period and start (after the towers have risen)
    s.css.append(f".sh{{opacity:0;animation:sh {T}s ease-out infinite}}"
                 "@keyframes sh{0%{opacity:0}2%{opacity:.75}9%{opacity:0}100%{opacity:0}}"
                 ".win{animation:win 4s steps(1) infinite}"
                 "@keyframes win{0%{opacity:.95}35%{opacity:.2}50%{opacity:.95}78%{opacity:.45}}"
                 ".pt{transform-box:fill-box;animation:pt 3.6s ease-out infinite}"
                 "@keyframes pt{0%{transform:translateY(0);opacity:0}15%{opacity:1}100%{transform:translateY(-38px);opacity:0}}")
    rng = random.Random(5)
    span = nweeks + 4

    def sweep_delay(w: float) -> float:
        return T0 + (w + 2) / span * T

    gap = .13
    tallest = sorted((c for c in cells if c[2]), key=lambda c: -c[2])[:12]
    sparks = {(c[0], c[1]) for c in tallest}
    peak_roof = None
    last_date = days[-1]["date"] if days else ""
    beacon = None
    for w, d, c, ds in cells:
        a, b, e, f = w + gap, w + 1 - gap, d + gap, d + 1 - gap
        p1, p2, p3, p4 = P(a, e), P(b, e), P(b, f), P(a, f)
        if c == 0:
            s.add(poly([p1, p2, p3, p4], CITY_LEVELS[0]))
            if ds == last_date:
                beacon = ((p1[0] + p3[0]) / 2, (p1[1] + p3[1]) / 2)
            continue
        ratio = math.sqrt(c / cmax)
        top = CITY_LEVELS[min(4, 1 + int(ratio * 3.999))]
        is_peak = ds == peak["date"]
        if is_peak:
            top = WARM
        h = 3 + top_h * ratio
        up = lambda p: (p[0], p[1] - h)
        roof = [up(p1), up(p2), up(p3), up(p4)]
        # lit windows on the front face of taller towers
        wins = []
        if h >= 16:
            for k in range(min(6, int((h - 6) / 9))):
                for sx in (.3, .7):
                    if rng.random() < .55:
                        wx = p4[0] + sx * (p3[0] - p4[0])
                        wy = p4[1] + sx * (p3[1] - p4[1]) - 7 - k * 9
                        wins.append(f'<rect class="win" style="animation-duration:{rng.uniform(2.5, 6.5):.1f}s;animation-delay:{rng.uniform(0, 4):.1f}s" '
                                    f'x="{wx - 1:.1f}" y="{wy - .8:.1f}" width="2" height="1.6" fill="#fff1c1"/>')
        s.add(f'<g class="gy" style="animation-delay:{.2 + w * .022:.2f}s">'
              + poly([p1, p4, up(p4), up(p1)], shade(top, .5))
              + poly([p4, p3, up(p3), up(p4)], shade(top, .72))
              + poly(roof, top)
              + "".join(wins)
              + poly(roof, "#ffffff", f' class="sh" style="animation-delay:{sweep_delay(w):.2f}s"')
              + "</g>")
        if (w, d) in sparks:
            rx_, ry_ = (roof[0][0] + roof[2][0]) / 2, (roof[0][1] + roof[2][1]) / 2
            for _ in range(2):
                s.add(f'<circle class="pt" style="animation-delay:{T0 + rng.uniform(0, 4):.1f}s;animation-duration:{rng.uniform(2.8, 4.6):.1f}s" '
                      f'cx="{rx_ + rng.uniform(-3, 3):.1f}" cy="{ry_:.1f}" r="1.3" fill="{"#ffd28a" if (w, d) == peak_cell else MINT}"/>')
        if is_peak:
            peak_roof = ((roof[0][0] + roof[2][0]) / 2, (roof[0][1] + roof[2][1]) / 2)
        if ds == last_date:
            beacon = ((roof[0][0] + roof[2][0]) / 2, (roof[0][1] + roof[2][1]) / 2)

    # scanning beam that sweeps the city; roofs flash as it passes
    bid = s.uid("beam")
    s.defs.append(f'<linearGradient id="{bid}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{ACC}" stop-opacity="0"/>'
                  f'<stop offset="1" stop-color="{ACC}" stop-opacity=".22"/></linearGradient>')
    a0, a1 = P(0, -.8), P(0, 7.8)
    sheet = [(a0[0], a0[1] - 120), (a1[0], a1[1] - 120), a1, a0]
    floor_glow = [P(-.6, -.8), P(.6, -.8), P(.6, 7.8), P(-.6, 7.8)]
    dx0, dy0 = -2 * ux, -2 * uy
    dx1, dy1 = (nweeks + 2) * ux, (nweeks + 2) * uy
    s.css.append(f".beam{{opacity:0;animation:beam {T}s linear {T0}s infinite}}"
                 f"@keyframes beam{{0%{{transform:translate({dx0:.1f}px,{dy0:.1f}px);opacity:0}}6%{{opacity:1}}"
                 f"92%{{opacity:1}}100%{{transform:translate({dx1:.1f}px,{dy1:.1f}px);opacity:0}}}}")
    s.add(f'<g class="beam">{poly(sheet, f"url(#{bid})")}{poly(floor_glow, ACC, " fill-opacity=" + chr(34) + ".16" + chr(34))}'
          f'<path d="M{a0[0]:.1f},{a0[1]:.1f} L{a1[0]:.1f},{a1[1]:.1f}" stroke="{ACC}" stroke-opacity=".7"/></g>')

    if peak_roof:
        px_, py_ = peak_roof
        ly = max(84, py_ - 34)
        label = f"PEAK · {peak['count']}  {date.fromisoformat(peak['date']):%d %b}".upper()
        lw = tw(label, 9.5, True) + 16
        lx = min(px_ - 8, IN_R - lw)
        s.add(f'<g class="fi" style="animation-delay:2.2s"><path d="M{px_:.1f},{py_:.1f} V{ly + 6:.1f}" stroke="{WARM}" stroke-dasharray="2 2"/>'
              f'<circle cx="{px_:.1f}" cy="{py_:.1f}" r="2" fill="{WARM}"/>'
              f'<rect x="{lx:.1f}" y="{ly - 12:.1f}" width="{lw:.1f}" height="18" rx="3" fill="{BG0}" stroke="{WARM}" stroke-opacity=".6"/>'
              f'<text x="{lx + 8:.1f}" y="{ly + 1:.1f}" font-family="{MONO}" font-size="9.5" letter-spacing=".8" fill="{WARM}">{label}</text></g>')
    if beacon:
        bx, by = beacon
        s.add(f'<circle class="ring" cx="{bx:.1f}" cy="{by:.1f}" r="3" fill="none" stroke="{ACC}"/>',
              f'<circle cx="{bx:.1f}" cy="{by:.1f}" r="2.5" fill="{ACC}"/>',
              f'<text x="{bx:.1f}" y="{by - 10:.1f}" text-anchor="middle" font-family="{MONO}" font-size="8.5" letter-spacing=".8" fill="{ACC}">TODAY</text>')

    # legend
    lx = IN_R - 138
    s.add(f'<text x="{lx}" y="400" font-family="{MONO}" font-size="8.5" letter-spacing="1" fill="{FAINT}">LESS</text>')
    for i, c in enumerate(CITY_LEVELS):
        s.add(f'<rect x="{lx + 32 + i * 16}" y="391" width="11" height="11" rx="2" fill="{c}"/>')
    s.add(f'<text x="{lx + 32 + 5 * 16 + 4}" y="400" font-family="{MONO}" font-size="8.5" letter-spacing="1" fill="{FAINT}">MORE</text>')
    return s.render()


# ------------------------------------------------------------------ panels
def render_panels(cfg: dict, data: dict) -> str:
    W, H = 880, 430
    s = Svg(W, H, "Language stack and selected work", PAD)

    # ---- language stack card
    X0, Y0, LW, CH = 10, 10, 292, 410
    s.card(X0, Y0, LW, CH)
    s.heading(IN_L, 42, "FIG. 2", "Language stack")
    s.hline(X0 + 1, X0 + LW - 1, 60)
    s.add(f'<text x="{IN_L}" y="84" font-family="{MONO}" font-size="9" letter-spacing="1.4" fill="{FAINT}">BYTES OF CODE · PUBLIC REPOS</text>')

    excl = set(cfg.get("exclude_languages", []))
    langs = sorted(((n, b) for n, b in data["lang_bytes"].items() if n not in excl), key=lambda t: -t[1])
    langs = langs[: cfg.get("top_languages", 5)]
    tot = sum(b for _, b in langs) or 1
    bx, bwid = IN_L, LW - 60
    clip = s.uid("lb")
    s.defs.append(f'<clipPath id="{clip}"><rect class="gx" style="animation-delay:.3s" x="{bx}" y="96" width="{bwid}" height="10" rx="3"/></clipPath>')
    segs, cx = [], bx
    for n, b in langs:
        wseg = bwid * b / tot
        color = data["lang_color"].get(n) or LANG_FALLBACK.get(n, ACC)
        segs.append(f'<rect x="{cx:.1f}" y="96" width="{max(0, wseg - 2):.1f}" height="10" fill="{color}"/>')
        cx += wseg
    s.add(f'<g clip-path="url(#{clip})">{"".join(segs)}</g>')

    step = min(50, (318 - 146) / max(1, len(langs) - 1))
    for i, (n, b) in enumerate(langs):
        y = 146 + i * step
        pct = 100 * b / tot
        color = data["lang_color"].get(n) or LANG_FALLBACK.get(n, ACC)
        s.add(f'<g class="fu" style="animation-delay:{.4 + i * .1:.2f}s">'
              f'<rect x="{bx}" y="{y - 9}" width="8" height="8" rx="1.5" fill="{color}"/>'
              f'<text x="{bx + 16}" y="{y}" font-family="{SANS}" font-size="13.5" fill="{INK}">{esc(n)}</text>'
              f'<text x="{bx + bwid}" y="{y}" text-anchor="end" font-family="{MONO}" font-size="12" fill="{INK}">{pct:.1f}%</text>'
              f'<text x="{bx + 16}" y="{y + 15}" font-family="{MONO}" font-size="9" fill="{FAINT}">{size_str(b)}</text>'
              f'<rect x="{bx}" y="{y + 22}" width="{bwid}" height="3" rx="1.5" fill="{BG1}"/>'
              f'<rect class="gx" style="animation-delay:{.6 + i * .1:.2f}s" x="{bx}" y="{y + 22}" width="{max(3, bwid * pct / 100):.1f}" height="3" rx="1.5" fill="{color}"/></g>')
    # summary readouts along the bottom, aligned with the project cards' bottom edge
    s.hline(bx, bx + bwid, 344)
    summary = [("CODE", size_str(tot)), ("LANGUAGES", str(len(langs))), ("REPOS", str(data["repos"]))]
    colw = bwid / 3
    for i, (k, v) in enumerate(summary):
        sx = bx + i * colw
        s.add(f'<text x="{sx:.1f}" y="366" font-family="{MONO}" font-size="8.5" letter-spacing="1.4" fill="{FAINT}">{k}</text>'
              f'<text x="{sx:.1f}" y="390" font-family="{MONO}" font-size="15" font-weight="700" fill="{INK}">{esc(v)}</text>')

    # ---- selected work card
    PX = X0 + LW + GAP
    PW = W - 10 - PX
    s.card(PX, Y0, PW, CH)
    s.heading(PX + 30, 42, "TABLE 1", "Selected work", "./projects.sh --featured", PX + PW - 30)
    s.hline(PX + 1, PX + PW - 1, 60)

    gap = 10
    top, bottom = 80, Y0 + CH - 30  # 20 px under the heading rule, 30 px above the card edge (same as the sides)
    cw = (PW - 60 - gap) / 2
    chh = (bottom - top - gap) / 2
    for i, p in enumerate(data["featured"][:4]):
        cx = PX + 30 + (i % 2) * (cw + gap)
        cy = top + (i // 2) * (chh + gap)
        s.add(f'<g class="fu" style="animation-delay:{.3 + i * .14:.2f}s">')
        s.add(f'<rect x="{cx:.1f}" y="{cy:.1f}" width="{cw:.1f}" height="{chh:.1f}" rx="10" fill="{BG1}" stroke="{LINE2}"/>')
        s.add(f'<text x="{cx + 16:.1f}" y="{cy + 24:.1f}" font-family="{MONO}" font-size="9.5" letter-spacing="1.2" fill="{FAINT}">{i + 1:02d}</text>')
        s.add(f'<circle cx="{cx + cw - 16 - tw(p["language"], 9.5, True) - 9:.1f}" cy="{cy + 20.5:.1f}" r="3.5" fill="{p["color"]}"/>'
              f'<text x="{cx + cw - 16:.1f}" y="{cy + 24:.1f}" text-anchor="end" font-family="{MONO}" font-size="9.5" fill="{DIM}">{esc(p["language"])}</text>')
        name = p["name"] if len(p["name"]) <= 24 else p["name"][:23] + "…"
        s.add(f'<text x="{cx + 16:.1f}" y="{cy + 50:.1f}" font-family="{SANS}" font-size="16" font-weight="650" fill="{INK}">{esc(name)}</text>')
        for j, line in enumerate(wrap(p["description"], int((cw - 32) / 5.7), 3)):
            s.add(f'<text x="{cx + 16:.1f}" y="{cy + 70 + j * 14.5:.1f}" font-family="{SANS}" font-size="11.5" fill="{DIM}">{esc(line)}</text>')
        tags = "   ".join("#" + t for t in p["tags"][:3])
        s.add(f'<text x="{cx + 16:.1f}" y="{cy + chh - 44:.1f}" font-family="{MONO}" font-size="10" fill="{ACC}">{esc(tags)}</text>')

        # language mix bar
        mclip = s.uid("mx")
        mw = cw - 32
        s.defs.append(f'<clipPath id="{mclip}"><rect class="gx" style="animation-delay:{.7 + i * .14:.2f}s" x="{cx + 16:.1f}" y="{cy + chh - 32:.1f}" width="{mw:.1f}" height="4" rx="2"/></clipPath>')
        segs, mx_ = [], cx + 16
        for _, col, frac in p["mix"]:
            segs.append(f'<rect x="{mx_:.1f}" y="{cy + chh - 32:.1f}" width="{max(0, mw * frac - 1.5):.1f}" height="4" fill="{col}"/>')
            mx_ += mw * frac
        s.add(f'<rect x="{cx + 16:.1f}" y="{cy + chh - 32:.1f}" width="{mw:.1f}" height="4" rx="2" fill="{BG0}"/>',
              f'<g clip-path="url(#{mclip})">{"".join(segs)}</g>')
        s.add(f'<text x="{cx + 16:.1f}" y="{cy + chh - 14:.1f}" font-family="{MONO}" font-size="9.5" fill="{FAINT}">★ {p["stars"]}</text>'
              f'<text x="{cx + cw - 16:.1f}" y="{cy + chh - 14:.1f}" text-anchor="end" font-family="{MONO}" font-size="9.5" fill="{FAINT}">pushed {ago(p["pushed"])}</text>')
        s.add("</g>")
    return s.render()


# ------------------------------------------------------------------ link buttons
def render_button(label: str, idx: int, n: int) -> str:
    """One of n buttons shown side by side at 100/n % width each, with no whitespace
    between them in the README. Insets differ per button so the row lines up with
    the card edges (x 10..870 of 880) and the gaps between buttons equal GAP."""
    W, H = 880 / n, 54
    bw = (860 - (n - 1) * GAP) / n
    x = 10 + (idx - 1) * (bw + GAP) - (idx - 1) * W
    y, bh = 6, 42
    s = Svg(round(W), H, label.title())
    s.add(f'<rect x="{x:.1f}" y="{y}" width="{bw:.1f}" height="{bh}" rx="10" fill="{BG0}" stroke="{LINE2}"/>',
          f'<path d="M{x + 7:.1f},{y + 17} V{y + 7} H{x + 17:.1f}" fill="none" stroke="{ACC}" stroke-width="1.5"/>',
          f'<path d="M{x + bw - 7:.1f},{y + bh - 17} V{y + bh - 7} H{x + bw - 17:.1f}" fill="none" stroke="{ACC}" stroke-width="1.5"/>',
          f'<text x="{x + 20:.1f}" y="{y + 25}" font-family="{MONO}" font-size="9.5" fill="{FAINT}">{idx:02d}</text>',
          f'<text x="{x + 44:.1f}" y="{y + 25}" font-family="{MONO}" font-size="12" letter-spacing="1.6" fill="{INK}">{esc(label)}</text>',
          f'<text x="{x + bw - 20:.1f}" y="{y + 25}" text-anchor="end" font-family="{MONO}" font-size="13" fill="{ACC}">↗</text>')
    return s.render()


# ------------------------------------------------------------------ main
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true", help="render with sample data, no token")
    args = ap.parse_args()

    cfg = json.loads((ROOT / "config.json").read_text())
    if args.demo:
        data = fetch_demo(cfg)
    else:
        token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
        if not token:
            sys.exit("Set GH_TOKEN (or run with --demo).")
        data = fetch_live(cfg, token)

    # Demo output never goes to assets/, so sample numbers cannot reach the profile.
    out_dir = ROOT / "preview" if args.demo else ASSETS
    out_dir.mkdir(exist_ok=True)
    outputs = {"header.svg": render_header(cfg, data), "city.svg": render_city(cfg, data),
               "panels.svg": render_panels(cfg, data)}
    links = cfg.get("links", [])
    for i, link in enumerate(links, 1):
        outputs[f"btn-{link['label'].lower()}.svg"] = render_button(link["label"], i, len(links))
    for name, svg in outputs.items():
        (out_dir / name).write_text(svg, encoding="utf-8")
        print(f"wrote {out_dir.name}/{name}")


if __name__ == "__main__":
    main()
