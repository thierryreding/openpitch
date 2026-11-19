# SPDX-License-Identifier: GPL-3.0-or-later
"""Camera calibration from a video of a ChArUco board (see ``board``).

Detects the board in every ``stride``-th frame, picks frames that cover the image, and
fits a pinhole model three ways: without distortion, with radial k1 k2, and with OpenCV's
k1 k2 p1 p2 k3. The profile keeps the simplest model whose fit is within 10% of the
best: in-camera dewarped footage (e.g. DJI "Standard (Dewarp)") needs no distortion
terms, and extra terms fitted on noise only make the edges worse.

Long-running: decoding dominates (4K60 HEVC with tiles decodes at about 30 fps in
software). ``progress`` may raise to cancel. OpenCV (the ``cv`` extra) is imported lazily.
"""

from __future__ import annotations

import datetime as _dt
import math
import os
from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import numpy as np

from openpitch import __version__
from openpitch.core.camera.board import BoardSpec, cv_board
from openpitch.core.camera.profile import (
    DISTORTION_MODELS,
    CameraInfo,
    CameraMode,
    CameraProfile,
    FieldOfView,
    Fit,
    Intrinsics,
    SourceRef,
)
from openpitch.core.fingerprint import fingerprint

#: Called with the fraction done (0.0 .. 1.0). It may raise to cancel.
ProgressCallback = Callable[[float], None]

#: Inner corners a detection needs to be useful.
MIN_CORNERS = 12
#: Coverage cells across and down the image.
GRID = (8, 6)
#: A simpler model is kept if its RMS is within this factor of the best one.
SIMPLER_TOLERANCE = 1.10


@dataclass(frozen=True)
class Detection:
    frame: int
    corners: np.ndarray  # (n, 1, 2) image points
    ids: np.ndarray  # (n, 1) corner ids


def detect(
    path: str | os.PathLike[str],
    spec: BoardSpec,
    *,
    stride: int = 4,
    hwaccel: str | None = "auto",
    progress: ProgressCallback | None = None,
) -> tuple[list[Detection], tuple[int, int]]:
    """Board detections in every ``stride``-th frame, and the image size."""
    import cv2

    from openpitch.core.video import VideoDecoder

    detector = cv2.aruco.CharucoDetector(cv_board(spec))
    found = []
    with VideoDecoder(path, format="bgr24", hwaccel=hwaccel, cache_bytes=0) as decoder:
        n = len(decoder.index)
        size = None
        for decoded in decoder.iter_frames(stride=stride):
            gray = cv2.cvtColor(decoded.image, cv2.COLOR_BGR2GRAY)
            size = (gray.shape[1], gray.shape[0])
            corners, ids, _, _ = detector.detectBoard(gray)
            if ids is not None and len(ids) >= MIN_CORNERS:
                found.append(Detection(decoded.frame, corners, ids))
            if progress is not None:
                progress(min(0.99, (decoded.frame + 1) / n))
    if size is None:
        raise ValueError(f"{path}: no frames decoded")
    return found, size


def _cells(corners: np.ndarray, size: tuple[int, int]) -> set[tuple[int, int]]:
    w, h = size
    pts = corners.reshape(-1, 2)
    cx = np.clip((pts[:, 0] / w * GRID[0]).astype(int), 0, GRID[0] - 1)
    cy = np.clip((pts[:, 1] / h * GRID[1]).astype(int), 0, GRID[1] - 1)
    return set(zip(cx.tolist(), cy.tolist(), strict=True))


