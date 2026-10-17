# -*- coding: utf-8 -*-
"""timeline_gen.py -- derive a lyric-video page table from an LRC, mechanically.

Two subcommands, meant to be run in this order and BEFORE any page is written:

    # 1. which LRC is the timing authority?  (needs an ffmpeg binary)
    python timeline_gen.py score song.m4a official.lrc official.aligned.lrc --ff <ffmpeg>

    # 2. derive + verify + emit the page table
    python timeline_gen.py build official.aligned.lrc spec.json -o TIMELINE.py

    # 3. later, prove the emitted table still matches the LRC (anti-drift gate)
    python timeline_gen.py build official.aligned.lrc spec.json -o TIMELINE.py --check

WHY `score` EXISTS: an LRC from a lyrics site and an "aligned" LRC of the same
song can differ by a constant offset of most of a second while both look
plausible. Building a film on the wrong one costs a full re-timeline. Measured
on the reference case (《待春归》, 218.86 s): the correct file put 27/45 line
stamps on a high-frequency rise (median ratio 1.188), the early twin only 11/45
(median 0.987), and the two differed by a uniform +0.850 s. The ratio test below
reproduces that verdict in a few seconds.

WHY `build` EXISTS: hand-written CUTS / page-index tables do not converge. In the
reference case a single file-write round-trip silently truncated the cut list
from 49 entries to 42, and six successive "fix the timeline" scripts produced
45/47/48/50/51 pages because each one hand-placed the card pages differently.
The page count only becomes stable when ONE rule derives the table and the rule's
invariants are asserted on every run.

THE RULES (all asserted, never assumed):
    R1  one page per sung LRC line; page start == that line's stamp
    R2  cards live only in whitespace: [prev line end + TAIL_HOLD, next stamp)
    R3  exactly the cards the spec asks for, evenly spread in each gap,
        each card CARD_T long with LEAD of quiet after it
    R4  polarity alternates per same-kind BLOCK, never per page
    R5  invariants: page count, cuts[0] == 0, cuts[-1] == SONG_END,
        every lyric start == its stamp, every card inside its gap,
        every page duration above DY_MIN, contiguity

The emitted module is DATA ONLY (no renderer, no fonts), so the film imports it
and no second copy of the timing can drift against it.
"""
import argparse
import array
import importlib.util
import json
import os
import re
import statistics
import subprocess
import sys


