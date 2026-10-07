"""The independent (roundtable-authored) generators that passed validation still work.

They are third-party code kept unmodified; this only guards against them silently
breaking (e.g. a Python upgrade). Sizes use "small" to keep CI fast.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "evals" / "independent"
MANIFEST = json.loads((ROOT / "manifest.json").read_text())
PASSING = [k for k, v in MANIFEST["generators"].items() if v["status"] == "pass"]


def _load(lane: str):
    path = ROOT / "generators" / f"{lane}.py"
    spec = importlib.util.spec_from_file_location(f"indep_{lane}", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("lane", sorted(MANIFEST["generators"]))
def test_generators_unmodified(lane: str) -> None:
    entry = MANIFEST["generators"][lane]
    digest = hashlib.sha256((ROOT / entry["file"]).read_bytes()).hexdigest()
    assert digest == entry["sha256"], f"{lane} generator was modified; originals must stay verbatim"


@pytest.mark.parametrize("lane", PASSING)
def test_passing_generator_small(lane: str) -> None:
    g = _load(lane)
    a, b = g.generate(0, "small"), g.generate(0, "small")
    assert a == b
    assert len(a["context"]) > 40_000
    assert g.score(str(a["answer"]), a["answer"]) == 1.0
    assert g.score("", a["answer"]) < 1.0
