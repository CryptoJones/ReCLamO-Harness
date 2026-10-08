"""Thin, Qwen-aware wrapper over the ``openai`` SDK for OpenAI-compatible servers.

What it adds over a raw ``chat.completions.create``:

- per-role settings (``root`` thinks, ``sub`` does not) sent as
  ``chat_template_kwargs`` so Strata/vLLM-style servers toggle thinking;
- non-standard sampling keys (``top_k``, ``min_p``, ...) sent via ``extra_body``;
- ``<think>...</think>`` stripped from ``content`` and kept as ``reasoning``;
- ``reasoning_content`` used when ``content`` comes back empty;
- one HTTP client and one semaphore per distinct endpoint (pluto serves one
  request at a time; a root on another host is not serialised behind it);
- bounded retries with exponential backoff on 429, 5xx, timeouts and
  connection errors;
- tolerant usage accounting (a missing ``usage`` field is not an error);
- optional OpenAI-style function calling: ``tools=`` goes out with
  ``tool_choice="auto"`` and ``message.tool_calls`` comes back as ``ToolCall``s.

The API key is held privately and never appears in ``repr``, logs or errors.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

import openai

from reclamo.config import Endpoint, ModelConfig, RLMConfig, resolve_api_key

Message = Mapping[str, Any]

# Standard OpenAI parameters the SDK accepts by name. Anything else in a
# sampling dict is non-standard and goes through ``extra_body``.
_STANDARD_SAMPLING = frozenset(
    {"temperature", "top_p", "presence_penalty", "frequency_penalty", "seed", "stop"}
)

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)
_THINK_OPEN = re.compile(r"<think>.*\Z", re.DOTALL)
_THINK_CLOSE = re.compile(r"\A.*?</think>", re.DOTALL)


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def add(self, other: Usage) -> None:
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens
        self.total_tokens += other.total_tokens


@dataclass
class ToolCall:
    """One structured function call from the model. ``arguments`` is the raw JSON text."""

    id: str
    name: str
    arguments: str

    def as_message(self) -> dict[str, Any]:
        """The OpenAI wire shape, for the assistant message's ``tool_calls`` list."""
        return {
            "id": self.id,
            "type": "function",
            "function": {"name": self.name, "arguments": self.arguments},
        }


@dataclass
class Completion:
    content: str
    reasoning: str | None
    usage: Usage | None
    finish_reason: str | None
    latency: float
    model: str | None = None
    role: str = "root"
    content_from_reasoning: bool = False
    attempts: int = 1
    tool_calls: list[ToolCall] | None = None
    endpoint: str | None = None  # base_url that served this call


@dataclass
class _Conn:
    endpoint: Endpoint
    client: Any
    sem: threading.BoundedSemaphore


def split_think(text: str) -> tuple[str, str | None]:
    """Remove think blocks from ``text``; return ``(content, reasoning)``.

    Handles three shapes Qwen produces:

    - complete ``<think>...</think>`` blocks anywhere in the text;
    - a bare leading ``...</think>`` when the opening tag was eaten by the chat
      template (the reasoning is everything before the close tag);
    - an unclosed trailing ``<think>...`` when the output cap cut the reasoning
      short (everything after the open tag is reasoning; content is empty).
    """
    if "<think>" not in text and "</think>" not in text:
        return text, None

    reasoning_parts: list[str] = []

    def _grab(match: re.Match[str]) -> str:
        inner = match.group(0)
        inner = inner.removeprefix("<think>").removesuffix("</think>")
        reasoning_parts.append(inner.strip())
        return ""

    text = _THINK_BLOCK.sub(_grab, text)
    if "</think>" in text:
        text = _THINK_CLOSE.sub(_grab, text, count=1)
    if "<think>" in text:
        text = _THINK_OPEN.sub(_grab, text, count=1)

    reasoning = "\n".join(p for p in reasoning_parts if p) or None
    return text.strip(), reasoning


