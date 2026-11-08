# SPDX-License-Identifier: GPL-3.0-or-later
import av
import numpy as np
import pytest
from click.testing import CliRunner

from colorref import PATCH_COLORS, sample_patches
from openpitch.cli import main
from openpitch.core.video import VideoDecoder, build_frame_index
from openpitch.core.video.recode import (
    PROFILES,
    RecodeSettings,
    check_encoder,
    default_output,
    output_size,
    recode,
    resolve_encoder,
)
from videogen import VideoSpec, frame_id, make_video

# Pinned to software encoding and decoding, so results do not depend on the machine.
SOFTWARE = RecodeSettings(encoder="software", hwaccel=None)


@pytest.fixture(scope="module")
def with_audio(tmp_path_factory):
    path = tmp_path_factory.mktemp("recode") / "match.mp4"
    spec = VideoSpec(
        frames=60, gop=15, bframes=2, audio=True, metadata={"creation_time": "2026-11-08T14:03:10Z"}
    )
    return make_video(path, spec)


def _streams(path):
    with av.open(str(path)) as c:
        return {s.type: s.codec_context.name for s in c.streams}, dict(c.metadata)


def test_output_size():
    assert output_size(3840, 2160, 1080) == (1920, 1080)
    assert output_size(3840, 2160, 720) == (1280, 720)
    assert output_size(1920, 1080, 1080) == (1920, 1080)
    assert output_size(1280, 720, 1080) == (1280, 720)  # never upscales
    assert output_size(4000, 3000, 1080) == (1440, 1080)
    assert output_size(3840, 1634, 1080) == (2538, 1080)  # even width


def test_profiles_are_ordered():
    for family in ("x264", "x265", "nvenc"):
        values = [PROFILES[p][family] for p in ("high", "normal", "small", "tiny")]
        assert values == sorted(values)


def test_recode_keeps_frames_timestamps_audio_and_metadata(with_audio, tmp_path):
    dst = tmp_path / "out.mp4"
    result = recode(with_audio, dst, SOFTWARE)
    assert (result.width, result.height, result.frames) == (64, 48, 60)
    assert (result.codec, result.encoder, result.container) == ("h264", "libx264", "mp4")
    assert (result.quality, result.audio) == (PROFILES["normal"]["x264"], "copied")
    assert result.decoder == "software"
    assert not list(tmp_path.glob(".*partial"))

    streams, metadata = _streams(dst)
    assert streams == {"video": "h264", "audio": "aac"}
    assert metadata["creation_time"].startswith("2026-11-08T14:03:10")
    assert build_frame_index(dst).pts.tolist() == build_frame_index(with_audio).pts.tolist()
    with VideoDecoder(dst) as dec:
        assert [frame_id(f.image) for f in dec.iter_frames()] == list(range(60))


def test_recode_scales_and_tags_bt709_limited(videos, tmp_path):
    dst = tmp_path / "small.mp4"
    result = recode(
        videos["regular"], dst, RecodeSettings(height=24, encoder="software", hwaccel=None)
    )
    assert (result.width, result.height) == (32, 24)
    with av.open(str(dst)) as c:
        cc = c.streams.video[0].codec_context
        assert (cc.width, cc.height, cc.pix_fmt) == (32, 24, "yuv420p")
        assert (cc.color_range, cc.colorspace) == (1, 1)  # tv, bt709


@pytest.mark.parametrize(
    "name", ["h264_pc_709", "h264_tv_601", "hevc10_pc_709", "h264_colr_pc_709"]
)
def test_recode_converts_colors(color_videos, tmp_path, name):
    """Full-range, BT.601, 10-bit and container-tagged (Falcon-like) sources all end up
    correct as BT.709 limited range."""
    dst = tmp_path / "out.mp4"
    recode(color_videos[name], dst, RecodeSettings(quality=0, encoder="software", hwaccel=None))
    with VideoDecoder(dst) as dec:
        rgb = dec.decode_frame(0).image
    assert np.abs(sample_patches(rgb) - PATCH_COLORS).max() <= 3


