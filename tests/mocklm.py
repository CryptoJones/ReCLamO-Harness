"""A scripted stand-in for LMClient used by the loop tests."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from reclamo.client import Completion, Usage

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
    ) -> Completion:
        msgs = [dict(m) for m in messages]
        self.calls.append({"role": role, "messages": msgs, "enable_thinking": enable_thinking})
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
        return "\n".join(m["content"] for c in self.calls for m in c["messages"])
