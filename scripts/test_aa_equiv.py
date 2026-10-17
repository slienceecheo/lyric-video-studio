# -*- coding: utf-8 -*-
"""Equivalence + cost test for the upgraded AA class in assets/render_prefix.py.

The upgrade makes paint() downsample only the ink's bounding box. That is only safe if
the recorded box never misses ink, so this test renders the same drawing twice --
once forced to the full frame, once with the automatic crop -- and demands the two
images to be byte-identical. It also clones the OLD (full-frame) paint to measure what
the upgrade saves.

    python test_aa_equiv.py [path/to/render_prefix.py]
"""
import math
import os
import sys
import time

from PIL import Image, ImageChops, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))


def default_src():
    """Works both from <skill>/scripts/ and from a flat patch directory."""
    cands = [os.path.join(HERE, "assets", "render_prefix.py"),
             os.path.normpath(os.path.join(HERE, os.pardir, "assets", "render_prefix.py"))]
    for c in cands:
        if os.path.exists(c):
            return c
    return cands[1]


SRC = sys.argv[1] if len(sys.argv) > 1 else default_src()

src = open(SRC, encoding="utf-8").read()
i0 = src.index("class AA:")
i1 = src.index("\ndef base(", i0)
AA_SRC = src[i0:i1]
assert "def paint" in AA_SRC and "BB_PAD" in AA_SRC, "AA class not found in %s" % SRC

W, H = 1920, 1080
ns = {"Image": Image, "ImageDraw": ImageDraw, "W": W, "H": H}
exec(compile(AA_SRC, "<AA>", "exec"), ns)
AA = ns["AA"]

BG = (36, 22, 29)
FG = (250, 235, 240)


def mix(a):
    """A representative page worth of vector art: long polylines, dashes, ellipse
    outlines, a filled ellipse, arcs and a closed polygon."""
    a.line([(100, 200), (900, 240), (1500, 300), (1780, 420)], w=3)
    a.dash(200, 812, 1700, 820, 42, w=2, duty=0.5)
    a.ell(1200, 500, 1500, 700, out=255, w=4)
    a.ell(300, 300, 360, 360, out=255, w=2, fill=255)
    a.arc([300, 620, 700, 920], 30, 200, w=5)
    a.poly([(100, 1010), (400, 950), (700, 1030)], w=3)


def tiny(a):
    a.line([(1600, 940), (1700, 960), (1800, 930)], w=2)


def render(fn, region):
    im = Image.new("RGB", (W, H), BG)
    a = AA()
    fn(a)
    a.paint(im, FG, region=region)
    return im, a


def full_frame_paint(fn):
    """What the previous implementation did, for a before/after cost figure."""
    im = Image.new("RGB", (W, H), BG)
    a = AA()
    fn(a)
    im.paste(FG, mask=a.m.resize((W, H), Image.LANCZOS))
    return im


fails = []


def check(name, cond, note=""):
    print("  %-42s %s %s" % (name, "OK" if cond else "FAIL", note))
    if not cond:
        fails.append(name)


print("== 1. automatic crop must not change a single pixel ==")
for label, fn in (("dense mix", mix), ("three lines", tiny)):
    ref = full_frame_paint(fn)
    for region in (None, (0, 0, W, H)):
        got, a = render(fn, region)
        d = ImageChops.difference(ref, got)
        bb = d.getbbox()
        mx = max(d.getextrema(), key=lambda t: t[1])[1]
        check("%s, region=%s identical" % (label, "auto" if region is None else "full"),
              bb is None, "diff bbox %s, max %d" % (bb, mx))

print("== 2. the marked box must cover the real ink ==")
_, a = render(mix, None)
ink = a.m.getbbox()
if ink is None:
    check("ink exists", False)
else:
    ix0, iy0, ix1, iy1 = [v / 2.0 for v in ink]
    bx0, by0, bx1, by1 = a._bb
    check("ink bbox inside marked bbox",
          bx0 <= ix0 and by0 <= iy0 and bx1 >= ix1 and by1 >= iy1,
          "ink (%.1f,%.1f,%.1f,%.1f) in (%.1f,%.1f,%.1f,%.1f)" % (ix0, iy0, ix1, iy1, bx0, by0, bx1, by1))
    check("marked box is not wasteful", (bx1 - bx0) * (by1 - by0) < 0.75 * W * H,
          "%.0f%% of frame" % (100.0 * (bx1 - bx0) * (by1 - by0) / (W * H)))

print("== 3. degenerate cases ==")
im = Image.new("RGB", (W, H), BG)
a = AA()
a.paint(im, FG)
check("nothing drawn -> no-op", ImageChops.difference(im, Image.new("RGB", (W, H), BG)).getbbox() is None)
im2, a2 = render(lambda a: a.line([(-400, -400), (2400, 1300)], w=4), None)
ref2 = full_frame_paint(lambda a: a.line([(-400, -400), (2400, 1300)], w=4))
check("off-canvas line identical", ImageChops.difference(im2, ref2).getbbox() is None)
im3, a3 = render(lambda a: a.line([(50, 50), (50, 50)], w=2), None)
check("zero-length line pastes", ImageChops.difference(im3, Image.new("RGB", (W, H), BG)).getbbox() is not None)

print("== 4. cost: full-frame vs automatic crop (best of 5) ==")


def bench(fn, region):
    best = 1e9
    for _ in range(5):
        t = time.perf_counter()
        render(fn, region)
        best = min(best, time.perf_counter() - t)
    return best * 1000.0


def bench_old(fn):
    best = 1e9
    for _ in range(5):
        t = time.perf_counter()
        full_frame_paint(fn)
        best = min(best, time.perf_counter() - t)
    return best * 1000.0


for label, fn in (("dense mix", mix), ("three lines", tiny)):
    old = bench_old(fn)
    new = bench(fn, None)
    forced = bench(fn, (0, 0, W, H))
    print("  %-12s old(full frame) %6.2f ms   auto-crop %6.2f ms (%.0fx)   forced-full %6.2f ms"
          % (label, old, new, old / new, forced))

print("== 5. the documented cost law ==")
tiny_strip = Image.new("L", (W * 2, H * 2), 0)
td = ImageDraw.Draw(tiny_strip)
td.line([(0, 100), (W * 2, 100)], fill=255, width=4)


def time_resize(box):
    best = 1e9
    for _ in range(5):
        t = time.perf_counter()
        tiny_strip.crop(box).resize(((box[2] - box[0]) // 2, (box[3] - box[1]) // 2), Image.LANCZOS)
        best = min(best, time.perf_counter() - t)
    return best * 1000.0


small_box = (3200, 190, 3400, 210)
print("  resize 1920x1080 %6.2f ms   resize %dx%d %6.2f ms   resize 1920x4 %6.2f ms"
      % (time_resize((0, 0, W * 2, H * 2)), (small_box[2] - small_box[0]) // 2, (small_box[3] - small_box[1]) // 2,
         time_resize(small_box), time_resize((0, 200, W * 2, 208))))

print("\n%s" % ("FAILURES: %s" % fails if fails else "RESULT: AA upgrade is pixel-identical and cropped"))
sys.exit(1 if fails else 0)
