# Pipeline detail

Contents: 1 environment probe - 2 assets - 3 style spec - 4 timeline and envelope - 5 render and mux - 6 verification - 7 repair loop.

## 1. Environment probe
Run this before anything else and record the answers in the project README:

```
python -c "import PIL, numpy; print(PIL.__version__, numpy.__version__)"
python -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"   # if installed
where ffmpeg   # often empty on Windows
```
Then locate an ffmpeg binary and pin it, for example `FF = C:/Users/<you>/AppData/Roaming/Python/Python312/site-packages/imageio_ffmpeg/binaries/ffmpeg-win-x86_64-v7.1.exe`. Every ffmpeg call in the project uses that absolute path. Do not write a pipeline that assumes `ffmpeg` resolves.

Fonts must be downloaded once into `<project>/fonts/`. Verify the 2:1 grid property yourself before trusting it, with the measurement in section 3: at size 40, one CJK glyph must advance exactly 40 px and one Latin glyph exactly 20 px. If a font fails this test, it is the wrong face for the code column.

## 2. Assets
- The song: mp3/m4a/flac as downloaded. Keep the original file untouched; mux from it so the audio is never re-encoded twice.
- The LRC: needed for the segment table. If only plain lyrics exist, get the timing from a karaoke LRC or from onset detection on the vocal stem; a segment table with hand-set timings is acceptable when the count of lyric lines matches the bar grid.
- **When more than one LRC exists, decide the timing authority by measurement before anything else** (`assets/timeline_gen.py score`). Two files with identical text can sit most of a second apart; the reference case had a plain `.lrc` exactly 0.850 s early against its aligned twin, and building on the wrong one costs a full re-timeline.

```
# decode once for measurement AND for the envelope (8 kHz mono s16le)
FF -v error -i song.m4a -ac 1 -ar 8000 -f s16le -acodec pcm_s16le song_8k.raw
FF -i song.m4a          # read duration, sample rate, channels, and any leaked tags

# which LRC agrees with the audio?
python timeline_gen.py score song.m4a a.lrc b.lrc --raw song_8k.raw
```
The scorer compares high-frequency activity (mean |first difference| over 25 ms windows) in `t-0.60..t-0.05` against `t+0.05..t+0.70` for every stamp and prints, per file, how many stamps land on a rise and the median ratio, plus the best global offset. Reference verdict: aligned 29/45 stamps > 1.10 (median 1.187), plain 11/45 (median 0.981) -- a 12-line margin. If two candidates score within ~3 lines, do not pick: get a third opinion (a karaoke LRC, a stem-timed file, or onset detection on the vocal stem).
Record the verdict and the losing file's numbers in the project README -- it is the first thing to re-open when someone reports "全片都提前了半秒".
- Optional reference video: run references/forensics.md on it first; it decides the palette, the grid, and whether the type is real text.

## 3. Style spec
Write these down as constants before writing any renderer:
- Palette: the dark background, the light background, two dim greys, one accent. Keep every page inside it.
- Grid: `X0` (left margin), `CELL` (grid step), `COLS`. The reference case: `X0=160, CELL=20, COLS=80`, right edge 1760, CJK step = 2 cells = 40 px, code size 40 px, code line height 1.78.
- Fonts and the ink table. Measure each face once:
```
# advance width per run (CJK vs Latin), and ink extent in em
w = d.textlength(text, font=fnt(k, size))
ink_ext(size, smiley)  # returns (top_em, bottom_em), cached; superset string of real glyphs, ink threshold > 40/255
```
- Motion vocabulary: which decoration reacts to the envelope, which transitions belong to which section.

```
# the ink-extent measurement that layout_audit depends on; repeat per face/size
im = Image.new('L', (1400, 300), 0); d = ImageDraw.Draw(im)
d.text((20, 220), SUPERSET_TEXT, font=f, fill=255, anchor='ls')
mask = im.point(lambda v: 255 if v > 40 else 0)
# then np.nonzero(mask) -> top/bottom relative to the baseline -> divide by size
```

