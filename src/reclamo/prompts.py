"""System and per-turn prompts for the RLM loop, tuned for Qwen on a 32K window.

The system prompt follows the shape of the RLM paper's Qwen3-8B / 32K-context
variant (arXiv 2512.24601, App. C.1), written here in our own words. One
figure, ``subcall_chars``, governs every size hint so the prompt never
contradicts itself. The ``rlm_query`` section only appears when recursion is
allowed (``max_depth > 1``), because Qwen does worse at depth two and beyond.
"""

from __future__ import annotations

from dataclasses import dataclass

_MAX_CHUNKS_SHOWN = 10


@dataclass(frozen=True)
class PromptSettings:
    """The two knobs the prompt reads. ``RLMConfig`` carries the same names."""

    subcall_chars: int = 12_000
    max_depth: int = 1
    concurrency: int = 1


@dataclass(frozen=True)
class ContextMeta:
    """What the model is told about ``context`` before it looks."""

    kind: str
    total_chars: int
    chunk_lengths: list[int] | None = None

    def render(self) -> str:
        line = f"`context` is a {self.kind} of {self.total_chars:,} characters in total."
        if not self.chunk_lengths:
            return line
        shown = self.chunk_lengths[:_MAX_CHUNKS_SHOWN]
        rest = len(self.chunk_lengths) - len(shown)
        lengths = ", ".join(f"{n:,}" for n in shown)
        if rest > 0:
            lengths += f", ... (+{rest} more)"
        return f"{line} It has {len(self.chunk_lengths)} chunks with lengths: {lengths}."


def _tools_section(subcall_chars: int, recursive: bool) -> str:
    lines = [
        "## Tools inside the REPL",
        "",
        "- `context`: the data to answer about. It is already loaded; never try to "
        "print all of it.",
        "- `llm_query(prompt: str) -> str`: ask a fresh language model one question. "
        "It sees only `prompt`, nothing from this conversation, so put the relevant "
        f"text in the prompt. Keep each prompt under about {subcall_chars:,} characters.",
        "- `llm_query_batched(prompts: list[str]) -> list[str]`: the same, for several "
        "prompts; answers come back in the same order.",
        "- `SHOW_VARS()`: list the variables you have created so far and their types.",
        '- `answer`: a dict. Set `answer["content"] = ...` and `answer["ready"] = True` '
        "to finish, as an alternative to FINAL / FINAL_VAR below.",
    ]
    if recursive:
        lines.append(
            "- `rlm_query(question: str, data) -> str`: start a nested copy of this whole "
            "loop on `data` (a str, list or dict, such as one value of `context`). It gets "
            "`data` as its own `context`, works in turns with its own REPL and sub-calls, "
            "and returns its final answer. Use it when `context` splits into large "
            "independent parts (one per key, section or file) that each need their own "
            "inspection and iteration; give each child a precise question and ask for a "
            "short, parseable answer. For a plain 'read this and answer' task, `llm_query` "
            "is faster and more reliable."
        )
    return "\n".join(lines)


def _batching_section(subcall_chars: int, concurrency: int = 1) -> str:
    pace = (
        "runs one call at a time"
        if concurrency <= 1
        else f"runs at most {concurrency} calls at a time"
    )
    return (
        "## IMPORTANT: sub-calls are expensive\n"
        "\n"
        f"`llm_query` {pace}, and each call takes seconds. Do not call it "
        "once per line, once per record, or inside a tight loop. Batch instead: gather "
        f"about {subcall_chars:,} characters of text into one prompt and ask about the "
        "whole batch. For a context of 1000 lines, that means roughly 10 to 20 calls, "
        "never 1000. There is a hard cap on sub-calls per code block and per run; once "
        "it is reached, further calls fail with an error."
    )


def _examples_section(subcall_chars: int, recursive: bool = False) -> str:
    recursion = (
        "\n\n"
        "Delegate, when the parts are large and independent and recursion is allowed:\n"
        "\n"
        "```repl\n"
        "question = 'How many lines of this log mention a refund? Reply with just the number.'\n"
        "per_part = {name: rlm_query(question, text) for name, text in context.items()}\n"
        "print(per_part)\n"
        "```"
        if recursive
        else ""
    )
    heading = "## Three ways to decompose\n" if recursive else "## Two ways to decompose\n"
    return (
        heading + "\n"
        "Chunk and map, for data with no natural structure:\n"
        "\n"
        "```repl\n"
        f"size = {subcall_chars}\n"
        "chunks = [context[i : i + size] for i in range(0, len(context), size)]\n"
        "prompts = [f'Does this text mention the launch date? Quote it.\\n\\n{c}' "
        "for c in chunks]\n"
        "hits = llm_query_batched(prompts)\n"
        "print(len(chunks), 'chunks;', sum('yes' in h.lower() for h in hits), 'hits')\n"
        "```\n"
        "\n"
        "Split on structure, when the data has headers or records:\n"
        "\n"
        "```repl\n"
        "import re\n"
        "sections = re.split(r'(?m)^## ', context)[1:]\n"
        "summaries = llm_query_batched([f'Summarize in one line:\\n\\n{s}' for s in sections])\n"
        "print(len(sections), 'sections; first summary:', summaries[0][:200])\n"
        "```" + recursion
    )


