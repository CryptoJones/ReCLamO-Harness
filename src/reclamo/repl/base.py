"""The REPL interface the loop talks to, and its result types."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Protocol


class LLMHandler(Protocol):
    """``(kind, prompts[, contexts]) -> answers``, one answer per prompt.

    ``kind`` is "llm_query", "llm_query_batched" or "rlm_query". ``contexts``
    is only passed for ``rlm_query(question, data)``: one data object per
    prompt, which becomes the nested RLM's own ``context``. The handler may
    raise; the REPL turns that into an exception inside the model's code.
    """

    def __call__(
        self, kind: str, prompts: list[str], contexts: list[Any] | None = None, /
    ) -> list[str]: ...


@dataclass
class ExecResult:
    stdout: str = ""
    stderr: str = ""
    error: str | None = None
    truncated_chars: int = 0
    answer: dict[str, Any] | None = None  # {"ready": bool, "content": str | None}
    vars: list[str] = field(default_factory=list)
    subcalls: int = 0
    restarted: bool = False  # the worker died or timed out and was relaunched

    @property
    def ok(self) -> bool:
        return self.error is None and not self.restarted

    @property
    def answer_ready(self) -> bool:
        return bool(self.answer and self.answer.get("ready"))

    @property
    def output(self) -> str:
        """What the model gets to see: stdout, then stderr, then the error line."""
        parts = [p for p in (self.stdout.rstrip("\n"), self.stderr.rstrip("\n")) if p]
        if self.error:
            parts.append(self.error)
        return "\n".join(parts)


@dataclass
class VarResult:
    name: str
    found: bool
    value_repr: str | None = None
    value_str: str | None = None


class REPL(ABC):
    """A persistent Python namespace that model-written code runs in."""

    @abstractmethod
    def start(self, context: Any, kind: str = "str") -> None:
        """Load ``context`` (a str, or a JSON-serialisable object when kind='json')."""

    @abstractmethod
    def execute(self, code: str) -> ExecResult: ...

    @abstractmethod
    def get_var(self, name: str) -> VarResult: ...

    @abstractmethod
    def close(self) -> None: ...

    def __enter__(self) -> REPL:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
