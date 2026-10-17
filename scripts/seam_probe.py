# -*- coding: utf-8 -*-
"""seam_probe.py -- is a flagged assembly seam in the FILM or in the ENCODE?

    python scripts/seam_probe.py <delivered.mp4> <k0> <k1> [--mod film.py] [--thr 0.05] [--ff <path>]

`verify_assembly.py` section D compares the last frame of one chunk with the first of the next and flags
a ratio above its floor. That test cannot tell two very different defects apart: a stale/foreign chunk
(the assembly is wrong) and a per-frame jump inside the film itself that happens to land near a boundary
(the renderer is wrong). This probe separates them.

It decodes the delivered frames k0..k1 BY FRAME NUMBER (the `select` filter, never -ss, so a seek cannot
be blamed) and renders the same frames from the module, then prints per frame:
    mp4 dL      consecutive-frame luma delta inside the delivered file
    film dL     the same delta rendered fresh from the module
    |mp4-film|  how far the delivered frame is from the rendered frame
Reading it:
    mp4 dL and film dL both spike, |mp4-film| flat  -> the FILM jumps: a renderer defect
    only mp4 dL spikes                              -> the encode/assembly is at fault
    |mp4-film| spikes at one frame, flat elsewhere  -> that frame was lost or duplicated
Calibration from a delivered 1920x1080 film: a page interior runs 0.005-0.032 per frame, a page change
0.35+, a quantised +-1 px position breath on a 176 px display line 0.36.

`--thr` hides quiet frames so only the interesting rows print.
"""
import argparse, importlib.util, os, subprocess, sys

import numpy as np
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8")


def find_ff(explicit=None):
    if explicit:
        return explicit
    if os.environ.get("FFMPEG"):
        return os.environ["FFMPEG"]
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    return "ffmpeg"


def main():
    HERE = os.path.dirname(os.path.abspath(__file__))
    ROOT = os.path.dirname(HERE)
    ap = argparse.ArgumentParser()
    ap.add_argument("mp4")
    ap.add_argument("k0", type=int)
    ap.add_argument("k1", type=int)
    ap.add_argument("--mod", default=os.path.join(ROOT, "film.py"))
    ap.add_argument("--thr", type=float, default=-1.0)
    ap.add_argument("--tmp", default=os.path.join(os.getcwd(), "_lvstmp"))
    ap.add_argument("--ff", default=None)
    a = ap.parse_args()
    FF = find_ff(a.ff)
    os.makedirs(a.tmp, exist_ok=True)

    mod = importlib.util.spec_from_file_location("film", os.path.abspath(a.mod))
    film = importlib.util.module_from_spec(mod)
    mod.loader.exec_module(film)

    # 1. the delivered frames, by frame number
    pat = os.path.join(a.tmp, "sp_%05d.png")
    for f in os.listdir(a.tmp):
        if f.startswith("sp_"):
            os.remove(os.path.join(a.tmp, f))
    subprocess.run([FF, "-y", "-hide_banner", "-loglevel", "error", "-i", a.mp4,
                    "-vf", "select='between(n,%d,%d)'" % (a.k0, a.k1), "-vsync", "0",
                    "-start_number", str(a.k0), pat], check=True)
    mp4f = {}
    for f in sorted(os.listdir(a.tmp)):
        if f.startswith("sp_"):
            mp4f[int(f[3:8])] = np.asarray(
                Image.open(os.path.join(a.tmp, f)).convert("L"), dtype=np.float32)

    # 2. the same frames straight from the renderer
    ren = {}
    for k in range(a.k0, a.k1 + 1):
        im = film.frame_t(film.T0 + k / float(film.FPS), k=k).convert("L")
        ren[k] = np.asarray(im, dtype=np.float32)

    print("%-6s %-9s %-9s %-11s %s" % ("k", "mp4 dL", "film dL", "|mp4-film|", "song t"))
    for k in range(a.k0, a.k1 + 1):
        m, r = mp4f.get(k), ren.get(k)
        dm = float(np.abs(m - mp4f[k - 1]).mean()) if (m is not None and k - 1 in mp4f) else float("nan")
        dr = float(np.abs(r - ren[k - 1]).mean()) if (r is not None and k - 1 in ren) else float("nan")
        de = float(np.abs(m - r).mean()) if (m is not None and r is not None) else float("nan")
        if a.thr >= 0 and not (max(dm, dr) >= a.thr or de >= a.thr):
            continue
        print("%-6d %-9.3f %-9.3f %-11.3f %.3f" % (k, dm, dr, de, film.T0 + k / float(film.FPS)))
    missing = [k for k in range(a.k0, a.k1 + 1) if k not in mp4f]
    if missing:
        print("!! the delivered file has no frame for k = %s (dropped frames)" % missing[:12])
    return 0


if __name__ == "__main__":
    sys.exit(main())
