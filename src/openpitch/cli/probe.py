# SPDX-License-Identifier: GPL-3.0-or-later
"""``openpitch probe``: stream metadata and keyframe structure of a video."""

from __future__ import annotations

from pathlib import Path

import click

from openpitch.core.video import load_frame_index, probe, stream_structure, summarize
from openpitch.core.video.color import stream_color


def _fmt_s(seconds: float) -> str:
    # Round to milliseconds first, so 299.9999 s shows as 5:00.000, not 4:60.000.
    m, ms = divmod(round(seconds * 1000), 60_000)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{ms / 1000:06.3f}" if h else f"{m}:{ms / 1000:06.3f}"


@click.command("probe")
@click.argument("video", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--json", "as_json", is_flag=True, help="Print machine-readable JSON.")
@click.option("--no-cache", is_flag=True, help="Rebuild the frame index, ignore the cache.")
def probe_cmd(video: Path, as_json: bool, no_cache: bool) -> None:
    """Show stream metadata and keyframe spacing of VIDEO."""
    try:
        info = probe(video)
        index = load_frame_index(video, cache=not no_cache)
    except (ValueError, OSError) as e:
        raise click.ClickException(str(e)) from e
    except Exception as e:  # PyAV/ffmpeg errors on unreadable files
        raise click.ClickException(f"{video}: {e}") from e

    s = summarize(info, index)
    if as_json:
        click.echo(s.model_dump_json(indent=2))
        return

    fps = f"{float(info.fps_avg):.3f}" if info.fps_avg else "?"
    gop = s.gop_frames
    lines = [
        ("File", f"{video} ({info.size / 1e9:.2f} GB)"),
        ("Fingerprint", s.content_hash),
        ("Container", info.container),
        ("Video", f"{info.codec} {info.profile or ''} [{info.codec_tag or '-'}]".strip()),
        ("Size", f"{info.width}x{info.height}"),
        ("Pixels", f"{info.pix_fmt} ({info.bit_depth}-bit), range {info.color_range}"),
        (
            "Color",
            f"space {info.color_space}, primaries {info.color_primaries}, "
            f"transfer {info.color_trc}",
        ),
        ("Time base", f"{info.time_base}, B-frames: {'yes' if info.has_b_frames else 'no'}"),
        ("Frame rate", f"{fps} fps average (nominal {info.fps_nominal or '?'})"),
        ("Duration", f"{_fmt_s(s.duration_s)} ({s.frames} frames)"),
        ("Jitter", f"max {s.max_jitter_pts} pts ({s.max_jitter_s * 1e6:.0f} us)"),
        (
            "Keyframes",
            f"{s.keyframes}, GOP {gop.min}/{gop.median:g}/{gop.max} frames "
            f"(min/median/max), ~{s.gop_s:.2f} s",
        ),
    ]
    structure = stream_structure(video)
    parallel = {True: "yes", False: "no", None: "unknown"}[structure.intra_frame_parallel]
    lines.append(
        (
            "Structure",
            f"WPP {structure.wpp}, tiles {structure.tiles}, slices {structure.slices}"
            f" (intra-frame parallel decoding: {parallel})",
        )
    )
    color = stream_color(video)
    signalled = "range" if structure.signal_type else None
    signalled = ("range and matrix" if structure.colour_description else signalled) or "nothing"
    used = (
        f"range {color.range or 'from frames'}, matrix {color.matrix or 'from frames'}"
        f" from the {color.source}"
        if color.source != "frames"
        else "frame tags"
    )
    lines.append(("Color source", f"bitstream signals {signalled}; using {used}"))
    for step in reversed(info.provenance):  # nearest source first
        src = step.source
        offset = f", +{step.pts_offset} pts" if step.pts_offset else ""
        lines.append(
            (
                "Derived from",
                f"{step.op} of {src.file_name} ({src.content_hash[:18]}..., "
                f"{src.width}x{src.height}{offset})",
            )
        )
    if not s.starts_with_keyframe:
        lines.append(("Warning", "stream does not start with a keyframe"))
    width = max(len(k) for k, _ in lines)
    for k, v in lines:
        click.echo(f"{k:<{width}}  {v}")
