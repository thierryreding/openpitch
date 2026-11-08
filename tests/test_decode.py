# SPDX-License-Identifier: GPL-3.0-or-later
import random

import pytest

from conftest import SPECS
from openpitch.core.video import VideoDecoder, build_frame_index
from videogen import frame_id


def test_decode_every_frame_in_random_order(video):
    _, path, spec = video
    with VideoDecoder(path, cache_bytes=0) as dec:
        order = list(range(spec.frames))
        random.Random(7).shuffle(order)
        for n in order:
            got = dec.decode_frame(n)
            assert (got.frame, frame_id(got.image)) == (n, n)
            assert got.pts == dec.index.pts_of(n)
            assert got.keyframe == (n in spec.keyframe_set())


def test_decode_keyframe(video):
    _, path, spec = video
    keys = sorted(spec.keyframe_set())
    with VideoDecoder(path) as dec:
        for n in range(0, spec.frames, 7):
            expected = max(k for k in keys if k <= n)
            before = dec.stats.decoded
            got = dec.decode_keyframe(n)
            assert (got.frame, frame_id(got.image)) == (expected, expected)
            assert got.keyframe
            # Non-key frames are skipped: only a few keyframes come out of the codec.
            assert dec.stats.decoded - before <= 3


def test_forward_stepping_seeks_once_per_gop(videos):
    with VideoDecoder(videos["regular"]) as dec:  # keyframes every 30
        for n in range(30, 60):
            assert frame_id(dec.decode_frame(n).image) == n
        assert dec.stats.seeks == 1
        # Stepping into the next GOP seeks again.
        dec.decode_frame(61)
        assert dec.stats.seeks == 2


def test_stepping_back_hits_cache(videos):
    with VideoDecoder(videos["bframes"]) as dec:
        assert dec.cache_capacity > 20
        dec.decode_frame(25)  # decodes 15..25 and keeps them
        seeks = dec.stats.seeks
        for n in range(24, 14, -1):
            assert frame_id(dec.decode_frame(n).image) == n
        assert dec.stats.seeks == seeks
        assert dec.stats.cache_hits == 10


def test_cache_capacity_is_bounded(videos):
    frame_bytes = 64 * 48 * 3
    with VideoDecoder(videos["regular"], cache_bytes=4 * frame_bytes) as dec:
        assert dec.cache_capacity == 4
        dec.decode_frame(20)
        assert dec.stats.converted == 4  # only frames that stay cached are converted
        assert frame_id(dec.decode_frame(17).image) == 17
        assert dec.stats.cache_hits == 1
        seeks = dec.stats.seeks
        assert frame_id(dec.decode_frame(16).image) == 16  # evicted: decode again
        assert dec.stats.seeks == seeks + 1


def test_keyframe_then_frame(videos):
    """After keyframe-only decoding the decoder must not continue sequentially."""
    with VideoDecoder(videos["irregular"]) as dec:
        assert dec.decode_keyframe(45).frame == 41
        assert frame_id(dec.decode_frame(46).image) == 46
        assert frame_id(dec.decode_keyframe(80).image) == 75
        assert frame_id(dec.decode_frame(77).image) == 77


@pytest.mark.parametrize("name", sorted(SPECS))
def test_iter_frames_all(videos, name):
    with VideoDecoder(videos[name]) as dec:
        got = [(f.frame, frame_id(f.image)) for f in dec.iter_frames()]
    assert got == [(n, n) for n in range(SPECS[name].frames)]


@pytest.mark.parametrize(
    ("start", "end", "stride"),
    [(0, 90, 1), (8, 39, 1), (40, 41, 1), (13, 76, 5), (89, 90, 1), (0, 90, 30), (75, 90, 4)],
)
def test_iter_frames_ranges(videos, start, end, stride):
    with VideoDecoder(videos["irregular"]) as dec:
        got = [frame_id(f.image) for f in dec.iter_frames(start, end, stride=stride)]
    assert got == list(range(start, end, stride))


def test_iter_frames_edge_cases(videos):
    with VideoDecoder(videos["regular"]) as dec:
        assert list(dec.iter_frames(10, 10)) == []
        for args in [(-1, 5), (5, 4), (0, 91)]:
            with pytest.raises(ValueError):
                list(dec.iter_frames(*args))
        with pytest.raises(ValueError):
            list(dec.iter_frames(0, 10, stride=0))
        # Random access still works after (and in the middle of) a sequential read.
        it = dec.iter_frames(0, 90)
        next(it)
        assert frame_id(dec.decode_frame(50).image) == 50
        assert frame_id(dec.decode_frame(51).image) == 51


def test_out_of_range_frames(videos):
    with VideoDecoder(videos["regular"]) as dec:
        for n in (-1, 90):
            with pytest.raises(IndexError):
                dec.decode_frame(n)
            with pytest.raises(IndexError):
                dec.decode_keyframe(n)


def test_uses_given_index(videos, monkeypatch):
    from openpitch.core.video import decode

    index = build_frame_index(videos["jitter"])

    def no_load(*args, **kwargs):
        raise AssertionError("index should not be loaded")

    monkeypatch.setattr(decode, "load_frame_index", no_load)
    with VideoDecoder(videos["jitter"], index=index) as dec:
        assert dec.index is index
        assert frame_id(dec.decode_frame(44).image) == 44


class _LateSeek:
    """Container proxy whose first seek lands one GOP too late."""

    def __init__(self, container, shift):
        self._container = container
        self._shift = shift
        self.calls = 0

    def seek(self, pts, **kwargs):
        self.calls += 1
        if self.calls == 1:
            pts += self._shift
        return self._container.seek(pts, **kwargs)

    def __getattr__(self, name):
        return getattr(self._container, name)


def test_seek_landing_too_late_is_retried(videos):
    with VideoDecoder(videos["regular"]) as dec:
        proxy = _LateSeek(dec._container, shift=dec.index.pts_of(30))
        dec._container = proxy
        got = dec.decode_frame(35)
        assert frame_id(got.image) == 35
        assert proxy.calls == 2
