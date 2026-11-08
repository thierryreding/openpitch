# SPDX-License-Identifier: GPL-3.0-or-later
"""Synthetic test videos with a known structure, encoded in-process with PyAV.

No ffmpeg binary is needed, so this works on every CI platform. Never use real
match footage in tests (it shows minors).

Two kinds of content:
- ``numbered`` (default): noise with the frame number drawn as 8 black/white blocks in
  the top 16 rows, so tests can check which frame a decoder returned (``frame_id``).
- ``patches``: flat color patches whose YUV values come from the reference math in
  ``colorref``, encoded losslessly, for checking YUV -> RGB conversion.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import av
import numpy as np
from av.video.frame import PictureType

from colorref import PATCH_COLORS, PATCH_SIZE, rgb_to_yuv

ID_BITS = 8
ID_ROWS = 16


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
    #: "libx264" or "libx265".
    codec: str = "libx264"
    pix_fmt: str = "yuv420p"
    #: "numbered" or "patches".
    content: str = "numbered"
    #: Signalled color metadata. None leaves it unspecified.
    color_range: str | None = None  # "pc" or "tv"
    matrix: str | None = None  # "bt709" or "bt601"
    #: Lossless encoding (exact YUV values survive).
    lossless: bool = False
    #: Add a stereo AAC track (a 440 Hz tone).
    audio: bool = False
    #: Container metadata, e.g. {"creation_time": "..."}.
    metadata: dict[str, str] | None = None

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

    @property
    def bit_depth(self) -> int:
        return 10 if "10" in self.pix_fmt else 8


_RANGE = {"tv": 1, "pc": 2}
_MATRIX = {"bt709": 1, "bt601": 6}


def _numbered_rgb(spec: VideoSpec, i: int, rng: np.random.Generator) -> np.ndarray:
    img = rng.integers(40, 216, (spec.height, spec.width, 3), dtype=np.uint8)
    block = spec.width // ID_BITS
    for b in range(ID_BITS):
        img[:ID_ROWS, b * block : (b + 1) * block] = 255 if (i >> b) & 1 else 0
    return img


def frame_id(rgb: np.ndarray) -> int:
    """Read back the frame number drawn by ``numbered`` content."""
    height, width = rgb.shape[:2]
    block = width // ID_BITS
    value = 0
    for b in range(ID_BITS):
        cell = rgb[2 : ID_ROWS - 2, b * block + 2 : (b + 1) * block - 2]
        if cell.mean() > np.iinfo(cell.dtype).max / 2:
            value |= 1 << b
    return value


def patches_frame(
    *,
    matrix: str,
    full: bool,
    pix_fmt: str = "yuv420p",
    patch: int = PATCH_SIZE,
    height: int = PATCH_SIZE,
) -> av.VideoFrame:
    """Untagged frame of flat patches with exact YUV values from the reference math.

    ``patch`` is the width of each patch; the frame is ``patch * len(PATCH_COLORS)``
    wide. No RGB conversion by PyAV is involved.
    """
    bits = 10 if "10" in pix_fmt else 8
    yuv = rgb_to_yuv(PATCH_COLORS, matrix=matrix, full=full, bits=bits)
    width = patch * len(PATCH_COLORS)
    dtype = np.uint16 if bits > 8 else np.uint8
    y = np.zeros((height, width), dtype)
    u = np.zeros((height // 2, width // 2), dtype)
    v = np.zeros_like(u)
    half = patch // 2
    for i, (cy, cu, cv) in enumerate(yuv):
        y[:, i * patch : (i + 1) * patch] = cy
        u[:, i * half : (i + 1) * half] = cu
        v[:, i * half : (i + 1) * half] = cv
    frame = av.VideoFrame(width, height, pix_fmt)
    for plane, data in zip(frame.planes, (y, u, v), strict=True):
        line = plane.line_size // data.itemsize
        padded = np.zeros((data.shape[0], line), dtype)
        padded[:, : data.shape[1]] = data
        plane.update(padded.tobytes())
    return frame


def _patches_frame(spec: VideoSpec) -> av.VideoFrame:
    return patches_frame(
        matrix=spec.matrix or "bt601", full=spec.color_range == "pc", pix_fmt=spec.pix_fmt
    )


def make_video(path: Path, spec: VideoSpec) -> Path:
    tb = spec.stream_time_base()
    forced = spec.keyframes is not None
    keyint = 1_000_000 if forced else spec.gop
    patches = spec.content == "patches"
    width = PATCH_SIZE * len(PATCH_COLORS) if patches else spec.width
    height = PATCH_SIZE if patches else spec.height

    with av.open(str(path), "w", format="mp4") as out:
        for key, value in (spec.metadata or {}).items():
            out.metadata[key] = value
        stream = out.add_stream(spec.codec, rate=spec.fps)
        stream.width = width
        stream.height = height
        stream.pix_fmt = spec.pix_fmt
        stream.time_base = tb
        cc = stream.codec_context
        cc.time_base = tb
        if spec.color_range:
            cc.color_range = _RANGE[spec.color_range]
        if spec.matrix:
            cc.colorspace = _MATRIX[spec.matrix]
            cc.color_primaries = _MATRIX[spec.matrix]
            cc.color_trc = _MATRIX[spec.matrix]

        if spec.codec == "libx264":
            params = [
                f"keyint={keyint}",
                f"min-keyint={keyint if not forced else 1}",
                "scenecut=0",
                f"bframes={spec.bframes}",
                "b-adapt=0",  # always use the maximum number of B-frames
                "forced-idr=1",
                "log-level=none",
            ]
            stream.options = {"x264-params": ":".join(params), "preset": "ultrafast"}
            if spec.lossless:
                stream.options["qp"] = "0"
            if spec.bframes == 0:
                stream.options["tune"] = "zerolatency"
        elif spec.codec == "libx265":
            params = [
                f"keyint={keyint}",
                f"min-keyint={keyint if not forced else 1}",
                "scenecut=0",
                f"bframes={spec.bframes}",
                "log-level=none",
            ]
            if spec.lossless:
                params.append("lossless=1")
            stream.options = {"x265-params": ":".join(params), "preset": "ultrafast"}
        else:
            raise ValueError(f"unsupported codec {spec.codec}")

        # All streams must exist before the first packet is muxed.
        audio = None
        if spec.audio:
            audio = out.add_stream("aac", rate=48000)
            audio.layout = "stereo"

        keyframes = spec.keyframe_set()
        rng = np.random.default_rng(1234)
        patch_frame = _patches_frame(spec) if patches else None
        for i, pts in enumerate(spec.frame_pts()):
            if patch_frame is not None:
                frame = patch_frame
            else:
                frame = av.VideoFrame.from_ndarray(_numbered_rgb(spec, i, rng), format="rgb24")
                frame = frame.reformat(format=spec.pix_fmt)
            frame.pts = pts
            frame.time_base = tb
            if spec.color_range:
                frame.color_range = _RANGE[spec.color_range]
            if spec.matrix:
                frame.colorspace = _MATRIX[spec.matrix]
            if forced:
                frame.pict_type = PictureType.I if i in keyframes else PictureType.NONE
            for packet in stream.encode(frame):
                out.mux(packet)
        for packet in stream.encode(None):
            out.mux(packet)
        if audio is not None:
            _encode_tone(out, audio, seconds=spec.frames / spec.fps)
    return path


def _encode_tone(out, audio, seconds: float, rate: int = 48000) -> None:
    samples = int(seconds * rate)
    chunk = 1024
    for start in range(0, samples, chunk):
        t = np.arange(start, min(start + chunk, samples)) / rate
        tone = (0.2 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
        frame = av.AudioFrame.from_ndarray(np.stack([tone, tone]), format="fltp", layout="stereo")
        frame.sample_rate = rate
        frame.pts = start
        for packet in audio.encode(frame):
            out.mux(packet)
    for packet in audio.encode(None):
        out.mux(packet)
