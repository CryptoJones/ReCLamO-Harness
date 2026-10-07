"""Unit tests for examples/bench.py and examples/longdoc_qa.py. No model is called."""

from __future__ import annotations

import importlib
import json
import math
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import make_config
from tests.mocklm import MockLM

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
sys.path.insert(0, str(EXAMPLES))

bench = importlib.import_module("bench")
needle = importlib.import_module("needle")
qa = importlib.import_module("longdoc_qa")


# --- longdoc_qa generator ---------------------------------------------------------


def test_document_is_deterministic_per_seed() -> None:
    a, b = qa.generate_document(20, seed=3), qa.generate_document(20, seed=3)
    assert a.text == b.text and a.questions == b.questions
    assert qa.generate_document(20, seed=4).text != a.text


@pytest.mark.parametrize("seed", [0, 1, 2, 7])
def test_document_facts_are_unique_and_scattered(seed: int) -> None:
    doc = qa.generate_document(40, seed=seed)
    assert doc.text.count("## Week ") == 40
    sentences = re.split(r"(?<=[.!?])\s+|\n+", doc.text)
    for project, owner in doc.owners.items():
        pair_lines = [s for s in sentences if project in s and owner in s]
        assert len(pair_lines) == 1, (project, pair_lines)  # only the owner sentence pairs them
        owner_sentences = {t.format(person=owner, project=project) for t in qa.OWNER_TEMPLATES}
        assert pair_lines[0] in owner_sentences
    for person, city in doc.offices.items():
        office_lines = [s for s in sentences if person in s and city in s]
        assert len(office_lines) == 1, (person, office_lines)
    assert len(set(doc.owners.values())) == len(doc.owners)  # one project per owner
    for q in doc.questions:
        s_own, s_off = doc.placement[q.project]
        assert abs(s_own - s_off) >= 40 // 5
        assert doc.offices[doc.owners[q.project]] == q.answer
    qa.check_document(doc)


def test_check_document_rejects_a_greppable_answer() -> None:
    doc = qa.generate_document(10, seed=0)
    q = doc.questions[0]
    doc.text += f"\n\n## Week 11 digest: leak\n{q.project} is run from {q.answer}."
    with pytest.raises(AssertionError, match="share a sentence"):
        qa.check_document(doc)


def test_too_few_sections_rejected() -> None:
    with pytest.raises(ValueError):
        qa.generate_document(3)


@pytest.mark.parametrize(
    "answer, expected",
    [
        ("1: Lisbon\n2: Oslo\n3: Kyoto", {1: "Lisbon", 2: "Oslo", 3: "Kyoto"}),
        ("Q1. Lisbon\nQuestion 2 - Oslo\n3) Kyoto", {1: "Lisbon", 2: "Oslo", 3: "Kyoto"}),
        (
            "Here you go:\n1: **Lisbon**\n2: Oslo (the office)\n",
            {1: "**Lisbon**", 2: "Oslo (the office)"},
        ),
        ("1: Lisbon\n1: Oslo", {1: "Lisbon"}),  # first answer per number wins
        ("9: Lisbon", {}),  # out of range
    ],
)  # fmt: skip
def test_parse_answers(answer: str, expected: dict[int, str]) -> None:
    assert qa.parse_answers(answer, 3) == expected


def test_parse_answers_lone_reply_counts_for_single_question() -> None:
    assert qa.parse_answers("Lisbon", 1) == {1: "Lisbon"}
    assert qa.parse_answers("Lisbon", 3) == {}


def test_is_correct_is_exact_on_the_city() -> None:
    assert qa.is_correct("Lisbon", "Lisbon")
    assert qa.is_correct("The office is in lisbon.", "Lisbon")
    assert not qa.is_correct("Lisbon or Oslo", "Lisbon")  # hedging is wrong
    assert not qa.is_correct("Oslo", "Lisbon")
    assert not qa.is_correct("", "Lisbon")


def test_score_fraction() -> None:
    doc = qa.generate_document(12, seed=1)
    truth = [q.answer for q in doc.questions]
    perfect = "\n".join(f"{i}: {c}" for i, c in enumerate(truth, 1))
    assert qa.score(perfect, doc.questions) == ([True, True, True], 1.0)
    partial = f"1: {truth[0]}\n2: nowhere\n3: {truth[2]}"
    marks, fraction = qa.score(partial, doc.questions)
    assert marks == [True, False, True] and fraction == pytest.approx(2 / 3)
    assert qa.score("", doc.questions) == ([False, False, False], 0.0)


