"""JSONL trajectory logging and an optional rich console printer.

One file per run under ``log_dir``: ``<timestamp>-<shortid>.jsonl``. Line types:
``metadata``, ``iteration``, ``subcall``, ``compaction``, ``final``. With
``sft=True`` a second file, ``<same stem>.sft.jsonl``, gets one line per root
turn: ``{"messages": <history before the turn>, "completion": <content>}``,
the training format used for the paper's RLM-Qwen3-8B.

Reasoning is logged as its own field and never mixed into messages. Nothing
here ever sees an API key: the config is serialised without one (it never
holds one) and the client is not logged at all.
"""

from __future__ import annotations

import dataclasses
import json
import os
import secrets
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _jsonable(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {k: _jsonable(v) for k, v in dataclasses.asdict(value).items()}
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return repr(value)


class TrajectoryLogger:
    """Appends JSON lines to one trajectory file (and optionally an SFT file)."""

    def __init__(
        self,
        log_dir: str | os.PathLike[str] | None,
        *,
        sft: bool = False,
        run_id: str | None = None,
    ) -> None:
        self.path: Path | None = None
        self.sft_path: Path | None = None
        if log_dir is not None:
            directory = Path(log_dir)
            directory.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            run_id = run_id or secrets.token_hex(3)
            self.path = directory / f"{stamp}-{run_id}.jsonl"
            if sft:
                self.sft_path = directory / f"{stamp}-{run_id}.sft.jsonl"
        self._started = time.monotonic()

    def _write(self, path: Path | None, record: dict[str, Any]) -> None:
        if path is None:
            return
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(_jsonable(record), ensure_ascii=False) + "\n")

    def event(self, event_type: str, **fields: Any) -> None:
        record = {"type": event_type, "t": round(time.monotonic() - self._started, 3), **fields}
        self._write(self.path, record)

    def metadata(self, **fields: Any) -> None:
        self.event("metadata", **fields)

    def iteration(self, **fields: Any) -> None:
        self.event("iteration", **fields)

    def subcall(self, **fields: Any) -> None:
        self.event("subcall", **fields)

    def compaction(self, **fields: Any) -> None:
        self.event("compaction", **fields)

    def final(self, **fields: Any) -> None:
        self.event("final", **fields)

    def sft(self, messages: list[dict[str, Any]], completion: str, **fields: Any) -> None:
        self._write(self.sft_path, {"messages": messages, "completion": completion, **fields})


class VerbosePrinter:
    """Pretty console output for ``--verbose``; uses rich if available."""

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self._console: Any = None
        if enabled:
            from rich.console import Console

            self._console = Console(stderr=True)

    def _panel(self, text: str, title: str, style: str) -> None:
        if not self.enabled:
            return
        from rich.panel import Panel

        self._console.print(Panel(text.rstrip() or "(empty)", title=title, border_style=style))

    def response(self, depth: int, i: int, n: int, content: str) -> None:
        self._panel(content, f"turn {i}/{n} (depth {depth}) response", "cyan")

    def code(self, k: int, code: str) -> None:
        if not self.enabled:
            return
        from rich.panel import Panel
        from rich.syntax import Syntax

        self._console.print(
            Panel(Syntax(code, "python"), title=f"code block {k}", border_style="blue")
        )

    def output(self, k: int, text: str) -> None:
        self._panel(text, f"block {k} output", "green")

    def note(self, text: str) -> None:
        if self.enabled:
            self._console.print(f"[yellow]note:[/yellow] {text}")

    def subcall(self, kind: str, prompt_chars: int, answer_chars: int, latency: float) -> None:
        if self.enabled:
            self._console.print(
                f"[magenta]{kind}[/magenta] {prompt_chars} chars -> {answer_chars} chars "
                f"in {latency:.1f}s"
            )

    def final(self, answer: str, reason: str) -> None:
        self._panel(answer, f"final ({reason})", "bold green")


__all__ = ["TrajectoryLogger", "VerbosePrinter"]
