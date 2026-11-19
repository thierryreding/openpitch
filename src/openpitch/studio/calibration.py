# SPDX-License-Identifier: GPL-3.0-or-later
"""Full-screen calibration board for camera calibration (docs/design/camera.md).

The board is made by ``openpitch.core.camera`` for the physical resolution of the screen
the window is on, whatever the desktop scaling, with the physical size Qt reports for
that screen. Its image and description are written for ``openpitch camera calibrate``.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QImage, QKeyEvent, QPainter, QPaintEvent, QPixmap, QResizeEvent
from PySide6.QtWidgets import QApplication, QWidget

from openpitch.core.camera import BoardSpec, available, make_board, save_board
from openpitch.core.camera.board import DEFAULT_ROWS, render


class BoardWindow(QWidget):
    """Shows a board filling the window; writes it to ``output`` once the window covers
    the screen, so the files match what is shown."""

    def __init__(self, output: Path, rows: int = DEFAULT_ROWS) -> None:
        super().__init__()
        self.output = output
        self.rows = rows
        self.spec: BoardSpec | None = None
        self.saved: BoardSpec | None = None
        self._pixmap: QPixmap | None = None
        self.setWindowTitle("OpenPitch calibration board")
        self.setCursor(Qt.CursorShape.BlankCursor)
        # If the window manager never makes the window full-screen, say so.
        self._watchdog = QTimer(self, singleShot=True, interval=2000)
        self._watchdog.timeout.connect(self._check_full_screen)

    def showEvent(self, event) -> None:
        self._watchdog.start()
        super().showEvent(event)

    def covers_screen(self) -> bool:
        """True once the window has the screen's size (within a pixel of rounding).

        The window state is no help: ``isFullScreen()`` is true as soon as full-screen
        is requested, before the window manager resizes the window, and some Wayland
        compositors give the window the screen's size without confirming the
        full-screen state, which clears it again.
        """
        screen = self.screen().size()
        return abs(self.width() - screen.width()) <= 1 and abs(self.height() - screen.height()) <= 1

    def _check_full_screen(self) -> None:
        if self.saved is None:
            screen = self.screen().size()
            print(
                f"the window is {self.width()}x{self.height()}, smaller than the screen"
                f" ({screen.width()}x{screen.height()}); nothing written. Make it"
                " full-screen with the window manager, or show the PNG from"
                " 'openpitch camera board' instead.",
                file=sys.stderr,
                flush=True,
            )

    def physical_size(self) -> tuple[int, int]:
        ratio = self.devicePixelRatioF()
        return round(self.width() * ratio), round(self.height() * ratio)

    def mm_per_px(self) -> float | None:
        """From the size the screen reports (EDID on most systems), if it reports one."""
        screen = self.screen()
        width_mm = screen.physicalSize().width()
        width_px = screen.size().width() * screen.devicePixelRatio()
        return width_mm / width_px if width_mm > 0 and width_px > 0 else None

    def resizeEvent(self, event: QResizeEvent) -> None:
        # Going full-screen can take several resizes: make the board for each size, and
        # save it once the window covers the screen.
        width, height = self.physical_size()
        if width < 64 or height < 64:
            return
        spec = make_board(width, height, mm_per_px=self.mm_per_px(), rows=self.rows)
        if spec != self.spec:
            self.spec = spec
            image = render(spec)
            qimage = QImage(image.data, width, height, width, QImage.Format.Format_Grayscale8)
            self._pixmap = QPixmap.fromImage(qimage.copy())
            self._pixmap.setDevicePixelRatio(self.devicePixelRatioF())
        if self.covers_screen() and spec != self.saved:
            spec_path = save_board(spec, self.output)
            self.saved = spec
            mm = f" = {spec.square_mm:.1f} mm" if spec.square_mm else ""
            print(
                f"{width}x{height} px: {spec.squares[0]}x{spec.squares[1]} squares of"
                f" {spec.square_px} px{mm}; board in {self.output}, description in"
                f" {spec_path}",
                flush=True,
            )

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("white"))
        if self._pixmap is not None:
            painter.drawPixmap(0, 0, self._pixmap)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_Q):
            self.close()


def show_board(output: Path, rows: int = DEFAULT_ROWS) -> int:
    """Run the board window until Esc or Q."""
    if not available():
        print("the calibration board needs the 'cv' extra: uv sync --extra cv", file=sys.stderr)
        return 1
    app = QApplication.instance() or QApplication(sys.argv[:1])
    window = BoardWindow(output, rows)
    window.showFullScreen()
    return app.exec()
