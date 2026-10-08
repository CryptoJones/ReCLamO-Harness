import re
from dataclasses import dataclass

from reclamo.parsing import find_code_blocks
from reclamo.prompts import (
    ContextMeta,
    PromptSettings,
    build_system_prompt,
    decompose_nudge,
    final_rejection,
    forced_final_prompt,
    reverify_nudge,
    turn_prompt,
)

META = ContextMeta(kind="str", total_chars=1_234_567)


def V01(**kw: object) -> PromptSettings:
    """The published (v0.1) prompt; the tests below that use it pin its wording."""
    return PromptSettings(prompt_version="v0.1", **kw)  # type: ignore[arg-type]


def test_defaults() -> None:
    s = PromptSettings()
    assert s.subcall_chars == 12_000
    assert s.max_depth == 1


def test_prompt_uses_one_consistent_subcall_figure() -> None:
    prompt = build_system_prompt(PromptSettings(subcall_chars=9_000, prompt_version="v0.1"), META)
    assert "9,000" in prompt
    assert "size = 9000" in prompt
    assert "12,000" not in prompt
    assert "12000" not in prompt
    # No other large character figure sneaks in besides the context size.
    numbers = {int(n.replace(",", "")) for n in re.findall(r"\d[\d,]{3,}", prompt)}
    assert numbers <= {9_000, 1_234_567, 1000}


def test_rlm_query_omitted_at_depth_one() -> None:
    prompt = build_system_prompt(V01(max_depth=1), META)
    assert "rlm_query" not in prompt
    assert "llm_query(" in prompt
    assert "llm_query_batched(" in prompt


def test_rlm_query_included_at_depth_two_with_guidance() -> None:
    prompt = build_system_prompt(V01(max_depth=2), META)
    assert "rlm_query(question: str, data)" in prompt
    assert "own REPL" in prompt
    assert "`llm_query` is faster" in prompt
    assert "Three ways to decompose" in prompt
    assert "rlm_query(question, text) for name, text in context.items()" in prompt
    assert "Delegate" not in build_system_prompt(V01(max_depth=1), META)


def test_prompt_contains_batching_warning() -> None:
    prompt = build_system_prompt(V01(), META)
    assert "IMPORTANT" in prompt
    assert "one call at a time" in prompt
    assert "never 1000" in prompt
    assert "hard cap" in prompt


def test_prompt_contains_two_examples_as_repl_fences() -> None:
    prompt = build_system_prompt(V01(), META)
    blocks = find_code_blocks(prompt, strict=True)
    assert len(blocks) == 2
    assert "llm_query_batched" in blocks[0]
    assert "re.split" in blocks[1]
    for block in blocks:
        compile(block, "<example>", "exec")


def test_prompt_rules_present() -> None:
    prompt = build_system_prompt(V01(), META)
    assert "one code block per turn" in prompt
    assert "FINAL_VAR(<name>)" in prompt
    assert 'answer["ready"] = True' in prompt
    assert "SHOW_VARS()" in prompt
    assert "Keep results in variables" in prompt


def test_prompt_accepts_duck_typed_settings() -> None:
    @dataclass
    class Cfg:
        subcall_chars: int = 5_000
        max_depth: int = 3
        unrelated: str = "x"
        prompt_version: str = "v0.1"

    prompt = build_system_prompt(Cfg(), META)
    assert "5,000" in prompt
    assert "rlm_query" in prompt


def test_context_meta_plain() -> None:
    assert META.render() == "`context` is a str of 1,234,567 characters in total."


def test_context_meta_chunks_capped() -> None:
    meta = ContextMeta(kind="list[str]", total_chars=500, chunk_lengths=list(range(1, 26)))
    rendered = meta.render()
    assert "25 chunks" in rendered
    assert "1, 2, 3, 4, 5, 6, 7, 8, 9, 10, ... (+15 more)" in rendered
    assert "11," not in rendered


def test_context_meta_few_chunks_not_capped() -> None:
    meta = ContextMeta(kind="list[str]", total_chars=30, chunk_lengths=[10, 20])
    assert meta.render().endswith("2 chunks with lengths: 10, 20.")


def test_prompt_includes_context_meta() -> None:
    prompt = build_system_prompt(V01(), META)
    assert "1,234,567 characters" in prompt


def test_turn_prompt() -> None:
    assert turn_prompt(3, 20) == "Turn 3/20."
    first = turn_prompt(1, 20, first=True)
    assert first.startswith("Turn 1/20.")
    assert "inspecting `context`" in first
    assert "Do not answer yet" in first


def test_nudges_and_rejections() -> None:
    assert "whole context" in decompose_nudge()
    assert "FINAL_VAR(result)" in reverify_nudge("result")
    rej = final_rejection("it appeared next to code that has not run.")
    assert rej.startswith("That FINAL was not accepted: it appeared next to code")
    assert "FINAL(<answer>)" in forced_final_prompt()
    assert "No code" in forced_final_prompt()
    assert forced_final_prompt().startswith("You are out of turns.")
    assert forced_final_prompt("time").startswith("You are out of time.")


