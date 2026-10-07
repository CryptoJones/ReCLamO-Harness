import subprocess
import sys

import pytest

from reclamo import __version__
from reclamo.cli import main


def test_version_flag_prints_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    out = capsys.readouterr().out.strip()
    assert out == f"reclamo {__version__}"


def test_no_args_prints_usage_and_fails(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 2
    assert "usage: reclamo" in capsys.readouterr().err


def test_console_script_version() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "reclamo.cli", "--version"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == f"reclamo {__version__}"
