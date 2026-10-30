"""Pre-registered analysis for the frontier replication (issue #120, TEST-PLAN 1j).

    python3 evals/gpt5-replication/analyze.py runs/exp-gpt5 > runs/exp-gpt5/report.md

Standard library only. Pairs are (task, seed) within a size; the outcome is ``exact``;
a missing answer, an error or a ``does_not_fit`` counts as wrong. For each size it
reports harness (rlm) vs plain, and at large also rlm vs mapreduce:

- the two-sided exact McNemar test on the discordant pairs (primary);
- a task-clustered bootstrap 95% CI for the accuracy difference (10,000 reps, seed 0);
- leave-one-task-out: the difference and McNemar p with each task removed;
- per-task counts and the harness's stop reasons.
"""

from __future__ import annotations

import json
import math
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

SIZES = ("small", "medium", "large")
REPS = 10_000


def load(path: Path) -> dict[tuple[str, str, int], dict]:
    if not path.exists():
        return {}
    rows = json.loads(path.read_text(encoding="utf-8"))["rows"]
    return {(r["size"], r["task"], int(r["seed"])): r for r in rows}


def mcnemar(b: int, c: int) -> float:
    """Two-sided exact McNemar p: binomial(b + c, 1/2), doubled, capped at 1."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return min(1.0, 2 * tail)


def win(r: dict | None) -> bool:
    return bool(r and r.get("exact"))


def compare(a: dict, b: dict, size: str, label: str) -> list[str]:
    keys = sorted(k for k in a if k[0] == size and k in b)
    if not keys:
        return [f"### {size}: {label}\n\nNo paired rows.\n"]
    tasks = sorted({k[1] for k in keys})

    def stats(ks: list) -> tuple[int, int, int, int, float]:
        ra = sum(win(a[k]) for k in ks)
        rb = sum(win(b[k]) for k in ks)
        only_a = sum(win(a[k]) and not win(b[k]) for k in ks)
        only_b = sum(win(b[k]) and not win(a[k]) for k in ks)
        return ra, rb, only_a, only_b, mcnemar(only_a, only_b)

    ra, rb, oa, ob, p = stats(keys)
    n = len(keys)
    by_task = defaultdict(list)
    for k in keys:
        by_task[k[1]].append(k)
    rng = random.Random(0)
    diffs = []
    for _ in range(REPS):
        pick = [k for t in rng.choices(tasks, k=len(tasks)) for k in by_task[t]]
        diffs.append((sum(win(a[k]) for k in pick) - sum(win(b[k]) for k in pick)) / len(pick))
    diffs.sort()
    lo, hi = diffs[int(0.025 * REPS)], diffs[int(0.975 * REPS) - 1]
    name_a, name_b = label.split(" vs ")
    out = [
        f"### {size}: {label}\n",
        f"- Pairs: {n}. {name_a} {ra}/{n} exact, {name_b} {rb}/{n} exact.",
        f"- Discordant: {name_a} only {oa}, {name_b} only {ob}. Exact McNemar p = {p:.4g}.",
        f"- Accuracy difference {(ra - rb) / n:+.3f}, "
        f"task-clustered 95% CI [{lo:+.3f}, {hi:+.3f}].\n",
        f"| Task | {name_a} | {name_b} | n | Leave this task out: diff | p |",
        "|---|---|---|---|---|---|",
    ]
    for t in tasks:
        ks = by_task[t]
        rest = [k for k in keys if k[1] != t]
        loo = "n/a | n/a"
        if rest:
            r2a, r2b, _, _, p2 = stats(rest)
            loo = f"{(r2a - r2b) / len(rest):+.3f} | {p2:.3g}"
        out.append(
            f"| {t} | {sum(win(a[k]) for k in ks)} | {sum(win(b[k]) for k in ks)} | {len(ks)} "
            f"| {loo} |"
        )
    stops = Counter(a[k].get("stop_reason") for k in keys)
    out.append(f"\n{name_a} stop reasons: {dict(stops)}\n")
    return out


def main() -> int:
    d = Path(sys.argv[1])
    rlm, plain, mr = load(d / "rlm.json"), load(d / "plain.json"), load(d / "mapreduce.json")
    lines = ["# Frontier replication: GPT-5 RLM vs plain GPT-5 (TEST-PLAN 1j)\n"]
    for size in SIZES:
        lines += compare(rlm, plain, size, "rlm vs plain")
        if size == "large":
            lines += compare(rlm, mr, size, "rlm vs mapreduce")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
