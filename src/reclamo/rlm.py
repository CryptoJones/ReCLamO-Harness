"""The Recursive Language Model loop.

``RLM.completion(context, query)`` runs up to ``max_iterations`` turns. Each
turn the root model writes code, the REPL runs it, and the model sees a short
output. The history is append-only (one user message per turn carrying the
REPL output and the next ``Turn i/N`` line) so a server with a prefix cache
reuses it. Sub-calls made from inside the REPL (``llm_query``,
``llm_query_batched``, ``rlm_query``) come back to this process through the
REPL's handler, which enforces the per-run budget and, for ``rlm_query``,
starts a child ``RLM`` one level deeper.

``rlm_query(question, data)`` semantics: ``data`` becomes the child's
*context* and ``question`` its query, exactly like the root. The one-argument
form ``rlm_query(prompt)`` makes the prompt the child's context and gives it a
fixed query telling it to carry out the task found there. Either way the
child can slice and search what it was handed, which is the whole point of
recursing. At ``max_depth`` both degrade to a plain ``llm_query``.

Termination, in priority order per turn: an ``answer`` dict marked ready in
the REPL; then a ``FINAL`` / ``FINAL_VAR`` candidate in the prose (rejected,
with a corrective message, when it sits next to unexecuted code, names a
missing variable, or reads like a plan the first time it is seen). When turns
run out the loop prefers an answer that already exists in the REPL over asking
the model again (paper failure E.2).

``protocol="tools"`` (issue #20) runs the same loop over OpenAI-style function
calls: ``execute_python(code)`` replaces the fenced block and
``final_answer(answer | variable)`` replaces ``FINAL`` / ``FINAL_VAR``. Each
turn appends the assistant message with its ``tool_calls``, then one
``role: "tool"`` message per call (in call order, matching ``tool_call_id``),
then a user message with any notes and the next ``Turn i/N`` line, so the
history stays append-only and valid for the chat template. A text reply with
no tool call gets a nudge; a fenced block or a ``FINAL(...)`` in the text is
honoured once as a courtesy and counted as a protocol slip. Every guard that
applies to the fence protocol applies here too.
"""

from __future__ import annotations

import dataclasses
import functools
import hashlib
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from reclamo.client import Completion, ToolCall, Usage
from reclamo.config import RLMConfig
from reclamo.errors import RLMErrorLimit, RLMTimeout, RLMTokenLimit
from reclamo.logger import TrajectoryLogger, VerbosePrinter
from reclamo.parsing import FinalCandidate, find_code_blocks, find_final, looks_like_plan
from reclamo.prompts import (
    ContextMeta,
    build_system_prompt,
    build_tools_system_prompt,
    decompose_nudge,
    fence_slip_note,
    final_rejection,
    forced_final_prompt,
    no_action_prompt,
    reverify_nudge,
    tool_specs,
    turn_prompt,
)
from reclamo.repl import make_repl
from reclamo.repl.base import REPL, ExecResult, LLMHandler


class LMLike(Protocol):
    def complete(
        self,
        messages: Any,
        role: str = "root",
        *,
        enable_thinking: bool | None = None,
        max_tokens: int | None = None,
    ) -> Completion: ...


REPLFactory = Callable[[RLMConfig, LLMHandler], REPL]

# Variables the forced finish looks for, in order, when the model never said FINAL.
ANSWER_VAR_NAMES = ("final_answer", "answer_text", "result", "final")
CHARS_PER_TOKEN = 3.5
KEEP_RECENT_TURNS = 4
SUMMARY_CHARS = 1_500
NO_ACTION_PROMPT = no_action_prompt("fence")
TOOL_NAMES = ("execute_python", "final_answer")
RLM_QUERY_PROMPT = (
    "The context holds a task handed down by a parent process: instructions and the "
    "data they apply to. Carry out the task and finish with the result."
)
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# Qwen writes FINAL_VAR(answer['content']) after filling the answer dict without
# setting ready=True (seen live, nested.py depth 1): treat it as the dict's content.
_ANSWER_CONTENT = re.compile(r"""^answer\s*\[\s*(['"])content\1\s*\]$""")


@dataclass
class RLMResult:
    answer: str
    iterations: int
    subcalls: int
    usage: Usage
    elapsed: float
    stop_reason: str  # final | final_var | answer_dict | max_iterations
    trajectory_path: str | None
    depth: int = 0
    child_turns: int = 0  # root turns taken by nested RLMs (depth >= 1), whole run
    protocol: str = "fence"
    # executions, syntax_errors, exec_errors, final_rejections, slips: {kind: count}
    stats: dict[str, Any] = field(default_factory=dict)


