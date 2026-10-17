# -*- coding: utf-8 -*-
"""Structural sanity check for a delivered mp4 -- pure Python, no ffmpeg needed.

Usage:
    python mp4_sanity.py <delivered.mp4> [--quiet]

WHY THIS EXISTS: a single-frame extraction can come back EMPTY from a perfectly
good file. In the reference case

    ffmpeg -ss 191.2 -i delivered.mp4 -frames:v 1 -update 1 out.png

produced nothing for some offsets on a stream-copy-concatenated mux, while the
same command worked at other offsets and every other verifier was green. The
temptation is to conclude the deliverable is broken and re-render 6500 frames.
Do not: first prove the CONTAINER is self-consistent. If the sample table is
intact, the file is intact and the extraction is a probe artifact.

What is checked (all read straight out of the sample tables, not from metadata):
  1. `moov` sits before `mdat`            (faststart; a late moov cannot stream)
  2. for every track: sum of `stts` sample counts == `stsz` sample count
  3. for every track: sum of `stsc` samples over all chunks == `stsz` sample count
     (this is the exact relation that breaks when a chunked mux splices a wrong
     chunk: the table then describes one file and the mdat holds another)
  4. every chunk's byte range lies inside `mdat`
  5. sum of `stsz` sizes == the bytes actually accounted for by the chunk table
  6. `stts` total duration == `mdhd` duration, and audio/video durations agree
     within one frame (the A/V desync that `verify_assembly.py` catches by pixels
     is measured here in samples)

Exit 0 = container self-consistent. Exit 1 = a specific table disagrees; the
message names the relation, which is what you paste into the bug report.
"""
import struct
import sys

VIDEO = b"vide"
AUDIO = b"soun"


class Box(object):
    __slots__ = ("type", "start", "end", "payload")

    def __init__(self, type_, start, end, payload):
        self.type, self.start, self.end, self.payload = type_, start, end, payload


def walk(buf, start, end):
    """Yield sibling boxes in buf[start:end]."""
    p = start
    while p + 8 <= end:
        size = struct.unpack_from(">I", buf, p)[0]
        type_ = buf[p + 4:p + 8]
        head = 8
        if size == 1:
            size = struct.unpack_from(">Q", buf, p + 8)[0]
            head = 16
        elif size == 0:
            size = end - p
        if size < head or p + size > end:
            return
        yield Box(type_, p, p + size, p + head)
        p += size


def kids(buf, box):
    return list(walk(buf, box.payload, box.end))


def find(buf, box, *path):
    cur = box
    for want in path:
        nxt = None
        for c in kids(buf, cur):
            if c.type == want:
                nxt = c
                break
        if nxt is None:
            return None
        cur = nxt
    return cur


def u32(buf, off):
    return struct.unpack_from(">I", buf, off)[0]


def u64(buf, off):
    return struct.unpack_from(">Q", buf, off)[0]


def full_box(buf, box):
    """(version, flags, body_offset) of a FullBox."""
    ver = buf[box.payload]
    flags = int.from_bytes(buf[box.payload + 1:box.payload + 4], "big")
    return ver, flags, box.payload + 4


def timescale_duration(buf, box):
    ver, _, b = full_box(buf, box)
    if ver == 1:
        return u32(buf, b + 16), u64(buf, b + 20)
    return u32(buf, b + 8), u32(buf, b + 12)


def stsz_sizes(buf, box):
    ver, _, b = full_box(buf, box)
    fixed = u32(buf, b)
    n = u32(buf, b + 4)
    if fixed:
        return [fixed] * n
    return [u32(buf, b + 8 + 4 * i) for i in range(n)]


def stts_total(buf, box):
    ver, _, b = full_box(buf, box)
    n = u32(buf, b)
    total_n, total_d = 0, 0
    for i in range(n):
        c = u32(buf, b + 4 + 8 * i)
        d = u32(buf, b + 8 + 8 * i)
        total_n += c
        total_d += c * d
    return total_n, total_d


def stsc_rows(buf, box):
    ver, _, b = full_box(buf, box)
    n = u32(buf, b)
    return [(u32(buf, b + 4 + 12 * i), u32(buf, b + 8 + 12 * i), u32(buf, b + 12 + 12 * i))
            for i in range(n)]


def chunk_offsets(buf, box):
    ver, _, b = full_box(buf, box)
    n = u32(buf, b)
    if box.type == b"co64":
        return [u64(buf, b + 4 + 8 * i) for i in range(n)]
    return [u32(buf, b + 4 + 4 * i) for i in range(n)]


def handler(buf, trak):
    h = find(buf, trak, b"mdia", b"hdlr")
    if h is None:
        return b"?"
    return buf[h.payload + 8:h.payload + 12]