def test_query_names_every_question() -> None:
    doc = qa.generate_document(12, seed=2)
    query = qa.build_query(doc.questions)
    for q in doc.questions:
        assert q.text in query
    assert "<number>: <city>" in query


def test_dump_runs_without_a_model() -> None:
    proc = subprocess.run(
        [sys.executable, str(EXAMPLES / "longdoc_qa.py"), "--dump", "--sections", "6"],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "RECLAMO_API_KEY": ""},
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.count("## Week ") == 6
    assert "answer 1: " in proc.stdout


# --- needle position ------------------------------------------------------------------


def test_needle_position_is_honoured() -> None:
    for position, expected in ((0.0, 0), (0.5, 50), (1.0, 99)):
        _, _, line = needle.build_haystack(100, seed=1, position=position)
        assert line == expected
    with pytest.raises(ValueError):
        needle.build_haystack(10, position=1.5)


def test_bench_needle_cycles_positions_by_seed() -> None:
    lines = [bench.build_instance("needle", 100, seed).meta["needle_line"] for seed in range(3)]
    assert lines == [5, 50, 95]
    assert bench.build_instance("needle", 100, 3).meta["needle_position"] == 0.05


# --- fit decision and truncation ------------------------------------------------------


def test_fit_decision_uses_window_minus_output_reserve() -> None:
    cfg = make_config("http://x")
    cfg.context_tokens = 1000
    cfg.root.max_tokens = 200  # 800 usable tokens = 2800 chars
    assert bench.usable_tokens(cfg) == 800
    query = "q?"
    overhead = len("".join(m["content"] for m in bench.plain_messages("", query)))
    small = "x" * (2800 - overhead - 10)
    fits, est, budget = bench.fit_decision(cfg, small, query)
    assert fits and budget == 800 and est <= 800
    big = "x" * 2900
    fits, est, _ = bench.fit_decision(cfg, big, query)
    assert not fits and est > 800


def test_estimate_tokens_counts_digits_one_each() -> None:
    assert bench.estimate_tokens("") == 0
    assert bench.estimate_tokens("abcdefg") == 2  # 7 chars / 3.5
    assert bench.estimate_tokens("1234567") == 7
    assert bench.estimate_tokens("record 12: value 345") == 5 + math.ceil(15 / 3.5)


def test_truncate_to_fit_keeps_the_head_and_fits() -> None:
    cfg = make_config("http://x")
    cfg.context_tokens = 1000
    cfg.root.max_tokens = 200
    context = "".join(f"line {i}\n" for i in range(2000))
    cut, kept = bench.truncate_to_fit(cfg, context, "q?")
    assert context.startswith(cut) and 0 < kept < 1
    assert bench.fit_decision(cfg, cut, "q?")[0]
    whole, kept = bench.truncate_to_fit(cfg, "short", "q?")
    assert whole == "short" and kept == 1.0


def test_plain_mode_records_does_not_fit_without_calling_the_model() -> None:
    cfg = make_config("http://x")
    cfg.context_tokens = 500
    cfg.root.max_tokens = 100
    lm = MockLM(root=[])  # any call would raise "script exhausted"
    row = bench.run_row(cfg, lm, "needle", 500, "plain", 0, None)
    assert row["stop_reason"] == "does_not_fit" and row["fits"] is False
    assert row["score"] is None and row["seconds"] is None
    assert row["est_prompt_tokens"] > row["usable_tokens"] == 400
    assert lm.calls == []


def test_plain_truncated_mode_calls_with_a_cut_context() -> None:
    cfg = make_config("http://x")
    cfg.context_tokens = 2000
    cfg.root.max_tokens = 100
    inst = bench.build_instance("needle", 500, 2)  # needle near the end: cut away
    lm = MockLM(root=["I cannot find it", "Not in the document"])
    row = bench.run_row(cfg, lm, "needle", 500, "plain_truncated", 2, None)
    assert row["mode"] == "plain_truncated" and 0 < row["kept_fraction"] < 1
    sent = lm.root_calls[0]["messages"][-1]["content"]
    assert inst.truth not in sent and sent.startswith("=== DOCUMENT ===\nrecord 0:")
    assert row["score"] == 0.0 and row["correct"] is False and row["turns"] == 1
    assert row["chosen"] == "thinking" and set(row["variants"]) == {"thinking", "nothink"}


