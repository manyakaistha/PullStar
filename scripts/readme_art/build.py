"""Build the README artwork for PullStar ("Long Exposure" plates).

    uv run --with fonttools python scripts/readme_art/build.py

Writes `docs/images/readme/*-motion.svg` (CSS animation, no scripts) and
`*-still.svg` (the settled final frame) used under prefers-reduced-motion.
Text is converted to glyph outlines (see typeset.py) because SVG images on
GitHub cannot load web fonts. Geometry is seeded, so builds are reproducible.
"""
from __future__ import annotations

import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from typeset import italic, mono, serif  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "images" / "readme"
VERSION = re.search(r'^version\s*=\s*"([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M).group(1)

# ---------------------------------------------------------------- palette
INK = "#05060a"
NIGHT = "#0a0f1c"
PAPER = "#f1ebde"
SOFT = "#c9c3b6"
MUTED = "#8a92a6"
DIM = "#4d5468"
AMBER = "#ffa64d"
BLUE = "#5aa2ff"
ORANGE = "#ff7a45"
STAR_TEMPS = ["#9dbcff", "#c2d5ff", "#e9edf7", "#fff0d6", "#ffd09a"]
STAR_WEIGHTS = [0.14, 0.22, 0.34, 0.18, 0.12]


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


def pick(rnd, items, weights):
    x, acc = rnd() * sum(weights), 0.0
    for item, w in zip(items, weights):
        acc += w
        if x <= acc:
            return item
    return items[-1]


def f(v: float) -> str:
    s = f"{v:.1f}"
    return s[:-2] if s.endswith(".0") else s


def spring_keyframes(name: str, k: float = 5.2, w: float = 14.0, steps: int = 24) -> str:
    """Damped spring baked to keyframes; displacement comes from per-element vars."""
    rows = []
    for i in range(steps + 1):
        t = i / steps
        d = 0.0 if i == steps else math.exp(-t * k) * math.cos(t * w)
        rows.append(
            f"{t*100:.1f}%{{transform:translate(calc(var(--dx)*{d:.3f}),calc(var(--dy)*{d:.3f}))"
            f" rotate(calc(var(--r)*{d:.3f}))}}"
        )
    return f"@keyframes {name}{{{''.join(rows)}}}"


PL = ' pathLength="1"'
REDUCED = "@media (prefers-reduced-motion:reduce){*{animation:none!important}}"
COMMON = ("@keyframes fade{from{opacity:0}to{opacity:1}}"
          "@keyframes draw{from{stroke-dashoffset:1}to{stroke-dashoffset:0}}"
          "@keyframes out{0%,80%{opacity:1}100%{opacity:0}}")


def svg(w: int, h: int, title: str, body: str, style: str = "") -> str:
    css = f"<style>{COMMON}{style}{REDUCED}</style>" if style else ""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
        f'role="img" aria-labelledby="t"><title id="t">{title}</title>{css}{body}</svg>\n'
    )


def mono_text(s, x, y, size=14, fill=MUTED, anchor="start", tracking=1.6, extra=""):
    return f'<path d="{mono().text_path(s, size, x, y, tracking=tracking, anchor=anchor)}" fill="{fill}"{extra}/>'


def serif_text(s, x, y, size, fill=PAPER, face=None, anchor="start", tracking=0.0, extra=""):
    d = (face or serif()).text_path(s, size, x, y, tracking=tracking, anchor=anchor)
    return f'<path d="{d}" fill="{fill}"{extra}/>'


def arrow(x, y, s=22, color=AMBER) -> str:
    return (f'<path d="M{f(x)} {f(y+s)} L{f(x+s)} {f(y)} M{f(x+s*0.32)} {f(y)} L{f(x+s)} {f(y)} '
            f'L{f(x+s)} {f(y+s*0.68)}" fill="none" stroke="{color}" stroke-width="2" '
            f'stroke-linecap="round" stroke-linejoin="round"/>')


def cls(motion: bool, name: str, style: str = "") -> str:
    if not motion:
        return ""
    return f' class="{name}"' + (f' style="{style}"' if style else "")


def arc(cx, cy, r, a0, a1) -> str:
    x0, y0 = cx + r * math.cos(a0), cy + r * math.sin(a0)
    x1, y1 = cx + r * math.cos(a1), cy + r * math.sin(a1)
    large = 1 if abs(a1 - a0) > math.pi else 0
    return f"M{f(x0)} {f(y0)}A{f(r)} {f(r)} 0 {large} 0 {f(x1)} {f(y1)}"


def ridge(w: float, base: float, seed: int, amp: float = 46.0, x0: float = 0.0) -> str:
    rr = mulberry32(seed)
    pts = [0.0, 0.0]
    for _ in range(7):
        nxt = []
        for a, b in zip(pts, pts[1:]):
            nxt += [a, (a + b) / 2 + (rr() - 0.5) * amp]
        nxt.append(pts[-1])
        pts, amp = nxt, amp * 0.56
    line = " ".join(f"L{f(x0 + i * w / (len(pts) - 1))} {f(base + v)}" for i, v in enumerate(pts))
    return line


