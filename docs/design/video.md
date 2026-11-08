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
  full-range BT.709 up to 24 code values off. Unspecified metadata follows player
  conventions: `yuvj*` is full range, otherwise limited; BT.709 from 1280x720 up,
  BT.601 below; the result says when it guessed. Overrides exist for mis-tagged streams.
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
Stream copy (keyframe-aligned, no re-encode) for now
([0006](../decisions/0006-clip-markers-snap-to-keyframes.md)). Possible later:
configurable re-encode for frame-accurate cuts, smart cut, or a re-encoded 1080p export
for iPads.

## Footage facts
XbotGo Falcon, measured on a real recording (18:31, 4K):
- A single MP4, HEVC Main 8-bit (hvc1 tag, which Apple devices play), yuv420p full range
  (pc), bt709, 3840x2160, 30 fps (average and real frame rate agree, likely constant).
- ~38.7 Mb/s, ~290 MB/min: ~5.4 GB for the 18:31 file, ~8.7 GB for a 30 minute half.
- AAC stereo audio. Muxed by libavformat 61.7, so the file was remuxed or processed by an
  FFmpeg-based tool.
- Keyframes every ~1.0 s (30 frames). Packet pts are in a microsecond time base with small
  jitter (e.g. 5.000022).
- Still unknown (issue): whether long recordings are split into several files, how footage
  is retrieved from the camera, and whether pts are truly constant-rate. Falcon has
  recorded 4K so far but supports several formats and resolutions.

DJI Osmo Action 6: not yet measured (issue).
