# SPDX-License-Identifier: GPL-3.0-or-later
"""ChArUco calibration boards, sized for the screen (or page) that shows them.

A ChArUco board is a checkerboard with an ArUco marker in every white square, so each
corner can be identified even when only part of the board is visible. That gives
corners up to the image edges, where lens distortion is largest.

The board's description (``BoardSpec``) is saved next to its image, so calibration always
detects exactly the board that was shown. The square size only scales the board's
distance in the result: focal length, distortion and field of view do not depend on it,
so an approximate physical size is fine.

OpenCV (the ``cv`` extra) is imported lazily.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
from pydantic import BaseModel, ConfigDict

DICTIONARY = "DICT_5X5_250"
DICTIONARY_SIZE = 250
MARKER_RATIO = 0.75
DEFAULT_ROWS = 9


class BoardSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    #: OpenCV predefined ArUco dictionary.
    dictionary: str = DICTIONARY
    #: Squares across and down.
    squares: tuple[int, int]
    #: Square size in image pixels.
    square_px: int
    #: Marker size relative to the square.
    marker_ratio: float = MARKER_RATIO
    #: Physical square size where known (from the screen's reported size).
    square_mm: float | None = None
    #: Image size the board was made for.
    image_px: tuple[int, int]

    @property
    def inner_corners(self) -> int:
        return (self.squares[0] - 1) * (self.squares[1] - 1)


def available() -> bool:
    """True if OpenCV (the ``cv`` extra), which boards and calibration need, is installed."""
    import importlib.util

    return importlib.util.find_spec("cv2") is not None


def layout(width: int, height: int, rows: int = DEFAULT_ROWS) -> tuple[int, int, int]:
    """(columns, rows, square size in pixels) for a board filling a ``width`` x ``height``
    image, with ``rows`` squares on the short side and a margin of half a square (a
    light border the detector needs)."""
    if rows < 3:
        raise ValueError("a board needs at least 3 squares on each side")
    short, long = min(width, height), max(width, height)
    square = short // (rows + 1)
    if square < 16:
        raise ValueError(f"{width}x{height} is too small for {rows} rows of squares")
    along = (long - square) // square
    cols, rows = (along, rows) if width >= height else (rows, along)
    return cols, rows, square


def make_board(
    width: int, height: int, *, mm_per_px: float | None = None, rows: int = DEFAULT_ROWS
) -> BoardSpec:
    """A board filling a ``width`` x ``height`` image (e.g. a screen at native resolution)."""
    cols, rows, square = layout(width, height, rows)
    if cols * rows // 2 + 1 > DICTIONARY_SIZE:
        raise ValueError(f"{cols}x{rows} squares need more than {DICTIONARY_SIZE} markers")
    return BoardSpec(
        squares=(cols, rows),
        square_px=square,
        square_mm=round(square * mm_per_px, 3) if mm_per_px else None,
        image_px=(width, height),
    )


def cv_board(spec: BoardSpec):
    """The OpenCV ``CharucoBoard`` for ``spec`` (units: millimeters, or squares)."""
    import cv2

    dictionary = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, spec.dictionary))
    square = spec.square_mm or 1.0
    return cv2.aruco.CharucoBoard(spec.squares, square, square * spec.marker_ratio, dictionary)


def render(spec: BoardSpec) -> np.ndarray:
    """The board centered on a white 8-bit image of ``spec.image_px``."""
    width, height = spec.image_px
    cols, rows = spec.squares
    square = spec.square_px
    image = cv_board(spec).generateImage((cols * square, rows * square), marginSize=0)
    canvas = np.full((height, width), 255, np.uint8)
    y, x = (height - rows * square) // 2, (width - cols * square) // 2
    canvas[y : y + rows * square, x : x + cols * square] = image
    return canvas


def save_board(spec: BoardSpec, image_path: str | os.PathLike[str]) -> Path:
    """Write the board image and its description (same name, ``.json``). Returns the
    description's path."""
    import cv2

    image_path = Path(image_path)
    image_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(image_path), render(spec)):
        raise ValueError(f"cannot write {image_path} (use .png)")
    spec_path = image_path.with_suffix(".json")
    spec_path.write_text(spec.model_dump_json(indent=1) + "\n")
    return spec_path


def load_board(path: str | os.PathLike[str]) -> BoardSpec:
    return BoardSpec.model_validate_json(Path(path).read_text())
