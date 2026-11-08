# SPDX-License-Identifier: GPL-3.0-or-later
"""Measured structure of a video: what the frame index says beyond the container."""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel, ConfigDict

from openpitch.core.video.index import FrameIndex
from openpitch.core.video.probe import VideoInfo


class GopStats(BaseModel):
    min: int
    median: float
    max: int


class VideoSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    info: VideoInfo
    content_hash: str | None
    frames: int
    duration_s: float
    frame_interval_pts: int
    #: Largest deviation of a frame's pts from a constant-rate timeline through the first
    #: and last frame. Small values are timestamp jitter, large ones mean variable rate.
    max_jitter_pts: int
    max_jitter_s: float
    keyframes: int
    starts_with_keyframe: bool
    #: GOP lengths in frames (keyframe to next keyframe or end of stream).
    gop_frames: GopStats
    gop_s: float


def summarize(info: VideoInfo, index: FrameIndex) -> VideoSummary:
    gops = np.diff(np.append(index.keyframes, len(index)))
    tb = index.time_base
    interval = index.frame_interval
    n = len(index)
    if n > 1:
        first, last = int(index.pts[0]), int(index.pts[-1])
        ideal = first + (last - first) * np.arange(n) / (n - 1)
        jitter = int(np.ceil(np.max(np.abs(index.pts - ideal))))
    else:
        jitter = 0
    median_gop = float(np.median(gops))
    return VideoSummary(
        info=info,
        content_hash=index.content_hash,
        frames=len(index),
        duration_s=float((index.end_pts - index.pts_of(0)) * tb),
        frame_interval_pts=interval,
        max_jitter_pts=jitter,
        max_jitter_s=float(jitter * tb),
        keyframes=len(index.keyframes),
        starts_with_keyframe=bool(index.keyframe[0]),
        gop_frames=GopStats(min=int(gops.min()), median=median_gop, max=int(gops.max())),
        gop_s=float(median_gop * interval * tb),
    )
