# -*- coding: utf-8 -*-
"""page_sheet.py -- one contact sheet of the pages, rendered straight from the module.

    python scripts/page_sheet.py [sheet.png] [--mod film.py] [--cols 6] [--cw 320] [--spec "0:0.62,3:0.5"]

The cheap visual loop of the whole production: every page at a chosen progress, tiled into one image you
can actually look at. Run it after each renderer change and BEFORE the full render (it costs seconds, a
render costs minutes), and after muxing for the final look. Every pixel-level defect in the reference
projects was found this way -- a mask clipped square behind the headline, a glyph so loud it competed with
the lyric, a shape that read as a grey card -- and none of them by any verifier.

It does not write per-page files: it asks the module for one frame per page.
"""
import argparse, importlib.util, os, sys

from PIL import Image

sys.stdout.reconfigure(encoding="utf-8")


def render_at(film, sg, p):
    """One frame of page `sg` at progress p, tolerating either renderer shape."""
    fps = float(getattr(film, "FPS", 30))
    if "f0" in sg and "n" in sg:
        k = int(sg["f0"]) + min(int(sg["n"]) - 1, max(0, int(int(sg["n"]) * p)))
    else:
        t0, t1 = sg["t"]
        k = int(round((float(t0) + (float(t1) - float(t0)) * p - float(film.T0)) * fps))
    try:                                    # a film whose frame() takes a frame index
        im = film.frame(k)
    except TypeError:                       # ...and one whose frame() takes (i, p, k)
        im = film.frame_t(float(film.T0) + k / fps, k=k)
    return im, k


def main():
    HERE = os.path.dirname(os.path.abspath(__file__))
    ROOT = os.path.dirname(HERE)
    ap = argparse.ArgumentParser()
    ap.add_argument("out", nargs="?", default=os.path.join(os.getcwd(), "preview", "sheet.png"))
    ap.add_argument("--mod", default=os.path.join(ROOT, "film.py"))
    ap.add_argument("--cols", type=int, default=6)
    ap.add_argument("--cw", type=int, default=320)
    ap.add_argument("--spec", default=None, help='e.g. "0:0.62,3:0.5,7:0.3"; default every page at 0.62')
    a = ap.parse_args()

    mod = importlib.util.spec_from_file_location("film", os.path.abspath(a.mod))
    film = importlib.util.module_from_spec(mod)
    mod.loader.exec_module(film)
    segs = list(film.SEG)
    spec = ([(int(s.split(":")[0]), float(s.split(":")[1])) for s in a.spec.split(",")]
            if a.spec else [(i, 0.62) for i in range(len(segs))])
    cw, ch = a.cw, int(round(a.cw * 9.0 / 16.0))
    rows = (len(spec) + a.cols - 1) // a.cols
    sheet = Image.new("RGB", (cw * a.cols, ch * rows), (16, 16, 18))
    for n, (i, p) in enumerate(spec):
        sg = segs[i]
        im, k = render_at(film, sg, p)
        sheet.paste(im.convert("RGB").resize((cw, ch), Image.LANCZOS),
                    ((n % a.cols) * cw, (n // a.cols) * ch))
        print("page %2d  p=%.2f  frame %5d  dark=%s  %s"
              % (i, p, k, sg.get("dark"), sg.get("s")))
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    sheet.save(a.out)
    print("wrote %s  %dx%d  (%d pages)" % (a.out, sheet.size[0], sheet.size[1], len(spec)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
