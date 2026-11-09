# Video handling

## Decoding
- Decoding and playback use PyAV (ffmpeg bindings), chosen because of the author's
  extensive ffmpeg experience and its reliability. Concern: performance on coach laptops.
- `VideoDecoder` (`openpitch.core.video.decode`) gives full-range RGB (`rgb24`, `bgr24`,
  or `rgb48le` for 10-bit input), optionally scaled in the same pass:
  - `decode_keyframe(n)`: the keyframe at or before `n`, decoded with non-key frames
    skipped, then the decoder is drained (fast scrubbing). Without draining, a
    frame-threaded decoder returns a frame only once its threads are full, so one
    keyframe costs up to one keyframe decode per thread.
  - `decode_frame(n)`: exactly frame `n`. Seeks to the keyframe at or before it and decodes
    forward. Forward stepping continues without a seek. A byte-bounded LRU cache
    (default 256 MiB, about 10 frames at 4K) keeps the frames decoded on the way, so
    stepping back is free within the cache.
  - `iter_frames(start, end, stride)`: sequential reading for extraction, one seek.
  - Decoded frames are matched to the frame index by pts with tolerance. If a seek lands
    after the wanted keyframe, it retries from earlier keyframes. Leading frames of an
    open GOP (before the keyframe) are dropped, never cached.
- Color (`openpitch.core.video.color`): the source matrix and range are always passed to
  swscale explicitly. Untagged frames otherwise get BT.601 limited range, which renders
  full-range BT.709 up to 24 code values off. Where range and matrix come from, in
  order (`stream_color`): the bitstream (H.264/HEVC VUI) when it signals them; else the
  container (MP4 `colr`); else player conventions (`yuvj*` is full range, otherwise
  limited; BT.709 from 1280x720 up, BT.601 below; flagged as guessed). The container
  step matters: ffmpeg's HEVC decoder tags frames as limited range whenever the
  bitstream signals no range, overriding the container. Falcon footage is exactly that
  case, and trusting the frames rendered it with crushed shadows and clipped highlights
  (and made `recode` write full-range levels labelled as limited). `openpitch probe`
  shows the color source. Overrides exist for mis-tagged streams.
  8-bit output is within one code value of reference BT.709/BT.601 math (full and
  limited range, 8- and 10-bit input); `rgb48le` within 0.6/1.1 code values. Transfer
  functions are not converted: HDR or log footage (HLG, PQ, D-Log) is shown as encoded.
- Hardware decoding (`hwaccel=` on `VideoDecoder`, `openpitch.core.capabilities`):
  optional, per platform in order of preference (Linux: cuda, vaapi, qsv; Windows:
  d3d11va, cuda, qsv; macOS: videotoolbox). `"auto"` takes the first device that really
  decodes the file: the first frame must come out in device memory, because a configured
  hardware context falls back to software silently (unsupported codec, profile, or frames
  below the minimum size, e.g. 144x144 for NVDEC HEVC). Frames are copied back to system
  memory and converted like software frames. NVDEC output is bit-identical to the
  software decoder (HEVC 8 and 10 bit, full and limited range).
  VideoToolbox works in the PyAV wheels on macOS (GitHub's Apple Silicon runners decode
  HEVC with it, down to 128x16 frames, with correct colors). D3D11VA on Windows is still
  untested on real hardware.
- Threading: frame threads for everything. Slice threads only parallelize inside a frame,
  which needs HEVC wavefronts (WPP), tiles or several slices. The Falcon writes one slice
  per frame without WPP or tiles, and there slice threads are single-threaded (random
  access 415 ms instead of 152 ms). `openpitch probe` shows the structure
  (`openpitch.core.video.structure`). If other footage (Osmo?) uses WPP, slice threads
  could cut CPU scrubbing further (37 ms instead of about 100 ms on x265 WPP streams).
- Measured with `openpitch bench-decode` on a Falcon-like stand-in (4K HEVC Main, 38 Mb/s,
  1 s GOPs, 3 B-frames, single slice, no WPP), RTX 3080 laptop, 16 threads. Latencies are
  medians from a reset decoder:

  | mode | decode fps (cores) | +RGB fps | scrub | random | step |
  |---|---|---|---|---|---|
  | software, 16 threads | 271 (12.1) | 113 | 121 ms | 118 ms | 8.8 ms |
  | software, 4 threads | 136 (3.4) | 83 | 96 ms | 161 ms | 15.9 ms |
  | NVDEC (cuda) | 245 (0.4) | 111 | 20 ms | 60 ms | 12.8 ms |

  Before draining, software scrubbing took about 184 ms. (An earlier figure of 65 ms
  for `decode_keyframe` was wrong: that run hit the frame cache.) At 4K the RGB
  conversion on the CPU caps sequential output at about 110 fps whatever the decoder;
  converting at the working or display resolution is much cheaper (720p: about 146 fps
  with software decoding). Coach laptops will be several times slower in software, which
  makes their hardware decoders (D3D11VA, VideoToolbox, QSV) the important lever. They
  are untested so far.
