"""Build the README artwork for PullStar — "Registration", a two-colour riso run.

    uv run --with fonttools python scripts/readme_art/build.py

Every image is a *pull* (one impression from the press). Each is printed in two
inks — riso Blue and Fluorescent Pink — as separate plates that overprint with
multiply. In motion, the plates arrive misregistered and spring into register,
which is what PullStar does to night-sky frames. The night is solid blue ink;
star trails are knocked out to bare paper.

Writes `docs/images/readme/*-motion.svg` (CSS animation, no scripts) and
`*-still.svg` (the registered final impression) for prefers-reduced-motion.
Text is converted to glyph outlines because SVG images on GitHub cannot load
web fonts. Geometry is seeded, so builds are reproducible.
"""
from __future__ import annotations

import math
import re
import sys
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from typeset import Face  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "images" / "readme"
VERSION = re.search(r'^version\s*=\s*"([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M).group(1)

# ---------------------------------------------------------------- inks & paper
PAPER = "#f3eee4"
PAPER_EDGE = "#e6dfd1"
BLUE = "#0078bf"      # Riso Blue
PINK = "#ff48b0"      # Riso Fluorescent Pink
# Final misregistration of the pink plate: real riso is never perfect.
RESID = (1.6, 1.1)


@lru_cache(None)
def display() -> Face:
    return Face("BigShouldersDisplay[wght].ttf", {"wght": 900})


@lru_cache(None)
def mono() -> Face:
    return Face("SpaceMono-Regular.ttf")


@lru_cache(None)
def mono_b() -> Face:
    return Face("SpaceMono-Bold.ttf")


@lru_cache(None)
def italic() -> Face:
    return Face("Fraunces-Italic[SOFT,WONK,opsz,wght].ttf", {"opsz": 72, "SOFT": 100, "WONK": 1, "wght": 380})


# ---------------------------------------------------------------- helpers
def mulberry32(seed: int):
    s = seed & 0xFFFFFFFF

    def rnd() -> float:
        nonlocal s
        s = (s + 0x6D2B79F5) & 0xFFFFFFFF
        t = s
        t = ((t ^ (t >> 15)) * (1 | t)) & 0xFFFFFFFF
        t = (t + (((t ^ (t >> 7)) * (61 | t)) & 0xFFFFFFFF) ^ t) & 0xFFFFFFFF
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296

    return rnd


def f(v: float) -> str:
    s = f"{v:.1f}"
    return s[:-2] if s.endswith(".0") else s


def spring_keyframes(name: str, k: float = 5.0, w: float = 13.0, steps: int = 28) -> str:
    """Damped spring baked to keyframes. Settles on (--ex, --ey) rather than zero."""
    rows = []
    for i in range(steps + 1):
        t = i / steps
        d = 0.0 if i == steps else math.exp(-t * k) * math.cos(t * w)
        rows.append(
            f"{t*100:.1f}%{{transform:translate(calc(var(--ex,0px) + var(--dx)*{d:.3f}),"
            f"calc(var(--ey,0px) + var(--dy)*{d:.3f})) rotate(calc(var(--r)*{d:.3f}))}}"
        )
    return f"@keyframes {name}{{{''.join(rows)}}}"


PL = ' pathLength="1"'
REDUCED = "@media (prefers-reduced-motion:reduce){*{animation:none!important}}"
COMMON = ("@keyframes fade{from{opacity:0}to{opacity:1}}"
          "@keyframes draw{from{stroke-dashoffset:1}to{stroke-dashoffset:0}}"
          "@keyframes stamp{0%{opacity:0;transform:scale(1.5) rotate(var(--sr,0deg))}"
          "60%{opacity:1;transform:scale(.96) rotate(var(--sr,0deg))}100%{opacity:1;transform:scale(1) rotate(var(--sr,0deg))}}"
          ".mul{mix-blend-mode:multiply}")


def svg(w: int, h: int, title: str, body: str, style: str, motion: bool) -> str:
    css = f"<style>{COMMON}{style if motion else ''}{REDUCED}</style>"
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
            f'role="img" aria-labelledby="t"><title id="t">{title}</title>{css}{body}</svg>\n')


def text(face: Face, s: str, x, y, size, fill, anchor="start", tracking=0.0, extra="") -> str:
    return f'<path d="{face.text_path(s, size, x, y, tracking=tracking, anchor=anchor)}" fill="{fill}"{extra}/>'


def mono_t(s, x, y, size=13, fill=BLUE, anchor="start", tracking=0.6, bold=False, extra=""):
    return text(mono_b() if bold else mono(), s, x, y, size, fill, anchor, tracking, extra)


def cls(motion: bool, name: str, delay: float) -> str:
    return f' class="{name}" style="animation-delay:{delay:.2f}s"' if motion else ""


def arc(cx, cy, r, a0, a1) -> str:
    x0, y0 = cx + r * math.cos(a0), cy + r * math.sin(a0)
    x1, y1 = cx + r * math.cos(a1), cy + r * math.sin(a1)
    large = 1 if abs(a1 - a0) > math.pi else 0
    return f"M{f(x0)} {f(y0)}A{f(r)} {f(r)} 0 {large} 0 {f(x1)} {f(y1)}"


