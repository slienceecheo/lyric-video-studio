# -*- coding: utf-8 -*-
"""diff_cell.py -- where do two film frames actually differ?

    python scripts/diff_cell.py <kA> <kB> [--mod film.py] [--out preview]

Renders both frames from the module, prints the mean|dL|, the changed-pixel bbox and a coarse per-cell
map (so whichever element moved is named by its position on the page), and writes a contrast-stretched
diff PNG you can LOOK at.

Use it whenever a consecutive-frame delta is suspiciously large -- verify_assembly flagged a seam, or
motion_probe reported a jump. The bbox tells you what moved:
    confined to the text column, about one glyph row  -> a display block stepped (position breath)
    a full-frame box                                  -> a transition
    a stripe / a ring                                 -> a decoration
    the HUD strip only                                -> the timecode, harmless (~0.02)
"""
import argparse, importlib.util, os, sys

import numpy as np
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8")


def main():
    HERE = os.path.dirname(os.path.abspath(__file__))
    ROOT = os.path.dirname(HERE)
    ap = argparse.ArgumentParser()
    ap.add_argument("kA", type=int)
    ap.add_argument("kB", type=int)
    ap.add_argument("--mod", default=os.path.join(ROOT, "film.py"))
    ap.add_argument("--out", default=os.path.join(os.getcwd(), "preview"),
                    help="where the contrast-stretched PNG goes (default ./preview)")
    a = ap.parse_args()

    mod = importlib.util.spec_from_file_location("film", os.path.abspath(a.mod))
    film = importlib.util.module_from_spec(mod)
    mod.loader.exec_module(film)

    A = np.asarray(film.frame_t(film.T0 + a.kA / float(film.FPS), k=a.kA).convert("L"), dtype=np.float32)
    B = np.asarray(film.frame_t(film.T0 + a.kB / float(film.FPS), k=a.kB).convert("L"), dtype=np.float32)
    D = np.abs(A - B)
    H, W = D.shape
    print("frames %d -> %d   mean|dL| %.3f   max %.0f   pixels >8: %d (%.3f%%)"
          % (a.kA, a.kB, D.mean(), D.max(), int((D > 8).sum()), 100.0 * (D > 8).mean()))

    ny, nx = 8, 12
    print("mean |dL| per cell (rows top->bottom):")
    print("      " + " ".join("%6d" % int(c * W / nx) for c in range(nx)))
    for r in range(ny):
        y0, y1 = int(r * H / ny), int((r + 1) * H / ny)
        cells = [D[y0:y1, int(c * W / nx):int((c + 1) * W / nx)].mean() for c in range(nx)]
        print("%5d " % y0 + " ".join("%6.2f" % v for v in cells))

    ys, xs = np.where(D > 8)
    if len(ys):
        print("bbox of changed pixels: x %d..%d  y %d..%d" % (xs.min(), xs.max(), ys.min(), ys.max()))
    os.makedirs(a.out, exist_ok=True)
    p = os.path.join(a.out, "diff_%d_%d.png" % (a.kA, a.kB))
    Image.fromarray(np.clip(D * 8, 0, 255).astype(np.uint8)).save(p)
    print("wrote %s  (contrast-stretched x8)" % p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
