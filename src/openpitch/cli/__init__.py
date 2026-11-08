# SPDX-License-Identifier: GPL-3.0-or-later
"""Command line tools: thin click wrappers over openpitch.core."""

import click

from openpitch import __version__


@click.group()
@click.version_option(__version__, prog_name="openpitch")
def main() -> None:
    """OpenPitch command line tools."""
