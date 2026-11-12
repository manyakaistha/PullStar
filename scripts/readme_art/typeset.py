"""Glyph-outline typesetting for SVG.

Text is converted to paths so the profile art renders identically everywhere:
SVG images on GitHub cannot fetch web fonts, and system fallbacks would break
the composition. Pair kerning is read from GPOS so large display type sits
correctly.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

FONT_DIR = Path(__file__).parent / "fonts"


def _num(v: float) -> str:
    s = f"{v:.1f}"
    return s[:-2] if s.endswith(".0") else s


class Face:
    def __init__(self, file: str, wght: float | None = None):
        font = TTFont(FONT_DIR / file)
        if wght is not None and "fvar" in font:
            from fontTools.varLib import instancer

            font = instancer.instantiateVariableFont(font, {"wght": wght})
        self.font = font
        self.upm = font["head"].unitsPerEm
        self.cmap = font.getBestCmap()
        self.gs = font.getGlyphSet()
        self.hmtx = font["hmtx"]
        self.kern = self._read_kerning()

    def _read_kerning(self) -> dict[tuple[str, str], int]:
        pairs: dict[tuple[str, str], int] = {}
        if "GPOS" not in self.font:
            return pairs
        gpos = self.font["GPOS"].table
        if not gpos.LookupList:
            return pairs
        for lookup in gpos.LookupList.Lookup:
            for st in lookup.SubTable:
                if lookup.LookupType == 9:
                    st = st.ExtSubTable
                if getattr(st, "LookupType", 2) != 2 and lookup.LookupType != 9:
                    continue
                if not hasattr(st, "Format") or not hasattr(st, "Coverage"):
                    continue
                cov = st.Coverage.glyphs
                if st.Format == 1:
                    for i, first in enumerate(cov):
                        for rec in st.PairSet[i].PairValueRecord:
                            v = getattr(rec.Value1, "XAdvance", 0) or 0
                            if v:
                                pairs.setdefault((first, rec.SecondGlyph), v)
                elif st.Format == 2:
                    c1 = st.ClassDef1.classDefs if st.ClassDef1 else {}
                    c2 = st.ClassDef2.classDefs if st.ClassDef2 else {}
                    seconds: dict[int, list[str]] = {}
                    for g, c in c2.items():
                        seconds.setdefault(c, []).append(g)
                    for first in cov:
                        row = st.Class1Record[c1.get(first, 0)].Class2Record
                        for c, rec in enumerate(row):
                            v = getattr(rec.Value1, "XAdvance", 0) or 0
                            if v and c in seconds:
                                for second in seconds[c]:
                                    pairs.setdefault((first, second), v)
        return pairs

    def glyph_name(self, ch: str) -> str:
        return self.cmap.get(ord(ch)) or self.cmap.get(ord("?"))

    def layout(self, text: str, size: float, tracking: float = 0.0):
        """Return [(char, glyph_name, x_offset_px, advance_px)] and total width."""
        s = size / self.upm
        out = []
        x = 0.0
        prev = None
        for ch in text:
            g = self.glyph_name(ch)
            if prev is not None:
                x += self.kern.get((prev, g), 0) * s
            adv = self.hmtx[g][0] * s
            out.append((ch, g, x, adv))
            x += adv + tracking
            prev = g
        width = x - tracking if out else 0.0
        return out, width

    def glyph_path(self, g: str, size: float, x: float, y: float) -> str:
        s = size / self.upm
        pen = SVGPathPen(self.gs, ntos=_num)
        self.gs[g].draw(TransformPen(pen, (s, 0, 0, -s, x, y)))
        return pen.getCommands()

    def text_path(self, text: str, size: float, x: float, y: float,
                  tracking: float = 0.0, anchor: str = "start") -> str:
        glyphs, width = self.layout(text, size, tracking)
        x0 = x - (width if anchor == "end" else width / 2 if anchor == "middle" else 0)
        return "".join(self.glyph_path(g, size, x0 + gx, y) for _, g, gx, _ in glyphs)

    def width(self, text: str, size: float, tracking: float = 0.0) -> float:
        return self.layout(text, size, tracking)[1]


@lru_cache(None)
def serif() -> Face:
    return Face("InstrumentSerif-Regular.ttf")


@lru_cache(None)
def italic() -> Face:
    return Face("InstrumentSerif-Italic.ttf")


@lru_cache(None)
def mono() -> Face:
    return Face("JetBrainsMono-Variable.ttf", wght=430)
