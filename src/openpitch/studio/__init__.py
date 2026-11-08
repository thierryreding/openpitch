# SPDX-License-Identifier: GPL-3.0-or-later
"""OpenPitch Studio: the PySide6 desktop application.

PySide6 is only imported in this package, and only once Studio starts, so that
`import openpitch.studio` works without the studio extra installed.
"""

import sys


def main() -> int:
    try:
        from PySide6.QtWidgets import QApplication, QLabel
    except ImportError:
        print("OpenPitch Studio needs the 'studio' extra: uv sync --extra studio", file=sys.stderr)
        return 1

    app = QApplication(sys.argv)
    label = QLabel("OpenPitch Studio")
    label.resize(480, 120)
    label.show()
    return app.exec()
