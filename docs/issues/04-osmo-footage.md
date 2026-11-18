---
title: DJI Osmo Action 6: lens profile, codec, recording limits
labels: question,footage
---

- Lens/field of view, and how to get a distortion profile: a known profile, or our own checkerboard calibration with OpenCV.
- Codec and bit depth: 10-bit HEVC? D-Log/HLG?
- Recording limits: are long recordings split into multiple files?
- ffprobe a real file once the camera arrives (keyframe spacing, VFR, color range).

Measured on a real match recording (2026-11-14, one camera, 4:3 4K60), see
design/video.md, "Footage facts": HEVC Main 10, BT.709 limited range (no log in that
mode), 1 s keyframes, tiles, 16 GiB file splits (seamless), LRF proxy files with matching
keyframes. Still open: the lens profile, other modes (8K, D-Log M), the per-frame data
tracks (`CAM meta`), and what the two-camera rig needs.
