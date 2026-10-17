# Renderer architecture

Contents: 1 two-file split - 2 SEG schema - 3 helper API - 4 layers and background - 5 transitions - 6 adding a page - 7 the audit API - 8 reserving page geometry - 9 motion vocabulary.

## 1. The two-file split
`assets/render_prefix.py` is the shared core: constants, fonts, text helpers, the AA mask painter, the layer stack, and a 10-line sample film. `assets/film_template.py` is the real film and pulls the core in by exec-ing everything before the sample page list:

```
BASE = "<project dir>"
_src = open(BASE + "/render.py", encoding="utf-8").read()
exec(compile(_src.split("FN = [shot1")[0], "render_prefix", "exec"), globals())
T0, T1 = <first sung onset>, <song end>
FPS = 30
NFR = int((T1 - T0) * FPS)
ENVS = json.load(open(BASE + "/env_full.json"))
X0, CELL, COLS = 160.0, 20.0, 80
PAD = 30; W2, H2 = W + 2 * PAD, H + 2 * PAD; OX, OY = PAD, PAD
```
The split exists so the film can override `T0/T1/NFR` and every page renderer without forking the helpers. Two rules follow from exec-ing into `globals()`: never reuse an existing global name for a new purpose, and keep the split marker string (`FN = [shot1`) stable or update both files together.

### Three-part assembly, and the vertical short that shares it
When the same song ships as a landscape film AND a vertical short, build the second one from the first one's parts instead of copying the file:
```
_head.py      renderer core: geometry, fonts, palette, layout engine, chrome, frame()
_shortcfg.py  ONE switch: W, H = 1080, 1920; B.init(W, H); VWIN = (t0, t1); NFR
_mid.py       content tables + page assembly (reads VWIN when the short defines it)
_tail.py      frame_t / frame / __main__ (preview, render A B)
```
and concatenate them into a PRODUCT module (`film_land.py`, `film_short.py`) with an assembler script; never hand-edit a product, always edit a part and reassemble. Two traps, both paid for once:
- **Every W-derived constant must be recomputed after the canvas swap.** The core computes `XR = W - 150` at import time with the landscape width; a 1080-wide short that only rebinds `W` leaves the footer's right edge at x=1800 and the audit reports 出画 on every page. Rebinding `W, H` inside `_shortcfg.py` and recomputing `XR`, `MAXW`, and any other derived constant there is the fix, and asserting the expected tuple (`assert (X0, XR, XRV, MAXWV) == (150.0, 930.0, 960.0, 840.0)`) catches the next one.
- **The window switch belongs in the data layer, not the renderer.** `_mid.py` slices `TIMELINE.PAGES` when `VWIN` exists, clips the first/last page bounds, drops a trailing card fragment, appends the short's own tail card, and recomputes `NPAGE`/`NFR` -- so both products share one timing authority and the short's cuts stay on the song's real onsets.


## 2. Segment schema
`SEG` is a list of dicts built by:
```
SEG = []
def add(t0, t1, s, dark, **kw):
    d = dict(t=(t0, t1), s=s, dark=dark, seed=(len(SEG) * 37 + 11) % 997)
    d.update(kw); SEG.append(d)
```

| Field | Meaning |
|---|---|
| `t` | `(t0, t1)` song time; `p` inside the page is `(t - t0) / (t1 - t0)` |
| `s` | renderer key: either a legacy `shot*` function in the core or a `R_*` renderer in the film |
| `dark` | light-on-dark page when true, dark-on-light when false |
| `seed` | per-page random seed for dust and mottle |
| `back` | background layer names, e.g. `['grad','mottle','grid','ruler','frame','ghost']` |
| `ghost`, `ink` | ghost glyph and ink-wash variant keys |
| `dust` | dust mote count; `dustdir` for direction; `mirror` to mirror the page |
| `code` | list of `(text, style)` lines; style is `fg`, `dim`, `zhu` |
| `codex`,`codey`,`codeS`,`lh`,`cmt`,`rowmax`,`rb` | code block origin, size, line height, comment column |
| `rows` | `(left, mid, right, style)` table rows; `rowy`,`rowlh`,`rowS` |
| `log` | `(text, style)` log/console lines, drawn BELOW the code block |
| `big` | display headline text; `bigS`,`bigx`,`bigy`,`bigc` (centre), `bigfont='smiley'` for 得意黑 |
| `st`, `tm` | status bar left and right strings |
| `tb` | top bar string |
| `fly` | characters that drift across the page |
| `cap`, `capx`, `capy`, `capS` | caption line (only used by page renders that draw it themselves) |
| `seal`, `sealx`, `sealy`, `sealS`, `sealc` | seal stamp box (likewise page-local) |
| `tr`, `trd` | transition key into the NEXT segment and its duration in seconds (default 0.5) |

