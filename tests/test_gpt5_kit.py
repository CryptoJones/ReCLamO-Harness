"""The frontier replication kit (#120): the GPT-5 prompt style and the OpenAI dialect."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import pytest

from reclamo.client import LMClient
from reclamo.config import ConfigError, ModelConfig, RLMConfig, load_config
from reclamo.rlm import RLM
from reclamo.upstream import (
    SYSTEM_PROMPTS,
    UPSTREAM_GPT5_SYSTEM_PROMPT,
    UPSTREAM_SYSTEM_PROMPT,
    initial_messages,
    user_prompt,
)
from tests.mocklm import MockLM

ROOT = Path(__file__).resolve().parents[1]
KIT_PROFILES = ROOT / "evals" / "gpt5-replication" / "profiles.toml"
CONTEXT = "alpha\nbeta\nthe magic number is 42\ngamma\n"
QUERY = "What is the magic number?"


def _cfg(**overrides: Any) -> RLMConfig:
    fields: dict[str, Any] = {
        "name": "t",
        "base_url": "http://unused/v1",
        "max_iterations": 5,
        "exec_timeout": 10.0,
        "max_timeout": 60.0,
        "planner_style": "upstream-rlm-gpt5",
        "root": ModelConfig(model="gpt-5"),
        "sub": ModelConfig(model="gpt-5-mini"),
    }
    fields.update(overrides)
    return RLMConfig(**fields)


# --- the (1a) prompt ---------------------------------------------------------------


def test_gpt5_prompt_is_the_paper_1a_text() -> None:
    p = UPSTREAM_GPT5_SYSTEM_PROMPT
    assert p.startswith("You are tasked with answering a query with associated context.")
    assert "~32k" not in p and "high runtime costs" not in p
    assert p.count("(that can handle around 500K chars)") == 1
    assert "they can fit around 500K characters in their context window" in p
    assert "feed 10 documents per sub-LLM query" in p
    assert "chunk = context[:10000]\n" in p
    assert "NOT in code. Do not use these tags" in p
    assert "\nFINAL_VAR(final_answer)\n" not in p  # (1c) adds that line; (1a) does not
    assert "llm_query_batched" not in p  # (1a) predates the batched helper
    assert "{{chunk}}" in p  # never formatted, as upstream
    assert "3. The ability to use `print()` statements" in p


def test_gpt5_prompt_differs_from_the_8b_one_only_by_the_1c_diff() -> None:
    """Undoing the paper's (1c) hunks on the 8B prompt must give the (1a) prompt."""
    q = UPSTREAM_SYSTEM_PROMPT
    q = q.replace(q[q.index("IMPORTANT: You have a total") : q.index("The REPL environment")], "")
    q = q.replace(
        "(that can handle around ~100k chars, roughly 32k tokens)",
        "(that can handle around 500K chars)",
    )
    start = q.index("You can use the REPL environment to help")
    end = q.index("respect the ~32k token limit.") + len("respect the ~32k token limit.")
    q = (
        q[:start]
        + UPSTREAM_GPT5_SYSTEM_PROMPT[
            UPSTREAM_GPT5_SYSTEM_PROMPT.index(
                "You can use the REPL environment to help"
            ) : UPSTREAM_GPT5_SYSTEM_PROMPT.index("fit it in a few sub-LLM calls!")
            + len("fit it in a few sub-LLM calls!")
        ]
        + q[end:]
    )
    q = q.replace("chunk = context[:1000]\n", "chunk = context[:10000]\n")
    q = q.replace(
        "FINAL_VAR(final_answer).\nFINAL_VAR(final_answer)\n", "FINAL_VAR(final_answer).\n"
    )
    q = q.replace("NOT in code or repl tags.", "NOT in code.")
    assert q == UPSTREAM_GPT5_SYSTEM_PROMPT


def test_style_picks_the_prompt() -> None:
    assert initial_messages(CONTEXT)[0]["content"] == UPSTREAM_SYSTEM_PROMPT
    msgs = initial_messages(CONTEXT, "upstream-rlm-gpt5")
    assert msgs[0] == {"role": "system", "content": UPSTREAM_GPT5_SYSTEM_PROMPT}
    assert msgs[1]["role"] == "assistant"
    assert set(SYSTEM_PROMPTS) == {"upstream-rlm-v0", "upstream-rlm-gpt5"}


