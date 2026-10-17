# -*- coding: utf-8 -*-
# TEMPLATE: copy next to your project and re-point BASE / T0 / T1 / font paths.
# This is the reference project as shipped.
# Re-point BASE at your project dir, or set the LYRIC_VIDEO_BASE env var.
# 玄翎谣 · 程序化歌词片（全曲版）—— 基础设施：网格 / 背景 / 转场
import sys, os, math, json, random, traceback
from PIL import Image, ImageDraw, ImageFont
import numpy as np

BASE = os.environ.get("LYRIC_VIDEO_BASE", "<project dir>")
_src = open(BASE + "/render.py", encoding="utf-8").read()
exec(compile(_src.split("FN = [shot1")[0], "render_prefix", "exec"), globals())

T0, T1 = 17.934, 278.976
FPS = 30
NFR = int((T1 - T0) * FPS)
ENVS = json.load(open(BASE + "/env_full.json"))
X0, CELL, COLS = 160.0, 20.0, 80
PAD = 30
W2, H2 = W + 2 * PAD, H + 2 * PAD
OX, OY = PAD, PAD
CLIP, OUT2 = BASE + "/clip", BASE + "/out2"

# ================= GENERATION-2 CONVENTIONS (full text: references/*.md) =================
# 1 POLARITY has exactly one authority: the `dark` argument in the segment table below. If
#   you keep a separate polarity list, delete the per-page values -- two sources drift.
# 2 Every page keeps ONE continuous channel between its reveal and the next cut: the
#   breathing block further down (BR_* + breath_at), applied in exactly one place (the main
#   line's y) so it can never dislocate anything. Never a per-beat on/off switch: 3 Hz binary
#   toggling is what makes a viewer say "闪来闪去，看得眼睛很不好受". Measure it, never assume
#   it: scripts/motion_probe.py <this file> --seg N
# 3 FOOTERS ARE DERIVED, never hand-typed per page: line index, official stamp and card role
#   all come from tables (footer contract below). Check with `audit`; in a real project also
#   run assets/lrc_check_example.py against the official LRC.
# 4 A card page must not restate the neighbouring lyric, and adjacent pages must differ
#   visually -- otherwise the cut reads as "it never turned the page": `python <this> audit`.
# 5 The picture prints its own FRAME COUNTER in the right footer field. That number is the
#   only instrument that makes a whole-chunk timeline offset visible.
# 6 CHUNKS ARE NOT "any N-frame range": compute them with assets/chunk_manifest.py
#   (`python <this> plan`), have the driver write chunks.json, and mux from that list --
#   never from a glob over the output directory (a stale chunk shifted a delivered film by
#   224 frames / 7.4 s behind correctly rendered pictures).
# 7 Never trust the PNG sequence: re-read the delivered mp4 (scripts/verify_delivery.py) and
#   reconcile the chunk manifest (scripts/verify_assembly.py).
# 8 Cost scales with the NUMBER OF paint() CALLS, not with area: one 1920x4 line-art strip
#   costs about the same as a full 1920x1080 frame. Merge same-colour strokes into one AA().
# 9 PIL rasterises text on WHOLE pixels even when the y you pass is a float, so the display
#   line moves in 1 px steps and any amplitude under a pixel is invisible (a 42 px caption
#   breathing +-0.4 px never moves at all). Keep it at 1-3 px of the type size, and never
#   read sub-pixel text motion out of a rendered frame.
# =========================================================================================

# ---------------- 网格 ----------------
def gx(c): return X0 + c * CELL
def clen(s): return sum(2 if cjk(ch) else 1 for ch in s)
def snap(x): return X0 + round((x - X0) / CELL) * CELL