# --- rows through the library API (MockLM, real subprocess REPL) ----------------------


def test_run_row_plain_scores_oolong() -> None:
    cfg = make_config("http://x")
    inst = bench.build_instance("oolong_lite", 20, 0)
    perfect = "\n".join(f"{cat}: {n}" for cat, n in inst.truth.items())
    off_by_two = perfect.replace(f": {inst.truth['billing']}", f": {inst.truth['billing'] + 2}", 1)
    lm = MockLM(root=[off_by_two, perfect])  # thinking variant first, then thinking off
    row = bench.run_row(cfg, lm, "oolong_lite", 20, "plain", 0, None)
    assert row["fits"] and row["score"] == 0.0 and row["correct"] is True
    assert row["chosen"] == "nothink" and row["variants"]["thinking"]["score"] == 2.0
    assert row["stop_reason"] == "stop" and row["tokens"] == 15 and row["subcalls"] == 0
    assert row["seconds_both"] == 0.0
    sent = lm.root_calls[0]["messages"]
    assert sent[0]["role"] == "system" and "Ticket 1: " in sent[1]["content"]
    assert [c["enable_thinking"] for c in lm.root_calls] == [True, False]


def test_run_row_rlm_needle_with_scripted_model(tmp_path: Path) -> None:
    cfg = make_config("http://x")
    inst = bench.build_instance("needle", 30, 1)
    lm = MockLM(root=["```repl\nprint(len(context))\n```", f"FINAL({inst.truth})"])
    row = bench.run_row(cfg, lm, "needle", 30, "rlm", 1, str(tmp_path))
    assert row["correct"] is True and row["score"] == 1.0
    assert row["turns"] == 2 and row["subcalls"] == 0 and row["stop_reason"] == "final"
    assert row["trajectory"] and Path(row["trajectory"]).exists()
    assert row["needle_line"] == 15 and row["chars"] == len(inst.context)


def test_run_row_rlm_records_a_failed_run() -> None:
    cfg = make_config("http://x")

    class Boom:
        def complete(self, *_a: Any, **_k: Any) -> Any:
            raise RuntimeError("endpoint down")

    row = bench.run_row(cfg, Boom(), "longdoc_qa", 6, "rlm", 0, None)
    assert row["stop_reason"] == "error" and "endpoint down" in row["error"]
    assert row["score"] == 0.0 and row["turns"] is None


def test_unknown_mode_rejected() -> None:
    with pytest.raises(ValueError, match="unknown mode"):
        bench.run_row(make_config("http://x"), MockLM([]), "needle", 10, "magic", 0, None)


# --- grid, resume, output ---------------------------------------------------------


def test_parse_grid() -> None:
    assert bench.parse_grid(["needle:10,1_000", "oolong_lite:5", "needle:10"]) == [
        ("needle", 10),
        ("needle", 1000),
        ("oolong_lite", 5),
    ]
    for bad in ("needle", "nope:3", "needle:x", "needle:0", "needle:"):
        with pytest.raises(ValueError):
            bench.parse_grid([bad])


def test_plan_order_is_task_then_mode_then_seed() -> None:
    cells = bench.plan([("needle", 1), ("needle", 2)], ["rlm", "plain"], [0, 1])
    assert cells[:3] == [
        ("needle", 1, "rlm", 0),
        ("needle", 1, "rlm", 1),
        ("needle", 1, "plain", 0),
    ]
    assert len(cells) == 8


def _stub_runner(calls: list[tuple[str, int, str, int]]) -> bench.RowRunner:
    def runner(task: str, size: int, mode: str, seed: int) -> dict[str, Any]:
        calls.append((task, size, mode, seed))
        return {
            "task": task,
            "size": size,
            "mode": mode,
            "seed": seed,
            "score": 1.0,
            "correct": True,
            "turns": 2,
            "subcalls": 0,
            "tokens": 100,
            "seconds": 1.0,
            "stop_reason": "final",
            "error": None,
        }

    return runner