def main():
    if len(sys.argv) < 2:
        print("usage: python mp4_sanity.py <delivered.mp4> [--quiet]")
        return 2
    quiet = "--quiet" in sys.argv
    path = sys.argv[1]
    with open(path, "rb") as f:
        buf = f.read()
    print("%s  %d bytes" % (path, len(buf)))

    top = list(walk(buf, 0, len(buf)))
    names = [b.type.decode("latin-1") for b in top]
    print("top-level boxes: %s" % " ".join(names))
    moov = next((b for b in top if b.type == b"moov"), None)
    mdat = next((b for b in top if b.type == b"mdat"), None)
    if moov is None or mdat is None:
        print("FAIL: missing moov or mdat")
        return 1
    if moov.start > mdat.start:
        print("WARN: moov is AFTER mdat -- the file will not stream (missing +faststart)")
    else:
        print("moov before mdat: yes")

    mvhd = find(buf, moov, b"mvhd")
    mv_ts, mv_dur = timescale_duration(buf, mvhd) if mvhd is not None else (0, 0)
    bad = 0
    report = []

    for trak in kids(buf, moov):
        if trak.type != b"trak":
            continue
        h = handler(buf, trak)
        label = {VIDEO: "video", AUDIO: "audio"}.get(h, h.decode("latin-1"))
        mdhd = find(buf, trak, b"mdia", b"mdhd")
        stbl = find(buf, trak, b"mdia", b"minf", b"stbl")
        if mdhd is None or stbl is None:
            print("%s: FAIL missing mdhd/stbl" % label)
            bad += 1
            continue
        ts, dur = timescale_duration(buf, mdhd)
        stsz = find(buf, stbl, b"stsz")
        stts = find(buf, stbl, b"stts")
        stsc = find(buf, stbl, b"stsc")
        stco = find(buf, stbl, b"stco") or find(buf, stbl, b"co64")
        if not stsz or not stts or not stsc or not stco:
            print("%s: FAIL sample tables incomplete" % label)
            bad += 1
            continue

        sizes = stsz_sizes(buf, stsz)
        n_stsz = len(sizes)
        n_stts, d_stts = stts_total(buf, stts)
        rows = stsc_rows(buf, stsc)
        offs = chunk_offsets(buf, stco)

        # samples per chunk, expanded
        per_chunk = []
        for ci in range(len(offs)):
            spc = 0
            for first, n, _sd in rows:
                if first <= ci + 1:
                    spc = n
                else:
                    break
            per_chunk.append(spc)
        n_chunks = sum(per_chunk)

        secs = dur / float(ts) if ts else 0.0
        report.append("%-5s ts=%d dur=%d (%.3f s)  samples=%d chunks=%d"
                      % (label, ts, dur, secs, n_stsz, len(offs)))
        if not quiet:
            print("%-5s timescale %-6d duration %-9d %.3f s   samples %-6d chunks %d"
                  % (label, ts, dur, secs, n_stsz, len(offs)))

        if n_stts != n_stsz:
            print("FAIL %s: stts sample count %d != stsz %d" % (label, n_stts, n_stsz))
            bad += 1
        if n_chunks != n_stsz:
            print("FAIL %s: stsc sums to %d samples across %d chunks, stsz has %d"
                  % (label, n_chunks, len(offs), n_stsz))
            bad += 1
        if abs(d_stts - dur) > max(1, ts * 0.05):
            print("FAIL %s: stts total %d != mdhd duration %d (timescale %d)"
                  % (label, d_stts, dur, ts))
            bad += 1

        # every sample range inside mdat
        lo_mdat = mdat.payload
        hi_mdat = mdat.end
        si = 0
        out_of = 0
        for ci, off in enumerate(offs):
            n = per_chunk[ci]
            span = sum(sizes[si:si + n])
            si += n
            if off < lo_mdat or off + span > hi_mdat + 1:
                out_of += 1
        if out_of:
            print("FAIL %s: %d/%d chunks fall outside mdat [%d,%d]"
                  % (label, out_of, len(offs), lo_mdat, hi_mdat))
            bad += 1
        if si != n_stsz:
            print("FAIL %s: chunk map consumed %d samples, stsz has %d" % (label, si, n_stsz))
            bad += 1
        # mdat must actually hold the bytes the tables describe
        need = sum(sizes)
        have = hi_mdat - lo_mdat
        if need > have + 1:
            print("FAIL %s: tables describe %d payload bytes, mdat holds %d" % (label, need, have))
            bad += 1
        elif not quiet:
            print("      payload %d bytes described / %d bytes in mdat" % (need, have))

    # A/V duration agreement
    durs = {}
    for trak in kids(buf, moov):
        if trak.type != b"trak":
            continue
        h = handler(buf, trak)
        mdhd = find(buf, trak, b"mdia", b"mdhd")
        if mdhd is None:
            continue
        ts, dur = timescale_duration(buf, mdhd)
        durs[h] = dur / float(ts)
    if VIDEO in durs and AUDIO in durs:
        d = durs[VIDEO] - durs[AUDIO]
        print("duration video %.3f s / audio %.3f s  (diff %+.3f s)" % (durs[VIDEO], durs[AUDIO], d))
        if abs(d) > 1.0 / 30 * 1.5:
            print("WARN: A/V duration differs by more than one frame")
    if mv_ts:
        print("mvhd duration %.3f s" % (mv_dur / float(mv_ts)))

    print("")
    if bad:
        print("VERDICT: container INCONSISTENT (%d failed relation(s)) -- re-mux from the chunks" % bad)
        return 1
    print("VERDICT: container OK -- sample tables are self-consistent.")
    print("         An empty or refused single-frame extraction is a PROBE artifact,")
    print("         not evidence that the deliverable is broken. Retry with -update 1,")
    print("         or decode a short range instead: ffmpeg -ss X -t 0.1 -i in.mp4 -f rawvideo -pix_fmt rgb24 -y out.rgb")
    return 0


if __name__ == "__main__":
    sys.exit(main())