def reg_mark(x, y, r=11, color=BLUE) -> str:
    return (f'<g fill="none" stroke="{color}" stroke-width="1.1"><circle cx="{f(x)}" cy="{f(y)}" r="{r}"/>'
            f'<circle cx="{f(x)}" cy="{f(y)}" r="{r*0.45:.1f}" fill="{color}" stroke="none"/>'
            f'<path d="M{f(x-r*1.7)} {f(y)}H{f(x+r*1.7)}M{f(x)} {f(y-r*1.7)}V{f(y+r*1.7)}"/></g>')


def crop_marks(W, H, m=18, L=14, color=BLUE) -> str:
    d = ""
    for x, y, sx, sy in ((m, m, 1, 1), (W - m, m, -1, 1), (m, H - m, 1, -1), (W - m, H - m, -1, -1)):
        d += f"M{x - sx*L} {y}H{x - sx*3}M{x} {y - sy*L}V{y - sy*3}"
    return f'<path d="{d}" stroke="{color}" stroke-width="1" fill="none"/>'


def paper(W, H, seed=1) -> str:
    """Paper stock: warm sheet, soft vignette, fibre grain."""
    return (f'<defs><filter id="grain{seed}" x="0" y="0" width="100%" height="100%">'
            f'<feTurbulence type="fractalNoise" baseFrequency=".85" numOctaves="2" seed="{seed}"/>'
            f'<feColorMatrix values="0 0 0 0 .35  0 0 0 0 .3  0 0 0 0 .25  0 0 0 -1.1 .62"/></filter>'
            f'<radialGradient id="vig{seed}" cx=".5" cy=".45" r=".75"><stop offset=".6" stop-color="{PAPER}" stop-opacity="0"/>'
            f'<stop offset="1" stop-color="{PAPER_EDGE}"/></radialGradient></defs>'
            f'<rect width="{W}" height="{H}" rx="6" fill="{PAPER}"/>'
            f'<rect width="{W}" height="{H}" rx="6" fill="url(#vig{seed})"/>'
            f'<rect width="{W}" height="{H}" rx="6" filter="url(#grain{seed})" opacity=".55"/>')


def speckle(W, H, seed=1) -> str:
    """Ink voids: sparse paper-coloured specks over everything, as in a real riso pull."""
    return (f'<defs><filter id="sp{seed}" x="0" y="0" width="100%" height="100%">'
            f'<feTurbulence type="fractalNoise" baseFrequency="1.6" numOctaves="1" seed="{seed+7}"/>'
            f'<feColorMatrix values="0 0 0 0 .953  0 0 0 0 .933  0 0 0 0 .894  0 0 0 9 -6.2"/></filter></defs>'
            f'<rect width="{W}" height="{H}" filter="url(#sp{seed})" opacity=".7"/>')


def halftone_ring(cx, cy, r, color, step=7.0, seed=3, reach=1.42) -> str:
    """Halftone fall-off around a solid disc: dot size shrinks with distance."""
    rnd = mulberry32(seed)
    out = []
    R = r * reach
    y, row = cy - R, 0
    while y <= cy + R:
        x = cx - R + (step / 2 if row % 2 else 0)
        while x <= cx + R:
            d = math.hypot(x - cx, y - cy)
            if r * 0.96 < d < R:
                t = 1 - (d - r) / (R - r)
                rad = step * 0.5 * max(0, t) ** 1.2 * (0.9 + 0.2 * rnd())
                if rad > 0.35:
                    out.append(f'<circle cx="{f(x)}" cy="{f(y)}" r="{rad:.2f}"/>')
            x += step
        y += step * 0.866
        row += 1
    return f'<g fill="{color}">{"".join(out)}</g>'


def plates(motion: bool, blue: str, pink: str, origin, delay=0.15,
           blue_off=(-20, 12, -1.4), pink_off=(18, -14, 1.2)) -> str:
    """The two ink plates, multiplied onto paper. In motion they spring into register."""
    if not motion:
        return (f'<g class="mul">{blue}</g>'
                f'<g class="mul" transform="translate({RESID[0]} {RESID[1]})">{pink}</g>')
    ox, oy = origin
    bx, by, br = blue_off
    px, py, pr = pink_off
    common = f"transform-origin:{f(ox)}px {f(oy)}px;animation-delay:{delay:.2f}s"
    return (f'<g class="mul plate" style="--dx:{bx}px;--dy:{by}px;--r:{br}deg;{common}">{blue}</g>'
            f'<g class="mul plate" style="--dx:{px}px;--dy:{py}px;--r:{pr}deg;'
            f'--ex:{RESID[0]}px;--ey:{RESID[1]}px;{common}">{pink}</g>')


PLATE_CSS = spring_keyframes("reg") + ".plate{transform-box:view-box;animation:reg 2.1s linear both}"
TRAIL_CSS = ".trl path{stroke-dasharray:1;animation:draw 3.8s cubic-bezier(.3,.6,.2,1) var(--d) both}"


