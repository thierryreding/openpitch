# SPDX-License-Identifier: GPL-3.0-or-later
"""Camera profiles: the calibration of one camera in one recording mode.

A profile is a JSON file (``CameraProfile``). It holds a pinhole model with OpenCV's
distortion coefficients, the mode it was calibrated in (resolution, frame rate, and the
camera's FOV and stabilization settings where the metadata records them), the fit, and
where it came from. Profiles are per mode: a lens setting, stabilization (which crops)
or a different resolution needs its own profile. See docs/design/camera.md.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from openpitch.core.camera.board import BoardSpec

#: Distortion models, simplest first. Coefficients are always stored in OpenCV order
#: (k1, k2, p1, p2, k3), with zeros for terms a model does not use.
DISTORTION_MODELS = ("none", "k1k2", "k1k2p1p2k3")
PROFILE_VERSION = 1


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class Intrinsics(_Frozen):
    """Pinhole camera matrix in source pixels."""

    fx: float
    fy: float
    cx: float
    cy: float


class FieldOfView(_Frozen):
    """Degrees, after undistortion: between opposite edge midpoints, and corners."""

    horizontal: float
    vertical: float
    diagonal: float


class Fit(_Frozen):
    distortion_model: Literal["none", "k1k2", "k1k2p1p2k3"]
    rms_px: float
    frame_rms_median_px: float
    frame_rms_max_px: float
    intrinsics: Intrinsics
    distortion: list[float]
    fov: FieldOfView


class CameraInfo(_Frozen):
    """From the recording's metadata where it has any (DJI ``CAM meta``)."""

    model: str | None = None
    serial: str | None = None
    firmware: str | None = None


class CameraMode(_Frozen):
    width: int
    height: int
    #: Frame rate as a fraction, e.g. "60000/1001".
    fps: str | None = None
    #: Camera FOV setting, e.g. "standard" (DJI Standard (Dewarp)); None if unknown.
    fov_setting: str | None = None
    #: Electronic stabilization (it crops); None if unknown.
    stabilization: bool | None = None


class SourceRef(_Frozen):
    content_hash: str
    file_name: str


class CameraProfile(_Frozen):
    kind: Literal["camera_profile"] = "camera_profile"
    version: int = PROFILE_VERSION
    camera: CameraInfo
    mode: CameraMode
    intrinsics: Intrinsics
    distortion_model: Literal["none", "k1k2", "k1k2p1p2k3"]
    #: OpenCV order (k1, k2, p1, p2, k3).
    distortion: list[float]
    rms_px: float
    fov: FieldOfView
    #: Every model that was fitted, for comparison.
    fits: list[Fit]
    frames_used: int
    corners_used: int
    #: Image cells (8 across, 6 down) with detected corners: "#" covered, "." not.
    coverage: list[str]
    board: BoardSpec
    source: SourceRef
    created_at: str
    tool: str


def save_profile(profile: CameraProfile, path: str | os.PathLike[str]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(profile.model_dump_json(indent=1) + "\n")


def load_profile(path: str | os.PathLike[str]) -> CameraProfile:
    return CameraProfile.model_validate_json(Path(path).read_text())
