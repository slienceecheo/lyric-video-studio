# Lyrics, timings and the non-lyric (card) pages

Contents: 1 source of truth - 2 the validator - 3 when the official file is wrong - 4 cuts vs stamps -
5 the page taxonomy - 6 card copy - 7 boundaries must look different - 8 evidence sheets - 9 triage.

## 1. Keep a ground truth, and treat it as read-only
Copy the official LRC (and its translation file, if one exists) into the project and never edit them.
Record the exact paths and the byte sizes in the handoff/manifest, because a "the lyrics are wrong"
report is usually a diff against a file you can no longer find. In the reference case the two
authoritative files were the platform's own lyric tracks for the song:

- `... <track>.lrc` -- 45 lines: 12 credit lines (00:00-00:11) that are NOT lyrics, then 33 sung lines.
- `... <track>.zh.lrc` -- the 33 translations, same timestamps as the English.

The *old* project file was a hand-made LRC with 31 lines and two credit lines: it was missing two sung
lines entirely and its translations were a loose paraphrase. That is the normal situation -- the
first pass is a guess, the platform file is the contract.

## 2. The validator (`scripts/lrc_check.py` in the project, run it before every delivery)
```
python scripts/lrc_check.py film.py "<track>.lrc" "<track>.zh.lrc"
mismatches: 0   ALIGNED WITH THE OFFICIAL LRC
```
Five independent checks, because they fail for different reasons:
- **EN** -- concatenate every page's `big` lines for one lyric line, compare to the official text. Catches
  a typo, a dropped word, and a line that got merged into its neighbour.
- **ZH** -- concatenate the page captions and compare to the official translation.
- **ORDER** -- the RENDERED picture, top to bottom, must be the reading order. EN and ZH compare the
  AUTHORED list with the official line, and an authored list is always in reading order -- so neither can
  see a draw loop that places line 0 at the BOTTOM, which makes every multi-line page read backwards while
  `mismatches: 0` prints four deliveries in a row. Method: for each multi-line page render one frame from
  the steady part, compute the band each reading line occupies exactly as a CORRECT draw loop computes it
  (`ybase = yb0 - (len(lines)-1-j)*lh`, band `ybase - 0.78*s .. ybase + 0.08*s`), typeset every candidate
  line alone through the film's own `display()` at the same geometry, z-normalise both per-column ink-mass
  profiles, and require the declared line to win its own band. Skip the band when two candidates correlate
  above 0.995 (visually identical lines are undecidable). Reference run: 56 bands, 0 undecidable. Wire it
  up while the renderer is fresh -- it needs the display call, not just the tables.
- **TIME** -- the page's first frame must land in the stamp's `+0 .. +150 ms` window (the cut is snapped
  to a detected onset, so a small positive lag is correct, not a defect).
- **STAMP** -- the `LRC mm:ss.mmm` string printed in the page footer must equal the official stamp
  character for character. This is what makes the delivered pixels self-documenting.

**Every new check needs a negative control once.** Copy the film module to `<name>_negative_test.py` in
the project root, break exactly the thing the check is about (ORDER: re-invert the draw rule), run the
checker against the copy, and require it to fail. Then delete the copy -- never edit the real module for
the control. A check that has never failed has not been shown to work, and ORDER's control is the reason
its 56-band result means anything.

Plus a page-set assertion: every official lyric line must own at least one page, and page numbers must be
exactly `1..N`. A missing line is invisible in the film and obvious to anyone who knows the song.

**Register every deliberate deviation in an `EXPECT` table inside the validator**, with the reason, so
that a mismatch never becomes white noise:

```
EXPECT = {14: ["你不会孤单"], 15: ["在你选择的世界里"],   # the official .zh.lrc swapped these two
          24: ["你不会孤单"], 25: ["在你选择的世界里"],   # ...and their repeat in the last chorus
          19: ["所以我将明艳地起舞", "舞进那良夜"]}      # one official sentence split over two pages
```

## 3. When the official file is wrong (it happens -- decide by what is SUNG)
- **Swapped translations.** The official `.zh.lrc` carried `[01:24.730] 在你选择的世界里` and
  `[01:27.337] 你不会孤单`, while the `.lrc` at those same timestamps had `You won't be alone` and
  `In this world you've chosen as your own`. Timestamps identical, order inverted. Fix: pair each
  translation with the line actually sung there (the two pages swap), keep the official wording, and
  log it in `EXPECT` so the validator stays green and the decision is visible.
- **Missing lines.** Diff the two files' line counts and timestamps: a 31-line file against a 33-line
  official one means two lines have no page at all. Add the pages; do not silently orphan the lyric.
- **One sentence, two pages.** A long official sentence that spans two pages cannot be "one translation
  per page" -- split it into two phrases that each read on their own (`所以我将明艳地起舞` /
  `舞进那良夜`) instead of leaving two pages with the same caption.
- Never let the validator's official files be the only copy: keep the project's own LRC source under
  version control as `cuts.json` + the segment table, so a re-render does not depend on the Desktop.

## 4. Cuts versus stamps
- Cut points come from the onset list (`onsets.json`), not from the stamps. Snapping to a real onset is
  why page starts drift -112 .. +128 ms from the official stamps; that spread is normal and is inside
  the validator's window.
