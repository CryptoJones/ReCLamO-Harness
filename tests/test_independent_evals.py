"""Guards for the independent (roundtable-authored) eval generators.

Every file is third-party or third-party-repaired code, pinned by sha256 so nobody edits
it silently. The active evaluation set must still run (small size keeps CI fast).
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
GENS = MANIFEST["generators"]

PINNED = sorted(
    {(lane, g["file"], g["sha256"]) for lane, g in GENS.items()}
    | {(lane, a["file"], a["sha256"]) for lane, g in GENS.items() for a in g["fix_attempts"]}
    | {(lane, g["active"]["file"], g["active"]["sha256"]) for lane, g in GENS.items()}
)


def _load(path: Path):
    name = "indep_" + "_".join(path.relative_to(ROOT).with_suffix("").parts)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize(("lane", "rel", "digest"), PINNED, ids=[p[1] for p in PINNED])
def test_files_pinned(lane: str, rel: str, digest: str) -> None:
    assert hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() == digest, f"{rel} was modified"


@pytest.mark.parametrize("lane", sorted(GENS))
def test_active_generator_small(lane: str) -> None:
    g = _load(ROOT / GENS[lane]["active"]["file"])
    a, b = g.generate(0, "small"), g.generate(0, "small")
    assert a == b
    assert len(a["context"]) > 40_000
    assert g.score(str(a["answer"]), a["answer"]) == 1.0
    assert g.score("", a["answer"]) < 1.0