def test_batching_wording_follows_concurrency() -> None:
    from reclamo.prompts import build_system_prompt

    meta = ContextMeta(kind="str", total_chars=10)
    one = build_system_prompt(V01(concurrency=1), meta)
    four = build_system_prompt(V01(concurrency=4), meta)
    assert "runs one call at a time" in one
    assert "runs at most 4 calls at a time" in four


# --- prompt v0.2 (issue #59) ---------------------------------------------------

V02 = PromptSettings(subcall_chars=50_000, max_subcalls_per_exec=24, max_subcalls_per_run=64)


def test_v02_encourages_sub_calls_and_drops_the_deterrent() -> None:
    prompt = build_system_prompt(V02, META)
    assert "strongly encouraged to use them as much as possible" in prompt
    assert "don't be afraid to put a lot of context into one call" in prompt
    assert "sufficient to just fit it in a few sub-LLM calls" in prompt
    for deterrent in ("expensive", "IMPORTANT", "fail with an error", "never 1000"):
        assert deterrent not in prompt
    # The hard caps are still stated, as facts.
    assert "at most 24 per code block and 64 per run" in prompt
    assert "one call at a time" in prompt


def test_v02_has_the_orchestrator_guidance_including_when_not_to_delegate() -> None:
    prompt = build_system_prompt(V02, META)
    assert "## Work as an orchestrator, not a solver" in prompt
    assert "pause and plan" in prompt and "decomposes into sub-LLM / REPL steps" in prompt
    assert "would already pin the answer" in prompt and "just read it directly" in prompt
    assert "Delegate everything else." in prompt


def test_v02_examples_chain_a_buffer_and_aggregate() -> None:
    prompt = build_system_prompt(V02, META)
    blocks = find_code_blocks(prompt, strict=True)
    assert len(blocks) == 3
    one_call, map_aggregate, buffer = blocks
    assert "llm_query(" in one_call and "{context}" in one_call
    assert "llm_query_batched" in map_aggregate and "total = llm_query(" in map_aggregate
    assert "size = 50000" in map_aggregate
    assert "notes = llm_query(" in buffer and "{notes}" in buffer
    for block in blocks:
        compile(block, "<example>", "exec")


def test_v02_examples_run_against_a_fake_llm_query() -> None:
    prompt = build_system_prompt(PromptSettings(subcall_chars=40), META)
    calls: list[str] = []

    def llm_query(p: str) -> str:
        calls.append(p)
        return f"answer {len(calls)}"

    env = {
        "context": "## A\nAtlas goes to Ann.\n## B\nAtlas moves to Bo.\n" * 3,
        "llm_query": llm_query,
        "llm_query_batched": lambda ps: [llm_query(p) for p in ps],
    }
    for block in find_code_blocks(prompt, strict=True):
        exec(block, dict(env))
    assert any("Notes so far: answer" in c for c in calls)  # the buffer is carried
    assert any("Part 0: answer" in c for c in calls)  # per-chunk answers aggregated


def test_v02_says_when_the_whole_context_fits_one_call() -> None:
    fits = build_system_prompt(V02, ContextMeta("str", 40_000))
    big = build_system_prompt(V02, ContextMeta("str", 400_000))
    assert "The whole `context` (40,000 characters) fits in a single call." in fits
    assert "fits in a single call" not in big


def test_v02_uses_one_consistent_subcall_figure() -> None:
    prompt = build_system_prompt(V02, META)
    assert prompt.count("50,000") == 2 and "size = 50000" in prompt
    numbers = {int(n.replace(",", "")) for n in re.findall(r"\d[\d,]{3,}", prompt)}
    assert numbers <= {50_000, 1_234_567}


def test_v02_tools_prompt_has_the_same_guidance_without_fences() -> None:
    from reclamo.prompts import build_tools_system_prompt

    prompt = build_tools_system_prompt(V02, META)
    assert "strongly encouraged" in prompt and "orchestrator, not a solver" in prompt
    assert "```" not in prompt and "FINAL" not in prompt
    assert prompt.count("execute_python with code:") == 3


def test_v02_concurrency_wording() -> None:
    meta = ContextMeta(kind="str", total_chars=10)
    assert "up to 4 calls at a time" in build_system_prompt(PromptSettings(concurrency=4), meta)


def test_unknown_prompt_version_rejected() -> None:
    import pytest

    with pytest.raises(ValueError, match="prompt_version"):
        build_system_prompt(PromptSettings(prompt_version="v9"), META)


def test_decompose_nudge_per_version() -> None:
    assert decompose_nudge() == decompose_nudge("v0.1")
    assert "same limits you do" in decompose_nudge("v0.1")
    v02 = decompose_nudge("v0.2", 300_000, 78_336)
    assert "300,000 characters" in v02 and "about 78,336" in v02
    assert "same limits" not in v02
