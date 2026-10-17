# -*- coding: utf-8 -*-
"""Transition test matrix: every transition at q=0.25/0.5/0.75 over two solid test frames.

Usage:
    python transition_matrix.py [film.py] [out.png]

Read the result before rendering the film: stripes, blank frames, or a wrong
background colour mean a mask-broadcast bug (see references/pitfalls.md).
"""
import importlib.util, os, sys

from PIL import Image, ImageDraw, ImageFont


def label_font(m, size):
    for attr in ("MM", "M", "K"):
        cand = getattr(m, attr, None)
        if isinstance(cand, str) and cand.lower().endswith(".ttf") and os.path.exists(cand):
            try:
                return ImageFont.truetype(cand, size)
            except Exception:
                pass
    return ImageFont.load_default()


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "film.py"
    out = sys.argv[2] if len(sys.argv) > 2 else "tr_matrix.png"
    spec = importlib.util.spec_from_file_location("film", os.path.abspath(path))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    a = Image.new("RGB", (m.W, m.H), (200, 40, 40))
    b = Image.new("RGB", (m.W, m.H), (40, 60, 200))
    da, db = ImageDraw.Draw(a), ImageDraw.Draw(b)
    lf = label_font(m, 180)
    da.text((60, 120), "OLD", font=lf, fill=(255, 255, 255))
    db.text((60, 120), "NEW", font=lf, fill=(255, 255, 255))
    da.rectangle([0, 0, m.W - 1, 30], fill=(250, 230, 60))
    db.rectangle([0, 0, m.W - 1, 30], fill=(60, 240, 100))
    ks = [k for k in ("roll", "wipe", "blinds", "slice", "dissolve", "flash") if k in m.TRANS]
    qs = [0.25, 0.5, 0.75]
    cw, ch = 400, 225
    small = label_font(m, 20)
    s = Image.new("RGB", (cw * len(qs), ch * len(ks)), (0, 0, 0))
    seg = m.SEG[min(1, len(m.SEG) - 1)]
    for r, k in enumerate(ks):
        for c, q in enumerate(qs):
            im = m.TRANS[k](a, b, q, seg).resize((cw, ch), Image.LANCZOS)
            s.paste(im, (c * cw, r * ch))
            ImageDraw.Draw(s).text((c * cw + 12, r * ch + ch - 26), "%s q=%.2f" % (k, q), font=small, fill=(20, 20, 20))
        print(k, "ok", flush=True)
    s.save(out)
    print("matrix", s.size, "->", out)


if __name__ == "__main__":
    main()