def night_disc(cx, cy, r, seed, n, trail_deg, motion, mid, delay, stroke=(0.8, 2.6), rmin=8, pink_share=0.0):
    """Solid blue sky with trails knocked out to paper (mask), plus optional pink trails."""
    rnd = mulberry32(seed)
    knock, pinks = [], []
    trail = math.radians(trail_deg)
    for _ in range(n):
        rr = rmin + (r - rmin) * math.sqrt(rnd())
        a = rnd() * math.tau
        w = stroke[0] + (stroke[1] - stroke[0]) * rnd() ** 2.2
        d = arc(cx, cy, rr, a, a - trail)
        if rnd() < pink_share:
            pinks.append(f'<path{PL if motion else ""} d="{d}" stroke-width="{f(w*1.15)}"/>')
        else:
            knock.append(f'<path{PL if motion else ""} d="{d}" stroke-width="{f(w)}"/>')
    tr = f' class="trl" style="--d:{delay:.2f}s"' if motion else ""
    box = f'x="{f(cx-r-4)}" y="{f(cy-r-4)}" width="{f(2*r+8)}" height="{f(2*r+8)}"'
    mask = (f'<mask id="{mid}" maskUnits="userSpaceOnUse" {box}><rect {box} fill="#fff"/>'
            f'<g{tr} fill="none" stroke="#000" stroke-linecap="round">{"".join(knock)}</g></mask>')
    blue = f'<defs>{mask}</defs><circle cx="{f(cx)}" cy="{f(cy)}" r="{f(r)}" fill="{BLUE}" mask="url(#{mid})"/>'
    pink = f'<g{tr} fill="none" stroke="{PINK}" stroke-linecap="round">{"".join(pinks)}</g>' if pinks else ""
    return blue, pink


def pole(cx, cy, s=9, color=PINK) -> str:
    return (f'<path d="M{f(cx-s)} {f(cy)}H{f(cx+s)}M{f(cx)} {f(cy-s)}V{f(cy+s)}" stroke="{color}" stroke-width="1.6"/>'
            f'<circle cx="{f(cx)}" cy="{f(cy)}" r="{f(s*0.55)}" fill="none" stroke="{color}" stroke-width="1.2"/>')


def slug(W, left, right, y=42) -> str:
    return mono_t(left, 44, y, 12, BLUE, tracking=1.2) + mono_t(right, W - 44, y, 12, BLUE, "end", 1.2)


def rubber_stamp(motion, cx, cy, w, h, big, small, rot, big_size=22) -> str:
    attrs = (' class="stp" style="transform-box:fill-box;transform-origin:center;--sr:%sdeg"' % rot) if motion \
        else f' transform="rotate({rot} {f(cx)} {f(cy)})"'
    return (f'<g{attrs}><rect x="{f(cx-w/2)}" y="{f(cy-h/2)}" width="{w}" height="{h}" rx="6" fill="none" '
            f'stroke="{PINK}" stroke-width="2.4"/>'
            + mono_t(big, cx, cy + big_size * 0.12, big_size, PINK, "middle", 3, True)
            + mono_t(small, cx, cy + h / 2 - 10, 10.5, PINK, "middle", 1.4) + "</g>")


