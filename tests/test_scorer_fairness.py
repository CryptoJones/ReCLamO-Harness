"""The independent-eval scorers must stay fair: the audit's battery of correct answers in
reasonable formats and of wrong / hedged answers must raise zero flags on the active set
(round 4 since 2026-10-23) and on the round-4 set it was copied from (issue #95)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "evals" / "independent"
SCORER_SETS = ["fixed/active", "fixed/round4"]
# Declared in evals/TEST-PLAN.md section 1d: under round 4, "It moved from Room 101 to <key>"
# scores 1.0 because the final statement names the key as the destination. Nothing else.
# fixed/active is byte-identical to fixed/round4 since 2026-10-23, so both carry it.
ALLOWED = {
    "fixed/round4": {("TheDixieFlatline", "previous_location_too")},
    "fixed/active": {("TheDixieFlatline", "previous_location_too")},
}


@pytest.mark.parametrize("scorer_set", SCORER_SETS)
def test_scorer_battery_zero_flags(tmp_path: Path, scorer_set: str) -> None:
    out = tmp_path / "battery.json"
    subprocess.run(
        [
            sys.executable,
            "-I",
            str(ROOT / "audit/scripts/scorer_battery.py"),
            str(ROOT / scorer_set),
            str(out),
        ],
        check=True,
        capture_output=True,
        timeout=600,
    )
    flags = json.loads(out.read_text())["flags"]
    allowed = ALLOWED.get(scorer_set, set())
    flags = [f for f in flags if (f["task"], f["variant"]) not in allowed]
    assert flags == [], f"{scorer_set}: {len(flags)} scorer fairness flags, e.g. {flags[:3]}"