@dataclass
class RunBudget:
    """Shared by a root RLM and every child it spawns."""

    max_subcalls: int
    deadline: float | None
    max_tokens: int | None
    started: float = field(default_factory=time.monotonic)
    subcalls: int = 0
    subcall_chars: int = 0
    child_turns: int = 0  # root-role turns taken at depth >= 1
    usage: Usage = field(default_factory=Usage)

    def add(self, completion: Completion) -> None:
        if completion.usage is not None:
            self.usage.add(completion.usage)


def describe_context(context: Any) -> tuple[str, ContextMeta]:
    """Return the REPL load kind ('str' or 'json') and what to tell the model."""
    if isinstance(context, str):
        return "str", ContextMeta("str", len(context))
    if isinstance(context, list):
        chunks = [len(x) for x in context] if all(isinstance(x, str) for x in context) else None
        total = sum(chunks) if chunks is not None else len(json.dumps(context))
        return "json", ContextMeta(f"list of {len(context)} items", total, chunks)
    if isinstance(context, dict):
        values = list(context.values())
        chunks = [len(v) for v in values] if all(isinstance(v, str) for v in values) else None
        total = sum(chunks) if chunks is not None else len(json.dumps(context))
        return "json", ContextMeta(f"dict with {len(context)} keys", total, chunks)
    raise TypeError(f"context must be str, list or dict, not {type(context).__name__}")


def _strip_quotes(value: str) -> str:
    for q in ('"""', "'''", '"', "'", "`"):
        if len(value) >= 2 * len(q) and value.startswith(q) and value.endswith(q):
            return value[len(q) : -len(q)]
    return value


def _new_stats() -> dict[str, Any]:
    return {
        "executions": 0,
        "syntax_errors": 0,
        "exec_errors": 0,
        "final_rejections": 0,
        "slips": {},
    }


def _parse_tool_args(call: ToolCall) -> tuple[dict[str, Any] | None, str | None]:
    """Return (arguments, error). An empty argument string counts as ``{}``."""
    raw = (call.arguments or "").strip() or "{}"
    try:
        args = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, (
            f"the arguments to {call.name} were not valid JSON ({exc.msg} at position "
            f"{exc.pos}). Send one JSON object."
        )
    if not isinstance(args, dict):
        return None, f"the arguments to {call.name} must be a JSON object."
    return args, None


def _final_from_args(
    args: dict[str, Any], has_code: bool
) -> tuple[FinalCandidate | None, str | None]:
    """``final_answer`` arguments -> a candidate, or an error. Exactly one of the two."""
    answer, variable = args.get("answer"), args.get("variable")
    if isinstance(answer, str) and not answer.strip():
        answer = None
    if isinstance(variable, str) and not variable.strip():
        variable = None
    if answer is not None and variable is not None:
        return None, "final_answer takes exactly one of `answer` or `variable`, not both."
    if answer is None and variable is None:
        return None, (
            "final_answer needs `answer` (the answer text) or `variable` (the name of a "
            "variable holding it)."
        )
    if variable is not None:
        if not isinstance(variable, str):
            return None, "`variable` must be a string: the name of a REPL variable."
        return FinalCandidate("FINAL_VAR", variable.strip(), has_code, False), None
    text = answer if isinstance(answer, str) else json.dumps(answer, ensure_ascii=False)
    text = text.strip()
    return FinalCandidate("FINAL", text, has_code, looks_like_plan(text)), None


def _default_repl_factory(cfg: RLMConfig, handler: LLMHandler) -> REPL:
    return make_repl(cfg, handler)  # honours cfg.sandbox


