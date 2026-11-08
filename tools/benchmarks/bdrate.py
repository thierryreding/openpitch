# SPDX-License-Identifier: GPL-3.0-or-later
"""Curves and BD-rates from an encoder_matrix.py results file.

Usage:
    uv run python tools/benchmarks/bdrate.py RESULTS.csv [--baseline NAME]
        [--target VMAF ...]

Prints each configuration's points, the Bjontegaard delta rate (BD-rate) of every
configuration against the baseline for VMAF and VMAF NEG (the average bitrate difference
at equal quality, over the quality range both curves cover; negative means fewer bits),
HEVC-versus-H.264 pairs with equal tuning, and, with --target, the quality value
(CRF/CQ) each configuration needs to reach the given VMAF scores.
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

import numpy as np

#: (H.264 config, HEVC config) with equal tuning.
PAIRS = [
    ("nvenc-h264-p5", "nvenc-hevc-p5"),
    ("nvenc-h264-p7-bref-aq", "nvenc-hevc-p7-bref-aq"),
    ("x264-fast", "x265-fast"),
    ("x264-medium", "x265-medium"),
    ("x264-medium-psnr", "x265-medium-psnr"),
]


def load(path: Path) -> dict[str, list[dict[str, str]]]:
    rows: dict[str, list[dict[str, str]]] = defaultdict(list)
    for r in csv.DictReader(path.open()):
        rows[r["config"]].append(r)
    return rows


def curve(rows, name: str, metric: str) -> tuple[np.ndarray, np.ndarray]:
    pts = sorted((float(r[metric]), float(r["mbps"])) for r in rows[name])
    return np.array([p[0] for p in pts]), np.log(np.array([p[1] for p in pts]))


def bd_rate(rows, base: str, test: str, metric: str) -> float | None:
    """Average bitrate difference (%) of test vs base at equal quality (Bjontegaard)."""
    q1, r1 = curve(rows, base, metric)
    q2, r2 = curve(rows, test, metric)
    lo, hi = max(q1.min(), q2.min()), min(q1.max(), q2.max())
    if lo >= hi or len(q1) < 4 or len(q2) < 4:
        return None
    p1, p2 = np.polyfit(q1, r1, 3), np.polyfit(q2, r2, 3)
    i1 = np.polyval(np.polyint(p1), hi) - np.polyval(np.polyint(p1), lo)
    i2 = np.polyval(np.polyint(p2), hi) - np.polyval(np.polyint(p2), lo)
    return float((np.exp((i2 - i1) / (hi - lo)) - 1) * 100)


def quality_for(rows, name: str, target: float) -> float | None:
    """Quality value (CRF/CQ) that reaches ``target`` VMAF, interpolated linearly."""
    pts = sorted((float(r["vmaf"]), int(r["q"])) for r in rows[name])
    vmaf = [p[0] for p in pts]
    if not vmaf[0] <= target <= vmaf[-1]:
        return None
    return float(np.interp(target, vmaf, [p[1] for p in pts]))


def fmt(value: float | None) -> str:
    return "    n/a" if value is None else f"{value:+6.1f}%"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("results", type=Path)
    ap.add_argument("--baseline", default="nvenc-h264-p5")
    ap.add_argument("--target", type=float, action="append", help="VMAF target (repeatable)")
    args = ap.parse_args()
    rows = load(args.results)

    print("points: Mb/s -> VMAF / VMAF NEG @ encode fps")
    for name, rs in rows.items():
        pts = "  ".join(
            f"{float(r['mbps']):4.1f}->{float(r['vmaf']):4.1f}/{float(r['vmaf_neg']):4.1f}"
            f" @{r['fps']}"
            for r in sorted(rs, key=lambda r: float(r["mbps"]))
        )
        print(f"  {name:24s} {pts}")

    if args.baseline in rows:
        print(f"\nBD-rate vs {args.baseline} (VMAF, VMAF NEG; negative = fewer bits)")
        for name in rows:
            if name != args.baseline:
                vm = bd_rate(rows, args.baseline, name, "vmaf")
                neg = bd_rate(rows, args.baseline, name, "vmaf_neg")
                print(f"  {name:24s} {fmt(vm)}  {fmt(neg)}")

    pairs = [(a, b) for a, b in PAIRS if a in rows and b in rows]
    if pairs:
        print("\nHEVC vs H.264 with equal tuning (VMAF, VMAF NEG)")
        for a, b in pairs:
            print(
                f"  {b:24s} vs {a:24s} {fmt(bd_rate(rows, a, b, 'vmaf'))}"
                f"  {fmt(bd_rate(rows, a, b, 'vmaf_neg'))}"
            )

    if args.target:
        print("\nquality value (CRF/CQ) per VMAF target")
        print("  " + " " * 24 + "".join(f"{t:>8g}" for t in args.target))
        for name in rows:
            qs = [quality_for(rows, name, t) for t in args.target]
            print(f"  {name:24s}" + "".join("     n/a" if q is None else f"{q:8.1f}" for q in qs))


if __name__ == "__main__":
    main()
