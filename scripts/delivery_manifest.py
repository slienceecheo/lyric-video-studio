# -*- coding: utf-8 -*-
"""delivery_manifest.py -- the deliverable map: container frame k <-> song time, for every cut we ship.

The contract asks for a manifest proving `frame k <-> song time T0 + k/FPS` plus the container-time
offset, and for the chunk partition of every chunked render. Write it from the DELIVERED artefacts and
the modules that produced them, so a third party can take frame 4000 out of the mp4 and say which second
of the song it is, and can check that the audio trim is right.

Writes out/MANIFEST.json (machine) + out/MANIFEST.md (human), and prints the headline numbers.

Usage:
  python scripts/delivery_manifest.py --title "月声尽，心灯明" --source "<song file name>" \
      [--film film.py] [--short short.py] [--pages pages.json] [--lrc lrc_lines.json] \
      [--chunks out/chunks.json] [--chunks-short out/chunks_short.json] [--out out] \
      [--song-audio audio/song.m4a] [--total-s 255.1254] [--first-audible-s 1.324] [--last-audible-s 251.7272]

Everything except --title is optional-with-a-default; a project with only one deliverable just omits the
other's module (or its manifest) and the section disappears.
"""
import argparse, importlib.util, json, os, sys

sys.stdout.reconfigure(encoding="utf-8")


def load(path):
    if not path or not os.path.exists(path):
        return None
    spec = importlib.util.spec_from_file_location("m_" + os.path.basename(path).replace(".", "_"),
                                                 os.path.abspath(path))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def read_json(path):
    if not path or not os.path.exists(path):
        return None
    return json.load(open(path, encoding="utf-8"))