## 3. Helper API (core)
```
F(path, size)                     # cached ImageFont
cjk(ch)                           # True for CJK/fullwidth code points
runs(t)                           # split a string into [['c'|'l', text], ...] runs
fnt(k, s)                         # font for a run kind: the monospace face (2:1 advance)
width(d, s, t)                    # realised advance width, run by run
rich(d, x, by, s, t, fill, reveal=None)     # mixed CJK/Latin text at a baseline; reveal truncates chars
rich2(d, x, by, s, t, fill, path=None)      # single-font text (Medium / Smiley)
rrich(d, x_right, by, s, t, fill, reveal=None)  # right-aligned rich
big(d, x, by, s, t, fill, stroke=0, stroke_fill=None)   # display text in the Smiley face
bigw(d, s, t)                     # display advance width
cursor(d, x, by, s, fill)         # block caret
typing(d, x, y0, s, lines, p, fg, dim, reveal_by=0.55, lh=1.75)   # progressive typing of a code block
dashes(d, x1, y1, x2, y2, n, fill, w=2, duty=0.55)
seal(d, cx, cy, size, chars, color)
status(d, left, right, y=1024, s=30, col)
topbar(d, t, col, s=30)
class AA                          # 2x supersampled mask painter (auto-crops to the ink bbox)
base(i, p=0.0)                    # background image for segment i
static_bg(i)                      # cached background without per-frame motion
dust(im, i, t, fg, seg)           # particle layer
frame(i, p, k=None, t=None)       # render segment i at progress p
frame_at(t) -> (i, p)             # which segment a song time falls in
frame_t(t, k=None)                # transition-aware frame for an absolute song time
```

Film-level additions in `film_template.py`: `gx(c)`, `clen(s)` (CJK counts 2), `snap(x)`, `snapS(s)` (40 or 60 px), `align_rows(rows, cmtcol=56, eqmin=13)` (pads `x = y` and trailing `//` comments into columns), `typing2(...)` (snapped + comment-aligned typing), `status2(...)`, `topbar2(...)`, `tint(...)`.

Drawing is always `anchor='ls'` (left baseline). Baselines, not top-left corners, are what all the box maths assumes.

## 4. Layers and background
`base(i, p)` composites, in order, the named `back` layers: `grad`, `mottle`, `grid`, `ruler`, `frame`, `ghost`, `ink`, each at its own alpha from `DEF_ALPHA = {'grad': 24, 'mottle': 10, 'grid': 12, 'ruler': 30, 'frame': 34, 'ghost': 11, 'ink': 15}`. Static layers are cached with `static_bg(i)` so a 47-frame page does not repaint the grid 47 times.
Page rhythm comes from alternating `dark` and the layer set: `['grad','mottle','grid','ruler','frame','ghost']` for airy pages, `['grad','mottle','grid','ruler','frame','ink']` for heavy ones.

## 4b Ambient / atmospheric layers (when the note is 「背景很单调」)
Sooner or later the note is not "this page is wrong" but "the background is plain" -- 加点孔明灯 / 云 / 水上的灯 / 飘落的花. That is a layer-stack job, not a per-page job, and it is the one change that touches every page at once.

