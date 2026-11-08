# SPDX-License-Identifier: GPL-3.0-or-later
"""CPU vs NVDEC decode benchmark on raw PyAV (before VideoDecoder supported hwaccel).

Usage: uv run python tools/benchmarks/decode_raw.py VIDEO...

Superseded by ``openpitch bench-decode``, which measures the real VideoDecoder paths.
Kept because it separates decoding with frames left on the GPU (nvdec-gpu) from the
copy back to system memory. Linux only (resource module).
"""

import random
import resource
import statistics
import sys
import time

import av
import numpy as np
from av.codec.hwaccel import HWAccel

from openpitch.core.video import build_frame_index, to_array

MODES = ["cpu16", "cpu4", "nvdec", "nvdec-gpu"]


def cpu_s():
    r = resource.getrusage(resource.RUSAGE_SELF)
    return r.ru_utime + r.ru_stime


def open_(path, mode):
    if mode.startswith("nvdec"):
        hw = HWAccel("cuda", allow_software_fallback=False, is_hw_owned=(mode == "nvdec-gpu"))
        c = av.open(path, hwaccel=hw)
        s = c.streams.video[0]
    else:
        c = av.open(path)
        s = c.streams.video[0]
        s.thread_type = "AUTO"
        s.thread_count = {"cpu16": 0, "cpu4": 4, "cpu1": 1}[mode]
    return c, s


def first_frame(path, mode):
    t = time.perf_counter()
    c, s = open_(path, mode)
    f = next(c.decode(s))
    dt = time.perf_counter() - t
    fmt = f.format.name
    c.close()
    return dt, fmt


def sequential(path, mode, n, convert):
    c, s = open_(path, mode)
    it = c.decode(s)
    next(it)  # exclude device/decoder startup
    t, cpu = time.perf_counter(), cpu_s()
    for _, f in zip(range(n), it, strict=False):
        if convert:
            to_array(f)
    wall, cpu = time.perf_counter() - t, cpu_s() - cpu
    c.close()
    return n / wall, cpu / wall  # fps, CPU cores busy on average


def seek_decode(c, s, index, target, until, nonkey):
    s.codec_context.skip_frame = "NONKEY" if nonkey else "DEFAULT"
    c.seek(index.pts_of(target), stream=s, backward=True)
    for f in c.decode(s):
        pos = index.find_frame(f.pts)
        if pos is not None and pos >= until:
            return f, pos
    raise RuntimeError("frame not reached")


def latency(path, mode, index, nonkey, samples, rng):
    c, s = open_(path, mode)
    next(c.decode(s))  # warm up the device
    keys = index.keyframes
    times = []
    for _ in range(samples):
        n = rng.randrange(len(index) - 1)
        key = int(keys[keys <= n][-1])
        t = time.perf_counter()
        f, pos = seek_decode(c, s, index, key, key if nonkey else n, nonkey)
        if mode != "nvdec-gpu":
            to_array(f)
        times.append(time.perf_counter() - t)
        assert pos == (key if nonkey else n), (pos, key, n)
    c.close()
    return statistics.median(times) * 1000, max(times) * 1000


def compare(path, frames=30):
    out = {}
    for mode in ("cpu16", "nvdec"):
        c, s = open_(path, mode)
        out[mode] = [
            (f.pts, f.format.name, f.color_range, f.colorspace, to_array(f))
            for _, f in zip(range(frames), c.decode(s), strict=False)
        ]
        c.close()
    diffs = []
    for a, b in zip(out["cpu16"], out["nvdec"], strict=True):
        assert a[0] == b[0], "pts differ"
        diffs.append(int(np.abs(a[4].astype(int) - b[4].astype(int)).max()))
    meta = (out["cpu16"][0][1:4], out["nvdec"][0][1:4])
    return max(diffs), meta


def main(path):
    index = build_frame_index(path)
    print(f"# {path}: {len(index)} frames, {len(index.keyframes)} keyframes")
    maxdiff, meta = compare(path)
    print(
        f"correctness: max RGB diff cpu vs nvdec over 30 frames = {maxdiff}; "
        f"frame (format, range, space): cpu {meta[0]}, nvdec {meta[1]}"
    )
    for mode in MODES:
        dt, fmt = first_frame(path, mode)
        print(f"{mode:10s} open + first frame {dt * 1000:6.0f} ms  (frame format {fmt})")
    print()
    print(
        f"{'mode':10s} {'decode fps':>10s} {'cores':>6s} {'+RGB fps':>9s} {'cores':>6s}"
        f" {'scrub ms':>13s} {'random ms':>14s}"
    )
    for mode in MODES + ["cpu1"]:
        fps, cores = sequential(path, mode, 300, convert=False)
        if mode == "nvdec-gpu":
            rgb = "      -      -"
        else:
            rfps, rcores = sequential(path, mode, 300, convert=True)
            rgb = f"{rfps:9.0f} {rcores:6.1f}"
        if mode == "cpu1":
            print(f"{mode:10s} {fps:10.0f} {cores:6.1f} {rgb}")
            continue
        sk = latency(path, mode, index, True, 20, random.Random(1))
        rn = latency(path, mode, index, False, 20, random.Random(2))
        print(
            f"{mode:10s} {fps:10.0f} {cores:6.1f} {rgb} {sk[0]:6.0f} ({sk[1]:4.0f})"
            f" {rn[0]:6.0f} ({rn[1]:5.0f})"
        )
    print("scrub/random: median (max) of 20 samples, incl. RGB conversion except nvdec-gpu")


if __name__ == "__main__":
    for p in sys.argv[1:]:
        main(p)
        print()
