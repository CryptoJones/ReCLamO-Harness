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


# --- nested ---------------------------------------------------------------------

nested = importlib.import_module("nested")


def _reference_truth(log: str, fmt: str) -> tuple[int, dict[int, str]]:
    """Replay a rendered log independently of the generator's specs."""
    import json as _json

    last: dict[int, str] = {}
    text: dict[int, str] = {}
    for line in log.splitlines():
        if fmt == "syslog":
            m = re.match(r"\S+ TICKET-(\d+) (OPENED|CLOSED|REOPENED)(?: by \w+: (.*))?$", line)
            if m:
                last[int(m[1])] = m[2]
                if m[3]:
                    text[int(m[1])] = m[3]
        elif fmt == "chat":
            m = re.match(r"\[[^\]]+\] (open|close|reopen) #(\d+)(?: \(\w+\) -- (.*))?$", line)
            if m:
                last[int(m[2])] = m[1]
                if m[3]:
                    text[int(m[2])] = m[3]
        elif fmt == "json":
            rec = _json.loads(line)
            if rec["event"] in ("open", "close", "reopen"):
                last[rec["id"]] = rec["event"]
                if "text" in rec:
                    text[rec["id"]] = rec["text"]
        else:
            m = re.match(r"ts=\S+ evt=(new|done|again) id=(\d+)(?: user=\w+ msg=\"(.*)\")?$", line)
            if m:
                last[int(m[2])] = m[1]
                if m[3]:
                    text[int(m[2])] = m[3]
    unresolved = {i for i, ev in last.items() if ev not in ("CLOSED", "close", "done")}
    return len(unresolved), {i: text[i] for i in unresolved}


def test_nested_rendered_logs_agree_with_truth() -> None:
    depts = nested.generate(8, 12_000, seed=3)
    context = nested.build_context(depts)
    truth, most = nested.build_truth(depts)
    assert set(context) == set(truth) and len(truth) == 8
    assert all(len(log) >= 12_000 for log in context.values())
    assert {d.fmt for d in depts} == set(nested.FORMATS)
    for d in depts:
        n_unresolved, texts = _reference_truth(context[d.name], d.fmt)
        assert n_unresolved == d.unresolved, d.name
        by_id = {t.id: t for t in d.tickets}
        damaged = sum(1 for i in texts if by_id[i].category == nested.TARGET)
        assert damaged == truth[d.name], d.name
        assert all(by_id[i].text == text for i, text in texts.items())
    counts = list(truth.values())
    assert counts.count(max(counts)) == 1 and truth[most] == max(counts)


def test_nested_is_deterministic_and_grep_proof() -> None:
    a = nested.build_context(nested.generate(4, 8_000, seed=11))
    b = nested.build_context(nested.generate(4, 8_000, seed=11))
    assert a == b
    assert a != nested.build_context(nested.generate(4, 8_000, seed=12))
    depts = nested.generate(6, 8_000, seed=11)
    nested.check(depts)  # raises on a category word in any ticket text
    words = {w for ws in oolong.BANNED.values() for w in ws}
    pattern = re.compile(r"\b(" + "|".join(map(re.escape, sorted(words))) + r")\b", re.I)
    for d in depts:
        for t in d.tickets:
            assert not pattern.search(t.text), (d.name, t.text)
    assert "damaged item" in nested.build_query() and "Department: count" in nested.build_query()


def test_nested_default_size_is_large() -> None:
    depts = nested.generate(12, 25_000, seed=0)
    assert sum(len(v) for v in nested.build_context(depts).values()) >= 300_000


@pytest.mark.parametrize(
    "answer",
    [
        "Accounts: 3\nLegal: 7\nmost: Legal",
        "- **Accounts** – 3\n- Legal -> 7\n\nmost: **Legal**",
        "Accounts: 3, Legal: 7. Most: legal",
    ],
)
def test_nested_score_parses_counts_and_most(answer: str) -> None:
    truth = {"Accounts": 3, "Legal": 7}
    predicted, errors, total, most_predicted, ok = nested.score(answer, truth, "Legal")
    assert predicted == truth and total == 0 and errors == {"Accounts": 0, "Legal": 0}
    assert most_predicted == "Legal" and ok


def test_nested_score_missing_most_and_wrong_counts() -> None:
    truth = {"Accounts": 3, "Legal": 7}
    predicted, errors, total, most_predicted, ok = nested.score(
        "Accounts: 5\nLegal: 7", truth, "Legal"
    )
    assert predicted == {"Accounts": 5, "Legal": 7} and total == 2
    assert most_predicted is None and not ok
    assert nested.parse_most("most: Nowhere", ["Accounts"]) is None


def test_nested_help_and_dump_run_without_a_model() -> None:
    proc = subprocess.run(
        [sys.executable, str(EXAMPLES / "nested.py"), "--help"], capture_output=True, text=True
    )
    assert proc.returncode == 0 and "--max-depth" in proc.stdout
    proc = subprocess.run(
        [sys.executable, str(EXAMPLES / "nested.py"), "--dump", "--departments", "3",
         "--chars", "3000", "--seed", "4"],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "RECLAMO_API_KEY": ""},
    )  # fmt: skip
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.count("===== ") == 3
    assert "truth: " in proc.stdout and "most: " in proc.stdout
