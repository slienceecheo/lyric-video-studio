# chunk_manifest.py -- the ONE canonical chunk partition of this film, and out/chunks.json.
#
# Why this file exists: the 224-frame time shift came from muxing a GLOB of out/film_sub_*.mp4
# while the directory still held one chunk from an earlier cut table. The partition is a pure
# function of (nfr, nw, sub) -- nw contiguous runs, each cut into sub-frame chunks -- but the
# chunk spans depend on the driver's arguments, so it is computed here once, written to
# out/chunks.json, and every later step (mux, scripts/verify_assembly.py) must read that file
# instead of globbing. A chunk on disk that is NOT in this list is a defect: delete it.
import json
import os

NW, SUB = 8, 224


def canonical(nfr, nw=NW, sub=SUB):
    """Return [(k0, k1), ...] in render order, covering exactly range(nfr)."""
    spans = []
    step = (nfr + nw - 1) // nw            # run c renders [c*step, min(nfr, (c+1)*step))
    for c in range(nw):
        a = c * step
        b = min(nfr, a + step)
        for s in range(a, b, sub):         # ... cut into sub-frame chunks, last one short
            spans.append((s, min(s + sub, b)))
    return spans


def write(out_dir, nfr, nw=NW, sub=SUB, prefix="film"):
    """Write out_dir/chunks.json (a JSON array of {file, k0, k1}) and return it."""
    rows = [{"file": "%s_sub_%05d.mp4" % (prefix, a), "k0": a, "k1": b}
            for a, b in canonical(nfr, nw, sub)]
    path = os.path.join(out_dir, "chunks.json")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(rows, f, indent=1)
        f.write("\n")
    return path, rows


if __name__ == "__main__":
    import sys
    nfr = int(sys.argv[1]) if len(sys.argv) > 1 else 6733
    prefix = sys.argv[2] if len(sys.argv) > 2 else "film"
    p, rows = write(os.path.join(os.path.dirname(os.path.abspath(__file__)), "out"), nfr,
                    prefix=prefix)
    print("%s  %d chunks  %d frames  first %s  last %s"
          % (p, len(rows), sum(r["k1"] - r["k0"] for r in rows), rows[0]["file"], rows[-1]["file"]))
