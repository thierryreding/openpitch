# SPDX-License-Identifier: GPL-3.0-or-later
"""The Studio calibration board window, on Qt's offscreen platform (no display needed)."""

import os

import pytest

pytest.importorskip("PySide6")
cv2 = pytest.importorskip("cv2")

from openpitch.core.camera import load_board  # noqa: E402
from openpitch.core.camera.board import cv_board  # noqa: E402


@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _settle(app, rounds=20):
    for _ in range(rounds):
        app.processEvents()


def test_board_window_writes_the_board_it_shows(app, tmp_path):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent

    from openpitch.studio.calibration import BoardWindow

    output = tmp_path / "board.png"
    window = BoardWindow(output, rows=7)
    window.showFullScreen()
    _settle(app)
    assert window.covers_screen()

    spec = load_board(tmp_path / "board.json")
    assert spec == window.saved == window.spec
    assert spec.image_px == window.physical_size()
    assert spec.squares[1] == 7 or spec.squares[0] == 7

    image = cv2.imread(str(output), cv2.IMREAD_GRAYSCALE)
    assert (image.shape[1], image.shape[0]) == spec.image_px
    _, ids, _, _ = cv2.aruco.CharucoDetector(cv_board(spec)).detectBoard(image)
    assert len(ids) == spec.inner_corners

    escape = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    window.keyPressEvent(escape)
    _settle(app)
    assert not window.isVisible()


def test_board_window_saves_nothing_before_it_covers_the_screen(app, tmp_path):
    from openpitch.studio.calibration import BoardWindow

    window = BoardWindow(tmp_path / "board.png")
    window.resize(640, 480)
    window.show()  # a normal window: never covers the screen
    _settle(app)
    assert window.spec is not None and window.saved is None
    assert not (tmp_path / "board.json").exists()
    window.close()


def test_studio_option_parsing():
    from openpitch.studio import _parse_args

    args = _parse_args(["--calibration-board", "--board-output", "x.png", "--board-rows", "6"])
    assert args.calibration_board and str(args.board_output) == "x.png" and args.board_rows == 6
    assert not _parse_args([]).calibration_board
