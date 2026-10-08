from __future__ import annotations

import threading
import time
from typing import Any

import openai
import pytest

from reclamo.client import MIN_REQUEST_TIMEOUT, LMClient, Usage, split_think
from reclamo.config import RLMConfig
from tests.conftest import FakeServer, chat_response, make_config
from tests.mocklm import api_timeout

KEY = "sk-test-not-a-real-key"


def _client(cfg: RLMConfig) -> LMClient:
    return LMClient(cfg, KEY, sleep=lambda _s: None)


# --- think stripping --------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "content", "reasoning"),
    [
        ("plain answer", "plain answer", None),
        ("<think>plan it</think>\nanswer", "answer", "plan it"),
        ("<think>a</think>mid<think>b</think>end", "midend", "a\nb"),
        ("leftover reasoning</think>\nanswer", "answer", "leftover reasoning"),
        ("<think>cut off by max_tokens", "", "cut off by max_tokens"),
        ("<think></think>answer", "answer", None),
    ],
)
def test_split_think(raw: str, content: str, reasoning: str | None) -> None:
    assert split_think(raw) == (content, reasoning)


def test_think_block_stripped_from_content(fake_server: FakeServer, config: RLMConfig) -> None:
    fake_server.script(chat_response("<think>let me plan</think>\nFINAL(42)"))
    c = _client(config).complete([{"role": "user", "content": "q"}], "root")
    assert c.content == "FINAL(42)"
    assert c.reasoning == "let me plan"
    assert c.content_from_reasoning is False


def test_server_reasoning_content_is_separate(fake_server: FakeServer, config: RLMConfig) -> None:
    fake_server.script(chat_response("answer", reasoning_content="server-side reasoning"))
    c = _client(config).complete([{"role": "user", "content": "q"}], "root")
    assert c.content == "answer"
    assert c.reasoning == "server-side reasoning"


def test_reasoning_fallback_when_content_empty(fake_server: FakeServer, config: RLMConfig) -> None:
    fake_server.script(chat_response("", reasoning_content="only reasoning came back"))
    c = _client(config).complete([{"role": "user", "content": "q"}], "root")
    assert c.content == "only reasoning came back"
    assert c.content_from_reasoning is True


def test_null_content_with_reasoning(fake_server: FakeServer, config: RLMConfig) -> None:
    fake_server.script(chat_response(None, reasoning_content="r"))
    c = _client(config).complete([{"role": "user", "content": "q"}], "root")
    assert c.content == "r" and c.content_from_reasoning


# --- request shape ----------------------------------------------------------


def test_root_request_carries_thinking_and_extra_body(
    fake_server: FakeServer, config: RLMConfig
) -> None:
    _client(config).complete([{"role": "user", "content": "q"}], "root")
    req = fake_server.requests[-1]
    assert req.path.endswith("/chat/completions")
    assert req.headers["authorization"] == f"Bearer {KEY}"
    body = req.body
    assert body["model"] == "fake-model"
    assert body["max_tokens"] == 4096
    assert body["temperature"] == 0.6 and body["top_p"] == 0.95
    # non-standard keys arrive at the top level via extra_body
    assert body["top_k"] == 20 and body["min_p"] == 0.0
    assert body["chat_template_kwargs"] == {"enable_thinking": True, "reasoning_effort": "medium"}
    assert body["messages"] == [{"role": "user", "content": "q"}]


def test_sub_request_disables_thinking(fake_server: FakeServer, config: RLMConfig) -> None:
    _client(config).complete([{"role": "user", "content": "q"}], "sub")
    body = fake_server.requests[-1].body
    assert body["max_tokens"] == 2048
    assert body["presence_penalty"] == 1.0
    assert body["chat_template_kwargs"] == {"enable_thinking": False}


def test_enable_thinking_and_max_tokens_overrides(
    fake_server: FakeServer, config: RLMConfig
) -> None:
    _client(config).complete(
        [{"role": "user", "content": "q"}], "sub", enable_thinking=True, max_tokens=99
    )
    body = fake_server.requests[-1].body
    assert body["max_tokens"] == 99
    assert body["chat_template_kwargs"]["enable_thinking"] is True


def test_unknown_role_rejected(config: RLMConfig) -> None:
    with pytest.raises(ValueError, match="unknown role"):
        _client(config).build_request([], "mid")


# --- retries ----------------------------------------------------------------


def test_retry_on_500_then_success(fake_server: FakeServer, config: RLMConfig) -> None:
    fake_server.script(500, chat_response("recovered"))
    sleeps: list[float] = []
    client = LMClient(config, KEY, sleep=sleeps.append)
    c = client.complete([{"role": "user", "content": "q"}])
    assert c.content == "recovered"
    assert c.attempts == 2
    assert len([r for r in fake_server.requests if r.method == "POST"]) == 2
    assert sleeps == [0.0]


def test_retry_backoff_doubles(fake_server: FakeServer) -> None:
    cfg = make_config(fake_server.base_url, max_retries=3, retry_backoff=0.5)
    fake_server.script(429, 503, chat_response("ok"))
    sleeps: list[float] = []
    LMClient(cfg, KEY, sleep=sleeps.append).complete([{"role": "user", "content": "q"}])
    assert sleeps == [0.5, 1.0]