# ================================================================ PULL 01 — HERO
def hero(motion: bool) -> str:
    W, H = 1200, 700
    CX, CY, R = 884, 356, 236
    sky_b, sky_p = night_disc(CX, CY, R, 1002, 150, 54, motion, "hm", 2.0, (0.7, 2.8), pink_share=0.07)
    halo = halftone_ring(CX, CY, R, BLUE, step=7.2, seed=4, reach=1.26)

    size, trk, wx, wy = 300, -4, 48, 412
    wpath = display().text_path("PULLSTAR", size, wx, wy, tracking=trk)
    ww = display().width("PULLSTAR", size, trk)

    tag_y, tag_s = 488, 50
    t1 = "Align the night."
    t2x = 52 + italic().width(t1 + " ", tag_s)

    cols = [("STEADIER", "EXPOSURES"), ("SMOOTHER", "STAR TRAILS"), ("YOUR", "WORKFLOW")]
    col_t = "".join(mono_t(a, 54 + i * 168, 548, 13, BLUE, tracking=1.4, bold=True)
                    + mono_t(b, 54 + i * 168, 568, 13, BLUE, tracking=1.4) for i, (a, b) in enumerate(cols))

    bx0, by0 = 44, H - 58
    blue_bars = "".join(f'<rect x="{bx0 + i*26}" y="{by0}" width="22" height="14" fill="{BLUE}" fill-opacity="{o}"/>'
                        for i, o in enumerate((1, .55, .25)))
    pink_bars = "".join(f'<rect x="{bx0 + (i+3)*26}" y="{by0}" width="22" height="14" fill="{PINK}" fill-opacity="{o}"/>'
                        for i, o in enumerate((1, .55, .25)))
    over = lambda c: f'<rect x="{bx0 + 6*26}" y="{by0}" width="22" height="14" fill="{c}"/>'  # noqa: E731

    regs = [(30, H / 2), (W - 30, H / 2), (W / 2, 22), (W / 2, H - 22)]
    blue = (halo + sky_b
            + f'<path d="{wpath}" fill="{BLUE}"/>'
            + "".join(reg_mark(x, y, 9, BLUE) for x, y in regs)
            + crop_marks(W, H)
            + blue_bars + over(BLUE)
            + text(italic(), t1, 52, tag_y, tag_s, BLUE)
            + col_t
            + slug(W, f"PULLSTAR {VERSION} — PULL 01 / 05", "TWO-COLOUR RISO · BLUE + FLUORESCENT PINK")
            + mono_t("STAR-FIELD MATCHING · POLARIS OPTIONAL · LOCAL · NO UPLOAD", bx0 + 7*26 + 14, H - 46, 12, BLUE, tracking=1.1)
            + mono_t("MACOS 14+ · APPLE SILICON", W - 44, H - 46, 12, BLUE, "end", 1.1))
    pink = (f'<path d="{wpath}" fill="{PINK}"/>'
            + sky_p + pole(CX, CY)
            + "".join(reg_mark(x, y, 9, PINK) for x, y in regs)
            + pink_bars + over(PINK)
            + text(italic(), "Keep the motion.", t2x, tag_y, tag_s, PINK))

    nx, ny = 330, 120
    note = (f'<g{cls(motion, "note", 2.4)}>' + text(italic(), "in register", nx, ny, 30, PINK)
            + f'<path d="M{nx+150} {ny-6}C{nx+196} {ny-12} {nx+222} {ny+14} {nx+226} {ny+58}M{nx+215} {ny+46}L{nx+226} {ny+60}L{nx+236} {ny+45}" '
              f'fill="none" stroke="{PINK}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></g>')
    stamp = rubber_stamp(motion, 640, 560, 184, 62, "ALIGNED", "WOBBLE → 0 PX", -6)

    style = (PLATE_CSS + TRAIL_CSS + ".note{animation:fade .6s ease-out both}"
             ".stp{animation:stamp .45s cubic-bezier(.3,1.4,.5,1) 5.6s both}")
    body = (paper(W, H, 1) + plates(motion, blue, pink, (W / 2, H / 2))
            + f'<g class="mul">{note}{stamp}</g>' + speckle(W, H, 1))
    return svg(W, H, "PullStar — Align the night. Keep the motion. A two-colour risograph print: the blue and pink "
                     "plates arrive misregistered and spring into register, then star trails are knocked out of a "
                     "solid blue night sky.", body, style, motion)


# ================================================================ PULL 02 — HOW IT WORKS
def shift_path(d: str, dx: float, dy: float) -> str:
    out, i = [], 0
    for tok in re.findall(r"[MLZ]|-?\d+(?:\.\d+)?", d):
        if tok in "MLZ":
            out.append(tok)
            continue
        out.append(f(float(tok) + (dx if i % 2 == 0 else dy)) + (" " if i % 2 == 0 else ""))
        i += 1
    return "".join(out)