- The JSONL header `video` block stores `pix_fmt`, `color_range` and `color_space`.

## Time and seeking
- pts is the source of truth for time, not the frame count, since footage may be variable
  frame rate. JSONL records store both the frame index and pts. Frames are matched to pts
  with a tolerance, never by exact equality.
- Frame-accurate seeking is needed for clipping and for overlay lookup in Studio. It is
  not needed for extraction, which decodes sequentially.
- Frame index (`openpitch.core.video`): pts and keyframe flag of every frame, built per
  file by demuxing packets (no decoding) and never assumed. It drives pts <-> frame
  mapping and marker snapping ([0006](../decisions/0006-clip-markers-snap-to-keyframes.md)).
  Container indexes are not used: MP4 sample tables hold DTS, and with B-frames a
  keyframe's DTS is not its PTS. A full demux reads the whole file (3.1 s for 9 GB on
  NVMe, cold), so the index is cached on disk by content fingerprint
  ([0009](../decisions/0009-frame-index-disk-cache.md)).
- Frame positions are 0 .. n-1 in presentation order. Position n is the end of the
  stream, so ranges are half-open `[in, out)` and Out is exclusive.
- Tolerance: the default is half a frame interval (median frame delta), so any pts
  closer to a frame start than to its neighbours maps to that frame. `find_frame`
  matches a frame start, `frame_at` gives the frame on screen at a time, and `boundary`
  places a range marker. `openpitch probe` reports the largest deviation from a
  constant-rate timeline: small values are jitter, large ones mean VFR.

## Scrubbing
Implemented by `decode_keyframe` and `decode_frame` (above). The Studio side is still
to come.
- Fast mode shows keyframes only: seek to a keyframe and decode just that frame. PyAV can
  also skip non-key frames in the codec context. Since markers snap to keyframes, clip
  editing never needs more precision than this.
- Precise mode (frame-by-frame stepping) decodes forward from the previous keyframe (at
  most one GOP), with a small frame cache. It is needed mainly for viewing analysis
  overlays.
- The Studio use case picks fast or precise mode, not the file.

## Proxies (proposed)
- 8K and high-bitrate HEVC will not decode in real time on weak laptops. An optional
  low-res proxy (e.g. 720p), generated by a CLI, gives smooth playback. A dense-GOP or
  all-intra variant helps if precise stepping on slow machines matters. Use hardware
  decode where available.
- With keyframe-only scrubbing, clip editing does not need the proxy. Marker positions are
  pts on the original timeline, and export always cuts the original file.

## Multi-segment recordings (proposed)
If cameras split long recordings, the header `video` may need a list of segments (files
with hash and offset) forming one virtual timeline.

## Clip export
`openpitch clip` (`openpitch.core.video.clip`) exports ranges by stream copy, without
re-encoding ([0006](../decisions/0006-clip-markers-snap-to-keyframes.md)). It runs
in-process with PyAV, so no ffmpeg binary is needed.
- `plan_clip` gives the snapped range (In to the keyframe at or before, Out to the
  keyframe at or after) for Studio to show. `export_clip` copies the video packets of
  that range unchanged and shifts timestamps so the clip starts at 0. The CLI takes
  ranges as `START-END` in seconds from the first frame (`1:23-1:45.5`), and
  `--dry-run` prints the snapped ranges.
- Open GOPs (HEVC CRA, which x265 writes by default): frames shown just before a
  keyframe can be decoded after it and reference it (leading pictures). When the clip
  ends at such a keyframe, the export adds that keyframe, one frame more than the
  snapped range, because the last frames would not decode otherwise. The result reports
  it (`extra_keyframe`), so the preview may be one frame shorter than the file. Leading
  pictures of the first keyframe are dropped: they come before In and reference the
  previous GOP. The Falcon writes closed GOPs, so this never applies to its footage.
