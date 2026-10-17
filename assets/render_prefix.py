# -*- coding: utf-8 -*-
# TEMPLATE: copy next to your project and re-point BASE / T0 / T1 / font paths.
# This is the reference project as shipped.
# Re-point BASE at your project dir, or set the LYRIC_VIDEO_BASE env var.
import sys, os, math, traceback
from PIL import Image, ImageDraw, ImageFont

BASE = os.environ.get("LYRIC_VIDEO_BASE", "<project dir>")
K = BASE + "/fonts/LXGWWenKaiGB-Regular.ttf"
M = BASE + "/fonts/LXGWWenKaiMonoGB-Regular.ttf"    # 霞鹜文楷等宽 GB（真 2:1）
MM = BASE + "/fonts/LXGWWenKaiMonoGB-Medium.ttf"   # 等宽 Medium，用于大字与加重
S = BASE + "/fonts/SmileySans-Oblique.ttf"
W, H = 1920, 1080
DARK = (10, 10, 10); LIGHT = (247, 247, 243)
DIM = (126, 126, 124); DIM2 = (92, 92, 90)
ZHU = (176, 48, 40)      # 朱砂
TENG = (204, 158, 66)    # 藤黄
FPS = 30
T0, T1 = 17.934, 87.503
BLINK = True
ENV = 0.4
FNW = int((T1 - T0) * FPS)
try:
    import json as _json
    ENVS = _json.load(open(BASE + "/env.json"))
except Exception:
    ENVS = [0.4] * FNW
SHOTS = [(17.934,27.263),(27.263,36.019),(36.019,43.237),(43.237,52.583),(52.583,61.254),
         (61.254,69.981),(69.981,73.806),(73.806,78.173),(78.173,81.748),(81.748,87.503)]
LYR = ["玄翎飞，飞过江","水泱泱，山茫茫","明月光，月光照着影子长","海内兮传四方，唤伊莫相忘",
       "玄翎飞，飞断肠","天苍苍，地莽莽","明月光（千里长，亦往）","悠悠夜凉（湿衣裳，磨刀枪）",
       "海内兮传四方","唤阿爹阿娘 千万莫相望"]

_f = {}
def F(path, size):
    k = (path, size)
    if k not in _f: _f[k] = ImageFont.truetype(path, size)
    return _f[k]
def cjk(ch):
    o = ord(ch)
    return 0x2E80 <= o <= 0x9FFF or 0xF900 <= o <= 0xFAFF or 0xFE30 <= o <= 0xFE4F or 0xFF00 <= o <= 0xFFEF or 0x3000 <= o <= 0x303F
def runs(t):
    out = []
    for ch in t:
        k = "c" if cjk(ch) else "l"
        if out and out[-1][0] == k: out[-1][1] += ch
        else: out.append([k, ch])
    return out
def fnt(k, s):
    return F(M, s)                       # 等宽字体：汉字 1.0em / 拉丁 0.5em = 严格 2:1
def width(d, s, t):
    w = 0.0
    for k, seg in runs(t): w += d.textlength(seg, font=fnt(k, s))
    return w
def rich(d, x, by, s, t, fill, reveal=None):
    if reveal is not None: t = t[:max(0, int(reveal))]
    for k, seg in runs(t):
        f = fnt(k, s); d.text((x, by), seg, font=f, fill=fill, anchor="ls")
        x += d.textlength(seg, font=f)
    return x
def rich2(d, x, by, s, t, fill, path=None):
    f = F(path or MM, s); d.text((x, by), t, font=f, fill=fill, anchor="ls")
    return x + d.textlength(t, font=f)
def rrich(d, xr, by, s, t, fill, reveal=None):
    rich(d, xr - width(d, s, t[:max(0,int(reveal))] if reveal is not None else t), by, s, t, fill, reveal)
def big(d, x, by, s, t, fill, stroke=0, stroke_fill=None):
    d.text((x, by), t, font=F(S, s), fill=fill, anchor="ls",
           stroke_width=stroke, stroke_fill=stroke_fill or fill)
