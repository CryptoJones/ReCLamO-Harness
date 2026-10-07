from __future__ import annotations

import os
import time
from collections.abc import Iterator
from typing import Any

import pytest

from reclamo.config import ModelConfig, RLMConfig
from reclamo.repl import SubprocessREPL
from reclamo.repl.subprocess_repl import WORKER_PATH


def _cfg(**overrides: Any) -> RLMConfig:
    fields: dict[str, Any] = {
        "name": "test",
        "base_url": "http://unused/v1",
        "exec_timeout": 10.0,
        "output_truncate_chars": 200,
        "max_subcalls_per_exec": 3,
        "root": ModelConfig(model="m"),
        "sub": ModelConfig(model="m"),
    }
    fields.update(overrides)
    return RLMConfig(**fields)


class Handler:
    """Records every request; answers are ``f"{kind}:{prompt}"`` unless told to fail."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str]]] = []
        self.fail_with: Exception | None = None

    def __call__(self, kind: str, prompts: list[str]) -> list[str]:
        self.calls.append((kind, list(prompts)))
        if self.fail_with:
            raise self.fail_with
        return [f"{kind}:{p}" for p in prompts]


@pytest.fixture
def handler() -> Handler:
    return Handler()


@pytest.fixture
def repl(handler: Handler) -> Iterator[SubprocessREPL]:
    r = SubprocessREPL(_cfg(), handler)
    r.start("line one\nline two\nline three\n")
    try:
        yield r
    finally:
        r.close()


# --- basics -----------------------------------------------------------------


def test_worker_is_standalone_stdlib_only() -> None:
    src = WORKER_PATH.read_text(encoding="utf-8")
    assert "from reclamo" not in src and "import reclamo" not in src


def test_context_loaded_and_state_persists(repl: SubprocessREPL) -> None:
    r = repl.execute("n = len(context.splitlines())\nprint(type(context).__name__, n)")
    assert r.ok and r.stdout == "str 3\n"
    assert "n" in r.vars
    r2 = repl.execute("print(n * 2)")
    assert r2.stdout == "6\n"


def test_last_expression_is_echoed(repl: SubprocessREPL) -> None:
    assert repl.execute("x = 41\nx + 1").stdout == "42\n"
    assert repl.execute("'a' * 3").stdout == "'aaa'\n"
    assert repl.execute("None").stdout == ""
    assert repl.execute("x = 5").stdout == ""  # assignment, nothing echoed


def test_output_truncation_notice(repl: SubprocessREPL) -> None:
    r = repl.execute("print('x' * 1000)")
    assert r.truncated_chars == 801  # 1001 chars incl. newline, limit 200
    assert r.stdout.startswith("x" * 200)
    assert r.stdout.endswith("[truncated: 801 chars; store it in a variable]")


def test_syntax_error_one_liner(repl: SubprocessREPL) -> None:
    r = repl.execute("x = 1\nif x\n    pass")
    assert r.error is not None
    assert r.error.startswith("SyntaxError:")
    assert r.error.endswith("(line 2)")
    assert "\n" not in r.error


def test_runtime_error_carries_line_number(repl: SubprocessREPL) -> None:
    r = repl.execute("a = 1\nb = 2\nc = undefined_name\n")
    assert r.error == "NameError: name 'undefined_name' is not defined (line 3)"
    assert repl.execute("print(a + b)").stdout == "3\n"  # earlier statements ran


def test_stderr_is_captured(repl: SubprocessREPL) -> None:
    r = repl.execute("import sys\nsys.stderr.write('warn\\n')\nprint('ok')")
    assert r.stdout == "ok\n" and r.stderr == "warn\n"
    assert r.output == "ok\nwarn"


def test_multiple_statements_and_imports(repl: SubprocessREPL) -> None:
    r = repl.execute("import re\nhits = re.findall(r'line', context)\nlen(hits)")
    assert r.stdout == "3\n"
    assert "re" not in r.vars and "hits" in r.vars


# --- sub-calls --------------------------------------------------------------


def test_llm_query_round_trip(repl: SubprocessREPL, handler: Handler) -> None:
    r = repl.execute("reply = llm_query('What is 2+2?')\nprint(reply)")
    assert r.ok and r.stdout == "llm_query:What is 2+2?\n"
    assert handler.calls == [("llm_query", ["What is 2+2?"])]
    assert r.subcalls == 1 and repl.total_subcalls == 1


def test_llm_query_batched_keeps_order(repl: SubprocessREPL, handler: Handler) -> None:
    r = repl.execute("out = llm_query_batched(['a', 'b', 'c'])\nprint(out)")
    assert r.stdout == "['llm_query_batched:a', 'llm_query_batched:b', 'llm_query_batched:c']\n"
    assert handler.calls == [("llm_query_batched", ["a", "b", "c"])]
    assert r.subcalls == 3


def test_rlm_query_is_forwarded(repl: SubprocessREPL, handler: Handler) -> None:
    r = repl.execute("print(rlm_query('deep'))")
    assert r.stdout == "rlm_query:deep\n"
    assert handler.calls[0][0] == "rlm_query"


def test_per_exec_cap_raises_inside_user_code(repl: SubprocessREPL, handler: Handler) -> None:
    code = "got = []\nfor i in range(10):\n    got.append(llm_query(str(i)))"
    r = repl.execute(code)
    assert r.error is not None and r.error.startswith("RuntimeError: sub-call cap reached")
    assert "(line 3)" in r.error
    assert len(handler.calls) == 3 and r.subcalls == 3
    # the counter is per exec: a new block can call again
    assert repl.execute("print(llm_query('again'))").stdout == "llm_query:again\n"
    # and the partial results survived
    assert repl.execute("print(got)").stdout == "['llm_query:0', 'llm_query:1', 'llm_query:2']\n"


def test_batched_counts_each_prompt_toward_cap(repl: SubprocessREPL, handler: Handler) -> None:
    r = repl.execute("llm_query_batched(['1', '2', '3', '4'])")
    assert r.error is not None and "sub-call cap reached" in r.error
    assert handler.calls == []


def test_handler_exception_becomes_user_exception(repl: SubprocessREPL, handler: Handler) -> None:
    handler.fail_with = ConnectionError("pluto is down")
    r = repl.execute("try:\n    llm_query('x')\nexcept RuntimeError as e:\n    print('caught:', e)")
    assert r.ok
    assert r.stdout == "caught: ConnectionError: pluto is down\n"


def test_non_string_prompt_rejected(repl: SubprocessREPL, handler: Handler) -> None:
    r = repl.execute("llm_query(42)")
    assert r.error == "TypeError: llm_query prompts must be str, got int (line 1)"
    assert handler.calls == []


# --- answer / FINAL_VAR / SHOW_VARS -------------------------------------------


def test_answer_dict_ready_detection(repl: SubprocessREPL) -> None:
    r = repl.execute("answer['content'] = 'needle on line 2'")
    assert r.answer == {"ready": False, "content": "needle on line 2"}
    assert not r.answer_ready
    r = repl.execute("answer['ready'] = True")
    assert r.answer_ready and r.answer is not None
    assert r.answer["content"] == "needle on line 2"


def test_answer_rebound_to_non_dict_is_recreated(repl: SubprocessREPL) -> None:
    r = repl.execute("answer = 'oops'")
    assert r.answer is None
    r = repl.execute("answer['content'] = 'fine'\nanswer['ready'] = True")
    assert r.answer == {"ready": True, "content": "fine"}


def test_answer_reset_to_empty_dict(repl: SubprocessREPL) -> None:
    repl.execute("answer['ready'] = True\nanswer['content'] = 'x'")
    r = repl.execute("answer = {}")
    assert r.answer is None


def test_final_var_callable_in_code(repl: SubprocessREPL) -> None:
    r = repl.execute("result = 17\nprint(FINAL_VAR('result'))")
    assert r.stdout == "17\n"
    r = repl.execute("FINAL_VAR('nope')")
    assert r.error == "NameError: FINAL_VAR: no variable named 'nope' (line 1)"


def test_show_vars(repl: SubprocessREPL) -> None:
    assert repl.execute("SHOW_VARS()").stdout == "(no variables yet)\n"
    repl.execute("import os\ncount = 3\nnames = ['a', 'b']\ndef f(): pass")
    out = repl.execute("SHOW_VARS()").stdout
    assert "count: int" in out and "names: list (len 2)" in out
    assert "os" not in out and "f:" not in out and "context" not in out


def test_reserved_names_restored_after_clobber(repl: SubprocessREPL, handler: Handler) -> None:
    repl.execute("llm_query = None\ndel SHOW_VARS")
    r = repl.execute("print(llm_query('still here'))\nSHOW_VARS()")
    assert r.ok and r.stdout.startswith("llm_query:still here\n")


def test_context_restored_only_if_deleted(repl: SubprocessREPL) -> None:
    repl.execute("context = context[:8]")
    assert repl.execute("print(len(context))").stdout == "8\n"  # slice kept
    repl.execute("del context")
    assert repl.execute("print(len(context))").stdout == "29\n"  # original back


# --- get_var ------------------------------------------------------------------


def test_get_var_found_and_missing(repl: SubprocessREPL) -> None:
    repl.execute("ans = 'needle on line 2'\nbig = list(range(5000))")
    v = repl.get_var("ans")
    assert v.found and v.value_str == "needle on line 2" and v.value_repr == "'needle on line 2'"
    assert repl.get_var("missing").found is False
    big = repl.get_var("big")
    assert big.found and big.value_repr is not None and "more chars]" in big.value_repr
    assert big.value_str is not None and big.value_str.endswith("4999]")


# --- robustness ---------------------------------------------------------------


def test_timeout_kills_and_restarts(handler: Handler) -> None:
    r = SubprocessREPL(_cfg(exec_timeout=0.5), handler)
    r.start("ctx")
    try:
        r.execute("keep = 'me'")
        res = r.execute("import time\ntime.sleep(30)")
        assert res.restarted
        assert res.error == "timeout after 0.5s; REPL restarted, variables lost"
        assert r.restarts == 1
        after = r.execute("print(context); print('keep' in dir())")
        assert after.ok and after.stdout == "ctx\nFalse\n"
    finally:
        r.close()


def test_worker_crash_restarts(repl: SubprocessREPL) -> None:
    repl.execute("v = 1")
    res = repl.execute("import os\nos._exit(3)")
    assert res.restarted and res.error is not None and res.error.startswith("REPL crashed")
    assert repl.restarts == 1
    assert repl.execute("print('v' in dir(), len(context))").stdout == "False 29\n"


def test_llm_time_does_not_count_against_exec_timeout() -> None:
    class SlowHandler(Handler):
        def __call__(self, kind: str, prompts: list[str]) -> list[str]:
            time.sleep(0.8)
            return super().__call__(kind, prompts)

    r = SubprocessREPL(_cfg(exec_timeout=0.5), SlowHandler())
    r.start("ctx")
    try:
        res = r.execute("print(llm_query('slow'))")
        assert res.ok and res.stdout == "llm_query:slow\n"
    finally:
        r.close()


def test_child_env_is_scrubbed(monkeypatch: pytest.MonkeyPatch, handler: Handler) -> None:
    monkeypatch.setenv("RECLAMO_API_KEY", "sk-should-not-leak")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-leak-either")
    monkeypatch.setenv("RECLAMO_BASE_URL", "http://nope")
    r = SubprocessREPL(_cfg(), handler)
    r.start("ctx")
    try:
        res = r.execute(
            "import os\nprint(sorted(os.environ))\n"
            "print(os.path.realpath(os.environ['HOME']) == os.path.realpath(os.getcwd()))"
        )
        assert "RECLAMO_API_KEY" not in res.stdout
        assert "OPENAI_API_KEY" not in res.stdout
        assert "RECLAMO_BASE_URL" not in res.stdout
        assert "should-not-leak" not in res.stdout
        assert res.stdout.endswith("True\n")
    finally:
        r.close()


def test_c_level_stdout_write_does_not_corrupt_protocol(repl: SubprocessREPL) -> None:
    res = repl.execute("import os\nos.write(1, b'raw bytes to fd 1\\n')\nprint('after')")
    assert res.ok and res.stdout == "after\n"
    assert repl.execute("1 + 1").stdout == "2\n"


def test_input_is_unavailable(repl: SubprocessREPL) -> None:
    res = repl.execute("input('name? ')")
    assert res.error == "RuntimeError: input() is not available in the REPL (line 1)"


def test_json_context_loaded_as_object(handler: Handler) -> None:
    r = SubprocessREPL(_cfg(), handler)
    r.start({"rows": [1, 2, 3], "name": "x"}, kind="json")
    try:
        res = r.execute("print(type(context).__name__, context['rows'], context['name'])")
        assert res.stdout == "dict [1, 2, 3] x\n"
    finally:
        r.close()


def test_close_removes_tempdir_and_kills_worker(handler: Handler) -> None:
    r = SubprocessREPL(_cfg(), handler)
    r.start("ctx")
    tmp = r._tmp
    assert tmp is not None and os.path.isdir(tmp)
    proc = r._proc
    r.close()
    assert not os.path.exists(tmp)
    assert proc is not None and proc.poll() is not None


def test_context_manager(handler: Handler) -> None:
    with SubprocessREPL(_cfg(), handler) as r:
        r.start("ctx")
        assert r.execute("len(context)").stdout == "3\n"
    assert r._proc is None
