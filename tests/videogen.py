# SPDX-License-Identifier: GPL-3.0-or-later
"""Synthetic test videos with a known structure, encoded in-process with PyAV.

No ffmpeg binary is needed, so this works on every CI platform. Never use real
match footage in tests (it shows minors).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import av
import numpy as np
from av.video.frame import PictureType


@dataclass(frozen=True)
class VideoSpec:
    """What to generate. All frame numbers are in presentation order."""

    frames: int = 90
    fps: int = 30
    width: int = 64
    height: int = 48
    #: Keyframe interval for regular GOPs. 1 means all-intra.
    gop: int = 30
    #: Maximum number of consecutive B-frames (0 disables them).
    bframes: int = 0
    #: Explicit keyframe positions (irregular GOPs). Overrides ``gop``.
    keyframes: Sequence[int] | None = None
    #: Stream time base. None uses 1/(fps * 512), like ffmpeg's mp4 default.
    time_base: Fraction | None = None
    #: Per-frame pts offsets in time_base units (timestamp jitter), cycled.
    jitter: Sequence[int] | None = None

    def keyframe_set(self) -> set[int]:
        if self.keyframes is not None:
            return set(self.keyframes)
        return set(range(0, self.frames, self.gop))

    def stream_time_base(self) -> Fraction:
        return self.time_base or Fraction(1, self.fps * 512)

    def frame_pts(self) -> list[int]:
        """The pts written for each frame, in stream time_base units."""
        tb = self.stream_time_base()
        nominal = [round(Fraction(i, self.fps) / tb) for i in range(self.frames)]
        if not self.jitter:
            return nominal
        return [p + self.jitter[i % len(self.jitter)] for i, p in enumerate(nominal)]


def make_video(path: Path, spec: VideoSpec) -> Path:
    tb = spec.stream_time_base()
    forced = spec.keyframes is not None
    keyint = 1_000_000 if forced else spec.gop
    x264 = [
        f"keyint={keyint}",
        f"min-keyint={keyint if not forced else 1}",
        "scenecut=0",
        f"bframes={spec.bframes}",
        "b-adapt=0",  # always use the maximum number of B-frames
        "forced-idr=1",
        "log-level=none",
    ]

    with av.open(str(path), "w", format="mp4") as out:
        stream = out.add_stream("libx264", rate=spec.fps)
        stream.width = spec.width
        stream.height = spec.height
        stream.pix_fmt = "yuv420p"
        stream.time_base = tb
        stream.codec_context.time_base = tb
        stream.options = {"x264-params": ":".join(x264), "preset": "ultrafast"}
        if spec.bframes == 0:
            stream.options["tune"] = "zerolatency"

        keyframes = spec.keyframe_set()
        rng = np.random.default_rng(1234)
        for i, pts in enumerate(spec.frame_pts()):
            # Noise plus a moving bar, so P/B-frames are non-trivial.
            img = rng.integers(0, 64, (spec.height, spec.width, 3), dtype=np.uint8)
            img[:, (i * 2) % spec.width] = 255
            frame = av.VideoFrame.from_ndarray(img, format="rgb24")
            frame.pts = pts
            frame.time_base = tb
            if forced:
                frame.pict_type = PictureType.I if i in keyframes else PictureType.NONE
            for packet in stream.encode(frame):
                out.mux(packet)
        for packet in stream.encode(None):
            out.mux(packet)
    return path