def bigw(d, s, t): return d.textlength(t, font=F(S, s))
def cursor(d, x, by, s, fill):
    d.rectangle([x, by - 0.72 * s, x + 0.5 * s, by + 0.08 * s], fill=fill)
def typing(d, x, y0, s, lines, p, fg, dim, reveal_by=0.55, lh=1.75):
    total = sum(len(t) for t, c in lines)
    done = int(total * min(1.0, p / reveal_by))
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
def dashes(d, x1, y1, x2, y2, n, fill, w=2, duty=0.55):
    for i in range(n):
        a = i / n; b = a + duty / n
        d.line([x1 + (x2 - x1) * a, y1 + (y2 - y1) * a, x1 + (x2 - x1) * b, y1 + (y2 - y1) * b], fill=fill, width=w)
def seal(d, cx, cy, size, chars, color=ZHU):
    d.rounded_rectangle([cx, cy, cx + size, cy + size], radius=size * 0.09, outline=color, width=max(3, size // 26))
    n = len(chars); s = int(size * 0.86 / n) if n > 1 else int(size * 0.5)
    fs = F(MM, s); ws = [d.textlength(c, font=fs) for c in chars]; tot = sum(ws)
    x = cx + (size - tot) / 2
    for c in chars:
        w = d.textlength(c, font=fs); d.text((x, cy + size * 0.5 + s * 0.36), c, font=fs, fill=color, anchor="lm"); x += w
def status(d, left, right, y=1024, s=30, col=DIM2):
    rich(d, 150, y, s, left, col)
    rich(d, W - 150 - width(d, s, right), y, s, right, col)
def topbar(d, t, col=DIM2, s=30):
    rich(d, 150, 96, s, t, col)

class AA:
    """2x supersampled line art.

    Every primitive records its own bounding box, and paint() downsamples ONLY that box.
    Cost is driven by the NUMBER of paint() calls, not by the area they cover: a full
    1920x1080 LANCZOS costs ~26 ms, a 1920x4 strip still costs ~35 ms of fixed overhead,
    while three lines in a corner cost ~1 ms once cropped. So use ONE AA() per colour,
    merge every same-colour primitive into it, and paint once.
    """
    BB_PAD = 2      # px of slack so the LANCZOS kernel never misses ink at the crop edge

    def __init__(self):
        self.m = Image.new("L", (W * 2, H * 2), 0); self.d = ImageDraw.Draw(self.m)
        self._bb = None
    def _mark(self, x0, y0, x1, y1):
        b = self._bb
        if b is None:
            self._bb = [x0, y0, x1, y1]; return
        if x0 < b[0]: b[0] = x0
        if y0 < b[1]: b[1] = y0
        if x1 > b[2]: b[2] = x1
        if y1 > b[3]: b[3] = y1
    def line(self, pts, fill=255, w=2):
        self.d.line([(x * 2, y * 2) for x, y in pts], fill=fill, width=max(1, int(w * 2)), joint="curve")
        k = w * 0.5 + 1.5
        self._mark(min(p[0] for p in pts) - k, min(p[1] for p in pts) - k,
                   max(p[0] for p in pts) + k, max(p[1] for p in pts) + k)
    def dash(self, x1, y1, x2, y2, n, w=2, duty=0.55):
        for i in range(n):
            a = i / n; b = a + duty / n
            self.line([(x1 + (x2 - x1) * a, y1 + (y2 - y1) * a), (x1 + (x2 - x1) * b, y1 + (y2 - y1) * b)], w=w)
    def ell(self, x0, y0, x1, y1, out=255, w=2, fill=None):
        self.d.ellipse([x0 * 2, y0 * 2, x1 * 2, y1 * 2], outline=out, width=max(1, int(w * 2)), fill=fill)
        k = w * 0.5 + 1.0
        self._mark(min(x0, x1) - k, min(y0, y1) - k, max(x0, x1) + k, max(y0, y1) + k)
    def arc(self, box, a, b, out=255, w=2):
        self.d.arc([box[0] * 2, box[1] * 2, box[2] * 2, box[3] * 2], a, b, fill=out, width=max(1, int(w * 2)))
        k = w * 0.5 + 1.0
        self._mark(min(box[0], box[2]) - k, min(box[1], box[3]) - k,
                   max(box[0], box[2]) + k, max(box[1], box[3]) + k)
    def poly(self, pts, out=255, w=2):
        self.d.polygon([(x * 2, y * 2) for x, y in pts], outline=out, width=max(1, int(w * 2)))
        k = w * 0.5 + 1.5
        self._mark(min(p[0] for p in pts) - k, min(p[1] for p in pts) - k,
                   max(p[0] for p in pts) + k, max(p[1] for p in pts) + k)
    def paint(self, im, color, region=None):
        """Paste the mask. With region=None (the normal case) only the ink's own bounding
        box is downsampled; pass region=(x0, y0, x1, y1) to force a larger crop."""
        box = region if region is not None else self._bb
        if box is None:
            return                       # nothing was drawn -- nothing to paste
        x0 = max(0, int(box[0]) - self.BB_PAD); y0 = max(0, int(box[1]) - self.BB_PAD)
        x1 = min(W, int(box[2]) + 1 + self.BB_PAD); y1 = min(H, int(box[3]) + 1 + self.BB_PAD)
        if x1 - x0 < 2 or y1 - y0 < 2:
            return
        sub = self.m.crop((x0 * 2, y0 * 2, x1 * 2, y1 * 2)).resize((x1 - x0, y1 - y0), Image.LANCZOS)
        im.paste(color, (x0, y0), sub)

def base(i):
    dark = (i % 2) == 0
    bg = DARK if dark else LIGHT
    fg = LIGHT if dark else DARK
    return Image.new("RGB", (W, H), bg), dark, bg, fg

# ---------------- 1 玄翎飞，飞过江 (暗) ----------------
def shot1(im, d, p, dark, fg):
    code = [("// 玄翎谣 · 卷一 · 羽", "dim"), ("const 玄翎 = 羽.飞('过江');", "fg"),
            ("玄翎.trace = [水, 山, 明月];", "fg"), ("if (江.渡(玄翎)) 歌.起();", "fg"),
            ("return 玄翎;", "fg")]
    typing(d, 150, 300, 42, code, p, fg, DIM)
    rich(d, 150, 152, 30, "云中君@玄翎:~$ ./玄翎谣 --start", DIM2, reveal=len("云中君@玄翎:~$ ./玄翎谣 --start") * min(1, p / 0.25))
    a = AA(); bx = -120 + p * (W + 260); by = 210 + math.sin(p * 9) * 26
    a.line([(bx - 34, by), (bx, by + 20)]); a.line([(bx, by + 20), (bx + 34, by - 6)]); a.paint(im, fg)
    for j in range(1, 9):
        tx = bx - 60 - j * 34 - p * 60 * j * 0.12
        d.ellipse([tx - 2, by + 4 - j, tx + 2, by + 8 - j], fill=DIM2)
    status(d, "玄翎谣 · 卷一 · 第 1 句", "00:17.934")
    seal(d, W - 260, 878, 116, "玄翎")
    d.line([1795, 250, 1795, 760], fill=DIM2, width=2)
    for j, ch in enumerate("玄翎谣"):
        rich(d, 1822, 330 + j * 100, 46, ch, DIM)

# ---------------- 2 水泱泱，山茫茫 (亮) ----------------
def shot2(im, d, p, dark, fg):
    a = AA()
    for r in range(3):
        pts = [(x, 730 + r * 46 + math.sin(x / 150.0 + p * 6 + r) * (16 - r * 4)) for x in range(120, 1801, 12)]
        a.line(pts, w=3)
    a.paint(im, fg)
    a = AA()
    for j, (cx, sc, ph) in enumerate([(380, 1.0, 0.0), (1500, 0.8, 1.7), (1180, 0.55, 3.1)]):
        h = 130 * sc * (0.6 + 0.4 * math.sin(p * 4 + ph))
        a.poly([(cx - 190 * sc, 700), (cx, 700 - h - 60 * sc), (cx + 190 * sc, 700)], w=3)
    a.paint(im, fg)
    code = [("while (水.泱泱) {", "fg"), ("  山.茫茫(方位 => 望(方位));", "fg"), ("}", "fg")]
    typing(d, 150, 250, 40, code, p, fg, DIM, reveal_by=0.7)
    s = 150
    t = "水泱泱，山茫茫"
    big(d, (W - bigw(d, s, t)) / 2, 1000, s, t, fg)
    topbar(d, "水泱泱，山茫茫 ── 卷二", DIM2)
    status(d, "玄翎谣 · 第 2 句", "00:27.263")

# ---------------- 3 明月光，月光照着影子长 (暗) ----------------
def shot3(im, d, p, dark, fg):
    mx, my, r = 1470, 340, 132
    a = AA(); a.ell(mx - r, my - r, mx + r, my + r, fill=255, out=255, w=4); a.paint(im, fg)
    a = AA(); a.ell(mx - r + 66, my - r, mx + r + 66, my + r, fill=255, out=255, w=2)
    a.paint(im, (DARK if dark else LIGHT))
    a = AA()
    for j in range(13):
        ang = math.pi * 0.62 + j * 0.052
        L = (300 + 520 * (0.25 + 0.75 * ENV)) * (0.5 + ((j * 5) % 7) / 7.0)
        x1 = mx + math.cos(ang) * (r + 16); y1 = my + math.sin(ang) * (r + 16)
        a.dash(x1, y1, x1 + math.cos(ang) * L, y1 + math.sin(ang) * L, 9, w=2, duty=0.5)
    a.paint(im, fg)
    x = 170
    for j in range(16):
        s = int(46 - j * 2.2)
        if s < 15 or x > 1650: break
        rich(d, x, 940, s, "影", DIM if j % 2 else DIM2)
        x += 74 + j * 20
    code = [("const 月光 = new 光('明月');", "fg"), ("const 影 = 月光.照(我);", "fg"), ("影.length; // 很长", "fg"),
            ("月光.照(故乡) == 月光.照(我);", "fg")]
    typing(d, 150, 300, 42, code, p, fg, DIM)
    rich2(d, 150, 700, 120, "明月光", fg)
    status(d, "玄翎谣 · 第 3 句", "00:36.019")

# ---------------- 4 海内兮传四方，唤伊莫相忘 (亮) ----------------
def shot4(im, d, p, dark, fg):
    a = AA(); cx, cy = 560, 560
    for j in range(1, 9):
        rr = 90 + j * 78 + math.sin(p * 3.3 - j * 0.5) * 14
        a.arc([cx - rr, cy - rr, cx + rr, cy + rr], -70, 70, w=3)
    a.ell(cx - 22, cy - 22, cx + 22, cy + 22, w=4); a.paint(im, fg)
    code = [("broadcast('唤伊', { 至: '四方' });", "fg"), ("// 回执 · 海内存知己", "dim"), ("cache.set('伊', { 忘: false });", "fg")]
    typing(d, 980, 300, 40, code, p, fg, DIM, reveal_by=0.7)
    s = 130; t = "唤伊莫相忘"
    big(d, 980, 760, s, t, fg)
    seal(d, 980, 900, 120, "莫相忘")
    status(d, "玄翎谣 · 第 4 句", "00:43.237")

# ---------------- 5 玄翎飞，飞断肠 (暗) ----------------
def shot5(im, d, p, dark, fg):
    y = 620; seg = 34; gap_at = 0.62
    for i in range(46):
        t = i / 46.0
        if abs(t - gap_at) < 0.055: continue
        x = 150 + t * 1620
        d.line([x, y, x + seg, y], fill=fg, width=3)
    a = AA()
    for j in range(9):
        ang = j * 2 * math.pi / 9 + p * 5
        rr = 26 + 40 * ((j * 3) % 4) / 3
        gx = 150 + gap_at * 1620; a.line([(gx + math.cos(ang) * 12, y + math.sin(ang) * 12),
                                          (gx + math.cos(ang) * rr, y + math.sin(ang) * rr)], w=3)
    a.paint(im, ZHU)
    code = [("玄翎.飞();", "fg"), ("// 飞 → 断", "dim"), ("throw new 断肠Error('太远');", "zhu"), ("玄翎.飞();", "fg")]
    typing(d, 150, 250, 42, code, p, fg, DIM)
    rich2(d, 150, 900, 130, "飞断肠", fg)
    status(d, "玄翎谣 · 第 5 句", "00:52.583")

# ---------------- 6 天苍苍，地莽莽 (亮) ----------------
def shot6(im, d, p, dark, fg):
    d.line([150, 640, W - 150, 640], fill=fg, width=3)
    for r in range(4):
        for c in range(30):
            x = 170 + c * 53 + (r % 2) * 24
            yy = 200 + r * 62 + math.sin(c * 0.7 + p * 5 + r) * 10
            w = 26 + (c * 7 + r * 3) % 30
            d.line([x, yy, x + w, yy], fill=DIM, width=3)
    a = AA()
    for j in range(7):
        cx = 260 + j * 232
        h = 60 + (j * 37) % 90
        a.poly([(cx - 90, 1030), (cx, 1030 - h), (cx + 90, 1030)], w=3)
    a.paint(im, DIM2)
    s = 150; t = "天苍苍，地莽莽"
    big(d, (W - bigw(d, s, t)) / 2, 900, s, t, fg)
    code = [("const 天 = 苍苍, 地 = 莽莽;", "fg")]
    typing(d, 150, 250, 42, code, p, fg, DIM, reveal_by=0.7)
    status(d, "玄翎谣 · 第 6 句", "00:61.254")

# ---------------- 7 明月光（千里长，亦往）(暗) ----------------
def shot7(im, d, p, dark, fg):
    code = [("明月光(千里长, 亦往);", "fg"), ("// harmony:track  和声轨 @2ch", "dim")]
    typing(d, 150, 300, 42, code, p, fg, DIM)
    rich2(d, 150, 640, 150, "明月光", fg)
    rich(d, 150, 800, 62, "（明月光，千里长，亦往）", DIM)
    for t in range(2):
        y0 = 950 + t * 54
        for i in range(96):
            x = 150 + i * 17
            h = 6 + abs(math.sin(i * 0.31 + p * 9 + t * 1.3)) * (48 if t == 0 else 30) * (0.30 + 1.5 * ENV)
            d.rectangle([x, y0 - h, x + 9, y0], fill=fg if t == 0 else DIM)
    status(d, "玄翎谣 · 第 7 句", "00:69.981")

# ---------------- 8 悠悠夜凉（湿衣裳，磨刀枪）(亮) ----------------
def shot8(im, d, p, dark, fg):
    for j in range(int(24 + 42 * ENV)):
        x = 130 + ((j * 149) % 1660)
        yy = 120 + ((j * 271) % 760) + p * (260 + 220 * ENV)
        yy = 120 + (yy - 120) % 760
        d.line([x, yy, x - 5, yy + 30 + 44 * ((j * 13) % 5) / 5], fill=DIM2, width=2)
    a = AA(); bx, by = 1520, 300
    a.poly([(bx - 90, by), (bx + 90, by), (bx, by + 120)], w=4)
    a.poly([(bx - 90, by + 240), (bx + 90, by + 240), (bx, by + 120)], w=4)
    for j in range(4):
        f = (p * 2.2 + j / 4.0) % 1.0
        yy = by + 18 + f * 96
        a.ell(bx - 4, yy - 4, bx + 4, yy + 4, fill=255, out=255, w=2)
    a.paint(im, fg)
    code = [("if (夜.凉) {", "fg"), ("  衣裳.湿();", "fg"), ("  刀枪.磨();", "fg"), ("}", "fg")]
    typing(d, 150, 250, 40, code, p, fg, DIM, reveal_by=0.7)
    rich2(d, 150, 700, 120, "悠悠夜凉", fg)
    rich(d, 150, 840, 54, "（湿衣裳，磨刀枪）", DIM)
    status(d, "玄翎谣 · 第 8 句", "00:73.806")

# ---------------- 9 海内兮传四方 (暗) ----------------
def shot9(im, d, p, dark, fg):
    code = [("传(四方);", "fg"), ("传(四方);", "dim"), ("传(四方);", "dim"), ("传(四方);", "dim")]
    typing(d, 200, 300, 52, code, p, fg, DIM, reveal_by=0.7, lh=1.6)
    a = AA(); cx, cy = 1450, 700
    for j in range(1, 7):
        rr = 60 + j * 62 + p * 60 + 80 * ENV
        if rr > 380: continue
        a.arc([cx - rr, cy - rr, cx + rr, cy + rr], 150, 390, w=3, out=255 if j % 2 else 190)
    a.paint(im, fg)
    rich2(d, 200, 980, 150, "四方", fg)
    status(d, "玄翎谣 · 第 9 句", "00:78.173")

# ---------------- 10 唤阿爹阿娘 千万莫相望 (亮) ----------------
def shot10(im, d, p, dark, fg):
    a = AA(); vx, vy = 1330, 470
    for j in range(9):
        y = 1080 - j * 60
        a.line([(160, y), (vx, vy)], w=2)
    for j in range(4):
        yy = vy + 60 + j * 70 - p * 40
        a.line([(vx + 60 + j * 90, yy), (W - 120 - j * 60, vy + 260 + j * 40)], w=2)
    a.paint(im, DIM2)
    a = AA(); bx = vx - 10 + math.sin(p * 6) * 8; by = vy - 40
    a.line([(bx - 30, by), (bx, by + 18)]); a.line([(bx, by + 18), (bx + 30, by - 4)]); a.paint(im, fg)
    code = [("return 爹娘;", "fg"), ("// 唤阿爹阿娘", "dim"), ("// 千万莫相望", "dim")]
    typing(d, 150, 300, 42, code, p, fg, DIM, reveal_by=0.7)
    s = 140; t = "千万莫相望"
    big(d, 150, 880, s, t, fg)
    seal(d, 1660, 872, 130, "故乡")
    status(d, "玄翎谣 · 第 10 句", "00:81.748")

FN = [shot1, shot2, shot3, shot4, shot5, shot6, shot7, shot8, shot9, shot10]

def frame(i, p, k=None, t=None):
    global ENV, BLINK
    if t is None: t = SHOTS[i][0] + p * (SHOTS[i][1] - SHOTS[i][0])
    if k is None: k = int((t - T0) * FPS)
    ENV = ENVS[max(0, min(len(ENVS) - 1, k))]
    BLINK = (int(t * 3) % 2 == 0)
    im, dark, bg, fg = base(i)
    d = ImageDraw.Draw(im)
    FN[i](im, d, p, dark, fg)
    return im

def frame_at(t):
    for i, (a, b) in enumerate(SHOTS):
        if a <= t < b: return i, (t - a) / (b - a)
    return 9, 1.0

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "preview"
    if mode == "preview":
        ps = [float(x) for x in (sys.argv[2].split(",") if len(sys.argv) > 2 else ["0.85"])]
        for i in range(10):
            for p in ps:
                try:
                    im = frame(i, p)
                    im.save(BASE + "/preview/s%d_p%02d.png" % (i + 1, int(p * 100)))
                    ok = "ok"
                except Exception as e:
                    ok = "FAIL " + repr(e)[:160]; traceback.print_exc()
                print("shot%d p=%.2f %s" % (i + 1, p, ok))
    else:
        n = int((T1 - T0) * FPS)
        rng = range(n) if len(sys.argv) < 3 else range(int(sys.argv[2]), int(sys.argv[3]))
        for k in rng:
            t = T0 + k / float(FPS)
            i, p = frame_at(t)
            frame(i, p).save(BASE + "/out/f%05d.png" % k)
            if k % 120 == 0: print("frame %d/%d  t=%.2f shot=%d p=%.2f" % (k, n, t, i + 1, p), flush=True)
        print("DONE", n)
