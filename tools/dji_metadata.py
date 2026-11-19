# SPDX-License-Identifier: GPL-3.0-or-later
"""Inspect the per-frame metadata tracks of DJI recordings (e.g. Osmo Action 6).

DJI MP4 files carry protobuf messages in data tracks named "CAM meta" (dvtm_*.proto)
and "CAM dbgi" (dbginfo_*.proto). DJI does not publish the schemas, so this decodes the
protobuf wire format without one: fields are shown by number path (e.g. 3.2.9.1).
Findings so far are in docs/design/video.md ("Footage facts").

Usage (from the repository root):
    uv run python tools/dji_metadata.py dump VIDEO [--track meta|dbgi] [--packets 0,1,30]
    uv run python tools/dji_metadata.py fields VIDEO [--track meta|dbgi] [--limit N]
    uv run python tools/dji_metadata.py diff VIDEO_A VIDEO_B [--track meta|dbgi] [--limit N]

``fields`` lists every field path with how often it occurs and its value range.
``diff`` compares two recordings (e.g. two FOV settings): paths that exist in only one,
and constant values that differ.
"""

from __future__ import annotations

import argparse
import collections
import math
import struct
import sys

import av

from openpitch.core.video.dji import parse_message

TRACKS = {"meta": "CAM meta", "dbgi": "CAM dbgi"}

# -- protobuf wire format (shared with openpitch.core.video.dji) -------------------------

parse = parse_message


def _text(v: bytes) -> str | None:
    return v.decode("ascii") if v and all(32 <= c < 127 for c in v) else None


def _is_message(v: bytes) -> list | None:
    """Sub-message, unless the bytes read better as text."""
    sub = parse(v) if v else None
    text = _text(v)
    if sub and not (text is not None and len(text) > 3):
        return sub
    return None


def leaves(b: bytes, path: str = ""):
    """Yield ``(path, value)`` for every leaf: int, float, str or ``bytes``."""
    for field, wire, v in parse(b) or []:
        p = f"{path}.{field}" if path else str(field)
        if wire == 0:
            yield p, v
        elif wire == 5:
            yield p, struct.unpack("<f", v)[0]
        elif wire == 1:
            yield p, struct.unpack("<d", v)[0]
        elif _is_message(v) is not None:
            yield from leaves(v, p)
        else:
            text = _text(v)
            yield p, text if text is not None else bytes(v)


def _describe(v: object) -> str:
    if isinstance(v, float):
        return f"{v:.6g}"
    if isinstance(v, bytes):
        desc = f"bytes[{len(v)}] {v[:24].hex()}"
        if len(v) % 4 == 0 and 4 <= len(v) <= 64:
            floats = struct.unpack(f"<{len(v) // 4}f", v)
            if all(math.isfinite(x) for x in floats):
                desc += "  as f32: " + " ".join(f"{x:.4g}" for x in floats)
        return desc
    return repr(v)


# -- reading tracks ---------------------------------------------------------------------


def packets(path: str, track: str, limit: int | None = None):
    """Payloads of the named data track, in order."""
    name = TRACKS[track]
    with av.open(path) as c:
        streams = [s for s in c.streams if s.metadata.get("handler_name") == name]
        if not streams:
            raise SystemExit(f"{path}: no {name!r} track")
        n = 0
        for packet in c.demux(streams[0]):
            if packet.size == 0:
                continue
            yield bytes(packet)
            n += 1
            if limit is not None and n >= limit:
                return


def collect(path: str, track: str, limit: int | None) -> tuple[int, dict[str, list]]:
    fields: dict[str, list] = collections.defaultdict(list)
    n = 0
    for payload in packets(path, track, limit):
        for p, v in leaves(payload):
            fields[p].append(v)
        n += 1
    return n, fields


def _order(path: str) -> list[int]:
    return [int(x) for x in path.split(".")]


def _summary(values: list) -> str:
    distinct = list(dict.fromkeys(_describe(v) for v in values))
    numeric = all(isinstance(v, int | float) for v in values)
    if numeric and len(distinct) > 3:
        return f"{min(values):.6g} .. {max(values):.6g} ({len(distinct)} distinct)"
    return ", ".join(distinct[:4]) + (" ..." if len(distinct) > 4 else "")


# -- commands ---------------------------------------------------------------------------


def cmd_dump(args) -> None:
    want = sorted(int(x) for x in args.packets.split(","))
    for k, payload in enumerate(packets(args.video, args.track, want[-1] + 1)):
        if k in want:
            print(f"===== packet {k} ({len(payload)} bytes)")
            for p, v in leaves(payload):
                print(f"{'  ' * p.count('.')}{p}: {_describe(v)}")


def cmd_fields(args) -> None:
    n, fields = collect(args.video, args.track, args.limit)
    print(f"{n} packets")
    for p in sorted(fields, key=_order):
        print(f"{p:20} in {len(fields[p]):6} packets: {_summary(fields[p])[:110]}")


def cmd_diff(args) -> None:
    na, a = collect(args.video_a, args.track, args.limit)
    nb, b = collect(args.video_b, args.track, args.limit)
    print(f"A: {na} packets, B: {nb} packets")
    for p in sorted(set(a) | set(b), key=_order):
        if p not in b:
            print(f"only A  {p:20} {_summary(a[p])[:90]}")
        elif p not in a:
            print(f"only B  {p:20} {_summary(b[p])[:90]}")
        else:
            ca = {_describe(v) for v in a[p]}
            cb = {_describe(v) for v in b[p]}
            if len(ca) == 1 and len(cb) == 1 and ca != cb:
                print(f"differs {p:20} A {next(iter(ca))[:40]}  B {next(iter(cb))[:40]}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name, func in (("dump", cmd_dump), ("fields", cmd_fields), ("diff", cmd_diff)):
        p = sub.add_parser(name)
        if name == "diff":
            p.add_argument("video_a")
            p.add_argument("video_b")
        else:
            p.add_argument("video")
        p.add_argument("--track", choices=sorted(TRACKS), default="meta")
        if name == "dump":
            p.add_argument("--packets", default="0", help="Comma-separated packet numbers.")
        else:
            p.add_argument("--limit", type=int, help="Read at most this many packets.")
        p.set_defaults(func=func)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    sys.exit(main())