def test_run_grid_skips_rows_already_present_and_saves_each_row(tmp_path: Path) -> None:
    existing = [
        {"task": "needle", "size": 10, "mode": "rlm", "seed": 0, "score": 0.0, "correct": False,
         "turns": 1, "subcalls": 0, "tokens": 1, "seconds": 1.0, "stop_reason": "final"},
        {"task": "needle", "size": 10, "mode": "plain", "seed": 1, "score": 1.0, "correct": True,
         "turns": 1, "subcalls": 0, "tokens": 1, "seconds": 1.0, "stop_reason": "stop"},
    ]  # fmt: skip
    out = tmp_path / "bench.json"
    bench.write_rows(out, {"created": "t"}, existing)
    meta, rows = bench.load_rows(out)
    assert meta == {"created": "t"} and rows == existing

    calls: list[tuple[str, int, str, int]] = []
    saved: list[int] = []
    bench.run_grid(
        _stub_runner(calls),
        [("needle", 10)],
        ["rlm", "plain"],
        [0, 1],
        rows=rows,
        on_row=lambda _r: saved.append(len(rows)),
    )
    assert calls == [("needle", 10, "rlm", 1), ("needle", 10, "plain", 0)]
    assert saved == [3, 4] and len(rows) == 4
    # A second pass over the same grid has nothing left to do.
    calls.clear()
    bench.run_grid(_stub_runner(calls), [("needle", 10)], ["rlm", "plain"], [0, 1], rows=rows)
    assert calls == []


def test_write_rows_is_atomic_and_round_trips(tmp_path: Path) -> None:
    out = tmp_path / "deep" / "bench.json"
    bench.write_rows(out, {"m": 1}, [{"task": "needle", "size": 1, "mode": "rlm", "seed": 0}])
    assert out.exists() and not out.with_suffix(".json.tmp").exists()
    assert json.loads(out.read_text())["meta"] == {"m": 1}


# --- summary --------------------------------------------------------------------------


def _row(task: str, size: int, mode: str, seed: int, **fields: Any) -> dict[str, Any]:
    base = {
        "task": task, "size": size, "mode": mode, "seed": seed, "score": 1.0, "correct": True,
        "turns": 3, "subcalls": 2, "tokens": 1000, "seconds": 10.0, "stop_reason": "final",
        "error": None,
    }  # fmt: skip
    base.update(fields)
    return base


def test_summarize_mean_stdev_and_medians() -> None:
    rows = [
        _row("oolong_lite", 100, "rlm", 0, score=0.0, correct=True, seconds=50.0, subcalls=1),
        _row("oolong_lite", 100, "rlm", 1, score=4.0, correct=False, seconds=70.0, subcalls=2),
        _row("oolong_lite", 100, "rlm", 2, score=2.0, correct=False, seconds=60.0, subcalls=6),
        _row(
            "oolong_lite",
            100,
            "plain",
            0,
            score=1.0,
            correct=False,
            subcalls=0,
            turns=1,
            stop_reason="stop",
        ),  # fmt: skip
        _row(
            "needle",
            10_000,
            "plain",
            0,
            score=None,
            correct=None,
            seconds=None,
            turns=None,
            subcalls=None,
            tokens=None,
            stop_reason="does_not_fit",
            est_prompt_tokens=73_745,
            usable_tokens=28_672,
        ),  # fmt: skip
        _row("needle", 10_000, "rlm", 0, score=1.0),
        _row(
            "needle",
            10_000,
            "rlm",
            1,
            score=0.0,
            correct=False,
            error="RLMTimeout: x",
            stop_reason="error",
            turns=None,
            subcalls=None,
            tokens=None,
        ),  # fmt: skip
        _row(
            "longdoc_qa",
            100,
            "rlm",
            0,
            score=2 / 3,
            correct=False,
            per_question=[True, True, False],
        ),  # fmt: skip
        _row("longdoc_qa", 100, "rlm", 1, score=1.0, per_question=[True, True, True]),
    ]
    cells = {(c.task, c.size, c.mode): c for c in bench.summarize(rows)}
    assert list(cells) == [
        ("needle", 10_000, "rlm"),
        ("needle", 10_000, "plain"),
        ("oolong_lite", 100, "rlm"),
        ("oolong_lite", 100, "plain"),
        ("longdoc_qa", 100, "rlm"),
    ]
    o = cells[("oolong_lite", 100, "rlm")]
    assert o.n == 3 and o.mean == 2.0 and o.stdev == 2.0 and o.exact == 1
    assert o.median_seconds == 60.0 and o.median_subcalls == 2.0 and o.metric == "abs_error"
    p = cells[("oolong_lite", 100, "plain")]
    assert p.n == 1 and p.stdev == 0.0 and p.stop_reasons == {"stop": 1}
    nf = cells[("needle", 10_000, "plain")]
    assert nf.does_not_fit == 1 and nf.mean is None and nf.est_prompt_tokens == 73_745
    nr = cells[("needle", 10_000, "rlm")]
    assert nr.mean == 0.5 and nr.errors == 1 and nr.stop_reasons == {"error": 1, "final": 1}
    q = cells[("longdoc_qa", 100, "rlm")]
    assert q.questions_correct == 5 and q.questions_total == 6 and q.mean == round(5 / 6, 3)

    table = bench.format_summary(cells.values())
    lines = table.splitlines()
    assert lines[0].startswith("| Task | Size | Mode | n | Result")
    assert (
        "| oolong_lite | 100 tickets | rlm | 3 | abs error 2.0 ± 2.0 (exact 1/3) | 60 | 3 | 2 |"
        in table
    )
    assert "does not fit (~73,745 tokens > 28,672 usable)" in table
    assert "| 0.50 ± 0.71 (1/2 found) |" in table and "error, final; 1 error(s)" in table
    assert "0.83 ± 0.24 (5/6 questions)" in table


