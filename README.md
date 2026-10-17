# lyric-video-studio

An [OpenCode](https://opencode.ai) skill that renders a whole song as a
kinetic-typography lyric video **from code** — Python (Pillow) + ffmpeg, with no
video-generation model anywhere in the loop.

A segment table (one row per lyric line) drives one 1920x1080 frame per 1/30 s;
Pillow draws every glyph; ffmpeg muxes the original audio back on.

```
song.m4a + song.lrc  ->  segment table  ->  frames/  ->  out.mp4
                            (derived)         (Pillow)     (ffmpeg)
```

## Why no video model

Because the frames are deterministic, three things become possible that are
normally impossible with a generative pipeline:

- **Reviewable.** A `git diff` of a segment table is a meaningful review of a
  change to the video. You can see that segment 34 lost its table.
- **Repairable.** One bad page costs `scripts/rerange.py` — it re-renders only
  the affected frame ranges plus their transition tails. The reference project
  repaired 5 pages in 798 frames, about a minute on 8 processes, instead of
  re-rendering a 4-minute song.
- **Verifiable.** "Is the picture right?" stops being a judgement call. The skill
  ships 21 scripts that measure the delivered mp4 and answer it numerically.

## The one rule that matters most

A clean audit is not a picture. Box-collision auditing proves glyph ink boxes do
not intersect; it cannot see that the lyrics render bottom-to-top, that a mask
was clipped square behind the headline, or that a shape reads as a grey card.
Every pixel-level defect in the reference projects was found by *looking at
frames* — none of them by a verifier.

So the pipeline ends with rendering pages cheaply and reading the contact sheet
with your own eyes. The verifiers narrow the search; they do not close it.

## Install

```powershell
git clone https://github.com/slienceecheo/lyric-video-studio.git
Copy-Item -Recurse lyric-video-studio "$env:USERPROFILE\.config\opencode\skills\"
```

Linux/macOS: `~/.config/opencode/skills/`

To keep git as the single source of truth (so `git pull` updates the installed
skill in place), symlink instead of copy:

```powershell
New-Item -ItemType SymbolicLink `
  -Path "$env:USERPROFILE\.config\opencode\skills\lyric-video-studio" `
  -Target "$PWD\lyric-video-studio"
```

## Requirements

Not bundled — fetch them first.

- **Python** with `Pillow` + `numpy`. That is all. There is no `cv2` / `av` /
  `moviepy` / `imageio` dependency, and a stock Anaconda install suffices.
- **ffmpeg**, which is usually *not* on `PATH` on Windows. Locate it once and
  pin the absolute path; see `references/pipeline.md` §1.
- **Fonts** (OFL 1.1 — fetch, do not vendor; they are ~25 MB):
  [霞鹜文楷](https://github.com/lxgw/LxgwWenKai) — the **Mono GB** variants for
  the code column, since only those have the true 2:1 advance the grid needs.
  [得意黑 Smiley Sans](https://github.com/atelier-anchor/smiley-sans) for display headlines.

## Layout

```
lyric-video-studio/
├── SKILL.md                 # entry point: contract, 13 non-negotiables, pipeline
├── references/              # read on demand
│   ├── pipeline.md          # phase-by-phase commands, envelope, mux, verification
│   ├── renderer.md          # renderer architecture, SEG schema, layers, transitions
│   ├── assembly.md          # chunked rendering, seams, the vertical deliverable
│   ├── lyrics-and-cards.md  # LRC alignment, reading order, the negative control
│   ├── forensics.md         # reverse-engineering an existing reference video
│   └── pitfalls.md          # the bug catalogue: symptom -> cause -> fix
├── scripts/                 # 21 runnable tools
├── assets/                  # templates copied into your project dir
│   ├── render_prefix.py     # shared renderer core
│   ├── film_template.py     # a complete full-song film
│   ├── timeline_gen.py      # LRC scoring + page-table derivation
│   └── lrc_check_example.py # text / order / window / stamp verification
└── REVIEW-2026-yuesheng.md  # a project retrospective: 12 changes, incl. 3 that
                             # corrected this skill's own advice
```

`references/` is split out of `SKILL.md` on purpose: the entry file stays small
enough to load every session, and the deep material is read only when a task
needs it.

## Reading the references

`references/pitfalls.md` is the highest-value file — every entry cost real
debugging time. Read it before debugging anything, not after.

Some of it exists because the skill was wrong first:

- it recommended a ±1.5 px positional "breathing" that, because PIL rasterises
  to integer y, jittered the whole line by two full pixels every 1.45 s — a
  mean |dL| of 0.36, *larger than a page change*, which shipped through three
  deliveries undetected;
- it quoted the display face at 0.40 em/char; measured, it is 0.435–0.445;
- it told you to clear `out/` wholesale, which deleted the page table itself and
  killed all 8 workers in 0.4 s.

`REVIEW-2026-yuesheng.md` is the full write-up, including the verification
record and the two open questions the author left for themselves.

## License

MIT — see [LICENSE](LICENSE). Referenced fonts are OFL 1.1 and are not
redistributed here.