Contract:
1. **One `ambient(im, sg, t, p)` call, drawn after the background and BEFORE any text.** It can then never cover a glyph, and the audit's numbers do not change (which is the whole point: an ambient layer that lives in the decoration set has to fight every page's box budget).
2. **Everything in it wraps, nothing is born.** A particle is `y = ((phase0 + t*speed) mod 1)` mapped over `(-pad, H+pad)`, with `speed`, `x`, `size`, `alpha` from a stable hash of the particle index -- so there is no frame at which anything appears or disappears, and the field is continuous in time by construction. Cost: no state, no per-page seeding, and it looks the same if you render frames out of order.
3. **Alpha is bucketed, then cached.** Quantise the driver to ~16 levels and cache the whole layer per `(polarity, bucket)` in an LRU of ~6. A cross-fade then costs one `paste`, not one gradient. A continuously varying per-particle alpha computed per frame is the usual reason an ambient layer costs 0.3 s/frame.
4. **Light is a gradient, not a stack of shapes.** `a = (np.clip(1 - d, 0, 1) ** k) * (0.16 + 0.62*flux)` over the normalised elliptical distance `d`, painted into one alpha tile; AA primitives only for the silhouette (rim, ribs, hanger). Concentric ovals with rising alpha render as graph paper.
5. **Silhouettes must be the geometry, not a paint-over.** A crescent is the intersection of two masks (`ImageChops.multiply`), never a background-coloured disc slid across the face -- the disc reaches past the object's own tile and gets clipped square, printing a grey rectangle behind the lyric.
6. **Behind the type ≠ invisible.** Compute the page's text boxes once (`content_boxes`), and scale an object's alpha by ~0.38 inside them, so an object passing behind the headline reads as depth instead of as a gap.
7. **Drive the density by progress, not by time or beat**: `warmth(t)`/`progress(t)` sets how many objects exist and how bright they are, so the atmosphere follows the song's arc (a moonlit first half, a lamp-lit finale) rather than being uniformly busy. This is a continuous channel and it composes with the polarity rhythm.
8. **Do not touch the type.** An ambient layer has no boxes, no clamp and no share of the layout budget; if it needs to be visible THROUGH the type, it dims itself (rule 6) and nothing else changes.

Objects that earned their cost in the 心月灯 project: 孔明灯 (warm ovals with a cached radial glow, wrapping upward, brightness gated by progress), 河灯 (a waterline + drifting ripples + a 4-segment reflection per lamp + moonlight glitter), translucent cloud bands at three speeds, and a ground light-wash that rises with progress. Measured: `diff_cell` between consecutive frames stays at the HUD's level (~0.02) with the whole stack on, and the contact sheet shows the fields as continuous.

## 5. Transitions
Seven implementations, all `(a, b, q, seg) -> Image`:

| Key | Effect |
|---|---|
| `roll` | vertical roll of the whole frame |
| `wipe` | hard edge sweeping across |
| `blinds` | column slats opening, optional stagger |
| `slice` | horizontal slices sliding at different speeds |
| `dissolve` | `Image.blend(a, b, q)` |
| `flash` | blow the frame to the background colour, then cut |
| `cut` | hard cut at q=0.5 |

`frame_t(t)` renders the current segment normally, and during the last `trd` seconds also renders the NEXT segment at `p=0` as a skeleton (background, chrome, status only) and composites with the transition mask -- so the incoming page arrives already typeset but not yet written, then the typing continues. Every mask must be broadcast to `(H, W)`; see references/pitfalls.md.
Test with `scripts/transition_matrix.py`: 6 rows x 3 columns of q=0.25/0.5/0.75 over two solid test frames. Read the matrix before rendering the film.

