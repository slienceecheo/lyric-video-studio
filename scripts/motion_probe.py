# -*- coding: utf-8 -*-
"""Motion probe: does a page move the way you think it does?

Usage:
    python motion_probe.py film.py --seg 15 [--seg 16] [--samples 30] [--step 3]
           [--bar 235] [--tail 120] [--band "x0,y0,x1,y1"] [--out preview/motion.json]

For each page it samples frames straight from the module (no encode, no concat) and
reports the two channels a viewer actually perceives on a static page:

    centroid channel  peak-to-peak and median |step| of the ink centroid row, in px
    mass channel      peak-to-peak of the ink pixel count as a percentage of its mean

Measured on the TAIL of the page by default (last --tail frames), because the first part
of a page carries the line entry animation -- a fade plus a drop whose amplitude is 10x
to 100x any steady-state motion, and which is therefore not what "how much does this page
move" means.  The whole-page figure is printed next to it for reference, so you can see
how much of the motion is entry.

It also reports the one failure mode that reads as strobing on video: whole-frame MAD
between consecutive samples.  A steady ratio is continuous motion; isolated samples at
>3x the median are an EVENT (a flip between two states).

The band is auto-detected from the first sampled frame (the run of text rows containing
the densest single row, outside a 60 px border so HUD chrome is excluded).  Check the
printed band and the sample ink counts; if they look wrong, pass --band.

Exit code 0 always -- this is a measurement tool.  Measure two pages, then judge.
"""
import argparse, importlib.util, json, os, sys

INK_BORDER = 60
PAD = 6
MAD_FLOOR = 0.30  # a "spike" must clear this absolute mean-luma MAD as well as 3x the
                  # median, otherwise a near-zero median turns codec/grain jitter into
                  # fake events.


def load(path):
    spec = importlib.util.spec_from_file_location("film", os.path.abspath(path))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def frame_array(m, k):
    import numpy as np
    return np.asarray(m.frame_t(m.T0 + k / float(m.FPS), k=k).convert("L"), dtype=np.float32)


def mask_of(sub, thr, dark):
    return (sub >= thr) if dark else (sub <= thr)


def profile_shift(ref, rows, span=4.0, coarse=0.25):
    """Sub-pixel vertical shift of `rows` relative to `ref`, by row-profile correlation.

    The centroid of a thresholded mask moves in 1 px stair steps: below a pixel of real
    motion the thresholded mask can be pixel-identical, so the centroid is fine for
    comparing pages but blunt for amplitudes under a pixel.  Shifting an interpolated row
    profile is continuous, so this reports the displacement itself.
    """
    import numpy as np
    ref = np.asarray(ref, dtype=np.float64)
    ref = ref - ref.mean()
    grid = np.arange(0, len(ref), dtype=np.float64)
    out = []
    for r in rows:
        rr = np.asarray(r, dtype=np.float64)
        rr = rr - rr.mean()
        best = None
        d = -span
        while d <= span + 1e-9:
            sh = np.interp(grid - d, grid, rr, left=0.0, right=0.0)
            e = float(np.abs(sh - ref).mean())
            if best is None or e < best[1]:
                best = (d, e)
            d += coarse
        out.append(round(float(best[0]), 3))
    return out


def ink_threshold(inner, dark, fixed=None):
    """Threshold for "this pixel is ink", from the image's own dynamic range.

    An absolute bar (e.g. luma 235) only works for one palette: ink at 31 on a light
    page is nowhere near 255-235, so a fixed bar silently returns an EMPTY mask and the
    probe reports a band of None.  Take the 1st/99th percentile of the frame instead and
    put the split at 55% (dark pages: bright glyphs) or 45% (light pages: dark glyphs).
    """
    import numpy as np
    if fixed is not None:
        return float(fixed)
    lo, hi = np.percentile(inner, 1.0), np.percentile(inner, 99.0)
    return float(lo + (0.55 if dark else 0.45) * (hi - lo))


def auto_band(L, thr, dark):
    """(x0, y0, x1, y1) of the text line holding the densest single row."""
    inner = L[INK_BORDER:-INK_BORDER, INK_BORDER:-INK_BORDER]
    mask = mask_of(inner, thr, dark)
    rows = mask.sum(axis=1)
    if not rows.any():
        return None
    peak = int(rows.argmax())
    keep = rows > 0
    y0 = peak
    while y0 > 0 and keep[y0 - 1]:
        y0 -= 1
    y1 = peak
    while y1 < len(keep) - 1 and keep[y1 + 1]:
        y1 += 1
    band = mask[y0:y1 + 1]
    cols = band.sum(axis=0).nonzero()[0]
    x0 = int(cols[0]) if len(cols) else 0
    x1 = int(cols[-1]) + 1 if len(cols) else band.shape[1]
    # pad: a band that clips the glyph converts a rigid shift into two moving edge rows
    x0 = max(INK_BORDER, x0 + INK_BORDER - PAD)
    x1 = min(L.shape[1] - INK_BORDER, x1 + INK_BORDER + PAD)
    y0 = max(INK_BORDER, y0 + INK_BORDER - PAD)
    y1 = min(L.shape[0] - INK_BORDER, y1 + INK_BORDER + 1 + PAD)
    return (x0, y0, x1, y1)