def pipeline(motion: bool) -> str:
    W, H = 1200, 500
    steps = [("01", "Load", "the sequence", "RAW · TIFF · PNG · JPEG"),
             ("02", "Match", "the stars", "POLARIS OPTIONAL"),
             ("03", "Remove", "the wobble", "SKY ROTATION KEPT"),
             ("04", "Finish", "your way", "FRAMES · TRAILS · VIDEO")]
    CWD, X0, TOP = 280, 54, 96
    rnd = mulberry32(9)
    field = [(rnd() * 170 + 25, rnd() * 140 + 20, 1.6 + rnd() * 2.4) for _ in range(13)]
    T = 1.05
    blue, pink = [], []
    for i, (num, verb, rest, sub) in enumerate(steps):
        x = X0 + i * CWD
        bx, by, bw, bh = x, TOP + 70, 230, 180
        cx, cy = bx + bw / 2, by + bh / 2

        def dots(ox=0.0, oy=0.0):
            return "".join(f'<circle cx="{f(bx + px + ox)}" cy="{f(by + py + oy)}" r="{f(r)}"/>' for px, py, r in field)

        blue.append(f'<g{cls(motion, "in", i*T)}>'
                    + text(italic(), verb, x, TOP + 296, 38, BLUE)
                    + text(italic(), rest, x, TOP + 330, 26, BLUE)
                    + mono_t(sub, x + 2, TOP + 362, 12, BLUE, tracking=1.3)
                    + f'<rect x="{bx}" y="{by}" width="{bw}" height="{bh}" fill="none" stroke="{BLUE}" stroke-width="1.2"/></g>')
        pink.append(f'<g{cls(motion, "in", i*T)}>' + text(display(), num, x - 4, TOP + 58, 96, PINK, tracking=-2) + "</g>")
        if i == 0:
            for j, (dx, dy, rt) in enumerate([(-12, -10, -4), (2, -2, 3), (12, 9, -1.5)]):
                blue.append(
                    f'<g transform="rotate({rt} {f(cx)} {f(cy)}) translate({dx} {dy})"><g{cls(motion, "in", 0.2 + j*0.18)}>'
                    f'<rect x="{f(bx+40)}" y="{f(by+38)}" width="150" height="104" fill="{PAPER}" stroke="{BLUE}" stroke-width="1.2"/>'
                    f'<g fill="{BLUE}">' + "".join(
                        f'<circle cx="{f(bx+48+px*0.78)}" cy="{f(by+44+py*0.62)}" r="{f(r*0.55)}"/>' for px, py, r in field)
                    + "</g></g></g>")
        elif i == 1:
            gr = mulberry32(19)
            grid = [(36 + gx * 62 + gr() * 34, 24 + gy * 46 + gr() * 26, 1.6 + gr() * 2.2) for gy in range(3) for gx in range(3)]

            def dots(ox=0.0, oy=0.0, pts=grid):  # noqa: F811
                return "".join(f'<circle cx="{f(bx + px + ox)}" cy="{f(by + py + oy)}" r="{f(r)}"/>' for px, py, r in pts)
            pts = [(bx + px, by + py) for px, py, _ in grid]
            tri_d = "".join(f"M{f(pts[a][0])} {f(pts[a][1])}L{f(pts[b][0])} {f(pts[b][1])}L{f(pts[c][0])} {f(pts[c][1])}Z"
                            for a, b, c in ((0, 1, 3), (4, 5, 8), (6, 7, 4)))
            blue.append(f'<g{cls(motion, "in", i*T)}><g fill="{BLUE}">{dots()}</g>'
                        f'<path d="{tri_d}" fill="none" stroke="{BLUE}" stroke-width="1"/></g>')
            pink.append(f'<g{cls(motion, "in", i*T + .2)}><g fill="{PINK}">{dots(9, 7)}</g></g>'
                        f'<path{PL if motion else ""}{cls(motion, "ln", i*T + .6)} d="{shift_path(tri_d, 9, 7)}" '
                        f'fill="none" stroke="{PINK}" stroke-width="1.3"/>'
                        f'<g{cls(motion, "pop", i*T + 1.2)}>' + mono_t("MATCHED", bx + bw - 10, by + bh - 12, 12, PINK, "end", 1.2, True) + "</g>")
        elif i == 2:
            if motion:
                o = f"transform-origin:{f(cx)}px {f(cy)}px;animation-delay:{i*T+.3:.2f}s"
                blue.append(f'<g class="mul cv" style="--dx:-14px;--dy:-10px;--r:-5deg;{o}"><g fill="{BLUE}">{dots()}</g></g>')
                pink.append(f'<g class="mul cv" style="--dx:14px;--dy:10px;--r:4deg;--ex:{RESID[0]}px;--ey:{RESID[1]}px;{o}">'
                            f'<g fill="{PINK}">{dots()}</g></g>')
            else:
                blue.append(f'<g fill="{BLUE}">{dots()}</g>')
                pink.append(f'<g fill="{PINK}" transform="translate({RESID[0]} {RESID[1]})">{dots()}</g>')
            pink.append(f'<g{cls(motion, "pop", i*T + 2.0)}>' + mono_t("OFFSET 0 PX", bx + bw - 10, by + bh - 12, 12, PINK, "end", 1.2, True) + "</g>")
        else:
            sb, sp = night_disc(cx, cy, 80, 55, 34, 80, motion, "pm", i*T + .3, (0.8, 2.2), rmin=6, pink_share=0.1)
            blue.append(f'<g{cls(motion, "in", i*T)}>{sb}</g>')
            pink.append(f'<g{cls(motion, "in", i*T)}>{sp}{pole(cx, cy, 7)}</g>')
        if i < 3:
            ax = bx + bw + 12
            pink.append(f'<g{cls(motion, "in", i*T + .6)}><path d="M{ax} {f(cy)}h26m-8 -7l8 7-8 7" fill="none" '
                        f'stroke="{PINK}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></g>')
    style = (spring_keyframes("cv", k=4.6, w=12) + TRAIL_CSS
             + ".in{animation:fade .5s ease-out both}.pop{animation:fade .3s steps(2) both}"
             ".ln{stroke-dasharray:1;animation:draw .8s ease-out both}"
             ".cv{transform-box:view-box;animation:cv 1.7s linear both}")
    body = (paper(W, H, 2)
            + '<g class="mul">' + crop_marks(W, H)
            + slug(W, f"PULLSTAR {VERSION} — PULL 02 / 05", "HOW IT WORKS · CORRECT THE CAMERA, NOT THE SKY")
            + "".join(blue) + "</g>"
            + '<g class="mul">' + "".join(pink) + "</g>" + speckle(W, H, 2))
    return svg(W, H, "How PullStar works: 01 load the sequence, 02 match the star field (Polaris optional), "
                     "03 remove the camera wobble while keeping sky rotation, 04 export frames, trails, or video.",
               body, style, motion)


