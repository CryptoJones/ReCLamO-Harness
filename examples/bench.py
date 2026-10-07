"""Repeatable benchmark: RLM versus the plain model over N seeds, with resume.

    uv run python examples/bench.py --profile pluto --seeds 3
    uv run python examples/bench.py --profile pluto --grid oolong_lite:100,300 --seeds 3 \\
        --resume runs/bench-20261007T120000Z.json
    uv run python examples/bench.py --summary-only runs/bench-20261007T120000Z.json
    uv run python examples/bench.py --dry-run                # the grid and fit decisions

Tasks come from the sibling examples (``needle``, ``oolong_lite``, ``longdoc_qa``);
this file adds the grid, the modes and the bookkeeping:

- ``rlm``: the harness, through the library API.
- ``plain``: one chat call with the whole context in the prompt, the paper's
  baseline. It runs only when the prompt fits the model's usable window
  (``context_tokens`` minus the root output reserve, at ``CHARS_PER_TOKEN``
  chars per token); otherwise the row records ``does not fit`` and no call.
- ``plain_truncated`` (opt-in): the same call with the context cut to fit,
  clearly labelled; it shows what a window-limited model gets.

Every row is written to the JSON as soon as it finishes, so a run can be
interrupted and continued with ``--resume FILE``; rows already present
(same task, size, mode and seed) are skipped. A markdown summary (mean
+/- stdev over seeds, median seconds, median sub-calls) is written next to
the JSON and printed.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
import statistics
import sys
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import longdoc_qa  # noqa: E402
import needle  # noqa: E402
import oolong_lite  # noqa: E402

from reclamo.config import APIKeyError, ConfigError, RLMConfig  # noqa: E402
from reclamo.errors import RLMError  # noqa: E402
from reclamo.logger import TrajectoryLogger  # noqa: E402
from reclamo.rlm import CHARS_PER_TOKEN, RLM  # noqa: E402

MODES = ("rlm", "plain", "plain_truncated")
DEFAULT_MODES = ("rlm", "plain")
DEFAULT_GRID: tuple[tuple[str, int], ...] = (
    ("oolong_lite", 100),
    ("oolong_lite", 300),
    ("needle", 2_000),
    ("needle", 10_000),
    ("needle", 100_000),
    ("needle", 1_000_000),
    ("longdoc_qa", 100),
    ("longdoc_qa", 300),
)
# Needle position cycles through start / middle / end as the seed advances, so
# three seeds cover the cases a truncated baseline gets right and wrong.
NEEDLE_POSITIONS = (0.05, 0.5, 0.95)
PLAIN_SYSTEM = (
    "You are a careful analyst. The user message holds a document between the "
    "markers and then a question about it. Answer from the document only."
)
RowRunner = Callable[[str, int, str, int], dict[str, Any]]


@dataclass
class Instance:
    task: str
    size: int
    seed: int
    context: str
    query: str
    truth: Any
    meta: dict[str, Any]


@dataclass
class Scored:
    score: float  # higher is better for accuracy tasks; abs error for oolong
    correct: bool | None
    detail: dict[str, Any]


@dataclass(frozen=True)
class TaskSpec:
    name: str
    size_label: str  # what ``size`` counts
    metric: str  # "accuracy" (score in 0..1) | "abs_error" (lower is better)
    build: Callable[[int, int], Instance]
    score: Callable[[str, Any], Scored]


# --- tasks ------------------------------------------------------------------------


def _build_needle(size: int, seed: int) -> Instance:
    position = NEEDLE_POSITIONS[seed % len(NEEDLE_POSITIONS)]
    context, passphrase, line = needle.build_haystack(size, seed, position)
    return Instance(
        "needle", size, seed, context, needle.QUERY, passphrase,
        {"needle_line": line, "needle_position": position},
    )  # fmt: skip


def _score_needle(answer: str, truth: Any) -> Scored:
    found = truth in answer
    return Scored(1.0 if found else 0.0, found, {})


def _build_oolong(size: int, seed: int) -> Instance:
    tickets, truth = oolong_lite.generate_tickets(size, seed)
    return Instance(
        "oolong_lite", size, seed, oolong_lite.build_context(tickets), oolong_lite.build_query(),
        truth, {},
    )  # fmt: skip


def _score_oolong(answer: str, truth: Any) -> Scored:
    predicted, errors, total = oolong_lite.score(answer, truth)
    return Scored(float(total), total == 0, {"predicted": predicted, "errors": errors})


def _build_qa(size: int, seed: int) -> Instance:
    doc = longdoc_qa.generate_document(size, seed)
    meta = {
        "questions": [q.text for q in doc.questions],
        "answers": [q.answer for q in doc.questions],
    }
    return Instance(
        "longdoc_qa",
        size,
        seed,
        doc.text,
        longdoc_qa.build_query(doc.questions),
        doc.questions,
        meta,
    )


def _score_qa(answer: str, truth: Any) -> Scored:
    marks, fraction = longdoc_qa.score(answer, truth)
    return Scored(fraction, all(marks), {"per_question": marks})


TASKS: dict[str, TaskSpec] = {
    "needle": TaskSpec("needle", "lines", "accuracy", _build_needle, _score_needle),
    "oolong_lite": TaskSpec("oolong_lite", "tickets", "abs_error", _build_oolong, _score_oolong),
    "longdoc_qa": TaskSpec("longdoc_qa", "sections", "accuracy", _build_qa, _score_qa),
}


def build_instance(task: str, size: int, seed: int) -> Instance:
    return TASKS[task].build(size, seed)


# --- the plain baseline and the fit decision ----------------------------------------


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / CHARS_PER_TOKEN)


def plain_messages(context: str, query: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": PLAIN_SYSTEM},
        {
            "role": "user",
            "content": f"=== DOCUMENT ===\n{context}\n=== END DOCUMENT ===\n\n{query}",
        },
    ]


def usable_tokens(cfg: RLMConfig) -> int:
    """Prompt tokens the plain baseline may use: the window minus the output reserve."""
    return cfg.context_tokens - cfg.root.max_tokens


def fit_decision(cfg: RLMConfig, context: str, query: str) -> tuple[bool, int, int]:
    """Return (fits, estimated prompt tokens, usable prompt tokens)."""
    prompt = "".join(m["content"] for m in plain_messages(context, query))
    est = estimate_tokens(prompt)
    budget = usable_tokens(cfg)
    return est <= budget, est, budget


def truncate_to_fit(cfg: RLMConfig, context: str, query: str) -> tuple[str, float]:
    """Keep the head of ``context`` so the plain prompt fits; return (text, kept fraction)."""
    overhead = estimate_tokens("".join(m["content"] for m in plain_messages("", query)))
    keep_chars = int((usable_tokens(cfg) - overhead) * CHARS_PER_TOKEN)
    keep_chars = max(0, min(len(context), keep_chars))
    return context[:keep_chars], (keep_chars / len(context) if context else 1.0)


# --- one row ------------------------------------------------------------------------


def run_rlm(cfg: RLMConfig, client: Any, inst: Instance, log_dir: str | None) -> dict[str, Any]:
    spec = TASKS[inst.task]
    logger = TrajectoryLogger(log_dir)
    started = time.monotonic()
    try:
        result = RLM(cfg, client, logger=logger).completion(inst.context, inst.query)
    except RLMError as exc:
        answer = exc.partial_answer or ""
        scored = spec.score(answer, inst.truth)
        return {
            "answer": answer[:2000],
            "score": scored.score,
            "correct": scored.correct,
            **scored.detail,
            "turns": None,
            "subcalls": None,
            "tokens": None,
            "seconds": round(time.monotonic() - started, 2),
            "stop_reason": "error",
            "error": f"{type(exc).__name__}: {exc}",
            "trajectory": str(logger.path) if logger.path else None,
        }
    except Exception as exc:  # endpoint or sandbox failure: record it, keep the run going
        return {
            "answer": "",
            "score": 0.0 if spec.metric == "accuracy" else None,
            "correct": False,
            "turns": None,
            "subcalls": None,
            "tokens": None,
            "seconds": round(time.monotonic() - started, 2),
            "stop_reason": "error",
            "error": f"{type(exc).__name__}: {str(exc).splitlines()[0] if str(exc) else ''}",
            "trajectory": str(logger.path) if logger.path else None,
        }
    scored = spec.score(result.answer, inst.truth)
    return {
        "answer": result.answer[:2000],
        "score": scored.score,
        "correct": scored.correct,
        **scored.detail,
        "turns": result.iterations,
        "subcalls": result.subcalls,
        "tokens": result.usage.total_tokens,
        "prompt_tokens": result.usage.prompt_tokens,
        "completion_tokens": result.usage.completion_tokens,
        "seconds": round(result.elapsed, 2),
        "stop_reason": result.stop_reason,
        "error": None,
        "trajectory": result.trajectory_path,
    }


def run_plain(cfg: RLMConfig, client: Any, inst: Instance, *, truncated: bool) -> dict[str, Any]:
    spec = TASKS[inst.task]
    fits, est, budget = fit_decision(cfg, inst.context, inst.query)
    row: dict[str, Any] = {"fits": fits, "est_prompt_tokens": est, "usable_tokens": budget}
    context = inst.context
    if truncated:
        if fits:
            row["kept_fraction"] = 1.0
        else:
            context, kept = truncate_to_fit(cfg, inst.context, inst.query)
            row["kept_fraction"] = round(kept, 4)
    elif not fits:
        row.update(
            answer=None,
            score=None,
            correct=None,
            turns=None,
            subcalls=None,
            tokens=None,
            seconds=None,
            stop_reason="does_not_fit",
            error=None,
            trajectory=None,
        )
        return row
    messages = plain_messages(context, inst.query)
    started = time.monotonic()
    try:
        completion = client.complete(messages, "root")
    except Exception as exc:
        row.update(
            answer="",
            score=0.0 if spec.metric == "accuracy" else None,
            correct=False,
            turns=1,
            subcalls=0,
            tokens=None,
            seconds=round(time.monotonic() - started, 2),
            stop_reason="error",
            error=f"{type(exc).__name__}: {str(exc).splitlines()[0] if str(exc) else ''}",
            trajectory=None,
        )
        return row
    scored = spec.score(completion.content, inst.truth)
    usage = completion.usage
    row.update(
        answer=completion.content[:2000],
        score=scored.score,
        correct=scored.correct,
        **scored.detail,
        turns=1,
        subcalls=0,
        tokens=usage.total_tokens if usage else None,
        prompt_tokens=usage.prompt_tokens if usage else None,
        completion_tokens=usage.completion_tokens if usage else None,
        reasoning_chars=len(completion.reasoning or ""),
        seconds=round(completion.latency, 2),
        stop_reason=completion.finish_reason or "stop",
        error=None,
        trajectory=None,
    )
    return row


def run_row(
    cfg: RLMConfig, client: Any, task: str, size: int, mode: str, seed: int, log_dir: str | None
) -> dict[str, Any]:
    inst = build_instance(task, size, seed)
    row: dict[str, Any] = {
        "task": task,
        "size": size,
        "mode": mode,
        "seed": seed,
        "chars": len(inst.context),
        "truth": _jsonable_truth(inst.truth),
        **inst.meta,
        "started_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    if mode == "rlm":
        row.update(run_rlm(cfg, client, inst, log_dir))
    elif mode == "plain":
        row.update(run_plain(cfg, client, inst, truncated=False))
    elif mode == "plain_truncated":
        row.update(run_plain(cfg, client, inst, truncated=True))
    else:
        raise ValueError(f"unknown mode {mode!r}; expected one of {', '.join(MODES)}")
    return row


def _jsonable_truth(truth: Any) -> Any:
    if isinstance(truth, list) and truth and dataclasses.is_dataclass(truth[0]):
        return [t.answer for t in truth]
    return truth


# --- grid, resume, output -----------------------------------------------------------


def parse_grid(specs: Iterable[str]) -> list[tuple[str, int]]:
    """``task:size[,size...]`` -> [(task, size), ...]; order preserved, duplicates dropped."""
    grid: list[tuple[str, int]] = []
    for spec in specs:
        task, sep, sizes = spec.partition(":")
        if task not in TASKS or not sep or not sizes:
            raise ValueError(
                f"bad grid spec {spec!r}; expected task:size[,size...] with task in "
                f"{', '.join(TASKS)}"
            )
        for raw in sizes.split(","):
            try:
                size = int(raw.replace("_", ""))
            except ValueError:
                raise ValueError(f"bad size {raw!r} in grid spec {spec!r}") from None
            if size < 1:
                raise ValueError(f"bad size {raw!r} in grid spec {spec!r}")
            if (task, size) not in grid:
                grid.append((task, size))
    return grid


def row_key(row: dict[str, Any]) -> tuple[str, int, str, int]:
    return (row["task"], int(row["size"]), row["mode"], int(row["seed"]))


def load_rows(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("meta", {}), list(data.get("rows", []))


def write_rows(path: Path, meta: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps({"meta": meta, "rows": rows}, indent=1, ensure_ascii=False))
    tmp.replace(path)


def plan(
    grid: Iterable[tuple[str, int]], modes: Iterable[str], seeds: Iterable[int]
) -> list[tuple[str, int, str, int]]:
    modes, seeds = list(modes), list(seeds)
    return [(task, size, mode, seed) for task, size in grid for mode in modes for seed in seeds]


def run_grid(
    runner: RowRunner,
    grid: Iterable[tuple[str, int]],
    modes: Iterable[str],
    seeds: Iterable[int],
    *,
    rows: list[dict[str, Any]],
    on_row: Callable[[dict[str, Any]], None] | None = None,
    log: Callable[[str], None] = lambda _msg: None,
) -> list[dict[str, Any]]:
    """Run every cell not already in ``rows``; append each new row and call ``on_row``."""
    done = {row_key(r) for r in rows}
    todo = [cell for cell in plan(grid, modes, seeds) if cell not in done]
    log(f"{len(todo)} rows to run, {len(done)} already present")
    for n, (task, size, mode, seed) in enumerate(todo, 1):
        log(f"[{n}/{len(todo)}] {task} {size} {mode} seed={seed} ...")
        row = runner(task, size, mode, seed)
        rows.append(row)
        if on_row:
            on_row(row)
        log(f"    -> {describe_row(row)}")
    return rows


def describe_row(row: dict[str, Any]) -> str:
    if row.get("stop_reason") == "does_not_fit":
        return (
            f"does not fit (est {row['est_prompt_tokens']:,} tokens > "
            f"{row['usable_tokens']:,} usable)"
        )
    spec = TASKS[row["task"]]
    if spec.metric == "accuracy":
        outcome = f"score {row['score']:.2f}" if row.get("score") is not None else "score -"
    else:
        outcome = f"abs error {row['score']:g}" if row.get("score") is not None else "abs error -"
    bits = [
        outcome,
        f"{row.get('turns')} turns",
        f"{row.get('subcalls')} sub-calls",
        f"{row.get('tokens')} tokens",
        f"{row.get('seconds')}s",
        str(row.get("stop_reason")),
    ]
    if row.get("error"):
        bits.append(row["error"])
    return ", ".join(bits)


# --- summary --------------------------------------------------------------------------


@dataclass
class Cell:
    task: str
    size: int
    mode: str
    n: int
    metric: str
    mean: float | None
    stdev: float | None
    exact: int  # rows marked correct
    questions_correct: int | None  # longdoc_qa only
    questions_total: int | None
    median_seconds: float | None
    median_subcalls: float | None
    median_tokens: float | None
    median_turns: float | None
    does_not_fit: int
    errors: int
    stop_reasons: dict[str, int]
    est_prompt_tokens: int | None
    usable_tokens: int | None


def _median(values: list[Any]) -> float | None:
    nums = [float(v) for v in values if v is not None]
    return round(statistics.median(nums), 1) if nums else None


def summarize(rows: Iterable[dict[str, Any]]) -> list[Cell]:
    groups: dict[tuple[str, int, str], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault((row["task"], int(row["size"]), row["mode"]), []).append(row)
    order = {m: i for i, m in enumerate(MODES)}
    task_order = {t: i for i, t in enumerate(TASKS)}
    cells: list[Cell] = []
    for (task, size, mode), group in sorted(
        groups.items(), key=lambda kv: (task_order.get(kv[0][0], 99), kv[0][1], order[kv[0][2]])
    ):
        metric = TASKS[task].metric
        scores = [float(r["score"]) for r in group if r.get("score") is not None]
        mean = round(statistics.fmean(scores), 3) if scores else None
        stdev = round(statistics.stdev(scores), 3) if len(scores) > 1 else (0.0 if scores else None)
        stop_reasons: dict[str, int] = {}
        for r in group:
            reason = str(r.get("stop_reason"))
            stop_reasons[reason] = stop_reasons.get(reason, 0) + 1
        q_correct = q_total = None
        if task == "longdoc_qa":
            marks = [m for r in group for m in (r.get("per_question") or [])]
            q_correct, q_total = sum(bool(m) for m in marks), len(marks)
        fits_rows = [r for r in group if r.get("stop_reason") == "does_not_fit"]
        cells.append(
            Cell(
                task=task,
                size=size,
                mode=mode,
                n=len(group),
                metric=metric,
                mean=mean,
                stdev=stdev,
                exact=sum(1 for r in group if r.get("correct")),
                questions_correct=q_correct,
                questions_total=q_total,
                median_seconds=_median([r.get("seconds") for r in group]),
                median_subcalls=_median([r.get("subcalls") for r in group]),
                median_tokens=_median([r.get("tokens") for r in group]),
                median_turns=_median([r.get("turns") for r in group]),
                does_not_fit=len(fits_rows),
                errors=sum(1 for r in group if r.get("error")),
                stop_reasons=stop_reasons,
                est_prompt_tokens=fits_rows[0].get("est_prompt_tokens") if fits_rows else None,
                usable_tokens=fits_rows[0].get("usable_tokens") if fits_rows else None,
            )
        )
    return cells


def _result_text(cell: Cell) -> str:
    if cell.does_not_fit == cell.n:
        return f"does not fit (~{cell.est_prompt_tokens:,} tokens > {cell.usable_tokens:,} usable)"
    if cell.mean is None:
        return "no result"
    if cell.metric == "accuracy":
        text = f"{cell.mean:.2f} ± {cell.stdev:.2f}"
        if cell.questions_total:
            text += f" ({cell.questions_correct}/{cell.questions_total} questions)"
        else:
            text += f" ({cell.exact}/{cell.n} found)"
        return text
    return f"abs error {cell.mean:.1f} ± {cell.stdev:.1f} (exact {cell.exact}/{cell.n})"


def _num(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{int(value):,}" if float(value).is_integer() else f"{value:,.1f}"


def format_summary(cells: Iterable[Cell]) -> str:
    lines = [
        "| Task | Size | Mode | n | Result (mean ± sd over seeds) | Median s | Median turns | "
        "Median sub-calls | Median tokens | Stops |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for c in cells:
        label = TASKS[c.task].size_label
        stops = ", ".join(f"{k} ×{v}" if v > 1 else k for k, v in sorted(c.stop_reasons.items()))
        if c.errors:
            stops += f"; {c.errors} error(s)"
        lines.append(
            f"| {c.task} | {c.size:,} {label} | {c.mode} | {c.n} | {_result_text(c)} | "
            f"{_num(c.median_seconds)} | {_num(c.median_turns)} | {_num(c.median_subcalls)} | "
            f"{_num(c.median_tokens)} | {stops} |"
        )
    return "\n".join(lines)


def format_dry_run(cfg: RLMConfig, cells: Iterable[tuple[str, int, str, int]]) -> str:
    lines = []
    seen: dict[tuple[str, int], tuple[int, bool, int]] = {}
    for task, size, mode, seed in cells:
        if (task, size) not in seen:
            inst = build_instance(task, size, 0)
            fits, est, budget = fit_decision(cfg, inst.context, inst.query)
            seen[(task, size)] = (len(inst.context), fits, est)
        chars, fits, est = seen[(task, size)]
        verdict = ""
        if mode == "plain":
            verdict = "fits" if fits else "does not fit"
        elif mode == "plain_truncated":
            verdict = "no truncation needed" if fits else "truncated"
        lines.append(
            f"{task:12} {size:>9,} {mode:16} seed={seed}  {chars:>10,} chars ~{est:>7,} tokens  "
            f"{verdict}"
        )
    return "\n".join(lines)


# --- CLI --------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--profile", default="pluto")
    parser.add_argument("--profiles", default=None, metavar="FILE")
    parser.add_argument(
        "--grid",
        action="append",
        metavar="TASK:SIZE[,SIZE...]",
        help="a task and its sizes; repeatable (default: the built-in grid)",
    )
    parser.add_argument(
        "--modes",
        default=",".join(DEFAULT_MODES),
        help=f"comma-separated subset of {', '.join(MODES)} (default: %(default)s)",
    )
    parser.add_argument("--seeds", type=int, default=3, help="seeds 0..N-1 (default: 3)")
    parser.add_argument(
        "--seed-list", default=None, help="explicit comma-separated seeds (overrides --seeds)"
    )
    parser.add_argument("--out", default=None, metavar="FILE", help="JSON rows (default runs/)")
    parser.add_argument(
        "--resume", default=None, metavar="FILE", help="continue this JSON; skip rows it holds"
    )
    parser.add_argument(
        "--summary-only", default=None, metavar="FILE", help="summarise an existing JSON; no runs"
    )
    parser.add_argument("--log-dir", default="runs", help="trajectory directory (default runs/)")
    parser.add_argument(
        "--max-timeout", type=float, default=600.0, help="seconds per RLM run (default 600)"
    )
    parser.add_argument("--dry-run", action="store_true", help="print the plan; call no model")
    return parser


def _seeds(args: argparse.Namespace) -> list[int]:
    if args.seed_list:
        return [int(s) for s in args.seed_list.split(",") if s.strip()]
    return list(range(args.seeds))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    err = sys.stderr

    if args.summary_only:
        _meta, rows = load_rows(Path(args.summary_only))
        print(format_summary(summarize(rows)))
        return 0

    try:
        grid = parse_grid(args.grid) if args.grid else list(DEFAULT_GRID)
        modes = [m.strip() for m in args.modes.split(",") if m.strip()]
        bad = [m for m in modes if m not in MODES]
        if bad or not modes:
            raise ValueError(f"unknown mode(s) {', '.join(bad)}; expected {', '.join(MODES)}")
    except ValueError as exc:
        print(f"bench: {exc}", file=err)
        return 2
    seeds = _seeds(args)

    try:
        from reclamo.config import load_config

        cfg = load_config(args.profile, args.profiles)
        cfg = dataclasses.replace(cfg, max_timeout=args.max_timeout)
    except ConfigError as exc:
        print(f"bench: {exc}", file=err)
        return 2

    if args.dry_run:
        print(format_dry_run(cfg, plan(grid, modes, seeds)))
        return 0

    try:
        from reclamo.client import LMClient
        from reclamo.config import resolve_api_key

        client = LMClient(cfg, resolve_api_key(cfg))
    except APIKeyError as exc:
        print(f"bench: {exc}", file=err)
        return 2

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    rows: list[dict[str, Any]] = []
    meta: dict[str, Any] = {}
    if args.resume:
        meta, rows = load_rows(Path(args.resume))
    out = Path(args.out or args.resume or Path(args.log_dir) / f"bench-{stamp}.json")
    meta = {
        **meta,
        "profile": cfg.name,
        "model": cfg.root.model,
        "base_url": cfg.base_url,
        "context_tokens": cfg.context_tokens,
        "usable_tokens": usable_tokens(cfg),
        "chars_per_token": CHARS_PER_TOKEN,
        "root_max_tokens": cfg.root.max_tokens,
        "max_timeout": cfg.max_timeout,
        "subcall_chars": cfg.subcall_chars,
        "max_depth": cfg.max_depth,
        "created": meta.get("created", stamp),
        "updated": stamp,
    }
    meta.setdefault("batches", [])
    meta["batches"].append({"at": stamp, "grid": grid, "modes": modes, "seeds": seeds})

    def runner(task: str, size: int, mode: str, seed: int) -> dict[str, Any]:
        return run_row(cfg, client, task, size, mode, seed, args.log_dir)

    def save(_row: dict[str, Any]) -> None:
        write_rows(out, meta, rows)

    def log(message: str) -> None:
        print(message, file=err, flush=True)

    write_rows(out, meta, rows)
    try:
        run_grid(runner, grid, modes, seeds, rows=rows, on_row=save, log=log)
    except KeyboardInterrupt:
        print(f"bench: interrupted; {len(rows)} rows saved in {out}", file=err)
        return 130
    summary = format_summary(summarize(rows))
    summary_path = out.with_suffix(".md")
    summary_path.write_text(summary + "\n", encoding="utf-8")
    print(summary)
    print(f"\nrows: {out}\nsummary: {summary_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
