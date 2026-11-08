# SPDX-License-Identifier: GPL-3.0-or-later
"""Bitstream structure: parallelism and what the bitstream itself signals about color.

Slice threading only helps if a frame is split into independently decodable parts:
HEVC wavefronts (WPP), tiles, or several slices. Frame threading works for any stream,
but delays output by one frame per thread.

Color: H.264/HEVC carry range and matrix in the VUI, but only if
``video_signal_type_present_flag`` / ``colour_description_present_flag`` are set. When
they are not, ffmpeg's decoders still tag every frame as limited range, overriding what
the container says (see ``color.stream_color``). The XbotGo Falcon writes no signal type.

Read with ffmpeg's ``trace_headers`` bitstream filter on the parameter sets and the first
packet, in-process.
"""

from __future__ import annotations

import os
import re
import threading

import av
import av.logging
from av.bitstream import BitStreamFilterContext
from pydantic import BaseModel

_LOG_LOCK = threading.Lock()
_FIELD = re.compile(r"^\s*\d+\s+(\w+)(?:\[[^\]]*\])?\s+\S+\s+=\s+(-?\d+)\s*$")


class StreamStructure(BaseModel):
    codec: str
    #: HEVC entropy_coding_sync_enabled_flag (wavefront parallel processing).
    wpp: bool | None = None
    #: HEVC/AV1 tiles.
    tiles: bool | None = None
    #: Slices (slice segments for HEVC) in the first frame.
    slices: int | None = None
    #: VUI video_signal_type_present_flag: the bitstream signals the range.
    signal_type: bool | None = None
    #: VUI video_full_range_flag (only meaningful when signal_type is set).
    full_range: bool | None = None
    #: VUI colour_description_present_flag: the bitstream signals matrix/primaries/transfer.
    colour_description: bool | None = None
    #: VUI matrix_coefficients (ffmpeg AVColorSpace value), when colour_description is set.
    matrix: int | None = None

    @property
    def intra_frame_parallel(self) -> bool | None:
        """True if slice threading can decode parts of one frame in parallel."""
        known = [v for v in (self.wpp, self.tiles) if v is not None]
        if self.slices is None and not known:
            return None
        return any(known) or (self.slices or 0) > 1


def _trace(path: str | os.PathLike[str]) -> tuple[str, list[str]]:
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        codec = stream.codec_context.name
        packet = next(p for p in container.demux(stream) if p.pts is not None and p.size)
        with _LOG_LOCK:
            previous = av.logging.get_level()
            av.logging.set_level(av.logging.VERBOSE)
            try:
                with av.logging.Capture() as logs:
                    bsf = BitStreamFilterContext("trace_headers", stream)
                    list(bsf.filter(packet))
                    list(bsf.filter(None))
            finally:
                av.logging.set_level(previous)
    lines = [str(m[2]) for m in logs if len(m) > 2 and m[1] == "trace_headers"]
    return codec, lines


def stream_structure(path: str | os.PathLike[str]) -> StreamStructure:
    """Parallelism-relevant structure of the first video stream. Unknown fields are None."""
    try:
        codec, lines = _trace(path)
    except Exception:
        with av.open(str(path)) as container:
            return StreamStructure(codec=container.streams.video[0].codec_context.name)
    fields: dict[str, list[int]] = {}
    for line in lines:
        m = _FIELD.match(line)
        if m:
            fields.setdefault(m.group(1), []).append(int(m.group(2)))

    def flag(name: str) -> bool | None:
        values = fields.get(name)
        return None if values is None else any(values)

    def value(name: str) -> int | None:
        values = fields.get(name)
        return values[0] if values else None

    if codec not in ("hevc", "h264"):
        return StreamStructure(codec=codec)
    # Without VUI, nothing is signalled (the flags are absent from the trace).
    vui = flag("vui_parameters_present_flag")
    signal_type = flag("video_signal_type_present_flag") if vui else False
    colour = flag("colour_description_present_flag") if signal_type else False
    color = dict(
        signal_type=bool(signal_type),
        full_range=flag("video_full_range_flag") if signal_type else None,
        colour_description=bool(colour),
        matrix=value("matrix_coefficients") if colour else None,
    )
    if codec == "hevc":
        slices = len(fields.get("first_slice_segment_in_pic_flag", [])) or None
        return StreamStructure(
            codec=codec,
            wpp=flag("entropy_coding_sync_enabled_flag"),
            tiles=flag("tiles_enabled_flag"),
            slices=slices,
            **color,
        )
    slices = len(fields.get("first_mb_in_slice", [])) or None
    return StreamStructure(codec=codec, wpp=False, tiles=False, slices=slices, **color)