def test_describe_row() -> None:
    assert "does not fit" in bench.describe_row(
        {
            "task": "needle",
            "stop_reason": "does_not_fit",
            "est_prompt_tokens": 5,
            "usable_tokens": 1,
        }
    )
    text = bench.describe_row(_row("oolong_lite", 1, "rlm", 0, score=3.0, error="boom"))
    assert text.startswith("abs error 3, 3 turns, 2 sub-calls, 1000 tokens, 10.0s, final, boom")


# --- CLI ------------------------------------------------------------------------------


def _cli(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(EXAMPLES / "bench.py"), *args],
        capture_output=True,
        text=True,
        env=env or {"PATH": "/usr/bin:/bin", "RECLAMO_API_KEY": ""},
    )


def test_help_runs() -> None:
    proc = _cli("--help")
    assert proc.returncode == 0 and "--resume" in proc.stdout and "--grid" in proc.stdout


def test_dry_run_lists_cells_and_fit_decisions() -> None:
    proc = _cli(
        "--dry-run", "--grid", "needle:20,200000", "--modes", "rlm,plain", "--seeds", "2",
        "--profile", "openai-compatible",
    )  # fmt: skip
    assert proc.returncode == 0, proc.stderr
    lines = proc.stdout.strip().splitlines()
    assert len(lines) == 8
    assert any("needle" in ln and "20 plain" in ln and ln.endswith("fits") for ln in lines)
    assert any("200,000 plain" in ln and ln.endswith("does not fit") for ln in lines)


def test_summary_only_reads_an_existing_file(tmp_path: Path) -> None:
    out = tmp_path / "b.json"
    bench.write_rows(out, {}, [_row("needle", 5, "rlm", 0)])
    proc = _cli("--summary-only", str(out))
    assert proc.returncode == 0, proc.stderr
    assert "| needle | 5 lines | rlm | 1 | 1.00 ± 0.00 (1/1 found) |" in proc.stdout


def test_bad_grid_and_mode_exit_2() -> None:
    assert _cli("--dry-run", "--grid", "nope:1", "--profile", "openai-compatible").returncode == 2
    assert _cli("--dry-run", "--modes", "magic", "--profile", "openai-compatible").returncode == 2


def test_plain_output_budget_is_generous_but_fits_beside_the_prompt() -> None:
    cfg = make_config("http://x")  # 32768 window, root max_tokens 4096
    assert bench.plain_output_tokens(cfg, 2_000, 16_384) == 16_384
    assert bench.plain_output_tokens(cfg, 24_000, 16_384) == 8_768
    assert bench.plain_output_tokens(cfg, 30_000, 16_384) == 4_096  # never below the root cap


