#!/usr/bin/env python3
"""Regenerate the paper's LaTeX tables from the exp-v02 run files.

Standard library only. Reads the row files that ``evals/independent/run_eval.py``
writes (``{"meta": ..., "rows": [...]}``), one file per arm, and writes booktabs
tables plus a macro file into ``paper/tables/``. Nothing in the paper's results is
typed by hand: rerun this script and rebuild.

Two stages:

* ``--stage pilot`` (default) reads ``<runs>/rescored/*.json``: seeds 2-3, re-graded
  with the round-3.1 scorers (``run_eval.py --rescore``). This is the n=16-per-cell
  pilot. It writes ``pilot_*.tex``.
* ``--stage main`` reads the live ``<runs>/*.json`` files (seeds 2-9 and the large
  questions; seeds 4-9 were graded at round 3.1 from the start). It writes
  ``main_*.tex``. ``main.tex`` inputs those files when they exist and shows a PENDING
  box otherwise, so rerunning this script after the planned phases finish drops the
  numbers into the paper.

    python3 paper/analysis/make_tables.py --runs runs/exp-v02
    python3 paper/analysis/make_tables.py --runs runs/exp-v02 --stage main --seeds 2-9
    python3 paper/analysis/make_tables.py --side DIR   # optional pilot side runs

Statistics: Wilson 95% intervals for exact-match proportions; a percentile
bootstrap (10,000 resamples over cells, fixed seed) for mean scores and paired mean
differences; McNemar's exact test (two-sided binomial on the discordant pairs) for
paired exact-match comparisons. Cells are paired on (task, size, seed). No
correction for multiple comparisons is applied.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
from pathlib import Path

HERE = Path(__file__).resolve().parent
PAPER = HERE.parent
REPO = PAPER.parent

# Arm file stem -> short label used in tables.
ARMS = {
    "plain-32k": "Plain 32K",
    "plain-131k": "Plain 128K",
    "h-v01-32k": "Harness v0.1",
    "h-v02-32k": "Harness v0.2 32K",
    "h-v02-131k": "Harness v0.2 128K",
}
SIZES = ("small", "medium", "large")
SIZE_LABEL = {"small": "Small", "medium": "Medium", "large": "Large"}

# Paired comparisons (A, B): a positive difference means A ahead.
PAIRS = [
    ("h-v01-32k", "plain-131k"),
    ("h-v01-32k", "plain-32k"),
    ("h-v02-131k", "plain-131k"),
    ("h-v01-32k", "h-v02-131k"),
    ("h-v01-32k", "h-v02-32k"),
]

ANSWERED = {"final", "final_var", "answer_dict", "stop"}
LIMIT = {"max_iterations", "timeout", "error_limit", "context_overflow", "length"}
NOT_RUN = {"error"}
DNF = {"does_not_fit"}

BOOT = 10_000
RNG_SEED = 20261009


# --------------------------------------------------------------------------- stats


def wilson(k: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, centre - half), min(1.0, centre + half))


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value: b = A right / B wrong, c = A wrong / B right."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return min(1.0, 2 * tail)


def boot_mean(xs: list[float], rng: random.Random) -> tuple[float, float]:
    if not xs:
        return (float("nan"), float("nan"))
    n = len(xs)
    means = sorted(sum(xs[rng.randrange(n)] for _ in range(n)) / n for _ in range(BOOT))
    return (means[int(0.025 * BOOT)], means[int(0.975 * BOOT) - 1])


def pct(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    if not xs:
        return float("nan")
    i = min(len(xs) - 1, max(0, math.ceil(q * len(xs)) - 1))
    return xs[i]


# --------------------------------------------------------------------------- data


def parse_seeds(text: str | None) -> set[int] | None:
    if not text:
        return None
    out: set[int] = set()
    for part in text.split(","):
        if "-" in part:
            a, b = part.split("-")
            out.update(range(int(a), int(b) + 1))
        else:
            out.add(int(part))
    return out


def load(runs: Path, stage: str, seeds: set[int] | None) -> dict[str, list[dict]]:
    base = runs / "rescored" if stage == "pilot" else runs
    arms: dict[str, list[dict]] = {}
    for stem in ARMS:
        f = base / f"{stem}.json"
        if not f.exists():
            continue
        rows = json.loads(f.read_text())["rows"]
        if seeds is not None:
            rows = [r for r in rows if r["seed"] in seeds]
        cells: dict[tuple, dict] = {}  # last row per cell wins (resumed runs append)
        for r in rows:
            cells[(r["task"], r["size"], r["seed"])] = r
        arms[stem] = list(cells.values())
    return arms


def outcome(r: dict) -> str:
    s = r.get("stop_reason")
    if r.get("does_not_fit") or s in DNF:
        return "dnf"
    if s in NOT_RUN or r.get("error"):
        return "not_run"
    if s in LIMIT:
        return "limit"
    if s in ANSWERED:
        return "answered"
    return "other"


def score(r: dict) -> float:
    return float(r.get("score") or 0.0)


def exact(r: dict) -> bool:
    return score(r) >= 1.0


# --------------------------------------------------------------------------- summaries


def summarise(rows: list[dict], rng: random.Random) -> dict:
    n = len(rows)
    k = sum(exact(r) for r in rows)
    sc = [score(r) for r in rows]
    oc = [outcome(r) for r in rows]
    attempted = [r for r in rows if outcome(r) != "dnf"]
    secs = [float(r["seconds"]) for r in attempted if r.get("seconds") is not None]
    toks = [float(r["tokens"]) for r in attempted if r.get("tokens")]
    sub = [float(r.get("subcalls") or 0) for r in attempted]
    turns = [float(r.get("turns") or 0) for r in attempted]
    return {
        "n": n,
        "exact": k,
        "wilson": wilson(k, n),
        "mean": statistics.fmean(sc) if sc else float("nan"),
        "mean_ci": boot_mean(sc, rng),
        "dnf": oc.count("dnf"),
        "answered": oc.count("answered"),
        "limit": oc.count("limit"),
        "not_run": oc.count("not_run"),
        "n_attempted": len(attempted),
        "sec_med": statistics.median(secs) if secs else float("nan"),
        "sec_p95": pct(secs, 0.95),
        "tok_med": statistics.median(toks) if toks else float("nan"),
        "sub_mean": statistics.fmean(sub) if sub else float("nan"),
        "sub_any": sum(1 for x in sub if x > 0),
        "turns_mean": statistics.fmean(turns) if turns else float("nan"),
    }


def paired(a: list[dict], b: list[dict], size: str | None, rng: random.Random) -> dict | None:
    ka = {(r["task"], r["size"], r["seed"]): r for r in a if size is None or r["size"] == size}
    kb = {(r["task"], r["size"], r["seed"]): r for r in b if size is None or r["size"] == size}
    keys = sorted(set(ka) & set(kb))
    if not keys:
        return None
    both = sum(exact(ka[k]) and exact(kb[k]) for k in keys)
    only_a = sum(exact(ka[k]) and not exact(kb[k]) for k in keys)
    only_b = sum(exact(kb[k]) and not exact(ka[k]) for k in keys)
    d = [score(ka[k]) - score(kb[k]) for k in keys]
    return {
        "n": len(keys),
        "a_exact": both + only_a,
        "b_exact": both + only_b,
        "only_a": only_a,
        "only_b": only_b,
        "p": mcnemar_exact(only_a, only_b),
        "dmean": statistics.fmean(d),
        "dmean_ci": boot_mean(d, rng),
    }


# --------------------------------------------------------------------------- LaTeX


def f2(x: float) -> str:
    return "--" if x != x else f"{x:.2f}"


def f0(x: float) -> str:
    return "--" if x != x else f"{x:,.0f}".replace(",", "{,}")


def ci(lo_hi: tuple[float, float]) -> str:
    lo, hi = lo_hi
    return "--" if lo != lo else f"[{lo:.2f}, {hi:.2f}]"


def pfmt(p: float) -> str:
    return "1.00" if p >= 0.995 else f"{p:.2f}" if p >= 0.01 else f"{p:.3f}"


def caption_note(stage: str, seeds: str) -> str:
    if stage == "pilot":
        return (
            f"\\textbf{{Preliminary pilot}}: seeds {seeds}, $n{{=}}16$ cells per arm and "
            "size, round-3.1 grader. Not a test of any hypothesis."
        )
    return f"Seeds {seeds}; round-3.1 grader."


def table_accuracy(arms: dict, stats: dict, stage: str, seeds: str) -> str:
    lines = [
        "\\begin{table}[t]",
        "\\centering\\small",
        f"\\caption{{Accuracy per arm and size. {caption_note(stage, seeds)} "
        "Exact = score 1.0 under the task's own \\texttt{score()}; a plain prompt that "
        "does not fit the window (DNF) scores 0. Intervals: Wilson 95\\% for exact, "
        "bootstrap 95\\% for the mean.}",
        f"\\label{{tab:{stage}-accuracy}}",
        "\\begin{tabular}{llrlrlr}",
        "\\toprule",
        "Size & Arm & Exact & 95\\% CI & Mean & 95\\% CI & DNF \\\\",
        "\\midrule",
    ]
    for size in SIZES:
        present = [a for a in ARMS if a in arms and stats[a][size]["n"]]
        if not present:
            continue
        for i, a in enumerate(present):
            s = stats[a][size]
            lines.append(
                f"{SIZE_LABEL[size] if i == 0 else ''} & {ARMS[a]} & "
                f"{s['exact']}/{s['n']} & {ci(s['wilson'])} & {f2(s['mean'])} & "
                f"{ci(s['mean_ci'])} & {s['dnf']} \\\\"
            )
        lines.append("\\midrule")
    lines[-1] = "\\bottomrule"
    lines += ["\\end{tabular}", "\\end{table}", ""]
    return "\n".join(lines)


def table_cost(arms: dict, stats: dict, stage: str, seeds: str) -> str:
    lines = [
        "\\begin{table}[t]",
        "\\centering\\small",
        "\\setlength{\\tabcolsep}{4pt}",
        f"\\caption{{Completion, delegation, cost and latency over attempted rows. "
        f"{caption_note(stage, seeds)} Ans.\\ = the model finished on its own "
        "(\\texttt{FINAL}, \\texttt{FINAL\\_VAR}, the answer dict, or a plain reply that "
        "stopped normally); Lim.\\ = turn cap, time limit, error limit, context overflow "
        "or output-length cap (the harness then takes a forced finish). Deleg.\\ = rows "
        "with at least one sub-call; Sub-calls and Turns are means per attempted row. "
        "Tokens include sub-calls. Seconds are wall clock on shared, serial hardware.}",
        f"\\label{{tab:{stage}-cost}}",
        "\\begin{tabular}{llrrrrrrr}",
        "\\toprule",
        "Size & Arm & Ans. & Lim. & Deleg. & Sub-calls & Turns & Med.\\ tokens & Med./p95 s \\\\",
        "\\midrule",
    ]
    for size in SIZES:
        present = [a for a in ARMS if a in arms and stats[a][size]["n"]]
        if not present:
            continue
        for i, a in enumerate(present):
            s = stats[a][size]
            plain = a.startswith("plain")
            att = s["n_attempted"]
            lines.append(
                f"{SIZE_LABEL[size] if i == 0 else ''} & {ARMS[a]} & "
                f"{s['answered']}/{att} & {s['limit']}/{att} & "
                f"{'--' if plain else str(s['sub_any']) + '/' + str(att)} & "
                f"{'--' if plain else f2(s['sub_mean'])} & "
                f"{'--' if plain else f2(s['turns_mean'])} & {f0(s['tok_med'])} & "
                f"{f0(s['sec_med'])}/{f0(s['sec_p95'])} \\\\"
            )
        lines.append("\\midrule")
    lines[-1] = "\\bottomrule"
    lines += ["\\end{tabular}", "\\end{table}", ""]
    return "\n".join(lines)


def table_paired(pairs: dict, stage: str, seeds: str) -> str:
    lines = [
        "\\begin{table}[t]",
        "\\centering\\small",
        "\\setlength{\\tabcolsep}{4pt}",
        f"\\caption{{Paired comparisons on identical cells. {caption_note(stage, seeds)} "
        "$b$ = cells only A got exact, $c$ = cells only B got exact; $p$ = McNemar's "
        "exact two-sided test on $(b, c)$. $\\Delta$ = paired mean-score difference "
        "A$-$B with a bootstrap 95\\% interval. Uncorrected for multiple comparisons.}",
        f"\\label{{tab:{stage}-paired}}",
        "\\begin{tabular}{lllrrrrl}",
        "\\toprule",
        "Size & A & B & A ex. & B ex. & $b$/$c$ & $p$ & $\\Delta$ mean [95\\% CI] \\\\",
        "\\midrule",
    ]
    for size in (*SIZES, None):
        rows = [(k, v) for k, v in pairs.items() if k[2] == size and v]
        if not rows:
            continue
        for i, ((a, b, _), v) in enumerate(rows):
            label = (SIZE_LABEL[size] if size else "Pooled") if i == 0 else ""
            lines.append(
                f"{label} & {ARMS[a]} & {ARMS[b]} & {v['a_exact']}/{v['n']} & "
                f"{v['b_exact']}/{v['n']} & {v['only_a']}/{v['only_b']} & {pfmt(v['p'])} & "
                f"${v['dmean']:+.2f}$ {ci(v['dmean_ci'])} \\\\"
            )
        lines.append("\\midrule")
    lines[-1] = "\\bottomrule"
    lines += ["\\end{tabular}", "\\end{table}", ""]
    return "\n".join(lines)


def macro_name(*parts: str) -> str:
    """Letters only (LaTeX command names): digits become words."""
    words = "Zero One Two Three Four Five Six Seven Eight Nine".split()
    out = []
    for p in parts:
        for ch in p:
            if ch.isalpha():
                out.append(ch)
            elif ch.isdigit():
                out.append(words[int(ch)])
    return "".join(out)


def macros(arms: dict, stats: dict, pairs: dict, stage: str) -> str:
    """One \\newcommand per headline number, e.g. \\pilotExacthvZeroOneThreeTwoksmall."""
    lines = [f"% Generated by paper/analysis/make_tables.py --stage {stage}. Do not edit."]
    for a in arms:
        for size in SIZES:
            s = stats[a][size]
            if not s["n"]:
                continue
            key = macro_name(a, size)
            lo, hi = s["wilson"]
            lines.append(f"\\newcommand{{\\{stage}Exact{key}}}{{{s['exact']}/{s['n']}}}")
            lines.append(f"\\newcommand{{\\{stage}Wilson{key}}}{{[{lo:.2f}, {hi:.2f}]}}")
            lines.append(f"\\newcommand{{\\{stage}Mean{key}}}{{{s['mean']:.2f}}}")
            lines.append(f"\\newcommand{{\\{stage}Sub{key}}}{{{f2(s['sub_mean'])}}}")
            lines.append(f"\\newcommand{{\\{stage}Dnf{key}}}{{{s['dnf']}}}")
    for (a, b, size), v in pairs.items():
        if not v:
            continue
        key = macro_name(a, "vs", b, size or "pooled")
        lines.append(f"\\newcommand{{\\{stage}P{key}}}{{{pfmt(v['p'])}}}")
        lines.append(f"\\newcommand{{\\{stage}BC{key}}}{{{v['only_a']}/{v['only_b']}}}")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- side runs


def _rows(path: Path) -> list[dict]:
    return json.loads(path.read_text())["rows"] if path.exists() else []


def side_tables(side: Path, out: Path) -> None:
    """Pilot side runs (row files not in git): RLM-Qwen3-8B as planner, Laguna S 2.1
    before and after the parser fix, Llama 3.3 70B. Writes pilot_side.tex."""
    laguna = [side / "laguna-ronin28/r3-small-medium.json"] + sorted(
        side.glob("laguna-ronin28/w*-*.json")
    )
    specs = [
        ("RLM-Qwen3-8B planner", [side / "round3-tutor.json"]),
        ("Laguna S 2.1", laguna),
        ("Llama 3.3 70B (GLaDOS only)", [side / "py-llama70b-glados.json"]),
    ]
    lines = [
        "\\begin{table}[t]",
        "\\centering\\small",
        "\\caption{\\textbf{Preliminary} pilot side runs on the round-3 task set (seeds 0--1 "
        "at small and medium, seed 0 at large; the Llama run is GLaDOS only), with harness "
        "v0.1 settings. Their plain rows still used the best-of-2 rule of "
        "Section~\\ref{sec:lessons}, so plain is an upper bound. Exact / cells. "
        "Observations, not tests.}",
        "\\label{tab:pilot-side}",
        "\\begin{tabular}{llrr}",
        "\\toprule",
        "Setup & Size & Harness exact & Plain exact (best-of-2) \\\\",
        "\\midrule",
    ]
    for name, files in specs:
        cells: dict[tuple, dict] = {}
        for f in files:
            for r in _rows(f):
                cells[(r["task"], r["size"], r["seed"], r["mode"])] = r
        if not cells:
            continue
        first = True
        for size in SIZES:
            rl = [r for k, r in cells.items() if k[1] == size and k[3] == "rlm"]
            pl = [r for k, r in cells.items() if k[1] == size and k[3] == "plain"]
            if not rl and not pl:
                continue
            dnf = sum(outcome(r) == "dnf" for r in pl)
            pe = "--"
            if pl:
                pe = f"{sum(exact(r) for r in pl)}/{len(pl)}" + (f" ({dnf} DNF)" if dnf else "")
            lines.append(
                f"{name if first else ''} & {size} & "
                f"{sum(exact(r) for r in rl)}/{len(rl)} & {pe} \\\\"
            )
            first = False
        lines.append("\\midrule")
    before: dict[tuple, dict] = {}
    for f in laguna:
        for r in _rows(f):
            before[(r["task"], r["size"], r["seed"], r["mode"])] = r
    after: dict[tuple, dict] = {}
    for f in sorted(side.glob("laguna-ronin28/fix-*.json")):
        for r in _rows(f):
            after[(r["task"], r["size"], r["seed"], r["mode"])] = r
    keys = [k for k in after if k in before]
    if keys:
        b = sum(exact(before[k]) for k in keys)
        a = sum(exact(after[k]) for k in keys)
        lines.append(
            f"Laguna, parser-fix reruns & {len(keys)} cells & {b}/{len(keys)} before, "
            f"{a}/{len(keys)} after & -- \\\\"
        )
        lines.append("\\midrule")
    lines[-1] = "\\bottomrule"
    lines += ["\\end{tabular}", "\\end{table}", ""]
    (out / "pilot_side.tex").write_text("\n".join(lines))


# --------------------------------------------------------------------------- main


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--runs", type=Path, default=REPO / "runs" / "exp-v02")
    ap.add_argument("--stage", choices=("pilot", "main"), default="pilot")
    ap.add_argument(
        "--seeds", default=None, help="e.g. 2,3 or 2-9 (default: 2,3 for pilot, all for main)"
    )
    ap.add_argument("--out", type=Path, default=PAPER / "tables")
    ap.add_argument(
        "--side", type=Path, default=None, help="directory with pilot side-run row files"
    )
    args = ap.parse_args()

    seeds_text = args.seeds or ("2,3" if args.stage == "pilot" else None)
    seeds = parse_seeds(seeds_text)
    arms = load(args.runs, args.stage, seeds)
    if not arms:
        raise SystemExit(f"no arm files found under {args.runs}")
    rng = random.Random(RNG_SEED)
    stats = {
        a: {s: summarise([r for r in rows if r["size"] == s], rng) for s in SIZES}
        for a, rows in arms.items()
    }
    pairs = {}
    for a, b in PAIRS:
        if a in arms and b in arms:
            for size in (*SIZES, None):
                pairs[(a, b, size)] = paired(arms[a], arms[b], size, rng)
    seeds_label = seeds_text or ",".join(
        str(s) for s in sorted({r["seed"] for rows in arms.values() for r in rows})
    )
    seeds_label = seeds_label.replace(",", ", ").replace("-", "--")

    args.out.mkdir(parents=True, exist_ok=True)
    st = args.stage
    (args.out / f"{st}_accuracy.tex").write_text(table_accuracy(arms, stats, st, seeds_label))
    (args.out / f"{st}_cost.tex").write_text(table_cost(arms, stats, st, seeds_label))
    (args.out / f"{st}_paired.tex").write_text(table_paired(pairs, st, seeds_label))
    (args.out / f"{st}_macros.tex").write_text(macros(arms, stats, pairs, st))
    if args.side:
        side_tables(args.side, args.out)

    for a in arms:
        for s in SIZES:
            x = stats[a][s]
            if x["n"]:
                print(
                    f"{a:11s} {s:6s} exact {x['exact']:2d}/{x['n']:2d} {ci(x['wilson'])} "
                    f"mean {f2(x['mean'])} {ci(x['mean_ci'])} dnf {x['dnf']} ans {x['answered']} "
                    f"lim {x['limit']} deleg {x['sub_any']} sub {f2(x['sub_mean'])} "
                    f"turns {f2(x['turns_mean'])} tok {f0(x['tok_med'])} "
                    f"s {f0(x['sec_med'])}/{f0(x['sec_p95'])}"
                )
    for (a, b, s), v in pairs.items():
        if v:
            print(
                f"{a} vs {b} [{s or 'pooled'}] n={v['n']} {v['a_exact']} vs {v['b_exact']} "
                f"b/c={v['only_a']}/{v['only_b']} p={pfmt(v['p'])} "
                f"d={v['dmean']:+.2f} {ci(v['dmean_ci'])}"
            )


if __name__ == "__main__":
    main()
