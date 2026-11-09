# SPDX-License-Identifier: GPL-3.0-or-later
"""Re-encode footage to a smaller, widely playable file for sharing (e.g. 4K -> 1080p).

Codec, encoder and container are independent choices:
- codec: H.264 (default, plays everywhere) or HEVC (30-50% smaller at the same quality;
  needs the HEVC extension on Windows, plays natively on Apple devices);
- encoder: "auto" (NVENC when it works for the output size, else software), "software"
  (x264/x265) or "nvenc";
- container: MP4 (default; ``+faststart`` puts the index in front so it streams, and HEVC
  gets the ``hvc1`` tag Apple devices need) or MKV (cues in front; not playable on
  iPadOS/iOS or by QuickTime, and not on Google Drive's list of preview formats).

Video is converted to BT.709 limited range, what browsers, phones and tablets expect,
with the source's real matrix and range (``color``): full-range Falcon footage stays
correct. Source timestamps are kept (MKV rounds them to milliseconds). Audio is copied
when the container can carry it, else encoded to AAC. ``creation_time`` is copied, and the
output records its lineage (``provenance``).

Quality profiles map to a constant-quality value per encoder family (CRF for x264/x265,
CQ for NVENC); smaller numbers mean better quality and bigger files.
"""

from __future__ import annotations

import functools
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import av
from av.codec.hwaccel import HWAccel
from av.video.frame import PictureType
from av.video.reformatter import ColorRange, Colorspace, Interpolation
from pydantic import BaseModel

from openpitch.core.fingerprint import fingerprint
from openpitch.core.video.color import StreamColor, frame_color, stream_color
from openpitch.core.video.provenance import add_step, make_step

CODECS = ("h264", "hevc")
ENCODERS = ("auto", "software", "nvenc")
CONTAINERS = ("mp4", "mkv")

#: (codec, encoder) -> (ffmpeg encoder, family). Families share quality scales.
_FFMPEG_ENCODERS: dict[tuple[str, str], tuple[str, str]] = {
    ("h264", "software"): ("libx264", "x264"),
    ("hevc", "software"): ("libx265", "x265"),
    ("h264", "nvenc"): ("h264_nvenc", "nvenc"),
    ("hevc", "nvenc"): ("hevc_nvenc", "nvenc"),
}

#: Profile -> constant-quality value per encoder family, calibrated on real Falcon footage
#: (4K -> 1080p, default presets) so each row reaches the same VMAF: high 95.2,
#: normal 93.6, small 90.9, tiny 86.8. Above about 93 is generally indistinguishable from
#: the source in normal viewing. See docs/design/video.md and tools/benchmarks.
PROFILES: dict[str, dict[str, int]] = {
    "tiny": {"x264": 28, "x265": 28, "nvenc": 35},
    "small": {"x264": 25, "x265": 25, "nvenc": 32},
    "normal": {"x264": 22, "x265": 22, "nvenc": 29},
    "high": {"x264": 20, "x265": 19, "nvenc": 26},
}
DEFAULT_PROFILE = "normal"
DEFAULT_HEIGHT = 1080
DEFAULT_PRESET = {"x264": "fast", "x265": "fast", "nvenc": "p5"}
#: Default keyframe interval of the output, in seconds. Shorter intervals make files that
#: clip more precisely by stream copy, at a cost in size (on Falcon footage, NVENC H.264
#: "normal": +8% for 2 s, +23% for 1 s).
KEYFRAME_SECONDS = 5

#: Audio codecs MP4 carries as they are (MKV carries anything).
_MP4_AUDIO = {"aac", "mp3", "ac3", "eac3", "alac", "opus", "flac"}

#: Container -> (ffmpeg muxer, muxer options, file extension).
_CONTAINERS = {
    # use_metadata_tags: MP4 writes custom keys (provenance) only with it.
    "mp4": ("mp4", {"movflags": "+faststart+use_metadata_tags"}, ".mp4"),
    "mkv": ("matroska", {"cues_to_front": "1"}, ".mkv"),
}

_BT709 = 1
_TV = 1
_SWS_MATRIX = {
    "bt709": Colorspace.ITU709,
    "bt601": Colorspace.ITU601,
    "bt2020": Colorspace.BT2020,
    "fcc": Colorspace.FCC,
    "smpte240m": Colorspace.SMPTE240M,
}

