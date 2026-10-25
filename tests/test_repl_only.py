"""The REPL-only ablation arm (issue #83): harness v0.1 with sub-calls removed and off."""

from __future__ import annotations

import dataclasses
import difflib
from typing import Any

import pytest

from reclamo.config import (
    VERSION_DEFAULTS,
    ConfigError,
    ModelConfig,
    RLMConfig,
    load_config,
)
from reclamo.prompts import (
    ContextMeta,
    PromptSettings,
    build_system_prompt,
    build_tools_system_prompt,
    repl_only_removals,
)
from reclamo.rlm import RLM
from tests.mocklm import MockLM
from tests.test_frozen_arms import _generator, _run_eval

REPL_ONLY = "v0.1-repl-only"
METAS = [
    ContextMeta(kind="str", total_chars=1_234_567),
    ContextMeta(kind="list", total_chars=88_000, chunk_lengths=[8_000] * 11),
]
SUBCALL_WORDS = ("llm_query", "rlm_query", "sub-call", "language model", "sub-LLM")


def _pluto(version: str) -> RLMConfig:
    cfg = load_config("pluto", user_file="/nonexistent/profiles.toml", env={})
    return dataclasses.replace(cfg, prompt_version=version)


# --- the prompt ----------------------------------------------------------------------


@pytest.mark.parametrize("depth", [1, 2])
@pytest.mark.parametrize("concurrency", [1, 2])
@pytest.mark.parametrize("chars", [12_000, 50_000])
@pytest.mark.parametrize("meta", METAS)
def test_repl_only_prompt_is_v01_minus_the_subcall_text(
    depth: int, concurrency: int, chars: int, meta: ContextMeta
) -> None:
    kw: dict[str, Any] = {"subcall_chars": chars, "max_depth": depth, "concurrency": concurrency}
    v01 = build_system_prompt(PromptSettings(prompt_version="v0.1", **kw), meta)
    repl = build_system_prompt(PromptSettings(prompt_version=REPL_ONLY, **kw), meta)

    # Rebuilding it by hand from v0.1 and the listed removals gives the same text.
    removals = repl_only_removals(chars, depth > 1, concurrency)
    expected = v01
    for piece in removals:
        assert expected.count(piece) == 1
        expected = expected.replace(piece, "")
    assert repl == expected

    # Only deletions: no character of the REPL-only prompt is new.
    ops = difflib.SequenceMatcher(a=v01, b=repl, autojunk=False).get_opcodes()
    assert {op for op, *_ in ops} <= {"equal", "delete"}

    # Every removed piece mentions a sub-call, and none survives.
    for piece in removals:
        assert any(w in piece for w in SUBCALL_WORDS), piece
    for word in SUBCALL_WORDS:
        assert word not in repl, word
    assert "llm_query" in v01  # the comparison is not vacuous

    # What stays: the data, the REPL tools that do not call a model, and the rules.
    for kept in ("## The data", "SHOW_VARS()", "`answer`: a dict", "## Rules", "FINAL_VAR"):
        assert kept in repl
    assert meta.render() in repl


def test_repl_only_removals_are_the_four_listed_pieces() -> None:
    removals = repl_only_removals(12_000)
    assert removals[0].startswith(" Inside the REPL you can ask a separate language model")
    assert removals[1].startswith("\n- `llm_query(prompt: str) -> str`")
    assert removals[2].startswith("\n- `llm_query_batched(")
    assert removals[3].startswith("\n\n## IMPORTANT: sub-calls are expensive")
    assert removals[4].startswith("\n\n## Two ways to decompose")
    assert len(removals) == 5
    assert len(repl_only_removals(12_000, recursive=True)) == 6  # plus the rlm_query bullet


def test_repl_only_prompt_from_the_pluto_config() -> None:
    meta = METAS[0]
    v01 = build_system_prompt(_pluto("v0.1"), meta)
    repl = build_system_prompt(_pluto(REPL_ONLY), meta)
    for piece in repl_only_removals(12_000, False, 2):
        v01 = v01.replace(piece, "")
    assert repl == v01


def test_tools_prompt_refuses_repl_only() -> None:
    with pytest.raises(ValueError, match="fence protocol only"):
        build_tools_system_prompt(PromptSettings(prompt_version=REPL_ONLY), METAS[0])


# --- the config ----------------------------------------------------------------------


