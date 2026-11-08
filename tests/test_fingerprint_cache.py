# SPDX-License-Identifier: GPL-3.0-or-later
import hashlib
import shutil
import struct

import numpy as np
import pytest

from openpitch.core import fingerprint as fp
from openpitch.core.video import index as index_mod
from openpitch.core.video import index_cache_path, load_frame_index

MiB = 1 << 20


def _pattern(n: int) -> bytes:
    """Deterministic non-repeating bytes (no two blocks alike)."""
    i = np.arange(n, dtype=np.uint64)
    return ((i * 2654435761) >> 13).astype(np.uint8).tobytes()


def _reference(data: bytes) -> str:
    """Independent implementation of the opfp1 definition (docs/decisions/0008)."""
    size = len(data)
    length = min(MiB, size)
    h = hashlib.sha256(b"opfp1" + struct.pack(">Q", size))
    for i in range(64):
        offset = i * (size - length) // 63
        h.update(data[offset : offset + length])
    return "opfp1:" + h.hexdigest()


# Known-answer vectors. They pin the definition: never change them, add opfp2 instead.
# "empty" and "abc" were cross-checked with coreutils sha256sum.
KNOWN = {
    "empty": (b"", "63ced28dd407facd052bfac64dd9c1424ac1314ef91f25a15240a0f0c5efe800"),
    "abc": (b"abc", "f4c131b115bc3a65a2d1f6a2df9244ecb8d821281a3d93860e37e584da5c8fb5"),
    "1MiB-1": (MiB - 1, "1122c3ffec2984398bc6afde1f4ec165fbd1a668c0933fb4ad20f27ed74b52d8"),
    "3MiB": (3 * MiB, "6b2af06d04076d5f02274d6c5d6982819e008112e26bb96c448f460ea35ef2f2"),
    "64MiB": (64 * MiB, "91339c0c7fc9bb21146961d0a2ebaf04225f1a6c646cfb0065d39442521c3b9f"),
    "64MiB+1": (64 * MiB + 1, "2e4ee545db50d370ccf6d3394629407532b49bfe7ab01e6ce0916dcc71fdf229"),
    "100MiB+7": (
        100 * MiB + 7,
        "a49f6dad3e2b92f8979c3eeadc7dbc6a83b9c152d1a2305d464e5e56ec59c1bd",
    ),
}


@pytest.mark.parametrize("name", list(KNOWN))
def test_fingerprint_known_answers(tmp_path, name):
    content, digest = KNOWN[name]
    data = content if isinstance(content, bytes) else _pattern(content)
    path = tmp_path / "f.bin"
    path.write_bytes(data)
    assert fp.fingerprint(path) == f"opfp1:{digest}"
    assert _reference(data) == f"opfp1:{digest}"


@pytest.mark.parametrize("size", [1, 5, MiB - 1, MiB, MiB + 1, 64 * MiB])
def test_fingerprint_covers_every_byte_up_to_64_mib(tmp_path, size):
    data = bytearray(_pattern(size))
    path = tmp_path / "f.bin"
    path.write_bytes(data)
    base = fp.fingerprint(path)
    # Probe the edges and the gaps an evenly spaced sampler would leave.
    positions = {0, size - 1, size // 2, size // 3, min(size - 1, MiB + 7), size * 62 // 63}
    for pos in positions:
        changed = bytearray(data)
        changed[pos] ^= 0xFF
        path.write_bytes(changed)
        assert fp.fingerprint(path) != base, pos


def test_fingerprint_samples_large_files(tmp_path):
    size = 128 * MiB  # blocks start every ~2.02 MiB, so 1.5 MiB is not sampled
    data = bytearray(_pattern(size))
    path = tmp_path / "f.bin"
    path.write_bytes(data)
    base = fp.fingerprint(path)
    for pos, sampled in [(0, True), (size - 1, True), (MiB + MiB // 2, False)]:
        changed = bytearray(data)
        changed[pos] ^= 0xFF
        path.write_bytes(changed)
        assert (fp.fingerprint(path) != base) == sampled, pos
    # The size is always part of the input.
    path.write_bytes(data + b"\0")
    assert fp.fingerprint(path) != base


def test_sha256_file(tmp_path):
    path = tmp_path / "a.bin"
    path.write_bytes(b"abc")
    assert fp.sha256_file(path) == (
        "sha256:ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )


def test_index_cache_roundtrip(videos, tmp_path, monkeypatch):
    path = videos["irregular"]
    first = load_frame_index(path)
    entry = index_cache_path(first.content_hash)
    assert entry.is_file()

    # A copy under another name hits the same cache entry without demuxing.
    copy = tmp_path / "renamed.mp4"
    shutil.copy(path, copy)

    def no_build(*args, **kwargs):
        raise AssertionError("cache miss")

    monkeypatch.setattr(index_mod, "build_frame_index", no_build)
    cached = load_frame_index(copy)
    assert cached.pts.tolist() == first.pts.tolist()
    assert cached.keyframes.tolist() == first.keyframes.tolist()
    assert cached.end_pts == first.end_pts
    assert cached.time_base == first.time_base
    assert cached.content_hash == first.content_hash


def test_index_cache_disabled_and_corrupt(videos, monkeypatch):
    path = videos["bframes"]
    index = load_frame_index(path, cache=False)
    assert not index_cache_path(index.content_hash).exists()

    entry = index_cache_path(index.content_hash)
    entry.parent.mkdir(parents=True)
    entry.write_bytes(b"garbage")
    rebuilt = load_frame_index(path)
    assert rebuilt.pts.tolist() == index.pts.tolist()
    assert entry.stat().st_size > len(b"garbage")


def test_index_cache_unwritable(videos, tmp_path, monkeypatch):
    blocker = tmp_path / "file-not-dir"
    blocker.write_text("")
    monkeypatch.setenv("OPENPITCH_CACHE_DIR", str(blocker))
    assert len(load_frame_index(videos["regular"])) == 90


def test_cache_dir_override(monkeypatch, tmp_path):
    from openpitch.core.cache import cache_dir

    monkeypatch.setenv("OPENPITCH_CACHE_DIR", str(tmp_path / "x"))
    assert cache_dir() == tmp_path / "x"
    monkeypatch.delenv("OPENPITCH_CACHE_DIR")
    assert cache_dir().name in ("openpitch", "Cache")