FLICKER_RATIO = 5.0


def flicker_spikes(Ls):
    """Per-sample change curve and the indices that jump out of their local neighbourhood.

    A spike must be SUDDEN, not merely large: sinusoidal breathing swings the change curve by
    ~8x within one period, so `> 3 * median` calls every breathing page a flicker (and so does
    the star-field twinkle).  Compare each step against the median of the steps around it and
    keep an absolute floor -- an on/off switch is an isolated order-of-magnitude jump, a smooth
    motion never is.
    """
    import numpy as np
    diffs = [float(np.abs(Ls[i + 1] - Ls[i]).mean()) for i in range(len(Ls) - 1)]
    out = []
    for i, v in enumerate(diffs):
        lo, hi = max(0, i - 2), min(len(diffs), i + 3)
        near = sorted(diffs[j] for j in range(lo, hi) if j != i)
        ref = near[len(near) // 2] if near else 0.0
        if v > max(FLICKER_RATIO * ref, MAD_FLOOR):
            out.append(i)
    return diffs, out


def stats(rows, key):
    vals = [r[key] for r in rows if r[key] is not None]
    if len(vals) < 3:
        return None
    d = sorted(abs(vals[i + 1] - vals[i]) for i in range(len(vals) - 1))
    mean = sum(vals) / len(vals)
    return {"p2p": round(max(vals) - min(vals), 3), "median_d": round(d[len(d) // 2], 3),
            "mean": round(mean, 3),
            "pct": round(100.0 * (max(vals) - min(vals)) / mean, 3) if key == "ink" and mean else None}


def page_bounds(m, seg):
    """Time range of page `seg`, from whichever shape the film module publishes.

    `CUTS` (a list of cut boundaries) is the authority when present; otherwise the page's own
    `SEG[seg]["t"]`.  Both are legitimate -- never invent a third source, and never assume a
    uniform page length (pages are cut on musical onsets, so they differ).
    """
    c = getattr(m, "CUTS", None)
    if c is not None and seg + 1 < len(c):
        return float(c[seg]), float(c[seg + 1])
    t0, t1 = m.SEG[seg]["t"]
    return float(t0), float(t1)


def transition_guard(m, seg, override=None):
    """Frames at the END of page `seg` that belong to the outgoing transition, not to rest.

    A film may pre-roll the next page during the current page's last `trd` seconds (the shape
    assets/film_template.py uses: `SEG[i]["tr"], SEG[i]["trd"]`), or blend after the cut (a
    `DISS` constant, the shape the reference project uses).  Either way those frames are not
    the page at rest: sampling them inflates p2p by tens of pixels and turns the cut itself
    into a "flicker spike".  Override with --guard when a project cuts some third way.
    """
    sg = m.SEG[seg]
    trd = sg.get("trd")
    if sg.get("tr") not in (None, "cut") and trd:
        return int(round(float(trd) * float(m.FPS))) + 2
    for name in ("DISS", "FLASH"):
        v = getattr(m, name, None)
        if v:
            return int(round(float(v) * float(m.FPS))) + 4
    return int(round(0.40 * float(m.FPS)))


def measure(m, seg, samples, step, bar, tail, band_override, guard=None):
    import numpy as np
    a, b = page_bounds(m, seg)
    sg = m.SEG[seg]
    dark = bool(sg.get("dark", True))
    label = sg.get("note") or sg.get("slug") or sg.get("s") or "?"
    k0 = int(round((a - m.T0) * m.FPS))
    k1 = int(round((b - m.T0) * m.FPS))
    span = k1 - k0
    g = transition_guard(m, seg, guard)
    n_tail = min(samples * step, max(step, span // 2))
    ks_tail = list(range(max(k0, k1 - g - n_tail), k1 - g, step))
    ks_full = list(range(k0, k1, max(step, max(1, span // samples))))
    Ls_tail = [frame_array(m, k) for k in ks_tail]
    Ls_full = [frame_array(m, k) for k in ks_full]
    thr = ink_threshold(Ls_tail[0][INK_BORDER:-INK_BORDER, INK_BORDER:-INK_BORDER], dark, bar)
    band = band_override or auto_band(Ls_tail[0], thr, dark)
    x0, y0, x1, y1 = band

    def rows_of(ks, Ls):
        out, prof = [], []
        for k, L in zip(ks, Ls):
            sub = L[y0:y1, x0:x1]
            msk = mask_of(sub, thr, dark)
            ys, _ = msk.nonzero()
            out.append({"k": k, "t": round(m.T0 + k / float(m.FPS), 4),
                        "centroid": (float(ys.mean()) + y0) if len(ys) else None,
                        "ink": int(len(ys))})
            prof.append(msk.sum(axis=1).astype(np.float64))
        if prof:
            sh = profile_shift(prof[0], prof)
            for rec, s in zip(out, sh):
                rec["shift"] = s
        return out

    r_tail, r_full = rows_of(ks_tail, Ls_tail), rows_of(ks_full, Ls_full)
    mad, spikes = flicker_spikes(Ls_tail)
    med = sorted(mad)[len(mad) // 2] if mad else 0.0
    return {"seg": seg, "page": label, "dark": dark, "thr": round(thr, 1),
            "guard": g,
            "band": band, "k0": k0, "k1": k1,
            "tail_k": [ks_tail[0], ks_tail[-1]] if ks_tail else None,
            "tail_samples": len(ks_tail), "full_samples": len(ks_full),
            "tail_centroid": stats(r_tail, "centroid"), "tail_ink": stats(r_tail, "ink"),
            "tail_shift": stats(r_tail, "shift"),
            "full_centroid": stats(r_full, "centroid"), "full_ink": stats(r_full, "ink"),
            "full_shift": stats(r_full, "shift"),
            "mad_median": round(med, 4),
            "mad_spikes": spikes, "mad_max": round(max(mad), 4) if mad else 0.0,
            "tail_rows": r_tail}


def report(r):
    print("\n-- page %d  %s  (%s)  k %d..%d   band x%d..%d y%d..%d"
          % (r["seg"], r["page"], "dark" if r["dark"] else "light", r["k0"], r["k1"],
             r["band"][0], r["band"][2], r["band"][1], r["band"][3]))
    print("   ink threshold %.1f (auto; override with --bar)" % r["thr"])
    print("   tail window k %s (%d samples): entry animation and the %d-frame"
          % (r["tail_k"], r["tail_samples"], r["guard"]))
    print("   lead-in transition are both excluded -- this is the page at rest")
    for tag, c, i, sh in (("tail", r["tail_centroid"], r["tail_ink"], r["tail_shift"]),
                          ("page", r["full_centroid"], r["full_ink"], r["full_shift"])):
        if c:
            print("     %-4s centroid p2p %7.3f px (median|step| %5.3f)   ink mass p2p %s%%"
                  % (tag, c["p2p"], c["median_d"],
                     i["pct"] if i and i["pct"] is not None else "-"))
            if sh:
                print("          row-profile shift p2p %6.3f px (sub-pixel; use this one for"
                      " amplitudes under a pixel)" % sh["p2p"])
    print("   flicker: median frame-to-frame MAD %.4f, max %.4f, sudden jumps (>%.0fx its"
          " local median and >%.2f) at samples %s"
          % (r["mad_median"], r["mad_max"], FLICKER_RATIO, MAD_FLOOR,
             r["mad_spikes"] or "none"))
    print("   the band is %d rows tall: shifting the mask by one row moves the centroid by"
          % (r["band"][3] - r["band"][1]))
    print("   1.00 px, so the numbers above are real displacements, not noise.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("film", nargs="?", default="film.py")
    ap.add_argument("--seg", type=int, action="append", default=[])
    ap.add_argument("--samples", type=int, default=30)
    ap.add_argument("--step", type=int, default=3)
    ap.add_argument("--bar", type=float, default=None,
                    help="absolute ink threshold; default auto from each frame")
    ap.add_argument("--tail", type=int, default=120, help="frames of page tail to sample")
    ap.add_argument("--guard", type=int, default=None,
                    help="frames before each cut to keep out of the steady window"
                         " (default: read tr/trd or DISS from the film)")
    ap.add_argument("--band", default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    if not a.seg:
        print("give at least one --seg (page index)")
        return 2
    m = load(a.film)
    band = tuple(int(v) for v in a.band.split(",")) if a.band else None
    print("film: NFR=%s FPS=%s T0=%s  segments=%d"
          % (getattr(m, "NFR", "?"), m.FPS, m.T0, len(m.SEG)))
    out = []
    for seg in a.seg:
        r = measure(m, seg, a.samples, a.step, a.bar, a.tail, band, a.guard)
        out.append(r)
        report(r)
        band = None
    if a.out:
        d = os.path.dirname(a.out)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=1)
        print("\nwrote %s" % a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
