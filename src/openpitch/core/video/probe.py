# SPDX-License-Identifier: GPL-3.0-or-later
"""Container and stream metadata, read without decoding."""

from __future__ import annotations

import os
from fractions import Fraction
from pathlib import Path

import av
from pydantic import BaseModel, ConfigDict

from openpitch.core.video.provenance import ProvenanceStep, read_provenance

# ffmpeg AVColor* enum values -> the names ffprobe prints.
_COLOR_RANGE = {0: "unknown", 1: "tv", 2: "pc"}
_COLOR_SPACE = {
    0: "gbr",
    1: "bt709",
    2: "unknown",
    4: "fcc",
    5: "bt470bg",
    6: "smpte170m",
    7: "smpte240m",
    8: "ycgco",
    9: "bt2020nc",
    10: "bt2020c",
}
_COLOR_PRIMARIES = {
    1: "bt709",
    2: "unknown",
    4: "bt470m",
    5: "bt470bg",
    6: "smpte170m",
    7: "smpte240m",
    8: "film",
    9: "bt2020",
    11: "smpte431",
    12: "smpte432",
}
_COLOR_TRC = {
    1: "bt709",
    2: "unknown",
    4: "gamma22",
    5: "gamma28",
    6: "smpte170m",
    7: "smpte240m",
    8: "linear",
    13: "iec61966-2-1",
    14: "bt2020-10",
    15: "bt2020-12",
    16: "smpte2084",
    18: "arib-std-b67",
}


def _name(table: dict[int, str], value: int | None) -> str:
    if value is None:
        return "unknown"
    return table.get(int(value), str(int(value)))


class VideoInfo(BaseModel):
    """Metadata of the primary video stream of a file.

    Times are in stream ``time_base`` units. ``frame_count`` and ``duration_pts`` are
    what the container claims; the frame index (``FrameIndex``) is authoritative.
    """

    model_config = ConfigDict(frozen=True)

    path: str
    size: int
    container: str
    stream_index: int
    codec: str
    codec_tag: str | None
    profile: str | None
    width: int
    height: int
    pix_fmt: str | None
    bit_depth: int | None
    color_range: str
    color_space: str
    color_primaries: str
    color_trc: str
    time_base: Fraction
    start_pts: int | None
    duration_pts: int | None
    frame_count: int | None
    fps_avg: Fraction | None
    fps_nominal: Fraction | None
    has_b_frames: bool
    #: Lineage of a file made by ``clip`` or ``recode``, original first (decisions/0010).
    provenance: list[ProvenanceStep] = []


def probe(path: str | os.PathLike[str]) -> VideoInfo:
    """Read metadata of the first video stream. Raises ``ValueError`` if there is none."""
    path = Path(path)
    with av.open(str(path)) as container:
        if not container.streams.video:
            raise ValueError(f"{path}: no video stream")
        stream = container.streams.video[0]
        cc = stream.codec_context
        pix_fmt = cc.pix_fmt
        bit_depth = av.VideoFormat(pix_fmt).components[0].bits if pix_fmt else None
        tb = stream.time_base
        if tb is None:
            raise ValueError(f"{path}: video stream has no time base")
        duration = stream.duration
        if duration is None and container.duration is not None:
            # Container duration is in AV_TIME_BASE (microseconds).
            duration = round(Fraction(container.duration, 1_000_000) / tb)
        return VideoInfo(
            path=str(path),
            size=path.stat().st_size,
            container=container.format.name,
            stream_index=stream.index,
            codec=cc.name,
            codec_tag=getattr(cc, "codec_tag", None) or None,
            profile=cc.profile,
            width=cc.width,
            height=cc.height,
            pix_fmt=pix_fmt,
            bit_depth=bit_depth,
            color_range=_name(_COLOR_RANGE, cc.color_range),
            color_space=_name(_COLOR_SPACE, cc.colorspace),
            color_primaries=_name(_COLOR_PRIMARIES, cc.color_primaries),
            color_trc=_name(_COLOR_TRC, cc.color_trc),
            time_base=Fraction(tb),
            start_pts=stream.start_time,
            duration_pts=duration,
            frame_count=stream.frames or None,
            fps_avg=Fraction(stream.average_rate) if stream.average_rate else None,
            fps_nominal=Fraction(stream.base_rate) if stream.base_rate else None,
            has_b_frames=bool(cc.has_b_frames),
            provenance=read_provenance(dict(container.metadata)),
        )
