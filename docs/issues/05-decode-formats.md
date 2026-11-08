---
title: Decode layer: full-range YUV and 10-bit pixel formats
labels: task,video
---

Falcon footage is yuv420p full range (pc), bt709. Convert to RGB correctly for display and analysis. Also handle 10-bit and other pixel formats beyond 8-bit 4:2:0. Record pix_fmt, color_range and color_space in the analysis header.
