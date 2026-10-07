from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from reclamo import __version__
from reclamo.cli import main
from tests.conftest import FakeServer, chat_response


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


# --- ping -------------------------------------------------------------------


def _profiles_file(tmp_path: Path, base_url: str) -> Path:
    p = tmp_path / "profiles.toml"
    p.write_text(
        f"""
[profiles.fake]
base_url = "{base_url}"
[profiles.fake.root]
model = "fake-model"
enable_thinking = true
[profiles.fake.sub]
model = "fake-model"
""",
        encoding="utf-8",
    )
    return p


def test_ping_happy_path(
    fake_server: FakeServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("RECLAMO_API_KEY", "sk-test")
    fake_server.models = ["fake-model"]
    fake_server.script(
        chat_response("pong", model="fake-model"),
        chat_response("pong", reasoning_content="thought about it", model="fake-model"),
    )
    profiles = _profiles_file(tmp_path, fake_server.base_url)

    rc = main(["ping", "--profile", "fake", "--profiles", str(profiles)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "models:   fake-model" in out
    assert "model:    fake-model" in out
    assert "reply:    'pong'" in out
    assert "usage:    10 prompt + 5 completion = 15 tokens" in out
    assert "thinking: yes" in out
    assert "sk-test" not in out

    posts = [r for r in fake_server.requests if r.method == "POST"]
    assert posts[0].body["chat_template_kwargs"]["enable_thinking"] is False
    assert posts[1].body["chat_template_kwargs"]["enable_thinking"] is True


def test_ping_reports_no_thinking_and_empty_models(
    fake_server: FakeServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("RECLAMO_API_KEY", "sk-test")
    fake_server.models = []
    fake_server.script(chat_response("pong", usage=False), chat_response("pong"))
    profiles = _profiles_file(tmp_path, fake_server.base_url)
    assert main(["ping", "--profile", "fake", "--profiles", str(profiles)]) == 0
    out = capsys.readouterr().out
    assert "(none listed)" in out
    assert "usage:    (not reported)" in out
    assert "thinking: no" in out


def test_ping_missing_key_exits_2(
    fake_server: FakeServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("RECLAMO_API_KEY", raising=False)
    profiles = _profiles_file(tmp_path, fake_server.base_url)
    assert main(["ping", "--profile", "fake", "--profiles", str(profiles)]) == 2
    assert "no API key: set RECLAMO_API_KEY" in capsys.readouterr().err


def test_ping_unknown_profile_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("RECLAMO_API_KEY", "sk-test")
    assert main(["ping", "--profile", "nope", "--profiles", str(tmp_path / "none.toml")]) == 2
    assert "unknown profile 'nope'" in capsys.readouterr().err


def test_ping_request_failure_exits_1(
    fake_server: FakeServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("RECLAMO_API_KEY", "sk-test")
    fake_server.script(401, 401, 401, 401, 401)
    profiles = _profiles_file(tmp_path, fake_server.base_url)
    assert main(["ping", "--profile", "fake", "--profiles", str(profiles)]) == 1
    assert "request failed: AuthenticationError" in capsys.readouterr().err
