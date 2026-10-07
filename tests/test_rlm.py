from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from reclamo.config import ModelConfig, RLMConfig
from reclamo.errors import RLMErrorLimit, RLMTimeout, RLMTokenLimit
from reclamo.logger import TrajectoryLogger
from reclamo.prompts import forced_final_prompt
from reclamo.rlm import RLM, describe_context
from tests.mocklm import SECRET_REASONING, MockLM, completion

CONTEXT = "line one\nline two\nline three\n"  # 29 chars


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
        "root": ModelConfig(model="m", enable_thinking=True),
        "sub": ModelConfig(model="m"),
    }
    fields.update(overrides)
    return RLMConfig(**fields)


def _run(root: list[Any], *, cfg: RLMConfig | None = None, context: Any = CONTEXT, **kw: Any):
    lm = MockLM(root, **kw)
    result = RLM(cfg or _cfg(), lm).completion(context, "How many lines?")
    return result, lm


# --- termination paths --------------------------------------------------------


def test_happy_path_python_fence_then_final() -> None:
    result, lm = _run(
        ["```python\nn = len(context.splitlines())\nprint(n)\n```", "FINAL(There are 3 lines.)"]
    )
    assert result.answer == "There are 3 lines."
    assert result.stop_reason == "final"
    assert result.iterations == 2 and result.subcalls == 0
    assert result.usage.total_tokens == 30

    second = lm.root_calls[1]["messages"]
    assert second[0]["role"] == "system"
    assert second[1]["content"].startswith("How many lines?\n\nTurn 1/5.")
    assert second[2] == {"role": "assistant", "content": lm.root_calls[1]["messages"][2]["content"]}
    assert second[3]["role"] == "user"
    assert second[3]["content"].startswith("[output]\n3\n")
    assert second[3]["content"].endswith("Turn 2/5.")
    assert SECRET_REASONING not in lm.all_message_text()


def test_final_var() -> None:
    result, _ = _run(["```repl\nresult = 'needle at 7'\n```", "FINAL_VAR(result)"])
    assert (result.answer, result.stop_reason) == ("needle at 7", "final_var")


def test_answer_dict_ready() -> None:
    result, lm = _run(["```repl\nanswer['content'] = 'x'\nanswer['ready'] = True\n```"])
    assert (result.answer, result.stop_reason, result.iterations) == ("x", "answer_dict", 1)
    assert len(lm.root_calls) == 1


def test_final_bare_identifier_resolves_to_variable() -> None:
    result, _ = _run(["```repl\nbest = 42\n```", "FINAL(best)"])
    assert result.answer == "42" and result.stop_reason == "final_var"


def test_final_quoted_literal_is_unquoted() -> None:
    result, _ = _run(['FINAL("Paris")'])
    assert result.answer == "Paris" and result.stop_reason == "final"


def test_final_next_to_code_rejected_then_accepted() -> None:
    result, lm = _run(["```repl\nv = 1\n```\nFINAL(1)", "FINAL(1)"])
    assert result.answer == "1" and result.iterations == 2
    followup = lm.root_calls[1]["messages"][-1]["content"]
    assert "That FINAL was not accepted" in followup
    assert "code that had not run yet" in followup


def test_plan_like_final_rejected_then_accepted_on_repeat() -> None:
    plan = "FINAL(I will count the lines first.)"
    result, lm = _run([plan, plan])
    assert result.answer == "I will count the lines first."
    assert result.iterations == 2
    assert "reads like a plan" in lm.root_calls[1]["messages"][-1]["content"]


def test_missing_final_var_rejected() -> None:
    result, lm = _run(["FINAL_VAR(nothing)", "FINAL(ok)"])
    assert result.answer == "ok"
    assert "no variable named `nothing`" in lm.root_calls[1]["messages"][-1]["content"]


def test_mid_sentence_final_mention_ignored() -> None:
    result, _ = _run(["I'll call FINAL(answer) later.\n```repl\nprint(1)\n```", "FINAL(done)"])
    assert result.answer == "done" and result.iterations == 2


