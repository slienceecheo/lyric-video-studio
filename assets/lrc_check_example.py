# -*- coding: utf-8 -*-
"""REFERENCE EXAMPLE -- the official-LRC validator of the reference project.

Read this as a specification with a working implementation, then re-point it at your film
module.  It expects that module to expose:

    SEG    list of page dicts: t=(t0,t1), big=[display lines], cap="translation", s=renderer key
    T0     the film's start song time                    FPS    30
    LYR    {page index: lyric line number}               NLIN   len(STAMP)
    LRC    {lyric line number: "mm:ss.mmm"}              (the stamp printed in that page footer)
    STAMP  the official stamps, in order

The five checks (EN text / ZH translation / ORDER of the RENDERED lines / TIME window / STAMP in the
footer), the page-set assertion and the EXPECT table are specified in references/lyrics-and-cards.md
sections 1-3.

ORDER is optional: it switches on only when the module also exposes its display path
(`layout`, `display`, `frame`, `bg_col`, `fg_col`, `XR`).  It exists because every plan-level check
compares an AUTHORED list against the official line, and an authored list is always in reading order --
so nothing above can see a draw loop that puts line 0 at the BOTTOM.  That defect shipped 28 two-line
pages whose lyric read backwards through four deliveries, with `mismatches: 0` every time.
"""
import importlib.util, os, re, sys

LEAD = 0.150

# Two deliberate deviations from the official pair, printed as notes at the end:
#
#   lines 14 / 15 -- the official .zh.lrc crosses its own two stamps.  At 01:24.730
#     ("You won't be alone") it prints 「在你选择的世界里」; at 01:27.337 ("In this
#     world you've chosen as your own") it prints 「你不会孤单」.  The film pairs every
#     caption with the line actually sung, so these two are swapped against the file.
#   line 19 -- the official sentence 「所以我将明艳地舞进那良夜」 covers two pages
#     (24 + 25).  Each page carries a phrase that reads on its own, so 舞 appears on
#     both pages instead of a mechanical character split.
EXPECT = {14: ["你不会孤单"], 15: ["在你选择的世界里"],
          24: ["你不会孤单"], 25: ["在你选择的世界里"],      # the same two lines, chorus II
          19: ["所以我将明艳地起舞", "舞进那良夜"]}


def load(path):
    spec = importlib.util.spec_from_file_location("film", os.path.abspath(path))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def parse(path):
    """-> [(mm:ss.mmm, text)] in file order"""
    out = []
    for ln in open(path, encoding="utf-8-sig"):
        m = re.match(r"\[(\d+):(\d+\.\d+)\]\s*(.+?)\s*$", ln)
        if m:
            out.append((int(m.group(1)) * 60 + float(m.group(2)), m.group(3)))
    return out


def sec(v):
    m, s = divmod(float(v), 60.0)
    return "%02d:%06.3f" % (int(m), s)


def main():
    film = load(sys.argv[1] if len(sys.argv) > 1 else "hangxing/film.py")
    en = parse(sys.argv[2])
    zh = parse(sys.argv[3])
    en_lyr = [(t, x) for t, x in en if t >= 20.0]          # 12 credit lines drop out
    print("official: %d lines  (%d sung + %d credits)   zh: %d lines"
          % (len(en), len(en_lyr), len(en) - len(en_lyr), len(zh)))
    assert len(en_lyr) == 33 and len(zh) == 33, "official pair must hold 33 sung lines"

    pages = {}
    for i, sg in enumerate(film.SEG):
        n = film.LYR.get(i)
        if n is None:
            continue
        pages.setdefault(n, []).append(i)
    bad = 0

    print("-- 33 sung lines " + "-" * 60)
    for n in range(1, 34):
        want_en, want_zh = en_lyr[n - 1], zh[n - 1]
        stamp, w_en, w_zh = want_en[0], want_en[1], want_zh[1]
        got = pages.get(n, [])
        want_pages = EXPECT.get(n)
        if stamp != zh[n - 1][0]:
            print("  !! line %2d  stamp %s != zh stamp %s" % (n, sec(stamp), sec(zh[n - 1][0])))
            bad += 1
        if not got:
            print("  !! line %2d  NO PAGE            %s  %s" % (n, sec(stamp), w_zh))
            bad += 1
            continue
        g_en = " ".join(" ".join(film.SEG[i]["big"]) for i in got)
        g_zh = "".join(film.SEG[i].get("cap", "") for i in got)
        g_t = film.SEG[got[0]]["t"][0]
        ok1 = _norm(g_en) == _norm(w_en)
        if want_pages is not None:
            ok2 = [film.SEG[i].get("cap", "") for i in got] == want_pages
        else:
            ok2 = g_zh == w_zh
        ok3 = -LEAD <= g_t - stamp <= LEAD + 0.001
        ok4 = film.LRC.get(n) == sec(stamp)
        allok = ok1 and ok2 and ok3 and ok4
        if not allok:
            bad += 1
        print("  %2d %s %-44s pg %-9s %s  %+5.0f ms  %s"
              % (n, "OK " if allok else "!!!",
                 (w_zh[:21] + "…") if len(w_zh) > 22 else w_zh,
                 ",".join(str(i) for i in got), sec(stamp),
                 1000 * (g_t - stamp),
                 "" if allok
                 else "EN%s ZH%s TIME%s STAMP%s" % ("" if ok1 else "*", "" if ok2 else "*",
                                                    "" if ok3 else "*", "" if ok4 else "*")))
    unseen = sorted(set(pages) - set(range(1, 34)))
    if unseen:
        print("  !! lines outside 1..33: %s" % unseen)
        bad += 1
    print("-" * 92)
    if EXPECT:
        print("notes (deliberate, see EXPECT in this file):")
        print("  line 14/15 : official .zh.lrc crosses its own stamps; the film captions the line sung")
        print("  line 19    : official sentence split over pages 24+25, each page a readable phrase")
    bad += order_section(film)
    bad += short_section(os.path.dirname(os.path.abspath(sys.argv[1])), en_lyr, zh)
    print("mismatches: %d   %s" % (bad, "ALIGNED WITH THE OFFICIAL LRC" if not bad else "*** FIX ***"))
    return 1 if bad else 0


