# Pitfall catalogue

Symptom -> cause -> fix. Every entry here cost real debugging time in the reference project.

## Text collisions (the defect users report first)
Symptom: 字与字相互遮挡 -- the big display headline sits on top of the code block, or a log/table block overlaps the first code line.
Cause A: the display baseline was chosen for its position on the page, not for the content above it.
Cause B: the audit itself is wrong -- a y-only overlap test reports every wide headline as a collision (13 false hits in the reference case), and a 1D audit hides nothing but is unusable; you need a 2D intersection.
Cause C: a secondary block (log lines, table rows) was drawn at a fixed y that happens to equal the code block first baseline.
Fix: content boxes from real measured text (`content_boxes()`), the display box from the real ink extent (`big_box()`), a 2D `_hit()` with an 8 px margin, and a clamp that recomputes the display baseline as `content_bottom + |ink_top_em| * size + 14`. For blocks that follow the code, derive y from the code block bottom: `ly = codey + (len(code)-1)*codeS*lh + codeS*0.42 + 46`, not from a constant.

## Audit integrity (two false greens, both cost a full re-layout)
Symptom: `layout_audit.py` prints `remaining box collisions: 0`, and the rendered page has decoration strokes running across the display text (风线压在「今州风紧」上, 柳枝插进「那日一别」, 山形盖住代码块).
Cause A: the audit measured boxes the renderer does not draw. `scripts/layout_audit.py`'s legacy mode reads the template's SEG fields (`bigS`/`bigy`/`bigx`, `codey`, `capy`, `log`); a film that computes its own plan from a `layout()` function places text somewhere else entirely, so the audit is grading a fiction.
Cause B: **decorations were not in the box set at all.** Text-vs-text-only auditing is blind to the layer that actually covers glyphs; the reference project shipped a "0 collisions" verdict with 25 real decoration collisions behind it.
Cause C: the film's own decoration list was declared honestly but drawn outside its declared rect (a wind sine overshooting by +-0.075 of the band height, willow arcs straying), so even a decoration-aware audit under-reports.
Fix: audit the module's OWN plan (`layout_audit.py --from-layout`, which asks for `layout(d, seg)` and collects `pl["boxes"]` + the `big`/`cap`/`seal` blocks + every `deco_boxes` entry), pass `--require-deco` so a decoration rect with no box fails the run, and check out-of-canvas boxes too. When a decoration's ink genuinely exceeds its declared rect, clip it or inset it at draw time -- do not widen the declared box until the audit agrees.
Lesson: the audit is a second implementation of the layout. Any rewrite of the layout engine must rewrite the audit in the same commit, or the green light means nothing.

Symptom: the layout is provably clean per the audit, but the displayed text and the box still disagree by 5-20 px.
Cause: the box was computed from the font's ascent/descent, or from ink coefficients copied from another project.
Fix: measure per face with a nonzero-pixel bbox and use the GENEROUS extent for collision boxes -- a faint descender is still a collision. Measured on the reference CJK faces (threshold ~0, `im.getbbox()` on glyphs drawn at `anchor='ls'`, sizes 20-48): 霞鹜文楷等宽 top 0.833-0.864 em / bottom 0.206-0.250 em; 得意黑 top 0.895-0.929 / bottom 0.250-0.300; 霞鹜文楷 Light top 0.818-0.850 / bottom 0.125-0.182. The tighter `> 40/255` threshold used elsewhere in this skill reports a bottom around 0.11 em, i.e. **0.14 em optimistic** -- at 38 px that is 5 px of undeclared ink per line, enough to eat the gap between a 5-line panel and the caption.

## Patch-piling instead of reserving geometry
Symptom: the collision count walks 35 -> 25 -> 28 -> 27 -> 17 across a day of edits and never reaches 0; each fix adds a branch to a clamp function.
Cause: every iteration tried to nudge one colliding pair into a legal position while the layout had no reserved space for the second element. A clamp cannot create room.
Fix: give each layout an explicit two-column / banded skeleton, i.e. decide which column the code panel owns and which the display line owns, and make the decoration a band that the text column cannot reach (a top band under the header rule, a bottom band between the caption ink and the footer rule). Then the whole collision family disappears by construction instead of being clamped away. Order of concessions when a page is genuinely too tight: tighten line spacing (down to ~1.16, never stretch), then move the caption to the running-head position, then drop the decoration. Text is mandatory, decoration is bonus.