def test_no_code_no_final_gets_a_prompt() -> None:
    result, lm = _run(["Let me think about this.", "FINAL(now)"])
    assert result.answer == "now"
    assert "no code and no final answer" in lm.root_calls[1]["messages"][-1]["content"]


# --- sub-calls and recursion --------------------------------------------------


def test_llm_query_and_batched_are_logged_and_counted(tmp_path: Path) -> None:
    logger = TrajectoryLogger(tmp_path)
    lm = MockLM(
        [
            "```repl\na = llm_query('q1')\nb = llm_query_batched(['q2', 'q3'])\nprint(a, b)\n```",
            "FINAL(ok)",
        ]
    )
    result = RLM(_cfg(), lm, logger=logger).completion(CONTEXT, "?")
    assert result.subcalls == 3 and len(lm.sub_calls) == 3
    assert lm.sub_calls[0]["messages"] == [{"role": "user", "content": "q1"}]
    events = [json.loads(line) for line in Path(logger.path).read_text().splitlines()]
    subcalls = [e for e in events if e["type"] == "subcall"]
    assert [e["kind"] for e in subcalls] == ["llm_query", "llm_query_batched", "llm_query_batched"]


def test_per_run_subcall_cap_surfaces_in_next_message() -> None:
    cfg = _cfg(max_subcalls_per_run=2)
    result, lm = _run(
        ["```repl\nouts = [llm_query(str(i)) for i in range(5)]\n```", "FINAL(x)"], cfg=cfg
    )
    assert result.answer == "x"
    assert len(lm.sub_calls) == 2
    followup = lm.root_calls[1]["messages"][-1]["content"]
    assert (
        "RuntimeError: sub-call budget for this run exhausted (2); finish with what you have"
        in (followup)
    )


def test_rlm_query_spawns_child_at_depth_two() -> None:
    cfg = _cfg(max_depth=2)
    root = [
        "```repl\nr = rlm_query('what is 2+2? answer briefly')\nprint(r)\n```",
        "FINAL(4)",  # consumed by the child RLM
        "FINAL_VAR(r)",
    ]
    result, lm = _run(root, cfg=cfg)
    assert result.answer == "4"
    assert len(lm.root_calls) == 3 and len(lm.sub_calls) == 0
    child_system = lm.root_calls[1]["messages"][0]["content"]
    assert "`context` is a str of 27 characters" in child_system
    child_query = lm.root_calls[1]["messages"][1]["content"]
    assert child_query.startswith("The context holds a task handed down by a parent process")
    assert result.subcalls == 1  # the rlm_query counted against the shared budget
    assert result.child_turns == 1 and result.iterations == 2  # child turns are kept apart


def test_rlm_query_falls_back_to_llm_query_at_max_depth() -> None:
    result, lm = _run(["```repl\nr = rlm_query('deep question')\n```", "FINAL_VAR(r)"])
    assert result.answer.startswith("sub:deep question")
    assert len(lm.root_calls) == 2 and len(lm.sub_calls) == 1
    assert result.child_turns == 0


def test_child_subcalls_count_against_parent_budget() -> None:
    cfg = _cfg(max_depth=2, max_subcalls_per_run=2)
    root = [
        "```repl\nr = rlm_query('task')\nprint(r)\n```",
        # child: one llm_query (budget: rlm_query=1, this=2), then a second one fails
        "```repl\nx = llm_query('a')\ny = llm_query('b')\n```",
        "FINAL(child done)",
        "FINAL_VAR(r)",
    ]
    result, lm = _run(root, cfg=cfg)
    assert result.answer == "child done"
    assert len(lm.sub_calls) == 1
    assert (
        "sub-call budget for this run exhausted (2)" in lm.root_calls[2]["messages"][-1]["content"]
    )


# --- nudges -------------------------------------------------------------------


def test_reverify_nudge_on_repeated_code() -> None:
    code = "```repl\ncount = 3\nprint(count)\n```"
    result, lm = _run([code, code, "FINAL_VAR(count)"])
    assert result.answer == "3"
    third = lm.root_calls[2]["messages"][-1]["content"]
    assert "the last two turns repeated the same check" in third
    assert "FINAL_VAR(count)" in third


