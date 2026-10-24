"""The #85 analysis code runs on a synthetic fixture, never on confirmatory rows in CI.

The fixture is a paired grid with a known arm effect and a known task effect, so each
estimator has a truth to be checked against: sign and rough size, not exact values.
"""

from __future__ import annotations

import importlib.util
import math
import random
import sys
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[1] / "paper" / "analysis" / "h1_analysis.py"
spec = importlib.util.spec_from_file_location("h1_analysis", PATH)
h1 = importlib.util.module_from_spec(spec)
sys.modules["h1_analysis"] = h1
spec.loader.exec_module(h1)

TASKS = ["T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8"]


def _row(task, size, seed, mode, right, stop="final", dnf=False, **kw):
    r = {
        "task": task,
        "size": size,
        "seed": seed,
        "mode": mode,
        "score": 1.0 if right else 0.2,
        "stop_reason": stop,
        "does_not_fit": dnf,
        "error": None,
        "seconds": 10.0 + (seed % 7),
        "prompt_tokens": 1000,
        "completion_tokens": 100,
        "subcalls": 2 if mode == "rlm" else 0,
        "turns": 5 if mode == "rlm" else 1,
        "author_vendor": "v" + task[-1],
        "author_model": "m" + task[-1],
    }
    r.update(kw)
    return r


def fixture(effect: float, seeds=range(4, 44), task_sd: float = 1.0, seed: int = 7):
    """Harness right with prob sigmoid(a_t + effect), plain with sigmoid(a_t)."""
    rng = random.Random(seed)
    a = {t: rng.gauss(0.0, task_sd) for t in TASKS}
    h, p = [], []
    for t in TASKS:
        for s in seeds:
            for size in ("small", "medium"):
                ph = h1._sigmoid(a[t] + effect)
                pp = h1._sigmoid(a[t])
                h.append(_row(t, size, s, "rlm", rng.random() < ph, stop="answer_dict"))
                p.append(_row(t, size, s, "plain", rng.random() < pp, stop="stop"))
    return h, p


def test_pairs_and_primary_mcnemar_sign():
    h, p = fixture(1.5)
    pairs = h1.make_pairs(h, p, "small")
    assert len(pairs) == 8 * 40
    m = h1.mcnemar(pairs)
    assert m["b"] > m["c"] and m["z"] > 2.0 and m["p"] < 0.05


def test_null_effect_rarely_crosses():
    h, p = fixture(0.0, seed=3)
    m = h1.mcnemar(h1.make_pairs(h, p, "small"))
    assert abs(m["z"]) < 2.004


def test_cluster_bootstrap_brackets_truth():
    rng = random.Random(1)
    h, p = fixture(1.5)
    pairs = h1.make_pairs(h, p, "small")
    bs = h1.cluster_bootstrap(pairs, rng, reps=500)
    lo, hi = bs["exact_diff_ci"]
    assert lo <= bs["exact_diff"] <= hi and lo > 0.0
    h0, p0 = fixture(0.0, seed=5)
    bs0 = h1.cluster_bootstrap(h1.make_pairs(h0, p0, "small"), rng, reps=500)
    lo0, hi0 = bs0["exact_diff_ci"]
    assert lo0 <= 0.0 <= hi0


def test_hermite_gauss_integrates_gaussian_moments():
    gh = h1.hermite_gauss(20)
    assert len(gh) == 20
    assert abs(sum(w for _, w in gh) - math.sqrt(math.pi)) < 1e-9
    second = sum(w * x * x for x, w in gh)  # int x^2 e^{-x^2} = sqrt(pi)/2
    assert abs(second - math.sqrt(math.pi) / 2) < 1e-9


def test_glmm_recovers_arm_effect_and_task_sd():
    h, p = fixture(1.5, task_sd=1.0)
    pairs = h1.make_pairs(h, p, "small") + h1.make_pairs(h, p, "medium")
    g = h1.glmm_logit(pairs, nodes=12)
    assert g["ok"]
    assert 0.8 < g["beta_arm"] < 2.3, g
    assert g["p"] < 0.01
    assert 0.3 < g["sigma_task"] < 2.5, g


def test_glmm_null_is_not_significant():
    h, p = fixture(0.0, seed=11)
    g = h1.glmm_logit(h1.make_pairs(h, p, "small"), nodes=12)
    assert g["ok"] and abs(g["z"]) < 2.5


def test_loto_and_mde():
    h, p = fixture(1.0)
    pairs = h1.make_pairs(h, p, "small")
    loto = h1.leave_one_task_out(pairs)
    assert [m["dropped"] for m in loto] == TASKS
    assert all(m["n"] == 7 * 40 for m in loto)
    pd = h1.mcnemar(pairs)["discordance"]
    m1, m2, m3 = (h1.mde(n, pd, h1.BOUNDARIES[k]) for k, n in h1.LOOK_PAIRS.items())
    assert m1 > m2 > m3 > 0
    assert math.isnan(h1.mde(0, pd, 2.0))


