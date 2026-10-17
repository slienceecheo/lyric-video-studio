# -*- coding: utf-8 -*-
"""Assembly integrity check: chunk partition + delivered-frame alignment + seams.

Usage:
    python verify_assembly.py --film film.py --out out --mp4 deliver.mp4
           [--chunks out/chunks.json] [--sub 224] [--nw 8]
           [--points 1000,2240,4194,6200] [--reach 256] [--ff <ffmpeg>] [--no-decode]

Why this exists (references/assembly.md): a chunked render (parallel encode + concat
copy) can splice in a chunk that does not belong to the current cut table.  Nothing
errors, every frame still looks right, and the picture simply runs ahead of the audio
from that point on.  Section A catches the extra/missing chunk, B proves the delivered
pixels are the frames the renderer would draw at that time, C tells you how much B's
"offset 0" is worth, D looks at the seams themselves.

Exit code 0 = every check passed.
"""
import argparse, glob, importlib.util, json, os, re, subprocess, sys, tempfile


def find_ff(explicit=None):
    if explicit:
        return explicit
    if os.environ.get("FFMPEG"):
        return os.environ["FFMPEG"]
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def load(path):
    spec = importlib.util.spec_from_file_location("film", os.path.abspath(path))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def canonical(nfr, nw, sub):
    """THE partition: `nw` worker spans of ceil(nfr/nw) frames, tiled by `sub` frames.

    Every chunk span in the project must come from here -- the driver, the mux and this
    verifier.  A chunk set that depends on how a work range was requested is how the
    reference case ended up with an extra 224-frame chunk and a 7.4 s desync.
    """
    step = (nfr + nw - 1) // nw
    out = []
    for w in range(nw):
        a, b = min(w * step, nfr), min((w + 1) * step, nfr)
        x = a
        while x < b:
            out.append((x, min(x + sub, b)))
            x += sub
    return out