def select(
    detections: list[Detection], size: tuple[int, int], max_frames: int
) -> tuple[list[Detection], set[tuple[int, int]]]:
    """Frames covering the most image cells first, then the rest spread evenly."""
    chosen: list[Detection] = []
    covered: set[tuple[int, int]] = set()
    remaining = list(detections)
    while remaining and len(chosen) < max_frames:
        best = max(remaining, key=lambda d: len(_cells(d.corners, size) - covered))
        gain = _cells(best.corners, size) - covered
        if not gain:
            break
        chosen.append(best)
        covered |= gain
        remaining.remove(best)
    rest = max_frames - len(chosen)
    if rest > 0 and remaining:
        step = max(1, len(remaining) // rest)
        chosen += remaining[::step][:rest]
    return sorted(chosen, key=lambda d: d.frame), covered


def field_of_view(K: np.ndarray, dist: np.ndarray, size: tuple[int, int]) -> FieldOfView:
    """Angles between opposite edge midpoints (and corners) after undistortion."""
    import cv2

    w, h = size
    pts = np.array([[0, h / 2], [w, h / 2], [w / 2, 0], [w / 2, h], [0, 0], [w, h]], float)
    rays = cv2.undistortPoints(pts.reshape(-1, 1, 2), K, dist).reshape(-1, 2)
    rays = np.hstack([rays, np.ones((len(rays), 1))])

    def angle(a: int, b: int) -> float:
        cos = rays[a] @ rays[b] / np.linalg.norm(rays[a]) / np.linalg.norm(rays[b])
        return round(math.degrees(math.acos(max(-1.0, min(1.0, cos)))), 2)

    return FieldOfView(horizontal=angle(0, 1), vertical=angle(2, 3), diagonal=angle(4, 5))


def fit(detections: list[Detection], spec: BoardSpec, size: tuple[int, int], model: str) -> Fit:
    """Fit one distortion model (``DISTORTION_MODELS``) to the detections."""
    import cv2

    flags = {
        "none": cv2.CALIB_ZERO_TANGENT_DIST
        | cv2.CALIB_FIX_K1
        | cv2.CALIB_FIX_K2
        | cv2.CALIB_FIX_K3,
        "k1k2": cv2.CALIB_ZERO_TANGENT_DIST | cv2.CALIB_FIX_K3,
        "k1k2p1p2k3": 0,
    }[model]
    board = cv_board(spec)
    obj, img = [], []
    for d in detections:
        o, i = board.matchImagePoints(d.corners, d.ids)
        obj.append(o)
        img.append(i)
    rms, K, dist, rvecs, tvecs = cv2.calibrateCamera(obj, img, size, None, None, flags=flags)
    per_frame = []
    for o, i, r, t in zip(obj, img, rvecs, tvecs, strict=True):
        proj, _ = cv2.projectPoints(o, r, t, K, dist)
        per_frame.append(float(np.sqrt(np.mean(np.sum((proj - i) ** 2, axis=2)))))
    return Fit(
        distortion_model=model,
        rms_px=round(float(rms), 4),
        frame_rms_median_px=round(float(np.median(per_frame)), 4),
        frame_rms_max_px=round(max(per_frame), 4),
        intrinsics=Intrinsics(
            fx=float(K[0, 0]), fy=float(K[1, 1]), cx=float(K[0, 2]), cy=float(K[1, 2])
        ),
        distortion=[float(x) for x in dist.ravel()[:5]],
        fov=field_of_view(K, dist, size),
    )


def choose(fits: list[Fit]) -> Fit:
    """The simplest fit within ``SIMPLER_TOLERANCE`` of the best RMS."""
    best = min(f.rms_px for f in fits)
    order = {m: i for i, m in enumerate(DISTORTION_MODELS)}
    for f in sorted(fits, key=lambda f: order[f.distortion_model]):
        if f.rms_px <= best * SIMPLER_TOLERANCE:
            return f
    raise AssertionError("unreachable")


def calibrate(
    path: str | os.PathLike[str],
    spec: BoardSpec,
    *,
    stride: int = 4,
    max_frames: int = 60,
    model: str = "auto",
    hwaccel: str | None = "auto",
    progress: ProgressCallback | None = None,
) -> CameraProfile:
    """Calibrate the camera that recorded ``path`` (a video of the board ``spec``)."""
    if model != "auto" and model not in DISTORTION_MODELS:
        raise ValueError(f"unknown model {model!r}, use auto or one of {DISTORTION_MODELS}")
    path = Path(path)
    detections, size = detect(path, spec, stride=stride, hwaccel=hwaccel, progress=progress)
    if len(detections) < 5:
        raise ValueError(
            f"{path}: the board was found in only {len(detections)} frames (wrong board,"
            " too far away, or out of focus?)"
        )
    chosen, covered = select(detections, size, max_frames)
    fits = [fit(chosen, spec, size, m) for m in DISTORTION_MODELS]
    best = choose(fits) if model == "auto" else next(f for f in fits if f.distortion_model == model)
    if progress is not None:
        progress(1.0)
    return CameraProfile(
        camera=_camera_info(path),
        mode=_camera_mode(path, size),
        intrinsics=best.intrinsics,
        distortion_model=best.distortion_model,
        distortion=best.distortion,
        rms_px=best.rms_px,
        fov=best.fov,
        fits=fits,
        frames_used=len(chosen),
        corners_used=sum(len(d.ids) for d in chosen),
        coverage=[
            "".join("#" if (x, y) in covered else "." for x in range(GRID[0]))
            for y in range(GRID[1])
        ],
        board=spec,
        source=SourceRef(content_hash=fingerprint(path), file_name=path.name),
        created_at=_dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        tool=f"openpitch {__version__}",
    )


def _camera_info(path: Path) -> CameraInfo:
    from openpitch.core.video.dji import read_header

    header = read_header(path)
    if header is None:
        return CameraInfo()
    return CameraInfo(model=header.model, serial=header.serial, firmware=header.firmware)


def _camera_mode(path: Path, size: tuple[int, int]) -> CameraMode:
    from openpitch.core.video import probe
    from openpitch.core.video.dji import read_header

    info = probe(path)
    header = read_header(path)
    fps = info.fps_avg or info.fps_nominal
    return CameraMode(
        width=size[0],
        height=size[1],
        fps=str(Fraction(fps).limit_denominator(1001)) if fps else None,
        fov_setting=header.fov if header else None,
        stabilization=header.stabilization if header else None,
    )