def star_field(rnd, cx, cy, n, rmin, rmax):
    out = []
    for _ in range(n):
        r = rmin + (rmax - rmin) * math.sqrt(rnd())
        a = rnd() * math.tau
        c = pick(rnd, STAR_TEMPS, STAR_WEIGHTS)
        s = 0.6 + 1.7 * rnd() ** 2
        out.append((r, a, c, s))
    return out


# ================================================================ HERO
def hero(motion: bool) -> str:
    W, H = 1200, 600
    PX, PY = 930, 214
    TRAIL = math.radians(36)
    rnd = mulberry32(1002)
    stars = star_field(rnd, PX, PY, 300, 22, 980)
    faint, bright, glow, heads = [], [], [], []
    pl = ' pathLength="1"' if motion else ""
    for r, a, c, s in stars:
        d = arc(PX, PY, r, a, a - TRAIL)
        if s < 0.9:
            faint.append(f'<path{pl} d="{d}" stroke="{c}"/>')
            continue
        op = 0.45 + 0.5 * min(1, (s - 0.6) / 1.7)
        bright.append(f'<path{pl} d="{d}" stroke="{c}" stroke-width="{f(s)}" opacity="{op:.2f}"/>')
        if s > 1.6:
            glow.append(f'<path{pl} d="{d}" stroke="{c}" stroke-width="{f(s*3.2)}"/>')
        heads.append((PX + r * math.cos(a), PY + r * math.sin(a), s, c))

    # Shaken frames: the brightest star heads, doubled and wobbling, then locked.
    frames = ""
    lock = ""
    if motion:
        dots = "".join(f'<circle cx="{f(x)}" cy="{f(y)}" r="{f(s*1.2)}"/>' for x, y, s, _ in heads)
        offs = [(-30, 16, -2.6), (22, -19, 2.2), (-13, -26, -1.4), (27, 22, 3.0)]
        frames = '<g style="mix-blend-mode:screen" opacity=".75">' + "".join(
            f'<g class="fr" fill="{(BLUE, ORANGE)[i % 2]}" style="--dx:{dx}px;--dy:{dy}px;--r:{rt}deg;'
            f'animation-delay:{0.15 + 0.1*i:.2f}s">{dots}</g>' for i, (dx, dy, rt) in enumerate(offs)) + "</g>"
        lock = '<g class="lock">' + "".join(
            f'<circle cx="{f(x)}" cy="{f(y)}" r="{f(s*0.95)}" fill="{c}"/>' for x, y, s, c in heads) + "</g>"

    # Wordmark, glyph by glyph: each letter springs into register.
    gr = mulberry32(42)
    size, nx, ny = 236, 52, 318
    face = serif()
    glyphs, name_w = face.layout("PullStar", size)
    parts = []
    for k, (_, g, gx, _) in enumerate(glyphs):
        d = face.glyph_path(g, size, nx + gx, ny)
        if not motion:
            parts.append(f'<path d="{d}"/>')
            continue
        dx, dy, rot = (gr() - 0.5) * 46, (gr() - 0.5) * 34, (gr() - 0.5) * 14
        parts.append(f'<path class="g" style="--dx:{dx:.1f}px;--dy:{dy:.1f}px;--r:{rot:.1f}deg;'
                     f'animation-delay:{0.3 + k*0.07:.2f}s" d="{d}"/>')
    ghost = ""
    if motion:
        whole = face.text_path("PullStar", size, nx, ny)
        ghost = (f'<g style="mix-blend-mode:screen"><path class="gh a" d="{whole}" fill="{BLUE}"/>'
                 f'<path class="gh b" d="{whole}" fill="{ORANGE}"/></g>')

    # Reference-star annotation.
    rx, ry, rs, _ = max((h for h in heads if 700 < h[0] < 1120 and 300 < h[1] < 460), key=lambda h: h[2])
    ann = (f'<g{cls(motion, "ann")}><circle cx="{f(rx)}" cy="{f(ry)}" r="10" fill="none" stroke="{AMBER}" stroke-width="1.2"/>'
           f'<path d="M{f(rx+10)} {f(ry)}H{f(rx+44)}" stroke="{AMBER}" stroke-width="1"/>'
           + mono_text("REFERENCE LOCKED", rx + 50, ry - 4, 14, AMBER, tracking=1.2)
           + mono_text("ROTATION KEPT", rx + 50, ry + 16, 13, MUTED, tracking=1.1) + "</g>")

    pole = (f'<g stroke="{MUTED}" stroke-width="1" opacity=".7"><path d="M{PX-12} {PY}h8M{PX+4} {PY}h8'
            f'M{PX} {PY-12}v8M{PX} {PY+4}v8"/></g>' + mono_text("NCP", PX + 16, PY - 10, 11, DIM, tracking=1.4))

    style = ""
    if motion:
        style = (spring_keyframes("align") + spring_keyframes("wob", k=4.2, w=11)
                 + "@keyframes ghostA{0%{transform:translate(-14px,7px);opacity:.55}100%{transform:none;opacity:0}}"
                 "@keyframes ghostB{0%{transform:translate(12px,-9px);opacity:.45}100%{transform:none;opacity:0}}"
                 "@keyframes sat{0%{transform:translate(0,0);opacity:0}4%{opacity:.9}46%{opacity:.9}"
                 "50%,100%{transform:translate(1500px,-260px);opacity:0}}"
                 "@keyframes blink{0%,100%{opacity:1}50%{opacity:.25}}"
                 f".fr{{transform-box:view-box;transform-origin:{PX}px {PY}px;animation:wob 2.2s linear both,out 2.6s both}}"
                 ".lock{animation:fade .4s 2.1s both}"
                 ".sky path{stroke-dasharray:1;animation:draw 5.2s cubic-bezier(.22,.7,.2,1) 2.2s both}"
                 ".g{transform-box:fill-box;transform-origin:50% 60%;animation:align 1.9s linear both}"
                 ".gh{animation:1.7s cubic-bezier(.2,.8,.2,1) .25s both}.gh.a{animation-name:ghostA}.gh.b{animation-name:ghostB}"
                 ".ann{animation:fade .8s ease-out 5.4s both}"
                 ".stamp{animation:fade .5s steps(2) 2.4s both}"
                 ".pre{animation:out 2.4s both}"
                 ".sat{animation:sat 38s linear 8s infinite}.sat circle{animation:blink .9s steps(2) infinite}"
                 ".meta{animation:fade 1s ease-out .2s both}")
    sky = ' class="sky"' if motion else ""

    def group(items, attrs):
        return f'<g{sky} fill="none" stroke-linecap="round" {attrs}>{"".join(items)}</g>'

    ridge_d = f"M0 {H} {ridge(W, 548, 7)} L{W} {H}Z"
    status = (f'<g class="pre">{mono_text("UNALIGNED · 4 FRAMES · ±30 PX", W-40, 84, 15, MUTED, "end")}</g>'
              if motion else "")
    body = f"""
<defs>
<radialGradient id="sky" cx="{PX/W:.3f}" cy="{PY/H:.3f}" r="1.1"><stop offset="0" stop-color="#111a33"/><stop offset=".55" stop-color="{NIGHT}"/><stop offset="1" stop-color="{INK}"/></radialGradient>
<linearGradient id="glowH" x1="0" y1="0" x2="0" y2="1"><stop offset=".62" stop-color="#ff8a3d" stop-opacity="0"/><stop offset=".9" stop-color="#ff8a3d" stop-opacity=".16"/></linearGradient>
<radialGradient id="shade" cx=".26" cy=".5" r=".55"><stop offset="0" stop-color="{INK}" stop-opacity=".62"/><stop offset="1" stop-color="{INK}" stop-opacity="0"/></radialGradient>
<filter id="bloom" x="-5%" y="-5%" width="110%" height="110%"><feGaussianBlur stdDeviation="3.2"/></filter>
<clipPath id="frame"><rect width="{W}" height="{H}" rx="22"/></clipPath>
</defs>
<g clip-path="url(#frame)">
<rect width="{W}" height="{H}" fill="url(#sky)"/>
{group(glow, 'opacity=".2" filter="url(#bloom)"')}
{group(faint, 'stroke-width=".7" opacity=".3"')}
{group(bright, '')}
{frames}{lock}
{"" if not motion else '<g class="sat"><circle cx="-60" cy="330" r="1.4" fill="#dfe6ff"/></g>'}
{pole}
<rect width="{W}" height="{H}" fill="url(#shade)"/>
<rect width="{W}" height="{H}" fill="url(#glowH)"/>
{ghost}
<g fill="{PAPER}">{''.join(parts)}</g>
{serif_text("Align the night. Keep the motion.", 60, 392, 44, SOFT, italic())}
{mono_text("STEADIER EXPOSURES · SMOOTHER STAR TRAILS · YOUR WORKFLOW", 62, 440, 16, MUTED, tracking=1.3)}
{ann}
<path d="{ridge_d}" fill="#020306"/>
<g{cls(motion, "meta")}>
{mono_text(f"PULLSTAR {VERSION} — NIGHT-SKY ALIGNMENT", 40, 52, 16, MUTED)}
{mono_text("LOCAL · NO ACCOUNT · NO UPLOAD", W-40, 52, 16, MUTED, "end", 1.2)}
{mono_text("POLARIS OPTIONAL · WOBBLE CORRECTED · TRAILS PRESERVED", 40, H-28, 15, MUTED, tracking=1.1)}
{mono_text("MACOS 14+ · APPLE SILICON", W-40, H-28, 15, MUTED, "end", 1.1)}
</g>
{status}
<g{cls(motion, "stamp")}>{mono_text("● ALIGNED", W-40, 84, 16, AMBER, "end")}</g>
</g>"""
    assert name_w < 760, name_w
    return svg(W, H, "PullStar — Align the night. Keep the motion. Shaken night-sky frames spring into alignment, "
                     "then the stars expose into trails around the celestial pole.", body, style)