def decode_frames(ff, path):
    """Video frames actually decodable from `path` (ffmpeg prints `frame= N` last)."""
    p = subprocess.run([ff, "-hide_banner", "-i", path, "-map", "0:v:0", "-f", "null", "-"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    hits = re.findall(r"frame=\s*(\d+)", p.stderr.decode("utf-8", "replace"))
    return int(hits[-1]) if hits else None


def read_manifest(path):
    with open(path, encoding="utf-8") as f:
        rows = json.load(f)
    base = os.path.dirname(os.path.abspath(path))
    return [(int(r["k0"]), int(r["k1"]), os.path.join(base, r["file"])) for r in rows]


def discover(out_dir, nfr, pattern="*_sub_*.mp4"):
    """Fallback for an existing project: measure each chunk's span from the NEXT index.

    Deliberately the weaker path -- it is the same name-sorted view of the directory that
    the mux uses, so it cannot by itself tell an extra chunk from a real one.  What it must
    never do is guess: it REFUSES when two files claim the same index (typically two films'
    chunks in one directory) instead of inventing a zero-length span from the collision.
    """
    found = []
    for p in sorted(glob.glob(os.path.join(out_dir, pattern))):
        m = re.search(r"_sub_(\d{5})\.mp4$", os.path.basename(p))
        if m:
            found.append((int(m.group(1)), p))
    found.sort()
    same = {}
    for s, p in found:
        same.setdefault(s, []).append(p)
    clash = {s: v for s, v in same.items() if len(v) > 1}
    if clash:
        lines = ["  frame %5d: %s" % (s, ", ".join(os.path.basename(x) for x in v))
                 for s, v in sorted(clash.items())[:8]]
        raise SystemExit("REFUSING: two chunk files claim the same start frame -- the directory "
                         "holds more than one film's chunks.\n" + "\n".join(lines)
                         + "\n  Pass --glob <pattern> or --chunks out/chunks.json.")
    rows = []
    for i, (s, p) in enumerate(found):
        e = found[i + 1][0] if i + 1 < len(found) else nfr
        rows.append((s, e, p))
    return rows


def grab(ff, mp4, k, fps, png):
    subprocess.run([ff, "-y", "-hide_banner", "-loglevel", "error", "-ss", "%.6f" % (k / float(fps)),
                    "-i", mp4, "-frames:v", "1", "-update", "1", png], check=True)
    return png


def luma(png, step=3):
    import numpy as np
    from PIL import Image
    a = np.asarray(Image.open(png).convert("L"), dtype=np.float32)
    return a[::step, ::step]


def render(m, k, png):
    m.frame_t(m.T0 + k / float(m.FPS), k=k).save(png)
    return png


def work_tmp(base=None):
    """Scratch dir for ffmpeg output, kept INSIDE the project.

    Never use tempfile.mkdtemp() here: under a file sandbox a child process is often
    denied writes under the platform temp dir, and ffmpeg then dies with
    `Error opening output C:\\Users\\...\\AppData\\Local\\Temp\\...\\a.raw: Permission denied`
    (exit 4294967283). The project directory is always writable."""
    p = os.path.join(base or os.getcwd(), "_lvstmp")
    os.makedirs(p, exist_ok=True)
    return p


def main():
    import numpy as np
    ap = argparse.ArgumentParser()
    ap.add_argument("--film", default="film.py")
    ap.add_argument("--out", default="out")
    ap.add_argument("--mp4", required=True)
    ap.add_argument("--chunks", default=None)
    ap.add_argument("--glob", default="*_sub_*.mp4")
    ap.add_argument("--sub", type=int, default=224)
    ap.add_argument("--nw", type=int, default=8)
    ap.add_argument("--points", default="")
    ap.add_argument("--reach", type=int, default=256)
    ap.add_argument("--ff", default=None)
    ap.add_argument("--no-decode", action="store_true")
    a = ap.parse_args()
    ff = find_ff(a.ff)
    m = load(a.film)
    nfr = int(getattr(m, "NFR"))
    fps = float(getattr(m, "FPS", 30))

    exp = canonical(nfr, a.nw, a.sub)
    tmp = work_tmp(a.out if os.path.isdir(a.out) else os.path.dirname(os.path.abspath(a.out)))
    ok = True

    print("== A. structural: manifest / disk / canonical partition ==")
    print("  canonical: %d chunks over %d frames (nw=%d sub=%d), last chunk %d frames"
          % (len(exp), nfr, a.nw, a.sub, exp[-1][1] - exp[-1][0]))
    if a.chunks and os.path.exists(a.chunks):
        got = read_manifest(a.chunks)
        print("  manifest : %s (%d chunks)" % (a.chunks, len(got)))
    else:
        got = discover(a.out, nfr, a.glob)
        print("  WARNING: no chunk manifest -- discovered %d files matching %r in %s."
              % (len(got), a.glob, a.out))
        print("           Glob discovery is what caused the desync in the reference case;")
        print("           the driver should write out/chunks.json as it finishes each chunk.")
    extra = [(x, y) for x, y, _ in got if (x, y) not in exp]
    missing = [(x, y) for x, y in exp if (x, y) not in [(u, v) for u, v, _ in got]]
    print("  extra   : %s" % (extra or "none"))
    print("  missing : %s" % (missing or "none"))
    if extra or missing:
        ok = False
    contig = all(got[i][1] == got[i + 1][0] for i in range(len(got) - 1)) and got and got[0][0] == 0
    print("  contiguous from 0: %s" % ("yes" if contig else "NO"))
    if not contig:
        ok = False
    if not a.no_decode:
        bad = []
        for x, y, p in got:
            n = decode_frames(ff, p)
            if n != y - x:
                bad.append((os.path.basename(p), x, y, n))
        print("  frame counts: %s" % ("all match their span" if not bad else "MISMATCH %s" % bad))
        if bad:
            ok = False
    total = sum(y - x for x, y, _ in got)
    print("  sum=%d  (NFR=%d)" % (total, nfr))
    if total != nfr:
        ok = False

    pts = [int(x) for x in a.points.split(",") if x.strip()] or \
          [nfr // 8, nfr // 2, nfr - nfr // 4, nfr - 60]
    print("== B. pixel: which rendered frame sits at container time k/fps ==")
    print("  (points %s; move-rich points only -- see section C)" % pts)
    for k in pts:
        ref = luma(grab(ff, a.mp4, k, fps, os.path.join(tmp, "d.png")))
        best = None
        for d in list(range(-a.reach, a.reach + 1, 16)):
            kk = k + d
            if 0 <= kk < nfr:
                e = float(np.abs(luma(render(m, kk, os.path.join(tmp, "c.png"))) - ref).mean())
                if best is None or e < best[1]:
                    best = (d, e)
        for d in range(best[0] - 15, best[0] + 16):
            kk = k + d
            if 0 <= kk < nfr:
                e = float(np.abs(luma(render(m, kk, os.path.join(tmp, "c.png"))) - ref).mean())
                if e < best[1]:
                    best = (d, e)
        flag = "OK" if best[0] == 0 else "*** SHIFT ***"
        print("  k=%6d  best offset %+5d  mean|dL| %6.3f   %s" % (k, best[0], best[1], flag))
        if best[0] != 0:
            ok = False

    print("== C. sensitivity: what a synthetic offset costs at those points ==")
    print("  (absolute mean|dL|, and the INCREMENT over the best offset -- the increment is the")
    print("   signal: a 1-frame increment near 0 means section B's '+0' proves little here)")
    for k in pts[:2]:
        ref = luma(grab(ff, a.mp4, k, fps, os.path.join(tmp, "d.png")))
        base, row = None, {}
        for d in (0, 1, 5, 30):
            if 0 <= k + d < nfr:
                e = float(np.abs(
                    luma(render(m, k + d, os.path.join(tmp, "c.png"))) - ref).mean())
                if d == 0:
                    base = e
                else:
                    row[d] = (round(e, 3), round(e - (base or e), 3))
        if not row or base is None:
            continue
        inc1 = row.get(1, (0, 0))[1]
        strength = ("weak (the picture barely moves here)" if inc1 < 0.25 else
                    "fair" if inc1 < 1.0 else "strong")
        print("  k=%6d  base %6.3f  " % (k, base) +
              "  ".join("+-%d: %.3f (+%.3f)" % (d, v[0], v[1]) for d, v in sorted(row.items())) +
              "   -> %s" % strength)

    print("== D. seams: does the delivery continue across each chunk boundary ==")
    lo = [x for x, _ in exp[1:4]]
    hi = [x for x, _ in exp[-3:]]
    for b in sorted(set(lo + hi)):
        if b <= 1 or b >= nfr - 1:
            continue
        f = [luma(grab(ff, a.mp4, b + i, fps, os.path.join(tmp, "s%d.png" % (i + 2))))
             for i in (-2, -1, 0, 1)]
        seam = float(np.abs(f[2] - f[1]).mean())
        floor = 0.5 * (float(np.abs(f[1] - f[0]).mean()) + float(np.abs(f[3] - f[2]).mean()))
        ratio = seam / max(floor, 1e-6)
        flag = "ok" if ratio < 12 else "*** DISCONTINUITY ***"
        print("  boundary k=%6d  seam %6.3f  neighbour floor %6.3f  ratio %6.2f  %s"
              % (b, seam, floor, ratio, flag))
        if ratio >= 12:
            ok = False

    print("VERDICT: %s" % ("assembly OK" if ok else "ASSEMBLY PROBLEM (see the flagged lines)"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
