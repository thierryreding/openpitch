---
title: Decode performance and hardware decoding on coach laptops
labels: task,video,studio
---

Run `openpitch bench-decode --mode cpu --mode cpu:4 --mode auto VIDEO` on real coach laptops (Windows, macOS) with real Falcon and Osmo footage, and record the results in docs/design/video.md. Reference numbers from an RTX 3080 laptop are there. Software decoding of 4K HEVC takes about 120 ms to scrub to a keyframe and about 120-160 ms for a random frame, NVDEC 20 ms and 60 ms.

Still to evaluate:
- Whether D3D11VA (Windows), VideoToolbox (macOS) and QSV work in the PyAV wheels on those platforms, are bit-exact, and how fast they are.
- Whether the Osmo footage uses WPP. If it does, slice threads could cut CPU scrubbing to about 40 ms (see docs/design/video.md).
- RGB conversion at 4K caps sequential output at about 110 fps. Converting at display or working resolution, or on the GPU.
- A low-res proxy for weak laptops without a usable hardware decoder.