# ================================================================ PIPELINE
def pipeline(motion: bool) -> str:
    W, H = 1200, 456
    PW, GAP, X0, TOP = 252, 36, 48, 122
    steps = [
        ("01", "LOAD", "Load the sequence", "RAW · TIFF · PNG · JPEG"),
        ("02", "MATCH", "Match the stars", "POLARIS OPTIONAL"),
        ("03", "CORRECT", "Remove the wobble", "SKY ROTATION KEPT"),
        ("04", "FINISH", "Export your way", "FRAMES · TRAILS · VIDEO"),
    ]
    rnd = mulberry32(77)
    pts = [(40 + rnd() * 172, 26 + rnd() * 148, 0.9 + rnd() * 1.5) for _ in range(16)]
    T = 1.0  # seconds between stages
    panels = []
    for i, (num, kick, cap, sub) in enumerate(steps):
        x = X0 + i * (PW + GAP)
        cx, cy = x + PW / 2, TOP + 100
        mech = ""
        if i == 0:  # stacked frames, slightly askew
            for j, (dx, dy, rt) in enumerate([(-22, -14, -5), (-8, -4, 2.5), (8, 8, -1.5)]):
                fx, fy = x + 46 + dx + 20, TOP + 36 + dy + 20
                dots = "".join(f'<circle cx="{f(fx+px*0.62)}" cy="{f(fy+py*0.62)}" r="{f(s*0.8)}"/>' for px, py, s in pts[:11])
                mech += (f'<g transform="rotate({rt} {f(fx+70)} {f(fy+52)})"><g{cls(motion, "pop", f"animation-delay:{0.2+j*0.18:.2f}s")}>'
                         f'<rect x="{f(fx)}" y="{f(fy)}" width="140" height="104" rx="6" fill="#0b1222" stroke="#fff" stroke-opacity=".22"/>'
                         f'<g fill="#dfe6ff" opacity=".8">{dots}</g></g></g>')
        elif i == 1:  # asterism matching between two exposures
            jr = mulberry32(19)
            grid = [(x + 40 + gx * 62 + jr() * 34, TOP + 30 + gy * 54 + jr() * 30, 1.0 + jr() * 1.4)
                    for gy in range(3) for gx in range(3)]
            off = (13, 9)
            b = [(px + off[0], py + off[1], s) for px, py, s in grid]
            tri = [(0, 1, 3), (4, 5, 8), (6, 7, 4)]

            def tris(pp):
                return "".join(f'<path d="M{f(pp[p][0])} {f(pp[p][1])}L{f(pp[q][0])} {f(pp[q][1])}'
                               f'L{f(pp[r][0])} {f(pp[r][1])}Z"/>' for p, q, r in tri)
            links = "".join(f'<path d="M{f(ax)} {f(ay)}L{f(bx)} {f(by)}"/>'
                            for (ax, ay, _), (bx, by, _) in zip(grid, b))
            mech = (f'<g fill="{BLUE}">' + "".join(f'<circle cx="{f(px)}" cy="{f(py)}" r="{f(s)}"/>' for px, py, s in grid) + "</g>"
                    + f'<g fill="{ORANGE}">' + "".join(f'<circle cx="{f(px)}" cy="{f(py)}" r="{f(s)}"/>' for px, py, s in b) + "</g>"
                    + f'<g fill="none" stroke="{BLUE}" stroke-opacity=".6"{cls(motion, "tri", f"--d:{T+0.3:.2f}s")}>{tris(grid)}</g>'
                    + f'<g fill="none" stroke="{ORANGE}" stroke-opacity=".6"{cls(motion, "tri", f"--d:{T+0.6:.2f}s")}>{tris(b)}</g>'
                    + f'<g fill="none" stroke="{AMBER}" stroke-width="1.2"{cls(motion, "tri", f"--d:{T+1.0:.2f}s")}>{links}</g>')
            mech = mech.replace("<path ", '<path pathLength="1" ' if motion else "<path ")
            mech += (f'<g{cls(motion, "ok", f"animation-delay:{T+1.5:.2f}s")}>'
                     + mono_text("9 STARS MATCHED", x + PW - 16, TOP + 196, 13, AMBER, "end", 1.2) + "</g>")
        elif i == 2:  # two exposures spring into one
            a = [(x + 30 + px * 0.9, TOP + 14 + py * 0.95, s) for px, py, s in pts[:12]]
            dots = "".join(f'<circle cx="{f(px)}" cy="{f(py)}" r="{f(s)}"/>' for px, py, s in a)
            if motion:
                mech = ('<g style="mix-blend-mode:screen">'
                        f'<g class="cv" fill="{BLUE}" style="--dx:-16px;--dy:-10px;--r:-4deg;animation-delay:{2*T+0.2:.2f}s">{dots}</g>'
                        f'<g class="cv" fill="{ORANGE}" style="--dx:15px;--dy:11px;--r:3.5deg;animation-delay:{2*T+0.2:.2f}s">{dots}</g></g>'
                        f'<g fill="#eef2ff" class="ok" style="animation-delay:{2*T+1.7:.2f}s">{dots}</g>')
            else:
                mech = f'<g fill="#eef2ff">{dots}</g>'
            mech += (f'<g{cls(motion, "ok", f"animation-delay:{2*T+1.8:.2f}s")}>'
                     + mono_text("Δ → 0 PX", x + PW - 16, TOP + 196, 13, AMBER, "end", 1.2) + "</g>")
        else:  # trails expose around the pole
            pcx, pcy = cx, TOP + 98
            tr = mulberry32(5)
            arcs = []
            for _ in range(22):
                r = 10 + 86 * math.sqrt(tr())
                a0 = tr() * math.tau
                c = pick(tr, STAR_TEMPS, STAR_WEIGHTS)
                arcs.append(f'<path{PL if motion else ""} d="{arc(pcx, pcy, r, a0, a0 - 1.0)}" '
                            f'stroke="{c}" stroke-width="{f(0.8 + tr()*1.4)}"/>')
            mech = (f'<g fill="none" stroke-linecap="round"{cls(motion, "trl", f"--d:{3*T+0.2:.2f}s")}>{"".join(arcs)}</g>'
                    f'<g stroke="{AMBER}" stroke-width="1" opacity=".8"><path d="M{f(pcx-9)} {f(pcy)}h6M{f(pcx+3)} {f(pcy)}h6M{f(pcx)} {f(pcy-9)}v6M{f(pcx)} {f(pcy+3)}v6"/></g>')
        box = (f'<rect x="{x}" y="{TOP}" width="{PW}" height="208" rx="14" fill="#070b16" '
               f'stroke="#fff" stroke-opacity=".09"/>')
        clip = f'<clipPath id="p{i}"><rect x="{x}" y="{TOP}" width="{PW}" height="208" rx="14"/></clipPath>'
        panels.append(
            f'<defs>{clip}</defs><g{cls(motion, "st", f"animation-delay:{i*T:.2f}s")}>{box}'
            f'<g clip-path="url(#p{i})">{mech}</g>'
            + mono_text(f"{num} — {kick}", x, TOP - 22, 15, AMBER, tracking=1.8)
            + serif_text(cap, x, TOP + 262, 36)
            + mono_text(sub, x + 1, TOP + 296, 13, MUTED, tracking=1.2)
            + "</g>")
        if i < 3:
            ax = x + PW + GAP / 2
            panels.append(f'<g{cls(motion, "st", f"animation-delay:{i*T+0.6:.2f}s")}>'
                          f'<path d="M{f(ax-5)} {TOP+94}l8 10-8 10" fill="none" stroke="{DIM}" stroke-width="1.6" '
                          f'stroke-linecap="round" stroke-linejoin="round"/></g>')
    style = (spring_keyframes("cv", k=4.6, w=12)
             + "@keyframes pop{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}"
             "@keyframes vanish{0%,70%{opacity:1}100%{opacity:0}}"
             ".st{animation:fade .6s ease-out both}"
             ".pop{animation:pop .5s cubic-bezier(.2,.8,.2,1) both}"
             ".tri path{stroke-dasharray:1;animation:draw .9s ease-out var(--d) both}"
             ".cv{transform-box:fill-box;transform-origin:50% 50%;animation:cv 1.6s linear both,vanish 1.9s both}"
             ".ok{animation:fade .4s steps(2) both}"
             ".trl path{stroke-dasharray:1;animation:draw 2.6s cubic-bezier(.3,.6,.2,1) var(--d) both}")
    body = f"""
<defs><clipPath id="c"><rect width="{W}" height="{H}" rx="22"/></clipPath>
<linearGradient id="bg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{NIGHT}"/><stop offset="1" stop-color="{INK}"/></linearGradient></defs>
<g clip-path="url(#c)"><rect width="{W}" height="{H}" fill="url(#bg)"/>
{''.join(panels)}
{mono_text("HOW IT WORKS", 48, 50, 14, DIM, tracking=2)}
{mono_text("CORRECT THE CAMERA, NOT THE SKY", W-48, 50, 14, DIM, "end", 1.3)}
</g>"""
    return svg(W, H, "How PullStar works: 01 load the sequence, 02 match the star field (Polaris optional), "
                     "03 remove the camera wobble while keeping sky rotation, 04 export frames, trails, or video.",
               body, style if motion else "")