## Font metrics
Symptom: text drawn with `anchor='ls'` looks 20-40 px too high or low, or a box computed from `getmetrics()` clips glyphs.
Cause: ascent/descent are font-table values, not ink extents, and CJK faces often report a line box far larger than the ink.
Fix: measure the ink once per (face, size) over a superset string of the glyphs you use, cache it, and use it for every box. Measured values for the reference faces (scripts/ink_extent.py, threshold > 40/255 -- "solid ink"): ink top -0.823em (LXGWWenKaiMonoGB-Regular) and -0.891em (SmileySans-Oblique); ink bottom +0.11em and +0.09em; identical at sizes 130 and 190. For COLLISION boxes use the generous extent instead (any non-zero pixel), measured in the 待春归 project: mono 0.842-0.875 / 0.206-0.260 em, 得意黑 0.895-0.940 / 0.250-0.310, 霞鹜文楷 Light 0.818-0.860 / 0.125-0.190. Round the coefficient UP to the next 0.005 so the declared box always contains the ink, and never mix the two conventions in one layout.

## Grid alignment
Symptom: the code column lines up on some rows and drifts on others.
Cause: Latin and CJK advances are being mixed without accounting for the CJK width, or the face is not the Mono variant.
Fix: split every string into runs (`runs()`), measure both runs with `textlength()`, and snap positions with `snap()` / `clen()` (a CJK glyph counts 2 cells). Assert the 2:1 property at startup: at size 40 a CJK glyph advances 40 px and a Latin glyph 20 px.

Symptom: after a refactor the audit suddenly reports every page colliding (0 -> 35), and the collisions look like the layout pass never ran.
Cause: a `return` placed one line too high. The dispatcher was edited to `return _layout_deco(d, sg, True)` ABOVE the function's real body, so the entire post-pass (band solve, caption reflow, display refit, decoration sweep) became dead code -- the function compiled, returned a plausible plan, and skipped everything that made the plan legal.
Fix: after touching a dispatcher or a `layout()` wrapper, re-run the audit AND a smoke render before reading any other result; a plausible-looking return value is not evidence that the body ran.

## Renderer plumbing
Symptom: an old page silently renders wrong after you add a new one.
Cause: `film.py` execs the prefix of `render.py` into its own globals; a new global that reuses an existing name (the reference case: `S` for a font path, later redefined) silently rebinds the old renderer.
Fix: namespaced prefixes for new globals (`S2`, `INK2`, `MM2`), and after a renderer change, re-render one full page of a different kind as a control.

Symptom: `RuntimeError: An attempt has been made to start a new process before the current process has finished its bootstrapping phase`.
Cause: `multiprocessing.Pool` at module import time on Windows (spawn).
Fix: put the parallel block behind `if __name__ == '__main__':`; do the module import and the affected-range computation inside that guard.

## numpy masks in transitions
Symptom: a transition crashes with a broadcast error, or produces stripes instead of a wipe.
Cause: a mask shaped (N,) or (H,1) cannot multiply an (H,W,3) array.
Fix: build every mask at (H,W) explicitly (`np.repeat(mask[:, None], H, axis=1)` for a per-column mask, `mask[None, :]` for per-row), keep the composite in float32, and convert back with explicit rounding before saving. Test all six transitions through `transition_matrix.py` at q=0.25/0.5/0.75 instead of eyeballing one frame.

## ffmpeg
Symptom: a single-frame extraction comes back EMPTY (or `-frames:v 1` writes nothing) from a delivered file that every verifier calls green, and the temptation is to re-render the whole film.
Cause: the extraction is the flaky part, not necessarily the file. On a stream-copy-concatenated mux, seek+single-frame extraction can fail for particular offsets while succeeding at others; and without `-update 1` ffmpeg refuses one image into a path it reads as a sequence.
Fix: prove the CONTAINER first -- `python scripts/mp4_sanity.py <delivered.mp4>` parses `stsz`/`stts`/`stsc`/`stco` straight out of `moov` and checks that the sample tables agree with each other and with `mdat`. A `VERDICT: container OK` means the deliverable is intact and the probe was at fault: retry with `-update 1`, or decode a short range to raw pixels (`-ss X -t 0.1 -f rawvideo -pix_fmt rgb24`) and read that. Only a structural mismatch justifies a re-mux.
Reference case: both delivered films report OK with video/audio durations 42.167/42.188 s and 218.867/218.880 s (a 21 ms container-level A/V difference, sub-frame and harmless).

