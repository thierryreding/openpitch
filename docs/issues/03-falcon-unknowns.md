---
title: Falcon footage: split recordings, retrieval, constant-rate pts
labels: question,footage
---

Measured so far: docs/design/video.md ("Footage facts"). Still unknown:
- Does the Falcon split long recordings into several files? (This affects multi-segment support in the header `video` block.)
- How is footage retrieved from the camera (app, SD card, network)?
- Are pts truly constant-rate over a full match? Check the whole file, not a sample: `openpitch probe` reports the largest deviation from a constant-rate timeline.