- Audio packets overlapping the clip are copied, not cut, so audio may start or end up
  to one packet (about 21 ms for AAC) outside the video, in sync. MP4 trims the start
  with an edit list. Audio that MP4 cannot carry is dropped (MKV carries anything).
- The container follows the output extension (`.mp4`, `.m4v`, `.mov` with `+faststart`,
  or `.mkv`), by default the input's. HEVC in MP4 is tagged `hvc1`. `creation_time` moves
  to the start of the clip. An interrupted export leaves no partial file.
- On a real Falcon recording (4K HEVC, 17 minutes, 5 GB), a 17 minute clip took 3.4 s
  (file in the page cache, output to tmpfs) and a 16 s clip 0.5 s. Frames are
  bit-identical to the source and audio stays in sync.
- Clips grow by up to one keyframe interval on each side: 1 s on Falcon originals, 5 s
  on `recode` output.
- Possible later: configurable re-encode for frame-accurate cuts, smart cut, or a
  re-encoded 1080p export for iPads (today: `clip`, then `recode`).

## Recoding for sharing
`openpitch recode` (`openpitch.core.video.recode`) re-encodes whole files to smaller files
for sharing, e.g. via cloud storage: 1080p by default (never upscales). Codec, encoder
and container are independent options:
- `--codec h264` (default) plays everywhere. `--codec hevc` is 30-50% smaller at the
  same quality and plays natively on Apple devices and in Chrome (with a hardware
  decoder), but Windows players need the paid "HEVC Video Extensions" (VLC does not).
- `--encoder auto` (default) uses NVENC when it works for the output size (checked with a
  test encode), else software (x264/x265). `software` and `nvenc` force one.
- `--container mp4` (default) with `+faststart`, and HEVC tagged `hvc1` as Apple devices
  require. `mkv` (cues in front) plays on Windows and in VLC, but not on iPadOS/iOS or in
  QuickTime, and is not on Google Drive's list of preview formats.
- Profiles map to a constant quality per encoder family, calibrated on real Falcon
  footage so each row reaches the same VMAF (see "Encoder comparison" below; `--crf` and
  `--preset` override them):

  | profile | VMAF | NVENC CQ | x264 `fast` | x265 `fast` | NVENC H.264 bitrate |
  |---|---|---|---|---|---|
  | high | 95.2 | 26 | 20 | 19 | 7.4 Mb/s (about 3.3 GB/h) |
  | normal (default) | 93.6 | 29 | 22 | 22 | 4.6 Mb/s (about 2.1 GB/h) |
  | small | 90.9 | 32 | 25 | 25 | 2.6 Mb/s (about 1.2 GB/h) |
  | tiny | 86.8 | 35 | 28 | 28 | 1.6 Mb/s (about 0.7 GB/h) |
- Output is BT.709 limited range, what browsers, phones and tablets expect. The source
  matrix and range are converted properly, so full-range Falcon footage stays correct.
- Keyframes every 5 seconds, chosen by the encoder (plus scene cuts), never copied from
  the source: decoded frames keep their source picture type, and encoders force a
  keyframe for every frame marked I, which turned Falcon recodes into 1 s GOPs (about 30%
  bigger) and intra-only sources into all keyframes.
- Source timestamps are kept (MKV rounds them to milliseconds). Audio is copied if the
  container can carry it, else encoded to AAC. `creation_time` is copied. Interrupted
  runs leave no partial file.
- Decoding uses a hardware decoder when one works. On a real 17 minute Falcon recording,
  4K to 1080p with NVENC ran at about 3.7x realtime on an RTX 3080 laptop (about 8
  minutes for a 30 minute half); x264 `fast` is about half as fast. Whether Google Drive
  previews HEVC and MKV uploads is untested.

## Encoder comparison
Measured with `tools/benchmarks/encoder_matrix.py` and `bdrate.py` on a 2 minute excerpt
of real Falcon footage (a match, lots of motion), converted to a lossless 1080p
reference that every encoder encodes; VMAF v0.6.1 and VMAF NEG against that reference.
BD-rate is the average bitrate difference at equal quality against NVENC H.264 p5 (what
`recode` uses); negative is better.

