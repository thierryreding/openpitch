---
title: PyAV playback performance on weak coach laptops
labels: task,video,studio
---

Measure 4K HEVC decode and scrubbing on a weak laptop. Reference numbers from a 16-thread dev machine (4K HEVC, 38 Mb/s, 1 s GOPs): `decode_keyframe` 65 ms, random `decode_frame` about 230 ms, forward step 9 ms/frame, sequential 94 fps. Done so far: frame index with on-disk cache, keyframe-only scrubbing, decoded-frame LRU cache. Still to evaluate: a low-res proxy, hardware decode, slice instead of frame threading for single-frame latency. See docs/design/video.md.