class RLM:
    def __init__(
        self,
        cfg: RLMConfig,
        client: LMLike,
        *,
        depth: int = 0,
        logger: TrajectoryLogger | None = None,
        repl_factory: REPLFactory | None = None,
        printer: VerbosePrinter | None = None,
        budget: RunBudget | None = None,
    ) -> None:
        self.cfg = cfg
        self.client = client
        self.depth = depth
        self.logger = logger or TrajectoryLogger(None)
        self.printer = printer or VerbosePrinter(enabled=False)
        self._repl_factory = repl_factory or _default_repl_factory
        self._budget = budget
        self._context_chars = 0
        self._turn_max_prompt = 0
        self._full_history: list[dict[str, Any]] = []
        self._stats = _new_stats()

    # --- public -----------------------------------------------------------

    def completion(self, context: Any, query: str) -> RLMResult:
        started = time.monotonic()
        cfg = self.cfg
        if self._budget is None:
            self._budget = RunBudget(
                max_subcalls=cfg.max_subcalls_per_run,
                deadline=(started + cfg.max_timeout) if cfg.max_timeout else None,
                max_tokens=cfg.max_tokens_total,
                started=started,
            )
        kind, meta = describe_context(context)
        self._context_chars = meta.total_chars
        self.logger.metadata(
            depth=self.depth,
            query=query,
            context=dataclasses.asdict(meta),
            config=dataclasses.asdict(cfg),
        )
        repl = self._repl_factory(cfg, self._handle_subcall)
        repl.start(context, kind)
        try:
            return self._run(repl, query, meta, started)
        finally:
            repl.close()

    # --- the loop ---------------------------------------------------------

    def _run(self, repl: REPL, query: str, meta: ContextMeta, started: float) -> RLMResult:
        if self.cfg.protocol == "tools":
            return self._run_tools(repl, query, meta, started)
        cfg = self.cfg
        n = cfg.max_iterations
        history: list[dict[str, str]] = [
            {"role": "system", "content": build_system_prompt(cfg, meta)},
            {"role": "user", "content": f"{query}\n\n{turn_prompt(1, n, first=True)}"},
        ]
        kinds = ["system", "query"]  # parallel to history; "repl" marks REPL-output turns
        self._full_history = list(history)

        prev_code_hash: str | None = None
        prev_vars: set[str] = set()
        rejected_plan: str | None = None
        consecutive_errors = 0
        answer_state: dict[str, Any] | None = None
        iterations = 0

        for i in range(1, n + 1):
            iterations = i
            try:
                self._check_limits(repl, answer_state)
            except RLMTimeout:
                # A child raises so the parent's code sees the error; the root instead
                # gets the same forced finish as running out of turns, because the REPL
                # may hold most of the answer (seen live: 11 of 12 nested results lost).
                if self.depth > 0:
                    raise
                self.logger.event("timeout", depth=self.depth, turn=i)
                return self._forced_finish(history, repl, answer_state, i - 1, started, why="time")
            if self.depth > 0:
                assert self._budget is not None
                self._budget.child_turns += 1
            self._maybe_compact(history, kinds, repl, i)
            self._turn_max_prompt = 0
            messages_in = len(history)

            completion, notes = self._root_call(history)
            content = completion.content
            if self.logger.sft_path:
                self.logger.sft(list(history), content, depth=self.depth, turn=i)
            self._append(history, kinds, {"role": "assistant", "content": content}, "assistant")
            self.printer.response(self.depth, i, n, content)

            blocks = find_code_blocks(content)
            results: list[ExecResult] = []
            for k, block in enumerate(blocks, 1):
                self.printer.code(k, block)
                res = self._exec(repl, block)
                results.append(res)
                self.printer.output(k, res.output)
                if res.answer is not None:
                    answer_state = res.answer

            # A ready answer wins even if another block in the same turn errored.
            for res in results:
                if res.answer_ready:
                    answer = (res.answer or {}).get("content") or ""
                    decision = {"kind": "answer_dict", "accepted": True}
                    self._log_iteration(
                        i, messages_in, completion, blocks, results, notes, decision
                    )
                    return self._finish(answer, "answer_dict", i, started)

            if blocks:
                consecutive_errors = consecutive_errors + 1 if any(r.error for r in results) else 0
                if consecutive_errors >= cfg.max_errors:
                    self._log_iteration(i, messages_in, completion, blocks, results, notes, None)
                    raise RLMErrorLimit(
                        f"{consecutive_errors} consecutive REPL errors "
                        f"(max_errors={cfg.max_errors})",
                        partial_answer=self._partial(repl, answer_state),
                    )

            cand = find_final(content)
            decision: dict[str, Any] | None = None
            if cand is not None:
                accepted, value, reason, stop = self._judge_final(
                    cand, repl, rejected_plan, answer_state
                )
                decision = {
                    "kind": cand.kind,
                    "value": cand.value,
                    "accepted": accepted,
                    "reason": reason,
                }
                if accepted:
                    self._log_iteration(
                        i, messages_in, completion, blocks, results, notes, decision
                    )
                    return self._finish(value or "", stop, i, started)
                notes.append(final_rejection(reason or "it was not usable."))
                self._stats["final_rejections"] += 1
                if cand.looks_like_plan:
                    rejected_plan = cand.value

            # Compose the next user message: outputs, then notes, then the turn line.
            parts: list[str] = []
            for k, res in enumerate(results, 1):
                header = f"[block {k} output]" if len(results) > 1 else "[output]"
                parts.append(f"{header}\n{res.output or '(no output)'}")

            if blocks:
                code_hash = hashlib.sha256(
                    "\n".join(b.strip() for b in blocks).encode("utf-8")
                ).hexdigest()
                if code_hash == prev_code_hash:
                    current = results[-1].vars if results else []
                    new_vars = [v for v in current if v not in prev_vars]
                    var = new_vars[-1] if new_vars else (current[-1] if current else None)
                    if var:
                        notes.append(reverify_nudge(var))
                prev_code_hash = code_hash
                prev_vars = set(results[-1].vars) if results else prev_vars
            if (
                self._context_chars > cfg.subcall_chars
                and self._turn_max_prompt >= 0.9 * self._context_chars
            ):
                notes.append(decompose_nudge())
            if not blocks and cand is None:
                notes.append(NO_ACTION_PROMPT)
                self._slip("no_action")
            for note in notes:
                self.printer.note(note)

            parts.extend(notes)
            if i < n:
                parts.append(turn_prompt(i + 1, n))
            self._append(history, kinds, {"role": "user", "content": "\n\n".join(parts)}, "repl")
            self._log_iteration(i, messages_in, completion, blocks, results, notes, decision)

        return self._forced_finish(history, repl, answer_state, iterations, started)

    def _run_tools(self, repl: REPL, query: str, meta: ContextMeta, started: float) -> RLMResult:
        """The loop for ``protocol="tools"``: execute_python / final_answer function calls."""
        cfg = self.cfg
        n = cfg.max_iterations
        tools = tool_specs(cfg.output_truncate_chars)
        first = turn_prompt(1, n, first=True, protocol="tools")
        history: list[dict[str, Any]] = [
            {"role": "system", "content": build_tools_system_prompt(cfg, meta)},
            {"role": "user", "content": f"{query}\n\n{first}"},
        ]
        kinds = ["system", "query"]
        self._full_history = list(history)

        prev_code_hash: str | None = None
        prev_vars: set[str] = set()
        rejected_plan: str | None = None
        consecutive_errors = 0
        answer_state: dict[str, Any] | None = None
        iterations = 0

        for i in range(1, n + 1):
            iterations = i
            try:
                self._check_limits(repl, answer_state)
            except RLMTimeout:
                if self.depth > 0:
                    raise
                self.logger.event("timeout", depth=self.depth, turn=i)
                return self._forced_finish(history, repl, answer_state, i - 1, started, why="time")
            if self.depth > 0:
                assert self._budget is not None
                self._budget.child_turns += 1
            self._maybe_compact(history, kinds, repl, i)
            self._turn_max_prompt = 0
            messages_in = len(history)

            completion, notes = self._root_call(history, tools)
            content = completion.content
            calls = completion.tool_calls or []
            assistant: dict[str, Any] = {"role": "assistant", "content": content}
            if calls:
                assistant["tool_calls"] = [c.as_message() for c in calls]
            if self.logger.sft_path:
                self.logger.sft(
                    list(history),
                    content,
                    depth=self.depth,
                    turn=i,
                    tool_calls=assistant.get("tool_calls"),
                )
            self._append(history, kinds, assistant, "assistant")
            self.printer.response(self.depth, i, n, content)

            slips: list[str] = []
            outputs: dict[int, str] = {}
            finals: dict[int, dict[str, Any]] = {}
            codes: list[str] = []
            results: list[ExecResult] = []
            for k, call in enumerate(calls):
                if call.name not in TOOL_NAMES:
                    outputs[k] = (
                        f"Error: there is no tool named `{call.name}`. The tools are "
                        "execute_python and final_answer."
                    )
                    slips.append("unknown_tool")
                    continue
                args, err = _parse_tool_args(call)
                if args is None:
                    outputs[k] = f"Error: {err}"
                    slips.append("malformed_args")
                    continue
                if call.name == "final_answer":
                    finals[k] = args  # judged after every execute_python in the turn ran
                    continue
                code = args.get("code")
                if not isinstance(code, str) or not code.strip():
                    outputs[k] = "Error: execute_python needs a non-empty string argument `code`."
                    slips.append("malformed_args")
                    continue
                self.printer.code(len(codes) + 1, code)
                res = self._exec(repl, code)
                self.printer.output(len(codes) + 1, res.output)
                codes.append(code)
                results.append(res)
                outputs[k] = res.output or "(no output)"
                if res.answer is not None:
                    answer_state = res.answer

            # Courtesy: a fenced block in a reply with no tool call still runs, once a turn.
            fenced = find_code_blocks(content) if not calls else []
            fenced_results: list[ExecResult] = []
            if fenced:
                slips.append("fenced_code")
                for block in fenced:
                    self.printer.code(len(codes) + 1, block)
                    res = self._exec(repl, block)
                    self.printer.output(len(codes) + 1, res.output)
                    codes.append(block)
                    results.append(res)
                    fenced_results.append(res)
                    if res.answer is not None:
                        answer_state = res.answer

            # Bound now; the lists are filled in place before each call.
            log = functools.partial(
                self._log_tool_turn, i, messages_in, completion, codes, results, notes,
                calls, outputs, slips,
            )  # fmt: skip

            for kind in slips:
                self._slip(kind)

            for res in results:
                if res.answer_ready:
                    log({"kind": "answer_dict", "accepted": True})
                    return self._finish(
                        (res.answer or {}).get("content") or "", "answer_dict", i, started
                    )

            if codes:
                consecutive_errors = consecutive_errors + 1 if any(r.error for r in results) else 0
                if consecutive_errors >= cfg.max_errors:
                    log(None)
                    raise RLMErrorLimit(
                        f"{consecutive_errors} consecutive REPL errors "
                        f"(max_errors={cfg.max_errors})",
                        partial_answer=self._partial(repl, answer_state),
                    )

            decision: dict[str, Any] | None = None
            for k, args in finals.items():
                cand, err = _final_from_args(args, has_code=bool(codes))
                if cand is None:
                    outputs[k] = f"Error: {err}"
                    slips.append("malformed_args")
                    self._slip("malformed_args")
                    continue
                accepted, value, reason, stop = self._judge_final(
                    cand, repl, rejected_plan, answer_state
                )
                decision = {
                    "kind": cand.kind,
                    "value": cand.value,
                    "accepted": accepted,
                    "reason": reason,
                    "via": "tool",
                }
                if accepted:
                    log(decision)
                    return self._finish(value or "", stop, i, started)
                outputs[k] = final_rejection(reason or "it was not usable.", "tools")
                self._stats["final_rejections"] += 1
                if cand.looks_like_plan:
                    rejected_plan = cand.value

            if not calls:
                cand = find_final(content)
                if cand is not None:  # FINAL(...) written as text: judged as a courtesy
                    slips.append("final_in_text")
                    self._slip("final_in_text")
                    accepted, value, reason, stop = self._judge_final(
                        cand, repl, rejected_plan, answer_state
                    )
                    decision = {
                        "kind": cand.kind,
                        "value": cand.value,
                        "accepted": accepted,
                        "reason": reason,
                        "via": "text",
                    }
                    if accepted:
                        log(decision)
                        return self._finish(value or "", stop, i, started)
                    notes.append(final_rejection(reason or "it was not usable.", "tools"))
                    self._stats["final_rejections"] += 1
                    if cand.looks_like_plan:
                        rejected_plan = cand.value
                elif not fenced:
                    slips.append("text_no_tool")
                    self._slip("text_no_tool")
                    notes.append(no_action_prompt("tools"))

            # One tool message per call, in call order, each answering its tool_call_id.
            for k, call in enumerate(calls):
                msg = {"role": "tool", "tool_call_id": call.id, "content": outputs[k]}
                self._append(history, kinds, msg, "repl")

            if codes:
                code_hash = hashlib.sha256(
                    "\n".join(c.strip() for c in codes).encode("utf-8")
                ).hexdigest()
                if code_hash == prev_code_hash:
                    current = results[-1].vars if results else []
                    new_vars = [v for v in current if v not in prev_vars]
                    var = new_vars[-1] if new_vars else (current[-1] if current else None)
                    if var:
                        notes.append(reverify_nudge(var, "tools"))
                prev_code_hash = code_hash
                prev_vars = set(results[-1].vars) if results else prev_vars
            if (
                self._context_chars > cfg.subcall_chars
                and self._turn_max_prompt >= 0.9 * self._context_chars
            ):
                notes.append(decompose_nudge())
            for note in notes:
                self.printer.note(note)

            parts: list[str] = []
            for k, res in enumerate(fenced_results, 1):
                header = f"[block {k} output]" if len(fenced_results) > 1 else "[output]"
                parts.append(f"{header}\n{res.output or '(no output)'}")
            if fenced_results:
                parts.append(fence_slip_note())
            parts.extend(notes)
            if i < n:
                parts.append(turn_prompt(i + 1, n, protocol="tools"))
            if parts:
                kind = "repl" if fenced_results else "note"
                self._append(history, kinds, {"role": "user", "content": "\n\n".join(parts)}, kind)
            log(decision)

        return self._forced_finish(history, repl, answer_state, iterations, started)

    # --- pieces -----------------------------------------------------------

    def _exec(self, repl: REPL, code: str) -> ExecResult:
        res = repl.execute(code)
        self._stats["executions"] += 1
        if res.error:
            key = "syntax_errors" if res.error.startswith("SyntaxError") else "exec_errors"
            self._stats[key] += 1
        return res

    def _slip(self, kind: str) -> None:
        slips = self._stats["slips"]
        slips[kind] = slips.get(kind, 0) + 1

    def _append(
        self, history: list[dict[str, Any]], kinds: list[str], msg: dict[str, Any], kind: str
    ) -> None:
        history.append(msg)
        kinds.append(kind)
        self._full_history.append(msg)

    def _root_call(
        self, history: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> tuple[Completion, list[str]]:
        notes: list[str] = []
        # ``tools`` only travels when set, so fence-protocol clients need not accept it.
        extra: dict[str, Any] = {"tools": tools} if tools else {}
        completion = self.client.complete(history, "root", **extra)
        self._budget_add(completion)
        if (
            completion.finish_reason == "length"
            and not completion.content.strip()
            and not completion.tool_calls
        ):
            notes.append(
                "[note] the previous attempt spent its whole output budget thinking; "
                "it was retried without thinking."
            )
            completion = self.client.complete(history, "root", enable_thinking=False, **extra)
            self._budget_add(completion)
            completion.attempts += 1
        return completion, notes

    def _budget_add(self, completion: Completion) -> None:
        assert self._budget is not None
        self._budget.add(completion)

    def _judge_final(
        self,
        cand: FinalCandidate,
        repl: REPL,
        rejected_plan: str | None,
        answer_state: dict[str, Any] | None = None,
    ) -> tuple[bool, str | None, str | None, str]:
        """Return (accepted, value, rejection reason, stop_reason)."""
        if cand.has_code:
            return False, None, "it was sent in the same message as code that had not run yet.", ""
        if _ANSWER_CONTENT.match(cand.value.strip()):
            content = (answer_state or {}).get("content")
            if content:
                return True, str(content), None, "answer_dict"
            return False, None, "`answer['content']` has not been set.", ""
        if cand.kind == "FINAL_VAR":
            name = _strip_quotes(cand.value.strip())
            var = repl.get_var(name)
            if not var.found:
                return False, None, f"there is no variable named `{name}`.", ""
            return True, var.value_str or "", None, "final_var"
        value = cand.value
        if cand.looks_like_plan and value != rejected_plan:
            return (
                False,
                None,
                "it reads like a plan, not an answer. Run the plan, then send the result.",
                "",
            )
        if _IDENT.match(value):
            var = repl.get_var(value)
            if var.found:
                return True, var.value_str or "", None, "final_var"
        return True, _strip_quotes(value), None, "final"

    def _handle_subcall(
        self, kind: str, prompts: list[str], contexts: list[Any] | None = None, /
    ) -> list[str]:
        """REPL handler: budget, logging, and the rlm_query -> child RLM dispatch."""
        assert self._budget is not None
        budget = self._budget
        cfg = self.cfg
        answers: list[str] = []
        for i, prompt in enumerate(prompts):
            if budget.subcalls >= budget.max_subcalls:
                raise RuntimeError(
                    f"sub-call budget for this run exhausted ({budget.max_subcalls}); "
                    "finish with what you have"
                )
            data = contexts[i] if contexts is not None else None
            if data is None:
                child_context, child_query = prompt, RLM_QUERY_PROMPT
                prompt_chars = len(prompt)
            else:
                child_context, child_query = data, prompt
                prompt_chars = len(prompt) + describe_context(data)[1].total_chars
            budget.subcalls += 1
            budget.subcall_chars += prompt_chars
            self._turn_max_prompt = max(self._turn_max_prompt, prompt_chars)
            t0 = time.monotonic()
            recurse = kind == "rlm_query" and self.depth + 1 < cfg.max_depth
            if recurse:
                child = RLM(
                    cfg,
                    self.client,
                    depth=self.depth + 1,
                    logger=self.logger,
                    repl_factory=self._repl_factory,
                    printer=self.printer,
                    budget=budget,
                )
                answer = child.completion(child_context, child_query).answer
            else:
                if data is not None:  # flatten (question, data) into one prompt
                    text = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
                    prompt = f"{prompt}\n\n{text}"
                completion = self.client.complete([{"role": "user", "content": prompt}], "sub")
                budget.add(completion)
                answer = completion.content
            latency = time.monotonic() - t0
            self.logger.subcall(
                depth=self.depth,
                kind=kind,
                ran_as="rlm_query" if recurse else "llm_query",
                prompt_chars=prompt_chars,
                answer_chars=len(answer),
                latency=round(latency, 3),
                run_subcalls=budget.subcalls,
            )
            self.printer.subcall(kind, prompt_chars, len(answer), latency)
            answers.append(answer)
        return answers

    def _check_limits(self, repl: REPL, answer_state: dict[str, Any] | None) -> None:
        assert self._budget is not None
        b = self._budget
        if b.deadline is not None and time.monotonic() > b.deadline:
            raise RLMTimeout(
                f"run exceeded max_timeout={self.cfg.max_timeout:g}s",
                partial_answer=self._partial(repl, answer_state),
            )
        if b.max_tokens is not None and b.usage.total_tokens > b.max_tokens:
            raise RLMTokenLimit(
                f"run used {b.usage.total_tokens} tokens (max_tokens_total={b.max_tokens})",
                partial_answer=self._partial(repl, answer_state),
            )

    def _partial(self, repl: REPL, answer_state: dict[str, Any] | None) -> str | None:
        if answer_state and answer_state.get("content"):
            return str(answer_state["content"])
        for name in ANSWER_VAR_NAMES:
            var = repl.get_var(name)
            if var.found:
                return var.value_str
        return None

    def _forced_finish(
        self,
        history: list[dict[str, Any]],
        repl: REPL,
        answer_state: dict[str, Any] | None,
        iterations: int,
        started: float,
        why: str = "turns",
    ) -> RLMResult:
        """Out of turns (or time): use what exists in the REPL before asking the model again."""
        stop = "max_iterations" if why == "turns" else "timeout"
        existing = self._partial(repl, answer_state)
        if existing is not None:
            self.logger.event("forced_finish", method="existing_value", depth=self.depth)
            return self._finish(existing, stop, iterations, started)

        tools_mode = self.cfg.protocol == "tools"
        prompt = forced_final_prompt(why, self.cfg.protocol)
        if history and history[-1]["role"] == "user":
            history[-1]["content"] = f"{history[-1]['content']}\n\n{prompt}"
        else:
            self._append(history, kinds=[], msg={"role": "user", "content": prompt}, kind="repl")
        tools = tool_specs(self.cfg.output_truncate_chars) if tools_mode else None
        completion, _notes = self._root_call(history, tools)
        content = completion.content
        answer = content.strip()
        cand = find_final(content)
        for call in completion.tool_calls or []:
            if call.name != "final_answer":
                continue
            args, _err = _parse_tool_args(call)
            tool_cand = _final_from_args(args, has_code=False)[0] if args is not None else None
            if tool_cand is not None:
                cand = tool_cand
                break
        if cand is not None:
            if cand.kind == "FINAL_VAR" or _IDENT.match(cand.value):
                var = repl.get_var(_strip_quotes(cand.value.strip()))
                answer = var.value_str or "" if var.found else _strip_quotes(cand.value)
            else:
                answer = _strip_quotes(cand.value)
        self.logger.event(
            "forced_finish",
            method="model",
            depth=self.depth,
            content=content,
            reasoning=completion.reasoning,
            tool_calls=[dataclasses.asdict(c) for c in completion.tool_calls or []],
        )
        return self._finish(answer, stop, iterations, started)

    def _finish(self, answer: str, reason: str, iterations: int, started: float) -> RLMResult:
        assert self._budget is not None
        elapsed = time.monotonic() - started
        self.logger.final(
            depth=self.depth,
            answer=answer,
            stop_reason=reason,
            iterations=iterations,
            subcalls=self._budget.subcalls,
            child_turns=self._budget.child_turns,
            usage=dataclasses.asdict(self._budget.usage),
            elapsed=round(elapsed, 3),
            protocol=self.cfg.protocol,
            stats=self._stats,
            protocol_slips=sum(self._stats["slips"].values()),
        )
        self.printer.final(answer, reason)
        return RLMResult(
            answer=answer,
            iterations=iterations,
            subcalls=self._budget.subcalls,
            usage=Usage(**dataclasses.asdict(self._budget.usage)),
            elapsed=elapsed,
            stop_reason=reason,
            trajectory_path=str(self.logger.path) if self.logger.path else None,
            depth=self.depth,
            child_turns=self._budget.child_turns,
            protocol=self.cfg.protocol,
            stats=json.loads(json.dumps(self._stats)),
        )

    def _log_iteration(
        self,
        i: int,
        messages_in: int,
        completion: Completion,
        blocks: list[str],
        results: list[ExecResult],
        notes: list[str],
        decision: dict[str, Any] | None,
        **extra: Any,
    ) -> None:
        self.logger.iteration(
            depth=self.depth,
            i=i,
            messages_in=messages_in,
            content=completion.content,
            reasoning=completion.reasoning,
            finish_reason=completion.finish_reason,
            attempts=completion.attempts,
            code_blocks=blocks,
            results=[dataclasses.asdict(r) for r in results],
            notes=notes,
            final=decision,
            usage=dataclasses.asdict(completion.usage) if completion.usage else None,
            latency=round(completion.latency, 3),
            **extra,
        )

    def _log_tool_turn(
        self,
        i: int,
        messages_in: int,
        completion: Completion,
        codes: list[str],
        results: list[ExecResult],
        notes: list[str],
        calls: list[ToolCall],
        outputs: dict[int, str],
        slips: list[str],
        decision: dict[str, Any] | None,
    ) -> None:
        self._log_iteration(
            i, messages_in, completion, codes, results, notes, decision,
            tool_calls=[dataclasses.asdict(c) for c in calls],
            tool_outputs=[outputs.get(k, "") for k in range(len(calls))],
            slips=slips,
        )  # fmt: skip

    # --- compaction (epic #8 decision 8)----------------------------------

    def _maybe_compact(
        self, history: list[dict[str, Any]], kinds: list[str], repl: REPL, turn: int
    ) -> None:
        cfg = self.cfg
        limit = 0.85 * cfg.context_tokens

        def size(m: dict[str, Any]) -> int:
            calls = m.get("tool_calls")
            return len(m["content"] or "") + (len(json.dumps(calls)) if calls else 0)

        def estimate() -> float:
            return sum(size(m) for m in history) / CHARS_PER_TOKEN

        before = estimate()
        if before <= limit:
            return

        repl_positions = [idx for idx, k in enumerate(kinds) if k in ("repl", "repl_stub")]
        old = repl_positions[:-KEEP_RECENT_TURNS] if len(repl_positions) > KEEP_RECENT_TURNS else []
        elided: list[tuple[int, str]] = []
        for idx in old:
            if kinds[idx] != "repl":
                continue
            turn_no = repl_positions.index(idx) + 1
            original = history[idx]["content"]
            elided.append((turn_no, original))
            # A tool message keeps its role and tool_call_id so the history stays valid.
            history[idx] = {
                **history[idx],
                "content": f"[REPL output from turn {turn_no} elided; {len(original)} chars]",
            }
            kinds[idx] = "repl_stub"
        if not elided:
            return  # nothing old enough to drop; the model keeps its recent turns

        summarized = False
        if estimate() > limit:
            body = "\n\n".join(f"--- turn {t} ---\n{text}" for t, text in elided)
            prompt = (
                "Below are outputs from earlier steps of a data-analysis session. Summarize "
                f"what was learned in under {SUMMARY_CHARS} characters: facts found, variable "
                "names created and what they hold, and anything still unresolved.\n\n"
                f"{body[: cfg.subcall_chars]}"
            )
            completion = self.client.complete([{"role": "user", "content": prompt}], "sub")
            self._budget_add(completion)
            first, last = elided[0][0], elided[-1][0]
            history[old[0]] = {
                **history[old[0]],
                "content": (
                    f"[Summary of elided REPL output from turns {first}-{last}]\n"
                    f"{completion.content.strip()[:SUMMARY_CHARS]}"
                ),
            }
            summarized = True

        self._push_history(repl)
        after = estimate()
        self.logger.compaction(
            depth=self.depth,
            turn=turn,
            before_tokens=round(before),
            after_tokens=round(after),
            elided_turns=[t for t, _ in elided],
            summarized=summarized,
        )
        self.printer.note(
            f"compacted history: {round(before)} -> {round(after)} est. tokens; "
            f"full history is in the REPL as `history`"
        )

    def _push_history(self, repl: REPL) -> None:
        literal = json.dumps(json.dumps(self._full_history, ensure_ascii=True))
        repl.execute(f"import json as _json\nhistory = _json.loads({literal})")


__all__ = ["RLM", "RLMResult", "RunBudget", "describe_context"]
