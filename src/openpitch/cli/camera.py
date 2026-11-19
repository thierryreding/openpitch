# SPDX-License-Identifier: GPL-3.0-or-later
"""``openpitch camera``: calibration boards and camera calibration."""

from __future__ import annotations

from pathlib import Path

import click

_NEEDS_CV = "camera calibration needs the 'cv' extra (OpenCV): uv sync --extra cv"


def _size(text: str | None, cast=int):
    """WIDTHxHEIGHT as two numbers (``cast``: int for pixels, float for millimeters)."""
    if text is None:
        return None
    try:
        w, h = (cast(x) for x in text.lower().split("x"))
    except ValueError:
        raise click.BadParameter(f"{text!r}: use WIDTHxHEIGHT, e.g. 2560x1600") from None
    if w <= 0 or h <= 0:
        raise click.BadParameter(f"{text!r}: sizes must be positive")
    return w, h


@click.group("camera")
def camera_cmd() -> None:
    """Calibrate cameras (lens and field of view, not the pitch)."""


@camera_cmd.command("board")
@click.option(
    "-o",
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    default=Path("charuco.png"),
    show_default=True,
    help="Board image (PNG). Its description is written next to it as .json.",
)
@click.option(
    "--size",
    required=True,
    help="Native resolution of the screen that will show the board, WIDTHxHEIGHT.",
)
@click.option("--screen-mm", help="Physical screen size WIDTHxHEIGHT in millimeters.")
@click.option("--rows", default=9, show_default=True, help="Squares on the short side.")
def board_cmd(output: Path, size: str, screen_mm: str | None, rows: int) -> None:
    """Make a ChArUco board that fills a screen of --size pixels.

    Show the image full-screen (e.g. in a web browser with F11) on that screen and
    record it with the camera to calibrate (see "openpitch camera calibrate"). Use the
    screen's native resolution, as the display settings show it. The physical size
    (--screen-mm) is only informational: calibration results do not depend on it.
    """
    from openpitch.core.camera import make_board, save_board

    pixels, mm = _size(size), _size(screen_mm, float)
    mm_per_px = mm[0] / pixels[0] if mm else None
    try:
        spec = make_board(*pixels, mm_per_px=mm_per_px, rows=rows)
        spec_path = save_board(spec, output)
    except ImportError:
        raise click.ClickException(_NEEDS_CV) from None
    except ValueError as e:
        raise click.ClickException(str(e)) from e
    square = f"{spec.square_px} px" + (f" = {spec.square_mm:.1f} mm" if spec.square_mm else "")
    click.echo(
        f"{output}: {spec.squares[0]}x{spec.squares[1]} squares of {square},"
        f" {spec.inner_corners} corners; description in {spec_path}"
    )


@camera_cmd.command("calibrate")
@click.argument("video", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "-b",
    "--board",
    "board_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=Path("charuco.json"),
    show_default=True,
    help="Board description written by 'openpitch camera board'.",
)
@click.option(
    "-o",
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Camera profile to write (default: <video>.camera.json next to VIDEO).",
)
@click.option(
    "--model",
    type=click.Choice(["auto", "none", "k1k2", "k1k2p1p2k3"]),
    default="auto",
    show_default=True,
    help="Distortion model. auto keeps the simplest one that fits as well as the others.",
)
@click.option("--stride", default=4, show_default=True, help="Look at every Nth frame.")
@click.option("--max-frames", default=60, show_default=True, help="Frames to fit with.")
@click.option("--no-hwdec", is_flag=True, help="Decode in software even if a GPU decoder works.")
@click.option("-f", "--force", is_flag=True, help="Overwrite an existing profile.")
def calibrate_cmd(
    video: Path,
    board_path: Path,
    output: Path | None,
    model: str,
    stride: int,
    max_frames: int,
    no_hwdec: bool,
    force: bool,
) -> None:
    """Calibrate the camera that recorded VIDEO, a video of the board.

    Record 20-30 s in exactly the mode to calibrate (resolution, FOV setting,
    stabilization). Keep the camera still and move the screen through the whole image,
    corners and edges included, tilted up to about 45 degrees, at about 0.7-1.2 m.
    """
    from openpitch.core.camera import calibrate, load_board, save_profile

    output = output or video.with_suffix(".camera.json")
    if output.exists() and not force:
        raise click.ClickException(f"{output} exists (use --force to overwrite)")
    spec = load_board(board_path)
    with click.progressbar(length=1000, label=f"detecting the board in {video.name}") as bar:
        done = [0]

        def progress(fraction: float) -> None:
            step = int(fraction * 1000)
            if step > done[0]:
                bar.update(step - done[0])
                done[0] = step

        try:
            profile = calibrate(
                video,
                spec,
                stride=stride,
                max_frames=max_frames,
                model=model,
                hwaccel=None if no_hwdec else "auto",
                progress=progress,
            )
        except ImportError:
            raise click.ClickException(_NEEDS_CV) from None
        except KeyboardInterrupt:
            click.echo()
            raise click.ClickException("cancelled, no profile written") from None
        except ValueError as e:
            raise click.ClickException(str(e)) from e
    save_profile(profile, output)

    mode = profile.mode
    settings = ", ".join(
        x
        for x in (
            f"FOV {mode.fov_setting}" if mode.fov_setting else None,
            None
            if mode.stabilization is None
            else f"stabilization {'on' if mode.stabilization else 'off'}",
        )
        if x
    )
    camera = profile.camera.model or "unknown camera"
    click.echo(
        f"{camera}, {mode.width}x{mode.height} @ {mode.fps or '?'} fps"
        + (f", {settings}" if settings else "")
    )
    click.echo(
        f"{profile.frames_used} frames, {profile.corners_used} corners; image coverage (8x6 cells):"
    )
    for row in profile.coverage:
        click.echo(f"  {row}")
    click.echo(f"{'model':12} {'RMS px':>7} {'fx':>8} {'fy':>8} {'cx':>7} {'cy':>7}  FOV h/v/d")
    for f in profile.fits:
        k = f.intrinsics
        mark = "*" if f.distortion_model == profile.distortion_model else " "
        click.echo(
            f"{mark}{f.distortion_model:11} {f.rms_px:7.3f} {k.fx:8.1f} {k.fy:8.1f} {k.cx:7.1f}"
            f" {k.cy:7.1f}  {f.fov.horizontal:.1f}/{f.fov.vertical:.1f}/{f.fov.diagonal:.1f}°"
        )
    click.echo(f"* written to {output}")
