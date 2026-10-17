# -*- coding: utf-8 -*-
"""Cut strips: a dense sample of frames across a shot boundary.

Usage:
    python cut_strips.py [film.py] out.png 43.05,43.55 69.75,70.25

One row per window, N frames from t0 to t1, resized. Confirms that a transition
really blends, that the incoming page does not flash the wrong background, and
that the status bar does not jump.
"""
import importlib.util, os, sys

from PIL import Image


def main():
    args = [a for a in sys.argv[1:]]
    path, out, wins = "film.py", "strip.png", []
    for a in args:
        if "," in a and a.replace(",", "").replace(".", "").isdigit():
            t0, t1 = a.split(",")
            wins.append((float(t0), float(t1)))
        elif a.endswith(".png"):
            out = a
        else:
            path = a
    if not wins:
        print("give at least one window as t0,t1")
        return 1
    spec = importlib.util.spec_from_file_location("film", os.path.abspath(path))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    n, cw, ch = 8, 640, 360
    sheet = Image.new("RGB", (cw * n, ch * len(wins)), (60, 60, 60))
    for r, (t0, t1) in enumerate(wins):
        for j in range(n):
            t = t0 + (t1 - t0) * j / (n - 1.0)
            sheet.paste(m.frame_t(t).resize((cw, ch), Image.LANCZOS), (j * cw, r * ch))
            print("%.2f/seg%d" % (t, m.frame_at(t)[0]), end=" ", flush=True)
        print()
    sheet.save(out)
    print("strip", sheet.size, "->", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
