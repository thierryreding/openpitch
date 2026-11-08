# SPDX-License-Identifier: GPL-3.0-or-later
import os

import av
import numpy as np
import pytest

from colorref import PATCH_COLORS, sample_patches
from conftest import COLOR_SPECS
from openpitch.core.video import ColorInfo, VideoDecoder, resolve_color, to_array
from videogen import patches_frame

EXPECTED = PATCH_COLORS.astype(np.int64)


@pytest.mark.parametrize("name", sorted(COLOR_SPECS))
def test_decoded_colors_match_reference(color_videos, name):
    """Every encoded matrix/range/bit depth decodes within one code value."""
    with VideoDecoder(color_videos[name]) as dec:
        rgb = dec.decode_frame(0).image
    assert rgb.dtype == np.uint8 and rgb.shape[2] == 3
    assert np.abs(sample_patches(rgb) - EXPECTED).max() <= 1


@pytest.mark.parametrize(("name", "max_error"), [("hevc10_pc_709", 0.6), ("hevc10_tv_709", 1.1)])
def test_ten_bit_to_rgb48(color_videos, name, max_error):
    with VideoDecoder(color_videos[name], format="rgb48le") as dec:
        rgb = dec.decode_frame(0).image
    assert rgb.dtype == np.uint16
    # In 8-bit code values. swscale's 16-bit path is slightly less exact on limited range.
    assert np.abs(sample_patches(rgb) / 257 - EXPECTED).max() <= max_error


def test_bgr_output(color_videos):
    path = color_videos["h264_pc_709"]
    with VideoDecoder(path) as rgb_dec, VideoDecoder(path, format="bgr24") as bgr_dec:
        rgb = rgb_dec.decode_frame(0).image
        bgr = bgr_dec.decode_frame(0).image
    assert np.array_equal(rgb[..., ::-1], bgr)


def test_unsupported_output_format(color_videos):
    with pytest.raises(ValueError):
        VideoDecoder(color_videos["h264_pc_709"], format="yuv420p")


def test_full_range_bt709_yuv420p_frame():
    """Full range signalled on plain yuv420p (not yuvj), as newer decoders output it."""
    frame = patches_frame(matrix="bt709", full=True)
    frame.color_range = 2
    frame.colorspace = 1
    assert np.abs(sample_patches(to_array(frame)) - EXPECTED).max() <= 1


def test_untagged_full_range_needs_override():
    """Untagged frames get swscale's BT.601 limited default; overrides fix mis-tagging."""
    frame = patches_frame(matrix="bt709", full=True)
    assert frame.color_range == 0 and frame.colorspace == 2  # nothing signalled
    naive = sample_patches(frame.to_ndarray(format="rgb24"))
    assert np.abs(naive - EXPECTED).max() > 10  # the bug this module exists for
    fixed = to_array(frame, color=ColorInfo(matrix="bt709", range="pc"))
    assert np.abs(sample_patches(fixed) - EXPECTED).max() <= 1


def test_untagged_hd_frame_uses_bt709():
    patch, height = 160, 720  # 1280x720
    frame = patches_frame(matrix="bt709", full=False, patch=patch, height=height)
    assert (frame.width, frame.height) == (1280, 720)
    rgb = to_array(frame)
    assert np.abs(sample_patches(rgb, patch, height) - EXPECTED).max() <= 1
    naive = frame.to_ndarray(format="rgb24")
    assert np.abs(sample_patches(naive, patch, height) - EXPECTED).max() > 10