@pytest.mark.parametrize(("mode", "expected"), [("aac", "aac"), ("none", "none")])
def test_audio_modes(with_audio, tmp_path, mode, expected):
    dst = tmp_path / "out.mp4"
    result = recode(with_audio, dst, RecodeSettings(audio=mode, encoder="software", hwaccel=None))
    assert result.audio == expected
    streams, _ = _streams(dst)
    assert ("audio" in streams) == (mode != "none")


def test_hevc_output(videos, tmp_path):
    dst = tmp_path / "out.mp4"
    settings = RecodeSettings(codec="hevc", encoder="software", hwaccel=None)
    result = recode(videos["bframes"], dst, settings)
    assert (result.encoder, result.quality) == ("libx265", PROFILES["normal"]["x265"])
    with av.open(str(dst)) as c:
        assert c.streams.video[0].codec_context.name == "hevc"
        assert c.streams.video[0].codec_tag == "hvc1"  # needed by Apple devices
    with VideoDecoder(dst) as dec:
        assert [frame_id(f.image) for f in dec.iter_frames()] == list(range(90))


@pytest.mark.parametrize("codec", ["h264", "hevc"])
def test_mkv_output(with_audio, tmp_path, codec):
    dst = tmp_path / "out.mkv"
    settings = RecodeSettings(codec=codec, encoder="software", container="mkv", hwaccel=None)
    result = recode(with_audio, dst, settings)
    assert (result.container, result.audio) == ("mkv", "copied")
    with av.open(str(dst)) as c:
        assert c.format.name.startswith("matroska")
        assert c.streams.video[0].codec_context.name == codec
        assert c.streams.audio[0].codec_context.name == "aac"
        assert c.metadata.get("creation_time", c.metadata.get("CREATION_TIME", "")).startswith(
            "2026-11-08"
        )
    # Matroska stores milliseconds: timestamps match the source to within 1 ms.
    src, out = build_frame_index(with_audio), build_frame_index(dst)
    src_s = src.pts * float(src.time_base)
    out_s = out.pts * float(out.time_base)
    assert np.abs(src_s - out_s).max() <= 0.001
    with VideoDecoder(dst) as dec:
        assert [frame_id(f.image) for f in dec.iter_frames()] == list(range(60))


def test_default_output_names(tmp_path):
    src = tmp_path / "VID_1.mp4"
    assert default_output(src, 1080).name == "VID_1_1080p.mp4"
    assert default_output(src, 720, tmp_path / "d", "mkv") == tmp_path / "d" / "VID_1_720p.mkv"


def test_cancel_leaves_nothing(with_audio, tmp_path):
    class Cancelled(Exception):
        pass

    def cancel(fraction):
        if fraction > 0.3:
            raise Cancelled

    dst = tmp_path / "out.mp4"
    with pytest.raises(Cancelled):
        recode(with_audio, dst, SOFTWARE, progress=cancel)
    assert list(tmp_path.iterdir()) == []


def test_invalid_settings(videos, tmp_path):
    src = videos["regular"]
    with pytest.raises(ValueError):
        recode(src, src, SOFTWARE)
    with pytest.raises(ValueError):
        recode(src, tmp_path / "x.mp4", RecodeSettings(profile="huge"))
    with pytest.raises(ValueError):
        recode(src, tmp_path / "x.mp4", RecodeSettings(encoder="vp9"))
    with pytest.raises(ValueError):
        recode(src, tmp_path / "x.mp4", RecodeSettings(codec="vp9"))
    with pytest.raises(ValueError):
        recode(src, tmp_path / "x.mp4", RecodeSettings(container="avi"))
    with pytest.raises(ValueError):
        recode(src, tmp_path / "x.mp4", RecodeSettings(audio="mp3"))


def test_encoder_selection():
    assert check_encoder("libx264")
    assert not check_encoder("no-such-encoder")
    assert resolve_encoder("h264", "auto")[0] in ("libx264", "h264_nvenc")
    assert resolve_encoder("hevc", "software") == ("libx265", "x265")
    # Below NVENC's minimum frame size, auto falls back to software.
    assert resolve_encoder("h264", "auto", (32, 24)) == ("libx264", "x264")
    assert resolve_encoder("hevc", "auto", (32, 24)) == ("libx265", "x265")
    defaults = RecodeSettings()
    assert (defaults.codec, defaults.encoder, defaults.container) == ("h264", "auto", "mp4")


