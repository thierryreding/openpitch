# SPDX-License-Identifier: GPL-3.0-or-later
"""Export clips by stream copy: no re-encode, keyframe-snapped (docs/decisions/0006).

In/Out markers are pts on the source timeline, Out exclusive. They snap outward to
keyframes (``snap_pts``), so a clip never loses anything that was selected. Packets are
copied unchanged; only timestamps are shifted so the clip starts at 0.

Open GOPs (HEVC CRA, H.264 recovery points): frames shown just before a keyframe may be
decoded after it and reference it ("leading pictures"). If the snapped range ends at
such a keyframe, the clip also carries that keyframe, one frame more than selected,
because its leading pictures would not decode otherwise. Leading pictures of the first
keyframe are dropped: they come before In and reference the previous GOP.

Audio packets overlapping the clip are copied. Audio packets are not cut, so audio may
start or end up to one packet (about 21 ms for AAC at 48 kHz) outside the video; MP4
trims the start with an edit list.
"""

from __future__ import annotations

import datetime as _dt
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import av
from pydantic import BaseModel

from openpitch.core.video.index import FrameIndex, load_frame_index
from openpitch.core.video.snap import SnappedRange, snap_pts

#: Called with the fraction done (0.0 .. 1.0). It may raise to cancel.
ProgressCallback = Callable[[float], None]

#: File extension -> (ffmpeg muxer, muxer options).
_MUXERS: dict[str, tuple[str, dict[str, str]]] = {
    ".mp4": ("mp4", {"movflags": "+faststart"}),
    ".m4v": ("mp4", {"movflags": "+faststart"}),
    ".mov": ("mov", {"movflags": "+faststart"}),
    ".mkv": ("matroska", {"cues_to_front": "1"}),
}
EXTENSIONS = tuple(_MUXERS)

#: Audio codecs MP4/MOV carry (Matroska carries anything).
_MP4_AUDIO = {"aac", "mp3", "ac3", "eac3", "alac", "opus", "flac"}


class ClipResult(BaseModel):
    input: str
    output: str
    output_bytes: int
    #: The markers as given (source pts, Out exclusive).
    marked_in: int
    marked_out: int
    #: The copied range on the source timeline (keyframe-snapped, Out exclusive).
    pts_in: int
    pts_out: int
    #: Same in seconds from the first frame of the source.
    start_s: float
    end_s: float
    frames: int
    #: True if the keyframe at Out was added for the leading pictures before it.
    extra_keyframe: bool
    #: "copied", "none" (no audio track or not wanted) or "dropped" (container cannot
    #: carry the codec).
    audio: str
    seconds: float


@dataclass(frozen=True)
class _Plan:
    snapped: SnappedRange
    #: Exclusive end of the copied video, on the source timeline.
    pts_end: int


def output_format(dst: str | os.PathLike[str]) -> tuple[str, dict[str, str]]:
    """(ffmpeg muxer, options) for the file extension of ``dst``."""
    ext = Path(dst).suffix.lower()
    if ext not in _MUXERS:
        raise ValueError(f"unsupported output extension {ext!r}, use one of {EXTENSIONS}")
    muxer, options = _MUXERS[ext]
    return muxer, dict(options)


def plan_clip(
    index: FrameIndex, pts_in: int, pts_out: int, tolerance: int | None = None
) -> SnappedRange:
    """The range that ``export_clip`` copies for markers ``[pts_in, pts_out)``.

    This is what Studio shows as the snapped clip (docs/decisions/0006). For open-GOP
    footage the export may add one keyframe at the end (``ClipResult.extra_keyframe``).
    """
    return snap_pts(index, pts_in, pts_out, tolerance)


