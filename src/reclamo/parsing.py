"""Extract code blocks and final-answer candidates from a model turn.

This module is text-only. It never looks at the REPL namespace: per epic #8
decision 9, resolving ``FINAL(x)`` against a variable named ``x`` is the loop's
job (``rlm.py``). Here we only find candidates and describe them.

Qwen quirks handled here:

* it writes ```` ```python ```` fences as often as ```` ```repl ````;
* its thinking can contain literal ``FINAL(`` text that must be ignored;
* it sometimes emits ``FINAL(...)`` in the same turn as code it has not run;
* it sometimes answers with its plan instead of the answer.

Other models' quirks:

* Poolside Laguna (issue #48) writes code in its native tool-call syntax as plain
  text, ``<tool_call>repl\n<code></arg_value></tool_call>``, with the closing tags
  varying (``</arg_value>``, ``</value>``, ``</repl>``, ``</tool_call>``, a stray
  ``</think>``, or none at all) and sometimes a trailing ``description`` argument.
  It can also write several such blocks in one reply with *invented* REPL output
  between them, so when a reply's first code is a ``<tool_call>`` only that block
  counts and everything after it is discarded. ``<tool_call>FINAL(...)`` is read
  as ``FINAL(...)``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

FinalKind = Literal["FINAL", "FINAL_VAR"]

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)
_THINK_OPEN = re.compile(r"<think>.*\Z", re.DOTALL)
_FENCE_LANGS = {"repl", "python"}
_FENCE = re.compile(
    r"^[ \t]*```[ \t]*(?P<lang>[A-Za-z0-9_+-]*)[ \t]*\r?\n"
    r"(?P<body>.*?)"
    r"^[ \t]*```[ \t]*$",
    re.DOTALL | re.MULTILINE,
)
# A candidate must start its line. Qwen writes "...then I'll call FINAL(answer)"
# mid-sentence while planning, and that is not an answer. Light markdown
# wrappers before the keyword are allowed: bold/code marks, a blockquote or
# list marker, or a heading hash.
_FINAL_HEAD = re.compile(
    r"^[ \t]*(?:(?:\*\*|__|`|>|[-*+]|#+|\d+[.)])[ \t]*)*(?P<kind>FINAL_VAR|FINAL)\s*\(",
    re.MULTILINE,
)
_QUOTES = ("'", '"')

# Laguna's text-form tool call (#48). The code starts on the line after the name and
# runs to the first terminator (or the end of the text). A new <tool_call> also ends
# it, so two blocks with no closing tags between them stay two blocks.
_TOOL_CALL_LANGS = ("repl", "python", "execute_python")
_TOOL_CALL_OPEN = re.compile(
    r"<tool_call>[ \t]*(?P<name>" + "|".join(_TOOL_CALL_LANGS) + r")[ \t]*\r?\n"
)
_TOOL_CALL_END = re.compile(r"</arg_value>|</value>|</repl>|</tool_call>|</think>|(?=<tool_call>)")
# A GLM-style wrapper before the code (not seen from Laguna, but cheap to accept).
_TOOL_CALL_ARG_PREFIX = re.compile(r"\A\s*<arg_key>[^<]*</arg_key>\s*<arg_value>")
# What may follow the terminator and still belong to the call: trailing arguments
# (Laguna adds a "description") and the closing tag.
_TOOL_CALL_TAIL = re.compile(
    r"(?:\s*<arg_key>[^<]*</arg_key>\s*<arg_value>.*?</arg_value>)*(?:\s*</tool_call>)?",
    re.DOTALL,
)
# <tool_call>FINAL(...) / <tool_call>FINAL_VAR(...): read as a line-start FINAL.
_TOOL_CALL_FINAL = re.compile(r"<tool_call>(?=[ \t]*FINAL(?:_VAR)?\s*\()")
_TOOL_CALL_LEFTOVER = re.compile(r"<tool_call>.*?(?:</tool_call>|\Z)", re.DOTALL)
_STRAY_THINK_CLOSE = re.compile(r"</think>")

_PLAN_OPENERS = (
    "i will ",
    "i'll ",
    "i’ll ",
    "let me ",
    "let's ",
    "first, ",
    "first i ",
    "step 1",
    "plan:",
    "my plan",
    "next, i",
    "we need to ",
    "i need to ",
    "i should ",
)
_STEP_WORDS = re.compile(r"\bstep\s*[12]\b", re.IGNORECASE)


@dataclass(frozen=True)
class FinalCandidate:
    """A ``FINAL(...)`` or ``FINAL_VAR(...)`` found outside code and thinking.

    ``value`` is the raw text inside the parentheses, outer whitespace stripped.
    ``has_code`` is true when the same turn also contains a code block (which the
    loop should treat as "not finished yet"). ``looks_like_plan`` flags a value
    that reads as intentions rather than an answer.
    """

    kind: FinalKind
    value: str
    has_code: bool
    looks_like_plan: bool


def strip_think(text: str) -> str:
    """Remove ``<think>…</think>`` blocks and normalise CRLF to LF.

    An opening tag with no closing tag swallows everything after it: Qwen
    occasionally returns thinking that was cut off by the output cap, and
    nothing in there is a real action.
    """
    text = _THINK_BLOCK.sub("", text.replace("\r\n", "\n"))
    return _THINK_OPEN.sub("", text)


@dataclass(frozen=True)
class _Block:
    """One fenced block or text-form tool call: its span, and its code (None if not code)."""

    start: int
    end: int
    code: str | None
    tool_call: bool


def _fence_code(m: re.Match[str], langs: set[str]) -> str | None:
    if m.group("lang").lower() not in langs:
        return None
    body = m.group("body")
    return body[:-1] if body.endswith("\n") else body


def _tool_call_block(text: str, m: re.Match[str]) -> _Block:
    body_start = m.end()
    end = _TOOL_CALL_END.search(text, body_start)
    body_end = end.start() if end else len(text)
    stop = end.end() if end else len(text)
    tail = _TOOL_CALL_TAIL.match(text, stop)
    if tail:
        stop = tail.end()
    code = _TOOL_CALL_ARG_PREFIX.sub("", text[body_start:body_end]).rstrip()
    return _Block(m.start(), stop, code, tool_call=True)


def _scan(text: str) -> tuple[str, list[_Block]]:
    """Find fences and text-form tool calls in document order (thinking already removed).

    Returns the text that counts and its blocks. When the first block that holds
    code is a ``<tool_call>``, the text is cut right after it: Laguna follows such a
    block with invented REPL output (often in a ```repl fence) and more calls built
    on it, none of which may run or be read as an answer.
    """
    blocks: list[_Block] = []
    pos = 0
    while True:
        fm = _FENCE.search(text, pos)
        tm = _TOOL_CALL_OPEN.search(text, pos)
        if fm is None and tm is None:
            break
        if fm is not None and (tm is None or fm.start() < tm.start()):
            blocks.append(_Block(fm.start(), fm.end(), _fence_code(fm, _FENCE_LANGS), False))
            pos = fm.end()
        else:
            assert tm is not None
            block = _tool_call_block(text, tm)
            blocks.append(block)
            pos = block.end
    first = next((b for b in blocks if b.code is not None), None)
    if first is not None and first.tool_call:
        return text[: first.end], [b for b in blocks if b.end <= first.end]
    return text, blocks


def find_code_blocks(text: str, strict: bool = False) -> list[str]:
    """Return the code of ```` ```repl ````/```` ```python ```` fences and ``<tool_call>`` blocks.

    Blocks inside ``<think>`` are ignored. Bodies keep their internal newlines;
    a single trailing newline is dropped. Order is document order, except that a
    reply whose first code is a ``<tool_call>`` yields only that block (``_scan``).

    ``strict`` keeps only ```` ```repl ```` fences: the upstream rlm protocol, with
    no ``python`` fences and no text-form tool calls.
    """
    visible = strip_think(text)
    if strict:
        found = (_fence_code(m, {"repl"}) for m in _FENCE.finditer(visible))
        return [c for c in found if c is not None]
    _, blocks = _scan(visible)
    return [b.code for b in blocks if b.code is not None]


_FENCE_OPEN_TAIL = re.compile(r"^[ \t]*```.*\Z", re.DOTALL | re.MULTILINE)


def strip_code(text: str) -> str:
    """Remove thinking and every code block (any language, closed or cut off).

    That covers fences and text-form ``<tool_call>`` blocks, and whatever a leading
    ``<tool_call>`` block makes us discard (``_scan``). What is left is the prose of
    the reply, stripped. Used by the forced finish so a reply that is a code block
    is never taken as the answer.
    """
    visible, blocks = _scan(strip_think(text))
    for b in reversed(blocks):
        visible = visible[: b.start] + visible[b.end :]
    visible = _TOOL_CALL_LEFTOVER.sub("", visible)
    visible = _STRAY_THINK_CLOSE.sub("", visible)
    return _FENCE_OPEN_TAIL.sub("", visible).strip()


def _blank_blocks(text: str, blocks: list[_Block]) -> str:
    """Replace every block (any fence, or a tool call) with spaces of the same length.

    Keeping the length means match offsets stay comparable, which matters for
    "last occurrence wins". A ``<tool_call>`` right before ``FINAL(`` becomes a
    newline plus spaces, so the candidate starts its own line.
    """
    for b in blocks:
        text = text[: b.start] + " " * (b.end - b.start) + text[b.end :]
    return _TOOL_CALL_FINAL.sub(lambda m: "\n" + " " * (len(m.group(0)) - 1), text)


def _balanced_span(text: str, open_idx: int) -> int | None:
    """Return the index of the ``)`` matching the ``(`` at ``open_idx``.

    Parentheses inside single or double quotes are not counted, so
    ``FINAL("f(x)")`` extracts cleanly. Prose apostrophes (``It's``) open a
    "quote" that never closes, so if the quote-aware scan finds no match we
    retry counting parentheses only. Returns None when still unbalanced.
    """
    close = _scan_parens(text, open_idx, quotes=True)
    return close if close is not None else _scan_parens(text, open_idx, quotes=False)


def _scan_parens(text: str, open_idx: int, quotes: bool) -> int | None:
    depth = 0
    quote: str | None = None
    i = open_idx
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
        elif quotes and ch in _QUOTES:
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None


def looks_like_plan(s: str) -> bool:
    """Heuristic: does this read as a plan of action instead of an answer?"""
    lowered = s.strip().lower()
    if not lowered:
        return False
    if lowered.startswith(_PLAN_OPENERS):
        return True
    return len(_STEP_WORDS.findall(lowered)) >= 2


def find_final(text: str) -> FinalCandidate | None:
    """Find the last ``FINAL(...)`` / ``FINAL_VAR(...)`` outside code and thinking.

    ``<tool_call>FINAL(...)`` counts too. Text discarded after a leading
    ``<tool_call>`` code block (``_scan``) is never searched.

    Returns None when there is none, or when the only occurrences are unbalanced.
    """
    visible, blocks = _scan(strip_think(text))
    has_code = any(b.code is not None for b in blocks)
    prose = _blank_blocks(visible, blocks)

    best: tuple[int, FinalKind, str] | None = None
    for m in _FINAL_HEAD.finditer(prose):
        open_idx = m.end() - 1
        close_idx = _balanced_span(prose, open_idx)
        if close_idx is None:
            continue
        value = prose[open_idx + 1 : close_idx].strip()
        kind: FinalKind = "FINAL_VAR" if m.group("kind") == "FINAL_VAR" else "FINAL"
        best = (m.start(), kind, value)

    if best is None:
        return None
    _, kind, value = best
    return FinalCandidate(
        kind=kind,
        value=value,
        has_code=has_code,
        looks_like_plan=kind == "FINAL" and looks_like_plan(value),
    )


__all__ = [
    "FinalCandidate",
    "FinalKind",
    "find_code_blocks",
    "find_final",
    "looks_like_plan",
    "strip_code",
    "strip_think",
]