# ================================================================ FINISH CARDS
CW, CH = 600, 440


def card(letter, kicker, title, formats, mech, style, alt, motion, seed):
    rnd = mulberry32(seed)
    dust = "".join(f'<circle cx="{f(rnd()*CW)}" cy="{f(rnd()*250+20)}" r="{f(0.5+rnd()*0.9)}" '
                   f'opacity="{0.12+rnd()*0.3:.2f}"/>' for _ in range(34))
    body = f"""
<defs><clipPath id="c"><rect width="{CW}" height="{CH}" rx="20"/></clipPath>
<linearGradient id="bg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{NIGHT}"/><stop offset="1" stop-color="{INK}"/></linearGradient></defs>
<g clip-path="url(#c)"><rect width="{CW}" height="{CH}" fill="url(#bg)"/>
<g fill="#cfd8ff">{dust}</g>
{mech}
<path d="M36 300H{CW-36}" stroke="#fff" stroke-opacity=".1"/>
{mono_text(letter, 36, 52, 19, AMBER, tracking=2)}
{mono_text(kicker, CW-36, 52, 15, MUTED, "end", 1.2)}
{serif_text(title, 34, 368, 62)}
{mono_text(formats, 36, 408, 15, MUTED, tracking=1.2)}
</g>"""
    return svg(CW, CH, alt, body, style if motion else "")