def export_clip(
    src: str | os.PathLike[str],
    dst: str | os.PathLike[str],
    pts_in: int,
    pts_out: int,
    *,
    index: FrameIndex | None = None,
    audio: bool = True,
    tolerance: int | None = None,
    progress: ProgressCallback | None = None,
) -> ClipResult:
    """Stream-copy the markers ``[pts_in, pts_out)`` of ``src`` to ``dst``.

    The output format follows the extension of ``dst`` (``EXTENSIONS``). Writes to a
    temporary name next to ``dst`` and renames it on success, so an interrupted export
    never leaves a truncated file behind.
    """
    src, dst = Path(src), Path(dst)
    muxer, mux_options = output_format(dst)
    if src.resolve() == dst.resolve():
        raise ValueError("output would overwrite the input")
    if index is None:
        index = load_frame_index(src)
    snapped = plan_clip(index, pts_in, pts_out, tolerance)

    tmp = dst.with_name(f".{dst.name}.partial")
    started = time.perf_counter()
    try:
        frames, extra, audio_mode = _copy(
            src, tmp, muxer, mux_options, index, snapped, audio, progress
        )
        os.replace(tmp, dst)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    first = index.pts_of(0)
    end = index.pts_of(snapped.snapped.end + 1) if extra else snapped.pts_out
    return ClipResult(
        input=str(src),
        output=str(dst),
        output_bytes=dst.stat().st_size,
        marked_in=pts_in,
        marked_out=pts_out,
        pts_in=snapped.pts_in,
        pts_out=end,
        start_s=index.seconds(snapped.pts_in - first),
        end_s=index.seconds(end - first),
        frames=frames,
        extra_keyframe=extra,
        audio=audio_mode,
        seconds=time.perf_counter() - started,
    )


def _copy(
    src: Path,
    tmp: Path,
    muxer: str,
    mux_options: dict[str, str],
    index: FrameIndex,
    snapped: SnappedRange,
    want_audio: bool,
    progress: ProgressCallback | None,
) -> tuple[int, bool, str]:
    k_in, k_out = snapped.pts_in, snapped.pts_out
    at_end = snapped.snapped.end == len(index)
    with av.open(str(src)) as inp, av.open(str(tmp), "w", format=muxer, options=mux_options) as out:
        vin = inp.streams[index.stream_index]
        if vin.type != "video":
            raise ValueError(f"{src}: stream {index.stream_index} is not video")
        ain = inp.streams.audio[0] if inp.streams.audio and want_audio else None
        audio_mode = "copied" if ain is not None else "none"
        if ain is not None and muxer != "matroska" and ain.codec_context.name not in _MP4_AUDIO:
            ain, audio_mode = None, "dropped"

        vout = out.add_stream_from_template(vin)
        if vin.codec_context.name == "hevc" and muxer in ("mp4", "mov"):
            vout.codec_context.codec_tag = "hvc1"  # Apple devices only play hvc1 in MP4
        aout = out.add_stream_from_template(ain) if ain is not None else None
        _copy_metadata(inp, out, index.seconds(k_in - index.pts_of(0)))

        vtb = vin.time_base
        start_time = k_in * vtb  # seconds on the source timeline
        a_shift = round(start_time / ain.time_base) if ain is not None else 0
        # Audio runs to the end of the video, one frame longer if the keyframe at Out is
        # added.
        end = snapped.snapped.end
        a_end = a_end_extra = 0
        if ain is not None:
            a_end = round(index.pts_of(end) * vtb / ain.time_base)
            a_end_extra = round(index.pts_of(min(end + 1, len(index))) * vtb / ain.time_base)

        frames = 0
        started = False
        video_done = False
        audio_done = ain is None
        pending_key: av.Packet | None = None  # keyframe at Out, kept back
        leading: list[av.Packet] = []  # its leading pictures (pts < Out)
        audio_tail: list[av.Packet] = []  # audio during the keyframe at Out

        def mux_video(packet: av.Packet) -> None:
            packet.pts -= k_in
            packet.dts -= k_in
            packet.stream = vout
            out.mux(packet)

        streams = [s for s in (vin, ain) if s is not None]
        for packet in _demux_from(inp, index, snapped, streams):
            if packet.stream is vin:
                if video_done or packet.pts is None or packet.dts is None or packet.is_discard:
                    continue
                # Packet pts are the values the index was built from, so they compare
                # exactly here (no tolerance needed).
                if not started:
                    if packet.pts != k_in:
                        continue  # before In in decode order
                    if not packet.is_keyframe:
                        raise ValueError(f"{src}: frame at pts {k_in} is not a keyframe")
                    started = True
                if not at_end and packet.dts >= k_out:
                    video_done = True  # dts <= pts, so nothing later is before Out
                    continue
                if packet.pts < k_in:
                    continue  # leading picture of the first keyframe
                if at_end or packet.pts < k_out:
                    if pending_key is not None:
                        leading.append(packet)
                    else:
                        mux_video(packet)
                        frames += 1
                    if progress is not None:
                        progress(min(0.999, (packet.pts - k_in) / max(1, k_out - k_in)))
                elif packet.pts == k_out and packet.is_keyframe:
                    pending_key = packet
            else:
                if audio_done or packet.pts is None or packet.dts is None:
                    continue
                end_pts = packet.pts + (packet.duration or 0)
                if end_pts <= a_shift or packet.is_discard:
                    continue
                if packet.pts >= a_end_extra:
                    audio_done = True
                    continue
                tail = packet.pts >= a_end  # kept only if the keyframe at Out is added
                packet.pts -= a_shift
                packet.dts -= a_shift
                packet.stream = aout
                if tail:
                    audio_tail.append(packet)
                else:
                    out.mux(packet)
            if video_done and audio_done:
                break
        if not started:
            raise ValueError(f"{src}: keyframe at pts {k_in} not found")

        extra = bool(leading)
        if extra:
            mux_video(pending_key)
            frames += 1
            for packet in leading:
                mux_video(packet)
                frames += 1
            for packet in audio_tail:
                out.mux(packet)
        if progress is not None:
            progress(1.0)
    return frames, extra, audio_mode


