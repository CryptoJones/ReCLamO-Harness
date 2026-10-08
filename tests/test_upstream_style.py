"""planner_style = "upstream-rlm-v0" (#43): the scaffold RLM-Qwen3-8B was trained on."""

from __future__ import annotations

import dataclasses
import json
import os
from pathlib import Path
from typing import Any

import pytest

from reclamo.cli import main
from reclamo.config import BUILTIN_PROFILES_TOML, ConfigError, ModelConfig, RLMConfig, load_config
from reclamo.logger import TrajectoryLogger
from reclamo.repl.base import ExecResult
from reclamo.rlm import RLM
from reclamo.upstream import (
    FIRST_TURN_SAFEGUARD,
    LATER_TURN_PREFIX,
    UPSTREAM_SYSTEM_PROMPT,
    code_output_message,
    metadata_prompt,
    user_prompt,
)
from tests.conftest import FakeServer, chat_response
from tests.mocklm import SECRET_REASONING, MockLM

CONTEXT = "alpha\nbeta\nthe magic number is 42\ngamma\n"
QUERY = "What is the magic number?"
SNAPSHOT = Path(__file__).parent / "data" / "upstream_rlm_v0_turn3.json"
UPSTREAM = "upstream-rlm-v0"


def _cfg(**overrides: Any) -> RLMConfig:
    fields: dict[str, Any] = {
        "name": "test",
        "base_url": "http://unused/v1",
        "max_iterations": 5,
        "exec_timeout": 10.0,
        "max_timeout": 60.0,
        "output_truncate_chars": 20_000,
        "planner_style": UPSTREAM,
        "root": ModelConfig(model="rlm-qwen3-8b", enable_thinking=False),
        "sub": ModelConfig(model="reader"),
    }
    fields.update(overrides)
    return RLMConfig(**fields)


def _run(root: list[Any], *, cfg: RLMConfig | None = None, **kw: Any) -> tuple[Any, MockLM]:
    lm = MockLM(root, **kw)
    result = RLM(cfg or _cfg(), lm).completion(CONTEXT, QUERY)
    return result, lm


# A three-turn trajectory in the checkpoint's format: look, sub-call, FINAL_VAR.
SCRIPT = [
    "Let me look at the context first.\n```repl\nprint(type(context), len(context))\n"
    "print(context[:100])\n```",
    "I will ask a sub-LLM about the text.\n```repl\n"
    'answer = llm_query(f"What is the magic number in the context? Here is the chunk: '
    '{context}")\nprint(answer)\n```',
    "The sub-LLM found it.\nFINAL_VAR(answer)",
]


def _sub(_prompt: str) -> str:
    return "The magic number is 42."


# --- style selection ---------------------------------------------------------------


def test_default_style_is_ours_everywhere() -> None:
    plain = RLMConfig(base_url="x", root=ModelConfig(model="m"), sub=ModelConfig(model="m"))
    assert plain.planner_style == "reclamo"
    for name in ("pluto", "openai-compatible"):
        assert load_config(name, "/nonexistent", env={}).planner_style == "reclamo"
    assert "planner_style" not in BUILTIN_PROFILES_TOML


def test_default_style_prompt_unchanged() -> None:
    _, lm = _run(["FINAL(x)"], cfg=_cfg(planner_style="reclamo"))
    msgs = lm.root_calls[0]["messages"]
    assert [m["role"] for m in msgs] == ["system", "user"]
    assert msgs[1]["content"].startswith(f"{QUERY}\n\nTurn 1/5.")
    assert "~32k tokens" not in msgs[0]["content"]


def test_unknown_style_and_tools_protocol_rejected() -> None:
    with pytest.raises(ConfigError, match="planner_style must be one of"):
        _cfg(planner_style="upstream")
    with pytest.raises(ConfigError, match='needs protocol = "fence"'):
        _cfg(protocol="tools")


def test_style_from_profile_toml(tmp_path: Path) -> None:
    p = tmp_path / "profiles.toml"
    p.write_text(
        '[profiles.u]\nbase_url = "http://x/v1"\nplanner_style = "upstream-rlm-v0"\n'
        '[profiles.u.root]\nmodel = "a"\n[profiles.u.sub]\nmodel = "b"\n',
        encoding="utf-8",
    )
    assert load_config("u", p, env={}).planner_style == UPSTREAM


# --- end to end with a scripted MockLM ------------------------------------------------