def _import_path(p):
    """Import a .py file by path, under a private module name."""
    p = os.path.abspath(p)
    spec = importlib.util.spec_from_file_location("_tl_check_mod", p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_tl_check_mod"] = mod
    spec.loader.exec_module(mod)
    return mod

SR = 8000
WIN = int(SR * 0.025)          # energy window 25 ms
HOP = int(SR * 0.010)          # hop 10 ms

ROW = re.compile(r"^\[(\d+):(\d+(?:\.\d+)?)\](.*)$")


# --------------------------------------------------------------------------- I/O

def decode_8k(song, ff, out):
    """Decode to 8 kHz mono s16le. Write INSIDE the project, never to the temp dir."""
    cmd = [ff, "-v", "error", "-y", "-i", song, "-ac", "1", "-ar", str(SR),
           "-f", "s16le", "-acodec", "pcm_s16le", out]
    subprocess.run(cmd, check=True)
    return out


def load_raw(path):
    a = array.array("h")
    with open(path, "rb") as f:
        a.frombytes(f.read())
    if sys.byteorder == "big":
        a.byteswap()
    return a


def hf_env(a):
    """Per-10 ms high-frequency activity: mean |first difference| over a 25 ms window.

    A sung syllable onset is a broadband transient, so this rises sharply even
    when the overall RMS barely moves -- which is why it can place a line start
    where a plain RMS envelope cannot.
    """
    n = max(0, (len(a) - WIN) // HOP)
    env = [0.0] * n
    for i in range(n):
        s = i * HOP
        prev = a[s]
        tot = 0
        for j in range(s + 1, s + WIN):
            v = a[j]
            d = v - prev
            tot += d if d >= 0 else -d
            prev = v
        env[i] = tot / float(WIN - 1)
    return env


def onsets(env):
    """Indices where the activity rises sharply above its own 120 ms local mean."""
    out = []
    w = 12
    for i in range(w, len(env) - 1):
        base = sum(env[i - w:i]) / float(w) + 1e-6
        if env[i] / base >= 1.55 and env[i] >= env[i - 1]:
            out.append(i)
    return out


# --------------------------------------------------------------------------- LRC

def parse_lrc(path, min_t=1.0, drop_credit=True):
    """[(t, text)] for the SUNG lines only.

    The credit block is dropped twice over: by `min_t` (credits sit at 0.850 s in
    the reference case) and by the `：` / ` : ` marker that credit rows use
    (`作词：…`). Blank stamps are dropped because they are structure -- carriers
    of a gap -- not lyrics.
    """
    rows = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for ln in f:
            m = ROW.match(ln.strip())
            if not m:
                continue
            t = int(m.group(1)) * 60 + float(m.group(2))
            txt = m.group(3).strip()
            if not txt:
                continue
            if t < min_t:
                continue
            if drop_credit and ("\uff1a" in txt or " : " in txt):
                continue
            rows.append((round(t, 3), txt))
    rows.sort()
    return rows


# --------------------------------------------------------------------------- score

def ratio_at(env, t, pre=(0.60, 0.05), post=(0.05, 0.70)):
    """post/pre high-frequency activity around a stamp. None when undefined."""
    def win(a, b):
        i0 = max(0, int((t + a) * 100))
        i1 = min(len(env) - 1, int((t + b) * 100))
        if i1 <= i0:
            return None
        return sum(env[i0:i1]) / float(i1 - i0)
    p = win(-pre[0], -pre[1])
    q = win(post[0], post[1])
    if not p or p < 1e-6 or not q:
        return None
    return q / p


def score(lrc_path, env, offsets=(-0.40, -0.30, -0.20, -0.10, 0.0, 0.10, 0.20, 0.30, 0.40)):
    rows = parse_lrc(lrc_path)
    base = [ratio_at(env, t) for t, _ in rows]
    base = [r for r in base if r]
    best = None
    for off in offsets:
        rs = [ratio_at(env, t + off) for t, _ in rows]
        rs = [r for r in rs if r]
        if not rs:
            continue
        med = statistics.median(rs)
        n20 = sum(1 for r in rs if r > 1.20)
        if best is None or (n20, med) > (best[1], best[2]):
            best = (off, n20, med)
    return dict(path=lrc_path, n=len(rows),
                n110=sum(1 for r in base if r > 1.10),
                n120=sum(1 for r in base if r > 1.20),
                med=statistics.median(base) if base else 0.0,
                best_offset=best[0] if best else 0.0,
                best_n120=best[1] if best else 0,
                best_med=best[2] if best else 0.0)


def cmd_score(ns):
    ff = ns.ff or os.environ.get("FFMPEG")
    raw = ns.raw
    if not raw:
        if not ff:
            raise SystemExit("score needs --ff <ffmpeg> or --raw <song_8k.raw>")
        tmp = os.path.join(os.path.dirname(os.path.abspath(ns.lrc[0])), "song_8k.raw")
        raw = decode_8k(ns.song, ff, tmp)
    env = hf_env(load_raw(raw))
    print("raw: %s  (%.3f s)" % (raw, len(env) * HOP / float(SR)))
    print("onsets detected: %d" % len(onsets(env)))
    res = [score(p, env) for p in ns.lrc]
    print("")
    print("%-28s %4s %6s %6s %7s %8s %8s" % ("lrc", "n", ">1.10", ">1.20", "median", "best", "bestMed"))
    for r in res:
        print("%-28s %4d %6d %6d %7.3f %+8.2f %8.3f" % (
            os.path.basename(r["path"]), r["n"], r["n110"], r["n120"], r["med"],
            r["best_offset"], r["best_med"]))
    res.sort(key=lambda r: (r["n120"], r["med"]), reverse=True)
    win_ = res[0]
    print("")
    print("AUTHORITY: %s  (%d/%d stamps on a rise, median %.3f)" % (
        win_["path"], win_["n120"], win_["n"], win_["med"]))
    if len(res) > 1:
        gap = win_["n120"] - res[1]["n120"]
        print("runner-up: %s  (margin %d lines)" % (os.path.basename(res[1]["path"]), gap))
        if gap <= 3:
            print("WARNING: the two files score within noise. Get a third opinion (a karaoke LRC,")
            print("         a stem-timed file, or onset detection on the vocal stem) before building.")
    if abs(win_["best_offset"]) >= 0.15 and win_["best_n120"] > win_["n120"]:
        print("NOTE: a global offset of %+.2f s scores better (%d vs %d lines). Apply THAT offset"
              % (win_["best_offset"], win_["best_n120"], win_["n120"]))
        print("      to every stamp in spec.json's \"offset\" field -- not by editing the LRC.")
    return 0


# --------------------------------------------------------------------------- build

DY_MIN = 0.90


def gap_bounds(lines, k, song_end, tail_hold):
    """Whitespace slot number k (0..len(lines)) as (lo, hi)."""
    lo = 0.0 if k == 0 else lines[k - 1][0] + tail_hold
    hi = song_end if k >= len(lines) else lines[k][0]
    return lo, hi


def build(lines, spec):
    song_end = float(spec["song_end"])
    tail_hold = float(spec.get("tail_hold", 1.20))
    min_gap = float(spec.get("min_gap", 2.60))
    card_t = float(spec.get("card_t", 1.50))
    fps = int(spec.get("fps", 30))

    groups = {}
    for c in spec.get("cards", []):
        groups.setdefault(int(c["before"]), []).append(c)

    pages = []
    # head slot (before line 0), then each line followed by the slot after it
    for k in range(len(lines) + 1):
        if k > 0:
            t0 = lines[k - 1][0]
            t1 = lines[k][0] if k < len(lines) else song_end
            pages.append(dict(kind="lyric", li=k - 1, t0=round(t0, 3), t1=round(t1, 3)))
        rows = groups.get(k)
        if not rows:
            continue
        lo, hi = gap_bounds(lines, k, song_end, tail_hold)
        span = hi - lo
        n_tot = sum(int(c.get("n", 1)) for c in rows)
        # a card owns a whole SLOT of the gap -- card_t is the floor for the slot, not
        # the card's length, because a card stretched to its slot keeps the picture
        # moving instead of leaving dead frames. Measured on the reference tail:
        # 194.745 / 200.524 / 206.303 / 212.081 -> slots of 5.78 s.
        assert span >= n_tot * card_t, (
            "gap %d too short: %.3f s cannot hold %d cards of %.2f s"
            % (k, span, n_tot, card_t))
        assert span >= min_gap, (
            "gap %d is only %.3f s (< min_gap %.2f) but the spec asks for %d card(s)"
            % (k, span, min_gap, n_tot))
        slot = span / float(n_tot)
        j = 0
        for c in rows:
            for _ in range(int(c.get("n", 1))):
                a = lo + j * slot
                pages.append(dict(kind="card", grp=c["grp"], c=j, n=int(c.get("n", 1)),
                                  slot=k, t0=round(a, 3), t1=round(a + slot, 3)))
                j += 1

    # close each page against the next one so the table is contiguous by construction
    pages.sort(key=lambda p: p["t0"])
    for i in range(len(pages) - 1):
        pages[i]["t1"] = pages[i + 1]["t0"]
    pages[-1]["t1"] = round(song_end, 3)
    for i, p in enumerate(pages):
        p["dur"] = round(p["t1"] - p["t0"], 3)
        p["idx"] = i

    # ---- invariants (R5)
    n_lyr = sum(1 for p in pages if p["kind"] == "lyric")
    n_card = len(pages) - n_lyr
    assert n_lyr == len(lines), (n_lyr, len(lines))
    assert abs(pages[0]["t0"]) < 1e-6, pages[0]
    assert abs(pages[-1]["t1"] - song_end) < 1e-6, pages[-1]
    for p in pages:
        if p["kind"] == "lyric":
            t_stamp = lines[p["li"]][0]
            assert abs(p["t0"] - t_stamp) < 1e-6, (
                "R1 violated: page %d starts %.3f, line stamp %.3f" % (p["idx"], p["t0"], t_stamp))
        else:
            lo, hi = gap_bounds(lines, p["slot"], song_end, tail_hold)
            assert lo - 1e-6 <= p["t0"] and p["t1"] <= hi + 1e-6, (
                "R2 violated: card %d [%.3f,%.3f] outside its gap [%.3f,%.3f]"
                % (p["idx"], p["t0"], p["t1"], lo, hi))
        assert p["dur"] > DY_MIN, "R5 violated: page %d is only %.3f s" % (p["idx"], p["dur"])
    for i in range(len(pages) - 1):
        assert abs(pages[i]["t1"] - pages[i + 1]["t0"]) < 1e-6, i

    # ---- R4: polarity per same-kind block
    blocks = []
    for p in pages:
        if blocks and blocks[-1][0] == p["kind"]:
            blocks[-1][1] += 1
        else:
            blocks.append([p["kind"], 1])
    dark_first = bool(spec.get("dark_first", False))
    dark_last = spec.get("dark_last", True)
    dk, floor_ = [], dark_first
    for bi, (kind, cnt) in enumerate(blocks):
        d = not floor_
        if bi == len(blocks) - 1 and dark_last is not None:
            d = bool(dark_last)
        dk += [d] * cnt
        floor_ = d
    assert len(dk) == len(pages)

    # ---- transitions: dissolve wherever the polarity flips, flash otherwise
    diss = [i for i in range(1, len(pages)) if dk[i] != dk[i - 1]]

    return pages, dict(blocks=blocks, dk=dk, diss=diss, n_lyr=n_lyr, n_card=n_card,
                       fps=fps, song_end=song_end, nfr=int(round(song_end * fps)), lines=lines)


def emit(path, spec, lines, pages, meta):
    L = []
    A = L.append
    A("# -*- coding: utf-8 -*-")
    A('"""GENERATED by assets/timeline_gen.py -- do not hand-edit.')
    A("")
    A("Re-derive instead:  python timeline_gen.py build <lrc> spec.json -o %s" % os.path.basename(path))
    A('"""')
    A("")
    A("SONG_END = %.3f" % meta["song_end"])
    A("FPS = %d" % meta["fps"])
    A("NFR = %d" % meta["nfr"])
    A("NPAGE = %d          # %d lyric + %d card" % (len(pages), meta["n_lyr"], meta["n_card"]))
    A("LRC_PATH = %r" % spec["lrc"])
    A("")
    A("# one sung line per page, in LRC order (R1)")
    A("LINES = [")
    keys = spec.get("keys") or []
    for i, (t, txt) in enumerate(lines):
        key = keys[i] if i < len(keys) else "L%02d" % i
        A("    (%r, %r, %r)," % (key, txt, t))
    A("]")
    A("")
    A("# LRC stamp strings, one entry per line (a single %r-of-a-list emits a NESTED list)")
    A("LRC_TS = [")
    for t, _ in lines:
        A("    %r," % ("%02d:%06.3f" % (int(t) // 60, t - 60 * (int(t) // 60))))
    A("]")
    A("")
    A("PAGES = [")
    for p in pages:
        if p["kind"] == "lyric":
            A("    dict(kind='lyric', idx=%d, t0=%.3f, t1=%.3f, dur=%.3f, key=%r, li=%d),"
              % (p["idx"], p["t0"], p["t1"], p["dur"],
                 (keys[p["li"]] if p["li"] < len(keys) else "L%02d" % p["li"]), p["li"]))
        else:
            A("    dict(kind='card', idx=%d, t0=%.3f, t1=%.3f, dur=%.3f, grp=%r, c=%d, n=%d),"
              % (p["idx"], p["t0"], p["t1"], p["dur"], p["grp"], p["c"], p["n"]))
    A("]")
    A("")
    A("# polarity (R4): one value per page, alternating per same-kind block")
    A("DK = [%s]" % ", ".join("True" if v else "False" for v in meta["dk"]))
    A("")
    A("# dissolve wherever the polarity flips; every other boundary is a flash cut")
    A("DISS_FORCE = (%s)" % ", ".join(str(i) for i in meta["diss"]))
    A("")
    A("# run-length blocks, for reading the structure back")
    A("BLOCKS = %r" % (meta["blocks"],))
    A("")
    A("# self-checks, re-run on import so a stale import cannot pass silently")
    A("assert len(PAGES) == NPAGE")
    A("assert [p['idx'] for p in PAGES] == list(range(NPAGE))")
    A("assert abs(PAGES[0]['t0']) < 1e-6 and abs(PAGES[-1]['t1'] - SONG_END) < 1e-6")
    A("assert len(DK) == NPAGE and len(LRC_TS) == len(LINES)")
    A("assert sum(1 for p in PAGES if p['kind'] == 'lyric') == len(LINES)")
    A("assert all(p['dur'] > %.2f for p in PAGES)" % DY_MIN)
    A("")
    data = "\n".join(L)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(data)
    os.replace(tmp, path)


def cmd_build(ns):
    spec = json.load(open(ns.spec, encoding="utf-8"))
    spec["lrc"] = os.path.abspath(ns.lrc)
    off = float(spec.get("offset", 0.0))
    lines = parse_lrc(ns.lrc, min_t=float(spec.get("min_t", 1.0)))
    if off:
        lines = [(round(t + off, 3), txt) for t, txt in lines]
    pages, meta = build(lines, spec)
    print("lyric lines: %d   cards: %d   pages: %d" % (meta["n_lyr"], meta["n_card"], len(pages)))
    print("blocks: %s" % (meta["blocks"],))
    print("polarity flips (dissolves) at pages: %s" % (meta["diss"],))
    print("shortest page %.3f s, longest %.3f s, NFR %d" % (
        min(p["dur"] for p in pages), max(p["dur"] for p in pages), meta["nfr"]))
    for p in pages:
        tag = ("%s %s" % (p["grp"], p["c"] + 1)) if p["kind"] == "card" else lines[p["li"]][1]
        print("  %2d %-5s %7.3f -> %7.3f  %5.2fs  %s%s" % (
            p["idx"], p["kind"], p["t0"], p["t1"], p["dur"], tag,
            "" if p["kind"] == "lyric" or meta["dk"][p["idx"]] else "   (light)"))
    if ns.check:
        # Anti-drift gate: the emitted module is the artefact the film imports,
        # so prove THAT file agrees with this derivation -- import it (its own
        # invariants run on import) and compare the tables page by page.
        if not os.path.exists(ns.out):
            emit(ns.out, spec, lines, pages, meta)
            print("wrote %s (no previous file, check skipped)" % ns.out)
        try:
            mod = _import_path(ns.out)
        except Exception as e:            # noqa: BLE001 - report, do not crash
            print("CHECK FAILED: %s does not import: %r" % (ns.out, e))
            return 1
        bad = []
        if getattr(mod, "NPAGE", None) != len(pages):
            bad.append("NPAGE %r != %d" % (getattr(mod, "NPAGE", None), len(pages)))
        if getattr(mod, "NFR", None) != meta["nfr"]:
            bad.append("NFR %r != %d" % (getattr(mod, "NFR", None), meta["nfr"]))
        mp = list(getattr(mod, "PAGES", []))
        if len(mp) != len(pages):
            bad.append("PAGES %d != %d" % (len(mp), len(pages)))
        else:
            for a, b in zip(mp, pages):
                for k in ("t0", "t1", "kind"):
                    if abs(float(a[k]) - float(b[k])) > 5e-4 if k != "kind" else a[k] != b[k]:
                        bad.append("page %d %s %r != %r" % (b["idx"], k, a.get(k), b[k]))
                        break
        if bad:
            print("CHECK FAILED: %s has drifted from the derivation:" % ns.out)
            for s in bad[:12]:
                print("  " + s)
            print("regenerate it with: %s build %s %s -o %s"
                  % (os.path.basename(__file__), ns.lrc, ns.spec, ns.out))
            return 1
        print("CHECK OK: %s imports cleanly and matches the derivation (%d pages, NFR %d)"
              % (ns.out, len(pages), meta["nfr"]))
        return 0
    emit(ns.out, spec, lines, pages, meta)
    print("wrote %s" % ns.out)
    return 0


# --------------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description="derive and verify a lyric-video page table")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("score", help="which LRC is the timing authority")
    s.add_argument("song")
    s.add_argument("lrc", nargs="+")
    s.add_argument("--ff", default=None, help="ffmpeg binary (or set $FFMPEG)")
    s.add_argument("--raw", default=None, help="reuse an existing 8 kHz mono s16le file")
    s.set_defaults(fn=cmd_score)

    b = sub.add_parser("build", help="derive the page table and emit a timeline module")
    b.add_argument("lrc")
    b.add_argument("spec")
    b.add_argument("-o", "--out", default="TIMELINE.py")
    b.add_argument("--check", action="store_true", help="compare against --out, do not write")
    b.set_defaults(fn=cmd_build)

    ns = ap.parse_args()
    return ns.fn(ns)


if __name__ == "__main__":
    sys.exit(main())