## 4. Timeline and envelope
**Derive the segment table from rules; never hand-author it.** `assets/timeline_gen.py build <lrc> spec.json -o TIMELINE.py` is the working implementation; `assets/timeline_spec_example.json` is the reference case's spec (validated: 45 lines -> 55 pages, flips at 1/16/19/32/33/34/35/51, NFR 6566). Hand-written cut lists do not converge: in the reference project one file-write round-trip silently truncated `CUTS` from 49 entries to 42, and six successive "fix the timeline" scripts produced 45/47/48/50/51 pages because each one hand-placed the card pages differently. The count only became stable when one rule derived the table.

The rule set that worked, and the invariants to assert on every run:
1. one page per SUNG line, `t0` exactly that line's LRC stamp, `t1` from the next stamp;
2. a lyric page keeps `TAIL_HOLD` (~1.2 s) of its line before the whitespace starts;
3. cards live ONLY in whitespace `[prev line end + TAIL_HOLD, next stamp)`; a gap shorter than `MIN_GAP` (~2.6 s) gets none; each card owns a slot of `span / n` in its gap (a card stretched to its slot keeps the picture moving; slots of 1.5 s leave dead frames);
4. polarity (`dark`) alternates per same-kind BLOCK, never per page -- one `_floor` state variable, plus at most ONE forced rule (the last block ends on ink);
5. dissolve exactly where the polarity flips, flash cut everywhere else;
6. assert: page count, `cuts[0] == 0`, `cuts[-1] == song_end`, every lyric start == its stamp, every card inside its gap, every duration above ~0.9 s, and strict contiguity (`cuts[i+1] == pages[i].t1`).

`TIMELINE.py` is DATA ONLY (no fonts, no renderer) so the film imports it and no second copy of the timing can drift; re-run `build ... --check` as a gate before rendering and before delivery. `--check` IMPORTS the emitted module (so its own invariants run) and compares `NPAGE`, `NFR` and every page's `t0/t1/kind` against the fresh derivation, naming the first drifted page and printing the regenerate command; a missing file is written first. Never hand-edit `TIMELINE.py` -- regenerate it.

Cross-check the result against the music: detect onsets on the same 8 kHz signal, take the inter-onset interval histogram, and confirm the section boundaries sit on the detected grid (the reference case resolved to roughly 2 s per lyric line at 122 BPM). A segment table that drifts against the beat is the one error the audience hears immediately. But note the limit: overall RMS cannot distinguish a sung line from an instrumental restatement of the same melody (the 待春归 instrumental after the first chorus is as loud as the singing), so energy only ever CONFIRMS a line's onset -- the LRC stamps decide where pages start.

Build the envelope (`scripts/audio_envelope.py`): per-frame RMS over the decoded 8 kHz PCM, normalised to max 1.0, smoothed over +-3 frames, one value per frame -> `env_full.json`. Then in the renderer, `ENV = ENVS[frame_index]` drives amplitudes, ring radii, bar heights. Without this the visuals feel disconnected from the music even when every page is correct.

Two consumers, one timeline: a vertical short is a WINDOW over the same `TIMELINE.py`, not a second table. Keep one switch (`VWIN = (t0, t1)`, plus an optional `VTAIL` for a closing card) that slices the page list, clips the first and last page bounds to the window, drops a trailing card fragment, and appends its own tail card; then recompute `NPAGE`/`NFR` and assert the window's own start/end. Reusing the table is what keeps the short's cuts on the song's real onsets.


## 5. Render and mux
Single frame first, then parallel:
```
# sanity render of one frame
python -c "import importlib.util; spec=importlib.util.spec_from_file_location('film','film.py'); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); m.frame_t(30.0, k=0).save('preview/one.png')"
```
Parallel rendering uses `multiprocessing.Pool(8)` and MUST sit under `if __name__ == '__main__':` on Windows. Keep the film module loaded once per process (a module-level `load()` with a global cache), and write frames as `out/f%05d.png` with `k = int((t - T0) * FPS)`.
If `Pool` dies with `PermissionError: [WinError 5]` from `multiprocessing/connection.py` (`_winapi.CreateFile`), the sandbox forbids the named pipe that `spawn` needs -- do not retry with a different pool size. Spawn N independent `subprocess.Popen` workers inside `if __name__ == '__main__':`, each rendering its own frame range (`_run.py A B 1 --slice a b`) into the same `out/` with one log per worker, then wait for every return code. Measured: 1265 frames at 1080x1920 in ~2.5 min with 8 subprocess workers; ~8.3 fps with one.

