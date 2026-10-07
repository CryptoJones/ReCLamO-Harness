"""Docker sandbox tests. They skip themselves when no Docker daemon is reachable."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator
from typing import Any

import pytest

from reclamo.config import ModelConfig, RLMConfig
from reclamo.repl import DockerUnavailable, make_repl
from reclamo.repl.docker_repl import DEFAULT_IMAGE, DockerREPL, check_docker


def _docker_available() -> bool:
    try:
        check_docker()
    except DockerUnavailable:
        return False
    return True


pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(not _docker_available(), reason="no Docker daemon reachable"),
]


def _cfg(**overrides: Any) -> RLMConfig:
    fields: dict[str, Any] = {
        "name": "test",
        "base_url": "http://unused/v1",
        "sandbox": "docker",
        "exec_timeout": 60.0,  # first launch may pull the image
        "output_truncate_chars": 500,
        "max_subcalls_per_exec": 5,
        "root": ModelConfig(model="m"),
        "sub": ModelConfig(model="m"),
    }
    fields.update(overrides)
    return RLMConfig(**fields)


def _handler(kind: str, prompts: list[str]) -> list[str]:
    return [f"{kind}:{p}" for p in prompts]


def _container_running(name: str) -> bool:
    out = subprocess.run(
        ["docker", "ps", "-a", "--filter", f"name=^{name}$", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    return name in out.split()


@pytest.fixture(scope="module", autouse=True)
def _pull_image() -> None:
    subprocess.run(["docker", "pull", "-q", DEFAULT_IMAGE], capture_output=True, check=False)


@pytest.fixture
def repl() -> Iterator[DockerREPL]:
    r = DockerREPL(_cfg(), _handler)
    r.start("line one\nline two\nline three\n")
    try:
        yield r
    finally:
        r.close()


def test_make_repl_dispatches_on_sandbox() -> None:
    r = make_repl(_cfg(), _handler)
    assert isinstance(r, DockerREPL)
    with pytest.raises(ValueError, match="unknown sandbox"):
        make_repl(_cfg(sandbox="firecracker"), _handler)


def test_round_trip_with_llm_query(repl: DockerREPL) -> None:
    res = repl.execute("n = len(context.splitlines())\nr = llm_query('q')\nprint(n, r)")
    assert res.ok and res.stdout == "3 llm_query:q\n"
    assert repl.execute("print(n)").stdout == "3\n"  # state persists in the container


def test_runs_as_nobody_in_the_image(repl: DockerREPL) -> None:
    res = repl.execute("import os, sys\nprint(os.getuid(), os.getgid(), sys.version_info[:2])")
    assert res.stdout == "65534 65534 (3, 12)\n"


def test_network_is_off(repl: DockerREPL) -> None:
    code = (
        "import socket\n"
        "try:\n"
        "    socket.create_connection(('1.1.1.1', 53), timeout=2)\n"
        "    print('connected')\n"
        "except OSError as e:\n"
        "    print('blocked', type(e).__name__)\n"
    )
    res = repl.execute(code)
    assert res.ok and res.stdout.startswith("blocked ")


def test_filesystem_read_only_outside_tmp(repl: DockerREPL) -> None:
    code = (
        "import os\n"
        "for p in ('/usr/x', '/work/x', '/reclamo/x', '/x'):\n"
        "    try:\n"
        "        open(p, 'w').close(); print(p, 'WRITABLE')\n"
        "    except OSError as e:\n"
        "        print(p, type(e).__name__)\n"
        "open('/tmp/ok', 'w').write('x'); print('/tmp ok', os.path.exists('/tmp/ok'))\n"
    )
    res = repl.execute(code)
    assert "WRITABLE" not in res.stdout
    assert res.stdout.endswith("/tmp ok True\n")


def test_context_mounted_read_only(repl: DockerREPL) -> None:
    res = repl.execute("print(open('/work/context.txt').read() == context, len(context))")
    assert res.stdout == "True 29\n"


def test_no_secrets_in_container_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RECLAMO_API_KEY", "sk-should-not-leak")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-leak-either")
    r = DockerREPL(_cfg(), _handler)
    r.start("ctx")
    try:
        res = r.execute("import os\nprint(sorted(os.environ))")
        assert "should-not-leak" not in res.stdout
        assert "RECLAMO_API_KEY" not in res.stdout and "OPENAI_API_KEY" not in res.stdout
    finally:
        r.close()


def test_timeout_kills_container_and_restarts() -> None:
    r = DockerREPL(_cfg(exec_timeout=20.0), _handler)
    r.start("ctx")
    try:
        first = r.container
        assert first is not None and _container_running(first)
        r.cfg.exec_timeout = 1.0
        res = r.execute("import time\ntime.sleep(60)")
        r.cfg.exec_timeout = 20.0
        assert res.restarted and res.error is not None and res.error.startswith("timeout after 1s")
        assert not _container_running(first)
        assert r.container is not None and r.container != first
        assert r.execute("print(len(context))").stdout == "3\n"
    finally:
        r.close()


def test_close_kills_container_and_removes_scratch() -> None:
    r = DockerREPL(_cfg(), _handler)
    r.start("ctx")
    name, tmp = r.container, r._tmp
    assert name is not None and tmp is not None and os.path.isdir(tmp)
    r.close()
    assert not _container_running(name)
    assert not os.path.exists(tmp)
    assert r.container is None


def test_json_context_in_container() -> None:
    r = DockerREPL(_cfg(), _handler)
    r.start({"a": [1, 2]}, kind="json")
    try:
        assert r.execute("print(type(context).__name__, context['a'])").stdout == "dict [1, 2]\n"
    finally:
        r.close()


def test_unavailable_docker_binary_is_a_clear_error() -> None:
    r = DockerREPL(_cfg(), _handler, docker="definitely-not-docker-xyz")
    with pytest.raises(DockerUnavailable, match="not installed or not on PATH"):
        r.start("ctx")
