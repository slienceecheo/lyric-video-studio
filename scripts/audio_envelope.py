# -*- coding: utf-8 -*-
"""Per-frame audio envelope for the renderer.

Usage:
    ffmpeg -v error -i song.m4a -ac 1 -ar 8000 -f s16le -acodec pcm_s16le song_8k.raw
    python audio_envelope.py song_8k.raw T0 FPS N out.json [--smooth 3]

T0 is the song time of frame 0 (the same T0 the film uses), N is the frame
count, so env[k] matches frame k. Values are normalised to max 1.0 and smoothed
over +-smooth frames; the renderer reads ENV = env[k] to drive amplitudes.
"""
import json, struct, sys


def main():
    raw_path, t0, fps, n = sys.argv[1], float(sys.argv[2]), float(sys.argv[3]), int(sys.argv[4])
    out = sys.argv[5] if len(sys.argv) > 5 else "env_full.json"
    smooth = 3
    for a in sys.argv[6:]:
        if a.startswith("--smooth"):
            smooth = int(a.split("=", 1)[1])
    raw = open(raw_path, "rb").read()
    cnt = len(raw) // 2
    v = struct.unpack("<%dh" % cnt, raw[:cnt * 2])
    rate = 8000.0
    per = rate / fps
    env = []
    for k in range(n):
        a = int((t0 + k / fps) * rate)
        b = a + int(per)
        seg = v[a:b]
        s = 0
        for x in seg:
            s += x * x
        env.append((s / max(1, len(seg))) ** 0.5)
    mx = max(env) or 1.0
    env = [e / mx for e in env]
    sm = []
    for i in range(len(env)):
        lo, hi = max(0, i - smooth), min(len(env), i + smooth + 1)
        sm.append(sum(env[lo:hi]) / (hi - lo))
    json.dump([round(e, 4) for e in sm], open(out, "w"))
    print("frames %d  mean %.3f  max %.3f  -> %s" % (len(sm), sum(sm) / len(sm), max(sm), out))


if __name__ == "__main__":
    main()
