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


def test_defaults() -> None:
    s = PromptSettings()
    assert s.subcall_chars == 12_000
    assert s.max_depth == 1


def test_prompt_uses_one_consistent_subcall_figure() -> None:
    prompt = build_system_prompt(PromptSettings(subcall_chars=9_000), META)
    assert "9,000" in prompt
    assert "size = 9000" in prompt
    assert "12,000" not in prompt
    assert "12000" not in prompt
    # No other large character figure sneaks in besides the context size.
    numbers = {int(n.replace(",", "")) for n in re.findall(r"\d[\d,]{3,}", prompt)}
    assert numbers <= {9_000, 1_234_567, 1000}


def test_rlm_query_omitted_at_depth_one() -> None:
    prompt = build_system_prompt(PromptSettings(max_depth=1), META)
    assert "rlm_query" not in prompt
    assert "llm_query(" in prompt
    assert "llm_query_batched(" in prompt


def test_rlm_query_included_at_depth_two_with_guidance() -> None:
    prompt = build_system_prompt(PromptSettings(max_depth=2), META)
    assert "rlm_query(prompt: str)" in prompt
    assert "own REPL" in prompt
    assert "`llm_query` is faster" in prompt


def test_prompt_contains_batching_warning() -> None:
    prompt = build_system_prompt(PromptSettings(), META)
    assert "IMPORTANT" in prompt
    assert "one call at a time" in prompt
    assert "never 1000" in prompt
    assert "hard cap" in prompt


def test_prompt_contains_two_examples_as_repl_fences() -> None:
    prompt = build_system_prompt(PromptSettings(), META)
    blocks = find_code_blocks(prompt, strict=True)
    assert len(blocks) == 2
    assert "llm_query_batched" in blocks[0]
    assert "re.split" in blocks[1]
    for block in blocks:
        compile(block, "<example>", "exec")


def test_prompt_rules_present() -> None:
    prompt = build_system_prompt(PromptSettings(), META)
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
    prompt = build_system_prompt(PromptSettings(), META)
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


def test_batching_wording_follows_concurrency() -> None:
    from reclamo.prompts import PromptSettings, build_system_prompt

    meta = ContextMeta(kind="str", total_chars=10)
    one = build_system_prompt(PromptSettings(concurrency=1), meta)
    four = build_system_prompt(PromptSettings(concurrency=4), meta)
    assert "runs one call at a time" in one
    assert "runs at most 4 calls at a time" in four