Mux (audio is seeked to T0 so the audio and the frame sequence start together):
```
FF -y -v error -ss 17.934 -i song.m4a -framerate 30 -i out/f%05d.png \
   -map_metadata -1 -metadata title="<title>" \
   -c:v libx264 -crf 16 -preset medium -pix_fmt yuv420p \
   -c:a aac -b:a 192k -shortest -movflags +faststart out.mp4
```
`-ss <T0>` on the input and a PNG sequence starting at frame 0 means the delivered file runs on its own clock: `mp4_time = song_time - T0`. Record that offset in the manifest, or every later complaint about a timestamp will be misread. Reference case: `T0 = 17.934`, 7831 frames, 4:21.03, 1960 kb/s video + 193 kb/s audio.

Envelope for a windowed film (a short): the `T0` you pass `scripts/audio_envelope.py` is the offset INTO THE RAW FILE, not the song time. If the raw was already extracted with `ffmpeg -ss <window>`, frame 0 of that raw is the window's start, so call it with `T0=0`. Passing the song-time start makes the tool index past the end of the buffer and write an all-zero envelope, and `verify_delivery.py` then reports a bogus `-30 frames (-1000.0 ms)` lag and `DELIVERY PROBLEM` on audio that is perfectly aligned. Also: it parses `--smooth=N` only -- a space-separated `--smooth 3` raises `IndexError` at `audio_envelope.py:21`.

For a long song (or a repair loop) render in chunks instead -- `references/assembly.md`: one canonical partition, `out/chunks.json` written as chunks finish, each chunk encoded with `-g 30 -keyint_min 30` so it starts on an IDR, a stream-copy concat mux, and the integrity layer that prevents the 224-frame shift. Never glob the chunk files.