def card_frames(motion):
    rnd = mulberry32(12)
    pts = [(rnd() * 196, rnd() * 128, 0.8 + rnd() * 1.5) for _ in range(18)]
    cx, cy = 300, 172
    offs = [(-54, -30, -6), (-26, -12, 3), (22, 14, -3.5), (50, 32, 5)]
    out = []
    for i, (dx, dy, rt) in enumerate(offs):
        dots = "".join(f'<circle cx="{f(cx-98+px)}" cy="{f(cy-64+py)}" r="{f(s)}"/>' for px, py, s in pts)
        inner = (f'<rect x="{cx-110}" y="{cy-76}" width="220" height="152" rx="8" fill="#0b1222" fill-opacity=".86" '
                 f'stroke="#fff" stroke-opacity="{.16 + i*.06:.2f}"/><g fill="#dfe6ff" opacity=".85">{dots}</g>')
        if motion:
            out.append(f'<g class="sl" style="--dx:{dx}px;--dy:{dy}px;--r:{rt}deg;animation-delay:{0.5+i*0.12:.2f}s">{inner}</g>')
        else:
            out.append(f"<g>{inner}</g>")
    ghosts = "".join(
        f'<rect x="{cx-110}" y="{cy-76}" width="220" height="152" rx="8" fill="none" stroke="{(BLUE, ORANGE)[i % 2]}" '
        f'stroke-opacity=".28" stroke-dasharray="2 5" transform="translate({dx} {dy}) rotate({rt} {cx} {cy})"/>'
        for i, (dx, dy, rt) in enumerate(offs))
    crop = (f'<g{cls(motion, "ok")}><rect x="{cx-104}" y="{cy-70}" width="208" height="140" rx="4" fill="none" '
            f'stroke="{AMBER}" stroke-dasharray="6 5" stroke-width="1.3"/>'
            + mono_text("COMMON CROP", cx + 104, cy + 92, 13, AMBER, "end", 1.2) + "</g>")
    style = (spring_keyframes("sl", k=4.4, w=10)
             + ".sl{transform-box:view-box;transform-origin:300px 172px;animation:sl 2s linear both}"
             ".ok{animation:fade .4s steps(2) 2.4s both}")
    return card("A", "FOR ANOTHER EDITOR", "Aligned frames", "TIFF · PNG · JPEG · UP TO 16-BIT",
                ghosts + "".join(out) + crop, style,
                "Aligned frames — a TIFF, PNG, or JPEG sequence with a common crop, ready for another editor.", motion, 3)


