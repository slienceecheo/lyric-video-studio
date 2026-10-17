# -*- coding: utf-8 -*-
"""Re-render only the frames affected by a layout change.

Usage:
    python rerange.py [film.py] [--out DIR] [--procs N] [--segs 13,19,34]

Affected segments are recomputed automatically: any segment whose display box
gets clamped against content, plus every segment that draws a log block. Each
affected segment contributes its own frame range plus the transition tail
before it (the previous segment renders its last seconds blended with the next
one). Frames are written as DIR/f%05d.png with k = int((t - T0) * FPS).

On Windows the Pool MUST live under __main__ (spawn start method), otherwise:
  RuntimeError: An attempt has been made to start a new process before the
  current process has finished its bootstrapping phase.
"""
import importlib.util, math, os, sys
from multiprocessing import Pool

FILM = "film.py"
OUT = None
PROCS = 8
TAIL = 20
_M = None


def load():
    global _M
    if _M is None:
        spec = importlib.util.spec_from_file_location("film", os.path.abspath(FILM))
        _M = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_M)
    return _M


def work(k):
    m = load()
    m.frame_t(m.T0 + k / float(m.FPS), k=k).save(os.path.join(OUT, "f%05d.png" % k))
    return k


def main():
    global FILM, OUT, PROCS
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    opts = [a for a in sys.argv[1:] if a.startswith("--")]
    if args:
        FILM = args[0]
    for o in opts:
        if o.startswith("--procs"):
            PROCS = int(o.split("=", 1)[1])
        if o.startswith("--out"):
            OUT = o.split("=", 1)[1]
    m = load()
    from PIL import Image, ImageDraw
    d0 = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    if OUT is None:
        OUT = getattr(m, "OUT2", "out2")
    os.makedirs(OUT, exist_ok=True)

    def kr(t):
        return int(math.ceil((t - m.T0) * m.FPS))

    forced = set()
    for o in opts:
        if o.startswith("--segs"):
            forced = {int(x) for x in o.split("=", 1)[1].split(",") if x.strip()}

    aff = set(forced)
    for i, sg in enumerate(m.SEG):
        if sg.get("big"):
            s = sg.get("bigS", 150)
            t = sg["big"]
            x = sg.get("bigx", m.X0)
            yb = sg.get("bigy", 830)
            sm = sg.get("bigfont") == "smiley"
            if sg.get("bigc"):
                x = (m.W - (m.bigw(d0, s, t) if sm else m.width(d0, s, t))) / 2.0
            bb = m.big_box(d0, x, yb, s, t, sg)
            if any(m._hit(bb, cb) for cb in m.content_boxes(d0, sg)):
                aff.add(i)
        if sg.get("log"):
            aff.add(i)

    rng = []
    for i in sorted(aff):
        t0, t1 = m.SEG[i]["t"]
        k0, k1 = kr(t0), kr(t1)
        prev = kr(m.SEG[i - 1]["t"][0]) if i else 0
        rng.append((max(prev, k0 - TAIL), k0))
        rng.append((k0, k1))
    rng.sort()
    merged = []
    for a, b in rng:
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    jobs = [k for a, b in merged for k in range(a, b)]
    print("affected segs: %s" % sorted(aff))
    print("frames: %d  ranges: %s  out: %s" % (len(jobs), merged, OUT))
    with Pool(PROCS) as p:
        for n, _ in enumerate(p.imap_unordered(work, jobs, chunksize=4)):
            if n % 200 == 0:
                print("rendered %d/%d" % (n, len(jobs)), flush=True)
    print("RERENDER DONE %d frames" % len(jobs), flush=True)


if __name__ == "__main__":
    main()
