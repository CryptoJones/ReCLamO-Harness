"""Unit tests for evals/independent/run_eval.py (issue #22). No model is called."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import make_config
from tests.mocklm import MockLM

RUNNER = Path(__file__).resolve().parents[1] / "evals" / "independent" / "run_eval.py"
_spec = importlib.util.spec_from_file_location("run_eval", RUNNER)
assert _spec and _spec.loader
run_eval = importlib.util.module_from_spec(_spec)
sys.modules["run_eval"] = run_eval
_spec.loader.exec_module(run_eval)


def fake_generator(answer: Any = "Room 7", *, crash: bool = False) -> types.ModuleType:
    mod = types.ModuleType("fake_gen")

    def generate(seed: int, size: str) -> dict[str, Any]:
        n = {"small": 20, "medium": 200, "large": 2000}[size]
        lines = [f"line {i}: nothing here (seed {seed})" for i in range(n)]
        lines.insert(n // 2, f"the asset is in {answer}")
        return {"context": "\n".join(lines), "question": "Where is the asset?", "answer": answer}

    def score(answer_text: str, truth: Any) -> float:
        if crash:
            raise ValueError("bad scorer")
        return 1.0 if str(truth) in answer_text else 0.0

    mod.generate = generate  # type: ignore[attr-defined]
    mod.score = score  # type: ignore[attr-defined]
    return mod


MANIFEST = {"generators": {"Fake": {"vendor": "acme", "model": "acme-1", "active": {}}}}


def gens_with(mod: types.ModuleType, lane: str = "Fake") -> Any:
    gens = run_eval.Generators(MANIFEST)
    gens.add(lane, mod)
    return gens


# --- rows ------------------------------------------------------------------------------


def test_rlm_row_uses_the_generator_scorer_and_records_counters(tmp_path: Path) -> None:
    cfg = make_config("http://x")
    lm = MockLM(root=["```repl\nprint(len(context))\n```", "FINAL(Room 7)"])
    row = run_eval.run_row(cfg, lm, gens_with(fake_generator()), "Fake", "small", "rlm", 0,
                           str(tmp_path))  # fmt: skip
    assert row["score"] == 1.0 and row["exact"] is True and row["correct"] is True
    assert row["author_model"] == "acme-1" and row["author_vendor"] == "acme"
    assert row["turns"] == 2 and row["subcalls"] == 0 and row["stop_reason"] == "final"
    assert row["executions"] == 1 and row["syntax_errors"] == 0
    assert row["final_rejections"] == 0 and row["slips"] == 0
    assert row["trajectory"] and Path(row["trajectory"]).exists()
    assert row["protocol"] == "fence" and row["truth"] == "Room 7"


def test_plain_row_is_bench_best_of_two() -> None:
    cfg = make_config("http://x")
    lm = MockLM(root=["no idea", "It is in Room 7."])
    row = run_eval.run_row(cfg, lm, gens_with(fake_generator()), "Fake", "small", "plain", 0, None)
    assert row["fits"] and not row["does_not_fit"]
    assert row["score"] == 1.0 and row["exact"] and row["chosen"] == "nothink"
    assert [c["enable_thinking"] for c in lm.root_calls] == [True, False]
    assert lm.root_calls[0]["messages"][1]["content"].startswith("=== DOCUMENT ===")


def test_plain_row_does_not_fit_makes_no_call() -> None:
    cfg = make_config("http://x")
    cfg.context_tokens = 600
    cfg.root.max_tokens = 100
    lm = MockLM(root=[])
    row = run_eval.run_row(cfg, lm, gens_with(fake_generator()), "Fake", "large", "plain", 0, None)
    assert row["does_not_fit"] and row["score"] is None and row["exact"] is None
    assert lm.calls == []
    assert "does not fit" in run_eval.describe_row(row)


def test_tuple_truth_is_stored_as_json_and_scored_with_the_original() -> None:
    cfg = make_config("http://x")
    lm = MockLM(root=["('Priya', 5)", "nope"])
    row = run_eval.run_row(cfg, lm, gens_with(fake_generator(("Priya", 5))), "Fake", "small",
                           "plain", 0, None)  # fmt: skip
    assert row["truth"] == ["Priya", 5] and row["score"] == 1.0
    json.dumps(row)


def test_scorer_crash_is_recorded_as_zero() -> None:
    cfg = make_config("http://x")
    lm = MockLM(root=["Room 7", "Room 7"])
    gens = gens_with(fake_generator(crash=True))
    row = run_eval.run_row(cfg, lm, gens, "Fake", "small", "plain", 0, None)
    assert row["score"] == 0.0 and row["exact"] is False
    assert "bad scorer" in row["score_error"]


def test_unknown_mode_rejected() -> None:
    with pytest.raises(ValueError, match="unknown mode"):
        run_eval.run_row(make_config("http://x"), MockLM([]), gens_with(fake_generator()),
                         "Fake", "small", "plain_truncated", 0, None)  # fmt: skip


def test_load_generator_refuses_a_modified_file(tmp_path: Path) -> None:
    (tmp_path / "g.py").write_text("def generate(s, z): pass\ndef score(a, t): return 0\n")
    good = hashlib.sha256((tmp_path / "g.py").read_bytes()).hexdigest()
    manifest = {"generators": {"X": {"active": {"file": "g.py", "sha256": good}}}}
    assert hasattr(run_eval.load_generator("X", manifest, tmp_path), "score")
    manifest["generators"]["X"]["active"]["sha256"] = "0" * 64
    with pytest.raises(RuntimeError, match="pinned sha256"):
        run_eval.load_generator("X", manifest, tmp_path)


def test_real_active_generator_registers_and_scores() -> None:
    gens = run_eval.Generators(run_eval.load_manifest())
    inst = run_eval.build_instance(gens, "MasterControl", "small", 0)
    spec = run_eval.bench.TASKS["indep/MasterControl"]
    assert spec.score(str(inst.truth), inst.truth).correct is True
    assert spec.score("", inst.truth).score < 1.0


# --- plan, resume, aggregation -----------------------------------------------------------


def test_plan_runs_every_small_row_before_any_medium_row() -> None:
    cells = run_eval.plan(["A", "B"], ["small", "medium"], ["rlm", "plain"], [0, 1])
    sizes = [(seed, size) for _l, size, _m, seed in cells]
    assert sizes[:4] == [(0, "small")] * 4 and sizes[4:8] == [(0, "medium")] * 4
    assert cells[0] == ("A", "small", "rlm", 0) and cells[-1] == ("B", "medium", "plain", 1)


def _fake_row(lane: str, size: str, mode: str, seed: int, score: float | None = 1.0) -> dict:
    row: dict[str, Any] = {"task": lane, "size": size, "mode": mode, "seed": seed}
    if score is None:
        row.update(stop_reason="does_not_fit", score=None, est_prompt_tokens=90_000,
                   usable_tokens=28_672)  # fmt: skip
    else:
        row.update(score=score, stop_reason="final", turns=3, subcalls=2, seconds=10.0)
    if mode == "rlm":
        row["protocol"] = "fence"
    return run_eval.finish_row(row)


def test_resume_skips_rows_already_present(tmp_path: Path) -> None:
    calls: list[tuple] = []

    def runner(lane: str, size: str, mode: str, seed: int) -> dict:
        calls.append((lane, size, mode, seed))
        return _fake_row(lane, size, mode, seed)

    cells = run_eval.plan(["A", "B"], ["small"], ["rlm", "plain"], [0])
    out = tmp_path / "rows.json"
    rows: list[dict] = []
    run_eval.run_grid(runner, cells[:3], rows=rows,
                      on_row=lambda _r: run_eval.write_rows(out, {}, rows))  # fmt: skip
    assert len(calls) == 3
    _meta, loaded = run_eval.load_rows(out)
    calls.clear()
    run_eval.run_grid(runner, cells, rows=loaded)
    assert calls == [("B", "small", "plain", 0)] and len(loaded) == 4
    calls.clear()
    run_eval.run_grid(runner, cells, rows=loaded)
    assert calls == []


def test_tools_protocol_rows_are_a_separate_key() -> None:
    rows = [_fake_row("A", "small", "rlm", 0)]
    calls: list[tuple] = []
    run_eval.run_grid(
        lambda *a: calls.append(a) or {**_fake_row(*a), "protocol": "tools"},
        [("A", "small", "rlm", 0)],
        rows=rows,
        protocol="tools",
    )
    assert calls == [("A", "small", "rlm", 0)]


def test_cell_stats_counts_no_fit_as_zero_only_in_mean_all() -> None:
    group = [
        _fake_row("A", "medium", "plain", 0, None),
        _fake_row("B", "medium", "plain", 0, 1.0),
        _fake_row("C", "medium", "plain", 0, 0.5),
        _fake_row("D", "medium", "plain", 0, None),
    ]
    c = run_eval.cell_stats(group)
    assert c["n"] == 4 and c["attempted"] == 2 and c["does_not_fit"] == 2
    assert c["mean_attempted"] == 0.75 and c["mean_all"] == 0.375 and c["exact"] == 1


def test_summary_tables() -> None:
    rows = [
        _fake_row("GLaDOS", "small", "rlm", 0, 1.0),
        _fake_row("GLaDOS", "small", "plain", 0, 0.5),
        _fake_row("GLaDOS", "medium", "rlm", 0, 0.0),
        _fake_row("GLaDOS", "medium", "plain", 0, None),
        _fake_row("SHODAN", "small", "rlm", 0, 0.25),
        _fake_row("SHODAN", "small", "rlm", 1, 0.75),
    ]
    text = run_eval.format_summary(rows, run_eval.load_manifest())
    assert "| GLaDOS (grok-4.6) | small | 1.00 (exact) | 0.50 |" in text
    assert "| GLaDOS (grok-4.6) | medium | 0.00 | does not fit (~90,000 tokens) |" in text
    assert "| SHODAN (gpt-6-astra) | small | 0.50 (exact 0/2) | – |" in text
    assert "| small | rlm | 3 | 0.67 | 0.67 | 1/3 | 0 | 0 |" in text
    assert "| medium | plain | 1 | – | 0.00 | 0/1 | 1 | 0 |" in text
    assert text.index("GLaDOS") < text.index("SHODAN")


def test_main_summary_only(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "rows.json"
    run_eval.write_rows(out, {}, [_fake_row("Cerebex", "small", "rlm", 0, 1.0)])
    assert run_eval.main(["--summary-only", str(out)]) == 0
    assert "| Cerebex (glm-5.3-flash) | small | 1.00 (exact) |" in capsys.readouterr().out


def test_main_rejects_unknown_size() -> None:
    assert run_eval.main(["--sizes", "huge", "--dry-run"]) == 2


def test_provenance_reports_the_frozen_commit() -> None:
    p = run_eval.provenance()
    assert set(p) == {"head", "frozen_commit", "harness_changed_since_frozen"}
