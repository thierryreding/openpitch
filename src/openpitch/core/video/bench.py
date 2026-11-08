# SPDX-License-Identifier: GPL-3.0-or-later
"""Decode benchmark over the real ``VideoDecoder`` code paths.

Measures, per decoder mode (software with N threads, or a hardware device):
- open: opening the file and decoding the first frame (includes device setup);
- sequential: frames per second and CPU cores busy, decode only and with RGB output;
- scrub: ``decode_keyframe`` latency for random keyframes;
- random: ``decode_frame`` latency for random frames (seek + up to one GOP);
- step: forward stepping with ``decode_frame`` (ms per frame);
- for hardware modes, the largest RGB difference to the software decoder.

Every latency sample starts from a reset decoder (no cache hits, no sequential
continuation), so the numbers are worst-case for that access type.
"""

from __future__ import annotations

import os
import random
import statistics
import time
from collections.abc import Callable
from pathlib import Path

import numpy as np
from pydantic import BaseModel

from openpitch.core.video.decode import VideoDecoder
from openpitch.core.video.index import FrameIndex, load_frame_index
from openpitch.core.video.probe import probe
from openpitch.core.video.structure import StreamStructure, stream_structure

DEFAULT_MODES = ("cpu", "cpu:4", "auto")


class Latency(BaseModel):
    median_ms: float
    max_ms: float


class ModeResult(BaseModel):
    mode: str
    #: The hardware device used (None: software). For "auto", what it resolved to.
    device: str | None
    #: True if frames were really decoded in hardware.
    hardware: bool
    open_ms: float
    decode_fps: float
    decode_cores: float
    rgb_fps: float
    rgb_cores: float
    scrub: Latency
    random: Latency
    step_ms: float
    #: Largest RGB difference to the software decoder (hardware modes only).
    max_diff_vs_cpu: int | None = None


class FileResult(BaseModel):
    path: str
    codec: str
    profile: str | None
    width: int
    height: int
    pix_fmt: str | None
    fps: float | None
    frames: int
    gop_frames: float
    structure: StreamStructure
    modes: list[ModeResult]


def parse_mode(mode: str) -> tuple[str | None, int]:
    """``"cpu"`` / ``"cpu:N"`` -> (None, N); a device type or "auto" -> (device, 0)."""
    name, _, arg = mode.partition(":")
    if name == "cpu":
        return None, int(arg) if arg else 0
    if arg:
        raise ValueError(f"hardware mode {mode!r} takes no thread count")
    return name, 0


def _timed(fn: Callable[[], object]) -> float:
    t = time.perf_counter()
    fn()
    return (time.perf_counter() - t) * 1000


def _latency(samples: list[float]) -> Latency:
    return Latency(median_ms=statistics.median(samples), max_ms=max(samples))


def _sequential(decoder: VideoDecoder, frames: int, rgb: bool) -> tuple[float, float]:
    decoder.reset()
    end = min(len(decoder), frames + 1)
    # Raw frames (decode only) come from the decoder's internal sequential path.
    it = decoder.iter_frames(0, end) if rgb else decoder._raw_from(0)
    try:
        next(it)  # exclude seek and decoder startup
        n = 0
        wall, cpu = time.perf_counter(), time.process_time()
        for _ in it:
            n += 1
            if n >= end - 1:
                break
        wall, cpu = time.perf_counter() - wall, time.process_time() - cpu
    finally:
        it.close()  # run the generator's cleanup now, not at garbage collection
        decoder.reset()
    return n / wall, cpu / wall


def bench_mode(
    path: Path,
    index: FrameIndex,
    mode: str,
    *,
    samples: int,
    frames: int,
    reference: list[np.ndarray] | None,
    seed: int = 1,
) -> ModeResult:
    device, threads = parse_mode(mode)
    t = time.perf_counter()
    decoder = VideoDecoder(path, index=index, threads=threads, hwaccel=device, cache_bytes=0)
    with decoder:
        decoder.decode_frame(0)
        open_ms = (time.perf_counter() - t) * 1000
        resolved = decoder.hwaccel
        hardware = decoder.hardware

        decode_fps, decode_cores = _sequential(decoder, frames, rgb=False)
        rgb_fps, rgb_cores = _sequential(decoder, frames, rgb=True)

        rng = random.Random(seed)
        n = len(index)
        scrub, rand = [], []
        for _ in range(samples):
            key_target, frame_target = rng.randrange(n), rng.randrange(n)
            decoder.reset()
            scrub.append(_timed(lambda: decoder.decode_keyframe(key_target)))  # noqa: B023
            decoder.reset()
            rand.append(_timed(lambda: decoder.decode_frame(frame_target)))  # noqa: B023

        decoder.reset()
        start = int(index.keyframes[len(index.keyframes) // 2])
        steps = min(10, n - start - 1)
        decoder.decode_frame(start)
        step_ms = _timed(lambda: [decoder.decode_frame(start + i) for i in range(1, steps + 1)])
        step_ms /= max(1, steps)

        diff = None
        if hardware and reference is not None:
            decoder.reset()
            got = [f.image for f in decoder.iter_frames(0, len(reference))]
            diff = max(
                int(np.abs(a.astype(np.int32) - b.astype(np.int32)).max())
                for a, b in zip(reference, got, strict=True)
            )

    return ModeResult(
        mode=mode,
        device=resolved,
        hardware=hardware,
        open_ms=open_ms,
        decode_fps=decode_fps,
        decode_cores=decode_cores,
        rgb_fps=rgb_fps,
        rgb_cores=rgb_cores,
        scrub=_latency(scrub),
        random=_latency(rand),
        step_ms=step_ms,
        max_diff_vs_cpu=diff,
    )


def bench_file(
    path: str | os.PathLike[str],
    modes: tuple[str, ...] | list[str] = DEFAULT_MODES,
    *,
    samples: int = 20,
    frames: int = 300,
    compare_frames: int = 30,
    on_start: Callable[[FileResult], None] | None = None,
    on_result: Callable[[ModeResult], None] | None = None,
) -> FileResult:
    """Benchmark ``modes`` on one file.

    ``on_start`` gets the file description (no modes yet) before the first mode runs,
    ``on_result`` each mode's result as soon as it is done.
    """
    path = Path(path)
    for mode in modes:
        parse_mode(mode)  # fail early on typos
    info = probe(path)
    index = load_frame_index(path)
    gops = np.diff(np.append(index.keyframes, len(index)))

    result = FileResult(
        path=str(path),
        codec=info.codec,
        profile=info.profile,
        width=info.width,
        height=info.height,
        pix_fmt=info.pix_fmt,
        fps=float(info.fps_avg) if info.fps_avg else None,
        frames=len(index),
        gop_frames=float(np.median(gops)),
        structure=stream_structure(path),
        modes=[],
    )
    if on_start is not None:
        on_start(result)

    reference = None
    if any(parse_mode(m)[0] for m in modes):
        with VideoDecoder(path, index=index, cache_bytes=0) as cpu:
            reference = [f.image for f in cpu.iter_frames(0, min(compare_frames, len(index)))]

    for mode in modes:
        mode_result = bench_mode(
            path, index, mode, samples=samples, frames=frames, reference=reference
        )
        result.modes.append(mode_result)
        if on_result is not None:
            on_result(mode_result)
    return result
