# SPDX-License-Identifier: GPL-3.0-or-later
"""Camera calibration: ChArUco boards, intrinsics and distortion, camera profiles.

Not to be confused with pitch calibration (image to pitch homography, see
docs/design/pipeline.md). OpenCV comes from the ``cv`` extra and is imported lazily, so
``import openpitch.core.camera`` works without it.
"""

from openpitch.core.camera.board import (
    BoardSpec,
    available,
    load_board,
    make_board,
    save_board,
)
from openpitch.core.camera.calibrate import calibrate
from openpitch.core.camera.profile import CameraProfile, load_profile, save_profile

__all__ = [
    "BoardSpec",
    "CameraProfile",
    "available",
    "calibrate",
    "load_board",
    "load_profile",
    "make_board",
    "save_board",
    "save_profile",
]
