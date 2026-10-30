"""Spend so far, from the rows the lanes have written (issue #120).

    python3 evals/gpt5-replication/cost.py runs/exp-gpt5/lanes [cap_usd]

Rows record prompt and completion tokens summed over root and sub-calls, not split by
model, so every token is priced at GPT-5's uncached rates ($1.25 in / $10 out per
million). That is an upper bound: GPT-5-mini sub-calls cost a fifth of that, and
cached input a tenth. Exits 3 when the bound reaches ``cap_usd``. The OpenAI usage
dashboard is the authoritative figure.
"""

from __future__ import annotations

import glob
import json
import sys

IN_PER_M, OUT_PER_M = 1.25, 10.0


def spend(lane_dir: str) -> tuple[float, int, dict[str, float]]:
    total, rows, by_file = 0.0, 0, {}
    for path in sorted(glob.glob(f"{lane_dir}/*.json")):
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue  # a lane is mid-write; the next check reads it
        cost = 0.0
        for row in data.get("rows", []):
            p = row.get("prompt_tokens") or 0
            c = row.get("completion_tokens") or 0
            if not (p or c) and row.get("tokens"):
                p = row["tokens"]  # older rows: total only, price it all as input
            cost += p / 1e6 * IN_PER_M + c / 1e6 * OUT_PER_M
            rows += 1
        by_file[path.rsplit("/", 1)[-1]] = cost
        total += cost
    return total, rows, by_file


def main() -> int:
    lane_dir = sys.argv[1]
    cap = float(sys.argv[2]) if len(sys.argv) > 2 else float("inf")
    total, rows, _ = spend(lane_dir)
    print(f"{rows} rows, upper-bound spend ${total:,.2f} (cap ${cap:,.2f})")
    return 3 if total >= cap else 0


if __name__ == "__main__":
    sys.exit(main())
