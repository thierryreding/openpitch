# SPDX-License-Identifier: GPL-3.0-or-later
"""OpenPitch: football video tools for amateur coaches."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("openpitch")
except PackageNotFoundError:  # running from a source tree without install
    __version__ = "0.0.0"