Symptom: `The specified filename ... does not contain an image sequence pattern` when extracting a single frame.
Cause: ffmpeg refuses to write one image into a path it reads as a sequence.
Fix: add `-update 1`.

Symptom: the delivered mp4 carries someone else's metadata (e.g. a streaming service tag from the source audio).
Cause: muxing copies input metadata.
Fix: `-map_metadata -1` and an explicit `-metadata title=...`.

Symptom: timestamps in a bug report do not match the segment table.
Cause: the deliverable runs on its own clock because the audio was seeked with `-ss T0` while the PNG sequence starts at song time T0.
Fix: document `mp4_time = song_time - T0` in the manifest, and convert before hunting for the frame.

## Disk and time
Symptom: rendering the whole song repeatedly to fix one page takes 20 minutes.
Fix: `rerange.py` -- recompute only the affected segments plus the transition tails, then re-mux. 8 processes render roughly 800 frames a minute.

## Timeline and LRC authority (the sink that costs the most time)
Symptom: the page count will not settle -- successive fix attempts produce 45, 47, 48, 50, 51 pages, and each assertion that fails shows a number you did not expect.
Cause: the cut list was HAND-AUTHORED. A page-index table plus a hand-placed card table means the total is whatever the last edit happened to leave; a single file-write round-trip silently truncated one project's `CUTS` from 49 entries to 42, and six successive "fix the timeline" scripts each hand-placed the card pages differently.
Fix: derive the table from rules and assert the rules' invariants on every run (`assets/timeline_gen.py`). The minimum rule set that worked: one page per SUNG line with `t0` exactly the line's stamp; cards only in whitespace `[prev line end + TAIL_HOLD, next stamp)`, a card owns a whole slot of that gap; polarity alternates per same-kind BLOCK, never per page; then assert page count, `cuts[0] == 0`, `cuts[-1] == song_end`, every lyric start == its stamp, every card inside its gap, every page duration above ~0.9 s, and strict contiguity. Never hand-edit the emitted module -- regenerate it.
Corollary: one page per sung line, never a merged page for a repeated hook. Merging 「小燕子 / 穿花衣 / 年年春天来这里」 into one page violates the contract AND desynchronises the cut from the singing; the reference film gives all three their own page and all three read as one gesture anyway.

Symptom: the whole film is uniformly early or late against the vocal, by a constant you can hear.
Cause: the wrong LRC was treated as the authority. Two files of the same song can carry identical text and differ by a uniform offset -- measured on 「待春归」: the plain `.lrc` was exactly **+0.850 s early** relative to its "aligned" twin, and nothing in either file says so.
Fix: score the candidates against the decoded audio before writing a single page (`assets/timeline_gen.py score`). For every stamp, compare high-frequency activity (mean |first difference| over 25 ms windows) in `t-0.60..t-0.05` against `t+0.05..t+0.70`; the correct file puts most stamps on a rise. Reference verdict: 29/45 stamps above 1.10 with median 1.187 for the aligned file, 11/45 with median 0.981 for the plain one -- a 12-line margin, decided in seconds. Keep the losing file and the comparison table on disk as the record.
Corollary (learned the hard way): overall RMS cannot tell a sung line from an instrumental restatement of the same melody. In 「待春归」 the 25 s instrumental after the first chorus is as loud as the singing, so energy analysis cannot place page starts there -- the LRC stamp grid decides, and energy is only ever used to confirm a line's onset, never to invent one.

## Windows environment
Symptom: every tool call fails with `SetNamedSecurityInfoW failed (Win32 5): grantWrite(...)`.
Cause: the sandbox cannot grant write ACLs on the workspace path (writeOwner missing).
Fix: nothing in the project; ask the user to run the session with full access instead of fighting ACLs.

Symptom: `PermissionError: [WinError 5] 拒绝访问` from `multiprocessing/connection.py` (`_winapi.CreateFile`) via `context.py SimpleQueue` -> `queues.py connection.Pipe`.
Cause: under a Windows file sandbox, `multiprocessing.Pool` cannot create the named pipe that `spawn` needs. This is a sandbox limit, not a bug in the film -- retrying with a bigger pool only fails slower.
Fix: single process, or N independent `subprocess.Popen` workers each rendering its own frame range (`_run.py A B 1 --slice a b`, one log per worker, wait for all return codes). Measured on the 待春归 project: 1265 frames at 1080x1920 in ~2.5 min with 8 subprocess workers, ~8.3 fps with one.
Also: PowerShell has no heredoc. `python - <<'PY'` is not a thing there -- write a scratch `_probe.py` into the project and run it, and set `$env:PYTHONIOENCODING="utf-8"` before any command that prints CJK or the console mangles it.

