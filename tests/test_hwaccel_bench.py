# SPDX-License-Identifier: GPL-3.0-or-later
import json

import numpy as np
import pytest
from click.testing import CliRunner

from openpitch.cli import main
from openpitch.core import capabilities
from openpitch.core.video import VideoDecoder, stream_structure
from openpitch.core.video.bench import bench_file, parse_mode
from videogen import frame_id

# -- capabilities ---------------------------------------------------------------------


def test_hw_decode_candidates_are_compiled_in():
    from av.codec.hwaccel import hwdevices_available

    assert set(capabilities.hw_decode_candidates()) <= set(hwdevices_available())


def test_check_hw_decode_rejects_unknown_device(videos):
    assert capabilities.check_hw_decode(videos["regular"], "no-such-device") is False


def test_unusable_device_falls_back_to_threaded_software(videos):
    with VideoDecoder(videos["bframes"], hwaccel="no-such-device") as dec:
        assert dec.hwaccel is None
        assert frame_id(dec.decode_frame(33).image) == 33
        assert not dec.hardware


def test_auto_decodes_correctly_anywhere(videos):
    with VideoDecoder(videos["irregular"], hwaccel="auto") as dec:
        assert dec.hwaccel in (None, *capabilities.hw_decode_candidates())
        assert [frame_id(f.image) for f in dec.iter_frames(38, 44)] == list(range(38, 44))
        assert frame_id(dec.decode_keyframe(50).image) == 41


@pytest.mark.gpu
@pytest.mark.parametrize("name", ["bframes", "irregular", "jitter_bframes"])
def test_cuda_matches_software(videos, name):
    path = videos[name]
    with VideoDecoder(path, hwaccel="cuda") as hw, VideoDecoder(path) as sw:
        assert hw.hwaccel == "cuda"
        for n in (0, 7, 33, 41, 89):
            a, b = hw.decode_frame(n), sw.decode_frame(n)
            assert hw.hardware
            assert frame_id(a.image) == n
            assert np.array_equal(a.image, b.image)
        assert hw.decode_keyframe(50).frame == sw.decode_keyframe(50).frame


@pytest.mark.gpu
@pytest.mark.parametrize("pix_fmt", ["yuv420p", "yuv420p10le"])
@pytest.mark.parametrize("color_range", ["pc", "tv"])
def test_cuda_hevc_matches_software(tmp_path, pix_fmt, color_range):
    from videogen import VideoSpec, make_video

    # NVDEC needs at least 144x144 for HEVC.
    spec = VideoSpec(
        frames=20,
        gop=10,
        bframes=2,
        codec="libx265",
        width=256,
        height=160,
        pix_fmt=pix_fmt,
        color_range=color_range,
        matrix="bt709",
    )
    path = make_video(tmp_path / "hevc.mp4", spec)
    with VideoDecoder(path, hwaccel="cuda") as hw, VideoDecoder(path) as sw:
        assert hw.hardware
        for n in (0, 5, 13, 19):
            assert np.array_equal(hw.decode_frame(n).image, sw.decode_frame(n).image)
            assert frame_id(hw.decode_frame(n).image) == n


def test_auto_only_picks_a_working_device(color_videos):
    """Whatever auto picks (software, or e.g. VideoToolbox on macOS, which decodes even
    128x16 HEVC), frames decode with correct colors."""
    from colorref import PATCH_COLORS, sample_patches

    path = color_videos["hevc_pc_709"]
    with VideoDecoder(path, hwaccel="auto") as dec:
        assert dec.hardware == (dec.hwaccel is not None)
        if dec.hwaccel is not None:
            assert capabilities.check_hw_decode(path, dec.hwaccel)
        rgb = dec.decode_frame(0).image
    assert np.abs(sample_patches(rgb) - PATCH_COLORS).max() <= 1