# ================================================================ PULL 03 — FINISHES
def finishes(motion: bool) -> str:
    W, H = 1200, 520
    PW, X0, TOP = 352, 44, 96
    blue, pink = [], []
    cards = [("A", "Aligned", "frames", "TIFF · PNG · JPEG · 16-BIT", "FOR ANOTHER EDITOR"),
             ("B", "Trail", "image", "TIFF · PNG · JPEG · GAP FILL", "A FINISHED STILL"),
             ("C", "Trail", "video", "MP4 · MOV · HEVC · PRORES", "TRAIL-LAPSE, FRAME BY FRAME")]
    for i, (letter, a, b, fmt, kick) in enumerate(cards):
        x = X0 + i * (PW + 30)
        y0, art_h = TOP + 18, 238
        cx, cy = x + PW / 2, y0 + art_h / 2
        blue.append(f'<rect x="{x}" y="{y0}" width="{PW}" height="{art_h}" fill="none" stroke="{BLUE}" stroke-width="1.2"/>')
        blue.append(mono_t(kick, x + PW, TOP + 4, 12, BLUE, "end", 1.3))
        pink.append(text(display(), letter, x, TOP + 8, 40, PINK))
        blue.append(text(display(), a.upper(), x, y0 + art_h + 76, 64, BLUE, tracking=-1))
        pink.append(text(italic(), b, x + display().width(a.upper() + " ", 64, -1), y0 + art_h + 76, 50, PINK))
        blue.append(mono_t(fmt, x + 1, y0 + art_h + 108, 12, BLUE, tracking=1.3))
        if i == 0:
            rnd = mulberry32(12)
            pts = [(rnd() * 170, rnd() * 104, 1.2 + rnd() * 1.8) for _ in range(16)]
            offs = [(-34, -18, -6), (-14, -6, 4), (16, 10, -3), (36, 20, 5)]
            frame = (f'<rect x="{f(cx-100)}" y="{f(cy-66)}" width="200" height="132" fill="none" stroke="{BLUE}" stroke-width="1.1"/>'
                     f'<g fill="{BLUE}">' + "".join(f'<circle cx="{f(cx-85+px)}" cy="{f(cy-52+py)}" r="{f(r)}"/>' for px, py, r in pts) + "</g>")
            ghosts = "".join(f'<rect x="{f(cx-100)}" y="{f(cy-66)}" width="200" height="132" fill="none" stroke="{BLUE}" '
                             f'stroke-opacity=".4" stroke-dasharray="2 4" transform="translate({ox} {oy}) rotate({rr} {f(cx)} {f(cy)})"/>'
                             for ox, oy, rr in offs)
            blue.append(ghosts)
            if motion:
                blue.extend(f'<g class="mul sl" style="--dx:{dx}px;--dy:{dy}px;--r:{rt}deg;transform-origin:{f(cx)}px {f(cy)}px;'
                            f'animation-delay:{0.4 + j*0.1:.2f}s;opacity:{.3 + j*.12:.2f}">{frame}</g>'
                            for j, (dx, dy, rt) in enumerate(offs))
            else:
                blue.append(frame)
            pink.append(f'<g{cls(motion, "pop", 2.4)}><rect x="{f(cx-94)}" y="{f(cy-60)}" width="188" height="120" fill="none" '
                        f'stroke="{PINK}" stroke-width="1.6" stroke-dasharray="7 5"/>'
                        + mono_t("COMMON CROP", cx + 94, cy + 80, 11, PINK, "end", 1.2, True) + "</g>")
        elif i == 1:
            py_ = y0 + art_h * 0.62
            sb, sp = night_disc(cx, py_, 150, 21, 70, 70, motion, "fm", .5, (0.7, 2.4), rmin=8, pink_share=0.08)
            rr = mulberry32(11)
            ridge = " ".join(f"L{f(x + k*PW/24)} {f(y0 + art_h - 34 + math.sin(k*0.7)*8 + (rr()-.5)*12)}" for k in range(25))
            land = f"M{x} {y0+art_h} {ridge} L{x+PW} {y0+art_h}Z"
            blue.append(f'<defs><clipPath id="fc"><rect x="{x}" y="{y0}" width="{PW}" height="{art_h}"/></clipPath></defs>'
                        f'<g clip-path="url(#fc)">{sb}<path d="{land}" fill="{BLUE}"/></g>')
            pink.append(f'<g clip-path="url(#fc)">{sp}<path d="{land}" fill="{PINK}"/></g>' + pole(cx, py_, 7)
                        + f'<g{cls(motion, "pop", 3.6)}>' + mono_t("FOREGROUND", x + 10, y0 + 22, 11, PINK, tracking=1.2, bold=True) + mono_t("KEPT", x + 10, y0 + 38, 11, PINK, tracking=1.2, bold=True) + "</g>")
        else:
            n, fw, fh, gap = 4, 72, 58, 9
            sw = n * fw + (n - 1) * gap
            sx, sy = cx - sw / 2, cy - fh / 2 - 8
            holes = "".join(f'<rect x="{f(sx-8 + k*17)}" y="{f(yy)}" width="8" height="6" rx="1" fill="{PAPER}"/>'
                            for k in range(int((sw + 16) / 17) + 1) for yy in (sy - 17, sy + fh + 11))
            rnd = mulberry32(33)
            seeds = [(rnd() * 34 + 4, rnd() * math.tau) for _ in range(9)]
            cells = ""
            for k in range(n):
                fx = sx + k * (fw + gap)
                pcx, pcy = fx + fw / 2, sy + fh / 2
                arcs = "".join(f'<path d="{arc(pcx, pcy, r*0.8, a, a - (0.15 + k*0.5))}"/>' for r, a in seeds)
                cells += (f'<g{cls(motion, "in", .3 + k*.35)}><rect x="{f(fx)}" y="{f(sy)}" width="{fw}" height="{fh}" fill="{PAPER}"/>'
                          f'<clipPath id="vc{k}"><rect x="{f(fx)}" y="{f(sy)}" width="{fw}" height="{fh}"/></clipPath>'
                          f'<g clip-path="url(#vc{k})" fill="none" stroke="{BLUE}" stroke-width="1.4" stroke-linecap="round">{arcs}</g></g>')
            blue.append(f'<rect x="{f(sx-14)}" y="{f(sy-24)}" width="{f(sw+28)}" height="{fh+48}" fill="{BLUE}"/>' + holes + cells)
            bar_y = sy + fh + 54
            blue.append(f'<rect x="{f(sx-14)}" y="{f(bar_y)}" width="{f(sw+28)}" height="3" fill="{BLUE}" fill-opacity=".3"/>')
            pink.append(f'<rect{" class=" + chr(34) + "pb" + chr(34) if motion else ""} x="{f(sx-14)}" y="{f(bar_y)}" '
                        f'width="{f(sw+28)}" height="3" fill="{PINK}"/>'
                        + f'<path d="M{f(sx-14)} {f(bar_y-19)}l8 5-8 5Z" fill="{PINK}"/>'
                        + mono_t("PLAY", sx - 1, bar_y - 10, 11, PINK, tracking=1.2, bold=True))
    style = (spring_keyframes("sl", k=4.4, w=10) + TRAIL_CSS
             + "@keyframes pb{from{transform:scaleX(0)}to{transform:scaleX(1)}}"
             ".sl{transform-box:view-box;animation:sl 2s linear both}"
             ".in{animation:fade .35s ease-out both}.pop{animation:fade .35s steps(2) both}"
             ".pb{transform-box:fill-box;transform-origin:0 0;animation:pb 2.4s linear .3s both}")
    body = (paper(W, H, 3)
            + '<g class="mul">' + crop_marks(W, H) + slug(W, f"PULLSTAR {VERSION} — PULL 03 / 05", "CHOOSE YOUR FINISH")
            + "".join(blue) + "</g>"
            + '<g class="mul">' + "".join(pink) + "</g>" + speckle(W, H, 3))
    return svg(W, H, "Choose your finish: A, aligned frames as TIFF, PNG, or JPEG with a common crop; B, a trail image "
                     "with the foreground kept; C, a trail-lapse video as MP4 or MOV.", body, style, motion)


