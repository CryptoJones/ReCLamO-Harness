"""The independent-eval scorers must stay fair: the audit's battery of correct answers in
reasonable formats and of wrong / hedged answers must raise zero flags on the active set."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "evals" / "independent"


def test_scorer_battery_zero_flags(tmp_path: Path) -> None:
    out = tmp_path / "battery.json"
    subprocess.run(
        [
            sys.executable,
            "-I",
            str(ROOT / "audit/scripts/scorer_battery.py"),
            str(ROOT / "fixed/active"),
            str(out),
        ],
        check=True,
        capture_output=True,
        timeout=600,
    )
    flags = json.loads(out.read_text())["flags"]
    assert flags == [], f"{len(flags)} scorer fairness flags, e.g. {flags[:3]}"