- A long sung line legitimately extends past its stamp: in the reference case line 17 (`I'm well aware
  that all snowflakes melt in the end`) had a 4-second-long phrase, so its page ran 3.93 s past the
  stamp, into an audible instrumental tail. That is correct -- do not "fix" it by cutting early, which
  risks chopping the vocal mid-word.
- When a user says a page "did not turn in time", first check for a duplicate caption (section 6) and a
  lingering identical graphic (section 7). If those are clean, measure before moving a cut: extract the
  audio, and try to prove where the vocal ends. If the mix is dense, you cannot -- say so, keep the
  onset-snapped cut, and offer the user the earlier cut as a one-line change.

## 5. The page taxonomy and footer vocabulary
Two page kinds, and the footer must announce which:

| kind | footer middle field | example |
|---|---|---|
| lyric page | `LINE nn/NN · SLUG · LRC mm:ss.mmm` | `LINE 17/33 · MELT · LRC 01:33.886` |
| card page | `SLUG · ROLE` from a `CARD_NOTE` table | `MELT-INST · 间奏 I`, `END · 终章` |

A card page is any page that is not a lyric line: title card, credits (in), pre-departure, log,
instrumental/interlude, signal/still, outro, credits (out), end card. The reference film had 12 of them
across 46 pages, each with its own role label and its own footer right-hand field (`PROGRAMME-RENDERED
TYPOGRAPHY`, `T-MINUS 00:03.913`, `F k / 6733`, ...).

**Never let a template default reach the screen.** `"%s · INSTRUMENTAL" % slug` shipped on 9 card pages
and reads as a placeholder to the viewer; it was reported and had to be replaced. A card footer should
say what the page IS in the film's own language (开场 / 航行日志 / 备航 / 间奏 I / 尾声 II / 终章), and
the same vocabulary should appear in the manifest's page table.

## 6. Card copy must not restate a neighbour
A card page placed between two lyric pages is the one place where a caption can collide with the lyric
it sits next to. Reported defect in the reference case: the interlude card's caption read
`所有雪花终将融化 · ALL SNOWFLAKES MELT IN THE END` while the previous lyric page's last line was
`that all snowflakes melt in the end` / `我深知所有雪花最终都会融化` -- the same sentence, in English,
twice, 10 seconds apart. The film then also felt like it had "not turned the page".

Rules:
- For every card page, diff its `cap`/`big` strings against the neighbouring lyric pages' lines **and
  their translations**; any shared clause of more than a few words is a defect.
- A card should advance the motif, not repeat it: the repaired card read `零度以上 · ABOVE ZERO`
  ("above zero") while the next lyric page began `spring = warmth + hope` -- it is a hinge, not an echo.
- The card's headline word (a section title such as `MELT`) is fine; it is the sentence that must not be
  duplicated.

## 7. Two neighbouring pages must LOOK different, not just say different things
The second half of the same complaint was "the join between these two pages is bad". The cut was on a
musical onset and the pages were correct -- but the card repeated the lyric page's background polarity,
its decoration (the same snowflake), and its colour, so the change read as "the same page with more
stuff appearing on it". A correct hard cut between two look-alike pages still reads as a defect.

- Change the **graphic language** at the boundary: give the card its own decoration key (the repair
  switched the card from the snowflake to a wave/level-meter), or flip the polarity if the design allows.
- Prefer a **dissolve** at section boundaries instead of the default flash. Keep an explicit
  `FORCED_DISS = (11, 22, 25, 35, 42, 45)` list of page indices whose entry is a cross-dissolve even when
  the polarity does not change, and re-check it whenever a page is inserted or removed.
- The transition duration does not need to change: 0.36 s across a same-polarity boundary is enough once
  the two pages actually differ.

## 8. Evidence sheets (read from the DELIVERED file)
Two sheets answer almost every "these pages look wrong" report, and both crop the mp4, not the renderer:

- **card footers** -- for every card page, extract the mid-page frame and crop the footer band
  (`y` around the status baseline +- 27 px) into a stacked sheet with an ASCII label per row. That is how
  a footer change was shown as 12 rows in one image.
- **cut strips** -- 8 frames across a +-0.25 s window at the boundary, one row per boundary (the skill's
  `scripts/cut_strips.py`), rendered from the module. Use both: the strip shows the transition, the
  footer sheet shows the text.

Note that ffmpeg's `-ss` may return the frame after the requested one; label your evidence with the
frame number printed in the picture, not with the number you asked for.

## 9. Triage checklist for "these two pages are bad"
1. Is any string duplicated between the two pages (including translations)? -> section 6.
2. Are the two pages visually distinguishable (polarity, decoration key, composition)? -> section 7.
3. Is the cut on a detected onset, and does the page run long because the sung phrase is long? -> section 4.
4. Does the footer of each page say what the page is? -> section 5.
5. Re-run the LRC validator (section 2) before and after the repair, and re-run `layout_audit.py`.
6. Re-render only the affected canonical chunks, then `verify_assembly.py` (see references/assembly.md),
   and report the frame counter read back from the delivery as the proof.