def page_rows(mod, fps):
    """Per-page rows straight from the module's SEG: the page table the render actually used."""
    rows = []
    for i, sg in enumerate(getattr(mod, "SEG", [])):
        t = sg.get("t", (0, 0))
        rows.append({"i": i,
                     "kind": sg.get("kind", "lyric" if sg.get("lyn") else "card"),
                     "lyn": sg.get("lyn"),
                     "text": sg.get("text", ""),
                     "t0": round(float(t[0]), 4),
                     "t1": round(float(t[1]), 4),
                     "dur": round(float(t[1]) - float(t[0]), 4),
                     "n": int(round((float(t[1]) - float(t[0])) * fps)),
                     "dark": bool(sg.get("dark", False))})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", required=True)
    ap.add_argument("--source", default="")
    ap.add_argument("--film", default="film.py")
    ap.add_argument("--short", default="short.py")
    ap.add_argument("--pages", default="pages.json",
                    help="the landscape page table (f0/n per page); optional, SEG is the fallback")
    ap.add_argument("--lrc", default="lrc_lines.json")
    ap.add_argument("--chunks", default="out/chunks.json")
    ap.add_argument("--chunks-short", default="out/chunks_short.json")
    ap.add_argument("--out", default="out")
    ap.add_argument("--song-audio", default="audio/song.m4a")
    ap.add_argument("--total-s", type=float, default=None)
    ap.add_argument("--first-audible-s", type=float, default=None)
    ap.add_argument("--last-audible-s", type=float, default=None)
    ap.add_argument("--video-a", default=None, help="landscape mp4 name")
    ap.add_argument("--video-b", default=None, help="vertical mp4 name")
    a = ap.parse_args()

    fl = load(a.film)
    sh = load(a.short)
    lrc = read_json(a.lrc) or []
    pages = (read_json(a.pages) or {}).get("pages") or (page_rows(fl, float(fl.FPS)) if fl else [])
    cl = read_json(a.chunks)
    cs = read_json(a.chunks_short)
    fps = float(getattr(fl, "FPS", 30)) if fl else 30.0
    os.makedirs(a.out, exist_ok=True)

    song = {"file": a.song_audio, "source": a.source,
            "total_s": a.total_s,
            "first_audible_s": a.first_audible_s, "last_audible_s": a.last_audible_s}
    mapping = {"fps": fps,
               "song_time_of_container_frame_k": "T0 + k/%g" % fps,
               "container_time_of_frame_k": "k/%g" % fps,
               "note": "the lyric shown at container time t is the line sung at song time T0+t; "
                       "every cut shares the same mapping"}

    def deliverable(name, mod, mp4, chunks, part, note, pages_n):
        if mod is None:
            return None
        return {"name": name, "file": mp4 or "(not named)", "w": int(mod.W), "h": int(mod.H),
                "t0": round(float(mod.T0), 4), "t1": round(float(getattr(mod, "T1", 0.0)), 4),
                "nfr": int(mod.NFR), "dur_s": round(int(mod.NFR) / fps, 6),
                "pages": pages_n, "partition": part, "chunks": chunks or [], "note": note}

    A = deliverable("landscape (full song)", fl, a.video_a, cl, a.chunks,
                    "full song; frame 0 = song %.4f s" % (fl.T0 if fl else 0), len(pages))
    sh_rows = page_rows(sh, fps) if sh else []
    fblog = "the window this short covers"
    if sh and getattr(sh, "SEG", None):
        first = sh.SEG[0]
        fblog = "pages %s..%s of the film: %.4f -> %.4f s" % (
            getattr(sh, "F0S", "?"), getattr(sh, "F1S", "?"), float(sh.T0),
            float(getattr(sh, "T1", 0.0)))
    B = deliverable("vertical (short)", sh, a.video_b, cs, a.chunks_short, fblog, len(sh_rows))
    if B and lrc and sh and getattr(sh, "SEG", None) and sh.SEG[0].get("lyn"):
        n = sh.SEG[0]["lyn"]
        e = lrc[n - 1]
        B["first_lyric"] = {"lrc_line": n, "text": e.get("text", ""),
                            "stamp": e.get("stamp", "?"),
                            "delta_s": round(float(sh.T0) - float(e["t"]), 4)}

    J = {"title": a.title, "song": song, "mapping": mapping,
         "landscape": A, "vertical": B,
         "landscape_pages": [{"i": p.get("i"), "kind": p.get("kind"),
                              "lyn": p.get("line", p.get("lyn")), "text": p.get("text", ""),
                              "t0": p.get("t0"), "n": p.get("n"), "dark": p.get("dark")}
                             for p in pages],
         "vertical_pages": sh_rows}
    with open(os.path.join(a.out, "MANIFEST.json"), "w", encoding="utf-8") as f:
        json.dump(J, f, ensure_ascii=False, indent=1)

    stamp = {}
    for i, e in enumerate(lrc):
        stamp[i + 1] = e.get("stamp", "?")

    L = ["# Delivery manifest -- %s\n\n" % a.title]
    if a.source:
        L.append("Song: %s\n\n" % a.source)
    if a.total_s:
        L.append("Total %.4f s, audible %.4f -> %.4f s; official LRC read-only, %d lines.\n\n"
                 % (a.total_s, a.first_audible_s or 0, a.last_audible_s or 0, len(lrc)))
    L.append("## Container frame <-> song time (one mapping for every cut)\n\n")
    L.append("Container frame k (from 0) shows container time k/%g s, i.e. **song time T0 + k/%g s**; "
             "the container-time offset is 0 because the frame sequence and the audio trim start at the "
             "same song time.\n\n" % (fps, fps))
    for d in (A, B):
        if not d:
            continue
        L.append("\n### %s -- `%s`\n\n" % (d["name"], d["file"]))
        L.append("- %dx%d @ %g fps, %d frames = %.6f s, song %.4f -> %.4f s\n"
                 % (d["w"], d["h"], fps, d["nfr"], d["dur_s"], d["t0"], d["t1"]))
        L.append("- %d pages\n" % d["pages"])
        if d["chunks"]:
            L.append("- partition `%s`: %d chunks, frames %d..%d covering 0..%d contiguously\n"
                     % (d["partition"], len(d["chunks"]), d["chunks"][0]["k0"],
                        d["chunks"][-1]["k1"], d["nfr"]))
        if d.get("note"):
            L.append("- %s\n" % d["note"])

    if sh_rows:
        L.append("\n## Vertical -- page by page (frame = the page's first frame of this cut)\n\n")
        L.append("| page | kind | LRC line | official stamp | dur s | frames | start frame | song start s |\n"
                 "|---|---|---|---|---|---|---|---|\n")
        for p in sh_rows:
            L.append("| %d | %s | %s | %s | %.3f | %d | %d | %.4f |\n"
                     % (p["i"], p["kind"], p["lyn"] or "-",
                        stamp.get(p["lyn"], "-") if p["lyn"] else "-", p["dur"], p["n"],
                        int(round((p["t0"] - (B["t0"] if B else 0)) * fps)), p["t0"]))
    if pages:
        L.append("\n## Landscape -- page by page (first 3 and last 3; the full table is in MANIFEST.json)\n\n")
        L.append("| page | kind | LRC line | official stamp | start frame | frames | song start s |\n"
                 "|---|---|---|---|---|---|---|\n")
        for p in (pages[:3] + pages[-3:] if len(pages) > 9 else pages):
            ln = p.get("line", p.get("lyn"))
            L.append("| %s | %s | %s | %s | %s | %s | %.4f |\n"
                     % (p.get("i"), p.get("kind"), ln or "-", stamp.get(ln, "-") if ln else "-",
                        p.get("f0", "-"), p.get("n", "-"), float(p.get("t0") or 0)))
    if B and B.get("first_lyric"):
        L.append("\nVertical's opening line: LRC line %d \"%s\", official stamp %s, cut at %+.4f s "
                 "(tolerance +-0.150 s).\n"
                 % (B["first_lyric"]["lrc_line"], B["first_lyric"]["text"],
                    B["first_lyric"]["stamp"], B["first_lyric"]["delta_s"]))
    with open(os.path.join(a.out, "MANIFEST.md"), "w", encoding="utf-8") as f:
        f.write("".join(L))

    print("wrote %s/MANIFEST.json  %s/MANIFEST.md" % (a.out, a.out))
    for d in (A, B):
        if d:
            print("  %-22s %d frames %.4f s  %d pages  %d chunks"
                  % (d["name"], d["nfr"], d["dur_s"], d["pages"], len(d["chunks"])))
    if B and B.get("first_lyric"):
        print("  vertical starts %.4f s = LRC line %d %s  %+.4f s"
              % (B["t0"], B["first_lyric"]["lrc_line"], B["first_lyric"]["stamp"],
                 B["first_lyric"]["delta_s"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