Symptom: `UnicodeDecodeError: 'gbk' codec can't decode byte 0xae in position 30` from a script that reads the official LRC, or a JSON file that Python wrote and Python can no longer read on the same machine.
Cause: on a zh-CN Windows install the DEFAULT text codec is GBK, not UTF-8 -- so a bare `open(path)` decodes UTF-8 bytes as GBK, and `json.dump(..., open(p, "w"))` writes GBK. (The console codepage is a separate problem: that one only produces mojibake on screen.)
Fix: pass `encoding="utf-8"` on EVERY read and write of text/JSON in the project, `encoding="utf-8-sig"` for a file that may carry a BOM, and `sys.stdout.reconfigure(encoding="utf-8")` at the top of every script that prints CJK. Grep for `open(` without an encoding before blaming the data.

Symptom: `Copy-Item <source> <dest>` returns success and copies NOTHING (or `Get-Item` fails on a file you can see in Explorer).
Cause: the filename contains square brackets -- `《…》…［BV1xxxxxxxxxx］.m4a` -- and PowerShell treats `[` `]` as wildcard character classes, so the pattern matches no file. The source song for a lyric video is very often a downloaded file whose name carries a bracketed video id.
Fix: `-LiteralPath` on every `Copy-Item` / `Get-Item` / `Get-ChildItem` / `Remove-Item` whose path may contain `[` `]`, and verify after the copy (`Get-Item -LiteralPath <dest>` and compare the byte count) instead of trusting the silent success.

## Assembly (long songs, chunked renders)

Symptom: `verify_assembly.py` reports `*** DISCONTINUITY ***` at a chunk boundary while section A is perfect (contiguous, counts match, sum == NFR) and every page still looks right.
Cause: two completely different defects print the same line. (a) The assembly really does splice foreign content (the 224-frame incident below). (b) **The FILM itself jumps on that frame** -- a renderer-side per-frame event (see the motion section: a position breath quantised to whole pixels is the usual culprit) that happens to fall near a chunk boundary. The boundary is then innocent: the seam is loud because the content changed, exactly as the check is designed to notice.
Fix: locate the frame, and ask whether it is a PAGE CUT. If it is not, it is the film. Two tools settle it in a minute:
- `python scripts/seam_probe.py <delivered.mp4> <k0> <k1> [film.py]` -- decodes the delivered frames BY FRAME NUMBER (the `select` filter, never `-ss`, so a seek cannot be blamed) and renders the same frames from the module, printing `mp4 dL / film dL / |mp4-film| / t` per frame. If `film dL` spikes and `|mp4-film|` stays flat, the renderer is at fault and the delivery is faithful.
- `python scripts/diff_cell.py <kA> <kB> [film.py]` -- mean|dL| between two rendered frames plus a per-cell map and the bbox of the changed pixels, written as a contrast-stretched PNG. The bbox tells you WHAT moved: confined to the text column and about one glyph row == the display block stepped; a full-frame box == a transition; a stripe == a decoration.
Re-render after the fix and re-run the whole bundle; do not touch the concat list.

Symptom: section B reports a `SHIFT` (e.g. `-10` or `+30`) at a point where section C says `weak (the picture barely moves here)`, and re-rendering changes the number.
Cause: the section-B argmin is a NOISE argmin. On a near-static page a one-frame shift costs less than the codec's own round-trip error, so the minimum lands wherever the noise puts it.
Fix: pick move-rich points mechanically -- `pages.json` gives every page `f0` and `n`, so use `f0 + 10` (or `+18`) for pages with `n >= 40`, which is inside the typing/entry phase where the picture moves a lot. If a point still reports a shift, probe it before believing it (extract that frame and compare it against offsets -5..+5 by hand); a real offset repeats at every point on the same chunk, a noise argmin does not. Record the points you used in the delivery report, because a `+0` on a static page proves nothing.
Symptom: the delivered film is 7.4 s (224 frames) out of sync from one point on, while every individual page still looks correct.
Cause: a chunked render into a directory that still held one chunk from an earlier cut table; the mux sorted a glob of `film_sub_*.mp4` and spliced the stale 224-frame file between two current chunks.
Fix: one canonical partition function, `out/chunks.json` as the only chunk list, no globs anywhere, and `scripts/verify_assembly.py` before mux (references/assembly.md).

