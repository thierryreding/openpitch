# SPDX-License-Identifier: GPL-3.0-or-later
"""DJI recording metadata: the "CAM meta" data track of e.g. Osmo Action 6 files.

The track holds one protobuf message per frame (``dvtm_<model>.proto``, schema not
published). The first message starts with a header that records the camera and its
settings. Field numbers were worked out on Osmo Action 6 recordings (docs/design/video.md,
"Footage facts"; ``tools/dji_metadata.py`` inspects the rest).
"""

from __future__ import annotations

import os

import av
from pydantic import BaseModel, ConfigDict

#: Header field 2.5.1, measured on the Osmo Action 6.
FOV_SETTINGS = {1: "wide", 2: "standard", 3: "ultra_wide", 6: "natural_wide"}

META_TRACK = "CAM meta"


class DjiHeader(BaseModel):
    model_config = ConfigDict(frozen=True)

    #: e.g. "DJI OsmoAction6".
    model: str | None = None
    serial: str | None = None
    firmware: str | None = None
    #: "wide", "standard" (Standard (Dewarp)), "ultra_wide", "natural_wide", or
    #: "unknown:<n>" for a value not seen yet.
    fov: str | None = None
    stabilization: bool | None = None


# -- protobuf wire format ---------------------------------------------------------------


def _varint(b: bytes, i: int) -> tuple[int, int]:
    value = shift = 0
    while True:
        c = b[i]
        i += 1
        value |= (c & 0x7F) << shift
        shift += 7
        if c < 0x80:
            return value, i


def parse_message(b: bytes) -> list[tuple[int, int, int | bytes]] | None:
    """``(field, wire type, value)`` of a protobuf message, or None if ``b`` is not one.

    Varints come back as ints, everything else as raw bytes.
    """
    out: list[tuple[int, int, int | bytes]] = []
    i = 0
    try:
        while i < len(b):
            key, i = _varint(b, i)
            field, wire = key >> 3, key & 7
            if field == 0:
                return None
            if wire == 0:
                value, i = _varint(b, i)
            elif wire == 1:
                value, i = b[i : i + 8], i + 8
            elif wire == 5:
                value, i = b[i : i + 4], i + 4
            elif wire == 2:
                n, i = _varint(b, i)
                value, i = b[i : i + n], i + n
            else:
                return None
            if i > len(b):
                return None
            out.append((field, wire, value))
    except IndexError:
        return None
    return out


def _get(b: bytes, *path: int) -> int | bytes | None:
    """First value at a field number path, e.g. ``_get(msg, 2, 5, 1)``."""
    value: int | bytes | None = b
    for field in path:
        if not isinstance(value, bytes):
            return None
        found = next((v for f, _, v in parse_message(value) or [] if f == field), None)
        if found is None:
            return None
        value = found
    return value


def _text(value: int | bytes | None) -> str | None:
    if isinstance(value, bytes) and value and all(32 <= c < 127 for c in value):
        return value.decode("ascii")
    return None


def parse_header(packet: bytes) -> DjiHeader:
    """Decode the header from the first ``CAM meta`` packet. Unknown layouts give
    empty fields, never an error."""
    fov = _get(packet, 2, 5, 1)
    stabilization = _get(packet, 1, 9, 1)
    has_header = _get(packet, 1, 1) is not None
    return DjiHeader(
        model=_text(_get(packet, 1, 1, 10)),
        serial=_text(_get(packet, 1, 1, 5)),
        firmware=_text(_get(packet, 1, 1, 2)),
        fov=FOV_SETTINGS.get(fov, f"unknown:{fov}") if isinstance(fov, int) else None,
        # The flag is present (1) when stabilization is on and absent when it is off.
        stabilization=(stabilization == 1) if has_header else None,
    )


def read_header(path: str | os.PathLike[str]) -> DjiHeader | None:
    """Header of a DJI recording, or None if the file has no ``CAM meta`` track."""
    with av.open(str(path)) as container:
        streams = [s for s in container.streams if s.metadata.get("handler_name") == META_TRACK]
        if not streams:
            return None
        for packet in container.demux(streams[0]):
            if packet.size:
                return parse_header(bytes(packet))
    return None