def test_decompose_nudge_when_whole_context_sent_to_one_call() -> None:
    cfg = _cfg(subcall_chars=100)
    big = "x" * 1000
    result, lm = _run(["```repl\nr = llm_query(context)\n```", "FINAL(ok)"], cfg=cfg, context=big)
    assert result.answer == "ok"
    assert (
        "handed nearly the whole context to a single sub-call"
        in (lm.root_calls[1]["messages"][-1]["content"])
    )


# --- limits -------------------------------------------------------------------


def test_max_iterations_prefers_existing_variable_without_calling_model() -> None:
    cfg = _cfg(max_iterations=1)
    result, lm = _run(["```repl\nfinal_answer = 'picked'\n```"], cfg=cfg)
    assert (result.answer, result.stop_reason) == ("picked", "max_iterations")
    assert len(lm.root_calls) == 1


def test_max_iterations_prefers_unready_answer_dict() -> None:
    cfg = _cfg(max_iterations=1)
    result, lm = _run(["```repl\nanswer['content'] = 'partial'\n```"], cfg=cfg)
    assert result.answer == "partial" and len(lm.root_calls) == 1


def test_max_iterations_forced_model_call_when_nothing_exists() -> None:
    cfg = _cfg(max_iterations=1)
    result, lm = _run(["```repl\nx = 1\n```", "FINAL(forced)"], cfg=cfg)
    assert (result.answer, result.stop_reason) == ("forced", "max_iterations")
    assert len(lm.root_calls) == 2
    assert lm.root_calls[1]["messages"][-1]["content"].endswith(forced_final_prompt())
    assert "Turn 2/1" not in lm.root_calls[1]["messages"][-1]["content"]


def test_timeout_carries_partial_answer() -> None:
    cfg = _cfg(max_timeout=0.3)
    lm = MockLM(
        ["```repl\nimport time\nanswer['content'] = 'so far'\ntime.sleep(0.5)\n```", "FINAL(x)"]
    )
    with pytest.raises(RLMTimeout) as exc:
        RLM(cfg, lm).completion(CONTEXT, "?")
    assert exc.value.partial_answer == "so far"
    assert len(lm.root_calls) == 1


def test_error_limit() -> None:
    cfg = _cfg(max_errors=2)
    lm = MockLM(["```repl\nx = 1 / 0\n```", "```repl\nundefined_name\n```", "FINAL(never)"])
    with pytest.raises(RLMErrorLimit, match="2 consecutive REPL errors"):
        RLM(cfg, lm).completion(CONTEXT, "?")
    assert len(lm.root_calls) == 2


def test_token_limit() -> None:
    cfg = _cfg(max_tokens_total=20)  # each mock completion is 15 tokens
    lm = MockLM(["```repl\nx = 1\n```", "```repl\ny = 2\n```", "FINAL(never)"])
    with pytest.raises(RLMTokenLimit):
        RLM(cfg, lm).completion(CONTEXT, "?")


def test_length_finish_with_empty_content_retries_without_thinking() -> None:
    lm = MockLM([completion("", finish_reason="length"), "FINAL(ok)"])
    result = RLM(_cfg(), lm).completion(CONTEXT, "?")
    assert result.answer == "ok" and result.iterations == 1
    assert [c["enable_thinking"] for c in lm.root_calls] == [None, False]


# --- compaction ---------------------------------------------------------------


