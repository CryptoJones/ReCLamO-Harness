"""A scripted stand-in for LMClient used by the loop tests."""

from __future__ import annotations

import itertools
import json
from collections.abc import Callable
from typing import Any

from reclamo.client import Completion, ToolCall, Usage

SECRET_REASONING = "secret reasoning that must never reach the history"


def completion(content: str, *, role: str = "root", finish_reason: str = "stop") -> Completion:
    return Completion(
        content=content,
        reasoning=SECRET_REASONING if role == "root" else None,
        usage=Usage(10, 5, 15),
        finish_reason=finish_reason,
        latency=0.0,
        model="mock",
        role=role,
    )


_ids = itertools.count(1)


def call(name: str, arguments: str | None = None, /, **args: Any) -> ToolCall:
    """One scripted tool call. Pass raw ``arguments`` text to script malformed JSON."""
    raw = arguments if arguments is not None else json.dumps(args)
    return ToolCall(id=f"call_{next(_ids)}", name=name, arguments=raw)


def tool_turn(*calls: ToolCall, content: str = "", finish_reason: str = "tool_calls") -> Completion:
    """A root turn that makes ``calls`` (and optionally says ``content``)."""
    c = completion(content, finish_reason=finish_reason)
    c.tool_calls = list(calls) or None
    return c


class MockLM:
    """``root`` is a queue of scripted responses; ``sub`` answers sub-calls."""

    def __init__(
        self,
        root: list[str | Completion],
        sub: list[str] | Callable[[str], str] | None = None,
    ) -> None:
        self.root = list(root)
        self.sub = sub
        self.calls: list[dict[str, Any]] = []

    def complete(
        self,
        messages: Any,
        role: str = "root",
        *,
        enable_thinking: bool | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        timeout: float | None = None,
        retry: bool = True,
    ) -> Completion:
        msgs = [dict(m) for m in messages]
        self.calls.append(
            {
                "role": role,
                "messages": msgs,
                "enable_thinking": enable_thinking,
                "tools": tools,
                "timeout": timeout,
                "retry": retry,
            }
        )
        if role == "root":
            if not self.root:
                raise AssertionError("MockLM: root script exhausted")
            item = self.root.pop(0)
            return item if isinstance(item, Completion) else completion(item)
        prompt = msgs[-1]["content"]
        if isinstance(self.sub, list):
            answer = self.sub.pop(0)
        elif callable(self.sub):
            answer = self.sub(prompt)
        else:
            answer = f"sub:{prompt[:40]}"
        return completion(answer, role="sub")

    @property
    def root_calls(self) -> list[dict[str, Any]]:
        return [c for c in self.calls if c["role"] == "root"]

    @property
    def sub_calls(self) -> list[dict[str, Any]]:
        return [c for c in self.calls if c["role"] == "sub"]

    def all_message_text(self) -> str:
        parts: list[str] = []
        for c in self.calls:
            for m in c["messages"]:
                parts.append(m.get("content") or "")
                if m.get("tool_calls"):
                    parts.append(json.dumps(m["tool_calls"]))
        return "\n".join(parts)
