# SPDX-License-Identifier: GPL-3.0-or-later
"""YUV -> RGB conversion with the right matrix and range.

Every conversion passes the source matrix and range to swscale explicitly instead of
relying on defaults:
- A frame without color metadata gets swscale's default, BT.601 limited range, even for
  HD footage. Full-range BT.709 (what the XbotGo Falcon writes) rendered that way is up
  to 24 code values off, with crushed shadows and clipped highlights.
- PyAV 19 passes tagged frame metadata through, but its default rounding is up to 2 code
  values off, and the behavior has changed between PyAV versions.
- Callers can override the metadata when a stream is known to be mis-tagged.

Where color metadata comes from, in order (``stream_color``):
1. the bitstream (H.264/HEVC VUI), when it signals range or matrix;
2. otherwise the container (MP4 ``colr``, Matroska colour elements). This matters:
   ffmpeg's decoders tag frames as limited range whenever the bitstream is silent,
   overriding the container. The XbotGo Falcon writes full-range video with no range in
   the bitstream and ``colr`` = full range BT.709, so trusting the frames would render
   it with crushed shadows and clipped highlights;
3. otherwise the usual player conventions:
- range: ``yuvj*`` pixel formats are full range, everything else is limited (tv);
- matrix: BT.709 for HD and larger (width >= 1280 or height >= 720), BT.601 below.

8-bit output is within one code value of the reference BT.709/BT.601 math
(``tests/colorref.py``) for full and limited range, 8- and 10-bit input. ``rgb48le``
output from 10-bit input is within 0.6 (full range) and 1.1 (limited range) 8-bit code
values: swscale's 16-bit path is slightly less exact, whatever the flags. Use it only for
input deeper than 8 bits; from 8-bit input it is up to 2.3 off and adds nothing over
``rgb24``. ``tools/benchmarks/color_accuracy.py`` prints the full matrix.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace

import av
import numpy as np
from av.video.reformatter import ColorRange, Colorspace, Interpolation

#: Output formats ``to_array`` supports: 8-bit RGB/BGR and 16-bit RGB (for 10-bit input).
OUTPUT_FORMATS = ("rgb24", "bgr24", "rgb48le")


# ffmpeg AVColorSpace values -> (name, swscale matrix).
_MATRICES = {
    1: ("bt709", Colorspace.ITU709),
    4: ("fcc", Colorspace.FCC),
    5: ("bt601", Colorspace.ITU601),  # bt470bg
    6: ("bt601", Colorspace.ITU601),  # smpte170m
    7: ("smpte240m", Colorspace.SMPTE240M),
    9: ("bt2020", Colorspace.BT2020),  # bt2020nc
    10: ("bt2020", Colorspace.BT2020),  # bt2020c, approximated by the nc matrix
}
_BY_NAME = {name: cs for name, cs in _MATRICES.values()}

# 8-bit output: ACCURATE_RND alone is biased by up to -3 code values on limited range;
# together with full horizontal chroma interpolation it stays within one code value.
# Cost at 4K, on 16 threads: about 8 ms per frame, less than decoding the frame.
# 16-bit output: FULL_CHR_H_INT garbles rgb48 in swscale (ffmpeg 9.0.2), while
# ACCURATE_RND alone is already within one 8-bit code value there.
_INTERPOLATION = {
    "rgb24": Interpolation.BILINEAR | Interpolation.ACCURATE_RND | Interpolation.FULL_CHR_H_INT,
    "bgr24": Interpolation.BILINEAR | Interpolation.ACCURATE_RND | Interpolation.FULL_CHR_H_INT,
    "rgb48le": Interpolation.BILINEAR | Interpolation.ACCURATE_RND,
}


@dataclass(frozen=True)
class ColorInfo:
    """How to interpret a frame's YUV values."""

    #: "bt709", "bt601", "bt2020", "fcc", "smpte240m", or "rgb" for RGB pixel formats.
    matrix: str
    #: "pc" (full range) or "tv" (limited range).
    range: str
    #: True if the matrix or the range was not signalled and had to be guessed.
    guessed: bool = False


