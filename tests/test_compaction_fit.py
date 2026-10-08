"""Issue #49: every root request fits ``context_tokens`` with room for the reply."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from reclamo.config import ModelConfig, RLMConfig
from reclamo.logger import TrajectoryLogger
from reclamo.rlm import FIT_MARGIN, RLM, estimate_tokens, request_tokens
from tests.mocklm import MockLM, call, tool_turn

CONTEXT = "line one\nline two\nline three\n"
STYLES = ["reclamo", "upstream-rlm-v0"]
STUB = "of this REPL output elided to fit the context window"


def _cfg(**overrides: Any) -> RLMConfig:
    fields: dict[str, Any] = {
        "name": "test",
        "base_url": "http://unused/v1",
        "max_iterations": 5,
        "exec_timeout": 10.0,
        "max_timeout": 60.0,
        "output_truncate_chars": 8_000,
        "context_tokens": 11_000,
        "root": ModelConfig(model="m", max_tokens=4_096),
        "sub": ModelConfig(model="m"),
    }
    fields.update(overrides)
    return RLMConfig(**fields)


def _budget(cfg: RLMConfig) -> int:
    return int(cfg.context_tokens - cfg.root.max_tokens - FIT_MARGIN * cfg.context_tokens)


def _sizes(lm: MockLM, cfg: RLMConfig) -> list[int]:
    out = []
    for c in lm.root_calls:
        extra = estimate_tokens(json.dumps(c["tools"])) if c["tools"] else 0
        out.append(request_tokens(c["messages"], extra))
    return out


def _events(logger: TrajectoryLogger, kind: str) -> list[dict[str, Any]]:
    lines = Path(logger.path).read_text().splitlines()
    return [e for e in map(json.loads, lines) if e["type"] == kind]


def _loud_turn(blocks: int, chars: int) -> str:
    """One reply with ``blocks`` repl blocks, each printing ``chars`` characters."""
    return "\n".join(f"```repl\nprint({chr(97 + k)!r} * {chars})\n```" for k in range(blocks))


def test_budget_reserves_the_reply_and_a_margin() -> None:
    cfg = _cfg(context_tokens=16_384, root=ModelConfig(model="m", max_tokens=4_096))
    assert RLM(cfg, MockLM([]))._input_budget() == _budget(cfg) == 10_649
    # a max_tokens near the window still leaves a quarter of it for the prompt
    tiny = _cfg(context_tokens=4_000, root=ModelConfig(model="m", max_tokens=4_000))
    assert RLM(tiny, MockLM([]))._input_budget() == 1_000


def test_estimate_counts_digits_as_tokens() -> None:
    assert estimate_tokens("1234567890") == 10
    assert estimate_tokens("abcdefg") == 2
    assert estimate_tokens("") == 0


@pytest.mark.parametrize("style", STYLES)
def test_one_oversized_turn_of_many_blocks_is_shrunk_to_fit(style: str, tmp_path: Path) -> None:
    """The live failure: ~10 blocks x 8,000 chars in one turn of the 8B planner."""
    cfg = _cfg(planner_style=style)
    check = "```repl\nprint('LONGEST', max(len(m['content']) for m in history))\n```"
    logger = TrajectoryLogger(tmp_path)
    lm = MockLM([_loud_turn(10, 8_000), check, "FINAL(done)"])
    result = RLM(cfg, lm, logger=logger).completion(CONTEXT, "q?")
    assert (result.answer, result.stop_reason) == ("done", "final")

    sizes = _sizes(lm, cfg)
    assert max(sizes) <= _budget(cfg), sizes
    second = "\n".join(m["content"] or "" for m in lm.root_calls[1]["messages"])
    assert STUB in second and "`history`" in second
    # oldest outputs go first; the newest block's output survives, at least its head
    assert "jjjjjjjj" in second
    # the REPL still has every byte of the turn
    third = "\n".join(m["content"] or "" for m in lm.root_calls[2]["messages"])
    match = re.search(r"LONGEST (\d+)", third)
    assert match and int(match.group(1)) >= 8_000

    (first, *_) = _events(logger, "compaction")
    assert first["shrunk_messages"] and first["after_tokens"] <= first["budget_tokens"]
    assert not _events(logger, "context_overflow")


def test_one_oversized_turn_in_the_tools_protocol() -> None:
    cfg = _cfg(protocol="tools")
    calls = [call("execute_python", code=f"print({chr(97 + k)!r} * 8000)") for k in range(10)]
    lm = MockLM([tool_turn(*calls), tool_turn(call("final_answer", answer="done"))])
    result = RLM(cfg, lm).completion(CONTEXT, "q?")
    assert result.answer == "done"
    assert max(_sizes(lm, cfg)) <= _budget(cfg)
    msgs = lm.root_calls[1]["messages"]
    tool_msgs = [m for m in msgs if m["role"] == "tool"]
    assert len(tool_msgs) == 10 and all(m["tool_call_id"] for m in tool_msgs)
    assert any(STUB in m["content"] for m in tool_msgs)


@pytest.mark.parametrize("style", STYLES)
def test_history_growth_never_exceeds_the_budget(style: str) -> None:
    cfg = _cfg(planner_style=style, max_iterations=16, context_tokens=6_000,
               root=ModelConfig(model="m", max_tokens=1_024))  # fmt: skip
    root = [f"```repl\nprint({chr(97 + k)!r} * 1500)\n```" for k in range(14)]
    lm = MockLM([*root, "FINAL(done)"])
    result = RLM(cfg, lm).completion(CONTEXT, "q?")
    assert result.answer == "done"
    assert max(_sizes(lm, cfg)) <= _budget(cfg)


@pytest.mark.parametrize("style", STYLES)
def test_unshrinkable_request_takes_the_forced_finish(style: str, tmp_path: Path) -> None:
    """Code the model wrote is never shrunk; when it alone overflows, stop cleanly."""
    cfg = _cfg(planner_style=style)
    huge = "```repl\n# " + "x" * 30_000 + "\nfinal_answer = 'kept'\n```"
    logger = TrajectoryLogger(tmp_path)
    lm = MockLM([huge, "FINAL_VAR(final_answer)"])
    result = RLM(cfg, lm, logger=logger).completion(CONTEXT, "q?")
    assert (result.answer, result.stop_reason) == ("kept", "context_overflow")
    assert len(lm.root_calls) == 2
    forced = lm.root_calls[1]["messages"]
    assert request_tokens(forced) <= _budget(cfg)
    assert "x" * 1000 not in "".join(m["content"] or "" for m in forced)
    assert "no longer fits the context window" in forced[-1]["content"]
    assert "- final_answer = kept" in forced[-1]["content"]

    (turn, forced_event) = _events(logger, "context_overflow")
    assert turn["during"] == "turn" and turn["request_tokens"] > turn["budget_tokens"]
    assert (turn["context_tokens"], turn["max_tokens"]) == (11_000, 4_096)
    assert forced_event["action"] == "opening_messages_only"
    (ff,) = _events(logger, "forced_finish")
    assert ff["why"] == "context" and ff["source"] == "model"


def test_forced_finish_that_cannot_fit_at_all_falls_back_without_a_call(tmp_path: Path) -> None:
    # The system prompt alone is over this budget, so even the cut-down request overflows.
    cfg = _cfg(context_tokens=1_000, root=ModelConfig(model="m", max_tokens=900))
    logger = TrajectoryLogger(tmp_path)
    lm = MockLM([])
    result = RLM(cfg, lm, logger=logger).completion(CONTEXT, "q?")
    assert (result.answer, result.stop_reason) == ("", "context_overflow")
    assert lm.root_calls == []
    assert [e["action"] for e in _events(logger, "context_overflow")[1:]] == ["no_model_call"]


def test_v02_defaults_on_a_pluto_window_keep_every_request_in_budget(tmp_path: Path) -> None:
    """Issue #61: 20,000-char REPL outputs and an 8,192-token root reply on a 32K window.
    Compaction (#49) must keep every root request under the budget."""
    cfg = RLMConfig(
        name="t",
        base_url="http://unused/v1",
        context_tokens=32_768,
        exec_timeout=10.0,
        root=ModelConfig(model="m", enable_thinking=True),
        sub=ModelConfig(model="m"),
    )
    assert (cfg.output_truncate_chars, cfg.root.max_tokens, cfg.max_iterations) == (
        20_000, 8_192, 30,
    )  # fmt: skip
    loud = [_loud_turn(2, 20_000).replace("'a'", repr(chr(97 + i))) for i in range(10)]
    lm = MockLM([*loud, "FINAL(done)"])
    logger = TrajectoryLogger(tmp_path)
    result = RLM(cfg, lm, logger=logger).completion(CONTEXT, "?")
    assert result.answer == "done" and result.stop_reason == "final"
    budget = _budget(cfg)
    assert max(_sizes(lm, cfg)) <= budget
    # outputs really were 20K (not cut to 2K by the REPL) before compaction shrank them
    assert any(len(m["content"]) > 15_000 for c in lm.root_calls[:2] for m in c["messages"])
