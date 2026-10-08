"""System and per-turn prompts for the RLM loop, tuned for Qwen on a 32K window.

The system prompt follows the shape of the RLM paper's Qwen3-8B / 32K-context
variant (arXiv 2512.24601, App. C.1), written here in our own words. One
figure, ``subcall_chars``, governs every size hint so the prompt never
contradicts itself. The ``rlm_query`` section only appears when recursion is
allowed (``max_depth > 1``), because Qwen does worse at depth two and beyond.

``protocol="tools"`` (issue #20) swaps fenced code and ``FINAL`` text for two
OpenAI-style functions, ``execute_python`` and ``final_answer``
(``tool_specs``). Its system prompt keeps the same data, batching and
decomposition guidance; only the "how to act" parts differ. The fence prompt is
unchanged.

Prompt versions (``prompt_version``, issue #59). ``"v0.1"`` is the prompt the
published results used, kept byte for byte. ``"v0.2"`` (the default) follows the
paper's main prompt and upstream's current one on delegation:

* It encourages sub-calls instead of warning against them. The paper's main prompt
  (arXiv 2512.24601, App. C.1 (1a)) says sub-LLMs are "strongly encouraged to use as
  much as possible" and "don't be afraid to put a lot of context into them". Its
  "IMPORTANT: Be very careful about using `llm_query`" line ((1b), (1d)) was added
  because Qwen3-Coder made "thousands of LM subcalls for basic tasks" (App. C).
  Our models under-call: 7 of 40 rlm rows in the #22 re-run made any sub-call.
  The hard caps stay, stated as facts.
* It adds upstream's "act as an orchestrator, not a solver" addendum, lightly
  adapted (``ORCHESTRATOR_V02`` below, with its license notice).
* It adds a chained example (a running buffer carried from call to call, the
  paper's book example) and a map-then-aggregate example.
* It advertises a per-call size derived from the sub model's window
  (``RLMConfig.effective_subcall_chars``), not a fixed 12K.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_MAX_CHUNKS_SHOWN = 10
PROMPT_VERSIONS = ("v0.1", "v0.2")
DEFAULT_SUBCALL_CHARS = 12_000  # v0.1's fixed per-call size hint


@dataclass(frozen=True)
class PromptSettings:
    """The knobs the prompt reads. ``RLMConfig`` carries the same names."""

    subcall_chars: int = DEFAULT_SUBCALL_CHARS
    max_depth: int = 1
    concurrency: int = 1
    prompt_version: str = "v0.2"
    max_subcalls_per_run: int = 64
    max_subcalls_per_exec: int = 24


def subcall_chars_of(settings: object) -> int:
    """The per-call size the prompt advertises: ``RLMConfig.effective_subcall_chars``
    when present, else a plain ``subcall_chars`` attribute, else 12,000."""
    effective = getattr(settings, "effective_subcall_chars", None)
    if effective is not None:
        return int(effective)
    value = getattr(settings, "subcall_chars", None)
    return int(value) if value is not None else DEFAULT_SUBCALL_CHARS


def prompt_version_of(settings: object) -> str:
    version = str(getattr(settings, "prompt_version", "v0.2"))
    if version not in PROMPT_VERSIONS:
        raise ValueError(f"prompt_version must be one of {', '.join(PROMPT_VERSIONS)}")
    return version


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


def _tools_section(subcall_chars: int, recursive: bool, version: str = "v0.1") -> str:
    size = (
        f"Keep each prompt under about {subcall_chars:,} characters."
        if version == "v0.1"
        else f"One call can read about {subcall_chars:,} characters."
    )
    lines = [
        "## Tools inside the REPL",
        "",
        "- `context`: the data to answer about. It is already loaded; never try to "
        "print all of it.",
        "- `llm_query(prompt: str) -> str`: ask a fresh language model one question. "
        "It sees only `prompt`, nothing from this conversation, so put the relevant "
        f"text in the prompt. {size}",
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


# --- v0.2 (issue #59) ---------------------------------------------------------


def _subcalls_section_v02(
    subcall_chars: int, context_chars: int, concurrency: int, per_exec: int, per_run: int
) -> str:
    """Encouragement in place of v0.1's "sub-calls are expensive" (App. C.1 (1a)),
    then the hard caps as plain facts."""
    pace = "one call at a time" if concurrency <= 1 else f"up to {concurrency} calls at a time"
    fits = (
        f" The whole `context` ({context_chars:,} characters) fits in a single call."
        if 0 < context_chars <= subcall_chars
        else ""
    )
    return (
        "## Sub-calls\n"
        "\n"
        "A sub-call reads and interprets text; keyword search and regex can only match "
        f"it. Each call can read about {subcall_chars:,} characters, so don't be afraid to "
        "put a lot of context into one call: a whole section, or many records at once, "
        "rather than one record per call. Analyze your data and see if it is sufficient "
        f"to just fit it in a few sub-LLM calls.{fits}\n"
        "\n"
        f"Hard limits, for planning: sub-calls run {pace}, with at most {per_exec} per "
        f"code block and {per_run} per run."
    )


# The paragraphs below are adapted from ``ORCHESTRATOR_ADDENDUM`` in
# alexzhang13/rlm ``rlm/utils/prompts.py`` (main, commit d04208a; added in de762b9,
# 2026-05-24, and on by default via ``build_rlm_system_prompt(orchestrator=True)``).
# Edits: the finishing step names no specific mechanism (we accept FINAL, FINAL_VAR,
# the answer dict or final_answer); sub-LLMs see "the prompt you pass them" (our
# llm_query has no context argument); upstream's fixed "~100K characters per prompt"
# and "~20 prompts per batch" ceilings become this run's per-call size and per-run cap.
#
#     alexzhang13/rlm, MIT License
#     Copyright (c) 2026 Alex Zhang
#
#     Permission is hereby granted, free of charge, to any person obtaining a copy
#     of this software and associated documentation files (the "Software"), to deal
#     in the Software without restriction, including without limitation the rights
#     to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
#     copies of the Software, and to permit persons to whom the Software is
#     furnished to do so, subject to the following conditions:
#
#     The above copyright notice and this permission notice shall be included in all
#     copies or substantial portions of the Software.
#
#     THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
#     IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
#     FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
#     AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
#     LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
#     OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
#     SOFTWARE.
def _orchestrator_section_v02(per_run: int) -> str:
    return "\n\n".join(
        [
            "## Work as an orchestrator, not a solver",
            (
                "Directly after you probe `context` and understand your task, pause and "
                "plan: state explicitly how the task decomposes into sub-LLM / REPL steps, "
                "and sketch the concrete sequence of turns (what each turn computes and "
                "which sub-LLM call, if any, it issues) before you execute them. Then "
                "execute one turn at a time: after each step print a small sample of the "
                "result, verify it looks right, and only finish once you have actually "
                "printed the candidate answer. If you are running out of turns without a "
                "confirmed answer, submit your best inference rather than letting the run "
                "end unsubmitted."
            ),
            (
                "Push every long-context operation that would not fit comfortably in your "
                "own working window (reading, summarizing, classifying, verifying, "
                "answering sub-questions, even recapping your own progress) into "
                "`llm_query` / `llm_query_batched` calls instead of pulling that text into "
                "your own messages. (Conversely: if a Python keyword / regex search over "
                "`context` would already pin the answer, or if a single visible passage "
                "already contains it, just read it directly; sub-LLMs are for when the raw "
                "text won't fit or the question needs semantic interpretation.) Long REPL "
                "output pollutes your history the same way raw `context` does: if you want "
                "a recap, ask `llm_query` for a 1-2 sentence summary and print only that. "
                "Aggregate the small results back in the REPL."
            ),
            (
                "Sub-LLMs have no REPL; they only see the prompt you pass them. Hand them "
                "clean, focused inputs and ask for terse, structured outputs you can "
                "manipulate programmatically."
            ),
            (
                "Pack each prompt close to the per-call size above (a chunk of many items, "
                "a whole document) so one call accomplishes a lot of work; tiny one-item "
                "prompts are the anti-pattern. When the work can be expressed either as a "
                "sequential loop of `llm_query`s or as one `llm_query_batched` call, prefer "
                "batched: same total work, fewer turns. If the work would need more than "
                f"{per_run} calls, filter in Python first to a tractable subset, or stage "
                "it: a coarse pass narrows candidates, then a targeted second pass extracts "
                "from the survivors."
            ),
            (
                "Reserve your own tokens for high-level decisions: what to ask next, how to "
                "combine sub-LLM outputs, when to finalize. Delegate everything else."
            ),
        ]
    )


def _examples_section_v02(subcall_chars: int, recursive: bool = False) -> str:
    """Three strategies: one big call, map then aggregate, and a running buffer (the
    paper's book example, App. C.1 (1a), with its undefined ``buffers`` fixed)."""
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
    return (
        "## Ways to decompose\n"
        "\n"
        "One call, when the data fits in a single sub-call:\n"
        "\n"
        "```repl\n"
        "reply = llm_query(f'Using only this document, when is the launch date? Quote the "
        "line.\\n\\n{context}')\n"
        "print(reply[:500])\n"
        "```\n"
        "\n"
        "Map over chunks, then aggregate the per-chunk answers with one more call:\n"
        "\n"
        "```repl\n"
        f"size = {subcall_chars}\n"
        "chunks = [context[i : i + size] for i in range(0, len(context), size)]\n"
        "question = 'How many tickets ask for a refund?'\n"
        "per_chunk = llm_query_batched([f'{question} Give a number and one line of "
        "evidence.\\n\\n{c}' for c in chunks])\n"
        "parts = '\\n'.join(f'Part {i}: {a}' for i, a in enumerate(per_chunk))\n"
        "total = llm_query(f'{question}\\nThese are answers for {len(chunks)} parts of the "
        "data. Combine them into one final answer.\\n\\n{parts}')\n"
        "print(total)\n"
        "```\n"
        "\n"
        "Carry a running buffer, when later parts can change what earlier parts said:\n"
        "\n"
        "```repl\n"
        "import re\n"
        "sections = re.split(r'(?m)^## ', context)[1:]\n"
        "question = 'Who owns the Atlas project at the end, after all transfers?'\n"
        "notes = 'nothing yet'\n"
        "for i, s in enumerate(sections):\n"
        "    notes = llm_query(f'You are reading section {i + 1} of {len(sections)} in "
        "order. Question: {question}\\nNotes so far: {notes}\\nUpdate the notes with "
        "anything here that bears on the question. Keep them short.\\n\\n{s}')\n"
        "print(notes[:500])\n"
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
    subcall_chars = subcall_chars_of(settings)
    max_depth = int(getattr(settings, "max_depth", 1))
    concurrency = int(getattr(settings, "concurrency", 1))
    version = prompt_version_of(settings)
    recursive = max_depth > 1

    intro = (
        "You answer a question about data that is far too large to read at once. The "
        "data lives in a Python REPL as the variable `context`; you never see it "
        "directly. You work in turns: each turn you write one block of Python, the REPL "
        "runs it and shows you the output, and you decide the next step. Variables "
        "persist between turns. " + _ask_line(version) + "\n"
        "\n"
        "Your own context window is small. Treat it as a scratchpad for decisions, and "
        "keep the data and the intermediate results in REPL variables."
    )

    if version == "v0.1":
        parts = [
            intro,
            "## The data",
            context_meta.render(),
            _tools_section(subcall_chars, recursive),
            _batching_section(subcall_chars, concurrency),
            _examples_section(subcall_chars, recursive),
            _rules_section(),
        ]
    else:
        parts = [
            intro,
            "## The data",
            context_meta.render(),
            _tools_section(subcall_chars, recursive, version),
            _v02_subcalls(settings, subcall_chars, context_meta, concurrency),
            _orchestrator_section_v02(_caps(settings)[1]),
            _examples_section_v02(subcall_chars, recursive),
            _rules_section(),
        ]
    return "\n\n".join(parts) + "\n"


def _ask_line(version: str) -> str:
    if version == "v0.1":
        return (
            "Inside the REPL you can ask a separate language model to read a piece of "
            "the data for you."
        )
    # App. C.1 (1a): "... recursively query sub-LLMs, which you are strongly
    # encouraged to use as much as possible."
    return (
        "Inside the REPL you can ask separate language models (sub-LLMs) to read the "
        "data for you, and you are strongly encouraged to use them as much as possible."
    )


def _caps(settings: object) -> tuple[int, int]:
    """(per code block, per run) sub-call caps."""
    return (
        int(getattr(settings, "max_subcalls_per_exec", 24)),
        int(getattr(settings, "max_subcalls_per_run", 64)),
    )


def _v02_subcalls(
    settings: object, subcall_chars: int, context_meta: ContextMeta, concurrency: int
) -> str:
    per_exec, per_run = _caps(settings)
    return _subcalls_section_v02(
        subcall_chars, context_meta.total_chars, concurrency, per_exec, per_run
    )


def turn_prompt(i: int, n: int, first: bool = False, protocol: str = "fence") -> str:
    """The short user message that opens each turn (stored, so the prefix is reused)."""
    line = f"Turn {i}/{n}."
    if first:
        how = "one execute_python call" if protocol == "tools" else "one code block"
        line += (
            f" Start by inspecting `context` (type, length, a short slice) in {how}. "
            "Do not answer yet."
        )
    return line


def decompose_nudge(version: str = "v0.1", context_chars: int = 0, subcall_chars: int = 0) -> str:
    """Sent when one sub-call got nearly the whole context and the context is larger
    than one call can read (the loop never sends it when the context fits)."""
    if version == "v0.1":
        return (
            "Your last code handed nearly the whole context to a single sub-call. That "
            "defeats the purpose: the sub-model has the same limits you do. Split the "
            "context into pieces and ask about each piece, then combine the results in "
            "a variable."
        )
    return (
        f"Your last code handed nearly the whole context ({context_chars:,} characters) "
        f"to a single sub-call, more than one call can read (about {subcall_chars:,} "
        "characters). Split the context into pieces of up to that size, ask about each "
        "piece, then combine the results, with one more sub-call if needed."
    )


def reverify_nudge(var: str, protocol: str = "fence") -> str:
    how = (
        f'Call `final_answer(variable="{var}")`'
        if protocol == "tools"
        else f"Reply with `FINAL_VAR({var})`"
    )
    return (
        f"You already computed the answer; it is in `{var}` and the last two turns "
        f"repeated the same check. Stop verifying. {how}."
    )


def final_rejection(reason: str, protocol: str = "fence") -> str:
    if protocol == "tools":
        return (
            f"final_answer was not accepted: {reason} Continue working, and call "
            "final_answer only when the answer itself is ready, in a turn with no "
            "execute_python call."
        )
    return (
        f"That FINAL was not accepted: {reason} Continue working, and send FINAL or "
        "FINAL_VAR only when the answer itself is ready, in a message with no code."
    )


def forced_final_prompt(why: str = "turns", protocol: str = "fence") -> str:
    """``why`` is "turns", "time", "errors" (``max_errors`` failed runs in a row) or
    "context" (the request cannot fit the window, issue #49)."""
    leads = {
        "errors": "Your code has failed too many times in a row, so the run stops here.",
        "context": "The conversation no longer fits the context window, so the run stops here.",
    }
    lead = leads.get(why, f"You are out of {why}.")
    if protocol == "tools":
        return (
            f"{lead} Call final_answer now with your best answer, or with "
            "`variable` set to the name of a variable that already holds it. No "
            "execute_python."
        )
    return (
        f"{lead} Reply now with your best answer as `FINAL(<answer>)`, "
        "or `FINAL_VAR(<name>)` if a variable already holds it. No code."
    )


FORCED_VALUE_CHARS = 300
FORCED_OUTPUT_CHARS = 500


def _clip(text: str, limit: int, *, tail: bool = False) -> str:
    if len(text) <= limit:
        return text
    if tail:
        return f"[... {len(text) - limit} chars cut]{text[-limit:]}"
    return f"{text[:limit]}[... {len(text) - limit} chars cut]"


def forced_final_state(values: list[tuple[str, str]], last_output: str | None) -> str:
    """What the REPL holds right now, shown before the forced-finish request.

    ``values`` are ``(name, value)`` pairs: ``answer['content']`` and any of the
    usual answer variable names that exist. The model sees them so it can point
    at one with ``FINAL_VAR`` instead of the loop guessing which one is current.
    Returns "" when there is nothing to show.
    """
    parts: list[str] = []
    if values:
        lines = [f"Current values in the REPL (each cut to {FORCED_VALUE_CHARS} chars):"]
        for name, value in values:
            lines.append(f"- {name} = {_clip(value, FORCED_VALUE_CHARS)}")
        parts.append("\n".join(lines))
    if last_output and last_output.strip():
        parts.append(
            "Last REPL output (end):\n" + _clip(last_output.strip(), FORCED_OUTPUT_CHARS, tail=True)
        )
    return "\n\n".join(parts)


def no_action_prompt(protocol: str = "fence") -> str:
    if protocol == "tools":
        return (
            "That message called no tool. Call execute_python to run code, or "
            "final_answer when the answer is ready. Text outside a tool call is not "
            "run and is not taken as the answer."
        )
    return (
        "That message had no code and no final answer. Reply with exactly one ```repl code "
        "block, or FINAL(...) / FINAL_VAR(...) when the answer is ready."
    )


def fence_slip_note() -> str:
    """Tools protocol: the model wrote a fenced block instead of calling execute_python."""
    return (
        "[note] Your message had a fenced code block instead of an execute_python call. "
        "It was run this once; its output is above. Use the execute_python tool from now on."
    )


# --- tools protocol (issue #20) ----------------------------------------------


def tool_specs(output_truncate_chars: int = 2_000) -> list[dict[str, Any]]:
    """The two functions offered to the root model, in OpenAI ``tools`` format."""
    return [
        {
            "type": "function",
            "function": {
                "name": "execute_python",
                "description": (
                    "Run Python code in the persistent REPL that holds `context`, "
                    "`llm_query`, `llm_query_batched` and every variable you created. "
                    "Returns what the code printed (stdout, stderr, then any error), cut "
                    f"to about {output_truncate_chars:,} characters. Print short summaries "
                    "and keep results in variables."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "code": {"type": "string", "description": "Python source to run."}
                    },
                    "required": ["code"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "final_answer",
                "description": (
                    "Finish with the answer. Give exactly one of `answer` (the answer "
                    "text itself) or `variable` (the name of a REPL variable that already "
                    "holds the answer). Do not call it in the same turn as execute_python."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "answer": {"type": "string", "description": "The final answer text."},
                        "variable": {
                            "type": "string",
                            "description": "Name of a REPL variable holding the answer.",
                        },
                    },
                },
            },
        },
    ]


_FENCED = re.compile(r"```repl\n(.*?)```", re.DOTALL)


def _as_tool_examples(text: str) -> str:
    """Rewrite ```repl examples as indented execute_python code, so the tools prompt
    shows no fences to imitate."""

    def sub(m: re.Match[str]) -> str:
        lines = m.group(1).rstrip("\n").split("\n")
        body = "\n".join(f"    {line}" if line else "" for line in lines)
        return f"execute_python with code:\n\n{body}"

    return _FENCED.sub(sub, text)


def _tools_protocol_section(subcall_chars: int, recursive: bool, version: str = "v0.1") -> str:
    section = _tools_section(subcall_chars, recursive, version)
    return section.replace(
        "to finish, as an alternative to FINAL / FINAL_VAR below.",
        "to finish, as an alternative to calling final_answer.",
    ).replace("## Tools inside the REPL", "## Names inside the REPL")


def _tools_rules_section() -> str:
    return (
        "## Rules\n"
        "\n"
        "1. Look before you compute. On your first turn, inspect `context` (type, "
        "length, a short slice) so your plan matches the data.\n"
        "2. Keep results in variables. Print only short summaries: counts, a few "
        "lines, the first few hundred characters. Long output is truncated and "
        "wastes your window.\n"
        "3. Act only through tool calls. Make one execute_python call per turn and wait "
        "for its output before deciding the next step. Never write code in the message "
        "text; it is not run.\n"
        "4. Finish only when the answer exists: call final_answer with `answer` set to "
        "the answer text, or with `variable` set to the name of a variable you already "
        "created that holds it. Never both, and never in the same turn as execute_python. "
        'Or set `answer["content"]` and `answer["ready"] = True` in code.\n'
        "5. final_answer must contain the answer, not a plan, not a description of what "
        "you will do, and not a repeat of an earlier check. If the answer is already in "
        "a variable, pass that variable's name."
    )


def build_tools_system_prompt(settings: PromptSettings | object, context_meta: ContextMeta) -> str:
    """The system prompt for ``protocol="tools"``: same guidance, tools instead of fences."""
    subcall_chars = subcall_chars_of(settings)
    max_depth = int(getattr(settings, "max_depth", 1))
    concurrency = int(getattr(settings, "concurrency", 1))
    version = prompt_version_of(settings)
    recursive = max_depth > 1

    intro = (
        "You answer a question about data that is far too large to read at once. The "
        "data lives in a Python REPL as the variable `context`; you never see it "
        "directly. You have two tools. `execute_python(code)` runs code in that REPL and "
        "returns its printed output. `final_answer(answer=... | variable=...)` ends the "
        "task. You work in turns: each turn you call execute_python once, read the "
        "output, and decide the next step. Variables persist between turns. "
        + _ask_line(version)
        + "\n"
        "\n"
        "Your own context window is small. Treat it as a scratchpad for decisions, and "
        "keep the data and the intermediate results in REPL variables."
    )
    if version == "v0.1":
        parts = [
            intro,
            "## The data",
            context_meta.render(),
            _tools_protocol_section(subcall_chars, recursive),
            _batching_section(subcall_chars, concurrency),
            _as_tool_examples(_examples_section(subcall_chars, recursive)),
            _tools_rules_section(),
        ]
    else:
        parts = [
            intro,
            "## The data",
            context_meta.render(),
            _tools_protocol_section(subcall_chars, recursive, version),
            _v02_subcalls(settings, subcall_chars, context_meta, concurrency),
            _orchestrator_section_v02(_caps(settings)[1]),
            _as_tool_examples(_examples_section_v02(subcall_chars, recursive)),
            _tools_rules_section(),
        ]
    return "\n\n".join(parts) + "\n"


__all__ = [
    "PROMPT_VERSIONS",
    "ContextMeta",
    "PromptSettings",
    "build_system_prompt",
    "build_tools_system_prompt",
    "decompose_nudge",
    "fence_slip_note",
    "no_action_prompt",
    "tool_specs",
    "final_rejection",
    "forced_final_prompt",
    "reverify_nudge",
    "subcall_chars_of",
    "turn_prompt",
]
