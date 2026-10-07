"""Shared fixtures: a scripted fake OpenAI-compatible HTTP server (no network)."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from reclamo.config import ModelConfig, RLMConfig


@dataclass
class Recorded:
    method: str
    path: str
    headers: dict[str, str]
    body: Any


def chat_response(
    content: str | None = "ok",
    *,
    reasoning_content: str | None = None,
    usage: dict[str, int] | None | bool = True,
    model: str = "fake-model",
    finish_reason: str = "stop",
) -> dict[str, Any]:
    """Build a chat.completions response body. ``usage=False`` omits the field."""
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if reasoning_content is not None:
        message["reasoning_content"] = reasoning_content
    body: dict[str, Any] = {
        "id": "chatcmpl-fake",
        "object": "chat.completion",
        "created": 0,
        "model": model,
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
    }
    if usage is True:
        body["usage"] = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    elif isinstance(usage, dict):
        body["usage"] = usage
    return body


@dataclass
class FakeServer:
    """Scripted responses: each item is a dict (200 JSON) or an int (HTTP error)."""

    chat_script: list[dict[str, Any] | int] = field(default_factory=list)
    models: list[str] = field(default_factory=lambda: ["fake-model"])
    handler_delay: float = 0.0
    requests: list[Recorded] = field(default_factory=list)
    base_url: str = ""
    max_in_flight: int = 0
    _in_flight: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def script(self, *items: dict[str, Any] | int) -> None:
        self.chat_script.extend(items)


@pytest.fixture
def fake_server() -> Iterator[FakeServer]:
    state = FakeServer()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_: Any) -> None:  # keep pytest output clean
            pass

        def _send(self, status: int, body: dict[str, Any]) -> None:
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _record(self, body: Any) -> None:
            state.requests.append(
                Recorded(
                    self.command, self.path, {k.lower(): v for k, v in self.headers.items()}, body
                )
            )

        def do_GET(self) -> None:
            self._record(None)
            if self.path.endswith("/models"):
                self._send(
                    200,
                    {
                        "object": "list",
                        "data": [{"id": m, "object": "model"} for m in state.models],
                    },
                )
            else:
                self._send(404, {"error": {"message": "not found"}})

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            body = json.loads(raw) if raw else None
            self._record(body)
            with state._lock:
                state._in_flight += 1
                state.max_in_flight = max(state.max_in_flight, state._in_flight)
            try:
                if state.handler_delay:
                    time.sleep(state.handler_delay)
                if not self.path.endswith("/chat/completions"):
                    self._send(404, {"error": {"message": "not found"}})
                    return
                item = state.chat_script.pop(0) if state.chat_script else chat_response()
                if isinstance(item, int):
                    self._send(item, {"error": {"message": f"scripted {item}", "type": "x"}})
                else:
                    self._send(200, item)
            finally:
                with state._lock:
                    state._in_flight -= 1

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.02), daemon=True)
    thread.start()
    state.base_url = f"http://127.0.0.1:{server.server_address[1]}/v1"
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()


def make_config(base_url: str, **overrides: Any) -> RLMConfig:
    fields: dict[str, Any] = {
        "name": "test",
        "base_url": base_url,
        "concurrency": 1,
        "max_retries": 2,
        "retry_backoff": 0.0,
        "root": ModelConfig(
            model="fake-model",
            max_tokens=4096,
            enable_thinking=True,
            reasoning_effort="medium",
            sampling={"temperature": 0.6, "top_p": 0.95, "top_k": 20, "min_p": 0.0},
            timeout=5.0,
        ),
        "sub": ModelConfig(
            model="fake-model",
            max_tokens=2048,
            enable_thinking=False,
            sampling={"temperature": 0.7, "top_p": 0.8, "top_k": 20, "presence_penalty": 1.0},
            timeout=5.0,
        ),
    }
    fields.update(overrides)
    return RLMConfig(**fields)


@pytest.fixture
def config(fake_server: FakeServer) -> RLMConfig:
    return make_config(fake_server.base_url)
