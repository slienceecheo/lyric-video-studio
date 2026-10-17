# -*- coding: utf-8 -*-
"""Delivery check: run this against the FILE YOU ARE HANDING OVER, never a PNG sequence.

Usage:
    python verify_delivery.py deliver.mp4 [--film film.py] [--env env_full.json]
           [--nfr 6733] [--fps 30] [--ff <ffmpeg>] [--edges 3] [--out preview]

Sections:
  1 streams   codec / profile / pix_fmt / size / fps / bitrate / duration / audio params
  2 frames    video frames actually decodable == NFR
  3 layout    moov before mdat (faststart) -- concat/remux silently drops it
  4 tags      moov metadata: encoder id, title, and any foreign vendor marker
              (bvc0ot / ByteDance / XCoder / Douyin / Lavf on a platform delivery)
  5 audio     decoded envelope vs the production envelope: best lag + correlation,
              plus peak/clip; a 100 ms-level audio desync passes every picture check
  6 edges     first/last N frames written to <out>/ for the operator to LOOK at

Exit code 0 = every check passed.
"""
import argparse, os, re, subprocess, sys, tempfile


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


def run_ff(ff, args):
    p = subprocess.run([ff, "-hide_banner"] + args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return p.stderr.decode("utf-8", "replace")


def banner(ff, mp4):
    return run_ff(ff, ["-i", mp4])


def box_order(path, limit=24):
    """Top-level MP4 box types in file order (stops at mdat)."""
    order, off, size_total = [], 0, os.path.getsize(path)
    with open(path, "rb") as f:
        while len(order) < limit:
            f.seek(off)
            hdr = f.read(8)
            if len(hdr) < 8:
                break
            size = int.from_bytes(hdr[:4], "big")
            typ = hdr[4:8].decode("latin1", "replace")
            if size == 1:
                size = int.from_bytes(f.read(8), "big")
            if size < 8 or off + size > size_total:
                break
            order.append(typ)
            off += size
            if typ == "mdat":
                break
    return order


VENDORS = [b"bvc0ot", b"ByteDance", b"bytedance", b"XCoder", b"Douyin", b"douyin",
           b"CapCut", b"\xe5\x89\xaa\xe6\x98\xa0", b"Kuaishou", b"liketvc", b"amv0",
           b"meta0", b"orion", b"Orion"]


def moov_strings(path, cap=8 << 20):
    """Printable ASCII runs inside the moov region (search first `cap` bytes + last 1 MB)."""
    data = open(path, "rb").read(cap)
    i = data.find(b"moov")
    if i >= 0:
        import struct
        size = struct.unpack(">I", data[i - 4:i])[0] if i >= 4 else 0
        data = data[i - 4:i - 4 + size] if 8 <= size <= cap else data
    hits = [m.group().decode("ascii") for m in re.finditer(rb"[ -~]{5,}", data)]
    return hits


def work_tmp(base=None):
    """Scratch dir for ffmpeg output, kept INSIDE the project.

    Never use tempfile.mkdtemp() here: under a file sandbox a child process is often
    denied writes under the platform temp dir, and ffmpeg then dies with
    `Error opening output C:\\Users\\...\\AppData\\Local\\Temp\\...\\a.raw: Permission denied`
    (exit 4294967283). The project directory is always writable."""
    p = os.path.join(base or os.getcwd(), "_lvstmp")
    os.makedirs(p, exist_ok=True)
    return p


def audio_lag(ff, mp4, env_path, fps, span=30):
    import json
    import numpy as np
    env = json.load(open(env_path, encoding="utf-8"))
    env = np.asarray(env, dtype=np.float64)
    rate = 8000
    raw = os.path.join(work_tmp(), "a.raw")
    subprocess.run([ff, "-y", "-v", "error", "-i", mp4, "-ac", "1", "-ar", str(rate),
                    "-f", "s16le", "-acodec", "pcm_s16le", raw], check=True)
    d = np.fromfile(raw, dtype="<i2").astype(np.float64)
    peak = float(np.abs(d).max() / 32767.0)
    spf = rate / float(fps)
    n = int(len(d) / spf)
    idx = (np.arange(n + 1) * spf).astype(int)
    rms = np.array([np.sqrt((d[idx[i]:idx[i + 1]] ** 2).mean()) for i in range(n)])
    if rms.max() > 0:
        rms = rms / rms.max()
    rms = np.convolve(rms, np.ones(7) / 7.0, mode="same")
    best = (-1, -2.0)
    for lag in range(-span, span + 1):
        if lag >= 0:
            a, b = rms[lag:], env[:len(rms) - lag if lag else len(rms)]
        else:
            a, b = rms[:lag], env[-lag:len(rms) - lag]
        n2 = min(len(a), len(b))
        if n2 < 100:
            continue
        x, y = a[:n2], b[:n2]
        if x.std() < 1e-9 or y.std() < 1e-9:
            continue
        c = float(np.corrcoef(x, y)[0, 1])
        if c > best[1]:
            best = (lag, c)
    return best[0], best[1], peak, n / float(fps)


def grab(ff, mp4, k, fps, png, out_dir):
    p = os.path.join(out_dir, png)
    subprocess.run([ff, "-y", "-hide_banner", "-loglevel", "error", "-ss", "%.6f" % (k / float(fps)),
                    "-i", mp4, "-frames:v", "1", "-update", "1", p], check=True)
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mp4")
    ap.add_argument("--film", default=None)
    ap.add_argument("--env", default=None)
    ap.add_argument("--nfr", type=int, default=None)
    ap.add_argument("--fps", type=float, default=None)
    ap.add_argument("--ff", default=None)
    ap.add_argument("--edges", type=int, default=3)
    ap.add_argument("--out", default="preview")
    a = ap.parse_args()
    ff = find_ff(a.ff)
    nfr, fps = a.nfr, a.fps
    if a.film and (nfr is None or fps is None):
        import importlib.util
        spec = importlib.util.spec_from_file_location("film", os.path.abspath(a.film))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        nfr = int(getattr(m, "NFR")) if nfr is None else nfr
        fps = float(getattr(m, "FPS", 30)) if fps is None else fps
    nfr = nfr or 0
    fps = fps or 30.0
    ok = True
    os.makedirs(a.out, exist_ok=True)
    b = banner(ff, a.mp4)

    print("== 1. streams ==")
    for line in b.splitlines():
        if re.search(r"Stream #|Duration|encoder|title", line):
            print("  " + line.strip())
    vid = re.search(r"Video: (\S+).*?(\d{3,4}x\d{3,4})", b)
    aud = re.search(r"Audio: (\S+).*?(\d{4,5}) Hz, (\w+)", b)
    if "yuv420p" not in b:
        print("  *** pix_fmt is not yuv420p ***")
        ok = False
    if not aud:
        print("  *** no audio stream found ***")
        ok = False

    print("== 2. frames ==")
    txt = run_ff(ff, ["-i", a.mp4, "-map", "0:v:0", "-f", "null", "-"])
    hits = re.findall(r"frame=\s*(\d+)", txt)
    got = int(hits[-1]) if hits else -1
    print("  decoded %s frames (NFR=%s) -> %s" % (got, nfr, "OK" if got == nfr else "MISMATCH"))
    if nfr and got != nfr:
        ok = False

    print("== 3. layout (faststart) ==")
    order = box_order(a.mp4)
    print("  top-level boxes: %s" % " ".join(order))
    good = "moov" in order and "mdat" in order and order.index("moov") < order.index("mdat")
    print("  moov before mdat: %s" % ("yes -- progressive playback ok" if good else "NO -- add -movflags +faststart"))
    if not good:
        ok = False

    print("== 4. tags / metadata hygiene ==")
    blob = open(a.mp4, "rb").read(2 << 20)
    hits = []
    for m in re.finditer(rb"[ -~]{4,}", blob):
        s = m.group().decode("ascii")
        if re.search(r"^(Lavf|Lavc|libx264|title|encoder|handler|Apple|bvc0|meta)", s):
            hits.append(s)
    seen = []
    for s in hits:
        if s not in seen:
            seen.append(s)
    print("  tool/meta strings: %s" % (", ".join(seen[:10]) or "none found"))
    for v in VENDORS:
        if v in blob:
            print("  *** foreign vendor marker %r found in the file header ***" % v)
            ok = False

    print("== 5. audio ==")
    if a.env and os.path.exists(a.env):
        lag, corr, peak, adur = audio_lag(ff, a.mp4, a.env, fps)
        print("  envelope vs %s: best lag %+d frames (%.1f ms), correlation %.4f"
              % (os.path.basename(a.env), lag, lag * 1000.0 / fps, corr))
        print("  decoded audio %.3f s, peak %.4f %s"
              % (adur, peak, "(no clipping)" if peak < 0.999 else "*** CLIPPED ***"))
        if abs(lag) > 1 or corr < 0.85:
            ok = False
    else:
        print("  (no --env envelope given; skipped the sync check -- pass one, it is the")
        print("   only check that catches an audio/picture offset)")

    print("== 6. edges (write, then LOOK) ==")
    wrote = []
    for k in list(range(a.edges)) + list(range(max(0, nfr - a.edges), nfr)) if nfr else []:
        wrote.append(grab(ff, a.mp4, k, fps, "edge_f%05d.png" % k, a.out))
    print("  %d frames -> %s" % (len(wrote), a.out))

    print("VERDICT: %s" % ("delivery OK" if ok else "DELIVERY PROBLEM (see the flagged lines)"))
    print("Note: a picture-only check cannot see a whole-chunk offset -- run")
    print("      verify_assembly.py as well, and read the audit tool's output on the module")
    print("      that produced this render.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
