# -*- coding: utf-8 -*-
"""Ink-bbox collision audit for a lyric-video film module.

Usage:
    python layout_audit.py [film.py]                  # legacy mode (SEG fields)
    python layout_audit.py [film.py] --from-layout     # plan mode (module layout())
    python layout_audit.py [film.py] --from-layout --require-deco

Measures every text layer of every segment with the film module's own helpers
and checks them pairwise for a real 2D intersection. Exit code 0 means the film
is safe to render/deliver (remaining collisions: 0); exit code 1 lists the
colliding pairs.

TWO MODES, and picking the wrong one is a false green:
  * legacy mode reads the SEG field names of `assets/film_template.py`
    (`bigS`/`bigy`/`bigx`, `codey`, `capy`, `log`). It is only valid for a module
    that still places text from those fields.
  * `--from-layout` asks the module for `layout(d, seg)` and audits the boxes the
    module returns. Use this whenever the film computes its own plan: the
    reference project's first audit reported `0` collisions while the rendered
    frame had wind strokes across 今州风紧, because it was measuring boxes the
    renderer never drew.

`--require-deco` fails the run when a page declares a decoration but hands the
audit no box for it -- the second false green. A decoration that is not in the
box set can cover any glyph it likes and the audit stays silent.
"""
import importlib.util, os, sys

# ---- per-project tunables (override from the film module if it defines them)
LOG_SEGS = ("journey",)     # segment keys whose renderer draws a log block
LOG_S, LOG_LH, LOG_W, LOG_TOP = 34.0, 62.0, 600.0, 46.0


def load(path):
    spec = importlib.util.spec_from_file_location("film", os.path.abspath(path))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def log_box(m, sg):
    ly = sg.get("codey", 268)
    if sg.get("code"):
        cs = sg.get("codeS", 40)
        ly += (len(sg["code"]) - 1) * cs * sg.get("lh", 1.78) + cs * 0.42
    ly += LOG_TOP
    n = len(sg.get("log") or [])
    return (m.X0, ly - LOG_S * 0.9, m.X0 + LOG_W, ly + (n - 1) * LOG_LH + LOG_S * 0.2)


def boxes_from_layout(m, d, sg):
    """Every box the module's own plan says it will draw, decorations included.

    `pl["boxes"]` is the renderer's own named list and usually already carries
    cap/big/seal; the `big`/`cap`/`seal` plan blocks are added only when the list
    does not mention them, and identical rectangles are deduped -- a box audited
    against its own copy reads as a collision on every page.
    """
    pl = m.layout(d, sg)
    seen = {}

    def add(name, box):
        key = tuple(round(float(v), 1) for v in box)
        if key not in seen:
            seen[key] = (name, tuple(float(v) for v in box))

    for entry in (pl.get("boxes") or []):
        if len(entry) == 2 and isinstance(entry[1], (tuple, list)):
            add(str(entry[0]), entry[1])
        elif len(entry) == 4 and all(isinstance(v, (int, float)) for v in entry):
            add("box", entry)
    for name in ("big", "cap", "seal"):
        blk = pl.get(name)
        if isinstance(blk, dict) and blk.get("box"):
            add(name, blk["box"])
    n_deco = len(seen)
    for j, db in enumerate(pl.get("deco_boxes") or []):
        if len(db) == 2 and isinstance(db[1], (tuple, list)):
            add("deco:%s" % db[0], db[1])
        elif len(db) == 4 and all(isinstance(v, (int, float)) for v in db):
            add("deco%d" % j, db)
    deco = pl.get("deco")
    has_rect = isinstance(deco, (tuple, list)) and len(deco) == 4
    if has_rect:
        add("deco", deco)
    # the detectable inconsistency: a decoration rect the plan will draw, with no
    # decoration box handed to the audit
    naked = has_rect and len(seen) == n_deco
    return list(seen.values()), naked


