# SPDX-License-Identifier: GPL-3.0-or-later
"""OpenPitch Studio: the PySide6 desktop application.

PySide6 is only imported in this package, and only once Studio starts, so that
`import openpitch.studio` works without the studio extra installed.
"""

import argparse
import sys
from pathlib import Path


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="openpitch-studio", description="OpenPitch Studio")
    parser.add_argument(
        "--calibration-board",
        action="store_true",
        help="Show a camera calibration board full-screen and write it (image and"
        " description) for 'openpitch camera calibrate'. Esc or Q quits.",
    )
    parser.add_argument(
        "--board-output",
        type=Path,
        default=Path("charuco.png"),
        help="Board image to write; the description goes next to it as .json"
        " (default: charuco.png).",
    )
    parser.add_argument(
        "--board-rows", type=int, default=9, help="Squares on the short side (default: 9)."
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    try:
        from PySide6.QtWidgets import QApplication, QLabel
    except ImportError:
        print("OpenPitch Studio needs the 'studio' extra: uv sync --extra studio", file=sys.stderr)
        return 1

    if args.calibration_board:
        from openpitch.studio.calibration import show_board

        return show_board(args.board_output, args.board_rows)

    app = QApplication(sys.argv[:1])
    label = QLabel("OpenPitch Studio")
    label.resize(480, 120)
    label.show()
    return app.exec()
