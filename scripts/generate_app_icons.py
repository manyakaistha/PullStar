"""Construct PullStar's icon from geometry and package platform assets.

No generated artwork or image service is used. Geometry is expressed in a
1024-unit SVG coordinate system and rasterized by the project's Electron.
Run: uv run python scripts/generate_app_icons.py
"""
from pathlib import Path
import math
import os
import subprocess
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
BRANDING = ROOT / "assets/branding"


def polar(cx, cy, radius, degrees):
    angle = math.radians(degrees)
    return cx + radius * math.cos(angle), cy + radius * math.sin(angle)


def tapered_arc(cx, cy, radius, start, sweep, width, samples=200):
    """Outline a circular centerline with w(t)=0.5+(width-0.5)t^0.85.

    Offset both sides radially, then close with semicircular endpoint caps.
    This changes the actual silhouette rather than fading a uniform stroke.
    """
    outer, inner = [], []
    for index in range(samples + 1):
        t = index / samples
        half = (0.5 + (width - 0.5) * t ** 0.85) / 2
        degrees = start + sweep * t
        outer.append(polar(cx, cy, radius + half, degrees))
        inner.append(polar(cx, cy, radius - half, degrees))
    points = list(outer)
    for degrees, half, first_angle in [(start + sweep, width / 2, 0), (start, .25, 180)]:
        if first_angle == 180:
            points.extend(reversed(inner))
        theta = math.radians(degrees)
        x, y = polar(cx, cy, radius, degrees)
        for step in range(1, 17):
            phi = math.radians(first_angle + 180 * step / 16)
            points.append((x + half * (math.cos(phi) * math.cos(theta) - math.sin(phi) * math.sin(theta)),
                           y + half * (math.cos(phi) * math.sin(theta) + math.sin(phi) * math.cos(theta))))
    return "M " + " L ".join(f"{x:.3f},{y:.3f}" for x, y in points) + " Z"


def superellipse(cx, cy, radius, exponent=4.5, samples=512):
    """|x/a|^n + |y/a|^n = 1; sign(cos t)|cos t|^(2/n)."""
    points = []
    for index in range(samples):
        t = 2 * math.pi * index / samples
        c, s = math.cos(t), math.sin(t)
        x = cx + radius * math.copysign(abs(c) ** (2 / exponent), c)
        y = cy + radius * math.copysign(abs(s) ** (2 / exponent), s)
        points.append(f"{x:.3f},{y:.3f}")
    return "M " + " L ".join(points) + " Z"


def create_svg():
    tile = superellipse(512, 500, 428)
    # All tracks share one celestial pole: exact concentric circles, no wobble.
    trails = [(112, -155, 240, 12), (179, -109, 268, 14),
              (246, -160, 250, 16), (313, -111, 264, 17),
              (380, -149, 236, 18)]
    paths = []
    for radius, start, sweep, width in trails:
        path = tapered_arc(512, 500, radius, start, sweep, width)
        paths.append(f'<path d="{path}" fill="#000" opacity=".25" transform="translate(0 2)"/>')
        paths.append(f'<path d="{path}" fill="url(#trail)"/>')
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="0 0 1024 1024">
  <title>PullStar — concentric star trails</title>
  <desc>Five tapered, white, mathematically concentric trails around a pole star, on a subtly frosted midnight tile.</desc>
  <defs>
    <linearGradient id="tile" x1="0" y1="0" x2=".7" y2="1" gradientUnits="objectBoundingBox">
      <stop stop-color="#171d24"/><stop offset=".43" stop-color="#0b1017"/><stop offset="1" stop-color="#04070c"/>
    </linearGradient>
    <radialGradient id="light" cx=".19" cy="0" r="1">
      <stop stop-color="#e5f7ff" stop-opacity=".055"/><stop offset=".7" stop-color="#e5f7ff" stop-opacity="0"/>
    </radialGradient>
    <linearGradient id="rim" x1="0" y1="0" x2=".7" y2="1">
      <stop stop-color="#f2fcff" stop-opacity=".35"/><stop offset=".45" stop-color="#b6d1df" stop-opacity=".15"/><stop offset="1" stop-color="#8aa2b5" stop-opacity=".18"/>
    </linearGradient>
    <linearGradient id="trail" x1=".1" y1="0" x2=".85" y2="1">
      <stop stop-color="#d9dce1"/><stop offset=".36" stop-color="#fff"/><stop offset="1" stop-color="#f1f2f4"/>
    </linearGradient>
    <radialGradient id="starGlow"><stop stop-color="#eef2f7" stop-opacity=".12"/><stop offset="1" stop-color="#eef2f7" stop-opacity="0"/></radialGradient>
    <clipPath id="clip"><path d="{tile}"/></clipPath>
    <filter id="shadow" x="-.2" y="-.2" width="1.4" height="1.4"><feDropShadow dx="0" dy="15" stdDeviation="12" flood-color="#030910" flood-opacity=".25"/></filter>
  </defs>
  <path d="{tile}" fill="url(#tile)" filter="url(#shadow)"/>
  <g clip-path="url(#clip)">
    <path d="{tile}" fill="url(#light)"/>
    <path d="M 120 295 Q 445 210 930 335 L 930 60 L 80 60 Z" fill="#e2f5ff" opacity=".012"/>
  </g>
  <path d="{tile}" fill="none" stroke="url(#rim)" stroke-width="2"/>
  <g fill="none" stroke-linecap="round" stroke-linejoin="round">{''.join(paths)}</g>
  <circle cx="512" cy="500" r="52" fill="url(#starGlow)"/>
  <path d="M 512 468 Q 515 496 535 500 Q 515 504 512 532 Q 509 504 489 500 Q 509 496 512 468 Z" fill="#fafbff"/>
  <circle cx="512" cy="500" r="5" fill="#fff"/>
</svg>'''


def main():
    icons = ROOT / "frontend/resources/icons"
    public = ROOT / "frontend/public"
    icons.mkdir(parents=True, exist_ok=True)
    BRANDING.mkdir(parents=True, exist_ok=True)
    svg = BRANDING / "star-aligner.svg"
    svg.write_text(create_svg())
    (public / "app-icon.svg").write_text(svg.read_text())
    electron = ROOT / "frontend/node_modules/.bin" / ("electron.cmd" if os.name == "nt" else "electron")
    environment = os.environ.copy()
    environment.pop("ELECTRON_RUN_AS_NODE", None)
    subprocess.run([str(electron), str(ROOT / "frontend/electron/render-icon.cjs"),
                    str(svg), str(icons / "icon.png")], check=True, env=environment, timeout=45)
    with Image.open(icons / "icon.png") as source:
        master = source.convert("RGBA").resize((1024, 1024), Image.Resampling.LANCZOS)
        master.save(icons / "icon.png")
        master.save(icons / "icon.icns", format="ICNS")
        master.save(icons / "icon.ico", format="ICO", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
        master.resize((256, 256), Image.Resampling.LANCZOS).save(public / "app-icon.png")
        master.save(public / "favicon.ico", format="ICO", sizes=[(s, s) for s in (16, 32, 48)])
    print(f"Generated SVG, PNG, ICNS, ICO and favicon from concentric circular arcs: {svg}")


if __name__ == "__main__":
    main()
