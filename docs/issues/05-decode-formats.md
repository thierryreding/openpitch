---
title: HDR and log footage (HLG, PQ, D-Log) in the decode layer
labels: question,video
---

The decode layer converts YUV to RGB with the right matrix and range (full/limited, BT.709/BT.601/BT.2020, 8 and 10 bit), but it does not convert transfer functions. HDR (HLG, PQ) or log footage (DJI D-Log) is shown as encoded: flat and washed out. Find out what the Osmo Action 6 records by default. If it is HDR or log, decide on tone mapping for display, and on what analysis should see. Also record `pix_fmt`, `color_range`, `color_space` (and the transfer) in the analysis header once the schema exists.
