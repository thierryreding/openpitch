# SPDX-License-Identifier: GPL-3.0-or-later
from openpitch.core.video.dji import parse_header, read_header


def _pb(field, value):
    """Minimal protobuf encoder: ints as varints, bytes/str as length-delimited."""

    def varint(n):
        out = bytearray()
        while True:
            out.append((n & 0x7F) | (0x80 if n > 0x7F else 0))
            n >>= 7
            if not n:
                return bytes(out)

    if isinstance(value, int):
        return varint(field << 3) + varint(value)
    value = value.encode() if isinstance(value, str) else value
    return varint(field << 3 | 2) + varint(len(value)) + value


def _header(fov=None, stabilization=None):
    info = (
        _pb(1, "dvtm_ac206.proto")
        + _pb(2, "02.01.19")
        + _pb(5, "SERIAL")
        + _pb(10, "DJI OsmoAction6")
    )
    stab = _pb(1, 1) if stabilization else b""
    header = _pb(1, info) + _pb(9, stab)
    mode = _pb(3, _pb(1, 3840) + _pb(2, 2880)) + (_pb(5, _pb(1, fov)) if fov else b"")
    return _pb(1, header) + _pb(2, mode)


def test_dji_header():
    h = parse_header(_header(fov=2, stabilization=True))
    assert (h.model, h.serial, h.firmware) == ("DJI OsmoAction6", "SERIAL", "02.01.19")
    assert (h.fov, h.stabilization) == ("standard", True)
    h = parse_header(_header(fov=3, stabilization=False))
    assert (h.fov, h.stabilization) == ("ultra_wide", False)
    assert parse_header(_header(fov=9)).fov == "unknown:9"
    assert parse_header(b"\xff\xff") == parse_header(b"")  # not protobuf: all None


def test_read_header_without_dji_track(videos):
    assert read_header(videos["regular"]) is None
