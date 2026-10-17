# Assembly: frames -> one delivered file

Contents: 1 two paths - 2 the chunk manifest - 3 integrity rules - 4 chunk encode - 5 concat mux -
6 verify_assembly.py - 7 selective re-render - 8 the parallel driver - 9 the frame counter.

## 1. Two paths

| Path | When | Shape |
|---|---|---|
| A. single pass | short film, or spare time | PNG sequence -> one x264 pass (`references/pipeline.md` section 5) |
| B. chunked | long song (thousands of frames) or a repair loop | N workers each encode their own chunk, then stream-copy concat |

The reference case (3:44, 6733 frames, 46 pages) used B: 32 chunks across 8 workers, ~5.5 min wall
clock for the whole song, ~2 min for a 12-chunk repair. Path A on the same song is 25-40 min.

Path A cannot produce the failure in section 3. Path B can, and it fails **silently**: no error, no
warning, every individual frame still looks right. Do not use B without the section 3 integrity layer.

## 2. The chunk manifest -- one source of truth, no globs
The driver appends each finished chunk to `out/chunks.json`:

```
[{"file": "film_sub_00000.mp4", "k0": 0,   "k1": 224},
 {"file": "film_sub_00224.mp4", "k0": 224, "k1": 448}, ...]
```

Names are relative to the manifest's OWN directory (`verify_assembly.py` resolves an entry as
`dirname(chunks.json)/file`), so write bare basenames next to `out/`; an absolute path works too.

The mux and every verifier read THAT file, in order. **Never `glob("film_sub_*.mp4")`** -- the
incident below was precisely a stale file that matched the glob.

`assets/chunk_manifest.py` is the shipped implementation of this section: `canonical(nfr, nw=8, sub=224)`
returns the spans the driver must render, and `write(out_dir, nfr, ...)` writes `out/chunks.json` and
returns the rows. Call it when a driver finishes -- the full-film renderer AND whatever re-renders
individual pages -- and call `canonical()` before a repair run to REFUSE a directory holding a chunk
the partition does not contain. That refusal is the cheapest guard there is against the incident below.

## 3. Integrity rules (this is the part that cost a delivery)

**The incident.** Song 3:44, 6733 frames, chunk name `film_sub_%05d.mp4`. After the cut table changed,
the render was redone into the same `out/` directory. One 224-frame chunk from the earlier layout
(`out/film_sub_02240.mp4`) was still on disk. The mux sorted the glob by name and spliced it in
between two current chunks, so everything after it moved 224 frames (7.4 s) later in the picture
while the audio stayed put -- the film was out of sync from 1:15 onward, and nothing complained. It
surfaced only because every page prints its own frame counter: the delivered frame at container
1:39.8 said `F 3971` when it should have said `F 4194`.

1. **One canonical partition.** A single function computes every chunk span from `NFR` and `SUB`, and
   the driver, the mux and the verifier all call it. Never let a chunk span depend on how a work
   range happened to be requested: in the reference case `render_run.py 4040 4434` split into
   4040-4264 + 4264-4434, while the canonical partition had 4040-4210 + 4210-4434 -- same frames,
   different chunk set, one extra file, and the mux would have used both.
2. **`run` boundaries are not chunk boundaries.** A worker handed `[start, end)` renders whole
   `SUB`-sized chunks from `start`; its last chunk is usually short (170 frames in the reference
   case). That is expected and must be reproduced exactly when re-rendering: re-render the canonical
   spans, never an arbitrary sub-range. `verify_assembly.py` asserts the spans are contiguous from 0
   and sum to `NFR`, so a wrong split is caught instead of shipped.
3. **Clear `out/` whenever the cut table, page count or chunk size changes -- but only what a re-render
   regenerates.** `Remove-Item -Path out/*` (Windows: `-LiteralPath "$out\*"` does NOT expand the
   wildcard and errors out). Old chunks are poison, not disk usage. The step is only safe if `out/`
   contains nothing else: **inputs are not output**, so the parsed LRC, the derived page table, the cut
   list and the envelope belong at the PROJECT ROOT (a blanket clear once deleted `out/pages.json` and
   every worker died with `FileNotFoundError` before rendering a frame). Make the clear
   name-pattern-limited anyway, so a stray input file cannot be the thing that breaks the next run:
   ```
   Get-ChildItem -LiteralPath out -Force | Where-Object { $_.Name -match '^(film_|short_|chunks|list\.txt|run\d+\.log)' } | Remove-Item -Recurse -Force
   ```
   Keep the manifests, the trimmed audio and the comparison tables outside that pattern -- they are
   deliverables, not artefacts.
