# 0008: Sampled content fingerprint identifies video files

- Status: accepted
- Date: 2026-11-08

## Context
Analysis, overlay and annotation files refer to their video by content, not by path
(0003). Coaches open the same footage on other machines, often from slow disks or USB
sticks. Footage is large: a 30 minute 4K half from the Falcon is about 9 GB.

Measured on a 9 GB 4K HEVC file (NVMe, cold cache): full SHA-256 takes 6.8 s and is
CPU-bound at about 1.3-1.9 GB/s. A SATA SSD would need about 20 s and a USB 2 stick
several minutes, every time a file is opened on a machine that has not seen it. Hashing 64
blocks of 1 MiB takes 0.09 s on the same file.

## Decision
The content identity is `opfp1:` followed by the lowercase hex SHA-256 of a byte
sequence in a fixed order, with one rule for every file size:

```
L        = min(1 MiB, size)
offset_i = i * (size - L) // 63            for i = 0 .. 63 (integer arithmetic)
input    = b"opfp1"                        5 bytes, ASCII, no terminator
         | uint64_be(size)                 8 bytes, big-endian
         | file[offset_0  : offset_0  + L]
         | ...
         | file[offset_63 : offset_63 + L]
```

- Block 0 starts at the first byte and block 63 ends at the last. There are always 64
  blocks of the same length, in file order.
- Files up to 64 MiB: the blocks overlap, so every byte is hashed. Larger files are
  sampled. A file smaller than 1 MiB is hashed 64 times in full. An empty file hashes
  only prefix and size.
- A 64-bit size covers 16 EiB, enough for any footage.
- The definition never changes. Known-answer vectors in `tests/test_fingerprint_cache.py`
  pin it (two of them cross-checked with coreutils `sha256sum`). A change is a new
  scheme (`opfp2`) with a new prefix, and readers accept both.
- Implemented in `openpitch.core.fingerprint`. A short read (the file changed while it
  was being hashed) is an error, never a silently different fingerprint.
- A full `sha256:<hex>` is available for integrity checks (e.g. verifying a copied
  file). It is optional and never required to open or match a file.

## Consequences
- Opening and matching footage is near-instant on any disk.
- This is identity, not integrity: for files over 64 MiB a corruption between sampled
  blocks goes undetected. Two different recordings of the same size practically never
  share 64 MiB of compressed video at the same offsets. Any remux or re-encode changes
  the fingerprint, which is correct: it is a different file, with possibly different
  pts.
- Two exactly identical copies share a fingerprint, which is the point.