## 6. Adding a page
```
def R_mypage(im, d, p, dark, fg, seg):
    code = [("if (河.有梁) 过河();", "fg"), ("// 河无梁", "dim")]
    y = typing2(d, seg.get('codex', X0), seg.get('codey', 268), seg.get('codeS', 40),
                code, p, fg, DIM, reveal_by=0.7, lh=seg.get('lh', 1.78))
    a = AA()                       # vector art, supersampled
    for j in range(1, 7):
        rr = 60 + j * 62 + p * 60 + 80 * ENV
        a.arc([1450 - rr, 700 - rr, 1450 + rr, 700 + rr], 150, 390, w=3, out=255)
    a.paint(im, fg)
    rich2(d, X0, 700, 120, "河无梁", fg)
    status2(d, seg['st'], seg['tm'])
REND['mypage'] = R_mypage
```
`REND` maps the segment key to the renderer; `LEG` maps legacy `shot*` pages. `draw_seg` picks `LEG` first, then `REND`. Every renderer receives the in-progress `p` and the module-global `ENV` (current envelope value) and must not mutate the segment dict.

## 7. The audit API (keep these four in sync with the renderers)
```
ink_ext(s, smiley)        # (top_em, bottom_em) measured ink extent, cached per size
_hit(a, b, m=8)            # 2D intersection of two (x0, y0, x1, y1) boxes with an 8 px margin
big_box(d, x, yb, s, t, seg)      # display text ink box; applies the CLAMP against content boxes
content_boxes(d, seg)     # ink boxes of every non-display block: code, rows, log
```
Two contracts decide whether the audit is worth anything:

**It must measure what the renderer draws.** The four helpers above belong to the template's "place text from SEG fields" shape. If the film computes its own plan, expose that plan instead -- `layout(d, seg)` returning `{code, rows, big, cap, seal, deco, boxes:[(name, box)...], deco_boxes:[...]}` -- and audit it with `layout_audit.py --from-layout --require-deco`. A field-name mismatch makes the audit grade a fiction and print `0` while the frame has strokes across the headline. Corollary: when you rewrite the layout engine, rewrite the audit in the same edit.

**Decorations are content.** Declare a rect for every decoration the page draws, hand it to the audit as `deco_boxes`, and audit it like text. A decoration outside the box set can cover any glyph it likes. If a decoration's ink genuinely overshoots its rect (a wind sine at +-0.075 of its band height, arcs straying), inset it or clip it at draw time (`AA.paint` to a clipped region) rather than widening the declared box.

## 8. Laying out a page: reserve, do not clamp
A clamp cannot create room. The reference project spent a day walking a collision count 35 -> 25 -> 28 -> 27 -> 17 by nudging pairs, and reached 0 only after the layout became an explicit allocator:

1. **Two columns.** A page whose code panel is present gives the panel the LEFT column (`X0` to `X0 + min(code_width + 16, 470)`) and puts the display line in the right one (`gx0 = max(X0 + 490, code_left + 22, 620)`, right edge clamped to the viewport margin minus the vertical-gutter width). The display line's width budget is then a real number, not `W - 2*X0`.
2. **Bands.** The code panel prefers the band between the header rule and the footer rule (`pt_min = header_rule_y + 22`, `lim = footer_base - ink_top*size - 14`). Fit by walking line-height candidates DOWNWARD (`1.78, 1.62, 1.48, 1.32, 1.16`) and accepting the first that fits -- never stretch spacing to fill a band.
3. **Vertical first, horizontal last.** Refit the display line vertically, then place it horizontally, and after moving a display block RE-DERIVE its baseline from its own box: `yb0 = box_bottom - (len(lines)-1)*step - max(ink_bottom(line))`. Clamping the box without re-deriving `yb0` draws the text outside the box the audit just approved.
4. **Concession order.** If the panel still lands on the caption: tighten spacing, then move the caption to the running-head position under the header rule (`CAP_TOP_Y`), then drop the decoration. Text is mandatory; decoration is bonus.
5. **Per-page transition length.** `sg["trd"] = 0.20 if (t1 - t0) < 1.60 else 0.38`; a 1.02 s page must not spend a third of its life dissolving.
6. **Fit the display line by SIZE first, and know the advance.** 得意黑 measures **0.435-0.445 em per CJK glyph advance** (not 1.0): an N-glyph line is about `0.44*N*size` wide, so a "use as few lines as possible" policy collapses a 7-glyph line to an unreadable size while two rows would have kept it large. Policy that works: `fit_display(d, text, avail, smax=176, smin=96)` prefers the LARGEST size inside AT MOST TWO rows, and only accepts a third row when two rows would drop below ~0.63 of `smax`. Then measure the block's own ink bbox and LIFT it if it violates the caption: `lift = max(0, bb[3] + 10 - cap_box[1]); if lift: yb0 -= lift` -- a CJK comma or 、 hangs below the baseline and will otherwise collide with the caption two rows down.
7. **Place the lines in READING ORDER.** `nl = len(lines); yb = yb0 - (nl - 1 - j) * lh`: line 0 gets the HIGHEST baseline. Authoring the list top-to-bottom while drawing index 0 at the bottom inverts every multi-line page, and no plan-level check can see it (see references/lyrics-and-cards.md, the ORDER check).

