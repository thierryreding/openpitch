# SPDX-License-Identifier: GPL-3.0-or-later
"""Per-user cache directory for derived data that can always be rebuilt.

Set ``OPENPITCH_CACHE_DIR`` to override the location (tests, portable installs).
Deleting the directory is always safe.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def cache_dir() -> Path:
    if override := os.environ.get("OPENPITCH_CACHE_DIR"):
        return Path(override)
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "openpitch" / "Cache"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "openpitch"
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "openpitch"