def card_trails(motion):
    PX, PY = 300, 132
    rnd = mulberry32(21)
    arcs = []
    pl = ' pathLength="1"' if motion else ""
    for r, a, c, s in star_field(rnd, PX, PY, 64, 12, 330):
        arcs.append(f'<path{pl} d="{arc(PX, PY, r, a, a - math.radians(70))}" stroke="{c}" stroke-width="{f(s)}" '
                    f'opacity="{0.5 + 0.5*min(1, s/2):.2f}"/>')
    land = f"M0 301 {ridge(CW, 268, 11, amp=70)} L{CW} 301Z"
    mech = (f'<defs><clipPath id="sky"><rect width="{CW}" height="300"/></clipPath>'
            f'<linearGradient id="hd" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{INK}" stop-opacity=".85"/>'
            f'<stop offset="1" stop-color="{INK}" stop-opacity="0"/></linearGradient></defs>'
            f'<g clip-path="url(#sky)"><g{cls(motion, "tr")} fill="none" stroke-linecap="round">{"".join(arcs)}</g></g>'
            f'<rect width="{CW}" height="86" fill="url(#hd)"/>'
            f'<path d="{land}" fill="#020306"/>'
            f'<g stroke="{AMBER}" stroke-width="1" opacity=".8"><path d="M{PX-11} {PY}h7M{PX+4} {PY}h7M{PX} {PY-11}v7M{PX} {PY+4}v7"/></g>'
            f'<g{cls(motion, "ok")}>' + mono_text("FOREGROUND PRESERVED", CW - 36, 290, 13, AMBER, "end", 1.2) + "</g>")
    style = (".tr path{stroke-dasharray:1;animation:draw 4s cubic-bezier(.3,.6,.2,1) .4s both}"
             ".ok{animation:fade .5s steps(2) 3.6s both}")
    return card("B", "FINISHED STILL", "Trail image", "TIFF · PNG · JPEG · GAP FILL · TAPER",
                mech, style, "Trail image — a stacked star-trail still with the foreground preserved, gap filling, "
                             "and optional synthetic trail extension.", motion, 4)


