# SPDX-License-Identifier: GPL-3.0-or-later
"""Command line tools: thin click wrappers over openpitch.core."""

import click

from openpitch import __version__
from openpitch.cli.bench import bench_decode_cmd
from openpitch.cli.clip import clip_cmd
from openpitch.cli.probe import probe_cmd
from openpitch.cli.recode import recode_cmd


@click.group()
@click.version_option(__version__, prog_name="openpitch")
def main() -> None:
    """OpenPitch command line tools."""


main.add_command(probe_cmd)
main.add_command(bench_decode_cmd)
main.add_command(recode_cmd)
main.add_command(clip_cmd)