4. **Verify the assembly, not just the pages.** Rendering 46 correct pages is not evidence that the
   6733 frames were concatenated in the right order (section 6).
5. **The end of the film is where a mis-assembly hides.** Check the tail explicitly: the reference
   verifier sampled the last chunks and confirmed the printed counter advanced 6718 -> 6719 -> 6720 ->
   6721 frame by frame.
6. **Never let a verifier guess the chunk set from a directory.** A manifest is the one source of truth;
   glob discovery is a fallback for an existing project only, and it must REFUSE when two files claim
   the same start frame instead of inventing a zero-length span from the collision. In the reference
   project `out/` held a long film's 32 chunks *and* a short film's 4, and the first version of
   `verify_assembly.py` read the short film's files as zero-length chunks of the long one and reported
   an ASSEMBLY PROBLEM that did not exist. Narrow the fallback with `--glob film_sub_*.mp4`.

## 4. Chunk encode
Each worker renders RGB frames for its chunk, writes them to a raw file, and encodes that file:

```
FF -y -v error -f rawvideo -pix_fmt rgb24 -s 1920x1080 -framerate 30 -i chunk.raw \
   -c:v libx264 -crf 16 -preset medium -profile:v high -pix_fmt yuv420p \
   -g 30 -keyint_min 30 -sc_threshold 0 -bf 2 -threads 4 \
   -movflags +faststart out/film_sub_00000.mp4
```

`-g 30 -keyint_min 30` makes every second a keyframe so each chunk starts on an IDR: concat is then a
plain stream copy with no re-encode, and a later single-chunk repair is drop-in. Quoted 30 fps CFR
survives the copy.

**Never move frames through a stdio pipe.** Write the raw file, then encode it (a confined Windows
sandbox denies the named pipe anyway: Node's default `child_process` pipe fails with EPERM, and the
bigger reason is that a pipe gives you no resumable artifact).