def test_scripted_upstream_trajectory_end_to_end() -> None:
    result, lm = _run(SCRIPT, sub=_sub)
    assert (result.answer, result.stop_reason) == ("The magic number is 42.", "final_var")
    assert result.iterations == 3 and result.subcalls == 1

    first, second, third = (c["messages"] for c in lm.root_calls)
    assert first == [
        {"role": "system", "content": UPSTREAM_SYSTEM_PROMPT},
        {"role": "assistant", "content": metadata_prompt(CONTEXT)},
        {"role": "user", "content": user_prompt(QUERY, 0)},
    ]
    assert first[2]["content"].startswith(FIRST_TURN_SAFEGUARD)
    assert f'answer the original prompt: "{QUERY}"' in first[2]["content"]

    # The per-turn prompt is sent, not stored: turn 2 = stored history + a fresh one.
    assert second[:2] == first[:2]
    assert second[2] == {"role": "assistant", "content": SCRIPT[0]}
    out = second[3]["content"]
    assert out.startswith("Code executed:\n```python\nprint(type(context), len(context))")
    assert f"\n```\n\nREPL output:\n\n<class 'str'> {len(CONTEXT)}\n" in out
    assert out.endswith("REPL variables: ['context']\n")
    assert second[4] == {"role": "user", "content": user_prompt(QUERY, 1)}
    assert second[4]["content"].startswith(LATER_TURN_PREFIX)
    assert len(second) == 5

    assert third[:4] == second[:4]
    assert "The magic number is 42." in third[5]["content"]
    assert third[5]["content"].endswith("REPL variables: ['context', 'answer']\n")
    assert third[-1]["content"] == user_prompt(QUERY, 2)
    assert "Turn " not in json.dumps(third)
    assert SECRET_REASONING not in lm.all_message_text()

    (sub,) = lm.sub_calls
    prompt = "What is the magic number in the context? Here is the chunk: " + CONTEXT
    assert sub["messages"] == [{"role": "user", "content": prompt}]


def test_user_variables_listed_and_error_line_in_stderr_part() -> None:
    result, lm = _run(["```repl\nx = 1\nhits = [1, 2]\n1/0\n```", "FINAL(done)"])
    out = lm.root_calls[1]["messages"][3]["content"]
    assert "REPL output:\n\n\nZeroDivisionError: division by zero (line 3)\n\nREPL" in out
    assert out.endswith("REPL variables: ['context', 'hits', 'x']\n")
    assert result.answer == "done"


def test_one_user_message_per_block_and_truncation() -> None:
    _, lm = _run(
        ["```repl\nprint('a' * 300)\n```\n```repl\nprint('b')\n```", "FINAL(ok)"],
        cfg=_cfg(output_truncate_chars=100),
    )
    msgs = lm.root_calls[1]["messages"]
    assert [m["role"] for m in msgs] == ["system", "assistant", "assistant", "user", "user", "user"]
    first, second = msgs[3]["content"], msgs[4]["content"]
    assert "print('a' * 300)" in first and "... + [" in first and first.endswith(" chars...]")
    assert second.startswith("Code executed:\n```python\nprint('b')\n```")


def test_final_var_after_code_in_same_turn_is_accepted() -> None:
    result, _ = _run(["```repl\nfinal_answer = 'forty-two'\n```\nFINAL_VAR(final_answer)"])
    assert (result.answer, result.stop_reason, result.iterations) == ("forty-two", "final_var", 1)


def test_laguna_text_tool_call_runs_in_upstream_style() -> None:
    # Issue #48: the text-form <tool_call> flows through this style's output messages too.
    reply = "<tool_call>repl\nmagic = 42\nprint(magic)\n</repl>"
    result, lm = _run([reply, "FINAL_VAR(magic)"])
    assert (result.answer, result.stop_reason, result.iterations) == ("42", "final_var", 2)
    out = lm.root_calls[1]["messages"][3]["content"]
    assert out.startswith("Code executed:\n```python\nmagic = 42\nprint(magic)\n```")
    assert "REPL output:\n\n42\n" in out


def test_final_text_next_to_code_still_rejected_and_nudge_follows_outputs() -> None:
    result, lm = _run(["```repl\nprint(1)\n```\nFINAL(42)", "FINAL(42)"])
    assert (result.answer, result.iterations) == ("42", 2)
    msgs = lm.root_calls[1]["messages"]
    assert msgs[3]["content"].startswith("Code executed:")
    assert msgs[4]["role"] == "user"
    assert msgs[4]["content"].startswith("That FINAL was not accepted")
    assert msgs[5]["content"] == user_prompt(QUERY, 1)


