"""Frozen independent evaluation (issue #22): the harness vs the plain model on tasks
written by other models.

    uv run python evals/independent/run_eval.py --profile pluto --sizes small
    uv run python evals/independent/run_eval.py --tasks GLaDOS --sizes medium \\
        --resume runs/independent-20261007T120000Z.json
    uv run python evals/independent/run_eval.py --summary-only runs/independent-....json
    uv run python evals/independent/run_eval.py --dry-run         # sizes and fit decisions

The tasks are the eight generators in ``fixed/active/``, each scored by **its own**
``score()``; nothing here writes questions or scores answers. The modes are the ones
``examples/bench.py`` defines, imported rather than copied:

- ``rlm``: the harness through the library API (``bench.run_rlm``).
- ``plain``: the whole context in one prompt, one call with thinking as the profile's
  root role sets it (16K output cap, capped by what fits), or ``does not fit`` without a
  call when the prompt exceeds the usable window (``bench.run_plain`` /
  ``bench.fit_decision``).
- ``plain-think`` / ``plain-nothink`` (opt-in): the same single call with thinking forced
  on / off, each its own row. Nothing chooses between attempts using the answer key
  (issue #57); rows written before that are best-of-2 and load per ``--legacy-plain``.

Every row is written as soon as it finishes; ``--resume FILE`` skips rows already present
with the same task, size, mode and seed (bench.py's semantics). A markdown summary is
written next to the JSON.

Freeze: the harness, prompts, profile defaults and bench.py are not changed for this
run. The meta block records HEAD, the frozen commit, and whether ``src/`` or
``examples/`` differ from it.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import importlib.util
import json
import statistics
import subprocess
import sys
import time
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "examples"))

import bench  # noqa: E402

from reclamo.config import APIKeyError, ConfigError, RLMConfig  # noqa: E402

FROZEN_COMMIT = "e17580f"
LANES = (
    "GLaDOS",
    "SHODAN",
    "TheDixieFlatline",
    "Cerebex",
    "Neuromancer",
    "SELMA",
    "MasterControl",
    "Multivac",
)
SIZES = ("small", "medium", "large")
MODES = ("rlm", "plain", "plain-think", "plain-nothink")
DEFAULT_MODES = ("rlm", "plain")
PLAIN_MODES = ("plain", "plain-think", "plain-nothink")
DEFAULT_MAX_TIMEOUT = 900.0
RowRunner = Callable[[str, str, str, int], dict[str, Any]]


# --- generators and manifest --------------------------------------------------------


def load_manifest(root: Path = HERE) -> dict[str, Any]:
    return json.loads((root / "manifest.json").read_text(encoding="utf-8"))


def load_generator(lane: str, manifest: dict[str, Any], root: Path = HERE) -> ModuleType:
    """Import the active generator for ``lane``; refuse it if its sha256 drifted."""
    active = manifest["generators"][lane]["active"]
    path = root / active["file"]
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != active["sha256"]:
        raise RuntimeError(f"{active['file']} does not match its pinned sha256")
    name = f"indep_active_{lane}"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def task_key(lane: str) -> str:
    """Name under which a lane is registered in ``bench.TASKS``."""
    return f"indep/{lane}"


def generator_scorer(gen: ModuleType) -> Callable[[str, Any], bench.Scored]:
    """Wrap the generator's own ``score()``; exact means score == 1.0."""

    def score(answer: str, truth: Any) -> bench.Scored:
        try:
            value = float(gen.score(answer or "", truth))
        except Exception as exc:  # a scorer crash is recorded, never hidden
            return bench.Scored(0.0, False, {"score_error": f"{type(exc).__name__}: {exc}"})
        return bench.Scored(value, value == 1.0, {})

    return score


def _no_build(_size: int, _seed: int) -> bench.Instance:
    raise RuntimeError("independent tasks are built by run_eval.build_instance")


