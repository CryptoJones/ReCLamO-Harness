"""Extract code blocks and final-answer candidates from a model turn.

This module is text-only. It never looks at the REPL namespace: per epic #8
decision 9, resolving ``FINAL(x)`` against a variable named ``x`` is the loop's
job (``rlm.py``). Here we only find candidates and describe them.

Qwen quirks handled here:

* it writes ```` ```python ```` fences as often as ```` ```repl ````;
* its thinking can contain literal ``FINAL(`` text that must be ignored;
* it sometimes emits ``FINAL(...)`` in the same turn as code it has not run;
* it sometimes answers with its plan instead of the answer.
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


def find_code_blocks(text: str, strict: bool = False) -> list[str]:
    """Return the bodies of ```` ```repl ```` (and, unless strict, ```` ```python ````) fences.

    Blocks inside ``<think>`` are ignored. Bodies keep their internal newlines;
    a single trailing newline is dropped.
    """
    langs = {"repl"} if strict else _FENCE_LANGS
    blocks: list[str] = []
    for m in _FENCE.finditer(strip_think(text)):
        if m.group("lang").lower() in langs:
            body = m.group("body")
            blocks.append(body[:-1] if body.endswith("\n") else body)
    return blocks


_FENCE_OPEN_TAIL = re.compile(r"^[ \t]*```.*\Z", re.DOTALL | re.MULTILINE)


def strip_code(text: str) -> str:
    """Remove thinking and every fenced block (any language, closed or cut off).

    What is left is the prose of the reply, stripped. Used by the forced finish
    so a reply that is a code block is never taken as the answer.
    """
    visible = _FENCE.sub("", strip_think(text))
    return _FENCE_OPEN_TAIL.sub("", visible).strip()


def _blank_fences(text: str) -> str:
    """Replace every fenced block (any language) with whitespace of the same length.

    Keeping the length means match offsets stay comparable, which matters for
    "last occurrence wins".
    """
    return _FENCE.sub(lambda m: " " * len(m.group(0)), text)


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

    Returns None when there is none, or when the only occurrences are unbalanced.
    """
    visible = strip_think(text)
    has_code = bool(find_code_blocks(visible))
    prose = _blank_fences(visible)

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
