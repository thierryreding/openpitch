# SPDX-License-Identifier: GPL-3.0-or-later
"""``openpitch clip``: export clips by stream copy, keyframe-snapped."""

from __future__ import annotations

from pathlib import Path

import click

from openpitch.core.video import load_frame_index
from openpitch.core.video.clip import (
    EXTENSIONS,
    ClipResult,
    default_output,
    export_clip,
    parse_range,
    plan_clip,
    pts_at,
)


def _fmt_s(seconds: float) -> str:
    m, s = divmod(seconds, 60)
    h, m = divmod(int(m), 60)
    return f"{h}:{m:02d}:{s:06.3f}" if h else f"{m}:{s:06.3f}"


def _fmt_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1000 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1000
    raise AssertionError


def _summary(r: ClipResult, marked: tuple[float, float]) -> str:
    extra = ", +1 keyframe for open GOP" if r.extra_keyframe else ""
    return (
        f"{Path(r.output).name}: {_fmt_s(r.start_s)}-{_fmt_s(r.end_s)}"
        f" (marked {_fmt_s(marked[0])}-{_fmt_s(marked[1])}), {r.frames} frames{extra},"
        f" audio {r.audio}, {_fmt_bytes(r.output_bytes)}"
    )


@click.command("clip")
@click.argument("video", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("ranges", nargs=-1, required=True)
@click.option(
    "-o",
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Output file (single range only). The extension picks the container: "
    + ", ".join(EXTENSIONS)
    + ".",
)
@click.option(
    "-d",
    "--output-dir",
    type=click.Path(file_okay=False, path_type=Path),
    help="Directory for outputs (default: next to VIDEO).",
)
@click.option("--no-audio", is_flag=True, help="Leave out the audio track.")
@click.option("-n", "--dry-run", is_flag=True, help="Only show the snapped ranges.")
@click.option("-f", "--force", is_flag=True, help="Overwrite existing outputs.")
def clip_cmd(
    video: Path,
    ranges: tuple[str, ...],
    output: Path | None,
    output_dir: Path | None,
    no_audio: bool,
    dry_run: bool,
    force: bool,
) -> None:
    """Export RANGES of VIDEO as clips, without re-encoding.

    Each range is START-END in seconds from the start of the video: SS, MM:SS or
    H:MM:SS, with optional decimals (e.g. 1:23-1:45.5). END is exclusive. Clips are
    stream copies, so they start at the keyframe at or before START and end at the
    keyframe at or after END: nothing marked is cut off, and a clip may be up to one
    keyframe interval longer on each side. Each output is named
    <video>_<HHMMSS>-<HHMMSS>.<ext> unless -o is given.
    """
    if output is not None and len(ranges) > 1:
        raise click.UsageError("-o/--output works with a single range; use --output-dir")
    if output is not None and output_dir is not None:
        raise click.UsageError("use either -o/--output or --output-dir")
    try:
        marked = [parse_range(r) for r in ranges]
    except ValueError as e:
        raise click.BadParameter(str(e), param_hint="RANGES") from e

    try:
        index = load_frame_index(video)
    except (ValueError, OSError) as e:
        raise click.ClickException(str(e)) from e
    except Exception as e:  # PyAV/ffmpeg errors on unreadable files
        raise click.ClickException(f"{video}: {e}") from e

    length = index.seconds(index.end_pts - index.pts_of(0))
    jobs = []
    for start, end in marked:
        if start >= length:
            raise click.ClickException(
                f"{_fmt_s(start)}-{_fmt_s(end)} starts after the end of the video"
                f" ({_fmt_s(length)})"
            )
        pts_in, pts_out = pts_at(index, start), pts_at(index, end)
        try:
            plan = plan_clip(index, pts_in, pts_out)
        except ValueError as e:
            raise click.ClickException(f"{_fmt_s(start)}-{_fmt_s(end)}: {e}") from e
        dst = output or default_output(video, start, end, output_dir)
        jobs.append((pts_in, pts_out, (float(start), float(end)), plan, dst))

    if dry_run:
        first = index.pts_of(0)
        for _, _, (start, end), plan, dst in jobs:
            a, b = index.seconds(plan.pts_in - first), index.seconds(plan.pts_out - first)
            click.echo(
                f"{dst.name}: {_fmt_s(a)}-{_fmt_s(b)} (marked {_fmt_s(start)}-{_fmt_s(end)}),"
                f" frames {plan.snapped.start}-{plan.snapped.end}"
            )
        return

    names = [dst for *_, dst in jobs]
    if len(set(names)) != len(names):
        raise click.UsageError(
            "two ranges give the same output name; export them one by one with -o"
        )
    existing = [str(dst) for dst in names if dst.exists()]
    if existing and not force:
        raise click.ClickException(
            "output exists (use --force to overwrite): " + ", ".join(existing)
        )
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)

    for pts_in, pts_out, marked_s, _, dst in jobs:
        with click.progressbar(length=1000, label=dst.name, file=None) as bar:
            done = [0]

            def progress(fraction: float, bar=bar, done=done) -> None:
                step = int(fraction * 1000)
                if step > done[0]:
                    bar.update(step - done[0])
                    done[0] = step

            try:
                result = export_clip(
                    video, dst, pts_in, pts_out, index=index, audio=not no_audio, progress=progress
                )
            except KeyboardInterrupt:
                click.echo()
                raise click.ClickException(f"cancelled, no output written for {dst.name}") from None
            except (ValueError, OSError) as e:
                raise click.ClickException(f"{dst.name}: {e}") from e
        click.echo(_summary(result, marked_s))
