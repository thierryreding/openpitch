# SPDX-License-Identifier: GPL-3.0-or-later
from fractions import Fraction

import av
import pytest
from click.testing import CliRunner

from openpitch.cli import main
from openpitch.core.video import build_frame_index, export_clip, plan_clip
from openpitch.core.video.clip import default_output, parse_range, parse_time, pts_at
from videogen import VideoSpec, frame_id, make_video


def _decoded_ids(path):
    with av.open(str(path)) as c:
        return [frame_id(f.to_ndarray(format="rgb24")) for f in c.decode(video=0)]


def _ranges(n):
    """Frame ranges covering the start, the end, single frames and GOP boundaries."""
    return [(0, 1), (0, n), (1, n - 1), (n // 3, n // 2), (n - 1, n), (n // 2, n // 2 + 1)]


@pytest.fixture(scope="module")
def with_audio(tmp_path_factory):
    path = tmp_path_factory.mktemp("clip") / "match.mp4"
    spec = VideoSpec(
        frames=60, gop=15, bframes=2, audio=True, metadata={"creation_time": "2026-11-08T14:03:10Z"}
    )
    return make_video(path, spec)


@pytest.fixture(scope="module")
def open_gop(tmp_path_factory):
    """Open GOPs (see SPECS["open_gop"]) with an audio track."""
    path = tmp_path_factory.mktemp("clip") / "open_gop.mp4"
    return make_video(path, VideoSpec(gop=15, bframes=3, codec="libx265", audio=True))


def test_clip_contains_exactly_the_snapped_frames(video, tmp_path):
    _, path, spec = video
    index = build_frame_index(path)
    for start, end in _ranges(spec.frames):
        plan = plan_clip(index, index.pts_of(start), index.pts_of(end))
        dst = tmp_path / f"clip_{start}_{end}.mp4"
        result = export_clip(path, dst, index.pts_of(start), index.pts_of(end), index=index)
        if spec.codec == "libx264":
            assert not result.extra_keyframe  # x264 GOPs are closed
        expected = list(range(plan.snapped.start, plan.snapped.end + result.extra_keyframe))
        assert _decoded_ids(dst) == expected
        assert result.frames == len(expected)
        assert (result.pts_in, result.pts_out) == (plan.pts_in, index.pts_of(expected[-1] + 1))

        # The clip starts at 0 and keeps the source's frame timing.
        out = build_frame_index(dst)
        assert len(out) == len(expected)
        assert out.pts_of(0) == 0
        src_pts = [index.pts_of(i) - plan.pts_in for i in expected]
        tol = index.default_tolerance
        assert all(
            abs(float(p * out.time_base) - float(q * index.time_base))
            <= float(tol * index.time_base)
            for p, q in zip(out.pts.tolist(), src_pts, strict=True)
        )
        assert out.keyframe[0]


def test_open_gop_keeps_leading_pictures_decodable(open_gop, tmp_path):
    index = build_frame_index(open_gop)
    extras = 0
    for start, end in [(20, 40), (0, 10), (31, 44), (50, 90), (15, 30)]:
        plan = plan_clip(index, index.pts_of(start), index.pts_of(end))
        dst = tmp_path / f"clip_{start}_{end}.mp4"
        result = export_clip(open_gop, dst, index.pts_of(start), index.pts_of(end), index=index)
        expected = list(range(plan.snapped.start, plan.snapped.end + result.extra_keyframe))
        # Every frame decodes to the right picture: no missing references at either end.
        assert _decoded_ids(dst) == expected
        assert result.frames == len(expected)
        if result.extra_keyframe:
            assert plan.snapped.end in set(index.keyframes.tolist())
            assert result.pts_out == index.pts_of(plan.snapped.end + 1)
        extras += result.extra_keyframe
    assert extras > 0  # the fixture really has open GOPs
    with av.open(str(dst)) as c:
        assert c.streams.video[0].codec_context.codec_tag == "hvc1"


def test_open_gop_audio_covers_the_added_keyframe(open_gop, tmp_path):
    index = build_frame_index(open_gop)
    dst = tmp_path / "clip.mp4"
    result = export_clip(open_gop, dst, index.pts_of(20), index.pts_of(40), index=index)
    assert result.extra_keyframe
    video_s = result.end_s - result.start_s  # 31 frames
    with av.open(str(dst)) as c:
        a = c.streams.audio[0]
        last = [p for p in c.demux(a) if p.pts is not None][-1]
        end = float((last.pts + last.duration) * a.time_base)
    assert video_s <= end < video_s + 0.022


def test_markers_snap_outward(with_audio, tmp_path):
    index = build_frame_index(with_audio)
    dst = tmp_path / "clip.mp4"
    result = export_clip(with_audio, dst, index.pts_of(20), index.pts_of(40), index=index)
    assert (result.marked_in, result.marked_out) == (index.pts_of(20), index.pts_of(40))
    assert (result.pts_in, result.pts_out) == (index.pts_of(15), index.pts_of(45))
    assert result.start_s == pytest.approx(0.5)
    assert result.end_s == pytest.approx(1.5)


@pytest.mark.parametrize("ext", [".mp4", ".mov", ".mkv"])
def test_audio_is_copied_and_in_sync(with_audio, tmp_path, ext):
    index = build_frame_index(with_audio)
    dst = tmp_path / f"clip{ext}"
    result = export_clip(with_audio, dst, index.pts_of(20), index.pts_of(40), index=index)
    assert result.audio == "copied"
    with av.open(str(dst)) as c:
        a = c.streams.audio[0]
        assert a.codec_context.name == "aac"
        packets = [p for p in c.demux(a) if p.pts is not None]
        first = float(packets[0].pts * a.time_base)
        last = packets[-1]
        end = float((last.pts + last.duration) * a.time_base)
    # Audio packets are not cut: at most one packet (21 ms) outside the 1 s of video.
    assert -0.022 < first <= 0
    assert 1.0 <= end < 1.022


def test_no_audio(with_audio, tmp_path):
    index = build_frame_index(with_audio)
    dst = tmp_path / "clip.mp4"
    result = export_clip(with_audio, dst, index.pts_of(0), index.pts_of(10), audio=False)
    assert result.audio == "none"
    with av.open(str(dst)) as c:
        assert not c.streams.audio


def test_creation_time_moves_to_clip_start(with_audio, tmp_path):
    index = build_frame_index(with_audio)
    dst = tmp_path / "clip.mp4"
    export_clip(with_audio, dst, pts_at(index, 1), pts_at(index, 2), index=index)
    with av.open(str(dst)) as c:
        assert c.metadata["creation_time"].startswith("2026-11-08T14:03:11")


def test_builds_the_index_when_not_given(with_audio, tmp_path):
    dst = tmp_path / "clip.mp4"
    index = build_frame_index(with_audio)
    result = export_clip(with_audio, dst, index.pts_of(30), index.end_pts)
    assert _decoded_ids(dst) == list(range(30, 60))
    assert result.frames == 30


def test_interrupted_export_leaves_nothing(with_audio, tmp_path):
    index = build_frame_index(with_audio)
    out = tmp_path / "out"
    out.mkdir()
    dst = out / "clip.mp4"

    def cancel(fraction):
        if fraction > 0.2:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        export_clip(with_audio, dst, index.pts_of(0), index.end_pts, progress=cancel)
    assert list(out.iterdir()) == []


def test_rejects_bad_outputs_and_ranges(with_audio, tmp_path):
    index = build_frame_index(with_audio)
    with pytest.raises(ValueError, match="extension"):
        export_clip(with_audio, tmp_path / "clip.avi", 0, index.end_pts, index=index)
    with pytest.raises(ValueError, match="overwrite"):
        export_clip(with_audio, with_audio, 0, index.end_pts, index=index)
    with pytest.raises(ValueError):
        export_clip(with_audio, tmp_path / "c.mp4", index.end_pts, index.end_pts + 1, index=index)
    with pytest.raises(ValueError, match="empty"):
        export_clip(with_audio, tmp_path / "c.mp4", 5000, 5000, index=index)


def test_parse_time_and_range():
    assert parse_time("12") == 12
    assert parse_time("1:23.5") == Fraction(167, 2)
    assert parse_time("1:02:03") == 3723
    assert parse_time(" 0:00.25 ") == Fraction(1, 4)
    assert parse_range("1:23-1:45") == (83, 105)
    for bad in ("", "1:2:3:4", "-5", "abc", "1,5"):
        with pytest.raises(ValueError):
            parse_time(bad)
    for bad in ("12", "5-3", "5-5"):
        with pytest.raises(ValueError):
            parse_range(bad)


def test_default_output(tmp_path):
    src = tmp_path / "game.MP4"
    assert default_output(src, 83, 105.5) == tmp_path / "game_000123-000145.mp4"
    assert default_output(src, 3723, 3800, tmp_path / "out").name == "game_010203-010320.mp4"
    assert default_output(tmp_path / "game.ts", 0, 1).suffix == ".mp4"


def test_cli_exports_and_dry_runs(with_audio, tmp_path):
    tmp_path = tmp_path / "out"  # the frame index cache lives in tmp_path
    runner = CliRunner()
    args = ["clip", str(with_audio), "0.7-1.3", "1:00.0-1:00.9", "-d", str(tmp_path)]
    result = runner.invoke(main, args)
    assert result.exit_code != 0  # starts after the end (the video is 2 s)
    assert "after the end" in result.output

    result = runner.invoke(main, ["clip", str(with_audio), "0.7-1.3", "-d", str(tmp_path), "-n"])
    assert result.exit_code == 0, result.output
    assert "0:00.500-0:01.500 (marked 0:00.700-0:01.300)" in result.output
    assert not tmp_path.exists()

    result = runner.invoke(main, ["clip", str(with_audio), "0.7-1.3", "1.5-2", "-d", str(tmp_path)])
    assert result.exit_code == 0, result.output
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == ["match_000000-000001.mp4", "match_000001-000002.mp4"]
    assert _decoded_ids(tmp_path / names[0]) == list(range(15, 45))

    result = runner.invoke(main, ["clip", str(with_audio), "0.7-1.3", "-d", str(tmp_path)])
    assert result.exit_code != 0 and "--force" in result.output


def test_cli_usage_errors(with_audio, tmp_path):
    runner = CliRunner()
    result = runner.invoke(main, ["clip", str(with_audio), "1-2", "0-1", "-o", "x.mp4"])
    assert result.exit_code == 2
    result = runner.invoke(main, ["clip", str(with_audio), "0.1-0.5", "0.2-0.6"])
    assert result.exit_code == 2 and "same output name" in result.output
    result = runner.invoke(main, ["clip", str(with_audio), "2-1"])
    assert result.exit_code == 2
    out = tmp_path / "a.mkv"
    result = runner.invoke(main, ["clip", str(with_audio), "0-0.5", "-o", str(out), "--no-audio"])
    assert result.exit_code == 0, result.output
    assert "audio none" in result.output and out.is_file()