def test_forced_finish_shows_the_query() -> None:
    result, lm = _run(
        ["```repl\nresult = 'r'\nprint(2)\n```", "```repl\nprint(3)\n```", "FINAL_VAR(result)"],
        cfg=_cfg(max_iterations=2),
    )
    assert (result.answer, result.stop_reason) == ("r", "max_iterations")
    last = lm.root_calls[-1]["messages"][-1]["content"]
    assert f'The original prompt: "{QUERY}".' in last and "You are out of turns" in last


def test_sft_log_records_the_messages_actually_sent(tmp_path: Path) -> None:
    logger = TrajectoryLogger(tmp_path, sft=True)
    lm = MockLM(["```repl\nprint(1)\n```", "FINAL(1)"])
    RLM(_cfg(sft_log=True), lm, logger=logger).completion(CONTEXT, QUERY)
    assert logger.sft_path is not None
    lines = [json.loads(x) for x in Path(logger.sft_path).read_text().splitlines()]
    assert [line["messages"] for line in lines] == [c["messages"] for c in lm.root_calls]


def test_code_output_message_shape() -> None:
    res = ExecResult(stdout="hi\n", stderr="warn\n", vars=["a"])
    assert code_output_message("  print('hi')\n", res) == (
        "Code executed:\n```python\nprint('hi')\n```\n\nREPL output:\n"
        "\nhi\n\n\n\nwarn\n\n\nREPL variables: ['context', 'a']\n"
    )


def test_metadata_matches_upstream_query_metadata() -> None:
    assert metadata_prompt("abc") == (
        "Your context is a str with 3 total characters, and is broken up into chunks of "
        "char lengths: [3]."
    )
    assert metadata_prompt({"a": "xy", "b": [1]}).startswith(
        "Your context is a dict with 5 total characters"
    )
    many = metadata_prompt(["x"] * 105)
    assert many.endswith("... [5 others].") and "list with 105 total" in many


# --- prompt render snapshot -------------------------------------------------------------


def test_render_snapshot() -> None:
    """The exact messages of turn 3. Regenerate with RECLAMO_UPDATE_SNAPSHOTS=1."""
    _, lm = _run(SCRIPT, sub=_sub)
    rendered = lm.root_calls[2]["messages"]
    if os.environ.get("RECLAMO_UPDATE_SNAPSHOTS"):
        SNAPSHOT.parent.mkdir(exist_ok=True)
        text = json.dumps(rendered, indent=1, ensure_ascii=False) + "\n"
        SNAPSHOT.write_text(text, encoding="utf-8")
    assert rendered == json.loads(SNAPSHOT.read_text(encoding="utf-8"))


def test_system_prompt_carries_the_qwen3_8b_edits() -> None:
    p = UPSTREAM_SYSTEM_PROMPT
    assert p.startswith("You are tasked with answering a query with associated context.")
    assert "\n\nIMPORTANT: You have a total context window of approximately ~32k tokens." in p
    assert "(that can handle around ~100k chars, roughly 32k tokens)" in p
    assert "llm_query_batched" not in p and "500K" not in p
    assert "chunk = context[:1000]\n" in p
    assert "{{chunk}}" in p  # upstream never formats the system prompt
    assert "\nFINAL_VAR(final_answer)\n" in p
    assert "NOT in code or repl tags." in p


# --- per-role endpoints: root on server A in upstream style, subs on server B ---------