| encoder | curve (Mb/s → VMAF) | BD-rate VMAF / NEG | fps |
|---|---|---|---|
| NVENC H.264 p5 | 1.6 → 86.8, 2.6 → 90.9, 4.6 → 93.6, 7.4 → 95.2 | baseline | 190 |
| NVENC HEVC p5 | 1.6 → 88.2, 2.6 → 91.2, 4.4 → 93.3, 7.4 → 94.8 | -3.4% / -3.6% | 210 |
| NVENC HEVC p7, B-frame refs | 1.6 → 88.4, 2.6 → 91.3, 4.4 → 93.4, 7.4 → 94.9 | -5.7% / -5.4% | 127 |
| NVENC HEVC p7, B-frame refs, AQ | 1.5 → 86.9, 2.5 → 90.2, 4.3 → 92.4, 7.4 → 94.1 | +10.2% / +11.4% | 127 |
| NVENC H.264 p7, B-frame refs, AQ | 1.6 → 84.8, 2.7 → 89.1, 4.6 → 91.9, 7.7 → 94.0 | +38.6% / +40.9% | 170 |
| x264 fast | 1.6 → 85.3, 2.9 → 90.1, 6.1 → 93.3, 13.1 → 95.4 | +31.8% / +39.4% | 75-110 |
| x265 fast | 1.2 → 85.3, 2.1 → 89.4, 4.0 → 92.3, 7.6 → 94.3 | +11.0% / +10.8% | 46-68 |
| x264 medium | 1.7 → 86.0, 3.1 → 90.7, 6.3 → 93.7, 13.1 → 95.7 | +24.3% / +34.2% | 62-94 |
| x265 medium | 1.2 → 85.9, 2.3 → 90.0, 4.5 → 92.9, 8.8 → 94.8 | +6.0% / +8.7% | 33-58 |
| x265 slow | 1.4 → 89.2, 2.7 → 92.5, 5.5 → 94.5, 10.7 → 95.8 | -22.9% / -17.5% | 15-27 |
| x264 medium, `tune psnr` | 1.7 → 87.5, 3.1 → 91.7, 5.8 → 94.5, 11.0 → 96.2 | +3.6% / +4.2% | 72-101 |
| x265 medium, `tune psnr` | 0.8 → 81.8, 1.5 → 87.5, 3.0 → 91.4, 5.7 → 93.9 | +0.9% / +1.1% | 42-64 |

Findings:
- HEVC against H.264 with the same tuning: only 2-6% fewer bits when both are tuned for
  objective quality (NVENC without AQ: -3.4%; x265/x264 `tune psnr`: -2.3%), but 15-21%
  with psychovisual tuning on (NVENC with AQ: -20.7%; x265/x264 defaults: -15% to
  -17%). VMAF NEG agrees, so this is not a sharpening artifact. A plausible reason: grass
  and fine detail are mostly unpredictable texture, where residual coding dominates and
  HEVC's better prediction saves little; HEVC's large gains are reported at 4K, low
  bitrates and smoother content.
- VMAF penalizes AQ and psychovisual tuning heavily (they move bits to what the eye
  notices). Whether AQ looks better on this footage needs a visual check.
- NVENC H.264 without AQ is the best speed/efficiency trade-off by VMAF, so it stays the
  default. NVENC p7 and B-frame references gain only 2% for 40% of the speed. Only x265
  `slow` is clearly more efficient (-23%), at about one eighth of the speed.
- B-frames were not the issue: both NVENC encoders use 3 by default in this ffmpeg.



## Footage facts
XbotGo Falcon, measured on a real recording (18:31, 4K):
- A single MP4, HEVC Main 8-bit (hvc1 tag, which Apple devices play), yuv420p,
  3840x2160, 30 fps (average and real frame rate agree, likely constant).
- Full range BT.709, signalled only in the MP4 `colr` atom: the bitstream has VUI but no
  video signal type or colour description. The pixel data confirms full range (luma
  reaches 0 and 255). One slice per frame, no WPP, no tiles.
- ~38.7 Mb/s, ~290 MB/min: ~5.4 GB for the 18:31 file, ~8.7 GB for a 30 minute half.
- AAC stereo audio. Muxed by libavformat 61.7, so the file was remuxed or processed by an
  FFmpeg-based tool.
- Keyframes every ~1.0 s (30 frames), closed GOPs (no leading pictures). Packet pts are
  in a microsecond time base with small jitter (e.g. 5.000022).
- No `creation_time` in the container. The recording start is only in the file name
  (`VID_<YYYYMMDD>_<HHMMSS>_01_01.mp4`).
- Still unknown (issue): whether one long recording is ever split into several files, how
  footage is retrieved from the camera, and whether pts are truly constant-rate. Falcon
  has recorded 4K so far but supports several formats and resolutions.

DJI Osmo Action 6: not yet measured (issue).