Symptom: `Error opening output C:\Users\<you>\AppData\Local\Temp\...\a.raw: Permission denied` from ffmpeg (exit 4294967283), while the identical command works in a terminal.
Cause: under a file sandbox the child process cannot write the platform temp dir -- and `tempfile.mkdtemp()` picks exactly that path.
Fix: put scratch files inside the project (`<project>/_lvstmp`) and pass that path to every ffmpeg call that writes.

Symptom: `Remove-Item -LiteralPath "$out\*"` fails with "Cannot find path", or old chunk files survive the cleanup.
Cause: `-LiteralPath` does not expand wildcards.
Fix: `Get-ChildItem -LiteralPath $out -Force | Remove-Item -Recurse -Force`.

Symptom: the render dies in under a second on a fresh run -- all N workers return 1 while the previous render of the same code worked --
`FileNotFoundError: [Errno 2] No such file or directory: '...\out\pages.json'`.
Cause: the "clear `out/` before a re-render" step deleted INPUTS. The page table, the parsed LRC and the envelope had been written into `out/` alongside the chunks, so a blanket `Remove-Item -Recurse` removed the thing the renderer imports.
Fix: **inputs are not output** -- the parsed LRC, the derived page table / cut list, the envelope and the ground truth live at the PROJECT ROOT; `out/` holds only artefacts a re-render overwrites. Then make the clear name-pattern-limited rather than blanket:
`Get-ChildItem -LiteralPath out -Force | Where-Object { $_.Name -match '^(film_|short_|chunks|list\.txt|run\d+\.log)' } | Remove-Item -Recurse -Force`.
Keep the manifest, the comparison tables and the trimmed audio out of that pattern -- they are deliverables too.

Symptom: a title reads as mojibake in the PowerShell console (`杩滆埅鏄熺殑鍛婂埆`).
Cause: the console codepage (GBK), not the mux.
Fix: read the tags back from the file (the verifier prints them) and never "fix" a title that was fine.

Symptom: `Could find no file with path 'preview/f%05d.png' and index in the range 0-4`.
Cause: extracted frames were written with non-consecutive names (film frame numbers) into an image2 pattern.
Fix: number the extracted frames 0..n-1 and pass `-start_number 0`.

## Motion
Symptom: a 1.0-1.5 s page reads as a flash -- the line is only fully legible for about half its life.
Cause: one global transition length. A `DISS = 0.36` dissolve on a 1.02 s page (the reference case: 「你说」 at 1.016 s) spends a third of the page fading in.
Fix: make the transition length per page, derived from the page duration: `sg["trd"] = 0.20 if (t1 - t0) < 1.60 else 0.38`, and have `frame_t` read `sg.get("trd", DISS)`. Six pages of the reference film were affected; a short page must not pay a long dissolve.
Symptom: "your animation flickers, it is unpleasant to look at" (闪来闪去，看得眼睛很不好受).
Cause: a binary, event-locked switch that flips several times a second with the music (underline, rulers, tick marks and corner marks all flipping on the same frame).
Fix: continuous channels only -- breathing (a slow sine blended with a smoothed envelope term), a per-page drift, a density swing -- at an amplitude near the edge of perception (1 % of the type size is enough). Never a beat-locked toggle, and delete the code if it was already shipped.

Symptom: the motion is invisible in the film but looks convincing in your numbers, or a measurement contradicts the renderer.
Cause A: the figure averaged the whole page, including the entry animation (staggered line rise + fade) and the typing reveal, which are 30-60x larger than the steady motion.
Cause B: the measuring band clipped the glyphs; a clipped band converts a rigid shift into moving edge rows and under-reports it (0.6 px measured for a 2 px shift).
Fix: measure the steady tail of the page, with a band derived from the measured ink extent plus padding, and cross-check with a sub-pixel row-profile shift (`scripts/motion_probe.py`).

