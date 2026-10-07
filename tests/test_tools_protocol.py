"""The ``protocol="tools"`` loop (issue #20): execute_python / final_answer tool calls."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from reclamo.client import LMClient
from reclamo.config import ConfigError, ModelConfig, RLMConfig
from reclamo.errors import RLMErrorLimit
from reclamo.logger import TrajectoryLogger
from reclamo.prompts import build_tools_system_prompt, forced_final_prompt, tool_specs
from reclamo.rlm import RLM
from tests.conftest import chat_response
from tests.mocklm import SECRET_REASONING, MockLM, call, completion, tool_turn

CONTEXT = "line one\nline two\nline three\n"


def _cfg(**overrides: Any) -> RLMConfig:
    fields: dict[str, Any] = {
        "name": "test",
        "base_url": "http://unused/v1",
        "max_iterations": 5,
        "max_depth": 1,
        "exec_timeout": 10.0,
        "max_timeout": 60.0,
        "output_truncate_chars": 500,
        "max_subcalls_per_exec": 10,
        "max_subcalls_per_run": 20,
        "protocol": "tools",
        "root": ModelConfig(model="m", enable_thinking=True),
        "sub": ModelConfig(model="m"),
    }
    fields.update(overrides)
    return RLMConfig(**fields)


def _run(root: list[Any], *, cfg: RLMConfig | None = None, logger: Any = None, **kw: Any):
    lm = MockLM(root, **kw)
    result = RLM(cfg or _cfg(), lm, logger=logger).completion(CONTEXT, "How many lines?")
    return result, lm


def py(code: str):
    return call("execute_python", code=code)


def assert_valid_history(messages: list[dict[str, Any]]) -> None:
    """Every assistant tool_calls message is followed by exactly its tool replies, in order."""
    i = 0
    while i < len(messages):
        m = messages[i]
        assert m["role"] in ("system", "user", "assistant", "tool")
        if m["role"] == "assistant" and m.get("tool_calls"):
            ids = [tc["id"] for tc in m["tool_calls"]]
            for tc in m["tool_calls"]:
                assert tc["type"] == "function"
                assert set(tc["function"]) == {"name", "arguments"}
            replies = messages[i + 1 : i + 1 + len(ids)]
            assert [r["role"] for r in replies] == ["tool"] * len(ids)
            assert [r["tool_call_id"] for r in replies] == ids
            assert all(isinstance(r["content"], str) for r in replies)
            i += 1 + len(ids)
            continue
        assert m["role"] != "tool", f"orphan tool message at {i}"
        i += 1


# --- happy paths --------------------------------------------------------------


def test_execute_python_then_final_answer() -> None:
    result, lm = _run(
        [
            tool_turn(py("n = len(context.splitlines())\nprint(n)")),
            tool_turn(call("final_answer", answer="There are 3 lines.")),
        ]
    )
    assert (result.answer, result.stop_reason, result.iterations) == (
        "There are 3 lines.",
        "final",
        2,
    )
    assert result.protocol == "tools"
    assert result.stats["executions"] == 1 and result.stats["slips"] == {}

    first, second = lm.root_calls
    assert first["tools"] == tool_specs(500)
    assert first["messages"][0]["content"] == second["messages"][0]["content"]
    assert "execute_python" in first["messages"][0]["content"]
    assert "```repl" not in first["messages"][0]["content"]
    assert first["messages"][1]["content"].startswith("How many lines?\n\nTurn 1/5.")
    assert "one execute_python call" in first["messages"][1]["content"]

    msgs = second["messages"]
    assert msgs[2]["role"] == "assistant" and msgs[2]["tool_calls"][0]["function"]["name"] == (
        "execute_python"
    )
    assert msgs[3]["role"] == "tool" and msgs[3]["content"] == "3"
    assert msgs[4] == {"role": "user", "content": "Turn 2/5."}
    assert_valid_history(msgs)
    assert SECRET_REASONING not in lm.all_message_text()


def test_final_answer_variable() -> None:
    result, _ = _run(
        [
            tool_turn(py("result = 'needle at 7'")),
            tool_turn(call("final_answer", variable="result")),
        ]
    )
    assert (result.answer, result.stop_reason) == ("needle at 7", "final_var")


def test_final_answer_with_a_non_string_answer_is_json() -> None:
    result, _ = _run([tool_turn(call("final_answer", answer={"billing": 3}))])
    assert result.answer == '{"billing": 3}'


def test_answer_dict_ready_via_execute_python() -> None:
    result, lm = _run([tool_turn(py("answer['content'] = 'x'\nanswer['ready'] = True"))])
    assert (result.answer, result.stop_reason, result.iterations) == ("x", "answer_dict", 1)


# --- rejected finals ----------------------------------------------------------


def test_missing_variable_rejected_in_its_tool_message() -> None:
    result, lm = _run(
        [
            tool_turn(call("final_answer", variable="nothing")),
            tool_turn(call("final_answer", answer="ok")),
        ]
    )
    assert result.answer == "ok"
    msgs = lm.root_calls[1]["messages"]
    assert msgs[-2]["role"] == "tool"
    assert "final_answer was not accepted" in msgs[-2]["content"]
    assert "no variable named `nothing`" in msgs[-2]["content"]
    assert result.stats["final_rejections"] == 1
    assert_valid_history(msgs)


@pytest.mark.parametrize(
    "args",
    [{}, {"answer": "a", "variable": "b"}, {"answer": "", "variable": ""}, {"variable": 3}],
)
def test_final_answer_needs_exactly_one_argument(args: dict[str, Any]) -> None:
    result, lm = _run(
        [tool_turn(call("final_answer", **args)), tool_turn(call("final_answer", answer="ok"))]
    )
    assert result.answer == "ok" and result.iterations == 2
    reply = lm.root_calls[1]["messages"][-2]
    assert reply["role"] == "tool" and reply["content"].startswith("Error: ")
    assert result.stats["slips"] == {"malformed_args": 1}


def test_final_next_to_code_runs_the_code_then_rejects_the_final() -> None:
    first = tool_turn(call("final_answer", answer="3"), py("v = 3\nprint('ran')"))
    result, lm = _run([first, tool_turn(call("final_answer", variable="v"))])
    assert (result.answer, result.iterations) == ("3", 2)
    msgs = lm.root_calls[1]["messages"]
    final_reply, code_reply = msgs[3], msgs[4]
    assert "code that had not run yet" in final_reply["content"]
    assert code_reply["content"] == "ran"
    assert_valid_history(msgs)


def test_plan_like_final_rejected_once_then_accepted_on_repeat() -> None:
    plan = call("final_answer", answer="I will count the lines first.")
    again = call("final_answer", answer="I will count the lines first.")
    result, lm = _run([tool_turn(plan), tool_turn(again)])
    assert result.answer == "I will count the lines first." and result.iterations == 2
    assert "reads like a plan" in lm.root_calls[1]["messages"][-2]["content"]


# --- slips and nudges ---------------------------------------------------------


def test_plain_text_reply_gets_a_nudge() -> None:
    result, lm = _run(["There are three lines.", tool_turn(call("final_answer", answer="3"))])
    assert result.answer == "3"
    last = lm.root_calls[1]["messages"][-1]
    assert last["role"] == "user"
    assert "called no tool" in last["content"] and last["content"].endswith("Turn 2/5.")
    assert result.stats["slips"] == {"text_no_tool": 1}


def test_fenced_code_runs_once_as_a_courtesy_and_counts_as_a_slip(tmp_path: Path) -> None:
    logger = TrajectoryLogger(tmp_path)
    result, lm = _run(
        ["```python\nprint(len(context))\n```", tool_turn(call("final_answer", answer="29"))],
        logger=logger,
    )
    assert result.answer == "29"
    last = lm.root_calls[1]["messages"][-1]["content"]
    assert last.startswith("[output]\n29")
    assert "instead of an execute_python call" in last
    assert result.stats["slips"] == {"fenced_code": 1} and result.stats["executions"] == 1
    events = [json.loads(line) for line in Path(logger.path).read_text().splitlines()]
    assert events[-1]["type"] == "final" and events[-1]["protocol_slips"] == 1


def test_final_written_as_text_is_honoured_and_counted() -> None:
    result, _ = _run(["FINAL(3 lines)"])
    assert (result.answer, result.stop_reason) == ("3 lines", "final")
    assert result.stats["slips"] == {"final_in_text": 1}


def test_malformed_json_arguments_get_a_tool_error() -> None:
    bad = call("execute_python", '{"code": "print(1)"')
    result, lm = _run([tool_turn(bad), tool_turn(call("final_answer", answer="ok"))])
    assert result.answer == "ok"
    reply = lm.root_calls[1]["messages"][-2]
    assert reply["role"] == "tool" and "not valid JSON" in reply["content"]
    assert result.stats == {
        "executions": 0,
        "syntax_errors": 0,
        "exec_errors": 0,
        "final_rejections": 0,
        "slips": {"malformed_args": 1},
    }


def test_missing_code_and_unknown_tool_are_slips() -> None:
    first = tool_turn(call("execute_python", note="x"), call("run_shell", cmd="ls"))
    result, lm = _run([first, tool_turn(call("final_answer", answer="ok"))])
    assert result.answer == "ok"
    msgs = lm.root_calls[1]["messages"]
    assert "non-empty string argument `code`" in msgs[3]["content"]
    assert "no tool named `run_shell`" in msgs[4]["content"]
    assert result.stats["slips"] == {"malformed_args": 1, "unknown_tool": 1}
    assert_valid_history(msgs)


def test_multiple_calls_in_one_turn_run_in_order_and_share_state() -> None:
    first = tool_turn(py("a = 2\nprint('first')"), py("print('second', a * 3)"))
    result, lm = _run([first, tool_turn(call("final_answer", answer="6"))])
    msgs = lm.root_calls[1]["messages"]
    assert [m["content"] for m in msgs[3:5]] == ["first", "second 6"]
    assert result.stats["executions"] == 2
    assert_valid_history(msgs)


def test_syntax_errors_are_counted() -> None:
    result, _ = _run([tool_turn(py("print(")), tool_turn(call("final_answer", answer="x"))])
    assert result.stats["syntax_errors"] == 1 and result.stats["exec_errors"] == 0


def test_reverify_nudge_names_final_answer() -> None:
    code = "count = 3\nprint(count)"
    result, lm = _run(
        [
            tool_turn(py(code)),
            tool_turn(py(code)),
            tool_turn(call("final_answer", variable="count")),
        ]
    )
    assert result.answer == "3"
    note = lm.root_calls[2]["messages"][-1]["content"]
    assert 'final_answer(variable="count")' in note


# --- guards that still apply --------------------------------------------------


def test_per_run_subcall_cap_still_enforced() -> None:
    cfg = _cfg(max_subcalls_per_run=2)
    result, lm = _run(
        [
            tool_turn(py("outs = [llm_query(str(i)) for i in range(5)]")),
            tool_turn(call("final_answer", answer="x")),
        ],
        cfg=cfg,
    )
    assert result.answer == "x" and len(lm.sub_calls) == 2
    assert (
        "sub-call budget for this run exhausted (2)" in lm.root_calls[1]["messages"][-2]["content"]
    )


def test_error_limit_still_enforced() -> None:
    cfg = _cfg(max_errors=2)
    lm = MockLM([tool_turn(py("1 / 0")), tool_turn(py("undefined_name")), "unused"])
    with pytest.raises(RLMErrorLimit):
        RLM(cfg, lm).completion(CONTEXT, "?")


def test_forced_finish_uses_existing_value_first() -> None:
    result, lm = _run([tool_turn(py("final_answer = 'picked'"))], cfg=_cfg(max_iterations=1))
    assert (result.answer, result.stop_reason) == ("picked", "max_iterations")
    assert len(lm.root_calls) == 1


def test_forced_finish_asks_for_final_answer_tool() -> None:
    result, lm = _run(
        [tool_turn(py("x = 41 + 1")), tool_turn(call("final_answer", variable="x"))],
        cfg=_cfg(max_iterations=1),
    )
    assert (result.answer, result.stop_reason) == ("42", "max_iterations")
    forced = lm.root_calls[1]
    assert forced["tools"] is not None
    assert forced["messages"][-1] == {
        "role": "user",
        "content": forced_final_prompt("turns", "tools"),
    }
    assert_valid_history(forced["messages"])


def test_length_finish_without_tool_calls_retries_without_thinking() -> None:
    lm = MockLM(
        [completion("", finish_reason="length"), tool_turn(call("final_answer", answer="ok"))]
    )
    result = RLM(_cfg(), lm).completion(CONTEXT, "?")
    assert result.answer == "ok" and result.iterations == 1
    assert [c["enable_thinking"] for c in lm.root_calls] == [None, False]
    assert all(c["tools"] for c in lm.root_calls)


def test_compaction_keeps_tool_messages_valid() -> None:
    cfg = _cfg(context_tokens=1_600, max_iterations=8)
    root = [tool_turn(py(f"print('{c}' * 400)")) for c in "xyzwvu"]
    root.append(tool_turn(call("final_answer", answer="done")))
    result, lm = _run(root, cfg=cfg)
    assert result.answer == "done"
    msgs = lm.root_calls[-1]["messages"]
    stubs = [m for m in msgs if "elided" in m["content"]]
    assert stubs and all(m["role"] == "tool" and m["tool_call_id"] for m in stubs)
    assert_valid_history(msgs)


def test_trajectory_records_protocol_tool_calls_and_slips(tmp_path: Path) -> None:
    logger = TrajectoryLogger(tmp_path, sft=True)
    result, _ = _run(
        ["no tool here", tool_turn(py("print(1)")), tool_turn(call("final_answer", answer="1"))],
        cfg=_cfg(sft_log=True),
        logger=logger,
    )
    events = [json.loads(line) for line in Path(logger.path).read_text().splitlines()]
    assert events[0]["config"]["protocol"] == "tools"
    its = [e for e in events if e["type"] == "iteration"]
    assert its[0]["slips"] == ["text_no_tool"] and its[0]["tool_calls"] == []
    assert its[1]["tool_calls"][0]["name"] == "execute_python"
    assert its[1]["tool_outputs"] == ["1"]
    assert its[2]["final"]["via"] == "tool"
    final = events[-1]
    assert final["protocol"] == "tools" and final["protocol_slips"] == 1
    assert final["stats"]["slips"] == {"text_no_tool": 1}
    sft = [json.loads(line) for line in Path(logger.sft_path).read_text().splitlines()]
    assert sft[1]["tool_calls"][0]["function"]["name"] == "execute_python"
    assert SECRET_REASONING not in Path(logger.sft_path).read_text()


def test_fence_protocol_never_sends_tools() -> None:
    lm = MockLM(["FINAL(ok)"])
    RLM(_cfg(protocol="fence"), lm).completion(CONTEXT, "?")
    assert lm.root_calls[0]["tools"] is None


def test_unknown_protocol_rejected() -> None:
    with pytest.raises(ConfigError, match="protocol"):
        _cfg(protocol="xml")


def test_tools_prompt_keeps_batching_guidance_without_fences() -> None:
    from reclamo.prompts import ContextMeta, PromptSettings

    prompt = build_tools_system_prompt(PromptSettings(), ContextMeta("str", 10))
    assert "sub-calls are expensive" in prompt and "llm_query_batched" in prompt
    assert "```" not in prompt and "FINAL" not in prompt
    assert "execute_python with code:" in prompt


# --- client wire format -------------------------------------------------------


def test_client_sends_tools_and_parses_tool_calls(fake_server) -> None:
    body = chat_response(None, reasoning_content="thinking", finish_reason="tool_calls")
    body["choices"][0]["message"]["tool_calls"] = [
        {
            "id": "call_abc",
            "type": "function",
            "function": {"name": "execute_python", "arguments": '{"code": "print(1)"}'},
        }
    ]
    fake_server.chat_script.append(body)
    cfg = RLMConfig(
        base_url=fake_server.base_url, root=ModelConfig(model="m"), sub=ModelConfig(model="m")
    )
    out = LMClient(cfg, "k").complete([{"role": "user", "content": "hi"}], tools=tool_specs())
    sent = fake_server.requests[-1].body
    assert sent["tools"][0]["function"]["name"] == "execute_python"
    assert sent["tool_choice"] == "auto"
    assert out.tool_calls and out.tool_calls[0].name == "execute_python"
    assert out.tool_calls[0].arguments == '{"code": "print(1)"}'
    assert out.content == "" and out.reasoning == "thinking"  # no fallback to reasoning