def test_auto_encoder_on_tiny_frames(videos, tmp_path):
    result = recode(videos["regular"], tmp_path / "out.mp4", RecodeSettings(hwaccel=None))
    assert result.encoder == "libx264"


@pytest.mark.gpu
@pytest.mark.parametrize(("codec", "expected"), [("h264", "h264_nvenc"), ("hevc", "hevc_nvenc")])
def test_auto_encoder_prefers_nvenc(tmp_path, codec, expected):
    src = make_video(tmp_path / "src.mp4", VideoSpec(frames=10, width=256, height=160))
    assert resolve_encoder(codec, "auto", (256, 160)) == (expected, "nvenc")
    with pytest.raises(ValueError):
        resolve_encoder(codec, "nvenc", (32, 24))
    assert recode(src, tmp_path / "out.mp4", RecodeSettings(codec=codec)).encoder == expected


@pytest.mark.gpu
def test_nvenc(videos, tmp_path):
    dst = tmp_path / "out.mp4"
    # NVENC needs frames of at least 145x49 or so; scale nothing, use a big enough source.
    src = make_video(tmp_path / "src.mp4", VideoSpec(frames=30, width=256, height=160))
    result = recode(src, dst, RecodeSettings(encoder="nvenc", hwaccel="cuda"))
    assert result.encoder == "h264_nvenc"
    with VideoDecoder(dst) as dec:
        assert [frame_id(f.image) for f in dec.iter_frames()] == list(range(30))


# -- CLI ------------------------------------------------------------------------------


def test_cli_recode(with_audio, tmp_path):
    runner = CliRunner()
    out_dir = tmp_path / "share"
    args = ["recode", "--no-hwdec", "--encoder", "software", "-p", "small", "-d", str(out_dir)]
    args.append(str(with_audio))
    result = runner.invoke(main, args)
    assert result.exit_code == 0, result.output
    dst = default_output(with_audio, 1080, out_dir)
    assert dst.name == "match_1080p.mp4" and dst.is_file()
    assert f"h264/mp4, libx264 q{PROFILES['small']['x264']}" in result.output
    assert "audio copied" in result.output

    # Refuses to overwrite without --force.
    result = runner.invoke(main, args)
    assert result.exit_code == 1 and "--force" in result.output
    assert runner.invoke(main, [*args, "--force"]).exit_code == 0


def test_cli_recode_hevc_mkv(with_audio, tmp_path):
    args = ["recode", "--no-hwdec", "--encoder", "software", "--codec", "hevc"]
    result = CliRunner().invoke(
        main, [*args, "--container", "mkv", "-d", str(tmp_path), str(with_audio)]
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / "match_1080p.mkv").is_file()
    assert f"hevc/mkv, libx265 q{PROFILES['normal']['x265']}" in result.output


def test_cli_recode_usage_errors(videos, tmp_path):
    runner = CliRunner()
    two = [str(videos["regular"]), str(videos["bframes"])]
    result = runner.invoke(main, ["recode", "-o", str(tmp_path / "x.mp4"), *two])
    assert result.exit_code == 2
    result = runner.invoke(
        main, ["recode", "--crf", "20", "-o", str(videos["regular"]), str(videos["regular"]), "-f"]
    )
    assert result.exit_code == 1 and "overwrite the input" in result.output


@pytest.mark.parametrize("name", ["intra", "bframes"])
def test_output_gop_is_not_copied_from_source(videos, tmp_path, name):
    """Decoded frames carry their source picture type; encoders treat "I" as a forced
    keyframe. The output must get its own keyframe interval instead."""
    dst = tmp_path / "out.mp4"
    recode(videos[name], dst, SOFTWARE)
    source = set(build_frame_index(videos[name]).keyframes.tolist())
    output = set(build_frame_index(dst).keyframes.tolist())
    # Source: every frame (intra) or every 15th. Output: 5 s GOPs plus whatever scene cuts
    # the encoder finds in the noise, but not the source's keyframes.
    assert len(output) < len(source)
    assert len(output & source) <= 1  # frame 0 only