Symptom: `motion_probe.py` reports tens of pixels of p2p and several flicker spikes on a page whose text barely moves.
Cause: the sampled window ran into the transition. A film may pre-roll the next page inside the current page's last moments (`SEG[i]["tr"], SEG[i]["trd"]` -- the shape `assets/film_template.py` uses, `frame_t` blending from `t > b - trd`) or blend after the cut (a `DISS` constant -- the shape the reference project uses). Those frames are not the page at rest: measured on the template, sampling to `k1 - 5` turned an 8 px page drift into a 44 px swing and three spikes.
Fix: the tool derives a lead-in guard from the film (`trd`, else `DISS`/`FLASH`, else 0.4 s), prints the window it used, and takes `--guard` as an override. Read that printed window before believing a large number.

Symptom: the probe flags isolated "sudden jumps" on a page that visibly moves smoothly, while `median|step|` of the centroid is 0.
Cause: `PIL` rasterises text on whole pixels even when the y you pass is a float, so the display line moves in 1 px steps and each step changes every edge pixel of the glyph at once. A sub-pixel amplitude is lost entirely (a 42 px caption breathing +-0.4 px does not move).
Fix: **do not put the breath in position.** Draw the display block at a fixed baseline and breathe in INK DENSITY instead: `fill = mix(fill, bg_col(dark), max(0.0, amp))` with `amp = 0.020*sin(2*pi*t/1.45)*(0.48+0.52*env)`. Density moves through 8-bit fill levels (many invisible steps) where position moves through whole pixels (one visible step). Keep position only for the entry rise, which is progress-driven and ends.
Measured consequence of getting this wrong, on a 176 px display line: the +-1.5 px position breath produced a **0.36 mean|dL| jump between consecutive frames twice per 1.45 s period** -- larger than a page change -- and `verify_assembly.py` section D reported `*** DISCONTINUITY ***` at two chunk boundaries (ratio 54.25 and 25.74) even though the assembly was perfect. The same project's `motion_probe.py` had already been flagging "sudden jumps" on those pages and the advice above ("read it as quantisation") had been followed, which is why the defect survived three deliveries. After the fix the same frames measured 0.005-0.032, and both seam ratios fell to 5-9.
If you genuinely need sub-pixel text motion, render the line to its own layer and translate it by a fractional offset with a resample, or supersample the type -- never expect `draw.text` at a float y to do it.

Symptom: a decoration grows an extra stroke as the animation progresses -- reported as "所有的笑脸在变动的时候，脸上会多出一块东西".
Cause: one animation parameter drove two visuals: the smile's crack parameter both opened the mouth arc and drew crack strokes on the forehead.
Fix: give each visual its own parameter (`grow` for the mouth, the crack drawing gated off), and keep the removed visual unreachable so a later edit cannot re-enable it by accident.

## The lyric reads backwards (draw order vs reading order)
Symptom: none. Every gate is green -- `layout_audit.py` prints 0/0, `lrc_check.py` prints `mismatches: 0`, the display block's box is exactly where the plan says, and the union of the line baselines is correct. But every multi-line page renders its lines **bottom to top**, so a two-line lyric reads as its own second line followed by its first, and anyone who knows the song sees it immediately.
Cause: the segment table authors `big` as a LIST IN READING ORDER (line 0 = first line = TOP), while the draw loop placed index 0 at the BOTTOM: `yb = yb0 - j*lh`. Any check that compares the plan's strings with the official lyric passes, because the PLAN is right -- only the rasterised picture is inverted. In the 心月灯 project this shipped on all 28 two-line pages through four deliveries, and reading a downscaled contact sheet had confirmed the bug as "correct".
Fix: place line 0 at the HIGHEST baseline and count down -- `nl = len(lines); yb = yb0 - (nl - 1 - j) * lh` -- so the entry cascade also runs downward, like the page being written. The union of the y positions is unchanged, so every audit box stays valid and the fix costs no relayout.
Detect it with a rendered-picture check, not a plan check (the fifth check in `references/lyrics-and-cards.md`): for each multi-line page, render one frame in the steady part, take the band each reading line should occupy (`ybase = yb0 - (nl-1-j)*lh`, band `ybase - 0.78*s .. ybase + 0.08*s`), typeset every candidate line alone at the same geometry, and require the band's declared line to win a z-normalised per-column ink-mass profile. Measured result on the broken film: 56 bands checked, all 56 wrong, none undecidable.
**Prove the check has teeth with a NEGATIVE CONTROL**, and keep the recipe: copy `film.py` to `film_inverted_test.py` in the project root, re-invert the draw rule in the COPY (`yb = yb0 - j*lh`), run the checker against the copy and require it to fail every band with `-- the display is drawn upside down`, then delete the copy. Never edit the real module for the control. A checker that has never failed is not evidence.

