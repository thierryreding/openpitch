# SPDX-License-Identifier: GPL-3.0-or-later
"""What this machine can do. Studio queries this to enable or disable features.

Hardware video decoding: ffmpeg's hwaccel device types, per platform in order of
preference. A device type being compiled into ffmpeg does not mean it works here (no
GPU, no driver, unsupported codec or profile), so ``check_hw_decode`` tries a real
decode.
"""

from __future__ import annotations

import os
import sys

import av
from av.codec.hwaccel import HWAccel, hwdevices_available

#: Preferred hardware decoders per platform (``sys.platform`` prefix).
HW_DECODE_PREFERENCE: dict[str, tuple[str, ...]] = {
    "linux": ("cuda", "vaapi", "qsv", "vulkan"),
    "win32": ("d3d11va", "cuda", "qsv", "d3d12va", "dxva2"),
    "darwin": ("videotoolbox",),
}


def hw_decode_candidates() -> list[str]:
    """Hardware decoders compiled into ffmpeg for this platform, most preferred first."""
    available = set(hwdevices_available())
    for prefix, preferred in HW_DECODE_PREFERENCE.items():
        if sys.platform.startswith(prefix):
            return [d for d in preferred if d in available]
    return []


#: Pixel formats of frames that live in device memory (AV_PIX_FMT_FLAG_HWACCEL).
_HW_PIX_FMTS = frozenset(
    {
        "cuda",
        "vaapi",
        "qsv",
        "d3d11",
        "d3d12",
        "dxva2_vld",
        "videotoolbox_vld",
        "vulkan",
        "drm_prime",
        "opencl",
        "vdpau",
        "mediacodec",
        "amf",
    }
)


def check_hw_decode(path: str | os.PathLike[str], device: str) -> bool:
    """True if ``device`` really decodes the first video frame of ``path`` in hardware.

    The frame must come out in device memory. A configured hardware context alone
    proves nothing: decoders fall back to software for unsupported codecs, profiles or
    frame sizes (NVDEC needs at least 144x144 for HEVC, for example).
    """
    if device not in hwdevices_available():
        return False
    accel = HWAccel(device, allow_software_fallback=False, is_hw_owned=True)
    try:
        with av.open(str(path), hwaccel=accel) as c:
            frame = next(c.decode(c.streams.video[0]))
            return frame.format.name in _HW_PIX_FMTS
    except Exception:
        return False


def select_hw_decoder(path: str | os.PathLike[str]) -> str | None:
    """The first hardware decoder that works for ``path``, or None for software."""
    for device in hw_decode_candidates():
        if check_hw_decode(path, device):
            return device
    return None