def test_upstream_root_on_a_subs_on_b(
    fake_server: FakeServer,
    fake_server_b: FakeServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("ROOT_KEY", "sk-root")
    monkeypatch.setenv("SUB_KEY", "sk-sub")
    fake_server.script(
        chat_response('```repl\nanswer = llm_query("what is it?")\nprint(answer)\n```'),
        chat_response("FINAL_VAR(answer)"),
    )
    fake_server_b.script(chat_response("forty-two", model="sub-served"))
    profiles = tmp_path / "profiles.toml"
    profiles.write_text(
        f"""
[profiles.rlm8b]
base_url = "{fake_server_b.base_url}"
api_key_env = "SUB_KEY"
max_iterations = 4
planner_style = "upstream-rlm-v0"
output_truncate_chars = 20000
[profiles.rlm8b.root]
base_url = "{fake_server.base_url}"
api_key_env = "ROOT_KEY"
model = "rlm-qwen3-8b"
enable_thinking = false
sampling = {{ temperature = 0.7, top_p = 0.8, top_k = 20, min_p = 0.0 }}
[profiles.rlm8b.sub]
model = "qwen3.8-flash-next"
""",
        encoding="utf-8",
    )
    ctx = tmp_path / "ctx.txt"
    ctx.write_text(CONTEXT, encoding="utf-8")
    argv = ["run", "--profile", "rlm8b", "--profiles", str(profiles), "--context", str(ctx)]
    rc = main([*argv, "-q", QUERY, "--log-dir", str(tmp_path / "runs"), "--json"])
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert json.loads(captured.out)["answer"] == "forty-two"

    root_posts = [r.body for r in fake_server.requests if r.method == "POST"]
    sub_posts = [r.body for r in fake_server_b.requests if r.method == "POST"]
    assert len(root_posts) == 2 and len(sub_posts) == 1
    first, second = root_posts[0]["messages"], root_posts[1]["messages"]
    assert first[0] == {"role": "system", "content": UPSTREAM_SYSTEM_PROMPT}
    assert first[1]["role"] == "assistant" and first[2]["content"] == user_prompt(QUERY, 0)
    assert second[3]["content"].startswith("Code executed:\n```python\nanswer = llm_query(")
    assert "\nforty-two\n" in second[3]["content"]
    assert root_posts[0]["model"] == "rlm-qwen3-8b"
    assert (root_posts[0]["temperature"], root_posts[0]["top_p"]) == (0.7, 0.8)
    assert sub_posts[0]["model"] == "qwen3.8-flash-next"
    assert sub_posts[0]["messages"] == [{"role": "user", "content": "what is it?"}]


def test_cli_flag_selects_style_and_rejects_tools(
    fake_server: FakeServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("RECLAMO_API_KEY", "k")
    monkeypatch.setenv("RECLAMO_BASE_URL", fake_server.base_url)
    fake_server.script(chat_response("FINAL(ok)"))
    ctx = tmp_path / "c.txt"
    ctx.write_text("x", encoding="utf-8")
    base = ["run", "--profile", "openai-compatible", "--profiles", str(tmp_path / "none.toml")]
    base += ["--context", str(ctx), "-q", "q", "--log-dir", str(tmp_path / "runs"), "--json"]
    assert main([*base, "--planner-style", UPSTREAM]) == 0
    capsys.readouterr()
    body = next(r.body for r in fake_server.requests if r.method == "POST")
    assert body["messages"][0]["content"] == UPSTREAM_SYSTEM_PROMPT
    assert main([*base, "--planner-style", UPSTREAM, "--protocol", "tools"]) == 2
    assert 'needs protocol = "fence"' in capsys.readouterr().err


def test_child_rlm_inherits_style() -> None:
    cfg = dataclasses.replace(_cfg(), max_depth=2)
    lm = MockLM(
        [
            "```repl\nr = rlm_query('count lines', context)\nprint(r)\n```",
            "FINAL(4)",  # the child
            "FINAL_VAR(r)",
        ]
    )
    result = RLM(cfg, lm).completion(CONTEXT, QUERY)
    assert result.answer == "4"
    child = lm.root_calls[1]["messages"]
    assert child[0]["content"] == UPSTREAM_SYSTEM_PROMPT
    assert child[2]["content"] == user_prompt("count lines", 0)


def test_error_limit_forced_finish_in_upstream_style() -> None:
    """Issue #50 in the upstream layout: outputs stored per block, then the forced finish."""
    root = [
        "```repl\nparts = ['42']\n```",
        "```repl\n1 / 0\n```\n```repl\nprint('ok')\n```",
        "```repl\nundefined_name\n```",
        "FINAL_VAR(parts)",
    ]
    result, lm = _run(root, cfg=_cfg(max_errors=2))
    assert (result.answer, result.stop_reason) == ("['42']", "error_limit")
    msgs = lm.root_calls[-1]["messages"]
    assert msgs[-1]["content"].startswith("Code executed:") and "NameError" in msgs[-1]["content"]
    assert f'The original prompt: "{QUERY}".' in msgs[-1]["content"]
    assert "failed too many times in a row" in msgs[-1]["content"]
