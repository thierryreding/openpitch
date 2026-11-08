# SPDX-License-Identifier: GPL-3.0-or-later
"""CPU single-frame latency: frame threads vs slice threads vs draining the decoder.

Usage: uv run python tools/benchmarks/decode_latency.py VIDEO...

This chose VideoDecoder's strategy. Frame threads delay output by one frame per thread,
so a single keyframe costs up to one keyframe decode per thread; draining after the
target packet halves that. Slice threads only help streams with WPP, tiles or several
slices (x265 default), and are much slower on single-slice streams like the Falcon's.
"""

import random
import statistics
import sys
import time

import av

from openpitch.core.video import build_frame_index, to_array


def open_(path, thread_type, threads=0):
    c = av.open(path)
    s = c.streams.video[0]
    s.thread_type = thread_type
    s.thread_count = threads
    return c, s


def iterate(c, s, index, key, target, nonkey):
    """Current approach: seek, then pull frames until the target comes out."""
    s.codec_context.skip_frame = "NONKEY" if nonkey else "DEFAULT"
    c.seek(index.pts_of(key), stream=s, backward=True)
    for f in c.decode(s):
        pos = index.find_frame(f.pts)
        if pos is not None and pos >= target:
            return f, pos
    raise RuntimeError


def drain(c, s, index, key, target, nonkey):
    """Seek, feed packets until the target's packet is in, then drain the decoder."""
    cc = s.codec_context
    cc.skip_frame = "NONKEY" if nonkey else "DEFAULT"
    c.seek(index.pts_of(key), stream=s, backward=True)
    want = index.pts_of(target)
    tol = index.default_tolerance
    best = None

    def take(frames):
        nonlocal best
        for f in frames:
            pos = index.find_frame(f.pts)
            if pos == target:
                best = (f, pos)

    for packet in c.demux(s):
        if packet.pts is None:
            continue
        take(cc.decode(packet))
        if best:
            return best
        if abs(packet.pts - want) <= tol:
            break
    take(cc.decode(None))  # drain: everything sent so far comes out now
    if best:
        return best
    raise RuntimeError("target not decoded")


def run(path, label, thread_type, threads, method, nonkey, samples=20):
    index = build_frame_index(path)
    c, s = open_(path, thread_type, threads)
    next(c.decode(s))
    rng = random.Random(3)
    keys = index.keyframes
    times = []
    for _ in range(samples):
        n = rng.randrange(len(index) - 1)
        key = int(keys[keys <= n][-1])
        target = key if nonkey else n
        t = time.perf_counter()
        f, pos = method(c, s, index, key, target, nonkey)
        to_array(f)
        times.append(time.perf_counter() - t)
        assert pos == target
    c.close()
    print(
        f"  {label:34s} median {statistics.median(times) * 1000:5.0f} ms"
        f"  max {max(times) * 1000:5.0f} ms"
    )


for path in sys.argv[1:]:
    print(path.rsplit("/", 1)[-1])
    for what, nonkey in (("keyframe scrub", True), ("random frame", False)):
        print(f" {what}:")
        run(path, "frame threads x16, iterate (now)", "AUTO", 0, iterate, nonkey)
        run(path, "frame threads x16, drain", "AUTO", 0, drain, nonkey)
        run(path, "frame threads x4, drain", "AUTO", 4, drain, nonkey)
        run(path, "slice threads x16, iterate", "SLICE", 0, iterate, nonkey)
        run(path, "slice threads x4, iterate", "SLICE", 4, iterate, nonkey)
        run(path, "single thread, iterate", "SLICE", 1, iterate, nonkey)
