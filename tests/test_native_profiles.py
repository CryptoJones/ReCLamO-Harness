"""The native-sampling profiles of issue #69 differ from their base profiles in sampling only."""

from __future__ import annotations

import dataclasses
import importlib.util
import sys
from pathlib import Path

import pytest

from reclamo.config import load_config

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "evals" / "independent" / "profiles-native.toml"
GGUF_DEFAULTS = {"temperature": 1.0, "top_p": 0.95, "top_k": 20}

_spec = importlib.util.spec_from_file_location(
    "run_eval_native", ROOT / "evals" / "independent" / "run_eval.py"
)
assert _spec is not None and _spec.loader is not None
run_eval = importlib.util.module_from_spec(_spec)
sys.modules["run_eval_native"] = run_eval
_spec.loader.exec_module(run_eval)


@pytest.mark.parametrize("base", ["pluto", "pluto-long"])
@pytest.mark.parametrize("prompt_version", [None, "v0.1", "v0.2"])
def test_native_twin_changes_sampling_and_nothing_else(
    base: str, prompt_version: str | None
) -> None:
    preset = load_config(base, NATIVE, env={})
    native = load_config(f"{base}-native", NATIVE, env={})
    if prompt_version:
        preset = dataclasses.replace(preset, prompt_version=prompt_version)
        native = dataclasses.replace(native, prompt_version=prompt_version)

    assert native.root.sampling == GGUF_DEFAULTS
    assert native.sub.sampling == GGUF_DEFAULTS
    assert preset.root.sampling != native.root.sampling
    assert preset.sub.sampling != native.sub.sampling

    aligned = dataclasses.replace(
        native,
        name=preset.name,
        root=dataclasses.replace(native.root, sampling=preset.root.sampling),
        sub=dataclasses.replace(native.sub, sampling=preset.sub.sampling),
    )
    assert aligned == preset


def test_native_file_leaves_the_builtin_profiles_alone() -> None:
    for base in ("pluto", "pluto-long"):
        assert load_config(base, NATIVE, env={}) == load_config(base, ROOT / "no-such-file", env={})


def test_sampling_record_names_both_roles() -> None:
    cfg = load_config("pluto-native", NATIVE, env={})
    assert run_eval.sampling_record(cfg) == {"root": GGUF_DEFAULTS, "sub": GGUF_DEFAULTS}
    preset = run_eval.sampling_record(load_config("pluto", NATIVE, env={}))
    assert preset["root"] == {"temperature": 0.6, "top_p": 0.95, "top_k": 20, "min_p": 0.0}
    assert preset["sub"] == {"temperature": 0.7, "top_p": 0.8, "top_k": 20, "presence_penalty": 1.0}
