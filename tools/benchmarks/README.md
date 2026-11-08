# Benchmarks

Raw measurement scripts behind the numbers and decisions in `docs/design/video.md`,
decision records 0008/0009, and the decoder and color choices in `openpitch.core.video`.
For comparing decoders across footage, use the CLI instead:

```sh
uv run openpitch bench-decode VIDEO... [--mode cpu --mode cpu:4 --mode cuda --mode auto]
uv run openpitch bench-decode --json VIDEO... > results.json
```

| script | measures |
|---|---|
| `index_io.py VIDEO` | cold-cache cost of the container index, a full packet demux, the opfp1 fingerprint and a full SHA-256 (Linux; use a real disk, not tmpfs) |
| `decode_raw.py VIDEO...` | raw PyAV decode: CPU threads vs NVDEC, with frames copied back or left on the GPU; bit-exactness of NVDEC |
| `decode_latency.py VIDEO...` | single-frame latency: frame threads vs slice threads vs draining the decoder |
| `color_accuracy.py` | YUV -> RGB error of swscale flag sets against reference BT.709/BT.601 math |

Run them from the repository root with `uv run python tools/benchmarks/<script>`.

## Stand-in footage

Never commit real match footage. These ffmpeg commands make synthetic clips with the
properties that matter (4K HEVC, ~38 Mb/s, 1 s GOPs, B-frames). Noise keeps the bitrate
realistic.

```sh
# Like the XbotGo Falcon: HEVC Main, full-range BT.709, single slice, no WPP or tiles.
ffmpeg -f lavfi -i "testsrc2=size=3840x2160:rate=30,noise=alls=20:allf=t" -t 10 \
    -c:v libx265 -preset ultrafast -b:v 38M -tag:v hvc1 -color_range pc -colorspace bt709 \
    -x265-params "keyint=30:min-keyint=30:bframes=3:wpp=0:slices=1" falconlike_10s.mp4

# x265 defaults (WPP on), 10-bit full range.
ffmpeg -f lavfi -i "testsrc2=size=3840x2160:rate=30,noise=alls=20:allf=t,format=yuv420p10le" \
    -t 10 -c:v libx265 -preset ultrafast -b:v 60M -tag:v hvc1 -color_range pc -colorspace bt709 \
    -x265-params "keyint=30:min-keyint=30:bframes=3" hevc10_10s.mp4

# Longer files by stream copy (6x = 60 s; -stream_loop 179 gives a 30 minute, 9 GB file).
ffmpeg -stream_loop 5 -i falconlike_10s.mp4 -c copy falconlike_60s.mp4
```

Check the parallelism-relevant structure of any file (also shown by `openpitch probe`):

```sh
ffmpeg -hide_banner -i VIDEO -c copy -bsf:v trace_headers -frames:v 1 -f null - 2>&1 \
    | grep -E "entropy_coding_sync_enabled_flag|tiles_enabled_flag"
ffmpeg -hide_banner -i VIDEO -c copy -bsf:v trace_headers -frames:v 1 -f null - 2>&1 \
    | grep -c first_slice_segment_in_pic_flag
```