def test_compaction_stubs_old_outputs_and_keeps_full_history_in_repl(tmp_path: Path) -> None:
    cfg = _cfg(context_tokens=1_600, max_iterations=8)  # limit ~1,360 tokens ~ 4,760 chars
    loud = "```repl\nprint('x' * 400)\n```"
    root = [
        loud,
        loud.replace("'x'", "'y'"),
        loud.replace("'x'", "'z'"),
        loud.replace("'x'", "'w'"),
        loud.replace("'x'", "'v'"),
        loud.replace("'x'", "'u'"),
        "```repl\nprint(len(history), any('elided' in m['content'] for m in history))\n```",
        "FINAL(done)",
    ]
    logger = TrajectoryLogger(tmp_path)
    lm = MockLM(root)
    result = RLM(cfg, lm, logger=logger).completion(CONTEXT, "?")
    assert result.answer == "done"

    last_messages = lm.root_calls[-1]["messages"]
    stubs = [m for m in last_messages if m["content"].startswith("[REPL output from turn")]
    assert stubs, "expected at least one elided turn"
    assert "elided; " in stubs[0]["content"]
    recent = [m["content"] for m in last_messages[-8:]]
    assert any("'u" in c or "u" * 50 in c for c in recent)  # the last K turns are intact
    # the model-side check ran against the uncompacted history pushed into the REPL
    check_output = lm.root_calls[-1]["messages"][-1]["content"]
    assert "False" in check_output.splitlines()[1]

    events = [json.loads(line) for line in Path(logger.path).read_text().splitlines()]
    compactions = [e for e in events if e["type"] == "compaction"]
    assert compactions and compactions[0]["elided_turns"]
    if compactions[0]["summarized"]:
        assert any("[Summary of elided REPL output" in m["content"] for m in last_messages)
        assert lm.sub_calls


# --- logging ------------------------------------------------------------------


def test_jsonl_trajectory_has_no_secrets_and_parses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RECLAMO_API_KEY", "sk-test-SECRET")
    cfg = _cfg(sft_log=True)
    logger = TrajectoryLogger(tmp_path, sft=True)
    lm = MockLM(["```repl\nr = llm_query('q')\n```", "FINAL_VAR(r)"])
    result = RLM(cfg, lm, logger=logger).completion(CONTEXT, "the query")
    assert result.trajectory_path == str(logger.path)

    text = Path(logger.path).read_text(encoding="utf-8")
    assert "sk-test-SECRET" not in text
    events = [json.loads(line) for line in text.splitlines()]
    types = [e["type"] for e in events]
    assert types[0] == "metadata" and types[-1] == "final"
    assert "iteration" in types and "subcall" in types
    meta = events[0]
    assert meta["query"] == "the query" and meta["config"]["name"] == "test"
    assert meta["config"]["api_key_env"] == "RECLAMO_API_KEY"  # the name, never a value
    iteration = next(e for e in events if e["type"] == "iteration")
    assert iteration["reasoning"] == SECRET_REASONING  # logged separately...
    assert SECRET_REASONING not in lm.all_message_text()  # ...never in the history

    sft_lines = [json.loads(line) for line in Path(logger.sft_path).read_text().splitlines()]
    assert len(sft_lines) == 2
    assert sft_lines[0]["messages"][0]["role"] == "system"
    assert sft_lines[1]["completion"] == "FINAL_VAR(r)"
    assert "sk-test-SECRET" not in Path(logger.sft_path).read_text()


# --- helpers ------------------------------------------------------------------


def test_describe_context_kinds() -> None:
    assert describe_context("abc")[0] == "str"
    kind, meta = describe_context(["ab", "cde"])
    assert kind == "json" and meta.total_chars == 5 and meta.chunk_lengths == [2, 3]
    kind, meta = describe_context({"a.txt": "xx", "b.txt": "yyy"})
    assert kind == "json" and meta.chunk_lengths == [2, 3] and "dict with 2 keys" in meta.kind
    with pytest.raises(TypeError):
        describe_context(42)


def test_json_context_reaches_repl() -> None:
    result, _ = _run(
        ["```repl\nprint(sorted(context))\n```", "FINAL(ok)"],
        context={"b.txt": "two", "a.txt": "one"},
    )
    assert result.answer == "ok"


def test_ready_answer_wins_over_error_limit() -> None:
    cfg = _cfg(max_errors=1)
    code = (
        "```repl\nanswer['content'] = 'done'\nanswer['ready'] = True\n```\n```repl\nx = 1 / 0\n```"
    )
    result, lm = _run([code], cfg=cfg)
    assert (result.answer, result.stop_reason) == ("done", "answer_dict")
    assert len(lm.root_calls) == 1