def _rules_section() -> str:
    return (
        "## Rules\n"
        "\n"
        "1. Look before you compute. On your first turn, inspect `context` (type, "
        "length, a short slice) so your plan matches the data.\n"
        "2. Keep results in variables. Print only short summaries: counts, a few "
        "lines, the first few hundred characters. Long output is truncated and "
        "wastes your window.\n"
        "3. Write exactly one code block per turn, fenced as ```repl. Wait for its "
        "output before deciding the next step.\n"
        "4. Finish only when the answer exists. Reply with `FINAL(<answer text>)` on its "
        "own, with no code block in the same message, or `FINAL_VAR(<name>)` where "
        "`<name>` is a variable you already created that holds the answer. Or set "
        '`answer["content"]` and `answer["ready"] = True` in code.\n'
        "5. A FINAL must contain the answer, not a plan, not a description of what you "
        "will do, and not a repeat of an earlier check. If the answer is already in a "
        "variable, use FINAL_VAR with that variable."
    )


def build_system_prompt(settings: PromptSettings | object, context_meta: ContextMeta) -> str:
    """Compose the system prompt.

    ``settings`` only needs ``subcall_chars`` and ``max_depth`` attributes, so
    ``RLMConfig`` can be passed in directly.
    """
    subcall_chars = int(getattr(settings, "subcall_chars", 12_000))
    max_depth = int(getattr(settings, "max_depth", 1))
    concurrency = int(getattr(settings, "concurrency", 1))
    recursive = max_depth > 1

    intro = (
        "You answer a question about data that is far too large to read at once. The "
        "data lives in a Python REPL as the variable `context`; you never see it "
        "directly. You work in turns: each turn you write one block of Python, the REPL "
        "runs it and shows you the output, and you decide the next step. Variables "
        "persist between turns. Inside the REPL you can ask a separate language model to "
        "read a piece of the data for you.\n"
        "\n"
        "Your own context window is small. Treat it as a scratchpad for decisions, and "
        "keep the data and the intermediate results in REPL variables."
    )

    parts = [
        intro,
        "## The data",
        context_meta.render(),
        _tools_section(subcall_chars, recursive),
        _batching_section(subcall_chars, concurrency),
        _examples_section(subcall_chars, recursive),
        _rules_section(),
    ]
    return "\n\n".join(parts) + "\n"


def turn_prompt(i: int, n: int, first: bool = False) -> str:
    """The short user message that opens each turn (stored, so the prefix is reused)."""
    line = f"Turn {i}/{n}."
    if first:
        line += (
            " Start by inspecting `context` (type, length, a short slice) in one code "
            "block. Do not answer yet."
        )
    return line


def decompose_nudge() -> str:
    return (
        "Your last code handed nearly the whole context to a single sub-call. That "
        "defeats the purpose: the sub-model has the same limits you do. Split the "
        "context into pieces and ask about each piece, then combine the results in "
        "a variable."
    )


def reverify_nudge(var: str) -> str:
    return (
        f"You already computed the answer; it is in `{var}` and the last two turns "
        f"repeated the same check. Stop verifying. Reply with `FINAL_VAR({var})`."
    )


def final_rejection(reason: str) -> str:
    return (
        f"That FINAL was not accepted: {reason} Continue working, and send FINAL or "
        "FINAL_VAR only when the answer itself is ready, in a message with no code."
    )


def forced_final_prompt() -> str:
    return (
        "You are out of turns. Reply now with your best answer as `FINAL(<answer>)`, "
        "or `FINAL_VAR(<name>)` if a variable already holds it. No code."
    )


__all__ = [
    "ContextMeta",
    "PromptSettings",
    "build_system_prompt",
    "decompose_nudge",
    "final_rejection",
    "forced_final_prompt",
    "reverify_nudge",
    "turn_prompt",
]