def test_plain_passes_the_output_budget_and_keeps_both_variants() -> None:
    from reclamo.client import Completion, Usage

    cfg = make_config("http://x")
    inst = bench.build_instance("needle", 20, 0)
    starved = Completion(
        content="I am still thinking about which line",
        reasoning="I am still thinking about which line",
        usage=Usage(100, 4096, 4196),
        finish_reason="length",
        latency=5.0,
        content_from_reasoning=True,
    )
    lm = MockLM(root=[starved, f"The passphrase is {inst.truth}"])
    row = bench.run_row(cfg, lm, "needle", 20, "plain", 0, None, plain_max_tokens=16_384)
    assert row["plain_max_tokens"] == 16_384
    assert row["chosen"] == "nothink" and row["score"] == 1.0 and row["stop_reason"] == "stop"
    thinking = row["variants"]["thinking"]
    assert thinking["stop_reason"] == "length" and thinking["content_from_reasoning"]
    assert thinking["score"] == 0.0 and thinking["tokens"] == 4196
    assert row["seconds"] == 0.0 and row["seconds_both"] == 5.0
    assert [c["enable_thinking"] for c in lm.root_calls] == [True, False]


def test_better_variant_rules() -> None:
    tie = {"thinking": {"score": 1.0, "seconds": 150.0}, "nothink": {"score": 1.0, "seconds": 9.0}}
    assert bench.better_variant("accuracy", tie) == "nothink"  # tie on score -> faster
    tie["nothink"]["seconds"] = 150.0
    assert bench.better_variant("accuracy", tie) == "thinking"  # full tie -> thinking
    assert (
        bench.better_variant("accuracy", {"thinking": {"score": 0.0}, "nothink": {"score": 0.5}})
        == "nothink"
    )
    assert (
        bench.better_variant("abs_error", {"thinking": {"score": 4.0}, "nothink": {"score": 1.0}})
        == "nothink"
    )
    assert (
        bench.better_variant("abs_error", {"thinking": {"score": None}, "nothink": {"score": 9.0}})
        == "nothink"
    )
    assert (
        bench.better_variant("abs_error", {"thinking": {"score": 2.0}, "nothink": {"score": None}})
        == "thinking"
    )


def test_load_rows_reapplies_the_choice_rule(tmp_path: Path) -> None:
    row = _row("needle", 5, "plain", 0, chosen="thinking", seconds=150.0)
    row["variants"] = {
        "thinking": {"score": 1.0, "correct": True, "seconds": 150.0, "stop_reason": "stop"},
        "nothink": {"score": 1.0, "correct": True, "seconds": 9.0, "stop_reason": "stop"},
    }
    out = tmp_path / "b.json"
    bench.write_rows(out, {}, [row, _row("needle", 5, "rlm", 0)])
    _meta, rows = bench.load_rows(out)
    assert rows[0]["chosen"] == "nothink" and rows[0]["seconds"] == 9.0
    assert rows[0]["seconds_both"] == 159.0 and "variants" not in rows[1]


# --- protocol (issue #20) -------------------------------------------------------------


def test_rlm_row_records_protocol_and_stats(tmp_path: Path) -> None:
    import dataclasses

    from tests.mocklm import call, tool_turn

    cfg = dataclasses.replace(make_config("http://x"), protocol="tools")
    inst = bench.build_instance("needle", 30, 1)
    lm = MockLM(root=["no tool", tool_turn(call("final_answer", answer=inst.truth))])
    row = bench.run_row(cfg, lm, "needle", 30, "rlm", 1, str(tmp_path))
    assert row["protocol"] == "tools" and row["correct"] is True
    assert row["stats"]["slips"] == {"text_no_tool": 1}
    assert bench.row_key(row) == ("needle", 30, "rlm:tools", 1)


def test_protocols_are_separate_cells_for_resume_and_summary() -> None:
    fence = _stub_runner([])("needle", 10, "rlm", 0) | {"protocol": "fence"}
    calls: list[tuple[str, int, str, int]] = []
    rows = [fence]
    bench.run_grid(_stub_runner(calls), [("needle", 10)], ["rlm"], [0], rows=rows)
    assert calls == []  # the fence row is present; a fence pass has nothing to do
    bench.run_grid(_stub_runner(calls), [("needle", 10)], ["rlm"], [0], rows=rows, protocol="tools")
    assert calls == [("needle", 10, "rlm", 0)]
    rows[-1]["protocol"] = "tools"
    assert [c.mode for c in bench.summarize(rows)] == ["rlm", "rlm:tools"]
    assert "rlm:tools" in bench.format_summary(bench.summarize(rows))