def test_repl_only_inherits_every_v01_limit_but_the_subcall_budget() -> None:
    v01, repl = _pluto("v0.1"), _pluto(REPL_ONLY)
    assert repl.max_subcalls_per_run == 0
    assert VERSION_DEFAULTS[REPL_ONLY] == {**VERSION_DEFAULTS["v0.1"], "max_subcalls_per_run": 0}
    assert (repl.max_iterations, repl.output_truncate_chars) == (20, 2_000)
    assert (repl.root.max_tokens, repl.sub.max_tokens) == (4_096, 2_048)
    assert (repl.root.timeout, repl.sub.timeout) == (300.0, 300.0)
    assert repl.effective_subcall_chars == 12_000
    a, b = dataclasses.asdict(v01), dataclasses.asdict(repl)
    for d in (a, b):
        d.pop("defaults_resolved")
    diff = {k for k in a if a[k] != b[k]}
    assert diff == {"prompt_version", "max_subcalls_per_run"}
    # and back again
    again = dataclasses.replace(repl, prompt_version="v0.1")
    assert again.max_subcalls_per_run == 64


@pytest.mark.parametrize(
    "overrides, match",
    [
        ({"protocol": "tools"}, "fence"),
        ({"planner_style": "upstream-rlm-v0"}, "fence"),
        ({"max_subcalls_per_run": 5}, "max_subcalls_per_run = 0"),
    ],
)
def test_repl_only_rejects_combinations_that_allow_subcalls(
    overrides: dict[str, Any], match: str
) -> None:
    with pytest.raises(ConfigError, match=match):
        RLMConfig(
            base_url="http://x",
            prompt_version=REPL_ONLY,
            root=ModelConfig(model="m"),
            sub=ModelConfig(model="m"),
            **overrides,
        )


# --- a model that calls llm_query anyway ---------------------------------------------


@pytest.mark.parametrize(
    "call, kind",
    [
        ("llm_query('what is in here?')", "llm_query"),
        ("llm_query_batched(['a', 'b'])", "llm_query_batched"),
        ("rlm_query('q', context)", "rlm_query"),
    ],
)
def test_a_subcall_gets_a_clear_error_and_the_run_continues(call: str, kind: str) -> None:
    lm = MockLM(
        [
            f"```repl\nx = {call}\nprint(x)\n```",
            "```repl\nn = len(context.splitlines())\nprint(n)\n```",
            "FINAL_VAR(n)",
        ]
    )
    result = RLM(_pluto(REPL_ONLY), lm).completion("a\nb\nc\n", "How many lines?")
    assert result.answer == "3" and result.stop_reason == "final_var"
    assert result.subcalls == 0 and lm.sub_calls == []
    seen = lm.root_calls[1]["messages"][-1]["content"]
    assert f"RuntimeError: {kind} is disabled in this run: no sub-calls are available." in seen
    system = lm.root_calls[0]["messages"][0]["content"]
    assert "llm_query" not in system and "rlm_query" not in system


def test_repl_only_row_has_the_rlm_row_schema(tmp_path: Any) -> None:
    run_eval = _run_eval()
    gens = run_eval.Generators({"generators": {"Frozen": {"vendor": "v", "model": "m"}}})
    gens.add("Frozen", _generator())
    script = [
        "```repl\nhits = [l for l in context.splitlines() if 'vault' in l]\n"
        "a = llm_query(hits[0])\nprint(hits)\n```",
        "FINAL(4417)",
    ]
    rows = {}
    for version in ("v0.1", REPL_ONLY):
        lm = MockLM(list(script), sub=lambda _p: "4417")
        rows[version] = run_eval.run_row(
            _pluto(version), lm, gens, "Frozen", "small", "rlm", 0, str(tmp_path)
        )
    assert set(rows["v0.1"]) == set(rows[REPL_ONLY])
    assert rows["v0.1"]["subcalls"] == 1 and rows[REPL_ONLY]["subcalls"] == 0
    assert rows[REPL_ONLY]["exact"] is True and rows[REPL_ONLY]["exec_errors"] == 1


def test_run_eval_and_bench_accept_the_repl_only_version() -> None:
    import bench

    run_eval = _run_eval()
    args = run_eval.build_parser().parse_args(["--prompt-version", REPL_ONLY, "--modes", "rlm"])
    assert args.prompt_version == REPL_ONLY
    args = bench.build_parser().parse_args(["--prompt-version", REPL_ONLY])
    assert args.prompt_version == REPL_ONLY
