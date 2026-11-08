# SPDX-License-Identifier: GPL-3.0-or-later
from fractions import Fraction

import numpy as np
import pytest

from openpitch.core.video import FrameIndex, build_frame_index, probe


def test_probe(video):
    _, path, spec = video
    info = probe(path)
    assert (info.width, info.height) == (spec.width, spec.height)
    assert info.codec == "h264"
    assert info.pix_fmt == "yuv420p"
    assert info.bit_depth == 8
    assert info.time_base == spec.stream_time_base()
    assert info.fps_nominal == spec.fps
    assert abs(float(info.fps_avg) - spec.fps) < 0.01  # jitter skews the average
    assert info.frame_count == spec.frames
    assert info.has_b_frames == (spec.bframes > 0)


def test_index_matches_generated_structure(video):
    _, path, spec = video
    index = build_frame_index(path)
    assert len(index) == spec.frames
    assert index.pts.tolist() == spec.frame_pts()
    assert index.keyframes.tolist() == sorted(spec.keyframe_set())
    assert index.time_base == spec.stream_time_base()
    # The last frame lasts about one frame interval (give or take the jitter).
    slack = 2 * max(map(abs, spec.jitter or [0])) + 1
    last = index.end_pts - index.pts_of(len(index) - 1)
    assert abs(last - index.frame_interval) <= slack


def test_index_progress_reaches_one(videos):
    seen = []
    build_frame_index(videos["regular"], progress=seen.append)
    assert seen and seen[-1] == 1.0
    assert all(0.0 <= p <= 1.0 for p in seen)


def test_progress_callback_can_cancel(videos):
    class Cancelled(Exception):
        pass

    def cancel(_):
        raise Cancelled

    with pytest.raises(Cancelled):
        build_frame_index(videos["regular"], progress=cancel)


def test_index_rejects_non_video(tmp_path):
    path = tmp_path / "not-a-video.mp4"
    path.write_bytes(b"\0" * 1024)
    with pytest.raises(Exception):  # noqa: B017 - PyAV raises its own error types
        build_frame_index(path)


# -- pts <-> frame mapping ------------------------------------------------------------


def test_pts_of_and_find_frame_roundtrip(video):
    _, path, _ = video
    index = build_frame_index(path)
    for frame in range(len(index) + 1):
        assert index.find_frame(index.pts_of(frame)) == frame
    with pytest.raises(IndexError):
        index.pts_of(len(index) + 1)
    with pytest.raises(IndexError):
        index.pts_of(-1)


def test_nominal_timestamps_find_jittered_frames(videos):
    """Markers computed from nominal seconds land on the right jittered frame."""
    index = build_frame_index(videos["jitter_bframes"])
    for frame in range(len(index)):
        nominal = index.pts_from_seconds(Fraction(frame, 30))
        assert nominal != index.pts_of(frame) or frame % 7 == 0  # jitter is real
        assert index.find_frame(nominal) == frame
        assert index.frame_at(nominal) == frame
        assert index.boundary(nominal) == frame


def test_find_frame_tolerance(videos):
    index = build_frame_index(videos["regular"])  # 512 pts per frame
    p = index.pts_of(10)
    assert index.find_frame(p + 3, tolerance=3) == 10
    assert index.find_frame(p + 4, tolerance=3) is None
    assert index.find_frame(p - 255) == 10  # default tolerance: half a frame
    assert index.find_frame(p - 256) is None  # exactly between two frames: ambiguous
    assert index.find_frame(index.end_pts + 1) == len(index)
    with pytest.raises(ValueError):
        index.find_frame(p, tolerance=-1)


def test_frame_at_is_floor_with_tolerance(videos):
    index = build_frame_index(videos["regular"])
    p = index.pts_of(10)
    assert index.frame_at(p) == 10
    assert index.frame_at(p + 200) == 10  # the frame on screen
    assert index.frame_at(p + 300) == 11  # within tolerance (255) of the next frame
    assert index.frame_at(p + 300, tolerance=0) == 10
    assert index.frame_at(p + 511, tolerance=0) == 10
    assert index.frame_at(index.end_pts - 1, tolerance=0) == len(index) - 1
    with pytest.raises(ValueError):
        index.frame_at(index.end_pts)
    with pytest.raises(ValueError):
        index.frame_at(-1000)


def test_boundary(videos):
    index = build_frame_index(videos["regular"])
    p = index.pts_of(10)
    assert index.boundary(p) == 10
    assert index.boundary(p - 5) == 10
    assert index.boundary(p + 5) == 10
    assert index.boundary(p + 300) == 11  # frame 10 started before the boundary
    assert index.boundary(-10_000) == 0
    assert index.boundary(index.end_pts) == len(index)
    assert index.boundary(index.end_pts + 10_000) == len(index)


def test_seconds_conversion(videos):
    index = build_frame_index(videos["jitter"])
    assert index.pts_from_seconds(1.5) == 1_500_000
    assert index.seconds(1_500_000) == 1.5


def test_variable_frame_rate_mapping():
    # 30 fps, then a gap, then 60 fps (time base 1/1000).
    pts = np.array([0, 33, 67, 100, 500, 517, 533, 550], dtype=np.int64)
    index = FrameIndex(
        pts=pts, keyframe=np.ones(len(pts), bool), end_pts=567, time_base=Fraction(1, 1000)
    )
    assert index.frame_interval == 33  # median delta
    assert index.frame_at(300) == 3  # frame 3 stays on screen during the gap
    assert index.find_frame(300) is None
    assert index.find_frame(509) == 5
    assert index.boundary(300) == 4


@pytest.mark.parametrize(
    ("pts", "keyframe", "end_pts"),
    [
        ([], [], 1),  # empty
        ([0, 0], [True, False], 5),  # not strictly increasing
        ([0, 10], [True, False], 10),  # end_pts not after the last frame
        ([0, 10], [True], 20),  # length mismatch
    ],
)
def test_frame_index_validation(pts, keyframe, end_pts):
    with pytest.raises(ValueError):
        FrameIndex(
            pts=np.array(pts, np.int64),
            keyframe=np.array(keyframe, bool),
            end_pts=end_pts,
            time_base=Fraction(1, 1000),
        )
