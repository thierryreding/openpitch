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
