# Profile dashboard setup

Everything in this folder becomes the root of a new repository named exactly `Jawad-Official`. GitHub shows that repository's `README.md` on your profile page.

```mermaid
flowchart LR
    cfg[config.json<br/>name, role, facts, featured repos] --> gen
    av[avatar/pixels.json<br/>halftone portrait] --> gen
    api[(GitHub GraphQL API<br/>repos, stars, calendar, languages)] --> gen
    gen[scripts/generate.py<br/>stdlib only] --> h[assets/header.svg]
    gen --> c[assets/city.svg]
    gen --> p[assets/panels.svg]
    gen --> b[assets/btn-*.svg]
    h & c & p & b --> readme[README.md<br/>profile page]
    cron[GitHub Action<br/>daily 03:17 UTC + on push] --> gen
```

## 1. Create the repository

1. Go to https://github.com/new.
2. Name it `Jawad-Official` (must match your username). Public. No template files.
3. GitHub shows a "special repository" notice. That confirms it.

## 2. Copy this folder in

```bash
git clone https://github.com/Jawad-Official/Jawad-Official.git
```

```bash
cp -r github-profile/. Jawad-Official/
```

```bash
cd Jawad-Official && git add -A && git commit -m "feat: profile dashboard" && git push
```

The push triggers the workflow, which replaces the sample numbers in `assets/*.svg` with your live data within about a minute.

## 3. Allow the Action to push

Repository Settings, Actions, General, Workflow permissions: select **Read and write permissions**. Save.

Then run it once by hand: Actions tab, "Update profile dashboard", **Run workflow**.

## 4. Optional: count private contributions

The default `GITHUB_TOKEN` only sees public activity.

1. Create a classic personal access token with the `read:user` scope.
2. Add it as a repository secret named `PROFILE_TOKEN`.
3. On your profile, enable "Include private contributions on my profile".

## Customise

| What | Where |
| --- | --- |
| Name, role, tagline, facts, stack line | `config.json` |
| Selected work (up to 4 public repos), descriptions, tags | `config.json` `featured` |
| Repos left out of the stats | `config.json` `exclude_repos` |
| Link buttons | `config.json` `links` and `README.md` |
| Languages to hide (HTML, CSS, ...) | `config.json` `exclude_languages` |
| Colours | constants at the top of `scripts/generate.py` |
| Avatar | see below |

## Avatar

The header portrait is an LED dot matrix: every cell is a dot, empty cells glow dimly and coloured stars twinkle around the head. It prints in line by line, blinks every few seconds and a soft light sweeps over it.

The picture comes from `avatar/portrait.svg`, a flat cel-shaded illustration with one-dot outlines. `avatar/portrait.png` is that SVG rendered at 4x, and `scripts/make_avatar.py` turns it into `avatar/pixels.json` (64 x 77 dots). Each dot takes the dominant flat colour of its cell, so edges stay crisp.

After editing the SVG, re-render the PNG (any SVG renderer at 1000 x 1204 px) and run:

```bash
python scripts/make_avatar.py
```

Use your own photo instead:

```bash
pip install pillow
```

```bash
python scripts/make_avatar.py path/to/photo.png --style photo --eyes 0.38,0.45,0.62,0.45
```

`--eyes` is optional: the normalised x,y of each eye centre, used for the blink. A transparent PNG cut-out works best. Commit `avatar/pixels.json` and the Action re-renders the header.

## Spacing

Every card follows one grid, set at the top of `scripts/generate.py`:

| Constant | Meaning |
| --- | --- |
| `GAP` | space between neighbouring cards and link buttons (~10 px on GitHub) |
| `PAD` | transparent margin above and below each card; controls the vertical gap |
| `IN_L`, `IN_R` | inner content edges shared by every card (30 px padding) |

## Preview locally

```bash
python scripts/generate.py --demo
```

Renders with sample data, no token needed, into `preview/` (git-ignored). Sample numbers never touch `assets/`, so they cannot reach your profile.

With live data:

```bash
GH_TOKEN=<your token> python scripts/generate.py
```
