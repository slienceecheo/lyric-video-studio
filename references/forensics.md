# Reverse-engineering a reference lyric video

Use when the user says "分析一下这个视频是怎么制作的", or when a style must be matched to an existing file. Everything here works with Python + Pillow only; ffprobe is not required and usually is not installed.

Contents: 1 container parse - 2 codec provenance - 3 frame sampling - 4 style measurement - 5 determinism test - 6 music grid - 7 identification - 8 worked example.

## 1. Container parse by hand
MP4 is a box tree; walk it with `struct` and print a tree of `(offset, type, size)` before interpreting anything:
```
def boxes(buf, start, end, depth=0):
    o = start
    while o + 8 <= end:
        size, typ = struct.unpack('>I4s', buf[o:o+8])
        typ = typ.decode('latin1')
        if size == 1: size = struct.unpack('>Q', buf[o+8:o+16])[0]
        if size < 8: break
        print('  ' * depth + '%-6s %10d @%d' % (typ, size, o))
        if typ in ('moov','trak','mdia','minf','stbl','udta','meta','ilst','edts','free'):
            inner = o + 8 + (4 if typ == 'meta' else 0)   # meta has a 4-byte version/flags
            boxes(buf, inner, o + size, depth + 1)
        o += size
```
Then read the fields you actually need: `mvhd` (duration, timescale), `mdhd` (per-track timescale and duration), `hdlr` (SoundHandler / VideoHandler), `stts` (sample count and delta -> fps; a single entry means constant frame rate), `stsz` (per-sample byte sizes -> average bitrate, and the largest samples are usually scene changes or a keyframe), `stss` (sync samples = keyframe indices, giving the GOP length), `ctts` (B-frames present), `avcC` (profile, level, NAL length size), `esds` (audio object type; `sgpd` with a `roll` group plus ~2048 samples per frame means HE-AAC).
Pitfall: read child boxes at the offsets the parent walk gives you. Guessing an offset by eye produced a nonsense `keys` list (`['mdta','mdta','mdta']`) in the reference case and a `values` dump that ran off into `mdat`.

## 2. Codec provenance
Read `moov/udta/meta/ilst` (handler `mdta`). Its `keys` are usually `comment`, `information`, `encoder`; `encoder = Lavf58.76.100` means FFmpeg 4.4 muxed it, so compare that to the ffmpeg version on the user's own machine -- if they differ, the file was produced elsewhere.
Then scan the first video sample for a `user_data_unregistered` SEI:
```
# length-prefixed NALs: 4-byte length, then 06 (SEI), 05 (type), size, then a 16-byte UUID + payload
uuid = bytes.fromhex('dc45e9bde6d948b7962cd820d923eeef')
```
That UUID in the reference case carried `bvc0ot v2.2.1.3-20250220`, which identified ByteDance's BVC encoder as the final encoder, alongside a Douyin video id in `comment` and `{"com.bytedance.info": "{}"}` in `information` -- so the file was a platform re-encode of an author upload, not a local export. Also do a plain string scan of the whole file for CJK and vendor keywords; it is cheap and it is how the vendor strings surfaced.

## 3. Frame sampling when there is no ffmpeg
Chromium decodes H.264 out of the box, so drive Edge/Chrome headless with playwright-core:
```
// serve the file over local HTTP with Range support, then:
const browser = await chromium.launch({ executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe' })
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } })
// <video src=... muted>, then per sample: video.currentTime = t; await seeked; await page.screenshot({ path })
```
Notes: pass `executablePath` explicitly -- `channel: 'msedge'` fails when the `PROGRAMFILES` environment variable is missing. Read duration from `video.duration` after metadata loads (the reference case reported 47.02 s). Sample every 2 s for a style read, and 25-50 frames is enough for a contact sheet. Assemble sheets and zoom crops with Pillow.

## 4. Style measurement
- Palette: take the exact background colours from the histogram, not by eye (the reference case had exactly two: rgb(10,10,10) and rgb(247,247,243)).
- Static overlay test: build a per-pixel mask of pixels identical across all sampled frames. Zero persistent pixels means no watermark, no logo, no fixed UI.
- Cut detection: mean absolute difference between consecutive sampled frames; hard cuts read 200+ (a background flip), continuous motion reads under 20.
- Text sanity: OCR a few frames. Correct, readable, syntactically valid source code in every sampled frame is decisive -- a video model cannot hold that.

## 5. The determinism test (proves text rendering, not generation)
Find a region that should be a duplicate of another region (in the reference case, the right-hand diff pane at t=0) and search the shift that minimises the difference:
```
best = min((np.abs(left - right_shifted_by(dx)).mean(), dx) for dx in range(900, 1300, 2))
```
Result: `dx = 1118 px, mean abs diff 1.85`, while unrelated frames bottomed out at 8.1-22.2. That is a byte-level duplicate of typeset text, so the visuals are deterministic rendering, not diffusion. Confidence: high on the rendering method, medium on the authoring tool (HTML/CSS, After Effects, or a script are all consistent with the evidence).

## 6. Music grid
Decode to 8 kHz mono, compute a per-frame RMS envelope, then detect onsets (local flux above the 75th percentile) and estimate the bar by autocorrelation. Confirm each shot change sits within a frame or two of an onset. This is also the envelope the renderer will use, so measure it once.

## 7. Identification
Search the OCRed on-screen lyric line plus 歌词 to identify the song, then look for the artist and the remix name: the reference file's name pointed at 反乌托邦 and frame 0 contained `./拼接 --start`, which matched the 拼接版 remix. Report the identification together with its evidence and mark it as inferred, not certain.

## 8. Worked example (the reference case)
- 1920x1080, 1410 frames, exactly 30 fps CFR, H.264 High level 5.0, ~714 kb/s, 8 keyframes with GOP 174-181; audio HE-AAC ~63 kb/s stereo 44.1 kHz, 47.02 s.
- Muxed by a ByteDance build of the FFmpeg 4.4 muxer, encoded by ByteDance BVC (SEI UUID), carrying a Douyin video id: a platform re-encode, not a local export. The user's own machine has FFmpeg 7.1, which is what muxed their OTHER file in the same workspace.
- Content: kinetic typography, lyrics rewritten as code, two background colours only, no watermark. Deterministic text rendering, confirmed by the 1118 px duplicate-pane test.
- Conclusion delivered to the user: the video was made by authoring text/animation in some authoring tool (or by script), exporting to video, and uploading through a ByteDance product that re-encoded it -- which is why the encoder was BVC and the metadata held Douyin ids.