def align_rows(rows, cmtcol=56, eqmin=13):
    par = []
    for t, st in rows:
        cmt = ""; body = t
        k = t.find(" // ")
        if k >= 0: body, cmt = t[:k], t[k + 1:]
        lhs = rhs = None
        if not cmt:
            for idx in range(len(body) - 2):
                if body[idx] == " " and body[idx + 1] == "=" and body[idx + 2] == " ":
                    if idx + 3 < len(body) and body[idx + 3] == "=": continue
                    if idx > 0 and body[idx - 1] in "=!<>+-*/%&|": continue
                    lhs, rhs = body[:idx], body[idx + 2:]; break
        par.append([st, body, cmt, lhs, rhs])
    eqc = 0
    for p in par:
        if p[3] is not None: eqc = max(eqc, clen(p[3]))
    eqcol = max(eqmin, (eqc // 4 + 1) * 4 + 1)
    out = []
    for st, body, cmt, lhs, rhs in par:
        if lhs is not None:
            body = lhs + " " * max(1, eqcol - clen(lhs) - 1) + " = " + rhs.lstrip()
        if cmt:
            body = body + " " * max(1, cmtcol - clen(body) - 1) + cmt
        out.append((body, st))
    return out

def snapS(s): return 40 if s < 50 else 60

def typing2(d, x, y0, s, lines, p, fg, dim, reveal_by=0.55, lh=1.75, cmtcol=56):
    x = snap(x); s = snapS(s)
    lines = align_rows(lines, cmtcol)
    total = sum(len(t) for t, c in lines)
    done = int(total * min(1.0, max(0.0, p) / reveal_by))
    y = y0; used = 0; last = None
    for t, c in lines:
        if used >= done: break
        n = done - used
        col = fg if c == "fg" else (ZHU if c == "zhu" else dim)
        if n >= len(t):
            ex = rich(d, x, y, s, t, col); used += len(t); last = (ex, y, col); y += s * lh
        else:
            ex = rich(d, x, y, s, t, col, reveal=n); last = (ex, y, col)
            if BLINK: cursor(d, ex + 0.12 * s, y, s, col)
            used = done; break
    if last is not None and used >= total and BLINK:
        cursor(d, last[0] + 0.12 * s, last[1], s, last[2])
    return y

def status2(d, left, right, y=1028, s=30, col=DIM2):
    rich(d, X0, y, s, left, col)
    rich(d, W - X0 - width(d, s, right), y, s, right, col)

def topbar2(d, t, col=DIM2, s=30):
    rich(d, X0, 128, s, t, col)

globals()["typing"] = typing2
globals()["status"] = status2
globals()["topbar"] = topbar2

# ---------------- 背景层 ----------------
def tint(im, m, color, ox=0, oy=0):
    ci = Image.new("RGB", im.size, color)
    m2 = Image.new("L", im.size, 0)
    m2.paste(m, (ox, oy))
    im.paste(ci, mask=m2)

def L_grad(im, fg, a, seg):
    m = Image.new("L", (W, H), 0); dd = ImageDraw.Draw(m)
    for y in range(0, H, 6):
        dd.rectangle([0, y, W, y + 5], fill=int(a * (1 - y / float(H)) ** 1.3))
    tint(im, m, fg, OX, OY)

def L_mottle(im, fg, a, seg):
    rng = np.random.default_rng(seg["seed"])
    n = rng.random((H // 4, W // 4))
    n = (n * 0.5 + 0.5) ** 1.6
    g = Image.fromarray((n * a).astype("uint8")).resize((W, H), Image.BILINEAR)
    tint(im, g, fg, OX, OY)

def L_grid(im, fg, a, seg):
    m = Image.new("L", (W, H), 0); dd = ImageDraw.Draw(m)
    for c in range(0, COLS + 1, 5):
        dd.line([gx(c), 100, gx(c), H - 52], fill=a, width=1)
    for y in range(170, H - 52, 70):
        dd.line([X0, y, W - X0, y], fill=a, width=1)
    tint(im, m, fg, OX, OY)

def L_ruler(im, fg, a, seg):
    m = Image.new("L", (W, H), 0); dd = ImageDraw.Draw(m)
    for c in range(0, COLS + 1):
        x = gx(c); h = 22 if c % 10 == 0 else (12 if c % 5 == 0 else 5)
        dd.line([x, 50, x, 50 + h], fill=a, width=1)
    for c in range(0, COLS + 1, 10):
        dd.text((gx(c) + 4, 16), str(c), font=F(M, 19), fill=a)
    dd.line([X0 - 48, 96, W - X0, 96], fill=a, width=1)
    dd.line([X0 - 48, 96, X0 - 48, H - 88], fill=a, width=1)
    for j in range(1, 14):
        dd.text((X0 - 44, 118 + j * 70), ("%02d" % j), font=F(M, 19), fill=a)
    tint(im, m, fg, OX, OY)

def L_frame(im, fg, a, seg):
    m = Image.new("L", (W, H), 0); dd = ImageDraw.Draw(m)
    L = 52
    for cx, cy, sx, sy in [(52, 52, 1, 1), (W - 52, 52, -1, 1), (52, H - 52, 1, -1), (W - 52, H - 52, -1, -1)]:
        dd.line([cx, cy, cx + sx * L, cy], fill=a, width=3)
        dd.line([cx, cy, cx, cy + sy * L], fill=a, width=3)
    for j in range(1, 11):
        y = 150 + j * 80
        dd.line([W - 48, y, W - 62, y], fill=a, width=1)
    for j in range(1, 15):
        x = 190 + j * 105
        dd.line([x, H - 48, x, H - 62], fill=a, width=1)
    tint(im, m, fg, OX, OY)

def L_ghost(im, fg, a, seg):
    g = seg.get("ghost") or ""
    if not g: return
    s = seg.get("ghostS", 430)
    m = Image.new("L", (W, H), 0); dd = ImageDraw.Draw(m)
    x = seg.get("ghostx", 1120); y = seg.get("ghosty", 560)
    for ch in g:
        dd.text((x, y), ch, font=F(MM, s), fill=a, anchor="ls"); x += s * 0.94
    tint(im, m, fg, OX, OY)

def L_ink(im, fg, a, seg):
    kind = seg.get("ink", "shan")
    m = Image.new("L", (W, H), 0); dd = ImageDraw.Draw(m)
    if kind == "shan":
        for r, (base, hh) in enumerate([(H - 120, 190), (H - 196, 128), (H - 268, 86)]):
            pts = []
            for x in range(-40, W + 60, 18):
                y = base - hh * (0.40 + 0.60 * abs(math.sin(x * 0.0015 + r * 2.1 + seg["seed"])))
                pts.append((x, y))
            dd.polygon(pts + [(W + 60, H), (-40, H)], fill=int(a * (1 - r * 0.22)))
    elif kind == "yun":
        for j in range(11):
            y = 90 + (j * 173 + seg["seed"] * 37) % 860
            w = 380 + (j * 233) % 880
            x = (j * 331 + seg["seed"] * 61) % 1420 - 160
            dd.rounded_rectangle([x, y, x + w, y + 40], radius=20, fill=int(a * 0.55))
    elif kind == "bo":
        for j in range(15):
            y = 250 + j * 54
            for x in range(-60, W + 40, 150):
                dd.arc([x, y - 24, x + 150, y + 24], 0, 180, fill=int(a * 0.7), width=3)
    elif kind == "zhu":
        for j in range(30):
            x = 40 + j * 66 + (j % 4) * 9
            dd.line([x, 0, x - 40 + (j % 6) * 16, H], fill=int(a * 0.42), width=6)
    elif kind == "yu":
        for j in range(220):
            x = (j * 137 + seg["seed"] * 71) % (W + 120) - 60
            y = (j * 419 + seg["seed"] * 29) % H
            dd.line([x, y, x - 8, y + 26 + (j % 5) * 9], fill=int(a * 0.75), width=2)
    elif kind == "xing":
        for j in range(150):
            x = (j * 271 + seg["seed"] * 53) % W
            y = (j * 149 + seg["seed"] * 17) % H
            r = 1 + (j % 3)
            dd.ellipse([x - r, y - r, x + r, y + r], fill=a)
    tint(im, m, fg, OX, OY)

BGS = {"grad": L_grad, "mottle": L_mottle, "grid": L_grid, "ruler": L_ruler, "frame": L_frame, "ghost": L_ghost, "ink": L_ink}
_bgc = {}

def static_bg(i):
    if i in _bgc: return _bgc[i]
    seg = SEG[i]
    dark = seg["dark"]
    bg = DARK if dark else LIGHT
    fg = LIGHT if dark else DARK
    im = Image.new("RGB", (W2, H2), bg)
    for name in seg.get("back", []):
        f = BGS.get(name)
        if not f: continue
        al = (seg.get("alpha") or {}).get(name)
        if al is None: al = DEF_ALPHA.get(name, 12)
        try: f(im, fg, al, seg)
        except Exception:
            traceback.print_exc()
    _bgc[i] = im
    return im

def base(i, p=0.0):
    seg = SEG[i]; dark = seg["dark"]
    dx = 9 * math.sin(i * 1.7 + p * 0.8); dy = 7 * math.cos(i * 2.3 + p * 0.6)
    ox = int(PAD + dx); oy = int(PAD + dy)
    im = static_bg(i).crop((ox, oy, ox + W, oy + H))
    return im, dark, (DARK if dark else LIGHT), (LIGHT if dark else DARK)

globals()["base"] = base

def dust(im, i, t, fg, seg):
    n = seg.get("dust", 0)
    if not n: return
    rng = random.Random(7000 + i)
    dd = ImageDraw.Draw(im)
    up = seg.get("dustdir") == "up"
    for j in range(n):
        bx = rng.random() * W; by = rng.random() * H
        sp = 0.5 + rng.random() * 1.8
        cyc = 26.0
        ph = (t / cyc * sp) % 1.0
        x = (bx + (0 if not up else 26 * math.sin(t * 0.4 + j))) % W
        y = (by + (1 - ph if up else ph) * H) % H
        r = 1.0 + rng.random() * 2.4
        dd.ellipse([x - r, y - r, x + r, y + r], fill=DIM if (j % 3 == 0) else DIM2)

# ---------------- 转场 ----------------
def tr_roll(a, b, q, seg):
    bgc = DARK if seg["dark"] else LIGHT
    im = Image.new("RGB", (W, H), bgc)
    dy = int(q * H)
    y = int(6 * (1 - q))
    im.paste(b, (0, H - dy + y)); im.paste(a, (0, -dy + y))
    return im

def tr_wipe(a, b, q, seg):
    edge = int(q * (W + 240)) - 120
    xx = np.arange(W, dtype="float32")[None, :]
    m = np.clip((edge - xx) / 70.0, 0, 1)
    mm = Image.fromarray(np.repeat((m * 255).astype("uint8"), H, axis=0))
    return Image.composite(b, a, mm)

def tr_blinds(a, b, q, seg):
    yy = np.arange(H, dtype="float32")[:, None]
    band = H / 9.0
    j = np.floor(yy / band)
    m = np.clip((q - j * 0.0833) / 0.34, 0, 1)
    mm = Image.fromarray(np.repeat((m * 255).astype("uint8"), W, axis=1))
    return Image.composite(b, a, mm)

def tr_slice(a, b, q, seg):
    im = a.copy(); x = int((1 - q) * W)
    if x > 0 and x < W: im.paste(b.crop((0, 0, W - x, H)), (x, 0))
    elif x <= 0: im = b.copy()
    return im

def tr_dissolve(a, b, q, seg): return Image.blend(a, b, q)

def tr_flash(a, b, q, seg):
    c = DARK if seg["dark"] else LIGHT
    solid = Image.new("RGB", (W, H), c)
    if q < 0.38: return Image.blend(a, solid, q / 0.38)
    return Image.blend(solid, b, (q - 0.38) / 0.62)

def tr_cut(a, b, q, seg): return a if q < 0.5 else b

TRANS = {"roll": tr_roll, "wipe": tr_wipe, "blinds": tr_blinds, "slice": tr_slice,
         "dissolve": tr_dissolve, "flash": tr_flash, "cut": tr_cut}

# ---------------- 连续呼吸：全片唯一的连续动效通道 ----------------
BR_PERIOD = 1.45      # slow-sine period (s)
BR_ENV = 0.48         # weight of the smoothed-envelope swell
BR_SINE = 0.52        # weight of the slow sine
BR_DEPTH = 0.010      # amplitude: 1% of the font size
BR_WIN = 8            # +-0.27 s box window, removes envelope transients


def softlimit(x):
    """Bounded compression: near-linear under 1, never overshoots."""
    return x / (1.0 + abs(x))


def _env_at(j):
    return ENVS[max(0, min(len(ENVS) - 1, int(j)))]


_env_sm = []
for _i in range(NFR):
    _a, _b = max(0, _i - BR_WIN), min(NFR, _i + BR_WIN + 1)
    _env_sm.append(sum(_env_at(_j) for _j in range(_a, _b)) / float(_b - _a))
_sv = sorted(_env_sm)
BR_MEAN = sum(_env_sm) / float(len(_env_sm))
BR_SPAN = max(0.05, (_sv[int(0.90 * len(_sv))] - _sv[int(0.10 * len(_sv))]) * 0.5)


def breath_at(t, k=None):
    """-1..1 continuous breathing value. It never jumps -- that is deliberate."""
    if k is None: k = int((t - T0) * FPS)
    x = (_env_sm[max(0, min(NFR - 1, int(k)))] - BR_MEAN) / BR_SPAN
    return BR_ENV * softlimit(x) + BR_SINE * math.sin(2.0 * math.pi * t / BR_PERIOD)


_BR = 0.0             # this frame's breath value, set by frame()
_I = -1               # current segment index, set by frame()
_K = 0                # current frame number, set by frame()


def _entry(p):
    """Entry stagger of the main line: rises from +26 px and settles by p=0.20.
    On multi-line pages offset each line by i*0.17 s (renderer.md section 8)."""
    return max(0.0, min(1.0, (p - 0.06) / 0.14))


# ---------------- 帧 ----------------
LEG = {"L1": shot1, "L2": shot2, "L3": shot3, "L4": shot4, "L5": shot5,
       "L6": shot6, "L7": shot7, "L8": shot8, "L9": shot9, "L10": shot10}
REND = {}

def draw_seg(i, p, t):
    seg = SEG[i]
    im, dark, bg, fg = base(i, p)
    d = ImageDraw.Draw(im)
    dust(im, i, t, fg, seg)
    name = seg["s"]
    if name in LEG: LEG[name](im, d, p, dark, fg)
    else: REND[name](im, d, p, dark, fg, seg)
    return im

def frame(i, p, k=None, t=None):
    global ENV, BLINK, _BR, _I, _K
    seg = SEG[i]
    a, b = seg["t"]
    if t is None: t = a + p * (b - a)
    if k is None: k = int((t - T0) * FPS)
    ENV = ENVS[max(0, min(len(ENVS) - 1, k))]
    BLINK = (int(t * 3) % 2 == 0)
    _BR = breath_at(t, k)          # continuous channel, consumed by C_text only
    _I, _K = i, int(k)
    return draw_seg(i, max(0.0, min(1.0, p)), t)

def frame_at(t):
    for i, s in enumerate(SEG):
        a, b = s["t"]
        if a <= t < b: return i, (t - a) / (b - a)
    return len(SEG) - 1, 1.0

def frame_t(t, k=None):
    i, p = frame_at(t)
    seg = SEG[i]; a, b = seg["t"]
    kind = seg.get("tr", "cut"); trd = seg.get("trd", 0.5)
    if kind != "cut" and i + 1 < len(SEG) and t > b - trd:
        q = (t - (b - trd)) / trd
        cur = frame(i, min(1.0, (t - a) / (b - a)))
        nxt = frame(i + 1, 0.0, t=t)
        return TRANS.get(kind, tr_cut)(cur, nxt, max(0.0, min(1.0, q)), SEG[i + 1])
    return frame(i, p)

# ================= 全新分镜渲染器 =================
DEF_ALPHA = {"grad": 24, "mottle": 10, "grid": 12, "ruler": 30, "frame": 34, "ghost": 11, "ink": 15}

def mirror(seg):
    return (lambda v: W - v) if seg.get("mirror") else (lambda v: v)

_INK = {}
def ink_ext(s, smiley):
    """(top, bottom) 相对基线的墨迹偏移，按字号缓存；用超集字符测量，取保守值"""
    k = (smiley, s)
    if k not in _INK:
        tt = "玄翎谣荒山萧萧长风长归期遥遥河无梁家酒难尝发染雪霜勿望忘秋夜凉回故乡"
        yy = int(s * 1.7)
        tmp = Image.new("L", (int(s * len(tt)) + 80, int(s * 3.0)), 0)
        ImageDraw.Draw(tmp).text((40, yy), tt, font=(F(S, s) if smiley else F(MM, s)), fill=255, anchor="ls")
        bb = tmp.getbbox()
        _INK[k] = ((bb[1] - yy) / float(s), (bb[3] - yy) / float(s))
    return _INK[k]

def _hit(a, b, m=8):
    return (a[0] < b[2] - m) and (b[0] < a[2] - m) and (a[1] < b[3] - m) and (b[1] < a[3] - m)

def big_box(d, x, yb, s, t, seg):
    sm = seg.get("bigfont") == "smiley"
    w = bigw(d, s, t) if sm else width(d, s, t)
    tp, bt = ink_ext(s, sm)
    return (x, yb + tp * s, x + w, yb + bt * s)

def content_boxes(d, seg):
    """代码块与表格的墨迹框（用于大字避让）"""
    out = []
    if seg.get("code"):
        cs = seg.get("codeS", 40); lh = seg.get("lh", 1.78); y = seg.get("codey", 268); x = seg.get("codex", X0)
        w = 0
        for it in seg["code"]:
            w = max(w, width(d, cs, it[0] if isinstance(it, (tuple, list)) else it))
        out.append((x, y - cs * 1.0, x + w, y + (len(seg["code"]) - 1) * cs * lh + cs * 0.42))
    if seg.get("rows"):
        rs = seg.get("rowS", 36); rlh = seg.get("rowlh", 58); ry = seg.get("rowy", 330)
        rw = 0
        for r in seg["rows"]:
            rw = max(rw, (20 + 42 + 8) * (rs * 0.5))
        out.append((X0, ry - rs * 1.0, X0 + rw, ry + (len(seg["rows"]) - 1) * rlh + rs * 0.42))
    return out

def C_text(d, p, fg, seg, dark):
    y = seg.get("codey", 268)
    if seg.get("code"):
        typing(d, seg.get("codex", X0), y, seg.get("codeS", 40), seg["code"], p, fg, DIM,
               reveal_by=seg.get("rb", 0.58), lh=seg.get("lh", 1.78), cmtcol=seg.get("cmt", 56))
    if seg.get("rows"):
        rows = seg["rows"]; lh = seg.get("rowlh", 58); s = seg.get("rowS", 36)
        n = max(1, min(len(rows), int(len(rows) * min(1.0, p / 0.55)) + 1))
        for j, (l, m, r, st) in enumerate(rows[:n]):
            col = fg if st == "fg" else (ZHU if st == "zhu" else DIM)
            line = l + " " * max(1, 20 - clen(l)) + m + " " * max(1, 42 - clen(l) - clen(m)) + r
            rich(d, X0, seg.get("rowy", 330) + j * lh, s, line[:seg.get("rowmax", 76)], col)
    if seg.get("big"):
        s = seg.get("bigS", 150); t = seg["big"]
        x = seg.get("bigx", X0); yb = seg.get("bigy", 830)
        if seg.get("bigc"):
            if seg.get("bigfont") == "smiley": x = (W - bigw(d, s, t)) / 2
            else: x = (W - width(d, s, t)) / 2
        for cb in content_boxes(d, seg):
            if _hit(big_box(d, x, yb, s, t, seg), cb):
                yb = cb[3] + abs(ink_ext(s, seg.get("bigfont") == "smiley")[0]) * s + 14
                break
        # motion is added AFTER layout, so collision resolution can never see it:
        #   entry rise (continuous, settles at p=0.20) + the breathing channel (+-1% of size)
        yb = yb + (1.0 - _entry(p)) * 26.0 - BR_DEPTH * s * _BR
        if seg.get("bigfont") == "smiley": big(d, x, yb, s, t, fg)
        else: rich2(d, x, yb, s, t, fg)

    if seg.get("cap"):
        rich(d, seg.get("capx", X0), seg.get("capy", 1002), seg.get("capS", 50), seg["cap"], DIM)
    if seg.get("seal"):
        seal(d, seg.get("sealx", 1650), seg.get("sealy", 880), seg.get("sealS", 126), seg["seal"], seg.get("sealc", ZHU))
    if seg.get("st"): status(d, footer_left(_I), "F %d / %d" % (_K, NFR))
    if seg.get("tb"): topbar(d, seg["tb"])

def wave(a, x0, x1, y0, amp, k, ph, step=14, w=2):
    a.line([(x, y0 + math.sin(x / k + ph) * amp) for x in range(x0, x1, step)], w=w)

def R_tide(im, d, p, dark, fg, seg):
    a = AA(); lvl = 0.30 + 0.62 * p
    for r in range(15):
        y = 250 + r * 52 + math.sin(p * 2.6 + r * 0.8) * (8 + 24 * ENV)
        if y < 210 + (1 - lvl) * 640: continue
        wave(a, 40, W - 20, y, 5 + r * 1.4, 120 + r * 9, p * 4 + r * 1.3, 16, 2 + (r % 2))
    a.paint(im, fg); C_text(d, p, fg, seg, dark)

def R_fog(im, d, p, dark, fg, seg):
    m = Image.new("L", (W, H), 0); dd = ImageDraw.Draw(m)
    for j in range(8):
        y = 150 + j * 128 + math.sin(p * 1.5 + j) * 26
        w = 460 + (j * 251) % 760
        x = int(-260 + ((p * 260 + j * 430) % (W + 400)))
        dd.rounded_rectangle([x - w, y, x, y + 46], radius=23, fill=20)
    tint(im, m, fg)
    for j in range(44):
        t = j / 44.0
        x = 300 + t * 1320; y = 905 - t * 430
        r = 4.5 * (1 - t * 0.72)
        d.ellipse([x - r, y - r, x + r, y + r], fill=fg if j % 2 == 0 else DIM)
    C_text(d, p, fg, seg, dark)

def R_road(im, d, p, dark, fg, seg):
    mx = mirror(seg); a = AA(); vx, vy = mx(1250), 455
    for j in range(14):
        a.line([(mx(120), 1095 - j * 62), (vx, vy)], w=2)
    for j in range(6):
        yy = vy + 42 + j * 78 - p * 26
        a.line([(mx(vx + 46 + j * 108), yy), (mx(W - 80 - j * 66), vy + 300 + j * 46)], w=2)
    for j in range(10):
        t = (j / 10.0 + p * 0.55) % 1.0
        y = vy + 34 + t * t * 640; x = mx(vx - 30 + t * 260)
        r = 2 + t * 7
        a.ell(x - r, y - r, x + r, y + r, out=255, w=2, fill=255)
    a.paint(im, fg); C_text(d, p, fg, seg, dark)

def R_mount(im, d, p, dark, fg, seg):
    mx = mirror(seg); a = AA()
    for r in range(4):
        base = 1035 - r * 62; hh = 120 + r * 96
        pts = []
        for x in range(-40, W + 60, 20):
            y = base - hh * (0.36 + 0.64 * abs(math.sin(x * 0.0021 + r * 1.9 + p * 0.5)))
            pts.append((mx(x), y))
        a.line(pts, w=3)
    for j in range(26):
        x = mx(80 + (j * 137) % 1700); y = 240 + (j * 263) % 700
        a.dash(x, y, x + 170 + (j % 4) * 60, y - 12 - (j % 3) * 18, 3, w=2, duty=0.6)
    a.paint(im, fg); C_text(d, p, fg, seg, dark)

def R_bridge(im, d, p, dark, fg, seg):
    mx = mirror(seg); a = AA()
    for r in range(11):
        wave(a, 40, W - 20, 700 + r * 30, 6 + r, 130 + r * 12, p * 3 + r * 0.9, 18, 2)
    a.line([(mx(120), 700), (mx(700), 640)], w=4)
    a.line([(mx(760), 640), (mx(880), 632)], w=4)
    a.line([(mx(W - 130), 690), (mx(960), 630)], w=4)
    bx0, bx1 = sorted((mx(700), mx(940)))
    a.arc([bx0, 470, bx1, 700], 200, 340, w=4)
    a.paint(im, fg); C_text(d, p, fg, seg, dark)

def R_lantern(im, d, p, dark, fg, seg):
    mx = mirror(seg)
    for j in range(5):
        x = mx(360 + j * 290); y = 150 + (j % 2) * 96
        sw = math.sin(p * 2.4 + j) * (7 + 10 * ENV)
        d.line([x, 100, x + sw, y], fill=DIM2, width=2)
        cx = x + sw
        d.rounded_rectangle([cx - 52, y, cx + 52, y + 132], radius=22, outline=fg, width=4)
        d.line([cx, y - 8, cx, y + 140], fill=DIM, width=2)
        for q in range(5):
            d.line([cx - 30 + q * 15, y + 132, cx - 30 + q * 15, y + 168], fill=DIM2, width=2)
    C_text(d, p, fg, seg, dark)

def R_frost(im, d, p, dark, fg, seg):
    mx = mirror(seg); a = AA(); cx, cy = mx(1280), 420
    for j in range(26):
        ang = j * 2 * math.pi / 26 + p * 1.2
        L = (120 + (j * 97) % 380) * (0.55 + 0.65 * ENV)
        a.line([(cx + math.cos(ang) * 26, cy + math.sin(ang) * 26),
                (cx + math.cos(ang) * (26 + L), cy + math.sin(ang) * (26 + L))], w=2)
        for k in range(1, 4):
            t = 0.32 + k * 0.2
            bx = cx + math.cos(ang) * (26 + L * t); by = cy + math.sin(ang) * (26 + L * t)
            a.line([(bx, by), (bx + math.cos(ang + 0.7) * 34, by + math.sin(ang + 0.7) * 34)], w=2)
            a.line([(bx, by), (bx + math.cos(ang - 0.7) * 34, by + math.sin(ang - 0.7) * 34)], w=2)
    a.ell(cx - 16, cy - 16, cx + 16, cy + 16, out=255, w=3, fill=255)
    a.paint(im, fg); C_text(d, p, fg, seg, dark)

def R_birds(im, d, p, dark, fg, seg):
    mx = mirror(seg); a = AA(); bx = mx(260 + p * 1200); by = 300 + math.sin(p * 7) * 22
    for dy in (0, 26):
        a.line([(bx - 44, by + dy), (bx, by + 20 + dy)]); a.line([(bx, by + 20 + dy), (bx + 44, by + dy - 4)])
    for j in range(9):
        t = j / 9.0; x = mx(1420 + t * 300); y = 190 + t * 190
        s = 0.34 + t * 0.3
        a.line([(x - 40 * s, y), (x, y + 12 * s)]); a.line([(x, y + 12 * s), (x + 40 * s, y)])
    a.paint(im, fg); C_text(d, p, fg, seg, dark)

def R_wind(im, d, p, dark, fg, seg):
    mx = mirror(seg)
    for j in range(22):
        y = 180 + (j * 137) % 820
        x = mx(int((40 + p * 900 + j * 210) % (W + 420)) - 210)
        L = 120 + (j * 173) % 420
        d.line([x, y, mx(mx(x) + L), y], fill=DIM if j % 3 else fg, width=2 + (j % 3))
    for j, ch in enumerate(seg.get("fly", "魂魄荡长风长")):
        x = mx(int((200 + j * 260 + p * 520) % (W + 400)) - 200)
        rich(d, x, 760 + (j % 3) * 70, 62, ch, DIM2)
    C_text(d, p, fg, seg, dark)

def R_journey(im, d, p, dark, fg, seg):
    mx = mirror(seg)
    d.line([120, 900, W - 120, 900], fill=DIM2, width=2)
    for j in range(64):
        t = j / 64.0
        x = 130 + t * (W - 260)
        on = (t < p)
        d.line([x, 900, x, 900 - (14 if j % 5 == 0 else 7)], fill=fg if on else DIM2, width=2)
    bx = mx(130 + p * (W - 260))
    d.line([bx, 856, bx - 26, 872], fill=fg, width=3); d.line([bx - 26, 872, bx + 6, 890], fill=fg, width=3)
    lines = seg.get("log", [])
    n = max(1, min(len(lines), int(len(lines) * min(1.0, p / 0.5)) + 1))
    ly = seg.get("codey", 268)
    if seg.get("code"):
        _cs = seg.get("codeS", 40)
        ly += (len(seg["code"]) - 1) * _cs * seg.get("lh", 1.78) + _cs * 0.42
    ly += 46
    for j, (t, st) in enumerate(lines[:n]):
        col = fg if st == "fg" else DIM
        rich(d, X0, ly + j * 62, 34, t, col)

    C_text(d, p, fg, seg, dark)

def R_scroll(im, d, p, dark, fg, seg):
    a = AA(); off = p * 900 * (1 if seg.get("dir", 1) > 0 else -1)
    for r in range(3):
        base = 900 - r * 90; hh = 150 + r * 120
        pts = []
        for x in range(-200, W + 200, 24):
            y = base - hh * (0.3 + 0.7 * abs(math.sin((x + off) * 0.0017 + r * 2.3)))
            pts.append((x, y))
        a.line(pts, w=3)
    for j in range(16):
        x = -180 + ((j * 210 + off) % (W + 360))
        a.line([(x, 900), (x, 840 - (j % 3) * 16)], w=3)
        a.line([(x, 840 - (j % 3) * 16), (x - 26, 812 - (j % 5) * 12)], w=2)
        a.line([(x, 840 - (j % 3) * 16), (x + 26, 806 - (j % 4) * 14)], w=2)
    a.paint(im, fg); C_text(d, p, fg, seg, dark)

def R_dawn(im, d, p, dark, fg, seg):
    a = AA(); hy = 860
    a.line([(40, hy), (W - 40, hy)], w=3)
    r = 90 + p * 150; cx, cy = 960, hy + 40 - p * 60
    a.arc([cx - r * 2, cy - r * 2 * 0.9, cx + r * 2, cy + r * 2 * 0.9], 180, 360, w=4)
    for j in range(14):
        ang = math.pi + j * math.pi / 13
        a.line([(cx + math.cos(ang) * (r * 2 + 20), cy + math.sin(ang) * (r * 1.8 + 20)),
                (cx + math.cos(ang) * (r * 2 + 90), cy + math.sin(ang) * (r * 1.8 + 90))], w=3)
    a.paint(im, fg)
    for j in range(40):
        ph = (p * 1.2 + j / 40.0) % 1.0
        x = 200 + (j * 197) % 1500; y = hy - ph * 700
        rr = 2 + (j % 3) * 1.6
        d.ellipse([x - rr, y - rr, x + rr, y + rr], fill=DIM if j % 2 else DIM2)
    C_text(d, p, fg, seg, dark)

def R_autumn(im, d, p, dark, fg, seg):
    mx = mirror(seg)
    for j in range(54):
        rng = random.Random(100 + j * 7 + seg["seed"])
        x = mx(int((rng.random() * W + p * 70 * (0.4 + rng.random())) % W))
        y = int((rng.random() * H + p * (300 + 260 * rng.random())) % H)
        s = 12 + rng.random() * 12
        d.line([x, y, x - s * 0.7, y + s * 0.5], fill=DIM2 if j % 2 else DIM, width=2)
        d.line([x, y, x + s * 0.5, y + s * 0.5], fill=DIM2 if j % 2 else DIM, width=2)
    a = AA(); r = 130
    a.ell(1420 - r, 190 - r, 1420 + r, 190 + r, out=255, w=3)
    a.paint(im, fg); C_text(d, p, fg, seg, dark)

def R_rings(im, d, p, dark, fg, seg):
    mx = mirror(seg); a = AA(); cx, cy = mx(1400), 660
    for j in range(1, 8):
        rr = 60 + j * 66 + p * 90 + 90 * ENV
        if rr > 620: continue
        a.arc([cx - rr, cy - rr, cx + rr, cy + rr], 150, 390, w=3, out=255 if j % 2 else 190)
    a.ell(cx - 20, cy - 20, cx + 20, cy + 20, out=255, w=3)
    a.paint(im, fg); C_text(d, p, fg, seg, dark)

def R_rain(im, d, p, dark, fg, seg):
    mx = mirror(seg)
    n = 40 + int(50 * ENV)
    for j in range(n):
        x = mx(60 + (j * 149) % 1800)
        y = 90 + ((j * 271) % 900 + p * (240 + 300 * ENV)) % 900
        d.line([x, y, x - 6, y + 30 + 40 * ((j * 13) % 5) / 5], fill=DIM2 if j % 3 else DIM, width=2)
    C_text(d, p, fg, seg, dark)

def R_moonbig(im, d, p, dark, fg, seg):
    mx = mirror(seg); mx0, my0, r = mx(1300), 360, 150 + p * 40
    a = AA(); a.ell(mx0 - r, my0 - r, mx0 + r, my0 + r, fill=255, out=255, w=4); a.paint(im, fg)
    a = AA(); a.ell(mx0 - r + 74, my0 - r, mx0 + r + 74, my0 + r, fill=255, out=255, w=2)
    a.paint(im, DARK if dark else LIGHT)
    a = AA()
    for j in range(15):
        ang = math.pi * 0.58 + j * 0.058
        L = (320 + 560 * (0.3 + 0.7 * ENV)) * (0.5 + ((j * 5) % 7) / 7.0)
        a.dash(mx0 + math.cos(ang) * (r + 18), my0 + math.sin(ang) * (r + 18),
               mx0 + math.cos(ang) * (r + 18 + L), my0 + math.sin(ang) * (r + 18 + L), 9, w=2, duty=0.5)
    a.paint(im, fg)
    x = X0
    for j in range(14):
        s = int(44 - j * 2.0)
        if s < 15 or x > 1500: break
        rich(d, x, 985, s, "影", DIM if j % 2 else DIM2)
        x += 76 + j * 22
    C_text(d, p, fg, seg, dark)

def R_cut2(im, d, p, dark, fg, seg):
    mx = mirror(seg); y = 645; gap = 0.62
    for i in range(44):
        t = i / 44.0
        if abs(t - gap) < 0.06: continue
        x0 = mx(X0 + t * (W - 2 * X0)); x1 = mx(X0 + t * (W - 2 * X0) + 34)
        if x0 > x1: x0, x1 = x1, x0
        d.line([x0, y, x1, y], fill=fg, width=3)
    a = AA(); gx0 = mx(X0 + gap * (W - 2 * X0))
    for j in range(9):
        ang = j * 2 * math.pi / 9 + p * 5
        rr = 24 + 40 * ((j * 3) % 4) / 3
        a.line([(gx0 + math.cos(ang) * 12, y + math.sin(ang) * 12), (gx0 + math.cos(ang) * rr, y + math.sin(ang) * rr)], w=3)
    a.paint(im, ZHU)
    C_text(d, p, fg, seg, dark)

REND.update(dict(tide=R_tide, fog=R_fog, road=R_road, mount=R_mount, bridge=R_bridge, lantern=R_lantern,
                 frost=R_frost, birds=R_birds, wind=R_wind, journey=R_journey, scroll=R_scroll,
                 dawn=R_dawn, autumn=R_autumn, rings=R_rings, rain=R_rain, moonbig=R_moonbig, cut2=R_cut2))

# ================= 全曲分镜表（43 段） =================
SEG = []
def add(t0, t1, s, dark, **kw):
    d = dict(t=(t0, t1), s=s, dark=dark, seed=(len(SEG) * 37 + 11) % 997)
    d.update(kw); SEG.append(d)

BK = ["grad", "mottle", "grid", "ruler", "frame", "ink"]
BKG = ["grad", "mottle", "grid", "ruler", "frame", "ghost"]

add(17.934, 27.263, "L1", True, back=BKG, ghost="谣", ink="shan", dust=26)
add(27.263, 36.019, "L2", False, back=BK, ink="bo", dust=18)
add(36.019, 43.237, "L3", True, back=BKG, ghost="月", ink="yun", dust=22)
add(43.237, 52.583, "L4", False, back=BK, ink="yun", dust=16)
add(52.583, 61.254, "L5", True, back=BK, ink="shan", dust=20)
add(61.254, 69.981, "L6", False, back=BK, ink="bo", dust=16)
add(69.981, 73.806, "L7", True, back=BKG, ghost="谣", ink="yun", dust=30)
add(73.806, 78.173, "L8", False, back=BK, ink="yu", dust=26)
add(78.173, 81.748, "L9", True, back=BK, ink="bo", dust=18)
add(81.748, 87.503, "L10", False, back=BK, ink="shan", dust=18)

add(87.503, 91.903, "tide", True, back=BK, ink="bo", dust=24,
    code=[("// 卷三 · 潮", "dim"), ("while (潮.滔滔) {", "fg"), ("  岸.退(一步);", "fg"), ("}", "fg"),
          ("if (潮 > 心) 淹没(我);", "zhu")],
    big="潮水滔滔", bigS=150, bigy=850, st="玄翎谣 · 潮水滔滔", tm="01:27.503", tb="卷三 · 潮")
add(91.903, 96.179, "fog", False, back=BK, ink="yun", dust=20,
    code=[("雾 = 遮(道);", "fg"), ("能见度 = 0;", "fg"), ("// 只看得到脚下三寸", "dim")],
    big="迷雾遮道", bigS=140, bigfont="smiley", bigc=True, bigy=880, st="玄翎谣 · 迷雾遮道", tm="01:31.903")
add(96.179, 100.629, "road", True, back=BK, ink="shan", dust=22,
    code=[("while (路.迢迢) 走();", "fg"), ("里程 += 一步;", "fg"), ("目的地 = undefined;", "dim")],
    big="前路迢迢", bigS=150, bigy=850, st="玄翎谣 · 前路迢迢", tm="01:36.179")
add(100.629, 104.925, "journey", False, back=BK, ink="yun", dust=18,
    code=[("const 归期 = new Date(Infinity);", "fg")],
    rows=[("归期", "遥遥", "// NaN", "dim"), ("问山", "山不语", "", "fg"), ("问水", "水长流", "", "fg"),
          ("问星", "星已落", "", "fg"), ("问人", "人未归", "", "zhu")],
    log=[("// 查询中 ...", "dim")],
    big="归期遥遥", bigS=130, bigfont="smiley", bigc=True, bigy=1000, rowy=400, st="玄翎谣 · 归期遥遥", tm="01:40.629")
add(104.925, 109.270, "mount", True, back=BK, ink="shan", dust=26,
    code=[("for (山 of 荒山) {", "fg"), ("  风.萧萧(山);", "fg"), ("}", "fg"), ("// 无人的地方才有风", "dim")],
    big="荒山萧萧", bigS=140, bigy=340, bigx=1100, st="玄翎谣 · 荒山萧萧", tm="01:44.925")
add(109.270, 113.587, "bridge", False, back=BK, ink="bo", dust=18,
    code=[("if (!河.有梁) 桥.缺席();", "fg"), ("过河 = 未知;", "fg"), ("// 河无梁，人无渡", "dim")],
    big="河无梁", bigS=150, bigfont="smiley", bigc=True, bigy=430, st="玄翎谣 · 河无梁", tm="01:49.270")
add(113.587, 117.973, "lantern", True, back=BK, ink="shan", dust=24,
    code=[("try { 家酒.尝(); }", "fg"), ("catch (e) { 泪.落(); }", "zhu"), ("// 家酒难尝", "dim")],
    big="家酒难尝", bigS=140, bigy=880, st="玄翎谣 · 家酒难尝", tm="01:53.587")
add(117.973, 122.357, "frost", False, back=BK, ink="yu", dust=20,
    code=[("发.染('雪霜');", "fg"), ("// 时间是最好的染匠", "dim")],
    big="发染雪霜", bigS=140, bigfont="smiley", bigc=True, bigy=980, st="玄翎谣 · 发染雪霜", tm="01:57.973")
add(122.357, 130.699, "birds", True, back=BKG, ghost="翎", ink="yun", dust=30,
    code=[("翎鸟.唤({ 望: false, 忘: false });", "fg"), ("// 勿望，勿忘", "dim")],
    big="勿望 勿忘", bigS=180, bigy=760, bigx=1000, st="玄翎谣 · 唤翎鸟", tm="02:02.357")
add(130.699, 134.099, "wind", False, back=BK, ink="yun", dust=24, fly="魂魄荡长风长",
    code=[("魂魄.荡(长风.length);", "fg"), ("长风.长 = Infinity;", "fg")],
    big="长风长", bigS=200, bigfont="smiley", bigy=400, st="玄翎谣 · 长风长", tm="02:10.699")

add(134.099, 142.0, "autumn", True, back=BKG, ghost="秋", ink="shan", dust=34,
    code=[("await 秋夜凉;", "fg"), ("return 故乡;", "fg"), ("// 待到秋夜凉，送我回故乡", "dim")],
    big="秋夜凉", bigS=190, bigy=880, st="玄翎谣 · 待到秋夜凉", tm="02:14.099", tr="roll")
add(142.0, 150.5, "journey", False, back=BK, ink="yun", dust=20,
    code=[("route.add(故乡);", "fg")],
    log=[("// 归途 · 剩余 872 km", "dim"), ("[#####---------] 32%", "fg"), ("[##########----] 61%", "fg"), ("[##############] 92%", "fg")],
    big="归途", bigS=150, bigfont="smiley", bigc=True, bigy=1000, st="间奏 · 归途", tm="02:22.000", tr="dissolve")
add(150.5, 159.0, "scroll", True, back=BK, ink="shan", dust=26,
    code=[("canvas.scroll(-2px);", "fg"), ("// 千里江山，一卷未尽", "dim")],
    st="间奏 · 长卷", tm="02:30.500", tr="dissolve")
add(159.0, 167.173, "dawn", False, back=BK, ink="yun", dust=40, dustdir="up",
    code=[("while (夜) 等(破晓);", "fg"), ("// 天就要亮了", "dim")],
    big="破晓", bigS=200, bigfont="smiley", bigc=True, bigy=760, st="间奏 · 破晓", tm="02:39.000", tr="flash")

add(167.173, 174.925, "cut2", True, back=BK, ink="shan", dust=30,
    code=[("玄翎.飞();        // 断肠", "fg"), ("throw new 断肠Error('太远');", "zhu"), ("玄翎.飞();", "fg")],
    big="飞断肠", bigS=190, bigy=880, st="玄翎谣 · 卷二", tm="02:47.173")
add(174.925, 183.549, "L6", False, back=BK, ink="bo", dust=16)
add(183.549, 187.654, "L7", True, back=BKG, ghost="谣", ink="yun", dust=30)
add(187.654, 191.646, "L8", False, back=BK, ink="yu", dust=26)
add(191.646, 195.275, "rings", True, back=BK, ink="bo", dust=20,
    code=[("传(四方);", "fg"), ("传(四方);   // 第二遍", "dim"), ("传(四方);", "dim"), ("传(四方);", "dim")],
    big="四方", bigS=180, bigy=1010, bigx=1050, st="玄翎谣 · 传四方", tm="03:11.646")
add(195.275, 200.867, "road", False, back=BK, ink="shan", dust=20, mirror=True,
    code=[("return 阿爷 && 阿娘;", "fg"), ("// 千万莫相望", "dim")],
    big="千万莫相望", bigS=130, bigfont="smiley", bigc=True, bigy=1010, st="玄翎谣 · 唤阿爷阿娘", tm="03:15.275")
add(200.867, 205.355, "tide", True, back=BK, ink="bo", dust=24, mirror=True,
    code=[("while (潮.滔滔) 岸.退();", "fg"), ("// 又一遍", "dim")],
    big="潮水滔滔", bigS=150, bigy=850, st="玄翎谣 · 潮水滔滔", tm="03:20.867")
add(205.355, 209.549, "fog", False, back=BK, ink="yun", dust=20, mirror=True,
    code=[("雾.更浓();", "fg"), ("能见度 = 0;", "fg")],
    big="迷雾遮道", bigS=140, bigfont="smiley", bigc=True, bigy=880, st="玄翎谣 · 迷雾遮道", tm="03:25.355")
add(209.549, 213.747, "road", True, back=BK, ink="shan", dust=22, mirror=True,
    code=[("while (路.迢迢) 走();", "fg"), ("// 一步一步", "dim")],
    big="前路迢迢", bigS=150, bigy=850, st="玄翎谣 · 前路迢迢", tm="03:29.549")
add(213.747, 218.269, "journey", False, back=BK, ink="yun", dust=18, mirror=True,
    code=[("归期.until();  // 仍是 NaN", "fg")],
    rows=[("问山", "山不语", "", "fg"), ("问水", "水长流", "", "fg"), ("问星", "星已落", "", "fg"),
          ("问人", "人未归", "", "zhu"), ("问己", "己白头", "", "zhu")],
    big="归期遥遥", bigS=130, bigfont="smiley", bigc=True, bigy=1000, rowy=400, st="玄翎谣 · 归期遥遥", tm="03:33.747")
add(218.269, 222.693, "mount", True, back=BK, ink="shan", dust=26, mirror=True,
    code=[("风.萧萧(荒山);", "fg"), ("// 山还是那座山", "dim")],
    big="荒山萧萧", bigS=140, bigy=340, bigx=380, st="玄翎谣 · 荒山萧萧", tm="03:38.269")
add(222.693, 226.883, "bridge", False, back=BK, ink="bo", dust=18, mirror=True,
    code=[("桥.架(河);", "fg"), ("// 河无梁，桥自造", "dim")],
    big="河无梁", bigS=150, bigfont="smiley", bigc=True, bigy=430, st="玄翎谣 · 河无梁", tm="03:42.693")
add(226.883, 231.205, "lantern", True, back=BK, ink="shan", dust=24, mirror=True,
    code=[("家酒 = null;", "fg"), ("// 家酒难尝", "dim")],
    big="家酒难尝", bigS=140, bigy=880, st="玄翎谣 · 家酒难尝", tm="03:46.883")
add(231.205, 235.877, "frost", False, back=BK, ink="yu", dust=20, mirror=True,
    code=[("发.染('雪霜');  // 又深了一层", "fg")],
    big="发染雪霜", bigS=140, bigfont="smiley", bigc=True, bigy=980, st="玄翎谣 · 发染雪霜", tm="03:51.205")
add(235.877, 244.941, "birds", True, back=BKG, ghost="唤", ink="yun", dust=30, mirror=True,
    code=[("翎鸟.唤({ 望: false, 忘: false });", "fg"), ("// 勿望，勿忘", "dim")],
    big="勿望 勿忘", bigS=180, bigy=760, bigx=420, st="玄翎谣 · 唤翎鸟", tm="03:55.877")
add(244.941, 247.621, "wind", False, back=BK, ink="yun", dust=24, fly="魂魄长风",
    code=[("长风.长 = Infinity;", "fg")],
    big="长风长", bigS=200, bigfont="smiley", bigy=400, st="玄翎谣 · 长风长", tm="04:04.941")
add(247.621, 255.645, "autumn", True, back=BKG, ghost="归", ink="shan", dust=34,
    code=[("await 秋夜凉;", "fg"), ("return 故乡;", "fg")],
    big="回故乡", bigS=200, bigy=880, st="玄翎谣 · 送我回故乡", tm="04:07.621")
add(255.645, 262.101, "cut2", False, back=BK, ink="shan", dust=28, mirror=True,
    code=[("玄翎.飞();  // 尾声", "fg")],
    big="玄翎飞", bigS=170, bigfont="smiley", bigc=True, bigy=880, st="玄翎谣 · 尾声", tm="04:15.645")
add(262.101, 278.976, "outro", True, back=BKG, ghost="谣", ink="shan", dust=34,
    code=[("return 玄翎谣;", "fg"), ("// 全文终", "dim")],
    big="天苍苍，地莽莽", bigS=150, bigy=830, st="玄翎谣 · 终", tm="04:22.101", tr="flash")

_TRC = ["wipe", "roll", "blinds", "slice", "dissolve", "wipe", "flash", "roll", "blinds", "slice", "dissolve", "roll"]
for _k, _s in enumerate(SEG):
    _s.setdefault("tr", "cut" if _k == len(SEG) - 1 else _TRC[_k % len(_TRC)])
    _s.setdefault("trd", 0.42 if (_s["t"][1] - _s["t"][0]) < 5.2 else 0.5)
for _k, _t in {9: "flash", 19: "dissolve", 20: "roll", 21: "dissolve", 22: "flash", 23: "flash",
               29: "flash", 40: "dissolve", 41: "roll"}.items():
    SEG[_k]["tr"] = _t

# ---------------- 页脚契约：派生，不逐页手写 ----------------
# 歌词页：`LINE nn/NN · SLUG · LRC mm:ss.mmm`（nn = 官方 LRC 的行号；副歌 II 复用同一行号，
#   正如真实项目里第 19 句跨两页都印 `LINE 19/33`）。
# 卡片页：`SLUG · ROLE`。
# 判定：`st` 以「间奏」开头的页是卡片页（角色取其后半段），其余带大字的页是歌词页，
#   行号按「行名首次出现」编号。本参考片用自己那 10 句行名代替官方行号；真实项目请换成
#   官方 LRC 的行号并跑 assets/lrc_check_example.py（手打的 "/31" 就是这么漂移的）。
#   同一个渲染器名（slug）可能出现在两行：副歌 II 是同一句、沿用同一号，而 `cut2` 的
#   「卷二 / 尾声」是两句、各占一个号 —— 这正是「页 ≠ 行」的样子。
def _st_parts(s):
    st = s.get("st", "")
    nm = st.split("·")[-1].strip() if "·" in st else st.strip()
    return st, nm


LYR_NUM, _order = {}, []
for _i, _s in enumerate(SEG):
    _st, _nm = _st_parts(_s)
    if _s.get("big") and not _st.startswith("间奏") and _nm not in ("", "终"):
        if _nm not in _order: _order.append(_nm)
        LYR_NUM[_i] = _order.index(_nm) + 1
NLIN = len(_order)
ROLE = {_i: _st_parts(_s)[1] for _i, _s in enumerate(SEG) if _st_parts(_s)[0].startswith("间奏")}
STAMP = {_i: _s.get("tm", "--:--.---") for _i, _s in enumerate(SEG)}


def footer_left(i):
    """Left footer field, always derived. A card never restates a neighbouring lyric."""
    if i < 0: return "INSTRUMENTAL"
    s = SEG[i]
    if i in LYR_NUM:
        return "LINE %02d/%02d · %s · LRC %s" % (LYR_NUM[i], NLIN, s["s"].upper(),
                                                 STAMP.get(i, "--:--.---"))
    return "%s · %s" % (s["s"].upper(), ROLE.get(i, "INSTRUMENTAL"))


SHOTS = [s["t"] for s in SEG]

def R_outro(im, d, p, dark, fg, seg):
    R_autumn(im, d, p, dark, fg, dict(seg, s="autumn"))
    if p > 0.34:
        q = (p - 0.34) / 0.66
        c = DARK if dark else LIGHT
        im.paste(Image.new("RGB", (W, H), c), mask=Image.new("L", (W, H), int(255 * min(1.0, q * 6.0))))
        if q > 0.18:
            a = min(1.0, (q - 0.18) / 0.30) * min(1.0, max(0.0, (1.0 - p) / 0.06))
            lay = Image.new("RGBA", (W, H), (0, 0, 0, 0)); ld = ImageDraw.Draw(lay)
            rich2(ld, (W - width(d, 96, "玄翎谣")) / 2, 560, 96, "玄翎谣", fg)
            rich(ld, (W - width(d, 40, "鸣潮 · 秧秧 · 玄翎 主题曲")) / 2, 660, 40, "鸣潮 · 秧秧 · 玄翎 主题曲", DIM)
            seal(ld, 880, 720, 150, "玄翎谣", ZHU)
            im.paste(lay.convert("RGB"), (0, 0), lay.split()[3].point(lambda v: int(v * a)))

REND["outro"] = R_outro

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "preview"
    if mode == "preview":
        ps = [float(x) for x in (sys.argv[2].split(",") if len(sys.argv) > 2 else ["0.85"])]
        idx = [int(x) for x in sys.argv[3].split(",")] if len(sys.argv) > 3 else list(range(len(SEG)))
        os.makedirs(BASE + "/preview", exist_ok=True)
        for i in idx:
            for p in ps:
                try:
                    frame(i, p).save(BASE + "/preview/g%02d_p%02d.png" % (i, int(p * 100)))
                    print("seg %d p=%.2f ok" % (i, p), flush=True)
                except Exception as e:
                    print("seg %d p=%.2f FAIL %r" % (i, p, e), flush=True); traceback.print_exc()
    elif mode == "clip":
        t0, t1 = float(sys.argv[2]), float(sys.argv[3])
        os.makedirs(CLIP, exist_ok=True)
        n = int((t1 - t0) * FPS); n0 = max(0, int((t0 - T0) * FPS))
        for k in range(n):
            t = t0 + k / float(FPS)
            frame_t(t, k=n0 + k).save(CLIP + "/f%05d.png" % k)
            if k % 60 == 0: print("clip %d/%d t=%.2f" % (k, n, t), flush=True)
        print("CLIP DONE", n)
    elif mode == "audit":
        bad = 0
        print("idx   t0      t1      polarity  transition  footer")
        for i, s in enumerate(SEG):
            a, b = s["t"]
            left = footer_left(i) if s.get("st") else "(no footer)"
            note = []
            if i:
                pv = SEG[i - 1]
                if s.get("big") and s["big"] == pv.get("big"):
                    note.append("!! same big line as previous page"); bad += 1
                if s["dark"] != pv["dark"] and s.get("tr") == "flash":
                    note.append("-- flash across a polarity flip (prefer dissolve)")
                if not s.get("big"):
                    cap = s.get("cap", "")
                    for q in (pv.get("big"), pv.get("cap")):
                        if cap and q and (cap in q or q in cap):
                            note.append("!! card echoes neighbouring lyric"); bad += 1
            if s.get("big") and not s.get("st"):
                note.append("-- big line without a footer (add st= or a footer table)")
            if s["s"] in LEG and not s.get("big"):
                note.append("-- legacy shot page: no entry, no breathing (port it to a R_* renderer)")
            print("%3d  %7.3f %7.3f %-8s  %-10s  %-46s %s"
                  % (i, a, b, "dark" if s["dark"] else "light", s.get("tr", "?"), left,
                     " ".join(note)))
        print("segments %d  lyric lines %d  cards %d  problems %d"
              % (len(SEG), NLIN, len(ROLE), bad))
    elif mode == "plan":
        nw = int(sys.argv[2]) if len(sys.argv) > 2 else 8
        sub = int(sys.argv[3]) if len(sys.argv) > 3 else 224
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        try:
            import chunk_manifest
        except ImportError:
            print("copy assets/chunk_manifest.py next to this file: it defines the only legal partition")
            raise SystemExit(2)
        ch = chunk_manifest.canonical(NFR, nw=nw, sub=sub)
        print("NFR %d -> %d chunks (workers=%d, sub=%d)" % (NFR, len(ch), nw, sub))
        for a, b in ch:
            print("  %5d-%5d  %4d frames" % (a, b, b - a))
        print("driver: chunk_manifest.write(out_dir, NFR, nw=%d, sub=%d, prefix='film') then mux from it"
              % (nw, sub))
    else:
        k0 = int(sys.argv[2]) if len(sys.argv) > 2 else 0
        k1 = int(sys.argv[3]) if len(sys.argv) > 3 else NFR
        os.makedirs(OUT2, exist_ok=True)
        for k in range(k0, k1):
            t = T0 + k / float(FPS)
            frame_t(t, k=k).save(OUT2 + "/f%05d.png" % k)
            if k % 120 == 0: print("frame %d/%d t=%.2f" % (k, NFR, t), flush=True)
        print("DONE", k0, k1)
