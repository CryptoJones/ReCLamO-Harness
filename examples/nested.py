"""Nested: per-department ticket logs that each need code *and* a semantic read.

    uv run python examples/nested.py --profile pluto --max-depth 1
    uv run python examples/nested.py --profile pluto --max-depth 2
    uv run python examples/nested.py --dump            # logs + truth, no model

The context is a dict ``{department: log}`` with about 12 departments of
~25K characters each (300K+ in total). Every log mixes ticket events with
noise, in one of four line formats that differ by department. A ticket is
*unresolved* when its latest event is not a close (open -> close -> reopen
counts as unresolved). The question asks, per department, how many unresolved
tickets complain about a damaged item, and which department has the most.

Each department is too large for one ``llm_query`` and needs three steps:
work out the format, replay the open/close/reopen events in code, then read
the surviving complaints, which are paraphrases that never contain the
category's words (the OOLONG-lite templates, so grep cannot classify them).
That is the shape of work a nested RLM (``rlm_query``) is meant for, and the
script exists to measure whether ``--max-depth 2`` helps or hurts.

Deterministic by seed; exact ground truth; scored by per-department absolute
error plus whether the "most" department is right. ``run()`` is importable.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import random
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import oolong_lite  # noqa: E402

from reclamo.client import LMClient  # noqa: E402
from reclamo.config import (  # noqa: E402
    APIKeyError,
    ConfigError,
    RLMConfig,
    load_config,
    resolve_api_key,
)
from reclamo.errors import RLMError  # noqa: E402
from reclamo.logger import TrajectoryLogger  # noqa: E402
from reclamo.rlm import RLM  # noqa: E402

TARGET = "damaged item"  # the category the question counts
DEPARTMENTS = [
    "Accounts", "Logistics", "Payroll", "Facilities", "Procurement", "Legal",
    "Marketing", "Warehouse", "Fulfilment", "Catalog", "Retail", "Wholesale",
    "Concierge", "Outreach", "Onboarding", "Analytics", "Compliance", "Studio",
    "Dispatch", "Registry",
]  # fmt: skip
FORMATS = ["syslog", "chat", "json", "kv"]
_NAMES = ["Priya", "Marcus", "Elena", "Tomas", "Aisha", "Jonah", "Mei", "Luis", "Hannah", "Omar"]
_QUARTER_START = datetime(2026, 7, 1)
_QUARTER_MINUTES = 92 * 24 * 60

# Noise lines per format. Numbers are filled in; "tickets" appears on purpose
# so a naive count of the word is wrong.
_NOISE: dict[str, list[str]] = {
    "syslog": [
        "INFO heartbeat ok load={load} queue={q}",
        "INFO digest mailed to {n} subscribers; {m} tickets touched today",
        "WARN worker-{w} restarted after {s}s without a heartbeat",
        "INFO cache refreshed in {s}ms ({n} entries)",
        "INFO rota: {name} on call until {hh}:00",
    ],
    "chat": [
        "sys: heartbeat, load {load}, {q} queued",
        "sys: digest out, {m} tickets touched, {n} readers",
        "sys: worker {w} came back after {s}s",
        "sys: {name} takes the desk at {hh}:00",
        "sys: index rebuilt, {n} entries in {s}ms",
    ],
    "json": [
        '{{"ts": "{ts}", "event": "metric", "load": {load}, "queue": {q}}}',
        '{{"ts": "{ts}", "event": "digest", "touched": {m}, "readers": {n}}}',
        '{{"ts": "{ts}", "event": "restart", "worker": {w}, "gap_s": {s}}}',
        '{{"ts": "{ts}", "event": "rota", "who": "{name}", "until": "{hh}:00"}}',
        '{{"ts": "{ts}", "event": "cache", "entries": {n}, "ms": {s}}}',
    ],
    "kv": [
        "evt=ping load={load} queue={q}",
        "evt=digest touched={m} readers={n}",
        "evt=restart worker={w} gap={s}s",
        "evt=rota who={name} until={hh}:00",
        "evt=cache entries={n} ms={s}",
    ],
}


@dataclass(frozen=True)
class TicketSpec:
    id: int
    who: str
    category: str
    text: str
    # minutes from quarter start, in order: open, then zero or more close/reopen
    events: tuple[tuple[str, int], ...]

    @property
    def unresolved(self) -> bool:
        return self.events[-1][0] != "close"


@dataclass
class Department:
    name: str
    fmt: str
    tickets: list[TicketSpec]
    noise_minutes: list[int]

    @property
    def truth(self) -> int:
        return sum(1 for t in self.tickets if t.unresolved and t.category == TARGET)

    @property
    def unresolved(self) -> int:
        return sum(1 for t in self.tickets if t.unresolved)


# --- generation -----------------------------------------------------------------


def _ticket(rng: random.Random, ids: set[int], weights: list[float], p_close: float) -> TicketSpec:
    while True:
        tid = rng.randint(1000, 9999)
        if tid not in ids:
            ids.add(tid)
            break
    category = rng.choices(oolong_lite.CATEGORIES, weights=weights)[0]
    text = oolong_lite.ticket_text(category, rng)
    t = rng.randrange(_QUARTER_MINUTES - 3 * 24 * 60)
    events: list[tuple[str, int]] = [("open", t)]
    if rng.random() < p_close:
        t += rng.randint(30, 2 * 24 * 60)
        events.append(("close", t))
        if rng.random() < 0.3:
            t += rng.randint(30, 24 * 60)
            events.append(("reopen", t))
            if rng.random() < 0.5:
                t += rng.randint(30, 24 * 60)
                events.append(("close", t))
    return TicketSpec(tid, rng.choice(_NAMES), category, text, tuple(events))


def generate(n_departments: int = 12, chars: int = 25_000, seed: int = 0) -> list[Department]:
    """Deterministic departments; the "most" department is made unique."""
    if not 1 <= n_departments <= len(DEPARTMENTS):
        raise ValueError(f"departments must be 1..{len(DEPARTMENTS)}")
    rng = random.Random(seed)
    names = rng.sample(DEPARTMENTS, n_departments)
    depts: list[Department] = []
    for i, name in enumerate(names):
        fmt = FORMATS[i % len(FORMATS)]
        ids: set[int] = set()
        # The damaged-item share varies a lot by department so counts differ.
        weights = [rng.uniform(0.6, 1.6) for _ in oolong_lite.CATEGORIES]
        weights[oolong_lite.CATEGORIES.index(TARGET)] = rng.uniform(0.3, 2.5)
        p_close = rng.uniform(0.4, 0.8)
        n_tickets = rng.randint(45, 60)
        tickets = [_ticket(rng, ids, weights, p_close) for _ in range(n_tickets)]
        d = Department(name, fmt, tickets, [])
        # Pad with noise until the rendered log reaches the target size.
        while len(render(d)) < chars:
            d.noise_minutes.extend(rng.randrange(_QUARTER_MINUTES) for _ in range(20))
        depts.append(d)

    # Break ties for "most" with an extra genuine ticket in the first leader.
    while True:
        counts = [d.truth for d in depts]
        top = max(counts)
        if counts.count(top) == 1:
            break
        d = depts[counts.index(top)]
        ids = {t.id for t in d.tickets}
        weights = [0.0] * len(oolong_lite.CATEGORIES)
        weights[oolong_lite.CATEGORIES.index(TARGET)] = 1.0
        d.tickets.append(_ticket(rng, ids, weights, p_close=0.0))

    check(depts)
    return depts


def check(depts: list[Department]) -> None:
    """Ticket texts must not contain category words (OOLONG-lite's guard)."""
    tickets = [oolong_lite.Ticket(t.id, t.category, t.text) for d in depts for t in d.tickets]
    oolong_lite.check_tickets(tickets)


# --- rendering ------------------------------------------------------------------


def _stamp(minutes: int, fmt: str) -> str:
    dt = _QUARTER_START + timedelta(minutes=minutes)
    if fmt == "syslog":
        return dt.strftime("%Y-%m-%dT%H:%M:%S")
    if fmt == "chat":
        return dt.strftime("[%m/%d %H:%M]")
    if fmt == "json":
        return dt.strftime("%Y-%m-%d %H:%M")
    return dt.strftime("%Y-%m-%dT%H:%M")


def _event_line(fmt: str, t: TicketSpec, kind: str, minutes: int) -> str:
    ts = _stamp(minutes, fmt)
    if fmt == "syslog":
        if kind == "open":
            return f"{ts} TICKET-{t.id} OPENED by {t.who}: {t.text}"
        return f"{ts} TICKET-{t.id} {'CLOSED' if kind == 'close' else 'REOPENED'}"
    if fmt == "chat":
        if kind == "open":
            return f"{ts} open #{t.id} ({t.who}) -- {t.text}"
        return f"{ts} {kind} #{t.id}"
    if fmt == "json":
        rec: dict[str, Any] = {"ts": ts, "event": kind, "id": t.id}
        if kind == "open":
            rec.update(who=t.who, text=t.text)
        return json.dumps(rec)
    verb = {"open": "new", "close": "done", "reopen": "again"}[kind]
    if kind == "open":
        return f'ts={ts} evt={verb} id={t.id} user={t.who} msg="{t.text}"'
    return f"ts={ts} evt={verb} id={t.id}"


def _noise_line(fmt: str, minutes: int, rng: random.Random) -> str:
    ts = _stamp(minutes, fmt)
    body = rng.choice(_NOISE[fmt]).format(
        ts=ts,
        load=round(rng.uniform(0.05, 0.95), 2),
        q=rng.randint(0, 40),
        n=rng.randint(10, 900),
        m=rng.randint(1, 30),
        w=rng.randint(1, 8),
        s=rng.randint(5, 900),
        hh=rng.randint(6, 22),
        name=rng.choice(_NAMES),
    )
    if fmt == "json":
        return body
    if fmt == "chat":
        return f"{ts} {body}"
    if fmt == "kv":
        return f"ts={ts} {body}"
    return f"{ts} {body}"


def render(d: Department) -> str:
    """The department's log: all events in time order, one per line."""
    rng = random.Random(f"{d.name}:{d.fmt}")  # noise wording only; truth is in the specs
    lines: list[tuple[int, int, str]] = []
    for t in d.tickets:
        for kind, minutes in t.events:
            lines.append((minutes, 0, _event_line(d.fmt, t, kind, minutes)))
    for minutes in d.noise_minutes:
        lines.append((minutes, 1, _noise_line(d.fmt, minutes, rng)))
    lines.sort(key=lambda x: (x[0], x[1]))
    return "\n".join(line for _, _, line in lines)


def build_context(depts: list[Department]) -> dict[str, str]:
    return {d.name: render(d) for d in depts}


def build_truth(depts: list[Department]) -> tuple[dict[str, int], str]:
    truth = {d.name: d.truth for d in depts}
    return truth, max(truth, key=lambda k: truth[k])


def build_query() -> str:
    return (
        "Each key of `context` is a department and its value is that department's ticket "
        "log for the quarter, one event per line. Departments use different log formats. "
        "A ticket is unresolved when its most recent event is not a close; a ticket that "
        "was closed and then reopened is unresolved again until it is closed. For every "
        "department, count the unresolved tickets whose complaint is about a damaged item "
        "(the goods arrived physically damaged), as opposed to billing, shipping delays, "
        "login problems or feature requests. Reply with one line per department in the "
        "form 'Department: count', then a last line 'most: Department' naming the "
        "department with the highest count."
    )


# --- scoring --------------------------------------------------------------------

_MOST = re.compile(r"\bmost\b\W*([A-Za-z][A-Za-z-]+)", re.IGNORECASE)


def parse_most(answer: str, departments: list[str]) -> str | None:
    """The department named after 'most', matched case-insensitively."""
    names = {d.lower(): d for d in departments}
    for m in _MOST.finditer(answer):
        word = m.group(1).lower()
        if word in names:
            return names[word]
    return None


def score(
    answer: str, truth: dict[str, int], most: str
) -> tuple[dict[str, int | None], dict[str, int], int, str | None, bool]:
    """Return (predicted, per-department abs error, total error, most predicted, most ok)."""
    departments = list(truth)
    predicted = oolong_lite.parse_counts(answer, departments)
    errors = {
        d: abs((predicted[d] if predicted[d] is not None else 0) - truth[d]) for d in departments
    }
    most_predicted = parse_most(answer, departments)
    return predicted, errors, sum(errors.values()), most_predicted, most_predicted == most


# --- running --------------------------------------------------------------------


def run(
    cfg: RLMConfig,
    client: Any,
    n_departments: int = 12,
    chars: int = 25_000,
    seed: int = 0,
    *,
    log_dir: str | None = None,
) -> dict[str, Any]:
    depts = generate(n_departments, chars, seed)
    context = build_context(depts)
    truth, most = build_truth(depts)
    logger = TrajectoryLogger(log_dir)
    started = time.monotonic()
    summary: dict[str, Any] = {
        "task": "nested",
        "departments": n_departments,
        "chars": sum(len(v) for v in context.values()),
        "formats": {d.name: d.fmt for d in depts},
        "max_depth": cfg.max_depth,
        "truth": truth,
        "most": most,
    }
    try:
        result = RLM(cfg, client, logger=logger).completion(context, build_query())
    except RLMError as exc:
        answer = exc.partial_answer or ""
        predicted, errors, total, most_predicted, most_ok = score(answer, truth, most)
        summary.update(
            answer=answer,
            predicted=predicted,
            errors=errors,
            total_error=total,
            most_predicted=most_predicted,
            most_correct=most_ok,
            error=str(exc),
            turns=None,
            child_turns=None,
            subcalls=None,
            tokens=None,
            elapsed=round(time.monotonic() - started, 2),
            stop_reason="error",
            trajectory=str(logger.path) if logger.path else None,
        )
        return summary
    predicted, errors, total, most_predicted, most_ok = score(result.answer, truth, most)
    summary.update(
        answer=result.answer,
        predicted=predicted,
        errors=errors,
        total_error=total,
        most_predicted=most_predicted,
        most_correct=most_ok,
        turns=result.iterations,
        child_turns=result.child_turns,
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
    parser.add_argument("--departments", type=int, default=12)
    parser.add_argument("--chars", type=int, default=25_000, help="per-department log size")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--max-depth", type=int, default=1)
    parser.add_argument("--max-timeout", type=float, default=600.0, help="seconds, whole run")
    parser.add_argument("--max-subcalls", type=int, default=None, help="per run (profile default)")
    parser.add_argument("--log-dir", default="runs")
    parser.add_argument("--json", action="store_true", help="print the summary as JSON")
    parser.add_argument("--dump", action="store_true", help="print the logs and truth; no model")
    args = parser.parse_args(argv)

    if args.dump:
        depts = generate(args.departments, args.chars, args.seed)
        for name, log in build_context(depts).items():
            print(f"===== {name} =====")
            print(log)
        truth, most = build_truth(depts)
        print()
        print("truth:", ", ".join(f"{d}={n}" for d, n in truth.items()))
        print("most:", most)
        print("unresolved (any category):", ", ".join(f"{d.name}={d.unresolved}" for d in depts))
        return 0

    try:
        cfg, client = build_client(args.profile, args.profiles)
    except (ConfigError, APIKeyError) as exc:
        print(f"nested: {exc}", file=sys.stderr)
        return 2
    overrides: dict[str, Any] = {"max_depth": args.max_depth, "max_timeout": args.max_timeout}
    if args.max_subcalls is not None:
        overrides["max_subcalls_per_run"] = args.max_subcalls
    cfg = dataclasses.replace(cfg, **overrides)
    client.cfg = cfg

    summary = run(cfg, client, args.departments, args.chars, args.seed, log_dir=args.log_dir)
    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        print(f"answer:       {summary['answer']!r}")
        print(f"truth:        {summary['truth']} most={summary['most']}")
        print(f"predicted:    {summary['predicted']} most={summary['most_predicted']}")
        print(f"errors:       {summary['errors']}")
        print(f"total error:  {summary['total_error']}; most correct: {summary['most_correct']}")
        print(f"turns:        {summary['turns']} (+{summary['child_turns']} child turns)")
        print(f"sub-calls:    {summary['subcalls']}")
        print(f"tokens:       {summary['tokens']}")
        print(f"elapsed:      {summary['elapsed']}s")
        print(f"trajectory:   {summary['trajectory']}")
    if summary.get("error"):
        print(f"error:        {summary['error']}", file=sys.stderr)
    return 0 if summary["total_error"] == 0 and summary["most_correct"] else 1


if __name__ == "__main__":
    sys.exit(main())
