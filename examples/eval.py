"""Run the needle and OOLONG-lite tasks against one profile and tabulate.

    uv run python examples/eval.py --profile pluto --lines 1000000 --tickets 300

Writes ``runs/eval-<UTC timestamp>.json`` and prints a markdown table that can
be pasted into the README's Results section.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import needle  # noqa: E402
import oolong_lite  # noqa: E402

from reclamo.config import APIKeyError, ConfigError  # noqa: E402


def format_table(results: dict[str, Any]) -> str:
    rows = ["| Task | Result | Turns | Sub-calls | Tokens | Seconds |", "|---|---|---|---|---|---|"]
    n = results.get("needle")
    if n:
        outcome = "found" if n.get("found") else "missed"
        if n.get("error"):
            outcome += f" ({n['error']})"
        rows.append(
            f"| needle ({n['lines']:,} lines) | {outcome} | {_cell(n['turns'])} | "
            f"{_cell(n['subcalls'])} | {_cell(n['tokens'])} | {_cell(n['elapsed'])} |"
        )
    o = results.get("oolong_lite")
    if o:
        per_cat = ", ".join(f"{cat} {err}" for cat, err in o["errors"].items())
        outcome = f"total abs error {o['total_error']} ({per_cat})"
        if o.get("error"):
            outcome += f"; {o['error']}"
        rows.append(
            f"| oolong_lite ({o['n_tickets']} tickets) | {outcome} | {_cell(o['turns'])} | "
            f"{_cell(o['subcalls'])} | {_cell(o['tokens'])} | {_cell(o['elapsed'])} |"
        )
    return "\n".join(rows)


def _cell(value: Any) -> str:
    if value is None:
        return "-"
    return f"{value:,}" if isinstance(value, int) else str(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--profile", default="pluto")
    parser.add_argument("--profiles", default=None, metavar="FILE")
    parser.add_argument("--lines", type=int, default=1_000_000)
    parser.add_argument("--tickets", type=int, default=300)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--log-dir", default="runs")
    args = parser.parse_args(argv)

    try:
        cfg, client = needle.build_client(args.profile, args.profiles)
    except (ConfigError, APIKeyError) as exc:
        print(f"eval: {exc}", file=sys.stderr)
        return 2

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    results: dict[str, Any] = {
        "timestamp": stamp,
        "profile": cfg.name,
        "model": cfg.root.model,
        "base_url": cfg.base_url,
        "seed": args.seed,
        "needle": needle.run(cfg, client, args.lines, args.seed, log_dir=args.log_dir),
        "oolong_lite": oolong_lite.run(cfg, client, args.tickets, args.seed, log_dir=args.log_dir),
    }

    out_dir = Path(args.log_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"eval-{stamp}.json"
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    print(format_table(results))
    print(f"\nwritten: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
