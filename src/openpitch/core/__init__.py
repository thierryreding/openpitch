# SPDX-License-Identifier: GPL-3.0-or-later
"""Analysis algorithms and models, usable from both the CLI and Studio.

core never imports openpitch.cli or openpitch.studio (docs/decisions/0002).
Heavy dependencies (torch, ultralytics, ...) are imported lazily inside functions.
"""