## 9. Motion vocabulary
Three kinds of change, all of them continuous functions of `p` or `t` -- never of a beat index:

1. **reveal** -- per-character typing (`typing`/`typing2` with `reveal_by`) and the staggered entry of the display block: `a = clamp((p - (0.06 + i*0.17)) / 0.14, 0, 1)`, then `y = baseline + (1 - a) * 26` and a fade of `a`. Progress-driven, so it cannot flicker.
2. **breathing** -- one value from the smoothed envelope plus a sine, applied to a few channels at low amplitude. Reference values: `BR_PERIOD = 1.45`, `BR_ENV = 0.48`, `BR_SINE = 0.52`, `BR_DEPTH = 0.010`. Apply it to GEOMETRY that is vector (the decoration box scales about its own centre by `1 + BR_DEPTH * breath(t)`, clipped to its box with `softlimit(x) = x / (1 + |x|)` so it can never go sharp) and to the display line's INK DENSITY (`fill = mix(fill, bg, max(0, 0.020*breath(t)))`). **Do not apply it to the display line's POSITION**: `draw.text` rasterises on integer y, so `-BR_DEPTH*size` (about +-1.5 px at 150 px type) is not sub-perceptual, it is a full-pixel step of the whole line twice per period -- a 0.36 mean|dL| edge event, larger than a page change, which the assembly verifier then reports as a chunk seam. Everything else on the page (frame, rulers, status bar, counters, timecode) stays constant on purpose.
3. **transition** -- the page boundary only (dissolve or flash).

A beat-locked toggle is not a fourth kind; in the reference film it was the defect. If a channel must react to the music, react continuously to the envelope.

Polarity and transition type are data, not per-page code: keep one `DK = {page_index: 0|1}` dict as the single authority (a `dark=` keyword passed to a page helper is decorative and is overwritten at load), and one `FORCED_DISS = (page indices)` tuple for boundaries that dissolve even when the polarity does not change; `cut_kind(i)` returns dissolve when forced or when the polarity changes, else flash.

Verify the amplitude with `scripts/motion_probe.py`: tail centroid p2p, sub-pixel row-profile shift, ink mass, and a flicker check that compares each sampled step with the median of its neighbours plus an absolute floor (a sinusoid swings its own derivative by ~8x, so a `3x median` rule calls every breathing page a flicker). "I added motion" is not evidence, and a whole-page average is not a measurement.

The probe reads page bounds from `CUTS` when the film publishes it and from `SEG[i]["t"]` otherwise, and it keeps a lead-in guard (`SEG[i]["trd"]`, else `DISS` / `FLASH`, else 0.4 s, overridable with `--guard`) out of the steady window -- sampling up to a few frames before a cut otherwise measures the cut as a 44 px swing. Expect large glyphs to move in whole pixels: `PIL` rasterises on integers, so a 1 px step changes a whole glyph's edges at once (a jump whose change bbox is the glyph is quantisation, not flicker) and any amplitude under a pixel disappears. Set the amplitude from the type size (1 % = 1.5 px at 150 px) and never claim sub-pixel text motion from a rendered frame.

`big_box` and `content_boxes` are what make `layout_audit.py` meaningful: the audit recomputes the same boxes and asserts they never intersect. If you add a new text block type, add it to `content_boxes` -- otherwise it is invisible to the audit and the next delivery ships with a collision.
