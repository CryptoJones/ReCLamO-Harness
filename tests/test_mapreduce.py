"""The fixed-chunk map-reduce baseline arm (issue #84)."""

from __future__ import annotations

import dataclasses
import importlib
from typing import Any

import pytest

from reclamo.client import LMClient
from reclamo.config import RLMConfig, load_config
from reclamo.rlm import RLM
from tests.conftest import FakeServer, chat_response, make_config
from tests.mocklm import MockLM
from tests.test_frozen_arms import _generator, _run_eval

run_eval = _run_eval()  # puts examples/ on sys.path
bench = importlib.import_module("bench")

# The keys an rlm row carries that every comparison reads (issue #84).
RLM_KEYS = {
    "subcalls",
    "tokens",
    "prompt_tokens",
    "completion_tokens",
    "seconds",
    "stop_reason",
    "answer",
    "score",
    "exact",
    "correct",
    "error",
    "turns",
    "trajectory",
}


def _gens() -> Any:
    gens = run_eval.Generators({"generators": {"Frozen": {"vendor": "v", "model": "m"}}})
    gens.add("Frozen", _generator())
    return gens


def _small_window(**kw: Any) -> RLMConfig:
    """A 4K window (sub max_tokens 2,048, root 1,000) so the medium document needs
    several chunks and the aggregation still has room."""
    cfg = make_config("http://x", context_tokens=4_096, **kw)
    return dataclasses.replace(cfg, root=dataclasses.replace(cfg.root, max_tokens=1_000))


def _reader(prompt: str) -> str:
    return "The vault code is 4417." if "vault code is" in prompt else "Nothing relevant."


# --- chunking ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "\n".join(f"line {i}: some prose about nothing in particular" for i in range(500)),
        "x" * 10_000,  # no newline: hard cuts
        "1234567890" * 1_000,  # digits count one token each
        "short",
        "",
    ],
)
@pytest.mark.parametrize("budget", [1, 50, 700])
def test_split_fixed_chunks_fit_and_rejoin(text: str, budget: int) -> None:
    chunks = bench.split_fixed(text, budget)
    assert "".join(chunks) == text
    assert all(c and bench.estimate_tokens(c) <= budget for c in chunks)
    assert chunks == bench.split_fixed(text, budget)  # deterministic


def test_split_fixed_cuts_are_maximal_without_newlines() -> None:
    text = "ab1 " * 3_000
    chunks = bench.split_fixed(text, 300)
    pos = 0
    for chunk in chunks[:-1]:
        pos += len(chunk)
        assert bench.estimate_tokens(chunk + text[pos]) > 300  # one more char would not fit


def test_split_fixed_moves_back_to_a_newline_in_the_second_half() -> None:
    text = "\n".join("r" * 40 for _ in range(200))
    chunks = bench.split_fixed(text, 100)  # 100 tokens = 350 chars; lines are 41
    assert all(c.endswith("\n") for c in chunks[:-1])
    assert {len(c) for c in chunks[:-1]} == {41 * 8}  # 8 whole lines, not a ragged 350
    # A newline in the first half is not used: the cut stays hard.
    text = "a" * 10 + "\n" + "b" * 2_000
    first = bench.split_fixed(text, 100)[0]
    assert len(first) == 350


def test_chunk_budget_is_the_reader_window_minus_reserve_and_overhead() -> None:
    cfg = dataclasses.replace(
        load_config("pluto", user_file="/nonexistent/profiles.toml", env={}), prompt_version="v0.1"
    )
    q = "What is the vault code?"
    overhead = bench.estimate_tokens(bench.map_prompt("", q, 999_999, 999_999))
    assert bench.chunk_token_budget(cfg, q) == 32_768 - 2_048 - overhead
    # A full chunk plus its prompt fits the reader's usable window.
    chunk = bench.split_fixed("word " * 100_000, bench.chunk_token_budget(cfg, q))[0]
    assert bench.estimate_tokens(bench.map_prompt(chunk, q, 1, 9)) <= 32_768 - 2_048


def test_chunk_budget_uses_the_sub_role_window_when_set() -> None:
    cfg = _small_window()
    sub = dataclasses.replace(cfg.sub, context_tokens=8_192)
    wide = dataclasses.replace(cfg, sub=sub)
    assert bench.chunk_token_budget(wide, "q") - bench.chunk_token_budget(cfg, "q") == 4_096


# --- aggregation ---------------------------------------------------------------------


def test_reduce_prompt_lists_every_answer_in_order() -> None:
    prompt = bench.reduce_prompt(["first", "second", "third"], "Q?")
    assert prompt.index("PART 1 OF 3 ===\nfirst") < prompt.index("PART 2 OF 3 ===\nsecond")
    assert prompt.index("PART 3 OF 3 ===\nthird") < prompt.index("Question: Q?")
    assert "cut to its first" not in prompt


def test_fit_reduce_cuts_every_answer_to_an_equal_share_when_needed() -> None:
    cfg = _small_window()
    small = ["short answer"] * 3
    prompt, cut = bench.fit_reduce(cfg, small, "Q?")
    assert cut is None and prompt == bench.reduce_prompt(small, "Q?")
    big = [f"answer {i} " + "z" * 9_000 for i in range(4)]
    prompt, cut = bench.fit_reduce(cfg, big, "Q?")
    assert cut is not None and 0 < cut < 9_000
    assert bench.estimate_tokens(prompt) <= 4_096 - 1_000
    assert prompt == bench.reduce_prompt([a[:cut] for a in big], "Q?", cut)
    assert f"cut to its first {cut:,} characters" in prompt
    # The largest equal cut: one more character would not fit.
    longer = bench.reduce_prompt([a[: cut + 1] for a in big], "Q?", cut + 1)
    assert bench.estimate_tokens(longer) > 4_096 - 1_000


