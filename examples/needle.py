"""Needle in a haystack: find one passphrase line in N synthetic lines.

    uv run python examples/needle.py --profile pluto --lines 1000000

The default haystack is 1M lines (about 30 MB), far beyond any context window,
so the model has to search from the REPL. Exit status 0 when the passphrase is
in the answer, 1 otherwise. ``run()`` is importable by ``eval.py``.
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from typing import Any

from reclamo.client import LMClient
from reclamo.config import APIKeyError, ConfigError, RLMConfig, load_config, resolve_api_key
from reclamo.errors import RLMError
from reclamo.logger import TrajectoryLogger
from reclamo.rlm import RLM

QUERY = (
    "Somewhere in the context one line mentions a secret passphrase. What is it? "
    "Reply with just the passphrase."
)

_WORDS = [
    "MANDOLIN", "ECLIPSE", "GRANITE", "VELVET", "CORSAIR", "TUNDRA", "SAFFRON", "QUASAR",
    "LANTERN", "MERIDIAN", "OBSIDIAN", "PELICAN", "RADIANT", "SEQUOIA", "TALISMAN", "UMBRELLA",
    "VORTEX", "WALNUT", "ZENITH", "BASALT", "CINDER", "DYNAMO", "EMBER", "FALCON",
    "GLACIER", "HARBOR", "ISOTOPE", "JUNIPER", "KESTREL", "LAGOON", "NEBULA", "ORCHID",
]  # fmt: skip


def build_haystack(
    lines: int, seed: int = 0, position: float | None = None
) -> tuple[str, str, int]:
    """Return (context, passphrase, zero-based needle line index).

    ``position`` (0.0-1.0) pins the needle to a fraction of the way through the
    file; ``None`` picks a random line from the seed, as before.
    """
    if lines < 1:
        raise ValueError("lines must be >= 1")
    if position is not None and not 0.0 <= position <= 1.0:
        raise ValueError("position must be between 0.0 and 1.0")
    rng = random.Random(seed)
    first, second = rng.sample(_WORDS, 2)
    passphrase = f"{first}-{second}"
    needle = rng.randrange(lines) if position is None else min(lines - 1, int(position * lines))
    out = [f"record {i}: value {rng.randint(0, 10**6)}" for i in range(lines)]
    out[needle] = f"record {needle}: the secret passphrase is {passphrase}"
    return "\n".join(out), passphrase, needle


def run(
    cfg: RLMConfig,
    client: Any,
    lines: int = 1_000_000,
    seed: int = 0,
    *,
    log_dir: str | None = None,
) -> dict[str, Any]:
    """Build the haystack, run the RLM, and return a JSON-serialisable summary."""
    context, passphrase, needle = build_haystack(lines, seed)
    logger = TrajectoryLogger(log_dir)
    started = time.monotonic()
    summary: dict[str, Any] = {
        "task": "needle",
        "lines": lines,
        "chars": len(context),
        "needle_line": needle,
        "passphrase": passphrase,
    }
    try:
        result = RLM(cfg, client, logger=logger).completion(context, QUERY)
    except RLMError as exc:
        summary.update(
            answer=exc.partial_answer or "",
            found=bool(exc.partial_answer and passphrase in exc.partial_answer),
            error=str(exc),
            turns=None,
            subcalls=None,
            tokens=None,
            elapsed=round(time.monotonic() - started, 2),
            stop_reason="error",
            trajectory=str(logger.path) if logger.path else None,
        )
        return summary
    summary.update(
        answer=result.answer,
        found=passphrase in result.answer,
        turns=result.iterations,
        subcalls=result.subcalls,
        tokens=result.usage.total_tokens,
        elapsed=round(result.elapsed, 2),
        stop_reason=result.stop_reason,
        trajectory=result.trajectory_path,
    )
    return summary


def build_client(profile: str, profiles: str | None) -> tuple[RLMConfig, LMClient]:
    cfg = load_config(profile, profiles)
    return cfg, LMClient(cfg, resolve_api_key(cfg))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--profile", default="pluto")
    parser.add_argument("--profiles", default=None, metavar="FILE")
    parser.add_argument("--lines", type=int, default=1_000_000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--log-dir", default="runs")
    args = parser.parse_args(argv)
    try:
        cfg, client = build_client(args.profile, args.profiles)
    except (ConfigError, APIKeyError) as exc:
        print(f"needle: {exc}", file=sys.stderr)
        return 2
    summary = run(cfg, client, args.lines, args.seed, log_dir=args.log_dir)
    print(f"answer:    {summary['answer']!r}")
    print(f"found:     {summary['found']} (passphrase {summary['passphrase']})")
    print(f"turns:     {summary['turns']}")
    print(f"sub-calls: {summary['subcalls']}")
    print(f"tokens:    {summary['tokens']}")
    print(f"elapsed:   {summary['elapsed']}s")
    if summary.get("error"):
        print(f"error:     {summary['error']}", file=sys.stderr)
    return 0 if summary["found"] else 1


if __name__ == "__main__":
    sys.exit(main())
