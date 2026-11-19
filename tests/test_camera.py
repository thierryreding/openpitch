# SPDX-License-Identifier: GPL-3.0-or-later
import json
import math
from fractions import Fraction

import av
import numpy as np
import pytest
from click.testing import CliRunner

from openpitch.cli import main
from openpitch.core.camera import load_board, load_profile, make_board
from openpitch.core.camera.board import layout

cv2 = pytest.importorskip("cv2")

#: The synthetic camera: 960x720, about 69 degrees horizontally.
SIZE = (960, 720)
K_TRUE = np.array([[700.0, 0, 480], [0, 700.0, 360], [0, 0, 1]])


def _rotation(rx, ry, rz):
    return cv2.Rodrigues(np.radians([rx, ry, rz]))[0]


def _board_video(path, spec, frames=36, seed=7):
    """Video of the board seen by K_TRUE (no distortion) from varied poses."""
    from openpitch.core.camera.board import cv_board

    cols, rows = spec.squares
    sq_px, margin = spec.square_px, spec.square_px // 2
    board_img = cv_board(spec).generateImage((cols * sq_px, rows * sq_px), marginSize=0)
    padded = cv2.copyMakeBorder(
        board_img, margin, margin, margin, margin, cv2.BORDER_CONSTANT, value=255
    )
    unit = 1.0 / sq_px  # board units (squares) per board pixel
    to_world = np.array([[unit, 0, -margin * unit], [0, unit, -margin * unit], [0, 0, 1]])
    center = np.array([cols / 2, rows / 2, 0])
    rng = np.random.default_rng(seed)
    with av.open(str(path), "w", format="mp4") as out:
        stream = out.add_stream("libx264", rate=30)
        stream.width, stream.height, stream.pix_fmt = *SIZE, "yuv420p"
        stream.options = {"qp": "0", "preset": "ultrafast"}
        for i in range(frames):
            R = _rotation(*rng.uniform(-35, 35, 2), rng.uniform(-10, 10))
            depth = rng.uniform(13, 18)
            target = np.array([rng.uniform(150, 810), rng.uniform(120, 600), 1.0])
            t = depth * np.linalg.inv(K_TRUE) @ target - R @ center
            H = K_TRUE @ np.column_stack([R[:, 0], R[:, 1], t]) @ to_world
            gray = cv2.warpPerspective(padded, H, SIZE, borderValue=110)
            frame = av.VideoFrame.from_ndarray(np.dstack([gray] * 3), format="rgb24")
            frame.pts = i
            for packet in stream.encode(frame):
                out.mux(packet)
        for packet in stream.encode(None):
            out.mux(packet)
    return path


@pytest.fixture(scope="module")
def board_files(tmp_path_factory):
    d = tmp_path_factory.mktemp("camera")
    result = CliRunner().invoke(
        main,
        [
            "camera",
            "board",
            "--size",
            "1280x800",
            "--screen-mm",
            "300x187.5",
            "--rows",
            "7",
            "-o",
            str(d / "board.png"),
        ],
    )
    assert result.exit_code == 0, result.output
    spec = load_board(d / "board.json")
    return d, spec, _board_video(d / "board.mp4", spec)


def test_layout_fills_the_screen():
    assert layout(2560, 1600) == (15, 9, 160)
    assert layout(1920, 1080) == (16, 9, 108)
    assert layout(1080, 1920) == (9, 16, 108)  # portrait
    with pytest.raises(ValueError):
        layout(100, 80)
    with pytest.raises(ValueError):
        make_board(3840, 2160, rows=40)  # more markers than the dictionary has


def test_board_files(board_files):
    d, spec, _ = board_files
    assert spec.squares == (11, 7)
    assert spec.square_px == 100
    assert spec.square_mm == pytest.approx(23.438, abs=1e-3)
    image = cv2.imread(str(d / "board.png"), cv2.IMREAD_GRAYSCALE)
    assert image.shape == (800, 1280)
    detector = cv2.aruco.CharucoDetector(
        __import__("openpitch.core.camera.board", fromlist=["cv_board"]).cv_board(spec)
    )
    _, ids, _, _ = detector.detectBoard(image)
    assert len(ids) == spec.inner_corners


def test_calibration_recovers_the_camera(board_files):
    from openpitch.core.camera import calibrate

    _, spec, video = board_files
    profile = calibrate(video, spec, stride=1, hwaccel=None)
    k = profile.intrinsics
    assert k.fx == pytest.approx(700, rel=0.01)
    assert k.fy == pytest.approx(700, rel=0.01)
    assert k.cx == pytest.approx(480, abs=6)
    assert k.cy == pytest.approx(360, abs=6)
    assert profile.distortion_model == "none"  # a pinhole camera needs no terms
    assert profile.rms_px < 0.5
    hfov = math.degrees(2 * math.atan(480 / 700))
    assert profile.fov.horizontal == pytest.approx(hfov, abs=0.5)
    assert (profile.mode.width, profile.mode.height) == SIZE
    assert Fraction(profile.mode.fps) == 30
    assert profile.mode.fov_setting is None and profile.camera.model is None  # not DJI
    assert [f.distortion_model for f in profile.fits] == ["none", "k1k2", "k1k2p1p2k3"]
    assert len(profile.coverage) == 6 and all(len(r) == 8 for r in profile.coverage)


def test_calibration_rejects_footage_without_the_board(videos, tmp_path):
    from openpitch.core.camera import calibrate

    spec = make_board(1280, 800, rows=7)
    with pytest.raises(ValueError, match="found in only"):
        calibrate(videos["regular"], spec, hwaccel=None)


def test_cli_calibrate_writes_a_profile(board_files, tmp_path):
    d, _, video = board_files
    out = tmp_path / "cam.json"
    args = [
        "camera",
        "calibrate",
        str(video),
        "-b",
        str(d / "board.json"),
        "-o",
        str(out),
        "--stride",
        "2",
        "--no-hwdec",
    ]
    result = CliRunner().invoke(main, args)
    assert result.exit_code == 0, result.output
    assert "* written to" in result.output and "*none" in result.output
    profile = load_profile(out)
    assert profile.intrinsics.fx == pytest.approx(700, rel=0.01)
    assert json.loads(out.read_text())["kind"] == "camera_profile"
    result = CliRunner().invoke(main, args)
    assert result.exit_code == 1 and "--force" in result.output