def card_video(motion):
    n = 5
    fw, fh, gap = 92, 70, 12
    x0, y0 = (CW - (n * fw + (n - 1) * gap)) / 2, 112
    rnd = mulberry32(33)
    seeds = [(rnd() * 46 + 6, rnd() * math.tau, pick(rnd, STAR_TEMPS, STAR_WEIGHTS)) for _ in range(12)]
    cells = []
    for i in range(n):
        x = x0 + i * (fw + gap)
        pcx, pcy = x + fw / 2, y0 + fh / 2
        sweep = 0.12 + i * 0.32
        arcs = "".join(f'<path d="{arc(pcx, pcy, r*0.75, a, a - sweep)}" stroke="{c}"/>' for r, a, c in seeds)
        cells.append(
            f'<g{cls(motion, "fz", f"animation-delay:{0.3 + i*0.35:.2f}s")}>'
            f'<clipPath id="v{i}"><rect x="{f(x)}" y="{y0}" width="{fw}" height="{fh}" rx="4"/></clipPath>'
            f'<rect x="{f(x)}" y="{y0}" width="{fw}" height="{fh}" rx="4" fill="#0b1222" stroke="#fff" stroke-opacity=".18"/>'
            f'<g clip-path="url(#v{i})" fill="none" stroke-width="1.2" stroke-linecap="round">{arcs}</g></g>')
    sx0, sx1 = x0 - 14, x0 + n * fw + (n - 1) * gap + 14
    holes = "".join(f'<rect x="{f(sx0 + 10 + k*22)}" y="{yy}" width="10" height="6" rx="1.5"/>'
                    for k in range(int((sx1 - sx0 - 20) / 22) + 1) for yy in (y0 - 22, y0 + fh + 16))
    strip = (f'<rect x="{f(sx0)}" y="{y0-32}" width="{f(sx1-sx0)}" height="{fh+64}" rx="8" fill="#03050b" '
             f'stroke="#fff" stroke-opacity=".08"/><g fill="#fff" opacity=".14">{holes}</g>')
    bar_y = 248
    bar = (f'<rect x="{f(sx0)}" y="{bar_y}" width="{f(sx1-sx0)}" height="3" rx="1.5" fill="#fff" fill-opacity=".12"/>'
           f'<rect{cls(motion, "pb")} x="{f(sx0)}" y="{bar_y}" width="{f(sx1-sx0)}" height="3" rx="1.5" fill="{AMBER}"/>'
           + mono_text("▶ 00:12", sx0, bar_y - 12, 13, AMBER, tracking=1.2)
           + mono_text("FRAME BY FRAME", sx1, bar_y - 12, 13, MUTED, "end", 1.2))
    style = ("@keyframes pb{from{transform:scaleX(0)}to{transform:scaleX(1)}}"
             ".fz{animation:fade .35s ease-out both}"
             f".pb{{transform-box:fill-box;transform-origin:0 0;animation:pb 2.2s linear .3s both}}")
    return card("C", "TRAIL-LAPSE", "Trail-lapse video", "MP4 · MOV · H.264 · HEVC · PRORES",
                strip + "".join(cells) + bar, style,
                "Trail-lapse video — MP4 or MOV with H.264, HEVC, lossless H.264, or ProRes, trails growing frame by frame.",
                motion, 5)


