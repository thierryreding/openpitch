# 0009: The frame index is cached on disk

- Status: accepted
- Date: 2026-11-08

## Context
The frame index (pts and keyframe flag of every frame) drives seeking, pts <-> frame
mapping and keyframe snapping (0006). It must be exact, so it is built by demuxing every
packet. Container indexes are not enough: MP4's sample table gives DTS, and with B-frames
a keyframe's DTS is not its PTS. Seeking once per keyframe instead is fragile (it was off
by one GOP in a test) and still reads every keyframe.

A full demux reads the whole file. Measured on a 9 GB, 30 minute 4K HEVC file with 1 s
GOPs: 3.1 s on NVMe with a cold cache (1.0 s warm). Coach laptops with SATA SSDs or
footage on USB disks would wait 20 s to minutes every time they open a video. The index
itself is small: about 54,000 frames, a few hundred KB.

## Decision
- `load_frame_index` caches the index in the per-user cache directory
  (`openpitch.core.cache.cache_dir()`; `OPENPITCH_CACHE_DIR` overrides it). Entries are
  `.npz` files (no pickle) named by the content fingerprint (0008) and an index format
  version.
- The cache is purely derived data. A missing, stale or unreadable entry is rebuilt.
  Failing to write it (read-only disk) is not an error. Deleting the directory is
  always safe.
- Nothing is written next to the video. Footage may be on read-only or shared media, and
  sidecars there would clutter coaches' folders.
- Bump `INDEX_VERSION` whenever the build rules or the format change.

## Consequences
- Only the first open of a file on a machine pays for the demux. Studio should build the
  index in the background and show progress (the build takes a progress callback that can
  also cancel).
- Renamed or moved copies hit the same entry, because the key is the content.
- The cache grows by a few hundred KB per video. Pruning can come later if it ever
  matters.
