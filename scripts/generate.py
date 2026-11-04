#!/usr/bin/env python3
"""Render the profile dashboard SVGs from live GitHub data.

Outputs (in assets/):
  header.svg  animated name card, live stats, dotted pixel avatar
  city.svg    3D isometric contribution city for the last year
  panels.svg  language stack + featured projects

Usage:
  GH_TOKEN=... python scripts/generate.py      # live data (used by the Action)
  python scripts/generate.py --demo            # sample data, no token needed

Standard library only, so the Action needs no pip install.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"

# ---------------------------------------------------------------- theme
BG = "#0b1220"
PANEL = "#0f1a2b"
CARD = "#132238"
BORDER = "#1f3a4d"
TEXT = "#e6edf3"
MUTED = "#8b9bb0"
TEAL = "#2dd4bf"
MINT = "#5eead4"
PURPLE = "#a78bfa"
SANS = "'Segoe UI', Ubuntu, 'Helvetica Neue', Arial, sans-serif"
MONO = "'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace"

LANG_FALLBACK = {
    "Python": "#3572A5", "TypeScript": "#3178c6", "JavaScript": "#f1e05a",
    "Jupyter Notebook": "#DA5B0B", "Markdown": "#083fa1", "Rust": "#dea584",
    "Kotlin": "#A97BFF", "Go": "#00ADD8", "Java": "#b07219", "C++": "#f34b7d",
}

# ---------------------------------------------------------------- data
GRAPHQL = "https://api.github.com/graphql"

USER_QUERY = """
query($login: String!) {
  user(login: $login) {
    name
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
    name description stargazerCount pushedAt
    primaryLanguage { name color }
    languages(first: 10) { totalSize edges { size node { name } } }
  }
"""


def gql(token: str, query: str, variables: dict | None = None) -> dict:
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(
        GRAPHQL,
        data=body,
        headers={"Authorization": f"bearer {token}", "Content-Type": "application/json",
                 "User-Agent": "profile-dashboard"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.load(resp)
    if payload.get("errors"):
        sys.exit(f"GraphQL error: {payload['errors']}")
    return payload["data"]


def fetch_live(cfg: dict, token: str) -> dict:
    login = cfg["username"]
    user = gql(token, USER_QUERY, {"login": login})["user"]

    featured_q = "query {" + "".join(
        REPO_FRAGMENT % (i, *(f["repo"].split("/", 1) if "/" in f["repo"] else (login, f["repo"])))
        for i, f in enumerate(cfg["featured"])
    ) + "}"
    repos_raw = gql(token, featured_q) if cfg["featured"] else {}

    days = [
        {"date": d["date"], "count": d["contributionCount"], "weekday": d["weekday"]}
        for w in user["contributionsCollection"]["contributionCalendar"]["weeks"]
        for d in w["contributionDays"]
    ]

    lang_bytes: dict[str, int] = {}
    lang_color: dict[str, str] = {}
    stars = 0
    for repo in user["repositories"]["nodes"]:
        stars += repo["stargazerCount"]
        for edge in repo["languages"]["edges"]:
            n = edge["node"]["name"]
            lang_bytes[n] = lang_bytes.get(n, 0) + edge["size"]
            if edge["node"]["color"]:
                lang_color[n] = edge["node"]["color"]

    featured = []
    for i, f in enumerate(cfg["featured"]):
        r = repos_raw.get(f"r{i}")
        if not r:
            print(f"warning: featured repo {f['repo']} not found, skipped", file=sys.stderr)
            continue
        total = r["languages"]["totalSize"] or 1
        prim = r["primaryLanguage"] or {"name": "n/a", "color": MUTED}
        share = next((e["size"] for e in r["languages"]["edges"] if e["node"]["name"] == prim["name"]), 0)
        featured.append({
            "name": r["name"],
            "description": f.get("description") or r["description"] or "",
            "tags": f.get("tags", []),
            "stars": r["stargazerCount"],
            "pushed": r["pushedAt"],
            "language": prim["name"],
            "color": prim["color"] or MUTED,
            "share": round(100 * share / total),
        })

    return {
        "repos": user["repositories"]["totalCount"],
        "stars": stars,
        "followers": user["followers"]["totalCount"],
        "days": days,
        "lang_bytes": lang_bytes,
        "lang_color": lang_color,
        "featured": featured,
    }


def fetch_demo(cfg: dict) -> dict:
    """Deterministic sample data so the layout can be previewed offline."""
    rng = random.Random(7)
    end = date.today()
    start = end - timedelta(days=364 + (end.weekday() + 1) % 7)
    days = []
    d = start
    while d <= end:
        wd = (d.weekday() + 1) % 7
        burst = 1.0 + 1.6 * math.sin((d - start).days / 40) ** 2
        base = rng.random()
        count = 0 if base < 0.35 else int(rng.expovariate(1 / (4 * burst)))
        if wd in (5, 6) and rng.random() < 0.5:
            count //= 2
        days.append({"date": d.isoformat(), "count": count, "weekday": wd})
        d += timedelta(days=1)
    now = datetime.now(timezone.utc)
    sample = [("TypeScript", "#3178c6", 3, 62), ("TypeScript", "#3178c6", 1, 71),
              ("Python", "#3572A5", 1, 88), ("TypeScript", "#3178c6", 1, 94)]
    featured = []
    for f, (lang, color, stars, share) in zip(cfg["featured"], sample):
        featured.append({
            "name": f["repo"].split("/")[-1], "description": f.get("description", ""),
            "tags": f.get("tags", []), "stars": stars, "language": lang, "color": color,
            "share": share, "pushed": (now - timedelta(days=rng.randint(0, 20))).isoformat(),
        })
    return {
        "repos": 12, "stars": 9, "followers": 4, "days": days,
        "lang_bytes": {"TypeScript": 5_400_000, "Python": 2_100_000, "JavaScript": 300_000,
                       "Jupyter Notebook": 180_000, "Markdown": 90_000, "HTML": 800_000},
        "lang_color": {"TypeScript": "#3178c6", "Python": "#3572A5", "JavaScript": "#f1e05a",
                       "Jupyter Notebook": "#DA5B0B", "Markdown": "#083fa1"},
        "featured": featured,
    }


# ---------------------------------------------------------------- helpers
def esc(s) -> str:
    return escape(str(s), {'"': "&quot;"})


def fmt(n: int) -> str:
    return f"{n/1000:.1f}k" if n >= 10_000 else f"{n:,}"


def text_w(s: str, size: float, mono: bool = False) -> float:
    """Rough text width; SVG in <img> cannot measure fonts."""
    return len(s) * size * (0.61 if mono else 0.58)


def shade(hex_color: str, k: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(c * k))) for c in (r, g, b))


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
        out[-1] = out[-1][: width - 1].rstrip(" .,") + "…"
    return out


def ago(iso: str) -> str:
    then = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    days = (datetime.now(timezone.utc) - then).days
    if days <= 0:
        return "updated today"
    if days == 1:
        return "updated 1d ago"
    if days < 30:
        return f"updated {days}d ago"
    if days < 365:
        return f"updated {days // 30}mo ago"
    return f"updated {days // 365}y ago"


def streaks(days: list[dict]) -> tuple[int, int]:
    longest = run = 0
    for d in days:
        run = run + 1 if d["count"] else 0
        longest = max(longest, run)
    cur = 0
    seq = list(days)
    if seq and seq[-1]["count"] == 0:  # today not counted yet
        seq = seq[:-1]
    for d in reversed(seq):
        if not d["count"]:
            break
        cur += 1
    return cur, longest


def svg_open(w: int, h: int, title: str, css: str = "") -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
        f'role="img" aria-label="{esc(title)}">\n<title>{esc(title)}</title>\n'
        f"<style>{css}</style>\n"
    )


ICONS = {
    # 16x16 outline icons drawn with simple paths
    "repo": "M3 2.5h8.5a1.5 1.5 0 0 1 1.5 1.5v9H4.5A1.5 1.5 0 0 1 3 11.5zM3 11.5A1.5 1.5 0 0 1 4.5 10H13M6 2.5v5l1.5-1 1.5 1v-5",
    "star": "M8 1.8l1.9 3.9 4.3.6-3.1 3 .7 4.3L8 11.6l-3.8 2 .7-4.3-3.1-3 4.3-.6z",
    "pulse": "M1.5 8.5h3l1.8-4.5 3 9 2-6.5 1.2 2h2",
    "people": "M5.5 7.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zM1 14c0-2.5 2-4 4.5-4s4.5 1.5 4.5 4M11 7.5a2 2 0 1 0 0-4M12 10c1.8.3 3 1.6 3 4",
    "pin": "M8 15s5-4.6 5-8.5A5 5 0 0 0 3 6.5C3 10.4 8 15 8 15zM8 8.3a1.8 1.8 0 1 0 0-3.6 1.8 1.8 0 0 0 0 3.6z",
    "trophy": "M5 2h6v4a3 3 0 0 1-6 0zM5 3.5H2.5a2.5 2.5 0 0 0 2.6 3M11 3.5h2.5a2.5 2.5 0 0 1-2.6 3M8 9v3M5.5 14h5M6.5 12h3",
}


def icon(name: str, x: float, y: float, color: str, scale: float = 1.0) -> str:
    return (f'<path d="{ICONS[name]}" transform="translate({x},{y}) scale({scale})" fill="none" '
            f'stroke="{color}" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/>')


def sparkle(x: float, y: float, r: float, delay: float, color: str = MINT) -> str:
    d = (f"M{x},{y - r} Q{x},{y} {x + r},{y} Q{x},{y} {x},{y + r} "
         f"Q{x},{y} {x - r},{y} Q{x},{y} {x},{y - r}Z")
    return f'<path class="tw" style="animation-delay:{delay}s" d="{d}" fill="{color}"/>'


# ---------------------------------------------------------------- header
def render_header(cfg: dict, data: dict) -> str:
    W, H = 840, 270
    total = sum(d["count"] for d in data["days"])
    title = cfg["title"]
    css = f"""
    .tw{{animation:tw 3.2s ease-in-out infinite;transform-box:fill-box;transform-origin:center}}
    @keyframes tw{{0%,100%{{opacity:.15;transform:scale(.6)}}50%{{opacity:1;transform:scale(1)}}}}
    .type{{animation:type 3.4s steps({len(title)}) .4s both}}
    @keyframes type{{from{{width:0}}to{{width:{text_w(title, 14, True) + 6:.0f}px}}}}
    .cur{{animation:blink 1s step-end infinite}}
    @keyframes blink{{50%{{opacity:0}}}}
    .fade{{animation:fade .8s ease-out both}}
    @keyframes fade{{from{{opacity:0;transform:translateY(6px)}}to{{opacity:1;transform:none}}}}
    .scan{{animation:scan 4s linear infinite}}
    @keyframes scan{{from{{transform:translateY(0)}}to{{transform:translateY(190px)}}}}
    .glow{{animation:glow 3s ease-in-out infinite}}
    @keyframes glow{{50%{{stroke-opacity:.9}}}}
    """
    o = [svg_open(W, H, f"{cfg['name']}, {title}", css)]
    o.append(f"""<defs>
  <linearGradient id="edge" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="{TEAL}"/><stop offset=".55" stop-color="#1e3a5f"/><stop offset="1" stop-color="{PURPLE}"/>
  </linearGradient>
  <linearGradient id="name" x1="0" y1="0" x2="1" y2="0">
    <stop offset="0" stop-color="#ffffff"/><stop offset="1" stop-color="{MINT}"/>
  </linearGradient>
  <radialGradient id="halo" cx=".5" cy=".45" r=".6">
    <stop offset="0" stop-color="{TEAL}" stop-opacity=".38"/><stop offset="1" stop-color="{TEAL}" stop-opacity="0"/>
  </radialGradient>
  <pattern id="grid" width="18" height="18" patternUnits="userSpaceOnUse">
    <path d="M18 0H0V18" fill="none" stroke="#ffffff" stroke-opacity=".035"/>
  </pattern>
  <clipPath id="typeclip"><rect class="type" x="34" y="128" height="22" width="0"/></clipPath>
  <clipPath id="avclip"><rect x="626" y="44" width="186" height="200" rx="14"/></clipPath>
</defs>""")
    o.append(f'<rect x="1" y="1" width="{W - 2}" height="{H - 2}" rx="18" fill="{BG}" stroke="url(#edge)" stroke-width="1.5"/>')
    o.append(f'<rect x="1" y="1" width="{W - 2}" height="{H - 2}" rx="18" fill="url(#grid)"/>')

    # window chrome
    for i, c in enumerate(["#ff5f57", "#febc2e", "#28c840"]):
        o.append(f'<circle cx="{24 + i * 16}" cy="22" r="5" fill="{c}"/>')
    o.append(f'<text x="80" y="26" font-family="{MONO}" font-size="11" fill="{MUTED}">~/{esc(cfg["username"])}/README.md</text>')

    # identity
    o.append(f'<g class="fade"><text x="34" y="66" font-family="{MONO}" font-size="14" fill="{TEAL}">@{esc(cfg["username"])}</text>')
    if cfg.get("badge"):
        bx = 34 + text_w("@" + cfg["username"], 14, True) + 14
        bw = text_w(cfg["badge"], 11) + 34
        o.append(f'<rect x="{bx:.0f}" y="51" width="{bw:.0f}" height="21" rx="10.5" fill="#fbbf24" fill-opacity=".1" stroke="#fbbf24" stroke-opacity=".5"/>')
        o.append(icon("trophy", bx + 8, 54, "#fbbf24", 0.85))
        o.append(f'<text x="{bx + 25:.0f}" y="65.5" font-family="{SANS}" font-size="11" font-weight="600" fill="#fcd34d">{esc(cfg["badge"])}</text>')
    o.append(f'<text x="32" y="110" font-family="{SANS}" font-size="38" font-weight="700" fill="url(#name)">{esc(cfg["name"])}</text></g>')
    o.append(f'<g clip-path="url(#typeclip)"><text x="34" y="144" font-family="{MONO}" font-size="14" fill="{TEXT}" fill-opacity=".85">{esc(title)}</text></g>')
    cx = 34 + text_w(title, 14, True) + 6
    o.append(f'<rect class="cur" x="{cx:.0f}" y="131" width="8" height="16" fill="{TEAL}"/>')

    # meta line
    x = 34
    meta = []
    if cfg.get("location"):
        meta.append(("pin", cfg["location"], MUTED))
    if cfg.get("status"):
        meta.append(("dot", cfg["status"], "#4ade80"))
    for kind, label, color in meta:
        if x + 18 + text_w(label, 12.5) > 446:
            break
        if kind == "dot":
            o.append(f'<circle cx="{x + 5}" cy="172" r="4" fill="{color}"><animate attributeName="opacity" values="1;.35;1" dur="2s" repeatCount="indefinite"/></circle>')
        else:
            o.append(icon(kind, x - 1, 164, color, 0.95))
        o.append(f'<text x="{x + 18}" y="176" font-family="{SANS}" font-size="12.5" fill="{MUTED}">{esc(label)}</text>')
        x += 18 + text_w(label, 12.5) + 14

    # pills, wrapped to the left column
    px, py, maxx = 34, 196, 440
    for p in cfg.get("pills", []):
        pw = text_w(p, 11.5) + 26
        if px + pw > maxx:
            px, py = 34, py + 30
            if py > 230:
                break
        o.append(f'<rect x="{px}" y="{py}" width="{pw:.0f}" height="22" rx="11" fill="{CARD}" stroke="{BORDER}"/>')
        o.append(f'<circle cx="{px + 11}" cy="{py + 11}" r="3.5" fill="{LANG_FALLBACK.get(p, TEAL)}"/>')
        o.append(f'<text x="{px + 19}" y="{py + 15}" font-family="{SANS}" font-size="11.5" fill="{TEXT}">{esc(p)}</text>')
        px += pw + 8

    # live stats column
    stats = [("repo", data["repos"], "Repositories"), ("star", data["stars"], "Stars"),
             ("pulse", total, "Contributions"), ("people", data["followers"], "Followers")]
    sx, sy = 468, 70
    o.append(f'<rect x="{sx - 16}" y="{sy - 26}" width="156" height="166" rx="12" fill="{PANEL}" stroke="{BORDER}"/>')
    for i, (ic, val, label) in enumerate(stats):
        y = sy + i * 38
        o.append(f'<g class="fade" style="animation-delay:{.3 + i * .15}s">')
        o.append(icon(ic, sx - 2, y - 8, TEAL))
        o.append(f'<text x="{sx + 22}" y="{y + 4}" font-family="{SANS}" font-size="17" font-weight="700" fill="{TEXT}">{fmt(val)}</text>')
        o.append(f'<text x="{sx + 22}" y="{y + 19}" font-family="{SANS}" font-size="10.5" fill="{MUTED}">{label}</text></g>')
    o.append(f'<text x="{sx - 4}" y="{sy + 158}" font-family="{MONO}" font-size="9.5" fill="{MUTED}" fill-opacity=".8">live · {date.today():%d %b %Y}</text>')

    # avatar
    o.append(f'<rect x="626" y="44" width="186" height="200" rx="14" fill="#08131c"/>')
    o.append('<rect x="626" y="44" width="186" height="200" fill="url(#halo)"/>')
    o.append(render_avatar(626, 44, 186, 200))
    o.append(f'<g clip-path="url(#avclip)"><rect class="scan" x="626" y="40" width="186" height="10" fill="{MINT}" fill-opacity=".06"/></g>')
    o.append(f'<rect class="glow" x="626" y="44" width="186" height="200" rx="14" fill="none" stroke="{TEAL}" stroke-opacity=".35" stroke-width="1.5"/>')
    for i, (x, y, r) in enumerate([(612, 60, 6), (826, 98, 4.5), (604, 214, 4), (800, 30, 5), (830, 236, 3.5), (590, 132, 3)]):
        o.append(sparkle(x, y, r, i * 0.55))
    o.append("</svg>\n")
    return "\n".join(o)


def render_avatar(x0: float, y0: float, w: float, h: float) -> str:
    path = ROOT / "avatar" / "pixels.json"
    if not path.exists():
        return f'<text x="{x0 + w / 2}" y="{y0 + h / 2}" text-anchor="middle" font-family="{MONO}" font-size="11" fill="{MUTED}">run make_avatar.py</text>'
    av = json.loads(path.read_text())
    cols, rows, px = av["cols"], av["rows"], av["pixels"]
    cell = min((w - 16) / cols, (h - 14) / rows)
    ox = x0 + (w - cols * cell) / 2
    oy = y0 + h - rows * cell  # sit on the bottom edge like a bust
    rng = random.Random(11)
    out = ['<g>']
    for r in range(rows):
        for c in range(cols):
            col = px[r][c]
            if not col:
                continue
            k = 0.88 + rng.random() * 0.24  # mosaic shimmer
            rad = cell * (0.40 + rng.random() * 0.06)
            out.append(f'<circle cx="{ox + c * cell + cell / 2:.1f}" cy="{oy + r * cell + cell / 2:.1f}" r="{rad:.2f}" fill="{shade(col, k)}"/>')
    out.append("</g>")
    return "".join(out)


# ---------------------------------------------------------------- city
def render_city(cfg: dict, data: dict) -> str:
    W, H = 840, 320
    days = data["days"]
    total = sum(d["count"] for d in days)
    active = sum(1 for d in days if d["count"])
    busiest = max(days, key=lambda d: d["count"]) if days else {"count": 0, "date": ""}
    cur, longest = streaks(days)
    mx = max((d["count"] for d in days), default=0) or 1

    css = """
    .b{transform-box:fill-box;transform-origin:50% 100%;animation:rise 1s cubic-bezier(.2,.8,.2,1) both}
    @keyframes rise{from{transform:scaleY(0)}to{transform:scaleY(1)}}
    .fade{animation:fade .8s ease-out both}
    @keyframes fade{from{opacity:0}to{opacity:1}}
    .cur{animation:blink 1s step-end infinite}
    @keyframes blink{50%{opacity:0}}
    """
    o = [svg_open(W, H, f"3D contribution city: {total} contributions in the last year", css)]
    o.append(f'<rect x="1" y="1" width="{W - 2}" height="{H - 2}" rx="18" fill="{BG}" stroke="{BORDER}" stroke-width="1.5"/>')
    o.append(f'<text x="30" y="40" font-family="{MONO}" font-size="15" font-weight="700" fill="{TEXT}">{esc(cfg.get("city_title", "The city I built this year"))}</text>')
    o.append(f'<text x="{W - 30}" y="40" text-anchor="end" font-family="{MONO}" font-size="12" fill="{TEAL}">&gt; github-city_<tspan class="cur">▌</tspan></text>')

    # left stats
    o.append(f'<g class="fade"><text x="30" y="88" font-family="{MONO}" font-size="11" letter-spacing="1.5" fill="{TEAL}">CONTRIBUTIONS</text>')
    o.append(f'<text x="28" y="132" font-family="{SANS}" font-size="44" font-weight="800" fill="{TEXT}">{fmt(total)}</text>')
    rows = [("active days", active), ("busiest day", busiest["count"]),
            ("current streak", f"{cur}d"), ("longest streak", f"{longest}d")]
    for i, (k, v) in enumerate(rows):
        y = 166 + i * 24
        o.append(f'<text x="30" y="{y}" font-family="{SANS}" font-size="12.5" fill="{MUTED}">{k}</text>')
        o.append(f'<text x="200" y="{y}" text-anchor="end" font-family="{MONO}" font-size="12.5" fill="{TEXT}">{v}</text>')
    if busiest["date"]:
        bd = date.fromisoformat(busiest["date"])
        o.append(f'<text x="30" y="{166 + 4 * 24 + 4}" font-family="{MONO}" font-size="10" fill="{MUTED}" fill-opacity=".7">peak · {bd:%d %b %Y}</text>')
    o.append("</g>")

    # isometric city
    weeks: dict[int, list[dict]] = {}
    first = date.fromisoformat(days[0]["date"]) if days else date.today()
    for d in days:
        wi = (date.fromisoformat(d["date"]) - first).days // 7
        weeks.setdefault(wi, []).append(d)
    nweeks = max(weeks) + 1 if weeks else 53

    ux, uy = 9.0, -2.9   # one week step: right and up
    vx, vy = 5.6, 3.7    # one weekday step: right and down
    ox, oy = 238, 250
    gap = 0.14
    levels = ["#1b3a44", "#0f766e", "#14b8a6", "#2dd4bf", "#7af5e1"]

    def P(w, d):
        return (ox + w * ux + d * vx, oy + w * uy + d * vy)

    def poly(pts, fill, extra=""):
        return f'<polygon points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in pts)}" fill="{fill}"{extra}/>'

    floor = [P(-0.6, -0.6), P(nweeks + 0.6, -0.6), P(nweeks + 0.6, 7.6), P(-0.6, 7.6)]
    o.append(poly(floor, "#0d2230", f' stroke="{BORDER}" stroke-width="1"'))

    cells = []
    for wi, wdays in weeks.items():
        for d in wdays:
            cells.append((wi, d["weekday"], d["count"]))
    cells.sort(key=lambda c: (c[1] - c[0], c[1]))

    for w, d, c in cells:
        a, b = w + gap, w + 1 - gap
        e, f = d + gap, d + 1 - gap
        p1, p2, p3, p4 = P(a, e), P(b, e), P(b, f), P(a, f)
        if c == 0:
            o.append(poly([p1, p2, p3, p4], "#13303d"))
            continue
        ratio = math.sqrt(c / mx)
        lvl = min(4, 1 + int(ratio * 4))
        top = levels[lvl]
        h = 4 + 78 * ratio
        up = lambda p: (p[0], p[1] - h)
        left = [p1, p4, up(p4), up(p1)]
        front = [p4, p3, up(p3), up(p4)]
        roof = [up(p1), up(p2), up(p3), up(p4)]
        o.append(f'<g class="b" style="animation-delay:{w * 0.025:.2f}s">'
                 + poly(left, shade(top, 0.55)) + poly(front, shade(top, 0.78)) + poly(roof, top)
                 + "</g>")

    # legend
    lx = W - 190
    o.append(f'<text x="{lx}" y="{H - 22}" font-family="{SANS}" font-size="10.5" fill="{MUTED}">less</text>')
    for i, c in enumerate(["#13303d"] + levels[1:]):
        o.append(f'<rect x="{lx + 30 + i * 18}" y="{H - 32}" width="12" height="12" rx="2" fill="{c}"/>')
    o.append(f'<text x="{lx + 30 + 5 * 18 + 4}" y="{H - 22}" font-family="{SANS}" font-size="10.5" fill="{MUTED}">more</text>')
    o.append("</svg>\n")
    return "\n".join(o)


# ---------------------------------------------------------------- panels
def render_panels(cfg: dict, data: dict) -> str:
    W, H = 840, 330
    css = """
    .bar{transform-box:fill-box;transform-origin:0 50%;animation:grow 1.2s cubic-bezier(.2,.8,.2,1) both}
    @keyframes grow{from{transform:scaleX(0)}to{transform:scaleX(1)}}
    .ring{animation:ring 1.6s ease-out both}
    .fade{animation:fade .8s ease-out both}
    @keyframes fade{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
    .cur{animation:blink 1s step-end infinite}
    @keyframes blink{50%{opacity:0}}
    """
    o = [svg_open(W, H, "Language stack and featured projects", css)]

    # ---- language stack
    LW = 300
    o.append(f'<rect x="1" y="1" width="{LW}" height="{H - 2}" rx="18" fill="{BG}" stroke="{BORDER}" stroke-width="1.5"/>')
    o.append(f'<text x="24" y="38" font-family="{SANS}" font-size="16" font-weight="700" fill="{TEXT}">Language Stack</text>')
    o.append(f'<text x="24" y="56" font-family="{SANS}" font-size="10.5" fill="{TEAL}">repository-weighted technologies</text>')
    o.append(f'<text x="{LW - 20}" y="38" text-anchor="end" font-family="{MONO}" font-size="11" fill="{TEAL}">&gt; stack.scan<tspan class="cur">_</tspan></text>')

    excl = set(cfg.get("exclude_languages", []))
    langs = sorted(((n, b) for n, b in data["lang_bytes"].items() if n not in excl), key=lambda t: -t[1])
    langs = langs[: cfg.get("top_languages", 5)]
    tot = sum(b for _, b in langs) or 1
    for i, (n, b) in enumerate(langs):
        y = 96 + i * 44
        pct = 100 * b / tot
        color = data["lang_color"].get(n) or LANG_FALLBACK.get(n, TEAL)
        o.append(f'<circle cx="30" cy="{y - 4}" r="5" fill="{color}"/>')
        o.append(f'<text x="44" y="{y}" font-family="{SANS}" font-size="13" fill="{TEXT}">{esc(n)}</text>')
        o.append(f'<text x="{LW - 24}" y="{y}" text-anchor="end" font-family="{MONO}" font-size="12" fill="{color if color != "#083fa1" else MUTED}">{pct:.0f}%</text>')
        o.append(f'<rect x="24" y="{y + 10}" width="{LW - 48}" height="7" rx="3.5" fill="{CARD}"/>')
        bw = max(7, (LW - 48) * pct / 100)
        o.append(f'<rect class="bar" style="animation-delay:{.2 + i * .12:.2f}s" x="24" y="{y + 10}" width="{bw:.1f}" height="7" rx="3.5" fill="{color}"/>')

    # ---- projects
    X0 = LW + 16
    PW = W - X0 - 1
    o.append(f'<rect x="{X0}" y="1" width="{PW}" height="{H - 2}" rx="18" fill="{BG}" stroke="{BORDER}" stroke-width="1.5"/>')
    o.append(f'<text x="{X0 + 22}" y="38" font-family="{SANS}" font-size="16" font-weight="700" fill="{TEXT}">Projects.list</text>')
    o.append(f'<text x="{X0 + 22}" y="56" font-family="{MONO}" font-size="10.5" fill="{MUTED}">./projects.sh --featured</text>')
    o.append(f'<text x="{W - 22}" y="38" text-anchor="end" font-family="{MONO}" font-size="11" fill="{TEAL}">{len(data["featured"])} pinned</text>')

    cw, ch, gx, gy = (PW - 22 * 2 - 12) / 2, 118, 12, 12
    for i, p in enumerate(data["featured"][:4]):
        cx = X0 + 22 + (i % 2) * (cw + gx)
        cy = 72 + (i // 2) * (ch + gy)
        o.append(f'<g class="fade" style="animation-delay:{.2 + i * .15:.2f}s">')
        o.append(f'<rect x="{cx:.1f}" y="{cy}" width="{cw:.1f}" height="{ch}" rx="12" fill="{CARD}" stroke="{BORDER}"/>')
        o.append(f'<circle cx="{cx + 16:.1f}" cy="{cy + 20}" r="4" fill="{p["color"]}"/>')
        o.append(f'<text x="{cx + 27:.1f}" y="{cy + 24}" font-family="{SANS}" font-size="13" font-weight="700" fill="{TEXT}">{esc(p["name"])}</text>')
        for j, line in enumerate(wrap(p["description"], 27, 2)):
            o.append(f'<text x="{cx + 14:.1f}" y="{cy + 44 + j * 14}" font-family="{SANS}" font-size="10.5" fill="{MUTED}">{esc(line)}</text>')

        # ring: share of the repo's primary language
        rx, ry, rr = cx + cw - 30, cy + 34, 17
        circ = 2 * math.pi * rr
        o.append(f'<circle cx="{rx:.1f}" cy="{ry}" r="{rr}" fill="none" stroke="{BG}" stroke-width="4"/>')
        o.append(f'<circle class="ring" cx="{rx:.1f}" cy="{ry}" r="{rr}" fill="none" stroke="{p["color"]}" stroke-width="4" '
                 f'stroke-linecap="round" stroke-dasharray="{circ * p["share"] / 100:.1f} {circ:.1f}" '
                 f'transform="rotate(-90 {rx:.1f} {ry})"/>')
        o.append(f'<text x="{rx:.1f}" y="{ry + 4}" text-anchor="middle" font-family="{MONO}" font-size="10" fill="{TEXT}">{p["share"]}%</text>')
        o.append(f'<text x="{rx:.1f}" y="{ry + rr + 13}" text-anchor="middle" font-family="{SANS}" font-size="8.5" fill="{MUTED}">{esc(p["language"])}</text>')

        tx = cx + 14
        for t in p["tags"][:2]:
            tw = text_w(t, 9.5) + 14
            o.append(f'<rect x="{tx:.1f}" y="{cy + 74}" width="{tw:.0f}" height="17" rx="8.5" fill="none" stroke="{TEAL}" stroke-opacity=".45"/>')
            o.append(f'<text x="{tx + 7:.1f}" y="{cy + 86}" font-family="{SANS}" font-size="9.5" fill="{MINT}">{esc(t)}</text>')
            tx += tw + 6
        o.append(icon("star", cx + 13, cy + 97, MUTED, 0.7))
        o.append(f'<text x="{cx + 28:.1f}" y="{cy + 107}" font-family="{SANS}" font-size="10" fill="{MUTED}">{p["stars"]}  ·  {ago(p["pushed"])}</text>')
        o.append("</g>")
    o.append("</svg>\n")
    return "\n".join(o)


# ---------------------------------------------------------------- main
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

    ASSETS.mkdir(exist_ok=True)
    for name, fn in [("header.svg", render_header), ("city.svg", render_city), ("panels.svg", render_panels)]:
        (ASSETS / name).write_text(fn(cfg, data), encoding="utf-8")
        print(f"wrote assets/{name}")


if __name__ == "__main__":
    main()
