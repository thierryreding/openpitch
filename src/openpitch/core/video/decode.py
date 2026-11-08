# SPDX-License-Identifier: GPL-3.0-or-later
"""Frame access for clipping, overlays and extraction.

- ``decode_keyframe``: fast scrubbing. Seeks, has the codec skip non-key frames, and
  drains the decoder right after the keyframe's packet. Without draining, a
  frame-threaded decoder only returns a frame once all its threads are busy, which
  means decoding up to one keyframe per thread first (twice the latency on 4K HEVC).
- ``decode_frame``: precise stepping. Decodes forward from the keyframe at or before the
  frame, at most one GOP. Stepping forward continues without a new seek, and recently
  decoded frames are kept in a small LRU cache, so stepping back is cheap too.
- ``iter_frames``: sequential reading for extraction. One seek, then decode in order.

Hardware decoding (``hwaccel``) is optional and falls back to software when the
device cannot decode the stream. Frames are copied back to system memory, so the output
is the same, bit for bit (NVDEC was measured identical to the software decoder).

All output is full-range RGB converted with the stream's real matrix and range (see
``color``). Frames are identified by their position in the frame index; decoded frames
are matched to it by pts with a tolerance, never by exact equality.
"""

from __future__ import annotations

import os
from collections import OrderedDict
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import av
import numpy as np
from av.codec.hwaccel import HWAccel

from openpitch.core.video.color import OUTPUT_FORMATS, stream_color, to_array
from openpitch.core.video.index import FrameIndex, load_frame_index

DEFAULT_CACHE_BYTES = 256 << 20  # ~10 frames at 4K, ~85 at 1080p (rgb24)


@dataclass(frozen=True, eq=False)
class DecodedFrame:
    #: Position in the frame index (presentation order).
    frame: int
    pts: int
    keyframe: bool
    #: ``(H, W, 3)`` array in the decoder's output format.
    image: np.ndarray = field(repr=False)


@dataclass
class DecoderStats:
    seeks: int = 0
    #: Frames that came out of the codec (including ones only decoded to reach a frame).
    decoded: int = 0
    #: Frames converted to RGB.
    converted: int = 0
    cache_hits: int = 0