def test_gpt5_style_runs_the_upstream_loop() -> None:
    lm = MockLM(
        [
            "```repl\nanswer = llm_query('find it: ' + context)\nprint(answer)\n```",
            "FINAL_VAR(answer)",
        ],
        sub=["42"],
    )
    result = RLM(_cfg(), lm).completion(CONTEXT, QUERY)
    assert result.answer == "42"
    first = lm.root_calls[0]["messages"]
    assert first[0]["content"] == UPSTREAM_GPT5_SYSTEM_PROMPT
    assert first[2]["content"] == user_prompt(QUERY, 0)
    second = lm.root_calls[1]["messages"]
    assert second[3]["content"].startswith("Code executed:\n```python\nanswer = llm_query(")


def test_gpt5_style_needs_fence_protocol() -> None:
    with pytest.raises(ConfigError, match='needs protocol = "fence"'):
        _cfg(protocol="tools")


# --- api_dialect = "openai" --------------------------------------------------------


def test_openai_dialect_request_shape() -> None:
    cfg = _cfg(
        root=ModelConfig(
            model="gpt-5", api_dialect="openai", reasoning_effort="medium", max_tokens=1000
        ),
        sub=ModelConfig(model="gpt-5-mini", api_dialect="openai", reasoning_effort="medium"),
    )
    client = LMClient(cfg, "k", sleep=lambda _s: None)
    kw = client.build_request([{"role": "user", "content": "hi"}], "root")
    assert kw["model"] == "gpt-5" and kw["reasoning_effort"] == "medium"
    assert kw["max_completion_tokens"] == 1000
    assert "max_tokens" not in kw and "extra_body" not in kw
    assert client.build_request([], "root", max_tokens=55)["max_completion_tokens"] == 55
    assert client.build_request([], "sub")["model"] == "gpt-5-mini"


def test_openai_dialect_rejects_nonstandard_sampling() -> None:
    root = ModelConfig(model="gpt-5", api_dialect="openai", sampling={"top_k": 20})
    client = LMClient(_cfg(root=root), "k", sleep=lambda _s: None)
    with pytest.raises(ValueError, match="top_k"):
        client.build_request([], "root")


def test_default_dialect_unchanged() -> None:
    root = ModelConfig(model="m", enable_thinking=True, reasoning_effort="medium", max_tokens=9)
    kw = LMClient(_cfg(root=root), "k", sleep=lambda _s: None).build_request([], "root")
    assert kw["max_tokens"] == 9 and "max_completion_tokens" not in kw
    assert kw["extra_body"]["chat_template_kwargs"] == {
        "enable_thinking": True,
        "reasoning_effort": "medium",
    }


def test_unknown_dialect_is_a_config_error() -> None:
    with pytest.raises(ConfigError, match="api_dialect"):
        ModelConfig(model="m", api_dialect="anthropic")


# --- the kit's profiles ------------------------------------------------------------


@pytest.mark.parametrize("name", ["gpt5-rlm", "gpt5-plain"])
def test_kit_profiles_load(name: str) -> None:
    cfg = load_config(name, KIT_PROFILES)
    assert cfg.base_url == "https://api.openai.com/v1"
    assert cfg.api_key_env == "OPENAI_API_KEY" and cfg.api_key_cmd is None
    assert cfg.root.model == "gpt-5" and cfg.root.api_dialect == "openai"
    assert cfg.root.reasoning_effort == "medium" and cfg.root.sampling == {}
    assert cfg.sub.model == "gpt-5-mini" and cfg.sub.api_dialect == "openai"
    assert cfg.context_tokens == 400_000 and cfg.root.max_tokens == 128_000
    if name == "gpt5-rlm":
        assert cfg.planner_style == "upstream-rlm-gpt5"
        assert (cfg.max_iterations, cfg.output_truncate_chars) == (30, 20_000)
    replaced = dataclasses.replace(cfg)
    assert replaced.root.api_dialect == "openai"
