# -*- coding: utf-8 -*-
"""verify_short.py -- read back the DELIVERED vertical short and prove it, section by section.

Nothing here trusts the renderer or any intermediate file: every claim is taken from the final mp4.
    A streams     W x H, yuv420p, FPS, h264 High, aac LC, 48 kHz stereo, ~192 kb/s
    B duration    NFR/FPS +-0.05 s, and the decoded frame count == NFR
    C container   moov before mdat (faststart actually took effect)
    D metadata    no foreign vendor tag, an explicit title present
    E audio       length + a NON-SILENT head (the window must start on music, not on air), then the
                  delivered track cross-correlated against the source decode at T0: |offset| <= 1 frame
    H lrc         the first page's song time sits within +-0.150 s of the official LRC stamp
    F pixels      the delivered frame at k IS the module's frame at k (spot checks at 5 points)
    F2 seams      at every chunk boundary, frames b-1 / b / b+1 must all match the module frame by frame
                  -- a stale or dropped chunk is invisible to F but fatal here (the 224-frame incident)
    G sheets      extract 8 frames for eyeball review

Why both F and F2: F samples the interior of chunks, so a chunk that is missing, duplicated or stale
still passes F at every point it samples. Only the boundaries prove the assembly.

Usage:
  python scripts/verify_short.py <short.mp4> [--mod short.py] [--chunks out/chunks_short.json]
                                [--song8k audio/song_8k.raw] [--lrc lrc_lines.json]
                                [--out preview_s] [--ff <ffmpeg>]

The module must expose NFR, FPS, W, H, T0, SEG and frame_t(t, k=...).  A landscape film with the same
names works too -- point --mod at it and --chunks at its manifest to check any delivered file this way.
"""
import argparse, importlib.util, json, os, re, subprocess, sys, wave
import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
VENDOR = ("XCoder", "Bento4", "bvc0ot", "ByteDance", "Douyin", "CapCut", "Pitaya",
          "VE_Camera", "Jianying")