class VideoDecoder:
    """Random and sequential access to the frames of one video file.

    Not thread-safe: use one decoder per thread or worker process.
    """

    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        index: FrameIndex | None = None,
        format: str = "rgb24",
        size: tuple[int, int] | None = None,
        cache_bytes: int = DEFAULT_CACHE_BYTES,
        threads: int = 0,
        hwaccel: str | None = None,
    ) -> None:
        """Open ``path`` for decoding.

        ``threads`` is the software decoder's thread count (0: automatic).
        ``hwaccel`` is an ffmpeg hardware device type ("cuda", "d3d11va",
        "videotoolbox", ...), "auto" for the first one that works for this file
        (``openpitch.core.capabilities``), or None for software decoding. A device
        that cannot decode this file falls back to software; ``self.hwaccel`` says
        which device is in use.
        """
        if format not in OUTPUT_FORMATS:
            raise ValueError(f"unsupported output format {format!r}, use one of {OUTPUT_FORMATS}")
        self.path = Path(path)
        self.index = index if index is not None else load_frame_index(self.path)
        self.format = format
        self.size = size
        self.stats = DecoderStats()
        #: Container color that overrides frame tags the bitstream does not back up.
        self.stream_color = stream_color(self.path)

        if hwaccel:
            from openpitch.core.capabilities import check_hw_decode, select_hw_decoder

            if hwaccel == "auto":
                hwaccel = select_hw_decoder(self.path)
            elif not check_hw_decode(self.path, hwaccel):
                hwaccel = None  # unusable here: a normal, multi-threaded software decoder
        #: The hardware device type in use (None: software).
        self.hwaccel = hwaccel
        if hwaccel:
            accel = HWAccel(hwaccel, allow_software_fallback=True)
            self._container = av.open(str(self.path), hwaccel=accel)
        else:
            self._container = av.open(str(self.path))
        self._stream = self._container.streams.video[0]
        if self._stream.index != self.index.stream_index:
            raise ValueError("frame index belongs to a different stream")
        if not hwaccel:
            self._stream.thread_type = "AUTO"
            self._stream.thread_count = threads
        self._codec = self._stream.codec_context

        cc = self._codec
        out_w, out_h = size if size else (cc.width, cc.height)
        bytes_per_frame = max(1, out_w * out_h * (6 if format == "rgb48le" else 3))
        self._cache_capacity = max(1, cache_bytes // bytes_per_frame)
        self._cache: OrderedDict[int, DecodedFrame] = OrderedDict()

        # Sequential decode state: the live frame generator and the last frame it produced.
        self._frames: Iterator[av.VideoFrame] | None = None
        self._last: int | None = None

    # -- context management -----------------------------------------------------------

    def close(self) -> None:
        self._frames = None
        self._container.close()

    def __enter__(self) -> VideoDecoder:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def __len__(self) -> int:
        return len(self.index)

    @property
    def cache_capacity(self) -> int:
        """How many frames the LRU cache holds."""
        return self._cache_capacity

    @property
    def hardware(self) -> bool:
        """True if frames are decoded in hardware (checked on the file when opening)."""
        return self.hwaccel is not None

    def reset(self) -> None:
        """Drop cached frames and the sequential decode state (next access seeks)."""
        self._cache.clear()
        self._frames = None
        self._last = None

    # -- public API -------------------------------------------------------------------

    def decode_keyframe(self, frame: int) -> DecodedFrame:
        """Decode the keyframe at or before ``frame`` (fast scrubbing).

        If the stream does not start with a keyframe, frames before the first one give
        the first keyframe.
        """
        self._check(frame)
        key = self.index.keyframe_at_or_before(frame)
        if key is None:
            key = self.index.keyframe_at_or_after(frame)
        if key in self._cache:
            return self._hit(key)

        self._codec.skip_frame = "NONKEY"
        try:
            vf = self._drain_decode(key)
            if vf is not None:
                return self._remember(self._make(vf, key))
        finally:
            self._codec.skip_frame = "DEFAULT"
            # Non-key frames were skipped, so the decoder cannot continue sequentially.
            self._frames = None
            self._last = None
        raise RuntimeError(f"{self.path}: keyframe {key} could not be decoded")

    def decode_frame(self, frame: int) -> DecodedFrame:
        """Decode one frame exactly (precise stepping)."""
        self._check(frame)
        if frame in self._cache:
            return self._hit(frame)

        key = self.index.keyframe_at_or_before(frame)
        if key is None:
            raise ValueError(f"frame {frame} is before the first keyframe and cannot be decoded")
        # Keep only the frames that will still fit in the cache once ``frame`` is reached.
        keep_from = frame - self._cache_capacity + 1

        if self._frames is not None and self._last is not None and key <= self._last < frame:
            source = self._continue()
        else:
            source = self._raw_from(key)
        for vf, pos in source:
            if pos >= keep_from:
                decoded = self._remember(self._make(vf, pos))
                if pos == frame:
                    return decoded
            if pos >= frame:
                break  # the frame was dropped by the decoder
        raise RuntimeError(f"{self.path}: frame {frame} could not be decoded")

    def iter_frames(
        self, start: int = 0, end: int | None = None, *, stride: int = 1
    ) -> Iterator[DecodedFrame]:
        """Yield frames ``start, start + stride, ...`` below ``end``, in order.

        Decodes sequentially from the keyframe at or before ``start``. Nothing is cached.
        Frames the decoder drops (corrupt data) are missing from the output rather than
        stopping the iteration.
        """
        n = len(self.index)
        end = n if end is None else end
        if not 0 <= start <= end <= n:
            raise ValueError(f"invalid range [{start}, {end}) for {n} frames")
        if stride < 1:
            raise ValueError("stride must be >= 1")
        if start == end:
            return
        key = self.index.keyframe_at_or_before(start)
        if key is None:
            key = self.index.keyframe_at_or_after(start)
            if key >= end:
                return
        try:
            for vf, pos in self._raw_from(key):
                if pos >= end:
                    break
                if pos < start or (pos - start) % stride:
                    continue
                yield self._make(vf, pos)
        finally:
            # The shared decoder state was used: random access must seek again.
            self._frames = None
            self._last = None

    # -- internals --------------------------------------------------------------------

    def _check(self, frame: int) -> None:
        if not 0 <= frame < len(self.index):
            raise IndexError(f"frame {frame} out of range 0..{len(self.index) - 1}")

    def _hit(self, frame: int) -> DecodedFrame:
        self._cache.move_to_end(frame)
        self.stats.cache_hits += 1
        return self._cache[frame]

    def _remember(self, decoded: DecodedFrame) -> DecodedFrame:
        self._cache[decoded.frame] = decoded
        self._cache.move_to_end(decoded.frame)
        while len(self._cache) > self._cache_capacity:
            self._cache.popitem(last=False)
        return decoded

    def _raw_from(self, key: int) -> Iterator[tuple[av.VideoFrame, int]]:
        """Seek to keyframe ``key`` and yield ``(frame, position)`` from there on.

        Frames before ``key`` (leading B-frames of an open GOP, which reference the
        previous GOP) are dropped. If the seek lands after the keyframe, it retries from
        earlier keyframes, and finally from the start of the file.
        """
        target = key
        while True:
            pts = self.index.pts_of(target)
            self._container.seek(pts, stream=self._stream, backward=True)
            self.stats.seeks += 1
            frames = self._container.decode(self._stream)
            first = True
            for vf in frames:
                self.stats.decoded += 1
                pos = self._position(vf)
                if pos is None:
                    continue
                if first:
                    first = False
                    if pos > key and target > 0:
                        break  # landed too late: retry from an earlier keyframe
                if pos < key:
                    continue
                self._frames = frames
                self._last = pos
                yield vf, pos
            else:
                return  # end of stream
            if target == 0:
                return
            earlier = self.index.keyframe_at_or_before(target - 1)
            target = 0 if earlier is None else earlier

    def _drain_decode(self, key: int) -> av.VideoFrame | None:
        """Seek to keyframe ``key``, feed packets up to its own, then drain the decoder.

        Retries from earlier keyframes if the seek lands too late. The decoder is left
        drained: the next access must seek (which flushes it).
        """
        want = self.index.pts_of(key)
        tol = self.index.default_tolerance
        target = key
        while True:
            self._container.seek(self.index.pts_of(target), stream=self._stream, backward=True)
            self.stats.seeks += 1
            first = True
            late = False
            for packet in self._container.demux(self._stream):
                if packet.pts is None:
                    continue
                if first:
                    first = False
                    late = packet.pts > want + tol and target > 0
                    if late:
                        break
                for vf in self._codec.decode(packet):
                    self.stats.decoded += 1
                    if self._position(vf) == key:
                        return vf
                if abs(packet.pts - want) <= tol:
                    break
            if not late:
                for vf in self._codec.decode(None):
                    self.stats.decoded += 1
                    if self._position(vf) == key:
                        return vf
                return None
            earlier = self.index.keyframe_at_or_before(target - 1)
            target = 0 if earlier is None else earlier

    def _continue(self) -> Iterator[tuple[av.VideoFrame, int]]:
        """Continue the live generator after ``self._last``."""
        frames = self._frames
        assert frames is not None
        for vf in frames:
            self.stats.decoded += 1
            pos = self._position(vf)
            if pos is None or (self._last is not None and pos <= self._last):
                continue
            self._last = pos
            yield vf, pos
        self._frames = None

    def _make(self, vf: av.VideoFrame, pos: int) -> DecodedFrame:
        self.stats.converted += 1
        return DecodedFrame(
            frame=pos,
            pts=self.index.pts_of(pos),
            keyframe=bool(self.index.keyframe[pos]),
            image=to_array(vf, format=self.format, size=self.size, stream=self.stream_color),
        )

    def _position(self, vf: av.VideoFrame) -> int | None:
        if vf.pts is None:
            return None
        pos = self.index.find_frame(vf.pts)
        return pos if pos is not None and pos < len(self.index) else None