## Ambient layers read as the wrong thing (the 「背景很单调」 round)
Symptom: the user asks for atmosphere ("背景很单调，可以加点半空飘的灯吗"), and the first attempt makes the film worse: floating objects that pop into existence, a shape that reads as a grey card, a lit object that reads as graph paper.
Causes, all measured on the 心月灯 project:
- **Spawning instead of drifting.** Particles that are born at their start y and die at the end y make an EVENT out of every one. Fix: every particle wraps (its y is a continuous function of one phase plus its own hash-derived speed, so it leaves the top and re-enters at the bottom with no visible birth), and the whole field is driven by a slow per-particle hash, never by a beat index.
- **Concentric AA ovals instead of light.** Stacking 8 ovals with rising alpha renders visible banding rings that look like graph paper. Fix: build the interior as a numpy radial gradient, `a = (np.clip(1.0 - d, 0, 1) ** 1.7) * (0.16 + 0.62*flux)` where `d` is the normalised elliptical distance, and paint it once into an alpha tile; keep the AA vocabulary for the OUTLINE (ribs, hanger, rim) only.
- **A big object drawn as a rectangle.** A rounded-rect "lantern" reads as a UI card. Shapes must carry their silhouette -- an oval paper body with analytically clipped ribs (`hh = bh*sqrt(max(0, 1 - dx*dx))`), a hanger arc, a tassel.
- **Per-frame glow built from giant AA ellipses.** A radius-1300 px ellipse supersampled per frame costs more than everything else on the page. Fix: one cached 256x256 radial `glow_sprite()` (numpy, `** 2.4`), `resize` per frame and `putalpha(sp.getchannel("A").point(...))` to set the opacity.
- **A rounded-rect mask "phase terminator" for a crescent moon.** Sliding a background-coloured disc across the moon face reaches past the moon's own tile and gets CLIPPED SQUARE, printing a grey rectangle behind the lyric. Fix: build the crescent as the INTERSECTION of two L masks (`ImageChops.multiply(A, B)`), so the shape is the geometry, not a paint-over.
Rules that keep an ambient layer from competing with the type:
1. Draw it in the BACKGROUND layer, before any text, so it can never cover a glyph.
2. If an object must pass behind the text column, dim it by AREA -- compute the text boxes once per page and multiply the object's alpha by ~0.38 inside them, so "behind" reads as behind rather than as gone.
3. Drive density by PROGRESS, not by time or by beat: `warmth(t)`/`progress(t)` gates how many particles exist and how bright they are, so the film's atmosphere follows the song's arc (a moonlit first half, a lamp-lit finale) instead of being uniformly busy.
4. Bucket every continuously varying alpha into ~16 levels and cache the tile per (polarity, bucket). A cross-fade then costs one paste, not one gradient, and the 8-bit rounding is already baked in.
5. Measure it: `diff_cell` consecutive frames must stay at the HUD's level (~0.02). An ambient layer that is pretty in a still and 0.3 per frame in motion is a flicker the user will name.

## Renderer cost
Symptom: adding decorative layers takes a frame from 0.23 s to 0.83 s.
Cause: the AA mask painter's cost tracked the NUMBER of paint calls, not the painted area -- with a full-frame paint a 1920x4 strip cost almost as much as a full 1920x1080 frame (about 35 ms against 37 ms), because every call supersampled and downsampled a full-size mask.
Fix: merge all same-colour primitives into one `AA()` and paint once per colour per layer.
`assets/render_prefix.py` now does the rest by itself: the primitives (`line`, `dash`, `ell`,
`arc`, `poly`) each record their bounding box and `paint(im, color)` downsamples only that box --
pass `region=(x0, y0, x1, y1)` to force a wider crop. Measured on the shipped class: three lines
in a corner 40.5 -> 3.5 ms (12x), a page-filling drawing 56.4 -> 47.7 ms, a bare 1920x1080
LANCZOS 31 ms; the reference film went 0.83 -> 0.28 s/frame. Keep the merges anyway, because
every call still pays the crop+resize overhead.
Regression test: `scripts/test_aa_equiv.py [path/to/render_prefix.py]` draws one page of mixed
vector art twice -- automatic crop against a forced full-frame crop -- and requires the two
images to be byte-identical, plus the degenerate cases (nothing drawn, off-canvas line,
zero-length line). Run it after any edit to the AA class.
