"""Command-line entry point for ReCLamO-Harness.

Subcommands: ``ping`` (endpoint health check) and ``run`` (one RLM completion).
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import openai

from reclamo import __version__
from reclamo.client import LMClient
from reclamo.config import APIKeyError, ConfigError, RLMConfig, load_config, resolve_api_key
from reclamo.errors import RLMError

EXIT_OK = 0
EXIT_OTHER = 1
EXIT_CONFIG = 2
EXIT_LIMIT = 3


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

    run = sub.add_parser("run", help="answer a query about a large context with an RLM")
    _add_profile_args(run)
    run.add_argument(
        "--context",
        required=True,
        metavar="PATH|-",
        help="a text file, a directory (loaded as {relative path: text}), or - for stdin",
    )
    run.add_argument("-q", "--query", required=True, help="the question to answer")
    run.add_argument("--max-depth", type=int, default=None, help="recursion depth (default 1)")
    run.add_argument("--max-iterations", type=int, default=None, help="root turns (default 20)")
    run.add_argument("--log-dir", default="runs", help="trajectory JSONL directory (default runs/)")
    run.add_argument("--verbose", action="store_true", help="print each turn to stderr")
    run.add_argument("--no-thinking", action="store_true", help="disable thinking on root turns")
    run.add_argument("--json", action="store_true", help="print the result as JSON")
    run.add_argument("--sft", action="store_true", help="also write <run>.sft.jsonl")
    run.set_defaults(func=cmd_run)
    return parser


def _add_profile_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--profile", default="pluto", help="profile name (default: pluto)")
    p.add_argument(
        "--profiles",
        default=None,
        metavar="FILE",
        help="user profiles TOML (default: ~/.config/reclamo/profiles.toml)",
    )


def _load_client(args: argparse.Namespace, label: str) -> tuple[RLMConfig, LMClient] | int:
    try:
        cfg = load_config(args.profile, args.profiles)
        key = resolve_api_key(cfg)
    except (ConfigError, APIKeyError) as exc:
        print(f"reclamo {label}: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    return cfg, LMClient(cfg, key)


def cmd_ping(args: argparse.Namespace) -> int:
    out = sys.stdout
    loaded = _load_client(args, "ping")
    if isinstance(loaded, int):
        return loaded
    cfg, client = loaded
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
        return EXIT_OTHER
    return EXIT_OK


def load_context(spec: str) -> str | dict[str, str]:
    """``-`` reads stdin; a file is read as text; a directory becomes {relpath: text}."""
    if spec == "-":
        return sys.stdin.read()
    path = Path(spec)
    if path.is_dir():
        files: dict[str, str] = {}
        for p in sorted(path.rglob("*")):
            if not p.is_file() or any(part.startswith(".") for part in p.relative_to(path).parts):
                continue
            try:
                files[p.relative_to(path).as_posix()] = p.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue  # binary or unreadable: skipped
        if not files:
            raise ConfigError(f"no readable text files under {path}")
        return files
    if not path.is_file():
        raise ConfigError(f"context not found: {spec}")
    return path.read_text(encoding="utf-8", errors="replace")


def cmd_run(args: argparse.Namespace) -> int:
    from reclamo.logger import TrajectoryLogger, VerbosePrinter
    from reclamo.rlm import RLM

    loaded = _load_client(args, "run")
    if isinstance(loaded, int):
        return loaded
    cfg, client = loaded

    overrides: dict[str, Any] = {}
    if args.max_depth is not None:
        overrides["max_depth"] = args.max_depth
    if args.max_iterations is not None:
        overrides["max_iterations"] = args.max_iterations
    if args.sft:
        overrides["sft_log"] = True
    if args.no_thinking:
        overrides["root"] = dataclasses.replace(cfg.root, enable_thinking=False)
    if overrides:
        cfg = dataclasses.replace(cfg, **overrides)
        client.cfg = cfg

    try:
        context = load_context(args.context)
    except ConfigError as exc:
        print(f"reclamo run: {exc}", file=sys.stderr)
        return EXIT_CONFIG

    logger = TrajectoryLogger(args.log_dir, sft=cfg.sft_log)
    printer = VerbosePrinter(enabled=args.verbose)
    rlm = RLM(cfg, client, logger=logger, printer=printer)
    try:
        result = rlm.completion(context, args.query)
    except RLMError as exc:
        print(f"reclamo run: {exc}", file=sys.stderr)
        if logger.path:
            print(f"trajectory: {logger.path}", file=sys.stderr)
        if exc.partial_answer:
            if args.json:
                print(json.dumps({"partial_answer": exc.partial_answer, "error": str(exc)}))
            else:
                print(exc.partial_answer)
        return EXIT_LIMIT
    except openai.APIError as exc:
        print(f"reclamo run: request failed: {_short(exc)}", file=sys.stderr)
        return EXIT_OTHER

    if args.json:
        print(json.dumps(dataclasses.asdict(result), ensure_ascii=False, indent=2))
    else:
        print(result.answer)
        if logger.path:
            print(
                f"[{result.stop_reason}; {result.iterations} turns, {result.subcalls} sub-calls, "
                f"{result.usage.total_tokens} tokens, {result.elapsed:.1f}s; "
                f"trajectory: {logger.path}]",
                file=sys.stderr,
            )
    return EXIT_OK


def _short(exc: BaseException) -> str:
    text = str(exc).strip().splitlines()
    return f"{type(exc).__name__}: {text[0] if text else ''}"


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_usage(sys.stderr)
        return EXIT_CONFIG
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
