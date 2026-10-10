"""Unit tests for evals/longbenchpro/longbenchpro.py (issue #75). No network, no model.

The fixture (tests/data/longbenchpro_fixture.json) is synthetic: ten records in the
dataset's schema, written for these tests, with no LongBench Pro text in them.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "data" / "longbenchpro_fixture.json"
_spec = importlib.util.spec_from_file_location(
    "longbenchpro", ROOT / "evals" / "longbenchpro" / "longbenchpro.py"
)
assert _spec and _spec.loader
lbp = importlib.util.module_from_spec(_spec)
sys.modules["longbenchpro"] = lbp
_spec.loader.exec_module(lbp)

import bench  # noqa: E402  (on sys.path once longbenchpro is loaded)


def records() -> list[dict]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def loaded():
    return lbp.load(FIXTURE)


@pytest.fixture(scope="module")
def by_id(loaded):
    return {it.id: it for it in loaded.items}


# --- MC vs open ------------------------------------------------------------------------


def test_kinds_are_per_item_not_per_task(by_id) -> None:
    expected = {
        "fx-01": ("mc", 4),  # T3.1, A-D
        "fx-02": ("mc-multi", 7),  # T3.2, "A/B/BCD/EFG" select-all
        "fx-03": ("open", 0),  # T11.2 with a numeric answer
        "fx-04": ("mc", 4),  # T10.2: MC outside T3 / T11
        "fx-05": ("open", 0),  # a letter answer ("Y") with no listed options
        "fx-07": ("open", 0),  # option letters in the context, an ordering as the answer
    }
    assert {i: (by_id[i].kind, by_id[i].n_options) for i in expected} == expected
    assert by_id["fx-01"].chance == 0.25
    assert by_id["fx-02"].chance == 1 / 127
    assert by_id["fx-03"].chance is None
    assert by_id["fx-01"].is_mc and not by_id["fx-03"].is_mc


def test_options_need_a_run_from_a() -> None:
    assert lbp.options_of("A. one\nB. two\nC. three") == ["A", "B", "C"]
    assert lbp.options_of("A rose is a rose.\nNothing else.") == []
    assert lbp.options_of("B. two\nC. three") == []
    assert lbp.answer_kind("A. x\nB. y", ["C"]) == ("open", 0)  # not an offered option


def test_tags_reach_the_instance(by_id) -> None:
    inst = lbp.instance(by_id["fx-02"])
    assert isinstance(inst, bench.Instance)
    assert inst.context == by_id["fx-02"].context
    assert inst.query == by_id["fx-02"].question
    assert inst.truth == ["ACE"]
    assert inst.meta["kind"] == "mc-multi" and inst.meta["mc"] is True
    assert inst.meta["task"] == "T3" and inst.meta["split"] in lbp.SPLITS
    assert lbp.instance(by_id["fx-02"], thinking=True).query == by_id["fx-02"].question_thinking


# --- splits -------------------------------------------------------------------------------


def test_split_is_a_pure_function_of_the_group_id() -> None:
    # Pinned: changing the salt, the bounds or the hash moves every item.
    assert [lbp.split_of(f"fx-{n:02}") for n in range(1, 11)] == [
        "held-out",
        "practice",
        "practice",
        "practice",
        "held-out",
        "practice",
        "held-out",
        "practice-dev",
        "practice",
        "practice-dev",
    ]
    real = "401c9ee31d21dabf734bc2f48d13a4ebe30368041a84cdb460c964f9228120c3"
    assert lbp.split_of(real) == "held-out"


def test_shared_documents_share_a_split(by_id) -> None:
    # fx-09 repeats one long line of fx-01 (case and indentation differ); fx-10 reuses
    # fx-03's whole context. Each pair is one document, so one group and one split.
    assert by_id["fx-09"].group == by_id["fx-01"].group == "fx-01"
    assert by_id["fx-10"].group == by_id["fx-03"].group == "fx-03"
    assert by_id["fx-09"].split == by_id["fx-01"].split
    assert by_id["fx-02"].group == "fx-02"


def _synthetic(n: int) -> list[dict]:
    base = records()[0]
    out = []
    for i in range(n):
        # Every fifth record repeats the previous one's long line: a shared document.
        doc = i - 1 if i % 5 == 4 else i
        line = f"Document {doc} records that shipment {doc} cleared customs " + "x" * 120
        out.append({**base, "id": f"syn-{i:05}", "context": f"Header {i}\n{line}\nEnd."})
    return out


def test_splits_are_disjoint_and_cover_everything() -> None:
    loaded = lbp.load_records(_synthetic(3000))
    ids = {sp: {it.id for it in loaded.items if it.split == sp} for sp in lbp.SPLITS}
    for a, b in [("practice", "practice-dev"), ("practice", "held-out"),
                 ("practice-dev", "held-out")]:  # fmt: skip
        assert not ids[a] & ids[b], f"{a} and {b} overlap"
    assert set().union(*ids.values()) == {it.id for it in loaded.items}
    # No document text crosses a split boundary.
    owner: dict[bytes, str] = {}
    for it in loaded.items:
        for key in lbp.line_keys(it.context):
            assert owner.setdefault(key, it.split) == it.split
    share = {sp: len(ids[sp]) / len(loaded.items) for sp in lbp.SPLITS}
    assert 0.65 < share["practice"] < 0.75
    assert 0.07 < share["practice-dev"] < 0.13
    assert 0.16 < share["held-out"] < 0.24


def test_split_does_not_depend_on_record_order() -> None:
    recs = _synthetic(200)
    forward = {it.id: it.split for it in lbp.load_records(recs).items}
    backward = {it.id: it.split for it in lbp.load_records(recs[::-1]).items}
    assert forward == backward


def test_duplicate_ids_are_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        lbp.load_records(records()[:2] + records()[:1])


# --- exam-hash exclusion -----------------------------------------------------------------


def test_normalize_ignores_case_width_and_whitespace() -> None:
    assert lbp.normalize("  Ａ\tB\n\nc  ") == "a b c"
    assert lbp.text_hash("Room 7\n") == lbp.text_hash("room   7")


def test_exam_documents_are_refused() -> None:
    lane, size, seed, doc = next(lbp.exam_documents([0]))
    disguised = "  " + doc["context"].upper().replace("\n", "\r\n") + "\n"
    recs = records()
    recs[0] = {**recs[0], "context": disguised}
    recs[1] = {**recs[1], "question_nonthinking": doc["question"]}
    loaded = lbp.load_records(recs)
    refused = {it.id: why for it, why in loaded.refused}
    assert refused == {"fx-01": "context", "fx-02": "question"}, (lane, size, seed)
    assert {it.id for it in loaded.items}.isdisjoint(refused)
    # The refusal is recorded; the item's split is the one it would have had.
    assert all(it.split in lbp.SPLITS for it, _ in loaded.refused)


def test_fixture_has_no_exam_matches(loaded) -> None:
    assert loaded.refused == [] and len(loaded.items) == 10


def test_exam_hashes_match_the_active_exam() -> None:
    """exam_hashes.json must be rebuilt whenever an active generator changes."""
    data = json.loads(lbp.EXAM_HASHES.read_text(encoding="utf-8"))
    manifest = json.loads((ROOT / "evals" / "independent" / "manifest.json").read_text())
    assert data["generators"] == {
        lane: g["active"]["sha256"] for lane, g in sorted(manifest["generators"].items())
    }, "an exam generator changed: run longbenchpro.py exam-hashes"
    lo, hi = data["seeds"]
    assert lo == 0 and hi >= 41  # TEST-PLAN extends the grid to seeds 2-41
    assert len(data["contexts"]) == len(manifest["generators"]) * len(data["sizes"]) * (hi + 1)
    exam = lbp.load_exam_hashes()
    for _lane, _size, _seed, doc in lbp.exam_documents([0, hi]):
        if _size == "small":
            assert lbp.text_hash(doc["context"]) in exam.contexts
            assert lbp.text_hash(doc["question"]) in exam.questions


# --- scoring -------------------------------------------------------------------------------


def test_every_fixture_key_scores_itself(by_id) -> None:
    for it in by_id.values():
        s = lbp.score(it, "[Answer]\n" + "\n".join(it.answer))
        if it.scorable:
            assert s.score == 1.0 and s.correct, it.id
        else:
            assert s.correct is None and "unscored" in s.detail, it.id
        assert lbp.score(it, "").score == 0.0


def test_answer_lines_take_the_last_marker() -> None:
    assert lbp.answer_lines("think [Answer] no\n[Answer]\n  B  \nextra") == ["b", "extra"]
    assert lbp.answer_lines("[答案]\nACE") == ["ace"]
    assert lbp.answer_lines("B") == ["b"]  # no marker: the whole text


def test_metrics() -> None:
    assert lbp.accuracy(["B"], ["b", "c"]) == 1.0
    assert lbp.accuracy(["B"], ["c", "b"]) == 0.0
    assert lbp.subem(["76", "93"], ["76", "90"]) == 0.5
    assert lbp.f1(["1", "3"], ["1", "2"]) == 0.5
    assert lbp.pairwise(["b", "a", "c"], ["b", "a", "c"]) == 1.0
    assert lbp.pairwise(["b", "a", "c"], ["a", "b", "c"]) == pytest.approx(2 / 3)
    assert lbp.ndcg(["1970", "2015", "2019"], ["1970", "2015", "2019"]) == 1.0
    assert 0 < lbp.ndcg(["1970", "2015", "2019"], ["2015", "1970", "2019"]) < 1
    assert lbp.ndcg(["a", "b", "a"], ["a", "b", "a"]) == 1.0  # a key listing an entry twice


def test_bench_task_scores_with_the_item_metric(by_id) -> None:
    inst = lbp.instance(by_id["fx-10"])
    spec = bench.TASKS[inst.task]
    assert inst.task == "lbp/T8.2" and spec.metric == "accuracy"
    assert spec.score("[Answer]\n76\n93", inst.truth).correct
    assert spec.score("[Answer]\n76", inst.truth).score == 0.5


# --- select, stats, download, CLI ----------------------------------------------------------


def test_select(loaded) -> None:
    items = loaded.items
    assert "fx-08" not in {it.id for it in lbp.select(items)}  # T4 is unscored
    assert "fx-08" in {it.id for it in lbp.select(items, scorable_only=False)}
    assert {it.id for it in lbp.select(items, kinds=["mc", "mc-multi"])} == {
        "fx-01",
        "fx-02",
        "fx-04",
    }
    assert {it.id for it in lbp.select(items, tasks=["T3.2", "T11"])} == {"fx-02", "fx-03"}
    assert {it.id for it in lbp.select(items, languages=["Chinese"])} == {"fx-02"}
    assert all(it.token_length in ("8k", "16k") for it in lbp.select(items, max_bucket="16k"))
    assert lbp.select(items, max_tokens=1) == []
    assert {it.split for it in lbp.select(items, split="held-out")} <= {"held-out"}
    with pytest.raises(ValueError):
        lbp.select(items, split="test")


def test_stats_table(loaded) -> None:
    text = lbp.format_stats(loaded)
    assert "10 items in 8 document groups, 0 refused" in text
    assert "| T3 | mc | held-out | 1 |" in text
    assert "| T3 | mc-multi | practice | 1 |" in text
    assert "| mc | 1 | 0 | 1 | 2 |" in text
    assert "| 8k | 1 | 1 | 1 | 2 | 1 |" in text


def test_download_checks_the_sha256(tmp_path, monkeypatch) -> None:
    src = tmp_path / "src.json"
    src.write_bytes(b"[]")
    dest = tmp_path / "cache" / "longbench_pro.json"
    with pytest.raises(RuntimeError, match="sha256"):
        lbp.download(dest, url=src.as_uri())
    assert not dest.exists() and not dest.with_suffix(".json.part").exists()
    monkeypatch.setattr(lbp, "SHA256", hashlib.sha256(b"[]").hexdigest())
    assert lbp.download(dest, url=src.as_uri()) == dest
    assert lbp.download(dest, url="file:///nonexistent") == dest  # cached: no fetch


def test_cli_stats(capsys) -> None:
    assert lbp.main(["stats", "--data", str(FIXTURE), "--kinds", "mc"]) == 0
    out = capsys.readouterr().out
    assert "| T10 | mc |" in out and "| T11 |" not in out
    assert lbp.main(["stats", "--data", str(FIXTURE.with_name("missing.json"))]) == 2