def test_scaled_output(color_videos):
    with VideoDecoder(color_videos["h264_tv_709"], size=(64, 8)) as dec:
        assert dec.decode_frame(0).image.shape == (8, 64, 3)


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        (
            dict(colorspace=1, color_range=2, pix_fmt="yuv420p", width=3840, height=2160),
            ColorInfo("bt709", "pc"),
        ),
        (
            dict(colorspace=1, color_range=1, pix_fmt="yuv420p10le", width=3840, height=2160),
            ColorInfo("bt709", "tv"),
        ),
        (
            dict(colorspace=6, color_range=1, pix_fmt="yuv420p", width=720, height=576),
            ColorInfo("bt601", "tv"),
        ),
        (
            dict(colorspace=5, color_range=2, pix_fmt="yuv420p", width=720, height=576),
            ColorInfo("bt601", "pc"),
        ),
        (
            dict(colorspace=9, color_range=1, pix_fmt="yuv420p10le", width=3840, height=2160),
            ColorInfo("bt2020", "tv"),
        ),
        # Unspecified: conventions, flagged as guessed.
        (
            dict(colorspace=2, color_range=0, pix_fmt="yuv420p", width=1920, height=1080),
            ColorInfo("bt709", "tv", guessed=True),
        ),
        (
            dict(colorspace=2, color_range=0, pix_fmt="yuv420p", width=640, height=480),
            ColorInfo("bt601", "tv", guessed=True),
        ),
        (
            dict(colorspace=2, color_range=0, pix_fmt="yuvj420p", width=640, height=480),
            ColorInfo("bt601", "pc", guessed=True),
        ),
        (
            dict(colorspace=1, color_range=0, pix_fmt="yuvj420p", width=1920, height=1080),
            ColorInfo("bt709", "pc"),
        ),
        (
            dict(colorspace=0, color_range=0, pix_fmt="gbrp", width=1920, height=1080),
            ColorInfo("rgb", "pc"),
        ),
    ],
)
def test_resolve_color(kwargs, expected):
    assert resolve_color(**kwargs) == expected


def test_rgb_input_passes_through():
    img = np.random.default_rng(0).integers(0, 256, (16, 32, 3), dtype=np.uint8)
    frame = av.VideoFrame.from_ndarray(img, format="rgb24")
    assert np.array_equal(to_array(frame), img)


# -- container color when the bitstream is silent (the Falcon case) -----------------


def test_container_color_wins_when_bitstream_is_silent(color_videos):
    from openpitch.core.video import stream_structure
    from openpitch.core.video.color import StreamColor, stream_color

    path = color_videos["h264_colr_pc_709"]
    structure = stream_structure(path)
    assert (structure.signal_type, structure.colour_description) == (False, False)
    assert stream_color(path) == StreamColor(range="pc", matrix="bt709", source="container")
    with VideoDecoder(path) as dec:
        assert np.abs(sample_patches(dec.decode_frame(0).image) - EXPECTED).max() <= 1


def test_stream_color_overrides_decoder_range_tag():
    """ffmpeg's HEVC decoder tags frames "tv" when the bitstream signals no range, even
    though the container says full range. The stream-level color must win."""
    from openpitch.core.video.color import StreamColor, frame_color

    frame = patches_frame(matrix="bt709", full=True)
    frame.color_range = 1  # what the decoder claims
    stream = StreamColor(range="pc", matrix="bt709", source="container")
    assert frame_color(frame).range == "tv"
    assert np.abs(sample_patches(to_array(frame)) - EXPECTED).max() > 10
    assert frame_color(frame, stream) == ColorInfo("bt709", "pc")
    assert np.abs(sample_patches(to_array(frame, stream=stream)) - EXPECTED).max() <= 1
    # Only the range from the container: the matrix is still guessed from the frame.
    partial = frame_color(frame, StreamColor(range="pc", source="container"))
    assert (partial.matrix, partial.range, partial.guessed) == ("bt601", "pc", True)


@pytest.mark.parametrize("name", ["hevc_pc_709", "h264_tv_601", "h264_untagged"])
def test_bitstream_color_is_trusted(color_videos, name):
    from openpitch.core.video.color import TRUST_FRAMES, stream_color

    # Signalled in the bitstream (or nothing anywhere): the frames' own tags are used.
    assert stream_color(color_videos[name]) is TRUST_FRAMES


@pytest.mark.skipif(
    not os.environ.get("OPENPITCH_TEST_FOOTAGE"),
    reason="set OPENPITCH_TEST_FOOTAGE to a real XbotGo Falcon recording",
)
def test_real_falcon_footage_is_full_range():
    """Opt-in check on real footage (never committed): full range comes from colr."""
    from openpitch.core.video import stream_structure
    from openpitch.core.video.color import stream_color

    path = os.environ["OPENPITCH_TEST_FOOTAGE"]
    assert stream_structure(path).signal_type is False
    color = stream_color(path)
    assert (color.range, color.matrix, color.source) == ("pc", "bt709", "container")