# ================================================================ PULL 04 — MCP JOB TICKET
def mcp(motion: bool) -> str:
    W, H = 1200, 600
    cols = [("INSPECT", ["inspect_sequence", "recommend_settings", "detect_and_analyze_stars",
                         "get_hardware_capabilities", "evaluate_alignment_settings"]),
            ("PREVIEW", ["compare_alignment_candidates", "render_preview_stack", "render_annotated_preview",
                         "evaluate_stack_quality", "auto_tune_and_stack"]),
            ("RUN", ["create_stack", "start_stack_job", "get_job_status", "cancel_job", "list_jobs"])]
    session = ["inspect_sequence", "recommend_settings", "render_preview_stack", "start_stack_job", "get_job_status"]
    blue, pink = [], []
    TX, TY, TW, TH = 44, 74, 1112, 460
    SX = TX + 300
    blue.append(f'<rect x="{TX}" y="{TY}" width="{TW}" height="{TH}" rx="10" fill="none" stroke="{BLUE}" stroke-width="1.4"/>'
                f'<path d="M{SX} {TY+16}V{TY+TH-16}" stroke="{BLUE}" stroke-width="1.4" stroke-dasharray="2 7" stroke-linecap="round"/>'
                f'<path d="M{SX-13} {TY}A13 13 0 0 0 {SX+13} {TY}M{SX-13} {TY+TH}A13 13 0 0 1 {SX+13} {TY+TH}" '
                f'fill="{PAPER}" stroke="{BLUE}" stroke-width="1.4"/>')
    blue.append(mono_t("JOB TICKET · MCP", TX + 30, TY + 44, 13, BLUE, tracking=1.6, bold=True))
    pink.append(text(display(), "15", TX + 22, TY + 280, 250, PINK, tracking=-6))
    blue.append(text(display(), "TOOLS", TX + 30, TY + 336, 58, BLUE, tracking=1))
    blue.append(text(italic(), "for your agent.", TX + 30, TY + 384, 34, BLUE))
    blue.append(mono_t("STDIO · SSE · STREAMABLE HTTP", TX + 30, TY + 428, 11, BLUE, tracking=1.2))
    CW = 262
    pos = {}
    for c, (head, tools) in enumerate(cols):
        x = SX + 40 + c * CW
        blue.append(mono_t(head, x, TY + 44, 12, BLUE, tracking=2, bold=True)
                    + f'<path d="M{x} {TY+58}H{x+CW-30}" stroke="{BLUE}" stroke-width="1"/>')
        for r, t in enumerate(tools):
            y = TY + 102 + r * 58
            pos[t] = (x, y)
            blue.append(f'<rect x="{x}" y="{y-13}" width="15" height="15" fill="none" stroke="{BLUE}" stroke-width="1.2"/>'
                        + mono_t(t, x + 24, y, 12.5, BLUE, tracking=0)
                        + f'<path d="M{x+24} {y+14}H{x+CW-30}" stroke="{BLUE}" stroke-width=".8" stroke-dasharray="1 3"/>')
    for k, t in enumerate(session):
        x, y = pos[t]
        d = 1.0 + k * 0.5
        pink.append(f'<path{PL if motion else ""}{cls(motion, "ck", d)} d="M{x+2} {y-6}l5 6 12-17" fill="none" stroke="{PINK}" '
                    f'stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>'
                    f'<g{cls(motion, "pop", d + .1)}><circle cx="{x-14}" cy="{y-6}" r="9" fill="{PINK}"/>'
                    + mono_t(str(k + 1), x - 14, y - 2, 11, PAPER, "middle", 0, True) + "</g>")
    pink.append(rubber_stamp(motion, W - 230, TY + TH - 44, 300, 62, "ONE AGENT SESSION", "START TO FINISH · 5 CALLS", -6, 16))
    style = (".ck{stroke-dasharray:1;animation:draw .35s ease-out both}.pop{animation:fade .2s steps(2) both}"
             ".stp{animation:stamp .45s cubic-bezier(.3,1.4,.5,1) 3.8s both}")
    body = (paper(W, H, 4)
            + '<g class="mul">' + crop_marks(W, H)
            + slug(W, f"PULLSTAR {VERSION} — PULL 04 / 05", "MODEL CONTEXT PROTOCOL · BUNDLED IN THE APP")
            + "".join(blue) + "</g>"
            + '<g class="mul">' + "".join(pink) + "</g>" + speckle(W, H, 4))
    return svg(W, H, "A job ticket for fifteen MCP tools. An example agent session ticks inspect_sequence, "
                     "recommend_settings, render_preview_stack, start_stack_job, and get_job_status.", body, style, motion)