#: Called with the fraction done (0.0 .. 1.0). It may raise to cancel.
ProgressCallback = Callable[[float], None]


@dataclass(frozen=True)
class RecodeSettings:
    height: int = DEFAULT_HEIGHT
    profile: str = DEFAULT_PROFILE
    codec: str = "h264"
    #: "auto" (NVENC if it works here for this output size, else software), "software"
    #: or "nvenc".
    encoder: str = "auto"
    container: str = "mp4"
    #: Overrides the profile's quality value.
    quality: int | None = None
    #: Encoder preset (x264/x265: ultrafast .. veryslow, NVENC: p1 .. p7).
    preset: str | None = None
    #: Hardware decoding: a device type, "auto" or None.
    hwaccel: str | None = "auto"
    #: "copy" (re-encode only if MP4 cannot carry it), "aac" or "none".
    audio: str = "copy"
    #: Longest distance between keyframes, in seconds. Encoders may add more at scene cuts.
    keyframe_seconds: float = KEYFRAME_SECONDS


class RecodeResult(BaseModel):
    input: str
    output: str
    input_bytes: int
    output_bytes: int
    width: int
    height: int
    codec: str
    #: The ffmpeg encoder used, e.g. "h264_nvenc" or "libx265".
    encoder: str
    container: str
    quality: int
    preset: str
    decoder: str  # "software" or the hardware device type
    audio: str  # "copied", "aac" or "none"
    frames: int
    duration_s: float
    seconds: float

    @property
    def ratio(self) -> float:
        return self.output_bytes / max(1, self.input_bytes)


def output_size(width: int, height: int, target_height: int) -> tuple[int, int]:
    """Scale to ``target_height`` keeping the aspect ratio. Never upscales. Even sizes."""
    if height <= target_height:
        h = height
        w = width
    else:
        h = target_height
        w = round(width * target_height / height)
    return max(2, w - w % 2), max(2, h - h % 2)


@functools.lru_cache(maxsize=32)
def check_encoder(name: str, size: tuple[int, int] = (256, 256)) -> bool:
    """True if the ffmpeg encoder ``name`` exists and really encodes ``size`` frames here.

    NVENC needs an NVIDIA GPU and driver, and has a minimum frame size. Results are
    cached for the process (each NVENC check opens an encoder session).
    """
    try:
        codec = av.codec.Codec(name, "w")
    except Exception:
        return False
    width, height = size
    try:
        cc = av.CodecContext.create(codec)
        cc.width, cc.height, cc.pix_fmt = width, height, "yuv420p"
        cc.time_base = Fraction(1, 30)
        frame = av.VideoFrame(width, height, "yuv420p")
        frame.pts = 0
        cc.encode(frame)
        cc.encode(None)
        return True
    except Exception:
        return False


def resolve_encoder(
    codec: str, encoder: str, size: tuple[int, int] = (1920, 1080)
) -> tuple[str, str]:
    """(ffmpeg encoder, family) for ``codec`` and ``encoder`` at output ``size``.

    "auto" prefers NVENC (several times faster) and falls back to software. An explicitly
    requested encoder that does not work here is an error.
    """
    if codec not in CODECS:
        raise ValueError(f"unknown codec {codec!r}, use one of {CODECS}")
    if encoder not in ENCODERS:
        raise ValueError(f"unknown encoder {encoder!r}, use one of {ENCODERS}")
    if encoder == "auto":
        nvenc = _FFMPEG_ENCODERS[(codec, "nvenc")]
        return nvenc if check_encoder(nvenc[0], size) else _FFMPEG_ENCODERS[(codec, "software")]
    chosen = _FFMPEG_ENCODERS[(codec, encoder)]
    if not check_encoder(chosen[0], size):
        raise ValueError(f"encoder {chosen[0]} does not work here for {size[0]}x{size[1]} frames")
    return chosen


def _encoder_options(family: str, quality: int, preset: str) -> dict[str, str]:
    if family == "x264":
        return {"crf": str(quality), "preset": preset}
    if family == "x265":
        return {"crf": str(quality), "preset": preset, "x265-params": "log-level=error"}
    # NVENC: constant quality (VBR with no bitrate target), lookahead for better quality.
    return {"rc": "vbr", "cq": str(quality), "b": "0", "preset": preset, "rc-lookahead": "20"}


