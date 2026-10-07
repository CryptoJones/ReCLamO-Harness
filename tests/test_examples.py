"""Unit tests for the example scripts. No model is called anywhere here."""

from __future__ import annotations

import importlib
import re
import subprocess
import sys
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
sys.path.insert(0, str(EXAMPLES))

needle = importlib.import_module("needle")
oolong = importlib.import_module("oolong_lite")
eval_mod = importlib.import_module("eval")


# --- oolong_lite --------------------------------------------------------------


def test_generator_counts_and_truth() -> None:
    tickets, truth = oolong.generate_tickets(300, seed=1)
    assert len(tickets) == 300
    assert sum(truth.values()) == 300
    assert set(truth) == set(oolong.CATEGORIES)
    assert all(n > 0 for n in truth.values())
    assert [t.id for t in tickets] == list(range(1, 301))
    assert len({t.text for t in tickets}) > 100  # genuinely varied


@pytest.mark.parametrize("seed", [0, 1, 2, 3, 42])
def test_no_category_keyword_appears_literally(seed: int) -> None:
    tickets, _ = oolong.generate_tickets(300, seed=seed)
    words = {w for ws in oolong.BANNED.values() for w in ws}
    for cat in oolong.CATEGORIES:
        words.update(cat.split())
    pattern = re.compile(r"\b(" + "|".join(map(re.escape, sorted(words))) + r")\b", re.I)
    for t in tickets:
        assert not pattern.search(t.text), (t.category, t.text)
    oolong.check_tickets(tickets)  # the generator's own guard agrees


def test_every_template_is_used_and_clean() -> None:
    for cat, templates in oolong.TEMPLATES.items():
        assert len(templates) >= 12, cat
    tickets, _ = oolong.generate_tickets(2000, seed=5)
    assert len({(t.category, t.text[:25]) for t in tickets}) > 60


def test_check_tickets_rejects_a_keyword() -> None:
    bad = [oolong.Ticket(1, "billing", "Please refund my order.")]
    with pytest.raises(AssertionError, match="banned word 'refund'"):
        oolong.check_tickets(bad)


@pytest.mark.parametrize(
    "answer",
    [
        "billing: 61\nshipping delay: 70\ndamaged item: 55\nlogin problem: 64\nfeature request: 50",
        "There were 61 tickets about billing, 70 concerned a shipping delay, 55 reported a "
        "damaged item, 64 described a login problem and 50 were a feature request.",
        "| Category | Count |\n|---|---|\n| Billing | 61 |\n| Shipping delay | 70 |\n"
        "| Damaged item | 55 |\n| Login problem | 64 |\n| Feature request | 50 |",
        "- **billing** – 61\n- **shipping-delay**: 70\n- damaged items = 55\n"
        "- login problems -> 64\n- feature requests: 50",
    ],
)
def test_parse_counts_phrasings(answer: str) -> None:
    assert oolong.parse_counts(answer) == {
        "billing": 61,
        "shipping delay": 70,
        "damaged item": 55,
        "login problem": 64,
        "feature request": 50,
    }


def test_parse_counts_missing_category_is_none() -> None:
    assert oolong.parse_counts("billing: 3")["feature request"] is None


def test_score_errors() -> None:
    truth = {"billing": 10, "shipping delay": 20}
    predicted, errors, total = oolong.score("billing: 12, shipping delay: 20", truth)
    assert predicted == {"billing": 12, "shipping delay": 20}
    assert errors == {"billing": 2, "shipping delay": 0} and total == 2
    _, errors, total = oolong.score("no numbers here", truth)
    assert total == 30  # a missing count costs the whole truth value


def test_context_and_query_shape() -> None:
    tickets, _ = oolong.generate_tickets(5, seed=0)
    ctx = oolong.build_context(tickets)
    assert ctx.startswith("Ticket 1: ") and ctx.count("\n") == 4
    query = oolong.build_query()
    for cat in oolong.CATEGORIES:
        assert cat in query


# --- needle ---------------------------------------------------------------------


def test_haystack_has_exactly_one_needle() -> None:
    context, passphrase, idx = needle.build_haystack(1000, seed=3)
    lines = context.split("\n")
    assert len(lines) == 1000
    hits = [i for i, line in enumerate(lines) if "secret passphrase" in line]
    assert hits == [idx]
    assert re.fullmatch(r"[A-Z]+-[A-Z]+", passphrase)
    assert passphrase in lines[idx]
    assert context.count(passphrase) == 1


def test_haystack_is_deterministic_per_seed() -> None:
    assert needle.build_haystack(50, seed=9) == needle.build_haystack(50, seed=9)
    assert needle.build_haystack(50, seed=9)[1] != needle.build_haystack(50, seed=10)[1]


# --- eval ---------------------------------------------------------------------


def test_format_table() -> None:
    results = {
        "needle": {
            "lines": 1000,
            "found": True,
            "turns": 3,
            "subcalls": 0,
            "tokens": 4500,
            "elapsed": 16.4,
        },
        "oolong_lite": {
            "n_tickets": 300,
            "total_error": 4,
            "errors": {"billing": 1, "shipping delay": 3},
            "turns": 8,
            "subcalls": 12,
            "tokens": 90000,
            "elapsed": 300.5,
        },
    }
    table = eval_mod.format_table(results)
    lines = table.splitlines()
    assert lines[0] == "| Task | Result | Turns | Sub-calls | Tokens | Seconds |"
    assert "| needle (1,000 lines) | found | 3 | 0 | 4,500 | 16.4 |" in lines
    assert "total abs error 4 (billing 1, shipping delay 3)" in lines[3]


def test_format_table_handles_errors_and_missing() -> None:
    results = {
        "needle": {"lines": 10, "found": False, "error": "timeout", "turns": None,
                   "subcalls": None, "tokens": None, "elapsed": 1.0},
    }  # fmt: skip
    table = eval_mod.format_table(results)
    assert "missed (timeout) | - | - | - | 1.0 |" in table


# --- scripts run ------------------------------------------------------------------


@pytest.mark.parametrize("script", ["needle.py", "oolong_lite.py", "eval.py"])
def test_help_runs(script: str) -> None:
    proc = subprocess.run(
        [sys.executable, str(EXAMPLES / script), "--help"], capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stderr
    assert "--profile" in proc.stdout


def test_dump_prints_tickets_and_truth_without_a_model() -> None:
    proc = subprocess.run(
        [
            sys.executable,
            str(EXAMPLES / "oolong_lite.py"),
            "--dump",
            "--tickets",
            "12",
            "--seed",
            "4",
        ],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "RECLAMO_API_KEY": ""},
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.count("Ticket ") == 12
    assert "truth: " in proc.stdout