def test_retries_exhausted_raises(fake_server: FakeServer, config: RLMConfig) -> None:
    fake_server.script(500, 500, 500, 500)
    with pytest.raises(openai.InternalServerError):
        _client(config).complete([{"role": "user", "content": "q"}])
    # max_retries=2 -> 3 attempts total
    assert len(fake_server.requests) == 3


def test_retry_false_makes_one_attempt(fake_server: FakeServer, config: RLMConfig) -> None:
    fake_server.script(500, chat_response("never reached"))
    with pytest.raises(openai.InternalServerError):
        _client(config).complete([{"role": "user", "content": "q"}], retry=False)
    assert len(fake_server.requests) == 1


def test_timeout_override_is_per_call(config: RLMConfig) -> None:
    client = _client(config)
    assert client.build_request([], "root")["timeout"] == config.root.timeout
    assert client.build_request([], "root", timeout=7.5)["timeout"] == 7.5


class _RecordingSDK:
    """Stands in for the openai SDK: records each attempt's timeout, then fails or answers."""

    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.timeouts: list[float] = []
        self.chat = self
        self.completions = self

    def create(self, **kwargs: Any) -> str:
        self.timeouts.append(kwargs["timeout"])
        if self.failures:
            self.failures -= 1
            raise api_timeout()
        return "response"


def test_deadline_caps_each_attempt_timeout(config: RLMConfig) -> None:
    """Issue #51: the request timeout is min(role timeout, time left)."""
    client = _client(config)
    sdk = _RecordingSDK(failures=1)
    kwargs = client.build_request([], "root")
    assert kwargs["timeout"] == 5.0
    _resp, attempts = client._call_with_retry(sdk, kwargs, True, time.monotonic() + 2.0)
    assert attempts == 2
    assert all(t <= 2.0 for t in sdk.timeouts)
    # far deadline: the role timeout still applies
    sdk = _RecordingSDK(failures=0)
    client._call_with_retry(sdk, client.build_request([], "root"), True, time.monotonic() + 999)
    assert sdk.timeouts == [5.0]


def test_deadline_stops_retries_when_no_time_is_left(fake_server: FakeServer) -> None:
    cfg = make_config(fake_server.base_url, max_retries=3, retry_backoff=1.0)
    sleeps: list[float] = []
    client = LMClient(cfg, KEY, sleep=sleeps.append)
    sdk = _RecordingSDK(failures=5)
    with pytest.raises(openai.APITimeoutError):
        client._call_with_retry(sdk, client.build_request([], "root"), True, time.monotonic() + 0.5)
    assert len(sdk.timeouts) == 1 and sleeps == []  # the 1 s backoff would pass the deadline
    assert sdk.timeouts[0] == MIN_REQUEST_TIMEOUT  # 0.5 s left is floored to the minimum


def test_4xx_is_not_retried(fake_server: FakeServer, config: RLMConfig) -> None:
    fake_server.script(400)
    with pytest.raises(openai.BadRequestError):
        _client(config).complete([{"role": "user", "content": "q"}])
    assert len(fake_server.requests) == 1


def test_connection_error_is_retried_then_raised() -> None:
    cfg = make_config("http://127.0.0.1:9", max_retries=1, retry_backoff=0.0)
    sleeps: list[float] = []
    with pytest.raises(openai.APIConnectionError):
        LMClient(cfg, KEY, sleep=sleeps.append).complete([{"role": "user", "content": "q"}])
    assert sleeps == [0.0]


# --- usage accounting -------------------------------------------------------


def test_usage_totals_accumulate(fake_server: FakeServer, config: RLMConfig) -> None:
    fake_server.script(chat_response(), chat_response())
    client = _client(config)
    client.complete([{"role": "user", "content": "q"}])
    client.complete([{"role": "user", "content": "q"}])
    assert client.calls == 2
    assert client.totals == Usage(20, 10, 30)


def test_missing_usage_is_tolerated(fake_server: FakeServer, config: RLMConfig) -> None:
    fake_server.script(chat_response("x", usage=False))
    client = _client(config)
    c = client.complete([{"role": "user", "content": "q"}])
    assert c.content == "x"
    assert c.usage is None
    assert client.calls == 1 and client.calls_without_usage == 1
    assert client.totals == Usage()


def test_completion_metadata(fake_server: FakeServer, config: RLMConfig) -> None:
    fake_server.script(chat_response("x", model="served-id", finish_reason="length"))
    c = _client(config).complete([{"role": "user", "content": "q"}], "sub")
    assert c.model == "served-id"
    assert c.finish_reason == "length"
    assert c.role == "sub"
    assert c.latency >= 0


# --- models and concurrency -------------------------------------------------


def test_list_models(fake_server: FakeServer, config: RLMConfig) -> None:
    fake_server.models = ["a", "b"]
    assert _client(config).list_models() == ["a", "b"]
    fake_server.models = []
    assert _client(config).list_models() == []


def test_concurrency_one_serialises_calls(fake_server: FakeServer) -> None:
    fake_server.handler_delay = 0.05
    cfg = make_config(fake_server.base_url, concurrency=1)
    client = _client(cfg)

    def go() -> None:
        client.complete([{"role": "user", "content": "q"}])

    threads = [threading.Thread(target=go) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert client.calls == 4
    assert fake_server.max_in_flight == 1


# --- secrecy ----------------------------------------------------------------


def test_key_never_in_repr(config: RLMConfig) -> None:
    client = _client(config)
    assert KEY not in repr(client)
    assert KEY not in str(vars(client.cfg))