def order_section(film):
    """Does the PICTURE put the reading order top to bottom?

    For every multi-line lyric page: render one frame from the steady part of the page, crop the band
    each reading line should occupy, typeset every candidate line alone through the film's own display
    call at the same geometry, and correlate the z-normalised per-column ink mass.  The declared line
    must win its own band.

    Line j's band is spelled exactly the way a correct draw loop spells it -- line 0 at the HIGHEST
    baseline -- so this check FAILS on a film that draws line 0 at the bottom.  Proven with a negative
    control: copy the module, re-invert the draw rule in the copy, and require every band to fail.
    """
    need = ("layout", "display", "frame", "bg_col", "fg_col", "XR")
    if not all(hasattr(film, a) for a in need):
        print("%-46s skipped (module does not expose %s)"
              % ("ORDER render top-to-bottom", "/".join(need)))
        return 0
    import numpy as np
    Image, ImageDraw = film.Image, film.ImageDraw
    md = getattr(film, "_md", ImageDraw.Draw(Image.new("RGB", (8, 8))))
    acc = getattr(film, "ACCENT", None)
    no = ntie = bad = 0
    for sg in film.SEG:
        if sg.get("n", 1) < 2:
            continue
        pl = film.layout(md, sg)
        lines = pl["big"]["lines"]
        if len(lines) < 2:
            continue
        s, lh = pl["big"]["s"], pl["big"]["lh"]
        yb0, x = pl["big"]["yb0"], pl["big"]["x"]
        dark = sg.get("dark", False)
        im = film.frame(sg["f0"] + int(sg["n"] * 0.90)).convert("L")
        x0, x1 = int(x - 60), int(film.XR + 60)
        ybase = [yb0 - (len(lines) - 1 - j) * lh for j in range(len(lines))]
        jb = [int(round(y - 0.78 * s)) for y in ybase]
        jt = [int(round(y + 0.08 * s)) for y in ybase]

        def mass(a):
            a = np.asarray(a, dtype=np.float64)
            v = np.abs(a - np.median(a)).sum(axis=0)
            v = v - v.mean()
            n = np.sqrt((v * v).sum())
            return v / n if n > 1e-9 else v

        got = [mass(im.crop((x0, jb[j], x1, jt[j]))) for j in range(len(lines))]
        want = []
        for j, c in enumerate(lines):
            tile = Image.new("RGB", (x1 - x0, jt[j] - jb[j]), film.bg_col(dark))
            td = ImageDraw.Draw(tile)
            film.display(tile, td, x - x0, jt[j] - jb[j] - int(round(0.08 * s)),
                         s, c, film.fg_col(dark), acc, 1.0)
            want.append(mass(tile.convert("L")))
        for j in range(len(lines)):
            other = [c for c in range(len(lines)) if c != j]
            if other and float((want[j] * want[other[0]]).sum()) > 0.995:
                ntie += 1                      # two lines are visually identical: undecidable
                continue
            sc = sorted(((float((got[j] * want[c]).sum()), c)
                         for c in range(len(lines))), reverse=True)
            if sc[0][1] != j:
                bad += 1
                print("  !! page %d band %d (reading line %d) shows line %d: %r, not %r"
                      " -- the display is drawn upside down"
                      % (sg["i"], j, j, sc[0][1], lines[sc[0][1]], lines[j]))
            else:
                no += 1
    print("%-46s %d bands in reading order, %d undecidable (identical lines)"
          % ("ORDER render top-to-bottom", no, ntie))
    return bad


def short_section(here, en_lyr, zh):
    """The vertical cut is a montage of the chorus II repeat: its six lyric pages are
    official lines 20..25, cut on nearby onsets (<= LEAD after the stamp)."""
    path = os.path.join(here, "short.py")
    if not os.path.exists(path):
        return 0
    sys.path.insert(0, here)
    spec = importlib.util.spec_from_file_location("short", path)
    sh = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sh)
    print("-- short vertical cut " + "-" * 50)
    bad = 0
    for k, sg in enumerate(sh.SEG):
        if sg.get("s") == "end":
            continue
        n = 20 + k
        w_en, w_zh = en_lyr[n - 1][1], zh[n - 1][1]
        want = EXPECT.get(n, [w_zh])
        ok1 = _norm(" ".join(sg["big"])) == _norm(w_en)
        ok2 = [sg["cap"]] == want
        ok3 = -LEAD <= sg["t"][0] - en_lyr[n - 1][0] <= LEAD + 0.001
        if not (ok1 and ok2 and ok3):
            bad += 1
        print("  %2d %s %-44s pg %-9d %s  %+5.0f ms  %s"
              % (n, "OK " if (ok1 and ok2 and ok3) else "!!!",
                 (w_zh[:21] + "…") if len(w_zh) > 22 else w_zh, k, sec(en_lyr[n - 1][0]),
                 1000 * (sg["t"][0] - en_lyr[n - 1][0]),
                 "" if (ok1 and ok2 and ok3)
                 else "EN%s ZH%s TIME%s" % ("" if ok1 else "*", "" if ok2 else "*",
                                            "" if ok3 else "*")))
    return bad


def _norm(s):
    return re.sub(r"[^a-z0-9']+", " ", s.lower()).strip()


if __name__ == "__main__":
    sys.exit(main())