# ================================================================ PULL 05 — FOOTER
def footer(motion: bool) -> str:
    W, H = 1200, 330
    word = display().text_path("CLEAR SKIES.", 190, 40, 220, tracking=-2)
    blue = (f'<path d="{word}" fill="{BLUE}"/>'
            + text(italic(), "Download PullStar and align your next night.", 46, 272, 34, BLUE)
            + mono_t(f"MACOS 14+ · APPLE SILICON · v{VERSION}", 48, 304, 12, BLUE, tracking=1.4)
            + reg_mark(W - 70, 82, 13, BLUE))
    pink = (f'<path d="{word}" fill="{PINK}"/>' + reg_mark(W - 70, 82, 13, PINK)
            + f'<path d="M{W-120} 282L{W-72} 234M{W-108} 234H{W-72}V270" fill="none" stroke="{PINK}" stroke-width="3" '
              f'stroke-linecap="round" stroke-linejoin="round"/>'
            + mono_t("GET IT", W - 128, 300, 12, PINK, "end", 1.6, True))
    if motion:  # a slow, endless press wobble on the pink plate: the only loop in the run
        plate = (f'<g class="mul">{blue}</g><g class="mul"><g class="drift" '
                 f'transform="translate({RESID[0]} {RESID[1]})">{pink}</g></g>')
    else:
        plate = plates(False, blue, pink, (0, 0))
    style = ("@keyframes drift{0%,100%{transform:translate(1.6px,1.1px)}25%{transform:translate(4px,-1px)}"
             "50%{transform:translate(.4px,2.6px)}75%{transform:translate(-1.6px,.4px)}}"
             ".drift{animation:drift 7s ease-in-out infinite}")
    body = (paper(W, H, 5)
            + '<g class="mul">' + crop_marks(W, H) + slug(W, f"PULLSTAR {VERSION} — PULL 05 / 05", "END OF RUN") + "</g>"
            + plate + speckle(W, H, 5))
    return svg(W, H, f"Clear skies. Download PullStar {VERSION} for macOS 14 or later on Apple Silicon.", body, style, motion)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.svg"):
        old.unlink()
    jobs = {"hero": hero, "pipeline": pipeline, "finishes": finishes, "mcp": mcp, "footer": footer}
    for name, fn in jobs.items():
        for motion in (True, False):
            (OUT / f"{name}-{'motion' if motion else 'still'}.svg").write_text(fn(motion))
    print(f"built {len(jobs)*2} svgs for PullStar {VERSION} → {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
