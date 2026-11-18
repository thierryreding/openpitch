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

Still open:
- The lens profile per FOV mode, especially Standard, which the two-camera rig will use:
  a published profile (e.g. Gyroflow's lens profile database; check its coverage and
  license), or our own checkerboard/ChArUco calibration with OpenCV. The calibration also
  gives the horizontal FOV, which decides the bracket angle and the overlap between the
  two cameras.
- Whether Standard FOV is already undistorted in camera, and whether the metadata differs
  between FOV modes (`tools/dji_metadata.py diff`).
- Other modes (8K, D-Log M) and the unidentified metadata fields.
