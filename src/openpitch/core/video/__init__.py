# SPDX-License-Identifier: GPL-3.0-or-later
"""Video access: metadata, frame index, pts <-> frame mapping, keyframe snapping."""

from openpitch.core.video.index import (
    FrameIndex,
    build_frame_index,
    index_cache_path,
    load_frame_index,
)
from openpitch.core.video.probe import VideoInfo, probe
from openpitch.core.video.snap import FrameRange, SnappedRange, snap_frames, snap_pts
from openpitch.core.video.summary import GopStats, VideoSummary, summarize

__all__ = [
    "FrameIndex",
    "FrameRange",
    "GopStats",
    "SnappedRange",
    "VideoInfo",
    "VideoSummary",
    "build_frame_index",
    "index_cache_path",
    "load_frame_index",
    "probe",
    "snap_frames",
    "snap_pts",
    "summarize",
]