def register(lane: str, gen: ModuleType) -> None:
    """Make ``lane`` a bench task so bench.run_rlm / run_plain can score it."""
    bench.TASKS[task_key(lane)] = bench.TaskSpec(
        task_key(lane), "size", "accuracy", _no_build, generator_scorer(gen)
    )


class Generators:
    """Lazy, cached access to the active generators (each registered with bench)."""

    def __init__(self, manifest: dict[str, Any], root: Path = HERE) -> None:
        self.manifest = manifest
        self.root = root
        self._mods: dict[str, ModuleType] = {}

    def get(self, lane: str) -> ModuleType:
        if lane not in self._mods:
            self._mods[lane] = load_generator(lane, self.manifest, self.root)
            register(lane, self._mods[lane])
        return self._mods[lane]

    def add(self, lane: str, mod: ModuleType) -> None:
        """Use ``mod`` for ``lane`` (tests)."""
        self._mods[lane] = mod
        register(lane, mod)


def build_instance(gens: Generators, lane: str, size: str, seed: int) -> bench.Instance:
    data = gens.get(lane).generate(seed, size)
    return bench.Instance(
        task_key(lane), size, seed, data["context"], data["question"], data["answer"], {}
    )  # type: ignore[arg-type]


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


# --- one row -------------------------------------------------------------------------


