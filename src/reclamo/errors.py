"""Typed errors raised by the RLM loop. Each carries whatever answer existed."""

from __future__ import annotations


class RLMError(Exception):
    """A run stopped before the model finished. ``partial_answer`` may be None."""

    def __init__(self, message: str, partial_answer: str | None = None) -> None:
        super().__init__(message)
        self.partial_answer = partial_answer


class RLMTimeout(RLMError):
    """``max_timeout`` (wall clock for the whole run) was exceeded."""


class RLMErrorLimit(RLMError):
    """``max_errors`` consecutive REPL executions failed."""


class RLMTokenLimit(RLMError):
    """``max_tokens_total`` was exceeded."""


__all__ = ["RLMError", "RLMErrorLimit", "RLMTimeout", "RLMTokenLimit"]