def find_ff(explicit=None):
    if explicit:
        return explicit
    if os.environ.get("FFMPEG"):
        return os.environ["FFMPEG"]
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    for c in ("ffmpeg", r"C:\ffmpeg\bin\ffmpeg.exe"):
        if os.path.exists(c) or c == "ffmpeg":
            return c
    raise SystemExit("no ffmpeg found: pass --ff <path>")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mp4")
    ap.add_argument("--mod", default="short.py")
    ap.add_argument("--chunks", default=None, help="chunk manifest; default out/chunks_short.json if it exists")
    ap.add_argument("--song8k", default="audio/song_8k.raw", help="mono s16le 8 kHz decode of the SOURCE song")
    ap.add_argument("--lrc", default="lrc_lines.json", help="parsed official LRC ([{t,text,stamp}])")
    ap.add_argument("--out", default="preview_s")
    ap.add_argument("--tmp", default="_lvstmp")
    ap.add_argument("--tol", type=float, default=6.0, help="mean|d| ceiling for a pixel match (codec noise)")
    ap.add_argument("--ff", default=None)
    a = ap.parse_args()
    FF = find_ff(a.ff)
    fails = []

    def ff(args):
        p = subprocess.run([FF, "-hide_banner"] + args, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        return p.returncode, p.stdout, p.stderr

    spec = importlib.util.spec_from_file_location("m", os.path.abspath(a.mod))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    NFR, FPS, W, H, T0 = int(m.NFR), float(m.FPS), int(m.W), int(m.H), float(m.T0)
    NT = NFR / FPS
    print("FILE  %s  %d bytes" % (a.mp4, os.path.getsize(a.mp4)))
    print("SPEC  %dx%d  %d frames = %.6f s  window starts at %.4f s" % (W, H, NFR, NT, T0))

    rc, o, info = ff(["-i", a.mp4, "-f", "null", "-"])
    print("-- A streams " + "-" * 60)
    for key, want in (("%dx%d" % (W, H), "resolution"), ("yuv420p", "pix_fmt"),
                      ("%d fps" % FPS, "frame rate"), ("h264 (High)", "profile"),
                      ("aac (LC)", "audio codec"), ("48000 Hz, stereo", "audio layout")):
        ok = key in info
        print(("  OK  " if ok else "  FAIL") + "  %-14s %s" % (want, key))
        if not ok:
            fails.append(("stream", want))
    mab = re.search(r"Audio: aac \(LC\).*?(\d+) kb/s", info)
    ab = int(mab.group(1)) if mab else 0
    ok = 160 <= ab <= 220
    print("  %s  %-14s %d kb/s (target 192k)" % ("OK  " if ok else "FAIL", "audio bitrate", ab))
    if not ok:
        fails.append(("stream", "audio bitrate"))

    print("-- B duration / frame count " + "-" * 45)
    md = re.search(r"Duration: (\d+):(\d+):([\d.]+)", info)
    dur = int(md.group(1)) * 3600 + int(md.group(2)) * 60 + float(md.group(3)) if md else 0.0
    ok = abs(dur - NT) < 0.05
    print("  %s  %-14s %.3f s (want %.3f)" % ("OK  " if ok else "FAIL", "container", dur, NT))
    if not ok:
        fails.append(("duration", dur))
    rc, o, e = ff(["-i", a.mp4, "-map", "0:v:0", "-f", "null", "-"])
    mf = re.findall(r"frame=\s*(\d+)", e)
    dec = int(mf[-1]) if mf else 0
    ok = dec == NFR
    print("  %s  %-14s %d (want %d)" % ("OK  " if ok else "FAIL", "decoded frames", dec, NFR))
    if not ok:
        fails.append(("frames", dec))

    print("-- C/D container + metadata " + "-" * 45)
    with open(a.mp4, "rb") as f:
        head = f.read(1 << 20)
    i_moov, i_mdat = head.find(b"moov"), head.find(b"mdat")
    ok = 0 <= i_moov < i_mdat
    print("  %s  moov before mdat (moov@%d mdat@%d)" % ("OK  " if ok else "FAIL", i_moov, i_mdat))
    if not ok:
        fails.append(("faststart", (i_moov, i_mdat)))
    leak = [v for v in VENDOR if v in info]
    print("  %s  vendor tags    %s" % ("OK  " if not leak else "FAIL", leak or "clean"))
    if leak:
        fails.append(("metadata", leak))
    rc, o, e = ff(["-i", a.mp4, "-f", "ffmetadata", "-"])
    tt = re.search(r"^title=(.*)$", o, re.M)
    print("  %s  title          %s" % ("OK  " if tt else "FAIL", tt.group(1) if tt else "(none)"))
    if not tt:
        fails.append(("title", "missing"))

    print("-- E audio: length, non-silent head, sync " + "-" * 35)
    os.makedirs(a.tmp, exist_ok=True)
    wav = os.path.join(a.tmp, "verify_short.wav")
    ff(["-y", "-v", "error", "-i", a.mp4, "-vn", "-c:a", "pcm_s16le", wav])
    w = wave.open(wav, "rb")
    n, sr = w.getnframes(), w.getframerate()
    ch = w.getnchannels()
    pcm = np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float64)
    w.close()
    a_mono = (pcm.reshape(-1, ch).mean(axis=1) if ch > 1 else pcm) / 32768.0

    def rms(x):
        return float(np.sqrt(np.mean(x.astype(np.float64) ** 2))) if len(x) else 0.0

    head_r, mid_r, tail_r = rms(a_mono[:6000]), rms(a_mono[n // 2:n // 2 + 6000]), rms(a_mono[-6000:])
    ok = abs(n / float(sr) - NT) < 0.05
    print("  %s  %-14s %d frames = %.3f s  rms head %.4f / mid %.4f / tail %.4f"
          % ("OK  " if ok else "FAIL", "audio track", n, n / float(sr), head_r, mid_r, tail_r))
    if not ok:
        fails.append(("audio len", n))
    ok = head_r > 0.02
    print("  %s  %-14s rms %.4f > 0.02 (the window must opens on a musical attack)"
          % ("OK  " if ok else "FAIL", "audible head", head_r))
    if not ok:
        fails.append(("audio head silent", head_r))

    if os.path.exists(a.song8k):
        raw = os.path.join(a.tmp, "verify_short_8k.raw")
        ff(["-y", "-v", "error", "-i", a.mp4, "-vn", "-ac", "1", "-ar", "8000", "-f", "s16le", raw])
        mine = np.fromfile(raw, dtype="<i2").astype(np.float64)
        song = np.fromfile(a.song8k, dtype="<i2").astype(np.float64)
        c0 = int(round(T0 * 8000))
        win = mine[8000:16000]
        best, blag = -1e18, 0
        for lag in range(-1200, 1201):
            seg = song[c0 + 8000 + lag:c0 + 16000 + lag]
            if len(seg) < len(win):
                continue
            v = float(np.dot(win, seg))
            if v > best:
                best, blag = v, lag
        ms = blag / 8.0
        ok = abs(ms) <= 33.0
        print("  %s  %-14s %+.1f ms vs song %.4f s (1 frame = 33.3 ms)"
              % ("OK  " if ok else "FAIL", "A/V sync", ms, T0))
        if not ok:
            fails.append(("av sync", ms))
    else:
        print("  skip A/V sync -- %s not found (decode the source with -ac 1 -ar 8000 -f s16le)" % a.song8k)

    lyn = m.SEG[0].get("lyn") or 0
    if lyn and os.path.exists(a.lrc):
        L = json.load(open(a.lrc, encoding="utf-8"))
        st = L[lyn - 1]
        d = T0 - float(st["t"])
        ok = -0.150 <= d <= 0.150
        print("  %s  %-14s line %d %s  stamp %s  delta %+.3f s (tol +-0.150)"
              % ("OK  " if ok else "FAIL", "LRC start", lyn, st.get("text", "")[:18],
                 st.get("stamp", "?"), d))
        if not ok:
            fails.append(("lrc start", round(d, 3)))

    print("-- F pixels: delivered frame k == module frame k " + "-" * 25)
    tmp = os.path.join(a.tmp, "vs_%05d.raw")
    for k in (0, NFR // 4, NFR // 2, (3 * NFR) // 4, NFR - 1):
        ff(["-y", "-v", "error", "-ss", "%.6f" % (k / FPS), "-i", a.mp4, "-frames:v", "1",
            "-f", "rawvideo", "-pix_fmt", "rgb24", tmp % k])
        got = np.fromfile(tmp % k, dtype=np.uint8)
        if got.size != W * H * 3:
            print("  FAIL  frame %d unreadable (%d bytes)" % (k, got.size))
            fails.append(("pixel", k))
            continue
        got = got.reshape(H, W, 3).astype(np.float32)
        want = np.asarray(m.frame_t(T0 + k / FPS, k=k).convert("RGB"), dtype=np.float32)
        dl = float(np.abs(got - want).mean())
        ok = dl < a.tol
        print("  %s  frame %5d   mean|d| %.3f   max %d"
              % ("OK  " if ok else "FAIL", k, dl, int(np.abs(got - want).max())))
        if not ok:
            fails.append(("pixel", k, round(dl, 3)))
        os.remove(tmp % k)

    ch_path = a.chunks or (os.path.join("out", "chunks_short.json")
                           if os.path.exists(os.path.join("out", "chunks_short.json")) else None)
    if ch_path and os.path.exists(ch_path):
        man = json.load(open(ch_path, encoding="utf-8"))
        bounds = [c["k1"] for c in man[:-1]]
        print("-- F2 seams: %d chunk boundaries, 3 frames each " % len(bounds) + "-" * 22)
        bad = 0
        for b in bounds:
            for k in (b - 1, b, b + 1):
                ff(["-y", "-v", "error", "-ss", "%.6f" % (k / FPS), "-i", a.mp4, "-frames:v", "1",
                    "-f", "rawvideo", "-pix_fmt", "rgb24", tmp % k])
                got = np.fromfile(tmp % k, dtype=np.uint8)
                if got.size != W * H * 3:
                    print("  FAIL  seam %d frame %d unreadable" % (b, k))
                    bad += 1
                    continue
                got = got.reshape(H, W, 3).astype(np.float32)
                want = np.asarray(m.frame_t(T0 + k / FPS, k=k).convert("RGB"), dtype=np.float32)
                dl = float(np.abs(got - want).mean())
                if dl >= a.tol:
                    print("  FAIL  seam %d frame %d mean|d| %.3f  <- stale or dropped chunk" % (b, k, dl))
                    bad += 1
                os.remove(tmp % k)
        if bad:
            fails.append(("seam", bad))
        else:
            print("  OK    %d seams x 3 frames all match frame by frame" % len(bounds))
    else:
        print("-- F2 skipped: no chunk manifest (pass --chunks); a chunked delivery verified without it"
              " is not verified")

    os.makedirs(a.out, exist_ok=True)
    for f in os.listdir(a.out):
        if f.startswith("v_"):
            os.remove(os.path.join(a.out, f))
    ts = [NT * f for f in (0.05, 0.25, 0.45, 0.60, 0.72, 0.82, 0.92, 0.99)]
    for t in ts:
        ff(["-y", "-v", "error", "-ss", "%.3f" % t, "-i", a.mp4, "-frames:v", "1",
            os.path.join(a.out, "v_%06.3f.png" % t)])
    print("-- G extracted %d frames to %s/v_*.png" % (len(ts), a.out))
    print("\nRESULT:", "VERDICT: short delivery OK" if not fails
          else "%d FAILURE(S): %s" % (len(fails), fails))
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
