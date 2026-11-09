# SPDX-License-Identifier: GPL-3.0-or-later
"""``openpitch recode``: re-encode footage to a smaller file for sharing."""

from __future__ import annotations

from pathlib import Path

import click

from openpitch.core.video.recode import (
    CODECS,
    CONTAINERS,
    DEFAULT_HEIGHT,
    DEFAULT_PRESET,
    DEFAULT_PROFILE,
    ENCODERS,
    KEYFRAME_SECONDS,
    PROFILES,
    RecodeResult,
    RecodeSettings,
    default_output,
    recode,
)


def _profiles_help() -> str:
    rows = [
        f"{name}: x264 CRF {q['x264']}, x265 CRF {q['x265']}, NVENC CQ {q['nvenc']}"
        for name, q in PROFILES.items()
    ]
    return "; ".join(rows)


def _fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1000 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1000
    raise AssertionError


def _fmt_s(seconds: float) -> str:
    m, s = divmod(int(round(seconds)), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _summary(r: RecodeResult) -> str:
    speed = r.duration_s / r.seconds if r.seconds else 0
    return (
        f"{Path(r.output).name}: {_fmt_bytes(r.input_bytes)} -> {_fmt_bytes(r.output_bytes)}"
        f" ({r.ratio:.0%}), {r.width}x{r.height} {r.codec}/{r.container},"
        f" {r.encoder} q{r.quality} {r.preset},"
        f" decoder {r.decoder}, audio {r.audio},"
        f" {_fmt_s(r.seconds)} for {_fmt_s(r.duration_s)} ({speed:.1f}x realtime)"
    )


@click.command("recode")
@click.argument(
    "videos", nargs=-1, required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path)
)
@click.option(
    "-p",
    "--profile",
    type=click.Choice(list(PROFILES)),
    default=DEFAULT_PROFILE,
    show_default=True,
    help=f"Quality/size profile. {_profiles_help()}.",
)
@click.option(
    "--height", default=DEFAULT_HEIGHT, show_default=True, help="Output height (never upscales)."
)
@click.option(
    "--codec",
    type=click.Choice(CODECS),
    default="h264",
    show_default=True,
    help="h264 plays everywhere. hevc is 30-50% smaller at the same quality and plays on"
    " Apple devices and in Chrome, but Windows players need the HEVC extension.",
)
@click.option(
    "--encoder",
    type=click.Choice(ENCODERS),
    default="auto",
    show_default=True,
    help="auto uses NVENC when it works here (several times faster, slightly bigger files"
    " for the same quality), else software (x264/x265).",
)
@click.option(
    "--container",
    type=click.Choice(CONTAINERS),
    default="mp4",
    show_default=True,
    help="mp4 plays everywhere. mkv plays on Windows and in VLC, but not on iPads,"
    " iPhones or in QuickTime.",
)
@click.option("--crf", "quality", type=int, help="Override the profile's CRF/CQ value.")
@click.option(
    "--preset",
    help=f"Encoder preset (default: x264/x265 {DEFAULT_PRESET['x264']},"
    f" NVENC {DEFAULT_PRESET['nvenc']}).",
)
@click.option(
    "--audio",
    type=click.Choice(["copy", "aac", "none"]),
    default="copy",
    show_default=True,
    help="Copy the audio track (re-encoded to AAC if MP4 cannot carry it), re-encode, or drop.",
)
@click.option(
    "-k",
    "--keyframe-interval",
    "keyframe_seconds",
    type=click.FloatRange(min=0, min_open=True),
    default=KEYFRAME_SECONDS,
    show_default=True,
    help="Seconds between keyframes. Clips cut from the output by stream copy can grow by"
    " up to this much on each side; 1 makes about 23% bigger files than 5, 2 about 8%.",
)
@click.option("--no-hwdec", is_flag=True, help="Decode in software even if a GPU decoder works.")
@click.option(
    "-o",
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Output file (single input only).",
)
@click.option(
    "-d",
    "--output-dir",
    type=click.Path(file_okay=False, path_type=Path),
    help="Directory for outputs (default: next to each input).",
)
@click.option("-f", "--force", is_flag=True, help="Overwrite existing outputs.")
def recode_cmd(
    videos: tuple[Path, ...],
    profile: str,
    height: int,
    codec: str,
    encoder: str,
    container: str,
    quality: int | None,
    preset: str | None,
    audio: str,
    keyframe_seconds: float,
    no_hwdec: bool,
    output: Path | None,
    output_dir: Path | None,
    force: bool,
) -> None:
    """Re-encode VIDEOS to smaller MP4 files for sharing, e.g. 4K to 1080p.

    Output is H.264 (default) or HEVC in MP4 (default) or MKV, BT.709 limited range, with
    the index in front so it streams well from cloud storage. NVENC encodes when it works
    here. Each output is named <input>_<height>p.<ext> unless -o is given. An
    interrupted run leaves no partial file behind.
    """
    if output is not None and len(videos) > 1:
        raise click.UsageError("-o/--output works with a single input; use --output-dir")
    if output is not None and output_dir is not None:
        raise click.UsageError("use either -o/--output or --output-dir")
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)

    settings = RecodeSettings(
        height=height,
        profile=profile,
        codec=codec,
        encoder=encoder,
        container=container,
        quality=quality,
        preset=preset,
        hwaccel=None if no_hwdec else "auto",
        audio=audio,
        keyframe_seconds=keyframe_seconds,
    )
    targets = [(v, output or default_output(v, height, output_dir, container)) for v in videos]
    existing = [str(dst) for _, dst in targets if dst.exists()]
    if existing and not force:
        raise click.ClickException(
            "output exists (use --force to overwrite): " + ", ".join(existing)
        )

    for src, dst in targets:
        with click.progressbar(length=1000, label=src.name, show_eta=True, file=None) as bar:
            done = [0]

            def progress(fraction: float, bar=bar, done=done) -> None:
                step = int(fraction * 1000)
                if step > done[0]:
                    bar.update(step - done[0])
                    done[0] = step

            try:
                result = recode(src, dst, settings, progress=progress)
            except KeyboardInterrupt:
                click.echo()
                raise click.ClickException(f"cancelled, no output written for {src.name}") from None
            except (ValueError, OSError) as e:
                raise click.ClickException(f"{src.name}: {e}") from e
        click.echo(_summary(result))
