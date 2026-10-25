"""The paper's existing arms stay byte for byte as they were (epic #80, issues #83, #84).

New baselines (REPL-only, map-reduce) are added behind a new prompt version or mode
that defaults off. This test pins what the existing arms send: the v0.1 and v0.2
system prompts (fence and tools protocols) over a grid of settings, the per-turn and
nudge texts, and the full request sequence plus the recorded row of scripted ``rlm``
(v0.1, v0.2) and ``plain`` runs through ``run_eval.run_row``.

``tests/data/frozen_arms.json`` holds a sha256 per rendered item. It was generated from
origin/main at e8f2959, before either baseline existed, with

    uv run python -m tests.test_frozen_arms --write

Regenerate it only for a change that is meant to alter an existing arm, and say so.
"""

from __future__ import annotations

import dataclasses
import hashlib
import importlib.util
import json
import sys
import types
from pathlib import Path
from typing import Any

from reclamo.config import load_config
from reclamo.prompts import (
    ContextMeta,
    PromptSettings,
    build_system_prompt,
    build_tools_system_prompt,
    decompose_nudge,
    final_rejection,
    forced_final_prompt,
    no_action_prompt,
    reverify_nudge,
    tool_specs,
    turn_prompt,
)
from tests.mocklm import MockLM

GOLDEN = Path(__file__).resolve().parent / "data" / "frozen_arms.json"
RUNNER = Path(__file__).resolve().parents[1] / "evals" / "independent" / "run_eval.py"
# Row fields that vary run to run (wall clock, temp paths).
VOLATILE = ("seconds", "started_at", "trajectory")


def _run_eval() -> types.ModuleType:
    if "run_eval" in sys.modules:
        return sys.modules["run_eval"]
    spec = importlib.util.spec_from_file_location("run_eval", RUNNER)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["run_eval"] = mod
    spec.loader.exec_module(mod)
    return mod


def _generator() -> types.ModuleType:
    mod = types.ModuleType("frozen_gen")

    def generate(seed: int, size: str) -> dict[str, Any]:
        n = {"small": 40, "medium": 400, "large": 4000}[size]
        lines = [f"record {i}: status pending, owner {i % 7} (seed {seed})" for i in range(n)]
        lines.insert(n // 3, "the vault code is 4417")
        return {
            "context": "\n".join(lines),
            "question": "What is the vault code?",
            "answer": "4417",
        }

    def score(answer_text: str, truth: Any) -> float:
        return 1.0 if str(truth) in answer_text else 0.0

    mod.generate = generate  # type: ignore[attr-defined]
    mod.score = score  # type: ignore[attr-defined]
    return mod


class RecordingLM(MockLM):
    """MockLM that also records max_tokens, which the base class drops."""

    def complete(self, messages: Any, role: str = "root", **kw: Any):  # type: ignore[override]
        out = super().complete(messages, role, **kw)
        self.calls[-1]["max_tokens"] = kw.get("max_tokens")
        # The deadline is a monotonic-clock instant; keep only whether one was sent.
        self.calls[-1]["deadline"] = self.calls[-1]["deadline"] is not None
        return out


RLM_SCRIPT = [
    "```repl\nprint(type(context), len(context))\nprint(context[:200])\n```",
    "```repl\nhits = [l for l in context.splitlines() if 'vault' in l]\n"
    "a = llm_query('Find the vault code: ' + hits[0])\n"
    "b = llm_query_batched(['q1', 'q2'])\nprint(hits, a, b)\n```",
    "FINAL(4417)",
]


def _row_items(name: str, mode: str, version: str | None, size: str) -> dict[str, Any]:
    run_eval = _run_eval()
    cfg = load_config("pluto", user_file="/nonexistent/profiles.toml", env={})
    if version:
        cfg = dataclasses.replace(cfg, prompt_version=version)
    gens = run_eval.Generators({"generators": {"Frozen": {"vendor": "v", "model": "m"}}})
    gens.add("Frozen", _generator())
    lm = RecordingLM(list(RLM_SCRIPT) if mode == "rlm" else ["The code is 4417."])
    row = run_eval.run_row(cfg, lm, gens, "Frozen", size, mode, 0, None)
    for key in VOLATILE:
        row.pop(key, None)
    return {
        f"{name}/calls": json.dumps(lm.calls, sort_keys=True, default=str),
        f"{name}/row": json.dumps(row, sort_keys=True, default=str),
    }


def render_all() -> dict[str, str]:
    """Every pinned text, keyed by a readable name."""
    out: dict[str, str] = {}
    metas = {
        "str": ContextMeta(kind="str", total_chars=1_234_567),
        "small": ContextMeta(kind="str", total_chars=9_000),
        "list": ContextMeta(kind="list", total_chars=88_000, chunk_lengths=[8_000] * 11),
    }
    for version in ("v0.1", "v0.2"):
        for depth in (1, 2):
            for conc in (1, 2):
                for chars in (12_000, 50_000):
                    s = PromptSettings(
                        subcall_chars=chars,
                        max_depth=depth,
                        concurrency=conc,
                        prompt_version=version,
                    )
                    for mname, meta in metas.items():
                        key = f"{version}/d{depth}/c{conc}/s{chars}/{mname}"
                        out[f"system/{key}"] = build_system_prompt(s, meta)
                        out[f"tools-system/{key}"] = build_tools_system_prompt(s, meta)
    for profile in ("pluto", "pluto-long"):
        base = load_config(profile, user_file="/nonexistent/profiles.toml", env={})
        for version in ("v0.1", "v0.2"):
            cfg = dataclasses.replace(base, prompt_version=version)
            out[f"cfg-system/{profile}/{version}"] = build_system_prompt(cfg, metas["str"])
    for version in ("v0.1", "v0.2"):
        out[f"decompose/{version}"] = decompose_nudge(version, 100_000, 12_000)
    for protocol in ("fence", "tools"):
        out[f"turn/{protocol}"] = turn_prompt(1, 20, True, protocol) + turn_prompt(3, 20)
        out[f"reverify/{protocol}"] = reverify_nudge("ans", protocol)
        out[f"reject/{protocol}"] = final_rejection("why.", protocol)
        out[f"no-action/{protocol}"] = no_action_prompt(protocol)
        for why in ("turns", "time", "errors", "context"):
            out[f"forced/{protocol}/{why}"] = forced_final_prompt(why, protocol)
    out["tool-specs"] = json.dumps(tool_specs(2_000), sort_keys=True)
    out.update(_row_items("run/rlm-v0.1", "rlm", "v0.1", "small"))
    out.update(_row_items("run/rlm-v0.2", "rlm", "v0.2", "small"))
    out.update(_row_items("run/plain", "plain", None, "small"))
    out.update(_row_items("run/plain-medium", "plain", None, "medium"))
    out.update(_row_items("run/plain-large", "plain", None, "large"))
    return out


def digests() -> dict[str, str]:
    return {k: hashlib.sha256(v.encode()).hexdigest() for k, v in sorted(render_all().items())}


def test_existing_arms_are_byte_for_byte_unchanged() -> None:
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    actual = digests()
    assert sorted(actual) == sorted(expected)
    changed = [k for k in expected if actual[k] != expected[k]]
    assert not changed, f"existing arm output changed: {changed}"


if __name__ == "__main__":
    if "--write" in sys.argv:
        GOLDEN.write_text(json.dumps(digests(), indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {GOLDEN}")
    else:
        print(json.dumps(digests(), indent=1, sort_keys=True))
