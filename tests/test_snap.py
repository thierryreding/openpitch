# SPDX-License-Identifier: GPL-3.0-or-later
from fractions import Fraction

import numpy as np
import pytest

from openpitch.core.video import FrameIndex, FrameRange, build_frame_index, snap_frames, snap_pts


def _snap(index, start, end):
    return snap_frames(index, start, end).snapped


# Keyframes of the "irregular" video: 0, 7, 40, 41, 75 (90 frames).


@pytest.fixture(scope="module")
def irregular(videos):
    return build_frame_index(videos["irregular"])


@pytest.mark.parametrize(
    ("selected", "snapped"),
    [
        ((7, 40), (7, 40)),  # both markers exactly on keyframes: unchanged
        ((8, 39), (7, 40)),  # inside a GOP: outward to the enclosing keyframes
        ((6, 8), (0, 40)),  # spans a keyframe
        ((40, 41), (40, 41)),  # a one-frame GOP between adjacent keyframes
        ((41, 42), (41, 75)),
        ((0, 1), (0, 7)),  # In at file start
        ((80, 90), (75, 90)),  # Out at file end (exclusive end = frame count)
        ((76, 89), (75, 90)),  # Out inside the last GOP snaps to the end
        ((0, 90), (0, 90)),  # whole file
    ],
)
def test_snap_irregular_gops(irregular, selected, snapped):
    assert _snap(irregular, *selected) == FrameRange(*snapped)


def test_snapped_range_contains_selection(irregular):
    for start in range(len(irregular)):
        for end in range(start + 1, len(irregular) + 1):
            s = snap_frames(irregular, start, end)
            assert s.snapped.start <= start and s.snapped.end >= end
            assert irregular.keyframe[s.snapped.start]
            assert s.snapped.end == len(irregular) or irregular.keyframe[s.snapped.end]


def test_snap_is_noop_for_all_intra(videos):
    index = build_frame_index(videos["intra"])
    for start in range(len(index)):
        for end in range(start + 1, len(index) + 1):
            assert _snap(index, start, end) == FrameRange(start, end)


def test_snap_regular_and_bframes(videos):
    regular = build_frame_index(videos["regular"])  # keyframes every 30
    assert _snap(regular, 31, 59) == FrameRange(30, 60)
    assert _snap(regular, 30, 60) == FrameRange(30, 60)
    assert _snap(regular, 30, 61) == FrameRange(30, 90)
    bframes = build_frame_index(videos["bframes"])  # keyframes every 15
    assert _snap(bframes, 16, 29) == FrameRange(15, 30)
    assert _snap(bframes, 89, 90) == FrameRange(75, 90)


def test_snap_pts_values(irregular):
    s = snap_frames(irregular, 8, 39)
    assert s.pts_in == irregular.pts_of(7)
    assert s.pts_out == irregular.pts_of(40)
    end = snap_frames(irregular, 80, 90)
    assert end.pts_out == irregular.end_pts


def test_snap_rejects_invalid_ranges(irregular):
    for start, end in [(5, 5), (6, 5), (-1, 3), (0, 91)]:
        with pytest.raises(ValueError):
            snap_frames(irregular, start, end)


# -- markers given as pts -------------------------------------------------------------


def test_markers_on_jittered_keyframe(videos):
    """Markers from nominal seconds on a jittered keyframe do not pull in a GOP."""
    index = build_frame_index(videos["jitter_bframes"])  # keyframes 0, 12, 13, 50
    key = 12
    nominal = index.pts_from_seconds(Fraction(key, 30))
    assert nominal != index.pts_of(key)
    for delta in (-40, 0, 40):
        s = snap_pts(index, nominal + delta, index.pts_from_seconds(Fraction(50, 30)) + delta)
        assert s.snapped == FrameRange(12, 50)


def test_markers_at_file_start_and_end(irregular):
    s = snap_pts(irregular, irregular.pts_of(0), irregular.end_pts)
    assert s.snapped == FrameRange(0, len(irregular))
    s = snap_pts(irregular, -1000, irregular.end_pts + 1000)  # clamped
    assert s.snapped == FrameRange(0, len(irregular))


def test_out_marker_is_exclusive(irregular):
    # Out exactly on frame 40 (a keyframe) excludes frame 40.
    s = snap_pts(irregular, irregular.pts_of(8), irregular.pts_of(40))
    assert s.selected == FrameRange(8, 40)
    assert s.snapped == FrameRange(7, 40)
    # Out one frame later includes frame 40, so the next keyframe (41) ends the clip.
    s = snap_pts(irregular, irregular.pts_of(8), irregular.pts_of(41))
    assert s.snapped == FrameRange(7, 41)


def test_markers_mid_frame(irregular):
    # Without tolerance: In in the middle of keyframe 7 keeps frame 7, and Out in the
    # middle of frame 39 keeps frame 39 (it started before Out).
    half = irregular.frame_interval // 2
    pts_in, pts_out = irregular.pts_of(7) + half, irregular.pts_of(39) + half
    s = snap_pts(irregular, pts_in, pts_out, tolerance=0)
    assert s.selected == FrameRange(7, 40)
    assert s.snapped == FrameRange(7, 40)
    # With the default tolerance (half a frame minus one) a marker just past the middle
    # belongs to the next frame start.
    s = snap_pts(irregular, irregular.pts_of(7) + half + 1, irregular.pts_of(39) + half + 1)
    assert s.selected == FrameRange(8, 40)


def test_snap_pts_rejects_empty_and_out_of_range(irregular):
    p = irregular.pts_of(10)
    with pytest.raises(ValueError):
        snap_pts(irregular, p, p)
    with pytest.raises(ValueError):
        snap_pts(irregular, p + 10, p)
    with pytest.raises(ValueError):
        snap_pts(irregular, irregular.end_pts, irregular.end_pts + 100)


def test_stream_without_leading_keyframe():
    # E.g. a file cut mid-GOP: frames 0-2 cannot be stream-copied.
    pts = np.arange(10, dtype=np.int64) * 100
    key = np.zeros(10, bool)
    key[[3, 7]] = True
    index = FrameIndex(pts=pts, keyframe=key, end_pts=1000, time_base=Fraction(1, 3000))
    assert _snap(index, 0, 5) == FrameRange(3, 7)
    assert _snap(index, 4, 8) == FrameRange(3, 10)
    with pytest.raises(ValueError):
        snap_frames(index, 0, 3)
