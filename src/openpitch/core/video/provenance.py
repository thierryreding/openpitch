# SPDX-License-Identifier: GPL-3.0-or-later
"""Provenance of derived video files (docs/decisions/0010).

Files written by ``clip`` and ``recode`` carry their lineage in a container metadata tag,
so annotations made on a recode can be mapped back to the original footage. The tag
value is JSON::

    {"v": 1, "steps": [step, ...]}

Steps are ordered from the original footage to this file: the last step made this file,
from the file it names in ``source``. A step maps a time in the file it made to its
source: ``source_pts = seconds / source.time_base + pts_offset``, where ``seconds`` is
the made file's pts times its time base. Image coordinates scale from the made file's
size to ``source.width`` x ``source.height``.

Readers ignore fields they do not know, so steps can gain fields (e.g. a crop) without a
new version.
"""

from __future__ import annotations

import datetime as _dt
import json
from fractions import Fraction
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from openpitch import __version__

#: Container metadata key (an MP4 ``mdta`` key, a Matroska tag). Read case-insensitively.
METADATA_KEY = "org.openpitch.provenance"
VERSION = 1


class SourceRef(BaseModel):
    """The file a step started from."""

    model_config = ConfigDict(frozen=True)

    #: Content fingerprint (docs/decisions/0008).
    content_hash: str
    #: File name when the step ran (a hint for finding it, not an identity).
    file_name: str
    width: int
    height: int
    #: Time base of its video stream, e.g. "1/1000000".
    time_base: str


class ProvenanceStep(BaseModel):
    model_config = ConfigDict(frozen=True)

    op: Literal["clip", "recode"]
    source: SourceRef
    #: Added to a time converted to source pts (see the module docstring).
    pts_offset: int
    created_at: str
    tool: str

    def source_pts(self, seconds: Fraction | float) -> int:
        """pts in the source of a time (seconds on the made file's timeline)."""
        return round(Fraction(seconds) / Fraction(self.source.time_base)) + self.pts_offset


def read_provenance(metadata: dict[str, str]) -> list[ProvenanceStep]:
    """Lineage from container metadata. Missing, unreadable or newer tags give ``[]``:
    a bad tag must never stop an export, it only loses the link."""
    # Matroska stores tag names upper-case.
    raw = next((v for k, v in metadata.items() if k.lower() == METADATA_KEY), None)
    if not raw:
        return []
    try:
        value = json.loads(raw)
        if not isinstance(value, dict) or value.get("v") != VERSION:
            return []
        return [ProvenanceStep.model_validate(s) for s in value.get("steps", [])]
    except (ValueError, TypeError, ValidationError):
        return []


def make_step(
    op: Literal["clip", "recode"],
    src: Path,
    content_hash: str,
    width: int,
    height: int,
    time_base: Fraction,
    pts_offset: int,
) -> ProvenanceStep:
    return ProvenanceStep(
        op=op,
        source=SourceRef(
            content_hash=content_hash,
            file_name=src.name,
            width=width,
            height=height,
            time_base=f"{time_base.numerator}/{time_base.denominator}",
        ),
        pts_offset=pts_offset,
        created_at=_dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        tool=f"openpitch {__version__}",
    )


def provenance_value(steps: list[ProvenanceStep]) -> str:
    """The tag value for ``steps``."""
    return json.dumps(
        {"v": VERSION, "steps": [s.model_dump() for s in steps]}, separators=(",", ":")
    )


def add_step(in_metadata: dict[str, str], out_metadata, step: ProvenanceStep) -> None:
    """Write the source's lineage plus ``step`` to the output container's metadata."""
    out_metadata[METADATA_KEY] = provenance_value([*read_provenance(in_metadata), step])
