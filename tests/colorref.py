# SPDX-License-Identifier: GPL-3.0-or-later
"""Reference Y'CbCr math (ITU-R BT.709 / BT.601, H.273 quantization), independent of
swscale, for checking openpitch's YUV -> RGB conversion."""

from __future__ import annotations

import numpy as np

#: (Kr, Kb) per matrix.
COEFFICIENTS = {"bt709": (0.2126, 0.0722), "bt601": (0.299, 0.114)}

#: Test colors (8-bit RGB): extremes, primaries, grey and two mixed colors.
PATCH_COLORS = np.array(
    [
        [0, 0, 0],
        [255, 255, 255],
        [255, 0, 0],
        [0, 255, 0],
        [0, 0, 255],
        [128, 128, 128],
        [200, 100, 50],
        [30, 180, 220],
    ],
    dtype=float,
)
#: Patch width and height in pixels (a multiple of the 2x2 chroma block).
PATCH_SIZE = 16


def rgb_to_yuv(rgb: np.ndarray, *, matrix: str, full: bool, bits: int = 8) -> np.ndarray:
    """8-bit RGB -> quantized Y'CbCr code values (rounded, clipped)."""
    kr, kb = COEFFICIENTS[matrix]
    kg = 1 - kr - kb
    e = np.asarray(rgb, float) / 255.0
    y = kr * e[..., 0] + kg * e[..., 1] + kb * e[..., 2]
    pb = (e[..., 2] - y) / (2 * (1 - kb))
    pr = (e[..., 0] - y) / (2 * (1 - kr))
    scale = 1 << (bits - 8)
    mid = 1 << (bits - 1)
    if full:
        top = (1 << bits) - 1
        out = np.stack([top * y, top * pb + mid, top * pr + mid], axis=-1)
    else:
        out = np.stack([(219 * y + 16) * scale, 224 * pb * scale + mid, 224 * pr * scale + mid], -1)
    return np.clip(np.round(out), 0, (1 << bits) - 1).astype(np.int64)


def patch_centers(patch: int = PATCH_SIZE, height: int = PATCH_SIZE) -> list[tuple[int, int]]:
    """(row, column) at the center of each patch."""
    return [(height // 2, i * patch + patch // 2) for i in range(len(PATCH_COLORS))]


def sample_patches(rgb, patch: int = PATCH_SIZE, height: int = PATCH_SIZE) -> np.ndarray:
    """RGB values at the patch centers, as int64."""
    return np.array([rgb[r, c] for r, c in patch_centers(patch, height)], dtype=np.int64)
