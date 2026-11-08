# SPDX-License-Identifier: GPL-3.0-or-later
from click.testing import CliRunner

import openpitch
from openpitch.cli import main


def test_cli_version():
    result = CliRunner().invoke(main, ["--version"])
    assert result.exit_code == 0
    assert openpitch.__version__ in result.output