class LMClient:
    """Retrying chat-completion client for one profile, one connection per endpoint.

    ``api_key`` is either one key (the profile-level key; an endpoint with its own
    ``api_key_env``/``api_key_cmd`` resolves its key here instead) or a mapping
    ``{base_url: key}`` as returned by ``resolve_api_keys``. ``client`` injects one
    SDK client used for every endpoint (tests).
    """

    def __init__(
        self,
        cfg: RLMConfig,
        api_key: str | Mapping[str, str],
        *,
        client: openai.OpenAI | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.cfg = cfg
        self._sleep = sleep
        self._conns: dict[str, _Conn] = {}
        for ep in cfg.endpoints():
            if client is not None:
                sdk: Any = client
            else:
                # The SDK's own retries are turned off so backoff lives in one place.
                sdk = openai.OpenAI(
                    base_url=ep.base_url, api_key=self._key_for(ep, api_key), max_retries=0
                )
            self._conns[ep.base_url] = _Conn(ep, sdk, threading.BoundedSemaphore(ep.concurrency))
        self._lock = threading.Lock()
        self.totals = Usage()
        self.calls = 0
        self.calls_without_usage = 0

    def _key_for(self, ep: Endpoint, api_key: str | Mapping[str, str]) -> str:
        if isinstance(api_key, str):
            if (ep.api_key_env, ep.api_key_cmd) == (self.cfg.api_key_env, self.cfg.api_key_cmd):
                return api_key
        elif ep.base_url in api_key:
            return api_key[ep.base_url]
        return resolve_api_key(ep)

    def __repr__(self) -> str:  # never include the key
        urls = ", ".join(self._conns)
        return f"LMClient(profile={self.cfg.name!r}, endpoints=[{urls}])"

    def _conn(self, role: str) -> _Conn:
        url = self.cfg.endpoint(role).base_url
        try:
            return self._conns[url]
        except KeyError:
            raise ValueError(
                f"role {role!r} points at {url}, which this client was not built for"
            ) from None

    # --- requests ---------------------------------------------------------

    def build_request(
        self,
        messages: Iterable[Message],
        role: str = "root",
        *,
        enable_thinking: bool | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Return the kwargs for ``chat.completions.create`` (exposed for tests).

        ``timeout`` overrides the role's per-request timeout for this one call.
        """
        mc: ModelConfig = self.cfg.role(role)
        thinking = mc.enable_thinking if enable_thinking is None else enable_thinking

        extra_body: dict[str, Any] = {}
        kwargs: dict[str, Any] = {
            "model": mc.model,
            "messages": [dict(m) for m in messages],
            "max_tokens": max_tokens or mc.max_tokens,
            "timeout": mc.timeout if timeout is None else timeout,
        }
        for key, value in mc.sampling.items():
            if key in _STANDARD_SAMPLING:
                kwargs[key] = value
            else:
                extra_body[key] = value

        template_kwargs: dict[str, Any] = {"enable_thinking": thinking}
        if thinking and mc.reasoning_effort:
            template_kwargs["reasoning_effort"] = mc.reasoning_effort
        extra_body["chat_template_kwargs"] = template_kwargs
        kwargs["extra_body"] = extra_body
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        return kwargs

    def complete(
        self,
        messages: Iterable[Message],
        role: str = "root",
        *,
        enable_thinking: bool | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        timeout: float | None = None,
        retry: bool = True,
    ) -> Completion:
        """One chat completion. ``retry=False`` makes exactly one attempt (no backoff)."""
        kwargs = self.build_request(
            messages,
            role,
            enable_thinking=enable_thinking,
            max_tokens=max_tokens,
            tools=tools,
            timeout=timeout,
        )
        conn = self._conn(role)
        started = time.monotonic()
        with conn.sem:
            response, attempts = self._call_with_retry(conn.client, kwargs, retry)
        latency = time.monotonic() - started
        completion = self._parse(response, role=role, latency=latency, attempts=attempts)
        completion.endpoint = conn.endpoint.base_url
        with self._lock:
            self.calls += 1
            if completion.usage is None:
                self.calls_without_usage += 1
            else:
                self.totals.add(completion.usage)
        return completion

    def list_models(self, role: str = "root") -> list[str]:
        """Model ids from ``/v1/models`` on ``role``'s endpoint; an empty list is not an error."""
        page = self._conn(role).client.models.list()
        return [m.id for m in getattr(page, "data", None) or []]

    # --- internals --------------------------------------------------------

    def _call_with_retry(
        self, sdk: Any, kwargs: dict[str, Any], retry: bool = True
    ) -> tuple[Any, int]:
        attempts = 0
        while True:
            attempts += 1
            try:
                return sdk.chat.completions.create(**kwargs), attempts
            except openai.APIError as exc:
                if not retry or not _retryable(exc) or attempts > self.cfg.max_retries:
                    raise
                self._sleep(self.cfg.retry_backoff * 2 ** (attempts - 1))

    @staticmethod
    def _parse(response: Any, *, role: str, latency: float, attempts: int) -> Completion:
        choice = response.choices[0]
        message = choice.message
        raw_content = message.content or ""

        reasoning = getattr(message, "reasoning_content", None)
        if reasoning is None:
            extra = getattr(message, "model_extra", None) or {}
            reasoning = extra.get("reasoning_content") or extra.get("reasoning")

        content, inline_reasoning = split_think(raw_content)
        if inline_reasoning and not reasoning:
            reasoning = inline_reasoning
        reasoning = (reasoning or "").strip() or None

        tool_calls = _parse_tool_calls(getattr(message, "tool_calls", None))

        from_reasoning = False
        # An empty content is normal next to tool calls; only fall back without them.
        if not content and reasoning and not tool_calls:
            content, from_reasoning = reasoning, True

        usage = None
        if getattr(response, "usage", None) is not None:
            u = response.usage
            usage = Usage(
                prompt_tokens=int(getattr(u, "prompt_tokens", 0) or 0),
                completion_tokens=int(getattr(u, "completion_tokens", 0) or 0),
                total_tokens=int(getattr(u, "total_tokens", 0) or 0),
            )

        return Completion(
            content=content,
            reasoning=reasoning,
            usage=usage,
            finish_reason=getattr(choice, "finish_reason", None),
            latency=latency,
            model=getattr(response, "model", None),
            role=role,
            content_from_reasoning=from_reasoning,
            attempts=attempts,
            tool_calls=tool_calls,
        )


def _parse_tool_calls(raw: Any) -> list[ToolCall] | None:
    """``message.tool_calls`` -> ``ToolCall``s; a missing id gets a stable stand-in."""
    if not raw:
        return None
    calls: list[ToolCall] = []
    for k, tc in enumerate(raw):
        fn = getattr(tc, "function", None)
        name = getattr(fn, "name", None) or ""
        arguments = getattr(fn, "arguments", None)
        if not isinstance(arguments, str):  # some servers send an object
            arguments = json.dumps(arguments if arguments is not None else {})
        calls.append(
            ToolCall(id=getattr(tc, "id", None) or f"call_{k}", name=name, arguments=arguments)
        )
    return calls or None


def _retryable(exc: openai.APIError) -> bool:
    if isinstance(exc, openai.APITimeoutError | openai.APIConnectionError):
        return True
    if isinstance(exc, openai.APIStatusError):
        return exc.status_code == 429 or exc.status_code >= 500
    return False


__all__ = ["Completion", "LMClient", "ToolCall", "Usage", "split_think"]
