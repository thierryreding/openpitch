# SPDX-License-Identifier: GPL-3.0-or-later
"""``openpitch bench-decode``: compare decoder modes across footage."""

from __future__ import annotations

import json
from pathlib import Path

import click

from openpitch.core.capabilities import hw_decode_candidates
from openpitch.core.video.bench import DEFAULT_MODES, FileResult, ModeResult, bench_file

_HEADER = (
    f"{'mode':<10} {'device':<12} {'open':>6} {'decode fps':>10} {'cores':>5}"
    f" {'+RGB fps':>8} {'cores':>5} {'scrub ms':>13} {'random ms':>14} {'step':>5} {'diff':>4}"
)


def _row(r: ModeResult) -> str:
    device = r.device or "software"
    if r.mode not in ("auto",) and not r.mode.startswith("cpu") and not r.hardware:
        device = "software!"  # asked for a hardware device, got software
    diff = "-" if r.max_diff_vs_cpu is None else str(r.max_diff_vs_cpu)
    return (
        f"{r.mode:<10} {device:<12} {r.open_ms:6.0f} {r.decode_fps:10.0f} {r.decode_cores:5.1f}"
        f" {r.rgb_fps:8.0f} {r.rgb_cores:5.1f}"
        f" {r.scrub.median_ms:5.0f} ({r.scrub.max_ms:5.0f})"
        f" {r.random.median_ms:6.0f} ({r.random.max_ms:5.0f}) {r.step_ms:5.1f} {diff:>4}"
    )


def _header(result: FileResult) -> str:
    s = result.structure
    parallel = {True: "yes", False: "no", None: "unknown"}[s.intra_frame_parallel]
    return (
        f"{result.path}\n"
        f"  {result.codec} {result.profile or ''} {result.width}x{result.height} {result.pix_fmt},"
        f" {result.fps or 0:.3f} fps, {result.frames} frames, GOP {result.gop_frames:g}\n"
        f"  structure: WPP {s.wpp}, tiles {s.tiles}, slices {s.slices}"
        f" -> intra-frame parallel decoding: {parallel}"
    )


@click.command("bench-decode")
@click.argument(
    "videos", nargs=-1, required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path)
)
@click.option(
    "--mode",
    "modes",
    multiple=True,
    help="Decoder mode: cpu, cpu:N (N threads), a hardware device type (cuda, d3d11va,"
    " videotoolbox, qsv, vaapi, ...) or auto. Repeatable."
    f" Default: {', '.join(DEFAULT_MODES)}.",
)
@click.option("--samples", default=20, show_default=True, help="Latency samples per access type.")
@click.option("--frames", default=300, show_default=True, help="Frames for sequential runs.")
@click.option("--json", "as_json", is_flag=True, help="Print machine-readable JSON.")
def bench_decode_cmd(
    videos: tuple[Path, ...], modes: tuple[str, ...], samples: int, frames: int, as_json: bool
) -> None:
    """Benchmark decoding of VIDEOS: sequential, scrub, random access, stepping.

    Latencies are median (max) over random positions, each from a reset decoder, with
    RGB conversion included. "diff" is the largest RGB difference of a hardware mode to
    software decoding. "software!" means the requested device did not work for this file.
    """
    modes = modes or DEFAULT_MODES
    results = []
    if not as_json:
        available = ", ".join(hw_decode_candidates()) or "none"
        click.echo(f"hardware decoders compiled in for this platform: {available}")
    for video in videos:

        def start(result: FileResult) -> None:
            if not as_json:
                click.echo()
                click.echo(_header(result))
                click.echo(_HEADER)

        def show(r: ModeResult) -> None:
            if not as_json:
                click.echo(_row(r))

        try:
            result = bench_file(
                video, modes, samples=samples, frames=frames, on_start=start, on_result=show
            )
        except ValueError as e:
            raise click.ClickException(str(e)) from e
        results.append(result)
    if as_json:
        click.echo(json.dumps([r.model_dump() for r in results], indent=2))
