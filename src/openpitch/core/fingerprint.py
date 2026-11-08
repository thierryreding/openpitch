# SPDX-License-Identifier: GPL-3.0-or-later
"""Content fingerprints that identify a video file across machines (docs/decisions/0008).

``opfp1`` is defined as::

    L        = min(BLOCK_SIZE, size)                      # BLOCK_SIZE = 1 MiB
    offset_i = i * (size - L) // (BLOCK_COUNT - 1)        # i = 0 .. 63, integer math
    digest   = SHA-256( b"opfp1"                          # 5 bytes, ASCII
                      | uint64_be(size)                   # 8 bytes
                      | file[offset_0 : offset_0 + L]
                      | ...
                      | file[offset_63 : offset_63 + L] )
    value    = "opfp1:" + lowercase hex(digest)

There is exactly one rule for every size. Block 0 starts at the first byte and block 63
ends at the last. For files up to 64 MiB the blocks overlap, so every byte is hashed;
larger files are sampled. A file smaller than one block is hashed 64 times in full, and
an empty file hashes only prefix and size.

It identifies a file. It does not verify integrity: see ``sha256_file`` for that.
"""

from __future__ import annotations

import hashlib
import os
import struct
from pathlib import Path

SCHEME = "opfp1"
BLOCK_SIZE = 1 << 20  # 1 MiB
BLOCK_COUNT = 64


def _read_exactly(f, n: int) -> bytes:
    data = f.read(n)
    while len(data) < n:
        more = f.read(n - len(data))
        if not more:
            raise OSError(f"short read: file changed while fingerprinting ({len(data)}/{n})")
        data += more
    return data


def fingerprint(path: str | os.PathLike[str]) -> str:
    """Return the ``opfp1`` content fingerprint of a file, e.g. ``"opfp1:3f2a..."``."""
    with Path(path).open("rb") as f:
        size = os.fstat(f.fileno()).st_size
        length = min(BLOCK_SIZE, size)
        h = hashlib.sha256()
        h.update(SCHEME.encode("ascii"))
        h.update(struct.pack(">Q", size))
        for i in range(BLOCK_COUNT):
            f.seek(i * (size - length) // (BLOCK_COUNT - 1))
            h.update(_read_exactly(f, length))
    return f"{SCHEME}:{h.hexdigest()}"


def sha256_file(path: str | os.PathLike[str]) -> str:
    """Full SHA-256 of a file, e.g. ``"sha256:..."``. Reads the whole file."""
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        while chunk := f.read(8 * BLOCK_SIZE):
            h.update(chunk)
    return f"sha256:{h.hexdigest()}"