def default_output(
    path: Path, height: int, output_dir: Path | None = None, container: str = "mp4"
) -> Path:
    directory = output_dir if output_dir is not None else path.parent
    return directory / f"{path.stem}_{height}p{_CONTAINERS[container][2]}"


def recode(
    src: str | os.PathLike[str],
    dst: str | os.PathLike[str],
    settings: RecodeSettings | None = None,
    *,
    progress: ProgressCallback | None = None,
) -> RecodeResult:
    """Re-encode ``src`` to ``dst``. Writes to a temporary name next to ``dst`` and
    renames it on success, so an interrupted run never leaves a truncated file behind.
    """
    src, dst = Path(src), Path(dst)
    settings = settings or RecodeSettings()
    if settings.profile not in PROFILES:
        raise ValueError(f"unknown profile {settings.profile!r}, use one of {list(PROFILES)}")
    if settings.audio not in ("copy", "aac", "none"):
        raise ValueError(f"unknown audio mode {settings.audio!r}")
    if not settings.keyframe_seconds > 0:
        raise ValueError(f"keyframe interval must be positive, not {settings.keyframe_seconds}")
    if settings.container not in CONTAINERS:
        raise ValueError(f"unknown container {settings.container!r}, use one of {CONTAINERS}")
    if src.resolve() == dst.resolve():
        raise ValueError("output would overwrite the input")
    with av.open(str(src)) as probe_container:
        cc = probe_container.streams.video[0].codec_context
        size = output_size(cc.width, cc.height, settings.height)
    ffmpeg_encoder, family = resolve_encoder(settings.codec, settings.encoder, size)
    quality = settings.quality
    if quality is None:
        quality = PROFILES[settings.profile][family]
    preset = settings.preset or DEFAULT_PRESET[family]

    hwaccel = settings.hwaccel
    if hwaccel:
        from openpitch.core.capabilities import check_hw_decode, select_hw_decoder

        if hwaccel == "auto":
            hwaccel = select_hw_decoder(src)
        elif not check_hw_decode(src, hwaccel):
            hwaccel = None

    tmp = dst.with_name(f".{dst.name}.partial")
    started = time.perf_counter()
    try:
        result = _recode(
            src, tmp, ffmpeg_encoder, family, quality, preset, hwaccel, settings, progress
        )
        os.replace(tmp, dst)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    width, height, frames, duration, audio = result
    return RecodeResult(
        input=str(src),
        output=str(dst),
        input_bytes=src.stat().st_size,
        output_bytes=dst.stat().st_size,
        width=width,
        height=height,
        codec=settings.codec,
        encoder=ffmpeg_encoder,
        container=settings.container,
        quality=quality,
        preset=preset,
        decoder=hwaccel or "software",
        audio=audio,
        frames=frames,
        duration_s=duration,
        seconds=time.perf_counter() - started,
    )


