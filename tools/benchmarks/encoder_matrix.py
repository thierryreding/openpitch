# SPDX-License-Identifier: GPL-3.0-or-later
"""Encoder quality/bitrate matrix: VMAF and VMAF NEG curves per encoder configuration.

Usage:
    uv run python tools/benchmarks/encoder_matrix.py SOURCE --work DIR \\
        [--start 300] [--duration 120] [--height 1080] [--config NAME ...] [--list]
    uv run python tools/benchmarks/bdrate.py DIR/results.csv

1. Cuts ``--duration`` seconds from ``--start`` of SOURCE and converts them once to a
   lossless (FFV1) reference at the target height, BT.709 limited range. Range and matrix
   of the source come from ``openpitch.core.video.color``, so footage that signals color
   only in the container (XbotGo Falcon) is converted correctly.
2. Encodes the reference with every configuration at several quality points, with the
   ffmpeg CLI, and scores each encode against the reference with VMAF v0.6.1 and VMAF NEG
   (which does not reward sharpening). Rows append to ``DIR/results.csv``; points already
   there are skipped, so an interrupted run resumes.

Every encoder sees the same input, so the curves compare encoders only (not decoding or
scaling). Two pitfalls this avoids: frames are paired by index, not timestamp (Matroska
rounds timestamps to milliseconds, and VMAF then pairs neighbouring frames now and then),
and encodes use ``-fps_mode passthrough`` (no duplicated or dropped frames).

The work directory holds copies of the footage and can get large (about 3.9 GB for the
2 minute 1080p reference). Keep it out of the repository and delete it afterwards. Never
commit footage of minors.

Measured results for real Falcon footage are in docs/design/video.md.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import time
from pathlib import Path

import av

from openpitch.core.video.color import frame_color, stream_color

NV = ["-rc", "vbr", "-b:v", "0", "-rc-lookahead", "20"]
NV_TUNED = [
    "-rc",
    "vbr",
    "-b:v",
    "0",
    "-preset",
    "p7",
    "-tune",
    "hq",
    "-bf",
    "3",
    "-b_ref_mode",
    "middle",
    "-rc-lookahead",
    "32",
]
AQ = ["-spatial-aq", "1", "-temporal-aq", "1"]
X265 = ["-x265-params", "log-level=error"]
NVENC_Q = [26, 29, 32, 35]
X264_Q = [20, 23, 26, 29]
X265_Q = [21, 24, 27, 30]

#: name -> (encoder arguments, "{q}" is the quality value; quality points)
CONFIGS: dict[str, tuple[list[str], list[int]]] = {
    # What openpitch recode uses by default.
    "nvenc-h264-p5": (["-c:v", "h264_nvenc", "-preset", "p5", *NV, "-cq", "{q}"], NVENC_Q),
    "nvenc-hevc-p5": (["-c:v", "hevc_nvenc", "-preset", "p5", *NV, "-cq", "{q}"], NVENC_Q),
    "nvenc-hevc-p7-bref": (["-c:v", "hevc_nvenc", *NV_TUNED, "-cq", "{q}"], NVENC_Q),
    "nvenc-hevc-p7-bref-aq": (["-c:v", "hevc_nvenc", *NV_TUNED, *AQ, "-cq", "{q}"], NVENC_Q),
    "nvenc-h264-p7-bref-aq": (["-c:v", "h264_nvenc", *NV_TUNED, *AQ, "-cq", "{q}"], NVENC_Q),
    # What openpitch recode --encoder software uses.
    "x264-fast": (["-c:v", "libx264", "-preset", "fast", "-crf", "{q}"], X264_Q),
    "x265-fast": (["-c:v", "libx265", "-preset", "fast", *X265, "-crf", "{q}"], X265_Q),
    "x264-medium": (["-c:v", "libx264", "-preset", "medium", "-crf", "{q}"], X264_Q),
    "x265-medium": (["-c:v", "libx265", "-preset", "medium", *X265, "-crf", "{q}"], X265_Q),
    "x265-slow": (["-c:v", "libx265", "-preset", "slow", *X265, "-crf", "{q}"], X265_Q),
    # Psychovisual tuning off, like NVENC without AQ (VMAF does not reward it).
    "x264-medium-psnr": (
        ["-c:v", "libx264", "-preset", "medium", "-tune", "psnr", "-crf", "{q}"],
        X264_Q,
    ),
    "x265-medium-psnr": (
        ["-c:v", "libx265", "-preset", "medium", "-tune", "psnr", *X265, "-crf", "{q}"],
        X265_Q,
    ),
}
COMMON = [
    "-fps_mode",
    "passthrough",
    "-pix_fmt",
    "yuv420p",
    "-color_range",
    "tv",
    "-colorspace",
    "bt709",
    "-color_primaries",
    "bt709",
    "-color_trc",
    "bt709",
    "-an",
]
FIELDS = [
    "config",
    "q",
    "mbps",
    "encode_s",
    "fps",
    "vmaf",
    "vmaf_p5",
    "vmaf_neg",
    "vmaf_neg_p5",
    "frames",
]
_SWS_MATRIX = {
    "bt709": "bt709",
    "bt601": "bt601",
    "bt2020": "bt2020",
    "fcc": "fcc",
    "smpte240m": "smpte240m",
}


def run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if result.returncode:
        sys.exit(f"command failed ({result.returncode}): {' '.join(cmd)}\n{result.stderr}")


def source_color(path: Path) -> tuple[str, str]:
    """(range, matrix) of the source as openpitch resolves it."""
    with av.open(str(path)) as c:
        frame = next(c.decode(video=0))
    color = frame_color(frame, stream_color(path))
    return color.range, _SWS_MATRIX.get(color.matrix, "bt709")


def build_reference(src: Path, ref: Path, start: float, duration: float, height: int) -> None:
    rng, matrix = source_color(src)
    print(
        f"reference: {duration:g} s from {start:g} s, {height}p, source {rng} {matrix}", flush=True
    )
    vf = (
        f"scale=-2:{height}:flags=bicubic:in_range={rng}:out_range=tv"
        f":in_color_matrix={matrix}:out_color_matrix=bt709,format=yuv420p"
    )
    tmp = ref.with_suffix(".partial.mkv")
    run(
        [
            "ffmpeg",
            "-hide_banner",
            "-v",
            "error",
            "-y",
            "-ss",
            str(start),
            "-t",
            str(duration),
            "-i",
            str(src),
            "-an",
            "-vf",
            vf,
            "-color_range",
            "tv",
            "-colorspace",
            "bt709",
            "-color_primaries",
            "bt709",
            "-color_trc",
            "bt709",
            "-fps_mode",
            "passthrough",
            "-c:v",
            "ffv1",
            "-level",
            "3",
            "-slices",
            "16",
            "-threads",
            "16",
            str(tmp),
        ]
    )
    tmp.replace(ref)


def score(dist: Path, ref: Path, log: Path, fps: float) -> dict[str, float]:
    model = "version=vmaf_v0.6.1\\:name=vmaf|version=vmaf_v0.6.1neg\\:name=vmaf_neg"
    tb = f"settb=1/{round(fps)},setpts=N"  # pair frames by index, not timestamp
    run(
        [
            "ffmpeg",
            "-hide_banner",
            "-v",
            "error",
            "-i",
            str(dist),
            "-i",
            str(ref),
            "-lavfi",
            f"[0:v]{tb}[d];[1:v]{tb}[r];"
            f"[d][r]libvmaf=model='{model}':n_threads=16:log_fmt=json:log_path={log}",
            "-f",
            "null",
            "-",
        ]
    )
    data = json.loads(log.read_text())
    out: dict[str, float] = {"frames": len(data["frames"])}
    for key in ("vmaf", "vmaf_neg"):
        frames = sorted(f["metrics"][key] for f in data["frames"])
        out[key] = data["pooled_metrics"][key]["mean"]
        out[key + "_p5"] = frames[len(frames) // 20]
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("source", type=Path, nargs="?")
    ap.add_argument("--work", type=Path, help="work directory (footage copies, results)")
    ap.add_argument("--start", type=float, default=300.0)
    ap.add_argument("--duration", type=float, default=120.0)
    ap.add_argument("--height", type=int, default=1080)
    ap.add_argument(
        "--config",
        action="append",
        choices=sorted(CONFIGS),
        help="configurations to run (repeatable; default: all)",
    )
    ap.add_argument(
        "--quality",
        type=int,
        action="append",
        help="quality values (CRF/CQ) instead of each configuration's defaults (repeatable)",
    )
    ap.add_argument("--keep", action="store_true", help="keep the encodes")
    ap.add_argument("--list", action="store_true", help="list configurations and exit")
    args = ap.parse_args()
    if args.list:
        for name, (enc, qs) in CONFIGS.items():
            print(f"{name:24s} q={qs}  {' '.join(enc)}")
        return
    if args.source is None or args.work is None:
        ap.error("SOURCE and --work are required")

    args.work.mkdir(parents=True, exist_ok=True)
    ref = args.work / f"ref_{args.start:g}_{args.duration:g}_{args.height}p.mkv"
    if not ref.exists():
        build_reference(args.source, ref, args.start, args.duration, args.height)
    with av.open(str(ref)) as c:
        fps = float(c.streams.video[0].average_rate or 30)

    results = args.work / "results.csv"
    done = set()
    if results.exists():
        done = {(r["config"], int(r["q"])) for r in csv.DictReader(results.open())}
    with results.open("a", newline="") as fh:
        writer = csv.writer(fh)
        if not done:
            writer.writerow(FIELDS)
        for name in args.config or list(CONFIGS):
            encoder_args, qualities = CONFIGS[name]
            for q in args.quality or qualities:
                if (name, q) in done:
                    continue
                out = args.work / f"enc_{name}_{q}.mp4"
                t = time.perf_counter()
                run(
                    [
                        "ffmpeg",
                        "-hide_banner",
                        "-v",
                        "error",
                        "-y",
                        "-i",
                        str(ref),
                        *[a.format(q=q) for a in encoder_args],
                        *COMMON,
                        str(out),
                    ]
                )
                seconds = time.perf_counter() - t
                mbps = out.stat().st_size * 8 / args.duration / 1e6
                s = score(out, ref, args.work / f"vmaf_{name}_{q}.json", fps)
                if not args.keep:
                    out.unlink()
                row = [
                    name,
                    q,
                    f"{mbps:.2f}",
                    f"{seconds:.1f}",
                    f"{s['frames'] / seconds:.0f}",
                    f"{s['vmaf']:.2f}",
                    f"{s['vmaf_p5']:.2f}",
                    f"{s['vmaf_neg']:.2f}",
                    f"{s['vmaf_neg_p5']:.2f}",
                    int(s["frames"]),
                ]
                writer.writerow(row)
                fh.flush()
                print(*row, flush=True)


if __name__ == "__main__":
    main()
