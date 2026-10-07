"""Command-line entry point for ReCLamO-Harness.

Subcommands: ``ping`` (endpoint health check). ``run`` arrives with the RLM loop
(epic #8, child #5).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

import openai

from reclamo import __version__
from reclamo.client import LMClient
from reclamo.config import APIKeyError, ConfigError, load_config, resolve_api_key


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="reclamo",
        description="Recursive Language Model harness tuned for Qwen.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command")

    ping = sub.add_parser("ping", help="check the endpoint: models, a chat call, thinking")
    _add_profile_args(ping)
    ping.set_defaults(func=cmd_ping)
    return parser


def _add_profile_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--profile", default="pluto", help="profile name (default: pluto)")
    p.add_argument(
        "--profiles",
        default=None,
        metavar="FILE",
        help="user profiles TOML (default: ~/.config/reclamo/profiles.toml)",
    )


def cmd_ping(args: argparse.Namespace) -> int:
    out = sys.stdout
    try:
        cfg = load_config(args.profile, args.profiles)
        key = resolve_api_key(cfg)
    except (ConfigError, APIKeyError) as exc:
        print(f"reclamo ping: {exc}", file=sys.stderr)
        return 2

    client = LMClient(cfg, key)
    print(f"profile:  {cfg.name}", file=out)
    print(f"base_url: {cfg.base_url}", file=out)

    try:
        models = client.list_models()
        print(f"models:   {', '.join(models) if models else '(none listed)'}", file=out)
    except openai.APIError as exc:
        print(f"models:   unavailable ({_short(exc)})", file=out)

    probe = [{"role": "user", "content": "Reply with the single word: pong"}]
    try:
        plain = client.complete(probe, "sub", enable_thinking=False, max_tokens=16)
        print(f"model:    {plain.model or cfg.sub.model}", file=out)
        print(f"reply:    {plain.content.strip()[:80]!r}", file=out)
        print(f"latency:  {plain.latency:.2f}s", file=out)
        if plain.usage is None:
            print("usage:    (not reported)", file=out)
        else:
            u = plain.usage
            print(
                f"usage:    {u.prompt_tokens} prompt + {u.completion_tokens} completion"
                f" = {u.total_tokens} tokens",
                file=out,
            )

        thinking = client.complete(probe, "root", enable_thinking=True, max_tokens=512)
        got = "yes" if thinking.reasoning else "no"
        print(f"thinking: {got} (reasoning returned on an enable_thinking request)", file=out)
    except openai.APIError as exc:
        print(f"reclamo ping: request failed: {_short(exc)}", file=sys.stderr)
        return 1
    return 0


def _short(exc: BaseException) -> str:
    text = str(exc).strip().splitlines()
    return f"{type(exc).__name__}: {text[0] if text else ''}"


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_usage(sys.stderr)
        return 2
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
