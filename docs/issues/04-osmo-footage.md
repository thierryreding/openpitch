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
keyframes. The per-frame data tracks carry the camera clock, IMU orientation and gravity,
but no lens model (`tools/dji_metadata.py`).

Calibrated (2026-11-19, design/video.md): Standard (Dewarp) is rectilinear, horizontal FOV
103.5° with stabilization off and about 94-96° with it on, where the geometry also varies
slightly over time. The FOV setting and stabilization are in the metadata header.
`openpitch camera board` and `openpitch camera calibrate` do the calibration
(design/camera.md).

Still open:
- Calibrations of the other FOV settings, if they are ever used (Ultra Wide was used for
  the first match recording).
- Whether stabilization stays on for the rig: it narrows the overlap between the two
  cameras to about 11% for 180°, but cancels sway from wind.
- Other modes (8K, D-Log M) and the unidentified metadata fields.
