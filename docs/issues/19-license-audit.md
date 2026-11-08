---
title: License audit of dependencies, weights and datasets
labels: task,licensing
---

- The ffmpeg build bundled in PyAV wheels (GPL vs LGPL configuration). PyAV 19.0.2 (ffmpeg 9.0.2) reports libavcodec as "LGPL version 3 or later" but bundles libx264 and libx265 (GPL) and exposes their encoders. Clarify which license applies to the bundled build. This matters for the coach installers, which ship the wheel.
- Model weights and training datasets (Ultralytics AGPL, SoccerNet, NVIDIA Open Model License).
- Record the results next to ADR 0001.
