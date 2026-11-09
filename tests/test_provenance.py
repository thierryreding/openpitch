# SPDX-License-Identifier: GPL-3.0-or-later
from fractions import Fraction
from pathlib import Path

import av
import pytest
from click.testing import CliRunner

from openpitch.cli import main
from openpitch.core.fingerprint import fingerprint
from openpitch.core.video import build_frame_index, export_clip, probe
from openpitch.core.video.provenance import (
    METADATA_KEY,
    ProvenanceStep,
    make_step,
    provenance_value,
    read_provenance,
)
from openpitch.core.video.recode import RecodeSettings, recode
from videogen import VideoSpec, frame_id, make_video

SOFTWARE = RecodeSettings(encoder="software", hwaccel=None)


def _frames(path):
    """(seconds, frame_id) of every decoded frame."""
    with av.open(str(path)) as c:
        return [
            (Fraction(f.pts) * f.time_base, frame_id(f.to_ndarray(format="rgb24")))
            for f in c.decode(video=0)
        ]


def _source_frame(index, step: ProvenanceStep, seconds):
    return index.frame_at(step.source_pts(seconds))


@pytest.mark.parametrize("ext", [".mp4", ".mkv"])
def test_clip_maps_back_to_its_source(videos, tmp_path, ext):
    src = videos["jitter_bframes"]
    index = build_frame_index(src, content_hash=fingerprint(src))
    dst = tmp_path / f"clip{ext}"
    result = export_clip(src, dst, index.pts_of(20), index.pts_of(40), index=index)

    (step,) = probe(dst).provenance
    assert step.op == "clip"
    assert step.source.content_hash == fingerprint(src)
    assert step.source.file_name == src.name
    assert (step.source.width, step.source.height) == (64, 48)
    assert Fraction(step.source.time_base) == index.time_base
    assert step.pts_offset == result.pts_in
    # Every frame of the clip maps to the source frame it shows.
    for seconds, fid in _frames(dst):
        assert _source_frame(index, step, seconds) == fid


def test_lineage_accumulates_through_clip_and_recode(videos, tmp_path):
    raw = videos["bframes"]
    raw_index = build_frame_index(raw)
    game = tmp_path / "game.mp4"
    export_clip(raw, game, raw_index.pts_of(30), raw_index.end_pts)
    shared = tmp_path / "shared.mp4"
    recode(game, shared, SOFTWARE)

    steps = probe(shared).provenance
    assert [s.op for s in steps] == ["clip", "recode"]  # original first
    assert steps[0].source.content_hash == fingerprint(raw)
    assert steps[1].source.content_hash == fingerprint(game)
    assert steps[1].pts_offset == 0

    # Compose: recode -> game segment -> raw recording.
    game_tb = Fraction(steps[1].source.time_base)
    for seconds, fid in _frames(shared):
        game_pts = steps[1].source_pts(seconds)
        assert _source_frame(raw_index, steps[0], game_pts * game_tb) == fid


def test_other_metadata_survives_metadata_tags(tmp_path):
    src = make_video(
        tmp_path / "src.mp4",
        VideoSpec(frames=30, metadata={"creation_time": "2026-11-08T14:03:10Z"}),
    )
    dst = tmp_path / "out.mp4"
    recode(src, dst, SOFTWARE)
    with av.open(str(dst)) as c:
        assert c.metadata["creation_time"].startswith("2026-11-08T14:03:10")
        assert METADATA_KEY in c.metadata


def test_bad_tags_are_ignored():
    step = make_step("recode", Path("a.mp4"), "opfp1:00", 2, 2, Fraction(1, 1000), 0)
    good = provenance_value([step])
    assert read_provenance({METADATA_KEY: good}) == [step]
    for bad in ("", "{", "[]", '{"v": 2, "steps": []}', '{"v": 1, "steps": [{"op": "x"}]}'):
        assert read_provenance({METADATA_KEY: bad}) == []
    assert read_provenance({}) == []


def test_unknown_fields_are_ignored():
    step = make_step("clip", Path("a.mp4"), "opfp1:00", 2, 2, Fraction(1, 1000), 5)
    value = provenance_value([step]).replace('"op":', '"crop":null,"op":')
    assert read_provenance({METADATA_KEY: value}) == [step]


def test_probe_cli_shows_lineage(videos, tmp_path):
    src = videos["regular"]
    index = build_frame_index(src)
    dst = tmp_path / "clip.mp4"
    export_clip(src, dst, index.pts_of(30), index.pts_of(60))
    result = CliRunner().invoke(main, ["probe", str(dst)])
    assert result.exit_code == 0, result.output
    assert "Derived from" in result.output and "clip of regular.mp4" in result.output
