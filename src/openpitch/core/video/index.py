# SPDX-License-Identifier: GPL-3.0-or-later
"""Frame index: presentation timestamps and keyframe flags of every frame.

Built by demuxing packets of the primary video stream, without decoding
(docs/decisions/0006). Container indexes (``Stream.index_entries``) are not used: for
MP4 they hold DTS, and with B-frames a keyframe's DTS is not its PTS.

Frame numbers are positions in presentation order, 0 .. n-1. Position ``n`` is the end
of the stream, so a half-open range ``[a, b)`` of frames can cover the last frame.
pts is the time truth. Lookups by pts always use a tolerance, because real footage has
jittered timestamps and markers may come from seconds rounded to the time base.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import av
import numpy as np

from openpitch.core.cache import cache_dir
from openpitch.core.fingerprint import fingerprint

#: Bump when the cached index format or its build rules change.
INDEX_VERSION = 1

#: Called with the fraction of the file read so far (0.0 .. 1.0). It may raise to cancel.
ProgressCallback = Callable[[float], None]


@dataclass(frozen=True, eq=False)
class FrameIndex:
    #: Presentation timestamps (stream time_base units), strictly increasing.
    pts: np.ndarray
    #: True for keyframes (frames a decode or a stream copy can start at).
    keyframe: np.ndarray
    #: Exclusive end of the last frame, in time_base units.
    end_pts: int
    time_base: Fraction
    stream_index: int = 0
    content_hash: str | None = None

    def __post_init__(self) -> None:
        if len(self.pts) == 0:
            raise ValueError("a frame index needs at least one frame")
        if len(self.pts) != len(self.keyframe):
            raise ValueError("pts and keyframe arrays differ in length")
        if len(self.pts) > 1 and not np.all(np.diff(self.pts) > 0):
            raise ValueError("pts must be strictly increasing")
        if self.end_pts <= int(self.pts[-1]):
            raise ValueError("end_pts must be after the last frame")
        object.__setattr__(self, "_keyframes", np.flatnonzero(self.keyframe))

    def __len__(self) -> int:
        return len(self.pts)

    # -- time base helpers ------------------------------------------------------------

    @property
    def frame_interval(self) -> int:
        """Typical frame duration in pts units (median of the frame deltas)."""
        if len(self.pts) > 1:
            return max(1, int(np.median(np.diff(self.pts))))
        return self.end_pts - int(self.pts[0])

    @property
    def default_tolerance(self) -> int:
        """Half a typical frame interval: the widest tolerance that is never ambiguous."""
        return max(0, (self.frame_interval - 1) // 2)

    def _tol(self, tolerance: int | None) -> int:
        tol = self.default_tolerance if tolerance is None else int(tolerance)
        if tol < 0:
            raise ValueError("tolerance must be >= 0")
        return tol

    def pts_from_seconds(self, seconds: float | Fraction) -> int:
        return round(Fraction(seconds) / self.time_base)

    def seconds(self, pts: int) -> float:
        return float(pts * self.time_base)

    # -- frame <-> pts ----------------------------------------------------------------

    def pts_of(self, frame: int) -> int:
        """pts of a frame. ``frame == len(self)`` gives ``end_pts``."""
        n = len(self.pts)
        if frame == n:
            return self.end_pts
        if not 0 <= frame < n:
            raise IndexError(f"frame {frame} out of range 0..{n}")
        return int(self.pts[frame])

    def find_frame(self, pts: int, tolerance: int | None = None) -> int | None:
        """Frame whose pts matches ``pts`` within ``tolerance``, else None.

        ``end_pts`` matches position ``len(self)``. The default tolerance is half a
        frame, so any pts closer to a frame start than to its neighbours matches it.
        """
        tol = self._tol(tolerance)
        bounds = self._bounds()
        i = int(np.searchsorted(bounds, pts))
        best = None
        for j in (i - 1, i):
            if 0 <= j < len(bounds):
                d = abs(int(bounds[j]) - pts)
                if d <= tol and (best is None or d < best[1]):
                    best = (j, d)
        return None if best is None else best[0]

    def frame_at(self, pts: int, tolerance: int | None = None) -> int:
        """Frame displayed at time ``pts`` (0 .. n-1).

        A pts within ``tolerance`` before a frame start counts as that frame, so jitter
        never shifts a marker to the previous frame. Raises ``ValueError`` outside
        ``[pts[0] - tolerance, end_pts)``.
        """
        tol = self._tol(tolerance)
        if pts < int(self.pts[0]) - tol or pts >= self.end_pts:
            raise ValueError(f"pts {pts} outside the stream")
        i = int(np.searchsorted(self.pts, pts + tol, side="right")) - 1
        return max(0, min(i, len(self.pts) - 1))

    def boundary(self, pts: int, tolerance: int | None = None) -> int:
        """Position (0 .. n) of a range boundary at ``pts``.

        Frames before the boundary start before ``pts``. A boundary within
        ``tolerance`` of a frame start lies exactly before that frame. This is the
        inclusive start of a range (In marker) and the exclusive end (Out marker).
        """
        tol = self._tol(tolerance)
        return int(np.searchsorted(self.pts, pts - tol, side="left"))

    def _bounds(self) -> np.ndarray:
        return np.append(self.pts, self.end_pts)

    # -- keyframes --------------------------------------------------------------------

    @property
    def keyframes(self) -> np.ndarray:
        """Frame numbers of all keyframes, ascending."""
        return self._keyframes  # type: ignore[attr-defined]

    def keyframe_at_or_before(self, frame: int) -> int | None:
        """Last keyframe at or before ``frame``, or None if there is none."""
        i = int(np.searchsorted(self.keyframes, frame, side="right")) - 1
        return int(self.keyframes[i]) if i >= 0 else None

    def keyframe_at_or_after(self, frame: int) -> int:
        """First keyframe at or after ``frame``, or ``len(self)`` (end) if none."""
        i = int(np.searchsorted(self.keyframes, frame, side="left"))
        return int(self.keyframes[i]) if i < len(self.keyframes) else len(self.pts)

    # -- persistence ------------------------------------------------------------------

    def save(self, path: str | os.PathLike[str]) -> None:
        np.savez(
            path,
            pts=self.pts,
            keyframe=self.keyframe,
            meta=np.array(
                [
                    self.end_pts,
                    self.time_base.numerator,
                    self.time_base.denominator,
                    self.stream_index,
                ],
                dtype=np.int64,
            ),
            content_hash=np.array(self.content_hash or ""),
        )

    @classmethod
    def load(cls, path: str | os.PathLike[str]) -> FrameIndex:
        with np.load(path, allow_pickle=False) as data:
            end_pts, num, den, stream_index = (int(x) for x in data["meta"])
            content_hash = str(data["content_hash"]) or None
            return cls(
                pts=data["pts"].astype(np.int64),
                keyframe=data["keyframe"].astype(bool),
                end_pts=end_pts,
                time_base=Fraction(num, den),
                stream_index=stream_index,
                content_hash=content_hash,
            )


def build_frame_index(
    path: str | os.PathLike[str],
    *,
    progress: ProgressCallback | None = None,
    content_hash: str | None = None,
) -> FrameIndex:
    """Demux the first video stream and index every presented frame.

    Packets without pts, empty packets and packets flagged as discarded (e.g. before an
    MP4 edit list start) are skipped. Reads the whole file, so it is I/O bound: about 3 s
    for 9 GB on NVMe, much longer on slow disks. See ``load_frame_index`` for the cache.
    """
    path = Path(path)
    size = max(1, path.stat().st_size)
    pts_list: list[int] = []
    key_list: list[bool] = []
    durations: dict[int, int] = {}
    with av.open(str(path)) as container:
        if not container.streams.video:
            raise ValueError(f"{path}: no video stream")
        stream = container.streams.video[0]
        time_base = Fraction(stream.time_base)
        for count, packet in enumerate(container.demux(stream)):
            if packet.pts is None or packet.size == 0 or packet.is_discard:
                continue
            pts_list.append(packet.pts)
            key_list.append(packet.is_keyframe)
            if packet.duration:
                durations[packet.pts] = packet.duration
            if progress is not None and count % 256 == 0 and packet.pos is not None:
                progress(min(1.0, packet.pos / size))
        stream_index = stream.index
    if not pts_list:
        raise ValueError(f"{path}: no video frames")

    pts = np.asarray(pts_list, dtype=np.int64)
    key = np.asarray(key_list, dtype=bool)
    order = np.argsort(pts, kind="stable")
    pts, key = pts[order], key[order]
    # Duplicate pts (broken muxers): keep one frame, keyframe if any copy is one.
    unique, first = np.unique(pts, return_index=True)
    if len(unique) != len(pts):
        key = np.logical_or.reduceat(key, first)
        pts = unique

    last = int(pts[-1])
    last_duration = durations.get(last) or (int(np.median(np.diff(pts))) if len(pts) > 1 else 1)
    if progress is not None:
        progress(1.0)
    return FrameIndex(
        pts=pts,
        keyframe=key,
        end_pts=last + max(1, last_duration),
        time_base=time_base,
        stream_index=stream_index,
        content_hash=content_hash,
    )


def index_cache_path(content_hash: str) -> Path:
    scheme, _, digest = content_hash.partition(":")
    return cache_dir() / "frame-index" / f"{scheme}-{digest}-v{INDEX_VERSION}.npz"


def load_frame_index(
    path: str | os.PathLike[str],
    *,
    cache: bool = True,
    progress: ProgressCallback | None = None,
) -> FrameIndex:
    """Frame index of a video, from the on-disk cache when possible (docs/decisions/0009).

    The cache is keyed by the content fingerprint, so it survives renames and copies to
    another path. A missing, stale or unreadable cache entry is rebuilt. Failing to
    write the cache (read-only disk) is not an error.
    """
    content_hash = fingerprint(path)
    entry = index_cache_path(content_hash)
    if cache and entry.is_file():
        try:
            index = FrameIndex.load(entry)
        except Exception:  # any unreadable cache entry is simply rebuilt
            index = None
        if index is not None and index.content_hash == content_hash:
            return index
    index = build_frame_index(path, progress=progress, content_hash=content_hash)
    if cache:
        try:
            entry.parent.mkdir(parents=True, exist_ok=True)
            tmp = entry.with_suffix(f".{os.getpid()}.tmp.npz")
            index.save(tmp)
            os.replace(tmp, entry)
        except OSError:
            pass
    return index
