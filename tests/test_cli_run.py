from __future__ import annotations

import json
from pathlib import Path

import pytest

from reclamo.cli import load_context, main
from reclamo.config import ConfigError
from tests.conftest import FakeServer, chat_response


def _profiles_file(tmp_path: Path, base_url: str) -> Path:
    p = tmp_path / "profiles.toml"
    p.write_text(
        f"""
[profiles.fake]
base_url = "{base_url}"
max_iterations = 4
[profiles.fake.root]
model = "fake-model"
enable_thinking = true
[profiles.fake.sub]
model = "fake-model"
""",
        encoding="utf-8",
    )
    return p


def test_run_end_to_end_json(
    fake_server: FakeServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("RECLAMO_API_KEY", "sk-test-SECRET")
    fake_server.script(
        chat_response("<think>look first</think>\n```repl\nprint(len(context))\n```"),
        chat_response("FINAL(The context is 12 chars.)"),
    )
    profiles = _profiles_file(tmp_path, fake_server.base_url)
    ctx = tmp_path / "ctx.txt"
    ctx.write_text("hello world\n", encoding="utf-8")
    log_dir = tmp_path / "runs"

    rc = main(
        [
            "run",
            "--profile",
            "fake",
            "--profiles",
            str(profiles),
            "--context",
            str(ctx),
            "-q",
            "How long is it?",
            "--log-dir",
            str(log_dir),
            "--json",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    result = json.loads(out)
    assert result["answer"] == "The context is 12 chars."
    assert result["stop_reason"] == "final" and result["iterations"] == 2

    posts = [r for r in fake_server.requests if r.method == "POST"]
    assert len(posts) == 2
    assert posts[0].body["chat_template_kwargs"]["enable_thinking"] is True
    second_msgs = posts[1].body["messages"]
    assert second_msgs[-1]["role"] == "user" and "[output]\n12" in second_msgs[-1]["content"]
    assert "look first" not in json.dumps(second_msgs)  # reasoning stripped from history

    logs = list(log_dir.glob("*.jsonl"))
    assert len(logs) == 1
    text = logs[0].read_text(encoding="utf-8")
    assert "sk-test-SECRET" not in text
    assert result["trajectory_path"] == str(logs[0])


def test_run_no_thinking_and_plain_output(
    fake_server: FakeServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("RECLAMO_API_KEY", "sk-test")
    fake_server.script(chat_response("FINAL(plain)"))
    profiles = _profiles_file(tmp_path, fake_server.base_url)
    ctx = tmp_path / "ctx.txt"
    ctx.write_text("x", encoding="utf-8")
    rc = main(
        [
            "run",
            "--profile",
            "fake",
            "--profiles",
            str(profiles),
            "--context",
            str(ctx),
            "-q",
            "?",
            "--log-dir",
            str(tmp_path / "runs"),
            "--no-thinking",
            "--max-iterations",
            "2",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 0 and captured.out == "plain\n"
    assert "[final; 1 turns" in captured.err
    post = [r for r in fake_server.requests if r.method == "POST"][0]
    assert post.body["chat_template_kwargs"]["enable_thinking"] is False


def test_run_limit_exit_code_with_partial(
    fake_server: FakeServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("RECLAMO_API_KEY", "sk-test")
    fake_server.script(
        chat_response("```repl\nx = 1/0\n```"),
        chat_response("```repl\nanswer['content'] = 'half'\ny = undefined\n```"),
        chat_response("```repl\nz = 1/0\n```"),
        chat_response("I could not finish."),  # forced finish (issue #50): no FINAL
    )
    profiles = _profiles_file(tmp_path, fake_server.base_url)
    ctx = tmp_path / "ctx.txt"
    ctx.write_text("x", encoding="utf-8")
    rc = main(
        [
            "run",
            "--profile",
            "fake",
            "--profiles",
            str(profiles),
            "--context",
            str(ctx),
            "-q",
            "?",
            "--log-dir",
            str(tmp_path / "runs"),
        ]
    )
    captured = capsys.readouterr()
    assert rc == 3
    assert "stopped by error_limit" in captured.err
    assert captured.out == "half\n"  # the answer dict wins over unusable reply prose


def test_run_missing_context_is_config_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("RECLAMO_API_KEY", "sk-test")
    profiles = _profiles_file(tmp_path, "http://127.0.0.1:9/v1")
    rc = main(
        ["run", "--profile", "fake", "--profiles", str(profiles), "--context", "/nope", "-q", "?"]
    )
    assert rc == 2
    assert "context not found" in capsys.readouterr().err


def test_load_context_dir_and_stdin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "a.txt").write_text("alpha", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.md").write_text("beta", encoding="utf-8")
    (tmp_path / ".hidden").write_text("no", encoding="utf-8")
    (tmp_path / "bin.dat").write_bytes(b"\xff\xfe\x00binary")
    assert load_context(str(tmp_path)) == {"a.txt": "alpha", "sub/b.md": "beta"}

    import io

    monkeypatch.setattr("sys.stdin", io.StringIO("from stdin"))
    assert load_context("-") == "from stdin"

    (tmp_path / "empty").mkdir()
    with pytest.raises(ConfigError, match="no readable text files"):
        load_context(str(tmp_path / "empty"))


def test_run_reports_non_final_stop_reason(
    fake_server: FakeServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("RECLAMO_API_KEY", "sk-test")
    fake_server.script(chat_response("```repl\nfinal_answer = 'forced'\n```"))
    profiles = _profiles_file(tmp_path, fake_server.base_url)
    ctx = tmp_path / "ctx.txt"
    ctx.write_text("x", encoding="utf-8")
    rc = main(
        [
            "run",
            "--profile",
            "fake",
            "--profiles",
            str(profiles),
            "--context",
            str(ctx),
            "-q",
            "?",
            "--log-dir",
            str(tmp_path / "runs"),
            "--max-iterations",
            "1",
            "--sandbox",
            "subprocess",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 0 and captured.out == "forced\n"
    assert "stopped by max_iterations; the answer may be incomplete" in captured.err


def _tool_reply(name: str, arguments: str, call_id: str) -> dict:
    body = chat_response(None, finish_reason="tool_calls")
    body["choices"][0]["message"]["tool_calls"] = [
        {"id": call_id, "type": "function", "function": {"name": name, "arguments": arguments}}
    ]
    return body


def test_run_protocol_tools_sends_tools_and_finishes_on_final_answer(
    fake_server: FakeServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("RECLAMO_API_KEY", "sk-test-SECRET")
    fake_server.script(
        _tool_reply("execute_python", json.dumps({"code": "n = len(context)\nprint(n)"}), "c1"),
        _tool_reply("final_answer", '{"variable": "n"}', "c2"),
    )
    profiles = _profiles_file(tmp_path, fake_server.base_url)
    ctx = tmp_path / "ctx.txt"
    ctx.write_text("hello world\n", encoding="utf-8")
    rc = main(
        ["run", "--profile", "fake", "--profiles", str(profiles), "--context", str(ctx),
         "-q", "How long?", "--log-dir", str(tmp_path / "runs"), "--json",
         "--protocol", "tools"]
    )  # fmt: skip
    result = json.loads(capsys.readouterr().out)
    assert rc == 0 and result["answer"] == "12" and result["stop_reason"] == "final_var"
    assert result["protocol"] == "tools"
    posts = [r for r in fake_server.requests if r.method == "POST"]
    assert posts[0].body["tool_choice"] == "auto"
    assert posts[0].body["tools"][0]["function"]["name"] == "execute_python"
    msgs = posts[1].body["messages"]
    assert msgs[2]["tool_calls"][0]["id"] == "c1"
    assert msgs[3] == {"role": "tool", "tool_call_id": "c1", "content": "12"}


def test_run_prompt_version_and_sub_thinking_flags(
    fake_server: FakeServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("RECLAMO_API_KEY", "sk-test")
    fake_server.script(
        chat_response("```repl\nprint(llm_query('hi'))\n```"),
        chat_response("sub answer"),
        chat_response("FINAL(ok)"),
    )
    profiles = _profiles_file(tmp_path, fake_server.base_url)
    ctx = tmp_path / "ctx.txt"
    ctx.write_text("x", encoding="utf-8")
    argv = ["run", "--profile", "fake", "--profiles", str(profiles), "--context", str(ctx)]
    argv += ["-q", "?", "--log-dir", str(tmp_path / "runs"), "--prompt-version", "v0.1"]
    rc = main([*argv, "--sub-thinking", "--max-iterations", "3"])
    assert rc == 0 and capsys.readouterr().out == "ok\n"
    posts = [r for r in fake_server.requests if r.method == "POST"]
    system = posts[0].body["messages"][0]["content"]
    assert "sub-calls are expensive" in system  # the v0.1 prompt
    assert posts[0].body["max_tokens"] == 4_096  # v0.1 root default
    assert posts[1].body["chat_template_kwargs"]["enable_thinking"] is True  # the sub-call
    assert posts[1].body["max_tokens"] == 2_048  # v0.1 sub default