## 6. Verification (do not skip)
0. **Audit the audit.** `python scripts/layout_audit.py film.py --from-layout --require-deco` when the film computes its own plan, legacy mode otherwise. Then confirm the audit can actually see the thing that was broken: pick the page you know is tightest, print its boxes, and compare with the rendered PNG. Two false greens are on record -- a legacy-field audit against a `layout()`-based renderer, and a text-only audit blind to decorations -- and both reported `0` while the delivered frame had strokes across the headline.
1. `python scripts/layout_audit.py film.py` -> `remaining box collisions: 0` and `out-of-canvas boxes` absent.
2. Transition matrix: `python scripts/transition_matrix.py film.py` -> preview/tr_matrix.png; read it and confirm each of the 6 transitions at q=0.25/0.5/0.75.
3. Contact sheet: one frame per segment (at about p=0.85, the page at its fullest) -> a sheet; read it for rhythm, alignment, and palette drift. A whole-film sheet is the only cheap way to see "polarity flips far too often".
4. Cut strips: for 3-4 shot boundaries, an 8-frame strip across +-0.25 s -> confirms the transition really blends and does not flash the wrong background.
5. mp4 re-extract: pull 5-6 frames out of the DELIVERED file (one per repaired page plus one untouched control) and read them. If an extraction returns nothing, run `scripts/mp4_sanity.py <delivered.mp4>` BEFORE concluding the film is broken -- an empty single-frame grab is usually a probe artifact on a concat mux.
```
FF -y -v error -ss <song_time - T0> -i out.mp4 -frames:v 1 -update 1 preview/check.png
```
6. Tail and head: the first and last 0.5 s should be intentional (fade in/out), and the last frame should not be a half-drawn page.
7. Assembly: `python scripts/verify_assembly.py --film film.py --out out --mp4 out.mp4 --points <pages that move> --chunks out/chunks.json` -> `extra: none`, `missing: none`, `sum == NFR`, every probe point at `offset +0`. `--points` is a comma-separated list of FRAME NUMBERS: generate it from the page table (`f0 + 10` for every page whose `n >= 40`) instead of picking by eye. Read its sensitivity section before believing a `+0` on a near-static page, and when section D flags a boundary whose frame is NOT a page cut, run `scripts/seam_probe.py <mp4> k0 k1` plus `scripts/diff_cell.py kA kB` -- that combination separates a renderer jump from a bad splice in a minute (references/pitfalls.md).
8. Delivery: `python scripts/verify_delivery.py <delivered.mp4> --film film.py --env env_full.json` -> decoded frames == `NFR`, `moov` before `mdat`, no foreign vendor tag, envelope lag 0 frames. For a vertical short use `python scripts/verify_short.py <short.mp4> --mod short.py --chunks out/chunks_short.json --song8k audio/song_8k.raw`, which additionally cross-correlates the delivered track against the source decode, checks a non-silent head, spot-checks pixels against the module frame by frame, and checks all THREE frames around every chunk boundary (a stale chunk passes a spot check and fails a seam check). The practical bundle before handing anything over: layout_audit + lrc_check + verify_assembly + verify_delivery (+ verify_short), all green, all reading the DELIVERED file. Then write `python scripts/delivery_manifest.py --title "<song title>"` so the manifest is generated from what actually shipped.
9. Container: `python scripts/mp4_sanity.py <delivered.mp4>` -> `VERDICT: container OK`. It checks the relations inside `moov` (stts count == stsz count, stsc chunk sums == stsz count, stts total == mdhd duration, every chunk inside `mdat`, payload bytes described <= bytes present) and the video/audio duration difference. Cheap, needs no ffmpeg, and it is the fastest way to tell a broken deliverable from a broken probe.

## 7. Repair loop
When the user reports one bad page: identify the segments, patch the renderer, then re-render only the affected ranges (including the 20 transition-tail frames before each affected segment) with `scripts/rerange.py`, and re-mux. The reference case repaired 5 pages in 798 re-rendered frames, about one minute with 8 processes.

Re-render the CANONICAL chunks the repaired pages touch -- never an arbitrary sub-range. Asking the worker for `render_run.py 4040 4434` yields 4040-4264 + 4264-4434, which is not the partition the mux used (a page spans `ceil((t0-T0)*FPS)` .. `ceil((t1-T0)*FPS)-1`, and a page whose entry transition changed also touches the chunk holding that boundary). Re-render those chunks only, then re-run `verify_assembly.py`. Reference case: 9 page footers + one page graphic + one transition touched 12 of 32 chunks (~2 min) instead of a full re-render (~6.5 min).

## 8. The atmosphere pass (a second delivery of the same film)
A request like 「背景很单调，加点孔明灯/河灯/云」 is not a page fix: it changes every frame of the film, so treat it as a full re-delivery.
1. Implement it as ONE `ambient()` layer drawn after the background and before any text (references/renderer.md section 4b). Anything that lives in the per-page decoration set instead has to fight every page's box budget, and the audit will (correctly) start failing.
2. Re-run the audit: it must still be `0` collisions. An ambient layer with no boxes cannot collide -- if the number moved, the layer was probably drawn as decoration.
3. Render 4-6 pages with `film.py --pages ...` and build a page sheet; look at the fields in motion, not in a still (extract consecutive frames: the ambient layer must not step).
4. `scripts/diff_cell.py kA kB` on two consecutive frames: the delta must stay near the HUD's own level (~0.02). At 0.1+ the atmosphere is flickering and the user will say so.
5. Full re-render, re-mux, then the WHOLE proof bundle again -- a new layer changes pixel values on every frame, so every "verified" verdict from the previous build is stale. Quote the re-run bundle, never the previous one.
6. Re-check the contact sheet for the arc: the fields should build toward the climax (gate the density on progress), not be uniformly busy from the first page.
