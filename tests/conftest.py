# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from fractions import Fraction
from pathlib import Path

import pytest

from videogen import VideoSpec, make_video

#: Synthetic videos covering the GOP structures and timestamp patterns that matter.
SPECS: dict[str, VideoSpec] = {
    # 3 s at 30 fps, keyframe every 30 frames, no B-frames.
    "regular": VideoSpec(),
    # Keyframe every 15 frames, 2 B-frames: decode order != presentation order.
    "bframes": VideoSpec(gop=15, bframes=2),
    # Every frame is a keyframe: snapping must be a no-op.
    "intra": VideoSpec(gop=1, frames=20),
    # Keyframes at irregular positions, incl. two adjacent ones, with B-frames.
    "irregular": VideoSpec(keyframes=[0, 7, 40, 41, 75], bframes=2),
    # Microsecond time base with jittered pts (like the Falcon), no B-frames.
    "jitter": VideoSpec(time_base=Fraction(1, 1_000_000), jitter=[0, 22, -15, 40, -31, 7]),
    # Jitter plus B-frames and irregular GOPs together.
    "jitter_bframes": VideoSpec(
        time_base=Fraction(1, 1_000_000),
        jitter=[0, 40, -25, 13, -40, 31, -8],
        keyframes=[0, 12, 13, 50],
        bframes=3,
    ),
    # HEVC with open GOPs: x265 writes CRA keyframes whose leading pictures (shown before
    # the keyframe, decoded after it) reference the previous GOP.
    "open_gop": VideoSpec(gop=15, bframes=3, codec="libx265"),
}


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    """Never touch the user's real cache directory."""
    monkeypatch.setenv("OPENPITCH_CACHE_DIR", str(tmp_path / "cache"))


@pytest.fixture(scope="session")
def videos(tmp_path_factory) -> dict[str, Path]:
    d = tmp_path_factory.mktemp("videos")
    return {name: make_video(d / f"{name}.mp4", spec) for name, spec in SPECS.items()}


@pytest.fixture(params=sorted(SPECS))
def video(request, videos) -> tuple[str, Path, VideoSpec]:
    """Each synthetic video in turn."""
    name = request.param
    return name, videos[name], SPECS[name]


#: Lossless color-patch videos for checking YUV -> RGB conversion.
COLOR_SPECS: dict[str, VideoSpec] = {
    # Like the Falcon: HEVC, full range, BT.709 (H.264 and HEVC decode it as yuvj420p).
    "hevc_pc_709": VideoSpec(
        frames=3,
        content="patches",
        lossless=True,
        codec="libx265",
        color_range="pc",
        matrix="bt709",
    ),
    "h264_pc_709": VideoSpec(
        frames=3, content="patches", lossless=True, color_range="pc", matrix="bt709"
    ),
    "h264_tv_709": VideoSpec(
        frames=3, content="patches", lossless=True, color_range="tv", matrix="bt709"
    ),
    "h264_tv_601": VideoSpec(
        frames=3, content="patches", lossless=True, color_range="tv", matrix="bt601"
    ),
    # No color metadata at all: SD size, so BT.601 limited by convention.
    "h264_untagged": VideoSpec(frames=3, content="patches", lossless=True),
    "hevc10_pc_709": VideoSpec(
        frames=3,
        content="patches",
        lossless=True,
        codec="libx265",
        pix_fmt="yuv420p10le",
        color_range="pc",
        matrix="bt709",
    ),
    # Like the XbotGo Falcon: full-range BT.709 pixels, nothing signalled in the bitstream,
    # range and matrix only in the MP4 colr atom. (ffmpeg's libx265 wrapper always writes
    # a signal type, so this case can only be generated with H.264. The HEVC decoder then
    # tags frames "tv", see test_color.py.)
    "h264_colr_pc_709": VideoSpec(
        frames=3,
        content="patches",
        lossless=True,
        data_range="pc",
        data_matrix="bt709",
        container_color=("pc", "bt709"),
    ),
    "hevc10_tv_709": VideoSpec(
        frames=3,
        content="patches",
        lossless=True,
        codec="libx265",
        pix_fmt="yuv420p10le",
        color_range="tv",
        matrix="bt709",
    ),
}


@pytest.fixture(scope="session")
def color_videos(tmp_path_factory) -> dict[str, Path]:
    d = tmp_path_factory.mktemp("color")
    return {name: make_video(d / f"{name}.mp4", spec) for name, spec in COLOR_SPECS.items()}