# --- one row -------------------------------------------------------------------------


def test_mapreduce_row_reads_every_chunk_then_aggregates_once() -> None:
    cfg = _small_window()
    lm = MockLM(root=["The vault code is 4417."], sub=_reader)
    row = run_eval.run_row(cfg, lm, _gens(), "Frozen", "medium", "mapreduce", 0, None)
    n = row["chunks"]
    assert n > 2 and len(lm.sub_calls) == n and len(lm.root_calls) == 1
    assert row["subcalls"] == n and row["calls"] == n + 1
    assert row["tokens"] == 15 * (n + 1)
    assert (row["prompt_tokens"], row["completion_tokens"]) == (10 * (n + 1), 5 * (n + 1))
    assert row["score"] == 1.0 and row["exact"] is True and row["stop_reason"] == "stop"
    assert row["error"] is None and row["aggregate_truncated"] is False
    assert RLM_KEYS <= set(row) and row["mode"] == "mapreduce"
    assert sum(row["chunk_chars"]) == row["chars"]
    # Every reader call is one user message holding one chunk, the question and its index.
    texts = sorted((c["messages"] for c in lm.sub_calls), key=lambda m: m[0]["content"])
    for messages in texts:
        assert len(messages) == 1 and messages[0]["role"] == "user"
        assert "Question: What is the vault code?" in messages[0]["content"]
    assert all(c["enable_thinking"] is None for c in lm.sub_calls)  # the role decides
    reduce = lm.root_calls[0]["messages"]
    assert len(reduce) == 1 and f"cut into {n} parts" in reduce[0]["content"]
    assert reduce[0]["content"].count("=== ANSWER FOR PART") == n
    assert row["map_answers"].count("The vault code is 4417.") == 1


def test_mapreduce_scores_with_the_task_scorer() -> None:
    lm = MockLM(root=["I could not tell."], sub=_reader)
    row = run_eval.run_row(_small_window(), lm, _gens(), "Frozen", "small", "mapreduce", 0, None)
    assert row["score"] == 0.0 and row["exact"] is False and row["chunks"] == 1


def test_a_reader_failure_is_an_error_row() -> None:
    def broken(_prompt: str) -> str:
        raise RuntimeError("server went away")

    lm = MockLM(root=[], sub=broken)
    row = run_eval.run_row(_small_window(), lm, _gens(), "Frozen", "medium", "mapreduce", 0, None)
    assert row["stop_reason"] == "error" and row["error"] == "RuntimeError: server went away"
    assert row["score"] == 0.0 and row["exact"] is False and row["answer"] == ""
    assert lm.root_calls == []


def test_an_aggregation_failure_is_an_error_row() -> None:
    lm = MockLM(root=[RuntimeError("boom")], sub=_reader)
    row = run_eval.run_row(_small_window(), lm, _gens(), "Frozen", "medium", "mapreduce", 0, None)
    assert row["stop_reason"] == "error" and row["error"] == "RuntimeError: boom"
    assert row["subcalls"] == row["chunks"] and row["calls"] == row["chunks"]
    assert row["tokens"] == 15 * row["chunks"]


def test_reader_requests_match_harness_subcalls_and_the_aggregate_the_root(
    fake_server: FakeServer,
) -> None:
    """Over HTTP: a map call's request is a harness llm_query's, bar the messages, and
    the aggregation's is a root request's."""
    cfg = make_config(fake_server.base_url)
    client = LMClient(cfg, "k", sleep=lambda _s: None)
    fake_server.script(
        chat_response("```repl\nprint(llm_query('hello'))\n```"),
        chat_response("sub answer"),
        chat_response("FINAL(ok)"),
    )
    RLM(cfg, client).completion("some context", "q")
    harness = [{k: v for k, v in r.body.items() if k != "messages"} for r in fake_server.requests]
    harness_sub = harness[1]
    fake_server.requests.clear()
    client.complete([{"role": "user", "content": "x"}], "root")
    plain_root = {k: v for k, v in fake_server.requests[0].body.items() if k != "messages"}
    fake_server.requests.clear()

    inst = bench.Instance("indep/Frozen", "small", 0, "doc text\n" * 10, "q", "x", {})
    run_eval.register("Frozen", _generator())
    row = bench.run_mapreduce(cfg, client, inst)
    assert row["error"] is None
    sent = [{k: v for k, v in r.body.items() if k != "messages"} for r in fake_server.requests]
    assert sent[:-1] == [harness_sub] * row["chunks"]
    assert sent[-1] == plain_root
    assert harness_sub["max_tokens"] == 2_048 and harness_sub["temperature"] == 0.7
    assert harness_sub != plain_root  # the two roles really are configured differently


# --- run_eval wiring -----------------------------------------------------------------


def test_mapreduce_is_an_opt_in_run_eval_mode() -> None:
    assert "mapreduce" in run_eval.MODES and "mapreduce" not in run_eval.DEFAULT_MODES
    args = run_eval.build_parser().parse_args(["--modes", "mapreduce"])
    assert run_eval._csv(args.modes, run_eval.MODES, "mode(s)") == ["mapreduce"]


def test_summary_and_dry_run_show_mapreduce() -> None:
    lm = MockLM(root=["The vault code is 4417."], sub=_reader)
    row = run_eval.run_row(_small_window(), lm, _gens(), "Frozen", "medium", "mapreduce", 0, None)
    summary = run_eval.format_summary([row])
    assert "| medium | mapreduce | 1 | 1.00 |" in summary
    dry = run_eval.format_dry_run(_small_window(), _gens(), [("Frozen", "medium", "mapreduce", 0)])
    assert f"{row['chunks']} chunk(s) + 1 aggregation" in dry
