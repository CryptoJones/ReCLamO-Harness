"""Live tests against pluto. Skipped by default; run with ``uv run pytest -m live``.

They need the key from ``pass pluto/flashnext-api-key`` (or ``RECLAMO_API_KEY``)
and a reachable ``http://pluto:8083/v1``. Strata is FIFO, so keep these short.
"""

from __future__ import annotations

import pytest

from reclamo.cli import main
from reclamo.client import LMClient
from reclamo.config import load_config, resolve_api_key

pytestmark = pytest.mark.live


def test_ping_pluto(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["ping", "--profile", "pluto"]) == 0
    out = capsys.readouterr().out
    assert "qwen3.8-flash-next" in out
    assert "thinking: yes" in out


def test_thinking_is_logged_separately() -> None:
    cfg = load_config("pluto")
    client = LMClient(cfg, resolve_api_key(cfg))
    c = client.complete([{"role": "user", "content": "What is 17 * 23? Answer briefly."}], "root")
    assert "<think>" not in c.content
    assert c.reasoning, "expected reasoning_content on a thinking request"
    assert "391" in c.content


def test_needle_in_50k_lines() -> None:
    """A needle-in-a-haystack far beyond the 32K window; pluto must find it."""
    import random

    from reclamo.rlm import RLM

    rng = random.Random(7)
    lines = [f"record {i}: value {rng.randint(0, 10**6)}" for i in range(50_000)]
    needle_line = 31_337
    lines[needle_line] = "record 31337: the secret passphrase is MANDOLIN-ECLIPSE"
    context = "\n".join(lines)

    cfg = load_config("pluto")
    client = LMClient(cfg, resolve_api_key(cfg))
    result = RLM(cfg, client).completion(
        context, "What is the secret passphrase mentioned somewhere in the context?"
    )
    assert "MANDOLIN-ECLIPSE" in result.answer
