"""The #86 shortcut solvers: unit checks on tiny documents, and one pinned-generator smoke
run per lane at seed 0 small (the solvers must return a string the task's scorer accepts
without raising; their accuracy is the experiment, not the test)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "evals" / "independent"
spec = importlib.util.spec_from_file_location("shortcut_solver", ROOT / "shortcut_solver.py")
sc = importlib.util.module_from_spec(spec)
sys.modules["shortcut_solver"] = sc
spec.loader.exec_module(sc)


def test_dixie_follows_renames_and_takes_last_location():
    doc = (
        "Message-ID: <1>\nFrom: Director\nTo: All\nSubject: Codename Update\n\n"
        "Effective immediately, for operational security, 'The Genesis Drive' will now be "
        "known as 'The Void Key 30'.\n\n"
        "Message-ID: <2>\nFrom: Bob\nTo: Facilities\n\nI am staying in Room 120.\n\n"
        "Message-ID: <3>\nFrom: IT\nTo: All\nSubject: Audit\n\nCan whoever has "
        "'The Void Key 30' please bring it to Offsite Storage?\n\n"
        "Message-ID: <4>\nFrom: Zoe\nTo: All\n\nMy office is Room 145.\n"
    )
    q = "What is the final physical location of the asset originally known as 'The Genesis Drive'?"
    assert sc.dixie_last(q, doc) == "Room 145"
    assert sc.dixie_heuristic(q, doc) == "Offsite Storage"


def test_selma_assignment_and_unassigned():
    doc = (
        "From: A <a@x>\nSubject: Kickoff: AI Ethics Review\n\n"
        "We're starting the AI Ethics Review.\n"
        "From: B <b@x>\nSubject: Update\n\nI'm assigning the AI Ethics Review for Project "
        "Pinnacle to Finley Brown from Product.\n"
        "From: C <c@x>\nSubject: Other\n\nThe Security Audit goes to Gray Miller.\n"
    )
    q = (
        "who is the final owner responsible for the AI Ethics Review? "
        "If no one is currently assigned, respond with 'Unassigned'."
    )
    assert sc.selma_heuristic(q, doc) == "Finley Brown"
    doc2 = doc + (
        "From: D <d@x>\nSubject: Cancelled\n\nThe AI Ethics Review has been cancelled and "
        "the lead position is now unassigned.\n"
    )
    assert sc.selma_heuristic(q, doc2) == "Unassigned"


def test_mastercontrol_summary_line_and_log_sum():
    doc = (
        "=== Transaction Log for Ethan Nguyen ===\n2024-07-06 | Conference fees | $276.00\n"
        "2024-02-11 | Taxi | $24.00\n\n"
        "=== Transaction Log for Sophia Lee ===\n2024-07-06 | Hotel | $1,000.00\n\n"
        "=== FINAL AUDIT SUMMARY ===\n- Sophia Lee: flagged for 'late submission'.\n"
        "- Ethan Nguyen: flagged for 'double-dipped invoices' and 'non-compliant vendor'.\n"
    )
    q = (
        "Which employee's expense report was the only one flagged for both "
        "'double-dipped invoices' and 'non-compliant vendor' in the final audit summary?"
    )
    assert sc.mc_heuristic(q, doc) == "Ethan Nguyen; $300"
    assert sc.mc_last(q, doc).startswith("Ethan Nguyen")


def test_multivac_last_status_and_clarifications():
    doc = (
        "Initial Requirements:\n- R102: Automated testing (Status: Pending, Priority: High)\n"
        "- R7: Other (Status: Blocked, Priority: Low)\n\n"
        "Update (Step 10): Requirement R102 status changed from Pending to In Progress (v2).\n\n"
        "Clarification (Step 11): Requirement R102 updated with: Must use open-source "
        "libraries (v3).\n\n"
        "Update (Step 12): Requirement R102 status changed from In Progress to Completed (v4).\n"
    )
    q = "What is the current status and full description of requirement R102?"
    assert sc.multivac_last(q, doc) == "R102: Automated testing — Status: Completed"
    assert sc.multivac_heuristic(q, doc) == (
        "R102: Automated testing (Must use open-source libraries) — Status: Completed"
    )


def test_neuromancer_sums_named_month_and_category():
    doc = (
        "From: Finance\nTo: Jack\nRe: March Travel\nYour claim is approved for $100.50. "
        "Payment will be issued.\n"
        "From: Finance\nTo: Carol\nRe: May Travel\nYour claim is approved for $999.00. "
        "Payment will be issued.\n"
        "From: Finance\nTo: Bob\nRe: March Travel\nYour claim is approved for $1.50. "
        "Payment will be issued.\n"
    )
    q = "What is the total amount reimbursed for travel expenses originally submitted in March?"
    assert sc.neuro_heuristic(q, doc) == "$102.00"
    assert sc.neuro_last(q, doc) == "$1.50"


def test_shodan_offices_and_money_helpers():
    q = (
        "What is the total earned credit for each of these offices: Alderwick, Brindleford, "
        "Cairnstead? Include offices with zero credits."
    )
    assert sc.shodan_heuristic(q, "") == "Alderwick: 0\nBrindleford: 0\nCairnstead: 0"
    doc = "Alderwick earned 552 units. Brindleford none. Cairnstead 356."
    assert sc.shodan_last(q, doc).splitlines()[0] == "Alderwick: 552"
    assert sc._money("1,594,550") == 1594550.0


@pytest.mark.parametrize("lane", sorted(sc.SOLVERS))
def test_every_solver_runs_on_the_pinned_generator(lane):
    manifest = json.loads((ROOT / "manifest.json").read_text())
    gen = sc.load_generator(lane, manifest)
    d = gen.generate(0, "small")
    for kind, fn in sc.SOLVERS[lane].items():
        ans = fn(d["question"], d["context"])
        assert isinstance(ans, str) and ans, (lane, kind)
        s = float(gen.score(ans, d["answer"]))
        assert 0.0 <= s <= 1.0


def test_report_flags_half_or_more():
    rows = [
        {
            "task": "T",
            "size": "small",
            "seed": s,
            "kind": k,
            "score": 1.0 if (k == "last" and s < 3) else 0.0,
        }
        for s in range(4)
        for k in ("last", "heuristic")
    ]
    md = sc.report(rows, "fixture")
    assert "| T | small | 4 | 3/4 | 0.75 | 0/4 | 0.00 | SEARCH |" in md
    assert "Flagged: T/small." in md