## 5. Concat mux
Write the concat list with **absolute** paths (the demuxer resolves relative entries against the LIST
file's directory, which is a silent way to get "Impossible to open ...") and copy the video:

```
FF -y -v error -f concat -safe 0 -i out/list.txt -ss <T0> -i song.m4a \
   -map 0:v:0 -map 1:a:0 -c:v copy -c:a aac -b:a 192k \
   -map_metadata -1 -metadata title="<title>" -movflags +faststart -t <NFR/FPS> out.mp4
```

`-ss <T0>` on the audio input plus a frame sequence that starts at song time `T0` means the delivered
file runs on its own clock: `mp4_time = song_time - T0`. Document it in the manifest (see
`references/pitfalls.md`, mux offset).

## 6. verify_assembly.py -- the check that would have caught it
```
python scripts/verify_assembly.py --film film.py --out out --mp4 out.mp4 \
       [--chunks out/chunks.json] [--glob "film_sub_*.mp4"] [--sub 224] \
       [--points 1000,2240,4194,6200] [--ff <ffmpeg>]
```
Four sections, in increasing cost:

- **A structural** -- manifest vs disk vs canonical partition: `extra`, `missing`, every chunk's decoded
  frame count against its span, spans contiguous from 0, `sum == NFR`. This alone catches the incident
  (33 chunks found where 32 belong, and the sum no longer equals the frame count).
- **B pixel** -- for each `--points` frame k: extract frame `k/30` from the DELIVERED mp4, render candidates
  k-256 .. k+256 (coarse step 16, then fine step 1) and report the offset with the smallest
  mean absolute luma difference. Must be `+0` at every point, otherwise the delivery carries frames the
  renderer would draw elsewhere.
- **C sensitivity** -- what a synthetic +-1, +-5, +-30 frame offset costs at those points, as the
  absolute mean|dL| AND the increment over the best offset. Read it before believing B: the increment is
  the signal, because the H.264 round trip alone contributes ~2.0 to every figure. Reference case at a
  cross-dissolve page: base 1.993, `+-1: +0.513  +-5: +0.928  +-30: +1.523` -> `fair`; at a near-static
  page: `+-1: +0.067` -> `weak (the picture barely moves here)`, so a `+0` there proves little. Pick
  points where the picture moves, and always include the pages you just repaired.
  Generate the points mechanically instead of by eye -- every page table carries `f0` and `n`, so take
  `f0 + 10` (or `+18`, if that lands in the typing phase) for each page with `n >= 40`, which guarantees
  a frame with motion in it. `--points` takes a COMMA-SEPARATED LIST OF FRAME NUMBERS; there is no
  "move-rich" keyword. Then: **if B reports a shift while C calls the same point `weak`, B is a noise
  argmin** -- on a static frame a 1-frame offset costs less than the codec's own error. The signature of
  a real offset is that it repeats at every point inside the same chunk; a noise argmin moves when you
  re-render. Probe the single point against offsets -5..+5 before re-rendering anything.
- **D seams** -- for the first few and last few chunk boundaries, the mean|dL| between the last frame of
  chunk i and the first of chunk i+1, compared with the typical difference between neighbouring frames
  in the same page. A splice that replaces content instead of continuing it reads far above that floor.
  **First ask what frame it is.** If the flagged frame is not a page cut, the boundary is innocent and
  the FILM is jumping there: a renderer event lands on the seam and the check reads it as a splice.
  `scripts/seam_probe.py <mp4> <k0> <k1>` prints the delivered delta and the rendered delta per frame
  side by side (`|mp4-film|` flat = the delivery is faithful, `film dL` spiking = the renderer), and
  `scripts/diff_cell.py <kA> <kB>` shows what moved. Calibration from a real film: page interior
  0.005-0.032 per frame, a page change 0.35+, a quantised position breath 0.36. Fix the renderer,
  re-render, and leave the concat list alone.
  Sensitivity caveat: this section is meaningless on a page that does not move -- a 4-second chord
  pad's boundary really is a low ratio, and a dissolve boundary really is a high one. Read the ratio
  together with the floor.

`-ss k/30` in ffmpeg seeks to the first frame with `PTS >= k/30`, which can be frame k+1; do not build a
sensitivity test on that, use the search in B. (`-update 1` is still needed when writing a single image.)

## 7. Selective re-render (the repair path)
Map the repaired pages to the canonical chunks they touch, re-render those chunks only, and re-run
`verify_assembly.py`. In the reference case, changing 9 page footers + one page's graphic + one
transition touched 12 of 32 chunks (~2 min) instead of a full re-render (~6.5 min). Two rules:

- Compute the affected chunk set from the page frame ranges, never by hand; a page spans `ceil((t0-T0)*FPS)`
  to `ceil((t1-T0)*FPS)-1`.
- A transition belongs to the frames after the boundary, so a page whose *entry* transition changed needs
  its own chunk plus the chunk containing the boundary before it.

## 8. The parallel driver
One Python process, `subprocess.Popen` per worker, one log file per worker, then read the logs:

```
procs = [subprocess.Popen([sys.executable, "-u", "render_run.py", str(a), str(b), mod],
                          cwd=HERE, stdout=open("out/run%d.log" % n, "w"), stderr=subprocess.STDOUT)
         for n, (a, b) in enumerate(spans)]
rc = [p.wait() for p in procs]
```

Do NOT launch the workers from PowerShell with
`Start-Process -ArgumentList (@('-u') + $args)`: the array flattening drops the script name
(`python: can't open file '...\2356'`) and `Wait-Process` then reports access denied. The reference
case burned time on exactly that before moving the orchestration into Python.

## 9. The frame counter is the instrument
Every page prints its own `F <k> / <NFR>` in the footer. It is what made the 224-frame shift provable
from the delivered pixels, and it is what makes `verify_assembly.py` section A falsifiable after a
repair. Keep it in every render, keep it per-frame (a static page number was reported as a defect the
moment it replaced the counter), and quote it when you report a timing finding to the user.