def _demux_from(inp, index: FrameIndex, snapped: SnappedRange, streams):
    """Demux from a little before the first keyframe of the clip.

    Seeks to the keyframe before it, so audio stored ahead of the keyframe in the file is
    read too. If the seek lands after the clip start, reads from the start of the file.
    """
    start = snapped.snapped.start
    before = index.keyframe_at_or_before(start - 1) if start > 0 else None
    if before is None:
        inp.seek(0)
        yield from inp.demux(*streams)
        return
    vin = inp.streams[index.stream_index]
    inp.seek(index.pts_of(before), stream=vin, backward=True)
    packets = inp.demux(*streams)
    first_video = None
    buffered = []
    for packet in packets:
        buffered.append(packet)
        if packet.stream is vin and packet.pts is not None:
            first_video = packet
            break
    if first_video is not None and first_video.pts > snapped.pts_in:
        inp.seek(0)
        yield from inp.demux(*streams)
        return
    yield from buffered
    yield from packets


def _copy_metadata(inp, out, offset_s: float) -> None:
    """Copy recording metadata. ``creation_time`` moves to the start of the clip."""
    for key in ("location", "com.apple.quicktime.location.ISO6709"):
        if key in inp.metadata:
            out.metadata[key] = inp.metadata[key]
    created = inp.metadata.get("creation_time")
    if not created:
        return
    try:
        when = _dt.datetime.fromisoformat(created.replace("Z", "+00:00"))
    except ValueError:
        out.metadata["creation_time"] = created
        return
    when += _dt.timedelta(seconds=offset_s)
    out.metadata["creation_time"] = when.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


_TIME = re.compile(r"^(?:(?:(\d+):)?(\d+):)?(\d+(?:\.\d*)?)$")


def parse_time(text: str) -> Fraction:
    """Seconds from ``SS``, ``MM:SS`` or ``H:MM:SS``, each with optional decimals."""
    m = _TIME.match(text.strip())
    if not m:
        raise ValueError(f"invalid time {text!r}, use SS, MM:SS or H:MM:SS")
    hours, minutes, seconds = m.groups()
    return int(hours or 0) * 3600 + int(minutes or 0) * 60 + Fraction(seconds)


def parse_range(text: str) -> tuple[Fraction, Fraction]:
    """``START-END`` (see ``parse_time``), END exclusive."""
    start, sep, end = text.partition("-")
    if not sep:
        raise ValueError(f"invalid range {text!r}, use START-END, e.g. 1:23-1:45")
    a, b = parse_time(start), parse_time(end)
    if a >= b:
        raise ValueError(f"empty range {text!r}: start is not before end")
    return a, b


def pts_at(index: FrameIndex, seconds: Fraction | float) -> int:
    """pts at ``seconds`` from the first frame of the video."""
    return index.pts_of(0) + index.pts_from_seconds(seconds)


def default_output(
    src: Path, start_s: Fraction | float, end_s: Fraction | float, output_dir: Path | None = None
) -> Path:
    """``<stem>_<HHMMSS>-<HHMMSS><ext>`` from the marked range, next to the input."""

    def stamp(s: Fraction | float) -> str:
        total = int(s)
        return f"{total // 3600:02d}{total // 60 % 60:02d}{total % 60:02d}"

    ext = src.suffix.lower() if src.suffix.lower() in _MUXERS else ".mp4"
    directory = output_dir if output_dir is not None else src.parent
    return directory / f"{src.stem}_{stamp(start_s)}-{stamp(end_s)}{ext}"