def run_row(
    cfg: RLMConfig,
    client: Any,
    gens: Generators,
    lane: str,
    size: str,
    mode: str,
    seed: int,
    log_dir: str | None,
    *,
    plain_max_tokens: int = bench.PLAIN_MAX_TOKENS,
) -> dict[str, Any]:
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}; expected one of {', '.join(MODES)}")
    inst = build_instance(gens, lane, size, seed)
    info = gens.manifest["generators"].get(lane, {})
    _fits, est, _usable = bench.fit_decision(cfg, inst.context, inst.query)
    row: dict[str, Any] = {
        "task": lane,
        "author_lane": lane,
        "author_vendor": info.get("vendor"),
        "author_model": info.get("model"),
        "active_source": info.get("active", {}).get("source"),
        "size": size,
        "mode": mode,
        "seed": seed,
        "chars": len(inst.context),
        "est_prompt_tokens": est,
        "question": inst.query,
        "truth": _jsonable(inst.truth),
        "started_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    if mode == "rlm":
        row["protocol"] = cfg.protocol
        row.update(bench.run_rlm(cfg, client, inst, log_dir))
    else:
        row.update(
            bench.run_plain(
                cfg,
                client,
                inst,
                truncated=False,
                plain_max_tokens=plain_max_tokens,
                enable_thinking=bench.PLAIN_THINKING[mode],
            )
        )
    return finish_row(row)


def finish_row(row: dict[str, Any]) -> dict[str, Any]:
    """Derived fields: exact, fits and the flattened harness counters (idempotent)."""
    score = row.get("score")
    row["exact"] = None if score is None else score == 1.0
    row["does_not_fit"] = row.get("stop_reason") == "does_not_fit"
    stats = row.get("stats") or {}
    for key in ("executions", "syntax_errors", "exec_errors", "final_rejections"):
        row[key] = stats.get(key)
    slips = stats.get("slips")
    row["slips"] = sum(slips.values()) if isinstance(slips, dict) else None
    return row


# --- grid and resume ---------------------------------------------------------------


def row_key(row: dict[str, Any]) -> tuple[str, str, str, int]:
    label = bench.mode_label(row["mode"], row.get("protocol"))
    return (row["task"], str(row["size"]), label, int(row["seed"]))


def plan(
    lanes: Iterable[str], sizes: Iterable[str], modes: Iterable[str], seeds: Iterable[int]
) -> list[tuple[str, str, str, int]]:
    """Seed, then size, then task: all small rows come before any medium row."""
    lanes, sizes, modes = list(lanes), list(sizes), list(modes)
    return [
        (lane, size, mode, seed)
        for seed in seeds
        for size in sizes
        for lane in lanes
        for mode in modes
    ]


def run_grid(
    runner: RowRunner,
    cells: Iterable[tuple[str, str, str, int]],
    *,
    rows: list[dict[str, Any]],
    on_row: Callable[[dict[str, Any]], None] | None = None,
    log: Callable[[str], None] = lambda _msg: None,
    protocol: str = "fence",
) -> list[dict[str, Any]]:
    """Run every cell not already in ``rows`` (bench.py's resume rule)."""
    done = {row_key(r) for r in rows}
    todo = [
        (lane, size, mode, seed)
        for lane, size, mode, seed in cells
        if (lane, size, bench.mode_label(mode, protocol), seed) not in done
    ]
    log(f"{len(todo)} rows to run, {len(done)} already present")
    for n, (lane, size, mode, seed) in enumerate(todo, 1):
        log(f"[{n}/{len(todo)}] {lane} {size} {mode} seed={seed} ...")
        row = runner(lane, size, mode, seed)
        rows.append(row)
        if on_row:
            on_row(row)
        log(f"    -> {describe_row(row)}")
    return rows


def describe_row(row: dict[str, Any]) -> str:
    if row.get("does_not_fit"):
        return (
            f"does not fit (est {row['est_prompt_tokens']:,} tokens > "
            f"{row['usable_tokens']:,} usable)"
        )
    score = row.get("score")
    bits = [
        f"score {score:.2f}" if score is not None else "score -",
        f"{row.get('turns')} turns",
        f"{row.get('subcalls')} sub-calls",
        f"{row.get('tokens')} tokens",
        f"{row.get('seconds')}s",
        str(row.get("stop_reason")),
    ]
    if row.get("error"):
        bits.append(row["error"])
    return ", ".join(bits)


def load_rows(
    path: Path, legacy: str = "best-of-2"
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Rows from a JSON file; pre-#57 best-of-2 plain rows are summarised per ``legacy``."""
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = [
        finish_row(bench.apply_legacy(r, "accuracy", legacy=legacy)) for r in data.get("rows", [])
    ]
    return data.get("meta", {}), rows


write_rows = bench.write_rows


# --- summary -----------------------------------------------------------------------


def _mean(values: list[float]) -> float | None:
    return round(statistics.fmean(values), 3) if values else None


def _median(values: Iterable[Any]) -> float | None:
    nums = [float(v) for v in values if v is not None]
    return round(statistics.median(nums), 1) if nums else None


def _order(rows: Iterable[dict[str, Any]]) -> tuple[list[str], list[str]]:
    lanes = {r["task"] for r in rows}
    ordered = [lane for lane in LANES if lane in lanes] + sorted(lanes - set(LANES))
    sizes = {str(r["size"]) for r in rows}
    return ordered, [s for s in SIZES if s in sizes] + sorted(sizes - set(SIZES))


def cell_stats(group: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate rows of one (task or set, size, mode)."""
    attempted = [r for r in group if not r.get("does_not_fit")]
    scores = [float(r["score"]) for r in attempted if r.get("score") is not None]
    return {
        "n": len(group),
        "attempted": len(attempted),
        "does_not_fit": len(group) - len(attempted),
        "mean_attempted": _mean(scores),
        # A prompt that does not fit is an answer of nothing: score 0 over all rows.
        "mean_all": _mean(scores + [0.0] * (len(group) - len(attempted))) if group else None,
        "exact": sum(1 for r in group if r.get("exact")),
        "errors": sum(1 for r in group if r.get("error")),
        "median_turns": _median(r.get("turns") for r in attempted),
        "median_subcalls": _median(r.get("subcalls") for r in attempted),
        "median_seconds": _median(r.get("seconds") for r in attempted),
        "median_tokens": _median(r.get("tokens") for r in attempted),
        "stop_reasons": sorted({str(r.get("stop_reason")) for r in group}),
        "est_prompt_tokens": max((r.get("est_prompt_tokens") or 0 for r in group), default=0)
        or None,
    }


def _groups(rows: Iterable[dict[str, Any]]) -> dict[tuple[str, str, str], list[dict[str, Any]]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for r in rows:
        label = bench.mode_label(r["mode"], r.get("protocol"))
        groups.setdefault((r["task"], str(r["size"]), label), []).append(r)
    return groups


def _num(value: float | None) -> str:
    if value is None:
        return "–"
    return f"{int(value):,}" if float(value).is_integer() else f"{value:,.1f}"


def _score_text(c: dict[str, Any]) -> str:
    if c["n"] == 0:
        return "–"
    if c["does_not_fit"] == c["n"]:
        return f"does not fit (~{c['est_prompt_tokens']:,} tokens)"
    text = f"{c['mean_attempted']:.2f}" if c["mean_attempted"] is not None else "no result"
    if c["n"] == 1:
        text += " (exact)" if c["exact"] else ""
    else:
        text += f" (exact {c['exact']}/{c['n']})"
    if c["does_not_fit"]:
        text += f"; {c['does_not_fit']} did not fit"
    if c["errors"]:
        text += f"; {c['errors']} error(s)"
    return text


def format_summary(rows: list[dict[str, Any]], manifest: dict[str, Any] | None = None) -> str:
    gens = (manifest or {}).get("generators", {})
    lanes, sizes = _order(rows)
    groups = _groups(rows)
    seeds = sorted({int(r["seed"]) for r in rows})
    present = {m for (_l, _s, m) in groups}
    plain_cols = [m for m in PLAIN_MODES if m in present] or ["plain"]
    out = [
        f"Seeds: {', '.join(map(str, seeds))}. Scores are each generator's own `score()` "
        "(1.0 = exact); multi-seed cells show the mean.",
        "",
        "| Task (author model) | Size | rlm score | "
        + " | ".join(plain_cols)
        + " | rlm turns | rlm sub-calls | rlm s | rlm stop |",
        "|---|---|---|" + "---|" * len(plain_cols) + "---|---|---|---|",
    ]
    for lane in lanes:
        model = gens.get(lane, {}).get("model")
        name = f"{lane} ({model})" if model else lane
        for size in sizes:
            rlm = groups.get((lane, size, "rlm"), [])
            plains = [groups.get((lane, size, m), []) for m in plain_cols]
            if not rlm and not any(plains):
                continue
            rc = cell_stats(rlm)
            plain_text = " | ".join(_score_text(cell_stats(g)) for g in plains)
            out.append(
                f"| {name} | {size} | {_score_text(rc)} | {plain_text} | "
                f"{_num(rc['median_turns'])} | {_num(rc['median_subcalls'])} | "
                f"{_num(rc['median_seconds'])} | {', '.join(rc['stop_reasons']) or '–'} |"
            )
    out += [
        "",
        "| Size | Mode | Rows | Mean score (attempted) | Mean score (all; no fit = 0) | Exact | "
        "Does not fit | Errors | Median s |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for size in sizes:
        for mode in ("rlm", "rlm:tools", *PLAIN_MODES):
            group = [r for (_l, s, m), g in groups.items() if s == size and m == mode for r in g]
            if not group:
                continue
            c = cell_stats(group)
            mean_att = f"{c['mean_attempted']:.2f}" if c["mean_attempted"] is not None else "–"
            out.append(
                f"| {size} | {mode} | {c['n']} | {mean_att} | {c['mean_all']:.2f} | "
                f"{c['exact']}/{c['n']} | {c['does_not_fit']} | {c['errors']} | "
                f"{_num(c['median_seconds'])} |"
            )
    note = bench.legacy_note(rows)
    if note:
        out += ["", note]
    return "\n".join(out)


def format_dry_run(
    cfg: RLMConfig, gens: Generators, cells: Iterable[tuple[str, str, str, int]]
) -> str:
    lines = []
    seen: dict[tuple[str, str, int], tuple[int, bool, int]] = {}
    for lane, size, mode, seed in cells:
        if (lane, size, seed) not in seen:
            inst = build_instance(gens, lane, size, seed)
            fits, est, _ = bench.fit_decision(cfg, inst.context, inst.query)
            seen[(lane, size, seed)] = (len(inst.context), fits, est)
        chars, fits, est = seen[(lane, size, seed)]
        verdict = ("fits" if fits else "does not fit") if mode in PLAIN_MODES else ""
        lines.append(
            f"{lane:17} {size:7} {mode:13} seed={seed}  {chars:>10,} chars ~{est:>7,} tokens  "
            f"{verdict}"
        )
    return "\n".join(lines)


# --- provenance ----------------------------------------------------------------------


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO), *args], capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.stdout.strip()


def provenance(frozen: str = FROZEN_COMMIT) -> dict[str, Any]:
    """HEAD, the frozen commit, and whether the harness differs from it on disk."""
    changed = _git("diff", "--name-only", frozen, "--", "src", "examples", "pyproject.toml")
    return {
        "head": _git("rev-parse", "HEAD"),
        "frozen_commit": _git("rev-parse", frozen) or frozen,
        "harness_changed_since_frozen": None if changed is None else changed.splitlines(),
    }


# --- CLI -----------------------------------------------------------------------------


def _csv(value: str, allowed: Iterable[str], what: str) -> list[str]:
    items = [v.strip() for v in value.split(",") if v.strip()]
    allowed = list(allowed)
    bad = [v for v in items if v not in allowed]
    if bad or not items:
        raise ValueError(f"unknown {what} {', '.join(bad)}; expected {', '.join(allowed)}")
    return items


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--profile", default="pluto")
    parser.add_argument("--profiles", default=None, metavar="FILE")
    parser.add_argument("--tasks", default=",".join(LANES), help="comma-separated lanes")
    parser.add_argument("--sizes", default=",".join(SIZES), help="comma-separated sizes")
    parser.add_argument(
        "--modes",
        default=",".join(DEFAULT_MODES),
        help=f"comma-separated subset of {', '.join(MODES)} (default: %(default)s)",
    )
    parser.add_argument("--seed-list", default="0", help="comma-separated seeds (default 0)")
    parser.add_argument("--out", default=None, metavar="FILE", help="JSON rows (default runs/)")
    parser.add_argument("--resume", default=None, metavar="FILE", help="continue this JSON")
    parser.add_argument("--summary-only", default=None, metavar="FILE", help="summarise; no runs")
    parser.add_argument(
        "--legacy-plain",
        choices=bench.LEGACY_PLAIN,
        default="best-of-2",
        help="how plain rows written before issue #57 (best of thinking on/off, chosen on "
        "the truth) are summarised: as recorded (default) or as one single variant",
    )
    parser.add_argument("--log-dir", default="runs", help="trajectory directory (default runs/)")
    parser.add_argument(
        "--max-timeout",
        type=float,
        default=DEFAULT_MAX_TIMEOUT,
        help="seconds per RLM run (default %(default)s)",
    )
    parser.add_argument(
        "--plain-max-tokens",
        type=int,
        default=bench.PLAIN_MAX_TOKENS,
        help="output budget for plain calls, capped by what fits (default %(default)s)",
    )
    parser.add_argument(
        "--prompt-version",
        choices=("v0.1", "v0.2"),
        default=None,
        help="reclamo root prompt version (default: the profile's, v0.2); v0.1 reproduces "
        "the published results",
    )
    parser.add_argument("--dry-run", action="store_true", help="print the plan; call no model")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    err = sys.stderr
    manifest = load_manifest()

    if args.summary_only:
        _meta, rows = load_rows(Path(args.summary_only), args.legacy_plain)
        print(format_summary(rows, manifest))
        return 0

    try:
        lanes = _csv(args.tasks, LANES, "task(s)")
        sizes = _csv(args.sizes, SIZES, "size(s)")
        modes = _csv(args.modes, MODES, "mode(s)")
        seeds = [int(s) for s in args.seed_list.split(",") if s.strip()]
    except ValueError as exc:
        print(f"run_eval: {exc}", file=err)
        return 2

    try:
        from reclamo.config import load_config

        cfg = load_config(args.profile, args.profiles)
        cfg = dataclasses.replace(cfg, max_timeout=args.max_timeout)
        if args.prompt_version:
            cfg = dataclasses.replace(cfg, prompt_version=args.prompt_version)
    except ConfigError as exc:
        print(f"run_eval: {exc}", file=err)
        return 2

    gens = Generators(manifest)
    cells = plan(lanes, sizes, modes, seeds)
    if args.dry_run:
        print(format_dry_run(cfg, gens, cells))
        return 0

    try:
        from reclamo.client import LMClient
        from reclamo.config import resolve_api_key

        client = LMClient(cfg, resolve_api_key(cfg))
    except APIKeyError as exc:
        print(f"run_eval: {exc}", file=err)
        return 2

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    rows: list[dict[str, Any]] = []
    meta: dict[str, Any] = {}
    if args.resume:
        meta, rows = load_rows(Path(args.resume), args.legacy_plain)
        conflict = bench.legacy_resume_conflict(rows, modes)
        if conflict:
            print(
                f"run_eval: {args.resume} holds best-of-2 {', '.join(conflict)} rows from "
                "before issue #57; resuming would skip those cells. Write the new rows to a "
                "new file, or drop those modes.",
                file=err,
            )
            return 2
    out = Path(args.out or args.resume or Path(args.log_dir) / f"independent-{stamp}.json")
    meta = {
        **meta,
        "issue": 22,
        "profile": cfg.name,
        "model": cfg.root.model,
        "base_url": cfg.base_url,
        "protocol": cfg.protocol,
        "max_depth": cfg.max_depth,
        "max_iterations": cfg.max_iterations,
        "max_timeout": cfg.max_timeout,
        "context_tokens": cfg.context_tokens,
        "usable_tokens": bench.usable_tokens(cfg),
        "subcall_chars": cfg.effective_subcall_chars,
        "prompt_version": cfg.prompt_version,
        "root_max_tokens": cfg.root.max_tokens,
        "plain_max_tokens": args.plain_max_tokens,
        "plain_rule": f"bench.run_plain: {bench.PLAIN_RULE}",
        "root_enable_thinking": cfg.root.enable_thinking,
        "token_estimate": "bench.estimate_tokens: one token per digit, else chars/3.5",
        "active_sha256": {lane: manifest["generators"][lane]["active"]["sha256"] for lane in LANES},
        "created": meta.get("created", stamp),
        "updated": stamp,
    }
    meta.setdefault("batches", [])
    meta["batches"].append(
        {
            "at": stamp,
            "tasks": lanes,
            "sizes": sizes,
            "modes": modes,
            "seeds": seeds,
            **provenance(),
        }
    )

    def runner(lane: str, size: str, mode: str, seed: int) -> dict[str, Any]:
        return run_row(
            cfg,
            client,
            gens,
            lane,
            size,
            mode,
            seed,
            args.log_dir,
            plain_max_tokens=args.plain_max_tokens,
        )

    def save(_row: dict[str, Any]) -> None:
        write_rows(out, meta, rows)

    def log(message: str) -> None:
        stamp_now = time.strftime("%H:%M:%S")
        print(f"{stamp_now} {message}", file=err, flush=True)

    write_rows(out, meta, rows)
    try:
        run_grid(runner, cells, rows=rows, on_row=save, log=log, protocol=cfg.protocol)
    except KeyboardInterrupt:
        print(f"run_eval: interrupted; {len(rows)} rows saved in {out}", file=err)
        return 130
    summary = format_summary(rows, manifest)
    summary_path = out.with_suffix(".md")
    summary_path.write_text(summary + "\n", encoding="utf-8")
    print(summary)
    print(f"\nrows: {out}\nsummary: {summary_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