# ================================================================ MCP
def mcp(motion):
    W, H = 1200, 470
    cols = [
        ("INSPECT", ["inspect_sequence", "recommend_settings", "detect_and_analyze_stars",
                     "get_hardware_capabilities", "evaluate_alignment_settings"]),
        ("PREVIEW", ["compare_alignment_candidates", "render_preview_stack", "render_annotated_preview",
                     "evaluate_stack_quality", "auto_tune_and_stack"]),
        ("RUN", ["create_stack", "start_stack_job", "get_job_status", "cancel_job", "list_jobs"]),
    ]
    path = ["inspect_sequence", "recommend_settings", "render_preview_stack", "start_stack_job", "get_job_status"]
    X0, CWID, Y0, ROW = 436, 262, 156, 50
    pos = {}
    rows = []
    for c, (head, tools) in enumerate(cols):
        x = X0 + c * CWID
        rows.append(f'<g{cls(motion, "rw", f"animation-delay:{0.2 + c*0.15:.2f}s")}>'
                    + mono_text(head, x, Y0 - 34, 13, DIM, tracking=2) + "</g>")
        for r, t in enumerate(tools):
            y = Y0 + r * ROW
            pos[t] = (x, y)
            lit = t in path
            k = path.index(t) if lit else 0
            rows.append(f'<g{cls(motion, "rw", f"animation-delay:{0.3 + c*0.15 + r*0.06:.2f}s")}>'
                        + f'<circle cx="{x+4}" cy="{y-5}" r="3" fill="none" stroke="{DIM}"/>'
                        + mono_text(t, x + 16, y, 13.5, MUTED, tracking=0.3) + "</g>")
            if lit:
                d = 1.4 + k * 0.45
                rows.append(f'<g{cls(motion, "lt", f"animation-delay:{d:.2f}s")}>'
                            f'<circle cx="{x+4}" cy="{y-5}" r="3.2" fill="{AMBER}"/>'
                            + mono_text(t, x + 16, y, 13.5, PAPER, tracking=0.3) + "</g>")
    # call path
    segs = []
    for k, (a, b) in enumerate(zip(path, path[1:])):
        (ax, ay), (bx, by) = pos[a], pos[b]
        if ax == bx:  # same column: drop down along the bullets
            d = f"M{ax+4} {ay+1}V{by-11}"
        else:  # next column: leave from the end of the label
            ex = ax + 16 + mono().width(a, 13.5, 0.3) + 10
            d = f"M{f(ex)} {ay-5}H{bx-6}"
        segs.append(f'<path{PL if motion else ""}{cls(motion, "cp", f"animation-delay:{1.5 + k*0.45:.2f}s")} '
                    f'd="{d}" fill="none" stroke="{AMBER}" stroke-opacity=".55" stroke-width="1.2" '
                    f'stroke-dasharray="{"1" if motion else "3 4"}"/>')
    left = (mono_text("MODEL CONTEXT PROTOCOL", 48, 70, 15, AMBER, tracking=2)
            + serif_text("Fifteen tools", 44, 166, 74)
            + serif_text("for your agent.", 46, 228, 60, SOFT, italic())
            + mono_text("INSPECT · PREVIEW · EXPORT · JOBS", 48, 300, 14, MUTED, tracking=1.2)
            + mono_text("STDIO · SSE · STREAMABLE HTTP", 48, 328, 14, DIM, tracking=1.2)
            + mono_text("BUNDLED IN THE MACOS APP", 48, 356, 14, DIM, tracking=1.2))
    foot = (f'<g{cls(motion, "rw", "animation-delay:3.6s")}>'
            + mono_text("● ONE AGENT SESSION, START TO FINISH", W - 48, H - 40, 13, AMBER, "end", 1.2) + "</g>")
    body = f"""
<defs><clipPath id="c"><rect width="{W}" height="{H}" rx="22"/></clipPath>
<radialGradient id="bg" cx=".7" cy=".4" r=".9"><stop offset="0" stop-color="#0e1630"/><stop offset="1" stop-color="{INK}"/></radialGradient></defs>
<g clip-path="url(#c)"><rect width="{W}" height="{H}" fill="url(#bg)"/>
<rect x="404" y="70" width="756" height="330" rx="16" fill="#070b16" fill-opacity=".7" stroke="#fff" stroke-opacity=".08"/>
{left}{''.join(segs)}{''.join(rows)}{foot}
</g>"""
    style = (".rw{animation:fade .5s ease-out both}"
             ".lt{animation:fade .3s steps(2) both}"
             ".cp{stroke-dasharray:1;animation:draw .45s ease-out both}")
    return svg(W, H, "Fifteen MCP tools for your agent: inspect, preview, export, and manage jobs. An example session "
                     "calls inspect_sequence, recommend_settings, render_preview_stack, start_stack_job, and get_job_status.",
               body, style if motion else "")


# ================================================================ FOOTER
def footer(motion):
    W, H = 1200, 300
    body = f"""
<defs><clipPath id="c"><rect width="{W}" height="{H}" rx="22"/></clipPath>
<linearGradient id="m" x1="1" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity="0"/><stop offset="1" stop-color="#fff"/></linearGradient></defs>
<g clip-path="url(#c)"><rect width="{W}" height="{H}" fill="{INK}"/>
<path{cls(motion, "met")} pathLength="1" d="M1010 40L840 128" stroke="url(#m)" stroke-width="2" stroke-linecap="round"/>
{serif_text("Clear skies.", 44, 148, 104, PAPER, italic())}
{serif_text("Download PullStar and align your next night.", 48, 214, 40, SOFT)}
{mono_text(f"MACOS 14+ · APPLE SILICON · v{VERSION}", 48, 264, 18, AMBER)}
{arrow(W-80, 230, 26)}
</g>"""
    style = ("@keyframes shoot{0%{stroke-dashoffset:1;opacity:0}8%{opacity:1}20%{stroke-dashoffset:-.2;opacity:0}100%{opacity:0}}"
             ".met{stroke-dasharray:.6 1;animation:shoot 9s cubic-bezier(.3,0,.2,1) 1.2s infinite}")
    return svg(W, H, f"Clear skies. Download PullStar {VERSION} for macOS 14 or later on Apple Silicon.", body,
               style if motion else "")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    jobs = {"hero": hero, "pipeline": pipeline, "finish-frames": card_frames, "finish-trails": card_trails,
            "finish-video": card_video, "mcp": mcp, "footer": footer}
    for name, fn in jobs.items():
        for motion in (True, False):
            (OUT / f"{name}-{'motion' if motion else 'still'}.svg").write_text(fn(motion))
    print(f"built {len(jobs)*2} svgs for PullStar {VERSION} → {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
