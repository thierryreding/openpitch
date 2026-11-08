# SPDX-License-Identifier: GPL-3.0-or-later
"""Snap clip ranges to keyframes for stream-copy export (docs/decisions/0006).

A range is half-open, ``[in, out)``: the Out marker is exclusive. In snaps to the
previous keyframe and Out to the next one, so a snapped range always contains the
selected range. With all-intra footage snapping changes nothing.
"""

from __future__ import annotations

from dataclasses import dataclass

from openpitch.core.video.index import FrameIndex


@dataclass(frozen=True)
class FrameRange:
    """Half-open range of frame positions ``[start, end)``, ``0 <= start < end <= n``."""

    start: int
    end: int

    def __len__(self) -> int:
        return self.end - self.start


@dataclass(frozen=True)
class SnappedRange:
    selected: FrameRange
    snapped: FrameRange
    #: pts of the snapped range: ``pts_in`` is a keyframe, ``pts_out`` is exclusive
    #: (a keyframe, or ``end_pts`` at the end of the stream).
    pts_in: int
    pts_out: int


def snap_frames(index: FrameIndex, start: int, end: int) -> SnappedRange:
    """Snap a half-open frame range ``[start, end)`` outward to keyframes."""
    n = len(index)
    if not 0 <= start < end <= n:
        raise ValueError(f"invalid frame range [{start}, {end}) for {n} frames")
    snapped_start = index.keyframe_at_or_before(start)
    if snapped_start is None:
        # The stream does not start with a keyframe (e.g. cut mid-GOP). Nothing before
        # the first keyframe can be stream-copied, so start there.
        snapped_start = index.keyframe_at_or_after(start)
        if snapped_start >= end:
            raise ValueError(f"no keyframe in or before frames [{start}, {end})")
    snapped_end = index.keyframe_at_or_after(end) if end < n else n
    return SnappedRange(
        selected=FrameRange(start, end),
        snapped=FrameRange(snapped_start, snapped_end),
        pts_in=index.pts_of(snapped_start),
        pts_out=index.pts_of(snapped_end),
    )


def snap_pts(
    index: FrameIndex, pts_in: int, pts_out: int, tolerance: int | None = None
) -> SnappedRange:
    """Snap In/Out markers given as pts. Out is exclusive.

    A marker within ``tolerance`` of a frame start (default: half a frame) counts as
    exactly on that frame, so jittered or rounded timestamps of a marker on a keyframe
    do not pull in the previous GOP. An In marker inside a frame keeps that frame (it is
    on screen at In). An Out marker inside a frame keeps it too (it started before Out).
    In before the first frame clamps to the start, Out after the end to the end.
    """
    if pts_in >= index.end_pts:
        raise ValueError(f"In {pts_in} is at or after the end of the stream")
    start = 0 if pts_in <= index.pts_of(0) else index.frame_at(pts_in, tolerance)
    end = index.boundary(pts_out, tolerance)
    if start >= end:
        raise ValueError(f"empty range: In {pts_in} is not before Out {pts_out}")
    return snap_frames(index, start, end)
