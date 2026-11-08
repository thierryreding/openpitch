# SPDX-License-Identifier: GPL-3.0-or-later
"""YUV -> RGB accuracy of swscale flag combinations against reference BT.709/BT.601 math.

Usage: uv run python tools/benchmarks/color_accuracy.py

Builds untagged frames of flat color patches with exact YUV values (tests/colorref.py)
and prints the largest error in 8-bit code values per matrix, range, output format and
swscale flag set. This is what chose the flags in openpitch.core.video.color: with
ACCURATE_RND alone, limited range is biased by up to -3; adding FULL_CHR_H_INT keeps
8-bit output within 1, but garbles rgb48le output in ffmpeg 9.0.2.
"""

import sys
from pathlib import Path

import numpy as np
from av.video.reformatter import ColorRange, Colorspace, Interpolation

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))
from colorref import PATCH_COLORS, sample_patches  # noqa: E402
from videogen import patches_frame  # noqa: E402

FLAGS = {
    "default": None,
    "accurate_rnd": Interpolation.BILINEAR | Interpolation.ACCURATE_RND,
    "full_chr_h_int": Interpolation.BILINEAR | Interpolation.FULL_CHR_H_INT,
    "both": Interpolation.BILINEAR | Interpolation.ACCURATE_RND | Interpolation.FULL_CHR_H_INT,
}
MATRICES = {"bt709": Colorspace.ITU709, "bt601": Colorspace.ITU601}

print(f"{'input':28s} {'output':8s} " + " ".join(f"{k:>15s}" for k in FLAGS) + "   naive")
for pix_fmt in ("yuv420p", "yuv420p10le"):
    for matrix, cs in MATRICES.items():
        for full in (True, False):
            frame = patches_frame(matrix=matrix, full=full, pix_fmt=pix_fmt)
            rng = ColorRange.JPEG if full else ColorRange.MPEG
            for fmt, scale in (("rgb24", 1), ("rgb48le", 257)):
                errors = []
                for interp in FLAGS.values():
                    out = frame.reformat(
                        format=fmt,
                        src_colorspace=cs,
                        dst_colorspace=cs,
                        src_color_range=rng,
                        dst_color_range=ColorRange.JPEG,
                        interpolation=interp,
                    ).to_ndarray()
                    errors.append(np.abs(sample_patches(out) / scale - PATCH_COLORS).max())
                naive = frame.to_ndarray(format=fmt)
                naive_err = np.abs(sample_patches(naive) / scale - PATCH_COLORS).max()
                label = f"{pix_fmt} {matrix} {'full' if full else 'limited'}"
                print(
                    f"{label:28s} {fmt:8s} "
                    + " ".join(f"{e:15.2f}" for e in errors)
                    + f" {naive_err:7.2f}"
                )