def resolve_color(
    *, colorspace: int | None, color_range: int | None, pix_fmt: str, width: int, height: int
) -> ColorInfo:
    """Resolve matrix and range from ffmpeg color metadata, guessing when unspecified."""
    guessed = False
    fmt = av.VideoFormat(pix_fmt)
    if fmt.is_rgb:
        return ColorInfo(matrix="rgb", range="pc")

    if color_range == 2 or (not color_range and pix_fmt.startswith("yuvj")):
        rng = "pc"
    elif color_range == 1:
        rng = "tv"
    else:
        rng, guessed = "tv", True

    if colorspace in _MATRICES:
        matrix = _MATRICES[int(colorspace)][0]
    else:
        matrix = "bt709" if width >= 1280 or height >= 720 else "bt601"
        guessed = True
    return ColorInfo(matrix=matrix, range=rng, guessed=guessed)


@dataclass(frozen=True)
class StreamColor:
    """Stream-level color that overrides what decoded frames claim (None: trust them)."""

    range: str | None = None
    matrix: str | None = None
    #: Where the overrides come from, for display ("container colr", ...).
    source: str = "frames"


#: Use the frames' own metadata (bitstream signals everything, or nothing is known).
TRUST_FRAMES = StreamColor()


def stream_color(path: str | os.PathLike[str]) -> StreamColor:
    """Container color for what the bitstream does not signal (see the module docs)."""
    from openpitch.core.video.structure import stream_structure

    with av.open(str(path)) as container:
        cc = container.streams.video[0].codec_context
        # Before the first decode these are the container's values (codecpar).
        c_range, c_space = cc.color_range, cc.colorspace
    structure = stream_structure(path)
    rng = matrix = None
    if not structure.signal_type and c_range in (1, 2):
        rng = "tv" if c_range == 1 else "pc"
    if not structure.colour_description and c_space in _MATRICES:
        matrix = _MATRICES[int(c_space)][0]
    if rng is None and matrix is None:
        return TRUST_FRAMES
    return StreamColor(range=rng, matrix=matrix, source="container")


def frame_color(frame: av.VideoFrame, stream: StreamColor = TRUST_FRAMES) -> ColorInfo:
    color = resolve_color(
        colorspace=frame.colorspace,
        color_range=frame.color_range,
        pix_fmt=frame.format.name,
        width=frame.width,
        height=frame.height,
    )
    if color.matrix == "rgb" or stream is TRUST_FRAMES:
        return color
    if stream.range is not None:
        color = replace(color, range=stream.range)
    if stream.matrix is not None:
        color = replace(color, matrix=stream.matrix)
    # Guessed only if something was still not known from bitstream or container.
    frame_range_known = bool(frame.color_range) and stream.range is None
    range_known = stream.range is not None or frame_range_known
    matrix_known = stream.matrix is not None or frame.colorspace in _MATRICES
    return replace(color, guessed=not (range_known and matrix_known))


def to_array(
    frame: av.VideoFrame,
    *,
    format: str = "rgb24",
    size: tuple[int, int] | None = None,
    color: ColorInfo | None = None,
    stream: StreamColor = TRUST_FRAMES,
) -> np.ndarray:
    """Convert a decoded frame to an ``(H, W, 3)`` RGB/BGR array, full range.

    ``size`` is ``(width, height)`` to scale in the same pass. ``stream`` is the
    stream-level color (``stream_color``); ``color`` overrides everything.
    """
    if format not in OUTPUT_FORMATS:
        raise ValueError(f"unsupported output format {format!r}, use one of {OUTPUT_FORMATS}")
    color = color or frame_color(frame, stream)
    width, height = size if size else (None, None)
    if color.matrix == "rgb":
        out = frame.reformat(
            width=width, height=height, format=format, interpolation=_INTERPOLATION[format]
        )
    else:
        out = frame.reformat(
            width=width,
            height=height,
            format=format,
            src_colorspace=_BY_NAME[color.matrix],
            dst_colorspace=_BY_NAME[color.matrix],
            src_color_range=ColorRange.JPEG if color.range == "pc" else ColorRange.MPEG,
            dst_color_range=ColorRange.JPEG,
            interpolation=_INTERPOLATION[format],
        )
    return out.to_ndarray()