def test_taxonomy_and_exclusion_sets():
    assert h1.taxonomy(_row("T1", "small", 4, "rlm", True, stop="final")) == "answered"
    assert (
        h1.taxonomy(_row("T1", "small", 4, "rlm", False, stop="max_iterations"))
        == "forced finish: turn cap"
    )
    assert (
        h1.taxonomy(_row("T1", "small", 4, "rlm", False, stop="timeout"))
        == "forced finish: time limit"
    )
    assert (
        h1.taxonomy(_row("T1", "small", 4, "rlm", False, stop="error_limit"))
        == "forced finish: error limit"
    )
    assert (
        h1.taxonomy(_row("T1", "small", 4, "rlm", False, stop="context_overflow"))
        == "forced finish: context overflow"
    )
    assert h1.taxonomy(_row("T1", "small", 4, "plain", False, stop="length")) == "output-length cap"
    assert (
        h1.taxonomy(_row("T1", "small", 4, "rlm", False, stop="malformed_tool_call"))
        == "malformed_tool_call"
    )
    assert (
        h1.taxonomy(_row("T1", "small", 4, "plain", False, stop="does_not_fit", dnf=True))
        == "not_run: does_not_fit"
    )
    assert (
        h1.taxonomy(_row("T1", "small", 4, "rlm", False, stop="error", error="boom"))
        == "not_run: error"
    )

    h = [
        _row("T1", "small", s, "rlm", True, stop="max_iterations" if s == 5 else "final")
        for s in (4, 5, 6)
    ]
    p = [
        _row("T1", "small", 4, "plain", False, stop="does_not_fit", dnf=True),
        _row("T1", "small", 5, "plain", True),
        _row("T1", "small", 6, "plain", False, stop="length"),
    ]
    sets = h1.exclusion_sets(h1.make_pairs(h, p, "small"))
    sizes = {k: len(v[1]) for k, v in sets.items()}
    kinds = {k: v[0] for k, v in sets.items()}
    assert sizes["primary: every pair counts"] == 3
    assert sizes["secondary: plain does_not_fit pairs dropped"] == 2
    assert sizes["sensitivity: plain length rows dropped"] == 2
    assert sizes["sensitivity: harness turn-cap/timeout rows dropped"] == 2
    assert sizes["sensitivity: both arms finished"] == 0
    assert kinds["primary: every pair counts"] == "primary"
    assert kinds["secondary: plain does_not_fit pairs dropped"] == "secondary"
    assert all(v == "sensitivity" for k, v in kinds.items() if k.startswith("sensitivity"))


def test_cost_and_aa_floor():
    h, p = fixture(0.5, seeds=range(4, 10))
    c = h1.cost([r for r in h if r["size"] == "small"])
    assert c["n"] == 48 and c["completion_rate"] == 1.0
    assert c["subcalls_mean"] == 2.0 and c["turns_mean"] == 5.0
    assert c["sec_p50"] <= c["sec_p95"]
    small_a = [r for r in p if r["size"] == "small"]
    small_b = [dict(r) for r in small_a]
    small_b[0]["score"] = 0.0 if small_b[0]["score"] == 1.0 else 1.0
    small_b[1]["does_not_fit"] = True
    small_b[1]["stop_reason"] = "does_not_fit"
    aa = h1.aa_floor(small_a, small_b)
    assert aa["pairs"] == 48 and aa["both_fit"] == 47 and aa["discordant"] == 1


def test_evidence_position_buckets():
    ctx = "x" * 1000
    assert h1.evidence_position("Alice " + ctx, "Alice") == "first third"
    assert h1.evidence_position(ctx[:500] + " Alice " + ctx[:500], "Alice") == "middle third"
    assert h1.evidence_position(ctx + " Alice", "Alice") == "last third"
    assert h1.evidence_position("Alice " + ctx + " Alice", "Alice") == "last third"
    assert h1.evidence_position(ctx, "$11166.59") == "computed"
    assert h1.evidence_position(ctx, {"a": 1, "b": 2}) == "computed"
    assert h1.evidence_position(ctx + " Room 104", ["Room 104"]) == "last third"


def test_analyse_and_render_end_to_end(tmp_path):
    h, p = fixture(1.2, seeds=range(4, 20))
    res = h1.analyse(h, p, 2, random.Random(0), positions=None, reps=200, glmm=False)
    assert set(res["sizes"]) == {"small", "medium"}
    small = res["sizes"]["small"]
    assert small["sets"]["primary: every pair counts"]["n"] == 8 * 16
    assert len(small["loto"]) == 8 and len(small["by_task"]) == 8 and len(small["by_author"]) == 8
    md = h1.render_markdown(
        res, {"pairs": 1, "both_fit": 1, "discordant": 0, "rate": 0.0}, "fixture"
    )
    tex = h1.render_latex(res, "fixture")
    assert "## small" in md and "A/A noise floor" in md and "Go Big Red" in md
    assert "\\begin{table}" in tex and "GLMM n/a" in tex


@pytest.mark.parametrize("bad", ["", None])
def test_parse_seeds_empty(bad):
    assert h1.parse_seeds(bad) is None
    assert h1.parse_seeds("2,4-6") == {2, 4, 5, 6}


def test_glmm_flags_separation_on_tiny_sample():
    """Two seeds per task: tasks are all-right or all-wrong per arm, which is not
    identifiable; the fit must say so instead of returning a huge odds ratio as fact."""
    h = [_row(t, "small", s, "rlm", True, stop="final") for t in TASKS for s in (4, 5)]
    p = [_row(t, "small", s, "plain", False) for t in TASKS for s in (4, 5)]
    g = h1.glmm_logit(h1.make_pairs(h, p, "small"), nodes=12)
    assert not g["ok"] and "separation" in g["reason"]
    assert abs(g["beta_arm"]) <= 10.5 and g["sigma_task"] <= 10.5


def test_latex_escapes_underscores():
    h, p = fixture(1.0, seeds=range(4, 20))
    res = h1.analyse(h, p, 3, random.Random(0), positions=None, reps=50, glmm=False)
    tex = h1.render_latex(res, "fixture")
    assert "does\\_not\\_fit" in tex and " does_not_fit" not in tex