@pytest.mark.gpu
def test_nvdec_minimum_frame_size_falls_back(color_videos):
    # NVDEC needs at least 144x144 for HEVC: 128x16 must not count as hardware decoding.
    path = color_videos["hevc_pc_709"]
    assert not capabilities.check_hw_decode(path, "cuda")
    with VideoDecoder(path, hwaccel="cuda") as dec:
        assert dec.hwaccel is None and not dec.hardware


# -- drained keyframe decode ----------------------------------------------------------


class _LateSeek:
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


def test_keyframe_seek_landing_too_late_is_retried(videos):
    with VideoDecoder(videos["bframes"]) as dec:
        proxy = _LateSeek(dec._container, shift=dec.index.pts_of(15))
        dec._container = proxy
        got = dec.decode_keyframe(35)
        assert (got.frame, frame_id(got.image)) == (30, 30)
        assert proxy.calls == 2


def test_keyframe_decode_drains_instead_of_filling_threads(videos):
    with VideoDecoder(videos["regular"], threads=8) as dec:
        dec.decode_keyframe(45)
        # One keyframe out of the codec, not one per decoder thread.
        assert dec.stats.decoded == 1


# -- stream structure -----------------------------------------------------------------


def test_structure_h264(videos):
    s = stream_structure(videos["regular"])
    assert (s.codec, s.wpp, s.tiles, s.slices) == ("h264", False, False, 1)
    assert s.intra_frame_parallel is False


def test_structure_hevc(color_videos):
    # x265 disables wavefronts for frames this small (a single CTU row).
    s = stream_structure(color_videos["hevc_pc_709"])
    assert (s.codec, s.wpp, s.tiles, s.slices) == ("hevc", False, False, 1)
    assert s.intra_frame_parallel is False


def test_structure_hevc_wavefronts(tmp_path):
    from videogen import VideoSpec, make_video

    spec = VideoSpec(frames=2, codec="libx265", width=256, height=256)
    path = make_video(tmp_path / "wpp.mp4", spec)
    s = stream_structure(path)
    assert (s.codec, s.wpp, s.slices) == ("hevc", True, 1)
    assert s.intra_frame_parallel is True


# -- benchmark ------------------------------------------------------------------------


def test_parse_mode():
    assert parse_mode("cpu") == (None, 0)
    assert parse_mode("cpu:4") == (None, 4)
    assert parse_mode("cuda") == ("cuda", 0)
    with pytest.raises(ValueError):
        parse_mode("cuda:4")
    with pytest.raises(ValueError):
        parse_mode("cpu:x")


def test_bench_file(videos):
    seen = []
    result = bench_file(
        videos["bframes"],
        ["cpu", "cpu:1", "no-such-device"],
        samples=2,
        frames=20,
        on_start=lambda r: seen.append(("start", len(r.modes))),
        on_result=lambda r: seen.append(r.mode),
    )
    assert seen == [("start", 0), "cpu", "cpu:1", "no-such-device"]
    assert (result.codec, result.frames, result.gop_frames) == ("h264", 90, 15.0)
    for mode in result.modes:
        assert mode.decode_fps > 0 and mode.rgb_fps > 0
        assert 0 < mode.scrub.median_ms <= mode.scrub.max_ms
        assert mode.step_ms > 0
    fallback = result.modes[2]
    assert fallback.device is None and not fallback.hardware
    assert fallback.max_diff_vs_cpu is None


def test_cli_bench_decode(videos):
    runner = CliRunner()
    args = ["bench-decode", "--mode", "cpu", "--samples", "2", "--frames", "10"]
    result = runner.invoke(main, [*args, str(videos["regular"]), str(videos["intra"])])
    assert result.exit_code == 0, result.output
    assert result.output.count("structure: WPP") == 2
    assert "software" in result.output

    result = runner.invoke(main, [*args, "--json", str(videos["regular"])])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data[0]["modes"][0]["mode"] == "cpu"

    result = runner.invoke(main, ["bench-decode", "--mode", "cuda:2", str(videos["regular"])])
    assert result.exit_code == 1