def _recode(
    src: Path,
    tmp: Path,
    ffmpeg_encoder: str,
    family: str,
    quality: int,
    preset: str,
    hwaccel: str | None,
    settings: RecodeSettings,
    progress: ProgressCallback | None,
) -> tuple[int, int, int, float, str]:
    accel = HWAccel(hwaccel, allow_software_fallback=True) if hwaccel else None
    source_color = stream_color(src)
    # The index goes in front (MP4 +faststart, MKV cues), so players can start before
    # the download ends.
    muxer, mux_options, _ = _CONTAINERS[settings.container]
    with (
        av.open(str(src), hwaccel=accel) as inp,
        av.open(str(tmp), "w", format=muxer, options=dict(mux_options)) as out,
    ):
        vin = inp.streams.video[0]
        if not hwaccel:
            vin.thread_type = "AUTO"
        ain = inp.streams.audio[0] if inp.streams.audio and settings.audio != "none" else None

        for key in ("creation_time", "location", "com.apple.quicktime.location.ISO6709"):
            if key in inp.metadata:
                out.metadata[key] = inp.metadata[key]
        # Timestamps are kept, so the step maps time without an offset.
        step = make_step(
            "recode",
            src,
            fingerprint(src),
            vin.codec_context.width,
            vin.codec_context.height,
            Fraction(vin.time_base),
            0,
        )
        add_step(inp.metadata, out.metadata, step)

        width, height = output_size(
            vin.codec_context.width, vin.codec_context.height, settings.height
        )
        tb = vin.time_base
        rate = vin.average_rate or vin.base_rate or 30
        vout = out.add_stream(ffmpeg_encoder, rate=rate)
        vout.width, vout.height = width, height
        vout.pix_fmt = "yuv420p"
        vout.time_base = tb
        cc = vout.codec_context
        cc.time_base = tb
        cc.color_range, cc.colorspace, cc.color_primaries, cc.color_trc = _TV, _BT709, 1, 1
        vout.options = _encoder_options(family, quality, preset)
        # A keyframe every few seconds: cheap, and players seek quickly.
        cc.gop_size = max(1, round(float(rate) * settings.keyframe_seconds))
        if settings.codec == "hevc" and settings.container == "mp4":
            cc.codec_tag = "hvc1"  # Apple devices only play HEVC in MP4 tagged hvc1

        audio_mode = "none"
        aout = None
        resampler = None
        if ain is not None:
            carries = settings.container == "mkv" or ain.codec_context.name in _MP4_AUDIO
            if settings.audio == "copy" and carries:
                aout = out.add_stream_from_template(ain)
                audio_mode = "copied"
            else:
                aout = out.add_stream("aac", rate=ain.codec_context.sample_rate or 48000)
                aout.options = {"b": "160k"}
                resampler = av.AudioResampler(
                    format="fltp", layout="stereo", rate=aout.codec_context.sample_rate
                )
                audio_mode = "aac"

        duration = vin.duration if vin.duration else None
        start = vin.start_time or 0
        frames = 0
        last_reported = -1.0
        streams = [s for s in (vin, ain) if s is not None]
        for packet in inp.demux(*streams):
            if packet.stream is ain:
                if aout is None:
                    continue
                if audio_mode == "copied":
                    if packet.dts is None:
                        continue
                    packet.stream = aout
                    out.mux(packet)
                else:
                    for aframe in packet.decode():
                        for resampled in resampler.resample(aframe):
                            for p in aout.encode(resampled):
                                out.mux(p)
                continue
            for frame in packet.decode():
                for p in vout.encode(_convert(frame, width, height, source_color)):
                    out.mux(p)
                frames += 1
                if progress is not None and duration and frame.pts is not None:
                    done = min(1.0, max(0.0, (frame.pts - start) / duration))
                    if done - last_reported >= 0.001:
                        progress(done)
                        last_reported = done
        for p in vout.encode(None):
            out.mux(p)
        if resampler is not None and aout is not None:
            for resampled in resampler.resample(None):
                for p in aout.encode(resampled):
                    out.mux(p)
            for p in aout.encode(None):
                out.mux(p)
        if progress is not None:
            progress(1.0)
        seconds = float(duration * tb) if duration else 0.0
    return width, height, frames, seconds, audio_mode


def _convert(frame: av.VideoFrame, width: int, height: int, source: StreamColor) -> av.VideoFrame:
    """Scale and convert to BT.709 limited-range yuv420p, keeping the frame's pts."""
    color = frame_color(frame, source)
    if color.matrix == "rgb":
        out = frame.reformat(
            width=width,
            height=height,
            format="yuv420p",
            dst_colorspace=Colorspace.ITU709,
            dst_color_range=ColorRange.MPEG,
            interpolation=Interpolation.BICUBIC | Interpolation.ACCURATE_RND,
        )
    else:
        out = frame.reformat(
            width=width,
            height=height,
            format="yuv420p",
            src_colorspace=_SWS_MATRIX[color.matrix],
            dst_colorspace=Colorspace.ITU709,
            src_color_range=ColorRange.JPEG if color.range == "pc" else ColorRange.MPEG,
            dst_color_range=ColorRange.MPEG,
            interpolation=Interpolation.BICUBIC | Interpolation.ACCURATE_RND,
        )
    out.pts = frame.pts
    # Decoded frames keep their source picture type, and encoders force a keyframe for
    # every frame marked I. Left alone, the output copies the source's GOP structure (or
    # is all keyframes for intra-only sources), which costs 30% or more in size.
    out.pict_type = PictureType.NONE
    out.time_base = frame.time_base
    out.color_range = _TV
    out.colorspace = _BT709
    return out
