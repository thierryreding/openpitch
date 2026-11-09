# SPDX-License-Identifier: GPL-3.0-or-later
import json

import pytest
from click.testing import CliRunner

from openpitch.cli import main


@pytest.mark.parametrize("name", ["regular", "jitter_bframes"])
def test_cli_probe(videos, name):
    runner = CliRunner()
    result = runner.invoke(main, ["probe", str(videos[name])])
    assert result.exit_code == 0, result.output
    assert "Keyframes" in result.output and "opfp1:" in result.output

    result = runner.invoke(main, ["probe", "--json", "--no-cache", str(videos[name])])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["frames"] == 90
    assert data["info"]["codec"] == "h264"
    if name == "jitter_bframes":
        # Offsets of up to +-40 against a line through the (jittered) first and last frame.
        assert 0 < data["max_jitter_pts"] <= 81
        assert data["gop_frames"] == {"min": 1, "median": 24.5, "max": 40}  # GOPs 12, 1, 37, 40


def test_cli_probe_bad_file(tmp_path):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"nope")
    result = CliRunner().invoke(main, ["probe", str(bad)])
    assert result.exit_code == 1
    assert "Error" in result.output


def test_time_format_rounds_before_splitting():
    from openpitch.cli import clip, probe

    for fmt in (clip._fmt_s, probe._fmt_s):
        assert fmt(299.999986) == "5:00.000"
        assert fmt(59.9996) == "1:00.000"
        assert fmt(83.5) == "1:23.500"
        assert fmt(3599.9999) == "1:00:00.000"
        assert fmt(3723.25) == "1:02:03.250"
