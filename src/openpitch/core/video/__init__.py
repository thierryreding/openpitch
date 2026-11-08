# SPDX-License-Identifier: GPL-3.0-or-later
"""Video access: metadata, frame index, pts <-> frame mapping, keyframe snapping, decoding."""

from openpitch.core.video.color import ColorInfo, frame_color, resolve_color, to_array
from openpitch.core.video.decode import DecodedFrame, DecoderStats, VideoDecoder
from openpitch.core.video.index import (
    FrameIndex,
    build_frame_index,
    index_cache_path,
    load_frame_index,
)
from openpitch.core.video.probe import VideoInfo, probe
from openpitch.core.video.snap import FrameRange, SnappedRange, snap_frames, snap_pts
from openpitch.core.video.structure import StreamStructure, stream_structure
from openpitch.core.video.summary import GopStats, VideoSummary, summarize

__all__ = [
    "ColorInfo",
    "DecodedFrame",
    "DecoderStats",
    "VideoDecoder",
    "frame_color",
    "resolve_color",
    "to_array",
    "FrameIndex",
    "FrameRange",
    "GopStats",
    "SnappedRange",
    "StreamStructure",
    "VideoInfo",
    "VideoSummary",
    "build_frame_index",
    "index_cache_path",
    "load_frame_index",
    "probe",
    "snap_frames",
    "snap_pts",
    "stream_structure",
    "summarize",
]
