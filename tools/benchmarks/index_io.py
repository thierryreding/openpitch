# SPDX-License-Identifier: GPL-3.0-or-later
"""Cold-cache cost of building a frame index and hashing a file (decisions 0008, 0009).

Usage: uv run python tools/benchmarks/index_io.py VIDEO

Drops the file from the page cache before each measurement (Linux, posix_fadvise), so
run it on a real disk: on tmpfs everything stays in RAM. Measured on a 9 GB, 30 minute
4K HEVC file on NVMe: index entries 0.03 s, full demux 3.1 s, seek per keyframe 1.8 s,
sampled fingerprint 0.09 s, full SHA-256 6.8 s.
"""

import os
import sys
import time

import av

from openpitch.core.fingerprint import fingerprint, sha256_file


def drop_cache(path: str) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
    finally:
        os.close(fd)


def timed(label: str, fn) -> None:
    t = time.perf_counter()
    result = fn()
    print(f"{label:34s} {time.perf_counter() - t:7.3f} s  {result}")


def index_entries(path: str) -> str:
    with av.open(path) as c:
        entries = c.streams.video[0].index_entries
        return f"{len(entries)} entries (DTS, not PTS)"


def full_demux(path: str) -> str:
    with av.open(path) as c:
        s = c.streams.video[0]
        keys = sum(1 for p in c.demux(s) if p.pts is not None and p.is_keyframe)
        return f"{keys} keyframes"


def main(path: str) -> None:
    for label, fn in [
        ("container index entries", lambda: index_entries(path)),
        ("full packet demux", lambda: full_demux(path)),
        ("opfp1 fingerprint", lambda: fingerprint(path)),
        ("full sha256", lambda: sha256_file(path)),
    ]:
        drop_cache(path)
        timed(label, fn)


if __name__ == "__main__":
    main(sys.argv[1])