def boxes(m, d, sg):
    out = []
    for j, b in enumerate(m.content_boxes(d, sg)):
        out.append(("code%d" % j if j == 0 else "rows", b))
    if sg.get("log"):
        if sg.get("s") in LOG_SEGS:
            out.append(("log", log_box(m, sg)))
        else:
            print("WARN seg %s has a log block but is not in LOG_SEGS: invisible to the audit" % sg.get("s"))
    if sg.get("big"):
        s = sg.get("bigS", 150)
        t = sg["big"]
        x = sg.get("bigx", m.X0)
        yb = sg.get("bigy", 830)
        sm = sg.get("bigfont") == "smiley"
        if sg.get("bigc"):
            x = (m.W - (m.bigw(d, s, t) if sm else m.width(d, s, t))) / 2.0
        for cb in m.content_boxes(d, sg):
            if m._hit(m.big_box(d, x, yb, s, t, sg), cb):
                yb = cb[3] + abs(m.ink_ext(s, sm)[0]) * s + 14
                break
        out.append(("big", m.big_box(d, x, yb, s, t, sg)))
    if sg.get("cap"):
        cx, cy, cs = sg.get("capx", m.X0), sg.get("capy", 1002), sg.get("capS", 50)
        out.append(("cap", (cx, cy - cs * 0.85, cx + m.width(d, cs, sg["cap"]), cy + cs * 0.15)))
    if sg.get("seal"):
        sx, sy, ss = sg.get("sealx", 1650), sg.get("sealy", 880), sg.get("sealS", 126)
        out.append(("seal", (sx - ss / 2.0, sy - ss / 2.0, sx + ss / 2.0, sy + ss / 2.0)))
    return out


def main():
    from PIL import Image, ImageDraw
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    flags = {a for a in sys.argv[1:] if a.startswith("-")}
    path = args[0] if args else "film.py"
    m = load(path)
    plan_mode = "--from-layout" in flags
    need = ("layout", "SEG", "_hit") if plan_mode else ("content_boxes", "big_box", "_hit", "ink_ext")
    for name in need:
        if not hasattr(m, name):
            print("FAIL %s lacks %s -- not audit-capable%s"
                  % (path, name, " in --from-layout mode" if plan_mode else ""))
            return 2
    d0 = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    W, H = getattr(m, "W", None), getattr(m, "H", None)
    print("mode: %s  segments: %d" % ("layout plan" if plan_mode else "legacy SEG", len(m.SEG)))
    if plan_mode and W and H:
        print("canvas: %dx%d" % (W, H))
    bad = 0
    naked = []
    off = 0
    for i, sg in enumerate(m.SEG):
        if plan_mode:
            bs, undeco = boxes_from_layout(m, d0, sg)
            if undeco:
                naked.append((i, sg.get("s")))
        else:
            try:
                bs, undeco = boxes(m, d0, sg), False
            except Exception as e:
                print("FAIL legacy mode cannot measure SEG %2d %-9s: %s: %s"
                      % (i, sg.get("s"), type(e).__name__, e))
                print("     This module does not place text from SEG fields -- rerun with")
                print("     --from-layout so the audit reads the module's own plan.")
                return 2
        for name, b in bs:
            if W and H and (b[0] < -1 or b[1] < -1 or b[2] > W + 1 or b[3] > H + 1):
                off += 1
                print("SEG %2d %-9s %-9s OFF-CANVAS %s" % (i, sg.get("s"), name,
                                                           tuple(int(v) for v in b)))
        for a in range(len(bs)):
            for b in range(a + 1, len(bs)):
                if m._hit(bs[a][1], bs[b][1]):
                    bad += 1
                    print("SEG %2d %-9s %s %s HIT %s %s" % (
                        i, sg.get("s"), bs[a][0], tuple(int(v) for v in bs[a][1]),
                        bs[b][0], tuple(int(v) for v in bs[b][1])))
    for i, key in naked:
        print("WARN SEG %2d %-9s draws a decoration but hands the audit no deco box -- invisible"
              % (i, key))
    if "--require-deco" in flags and naked:
        print("FAIL %d page(s) declare a decoration the audit cannot see; "
              "add it to the plan's deco_boxes" % len(naked))
        bad += len(naked)
    if off:
        print("out-of-canvas boxes: %d" % off)
    print("remaining box collisions: %d" % bad)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
