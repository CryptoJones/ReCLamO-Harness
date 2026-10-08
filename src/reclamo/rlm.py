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
a fresh guess from the model (paper failure E.2); ``max_errors`` consecutive
erroring turns end the same way (issue #50, stop reason ``error_limit``). The
forced finish shows the model what the REPL holds (``answer['content']``, the
usual answer variables, the last output) and asks for one ``FINAL`` /
``FINAL_VAR``. A valid reply wins;
otherwise the loop falls back to the answer dict, then an answer variable, then
the reply's prose with code removed, then "". A code block is never the answer.

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

``planner_style="upstream-rlm-v0"`` (issue #43) keeps the fence loop but swaps
our prompt and turn layout for the alexzhang13/rlm v1.0.0 scaffold that
RLM-Qwen3-8B was trained on (``upstream.py``): context metadata as an assistant
message, one "Code executed / REPL output" user message per block, and the query
in a per-turn user prompt that is sent but not stored. Our nudges follow the
outputs as a separate user message.
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

import openai

from reclamo.client import Completion, ToolCall, Usage
from reclamo.config import RLMConfig
from reclamo.errors import RLMTimeout, RLMTokenLimit
from reclamo.logger import TrajectoryLogger, VerbosePrinter
from reclamo.parsing import (
    FinalCandidate,
    find_code_blocks,
    find_final,
    looks_like_plan,
    strip_code,
)
from reclamo.prompts import (
    ContextMeta,
    build_system_prompt,
    build_tools_system_prompt,
    decompose_nudge,
    fence_slip_note,
    final_rejection,
    forced_final_prompt,
    forced_final_state,
    no_action_prompt,
    reverify_nudge,
    tool_specs,
    turn_prompt,
)
from reclamo.repl import make_repl
from reclamo.repl.base import REPL, ExecResult, LLMHandler
from reclamo.upstream import code_output_message as upstream_code_output
from reclamo.upstream import initial_messages as upstream_initial_messages
from reclamo.upstream import user_prompt as upstream_user_prompt


class LMLike(Protocol):
    def complete(
        self,
        messages: Any,
        role: str = "root",
        *,
        enable_thinking: bool | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
        retry: bool = True,
        deadline: float | None = None,
    ) -> Completion: ...


REPLFactory = Callable[[RLMConfig, LLMHandler], REPL]

# Variables the forced finish shows the model, and falls back to in this order when
# the model's forced reply is not a usable final.
ANSWER_VAR_NAMES = ("final_answer", "answer_text", "result", "final")
# Forced-finish ``why`` -> the run's stop_reason.
FORCED_STOP_REASONS = {
    "turns": "max_iterations",
    "time": "timeout",
    "errors": "error_limit",
    "context": "context_overflow",
}
# Issue #51: every forced finish is one attempt (no HTTP retry) whose request timeout is
# min(root timeout, time left before max_timeout + FORCED_FINISH_TIMEOUT). Past the
# deadline that is min(root timeout, 60 s), thinking off. Root and sub requests in the
# loop are capped by the time left, and later blocks of a turn are skipped once it has
# passed, so a run ends within max_timeout + FORCED_FINISH_TIMEOUT + ~1 s (the client's
# minimum request timeout). Not bounded: one REPL block already computing at the
# deadline (up to exec_timeout); its sub-calls are refused, but it is not killed,
# because killing the worker would lose every variable the forced finish needs.
FORCED_FINISH_TIMEOUT = 60.0
# Prompt v0.2 (issue #61): sent once, thinking off, when a reply is cut off part-way.
CONTINUE_PROMPT = (
    "Your last message was cut off by the output limit. Continue it from exactly where "
    "it stopped, without repeating anything."
)
CHARS_PER_TOKEN = 3.5
# Issue #49: the request must fit the window with room for the root reply. The input
# budget is context_tokens - root max_tokens - FIT_MARGIN * context_tokens (the margin
# absorbs estimate error), never below MIN_BUDGET_FRACTION * context_tokens.
FIT_MARGIN = 0.10
MIN_BUDGET_FRACTION = 0.25
MESSAGE_OVERHEAD_TOKENS = 4  # chat-template tokens around each message
# A REPL output shrunk to fit keeps at least this many chars (head + tail), else none.
MIN_KEPT_CHARS = 200
KEEP_RECENT_TURNS = 4
SUMMARY_CHARS = 1_500
NO_ACTION_PROMPT = no_action_prompt("fence")
TIME_UP = "the run's time (max_timeout) ran out"
FIT_STUB = (
    "[... {cut} of {total} chars of this REPL output elided to fit the context window; "
    "the full text is in the REPL variable `history` ...]"
)
ERROR_LIMIT = "the run stopped at the error limit"
TOOL_NAMES = ("execute_python", "final_answer")
OPENING_KINDS = ("system", "query", "meta")  # history kinds a cut-down forced finish keeps
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
    stop_reason: str  # final | final_var | answer_dict | max_iterations | timeout | error_limit
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


def estimate_tokens(text: str) -> int:
    """Prompt-token estimate: one token per digit (Qwen splits numbers into digits),
    ``CHARS_PER_TOKEN`` chars per token for everything else (as ``examples/bench.py``)."""
    digits = sum(c.isdigit() for c in text)
    return digits + int((len(text) - digits) / CHARS_PER_TOKEN + 0.999)


def message_tokens(message: dict[str, Any]) -> int:
    calls = message.get("tool_calls")
    text = (message.get("content") or "") + (json.dumps(calls) if calls else "")
    return estimate_tokens(text) + MESSAGE_OVERHEAD_TOKENS


def request_tokens(messages: list[dict[str, Any]], extra: int = 0) -> int:
    """Estimated prompt tokens of a request: its messages plus ``extra`` (tools, etc.)."""
    return sum(message_tokens(m) for m in messages) + extra


@dataclass
class _Piece:
    """Part of a stored user/tool message. Shrinkable pieces are REPL output (#49)."""

    text: str
    shrinkable: bool = False
    orig: str = ""
    kept: int = -1  # chars of ``orig`` kept; -1 = all

    def __post_init__(self) -> None:
        if self.shrinkable and not self.orig:
            self.orig = self.text


def _join_parts(parts: list[str | tuple[str, str]]) -> list[_Piece]:
    """Pieces for parts joined by blank lines; ``(header, output)`` is a block's output."""
    pieces: list[_Piece] = []
    for n, part in enumerate(parts):
        if n:
            pieces.append(_Piece("\n\n"))
        if isinstance(part, tuple):
            header, output = part
            pieces.append(_Piece(f"{header}\n"))
            pieces.append(_Piece(output, shrinkable=True))
        else:
            pieces.append(_Piece(part))
    return pieces


def _upstream_pieces(code: str, res: ExecResult, limit: int) -> list[_Piece]:
    msg = upstream_code_output(code, res, limit)
    prefix = f"Code executed:\n```python\n{code.strip()}\n```\n\nREPL output:\n"
    if not msg.startswith(prefix):  # defensive: never shrink what we cannot split
        return [_Piece(msg)]
    return [_Piece(prefix), _Piece(msg[len(prefix) :], shrinkable=True)]


def _clip_middle(text: str, keep: int) -> str:
    """Keep ``keep`` chars of ``text`` (head and tail) around a stub saying what went."""
    stub = FIT_STUB.format(cut=len(text) - keep, total=len(text))
    head = keep // 2
    return f"{text[:head]}{stub}{text[len(text) - (keep - head) :] if keep - head else ''}"


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
        self._kinds: list[str] = []
        self._repl: REPL | None = None
        self._pieces: dict[int, list[_Piece]] = {}  # history index -> shrinkable layout
        self._stats = _new_stats()
        self._last_output: str | None = None
        self._context: Any = None
        self._query = ""

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
        self._context = context
        self._query = query
        self._context_chars = meta.total_chars
        self.logger.metadata(
            depth=self.depth,
            query=query,
            context=dataclasses.asdict(meta),
            config=dataclasses.asdict(cfg),
            endpoints=[
                {"base_url": ep.base_url, "roles": list(ep.roles), "concurrency": ep.concurrency}
                for ep in cfg.endpoints()
            ],
        )
        repl = self._repl_factory(cfg, self._handle_subcall)
        self._repl = repl
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
        # upstream-rlm-v0 (#43): the alexzhang13/rlm v1.0.0 message layout. The query
        # rides in a per-turn user prompt that is sent but never stored, each executed
        # block gets its own "Code executed: ... REPL output: ..." user message, and
        # there is no "Turn i/N" line. Every guard below still applies.
        upstream = cfg.planner_style == "upstream-rlm-v0"
        history: list[dict[str, Any]]
        if upstream:
            history = upstream_initial_messages(self._context)
            kinds = ["system", "meta"]
        else:
            history = [
                {"role": "system", "content": build_system_prompt(cfg, meta)},
                {"role": "user", "content": f"{query}\n\n{turn_prompt(1, n, first=True)}"},
            ]
            kinds = ["system", "query"]  # parallel to history; "repl" marks REPL-output turns
        self._full_history = list(history)
        self._kinds = kinds

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
            extra = estimate_tokens(upstream_user_prompt(query, i - 1)) if upstream else 0
            if not self._maybe_compact(history, kinds, repl, i, extra):
                return self._context_overflow(history, repl, answer_state, i - 1, started, extra)
            self._turn_max_prompt = 0
            messages_in = len(history)

            sent = history
            if upstream:
                sent = [*history, {"role": "user", "content": upstream_user_prompt(query, i - 1)}]
            try:
                completion, notes = self._root_call(sent)
            except RLMTimeout:
                # Issue #51: the root request ran into the deadline (it is capped by it).
                if self.depth > 0:
                    raise
                self.logger.event("timeout", depth=self.depth, turn=i, during="root_call")
                return self._forced_finish(history, repl, answer_state, i - 1, started, why="time")
            content = completion.content
            if self.logger.sft_path:
                self.logger.sft(list(sent), content, depth=self.depth, turn=i)
            self._append(history, kinds, {"role": "assistant", "content": content}, "assistant")
            self.printer.response(self.depth, i, n, content)

            blocks = find_code_blocks(content)
            results: list[ExecResult] = []
            for k, block in enumerate(blocks, 1):
                if self._past_deadline():
                    break  # issue #51: later blocks are skipped once time is up
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
                # Issue #50: the error limit ends the loop through the forced finish, not
                # an exception, so the REPL's work is not lost. The outputs go into the
                # history first so the forced call sees the errors.
                self._flush_outputs(history, kinds, blocks, results, ERROR_LIMIT)
                self._log_iteration(i, messages_in, completion, blocks, results, notes, None)
                self._log_error_limit(i, consecutive_errors)
                return self._forced_finish(history, repl, answer_state, i, started, why="errors")

            cand = find_final(content)
            if upstream and cand is not None and cand.kind == "FINAL_VAR" and cand.has_code:
                # Upstream runs the turn's code first and then reads FINAL_VAR, so the
                # checkpoint may name a variable its own block just set. The block has
                # run by now; a FINAL(text) next to code is still rejected.
                cand = dataclasses.replace(cand, has_code=False)
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

            if self._past_deadline():
                # Issue #51: the turn ran past max_timeout. Store what ran, then the
                # time-bounded forced finish (a child raises, as at a turn start).
                if self.depth > 0:
                    raise self._timeout_error(repl, answer_state)
                self._flush_outputs(history, kinds, blocks, results, TIME_UP)
                self._log_iteration(i, messages_in, completion, blocks, results, notes, decision)
                self.logger.event(
                    "timeout",
                    depth=self.depth,
                    turn=i,
                    during="turn",
                    skipped_blocks=len(blocks) - len(results),
                )
                return self._forced_finish(history, repl, answer_state, i, started, why="time")

            # Compose the next user message: outputs, then notes, then the turn line.
            parts: list[str | tuple[str, str]] = []
            if upstream:
                for block, res in zip(blocks, results, strict=True):
                    pieces = _upstream_pieces(block, res, cfg.output_truncate_chars)
                    self._append_pieces(history, kinds, {"role": "user"}, pieces, "repl")
            else:
                for k, res in enumerate(results, 1):
                    header = f"[block {k} output]" if len(results) > 1 else "[output]"
                    parts.append((header, res.output or "(no output)"))

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
            if self._wants_decompose_nudge():
                notes.append(self._decompose_nudge())
            if not blocks and cand is None:
                notes.append(NO_ACTION_PROMPT)
                self._slip("no_action")
            for note in notes:
                self.printer.note(note)

            parts.extend(notes)
            if upstream:
                if parts:  # our nudges, as their own user message after the outputs
                    msg = {"role": "user", "content": "\n\n".join(notes)}
                    self._append(history, kinds, msg, "note")
            else:
                if i < n:
                    parts.append(turn_prompt(i + 1, n))
                pieces = _join_parts(parts)
                self._append_pieces(history, kinds, {"role": "user"}, pieces, "repl")
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
        self._kinds = kinds
        tools_tokens = estimate_tokens(json.dumps(tools))

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
            if not self._maybe_compact(history, kinds, repl, i, tools_tokens):
                return self._context_overflow(
                    history, repl, answer_state, i - 1, started, tools_tokens
                )
            self._turn_max_prompt = 0
            messages_in = len(history)

            try:
                completion, notes = self._root_call(history, tools)
            except RLMTimeout:
                if self.depth > 0:
                    raise
                self.logger.event("timeout", depth=self.depth, turn=i, during="root_call")
                return self._forced_finish(history, repl, answer_state, i - 1, started, why="time")
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
            skipped = 0  # execute_python calls not run because time ran out (#51)
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
                if self._past_deadline():
                    skipped += 1  # no outputs[k]: flushed as "Not run" below
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
                    if self._past_deadline():
                        break
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
                # Issue #50: forced finish instead of RLMErrorLimit. Every tool call gets
                # its answer first so the history stays valid for the chat template.
                self._flush_tool_outputs(
                    history, kinds, calls, outputs, fenced, fenced_results, ERROR_LIMIT
                )
                log(None)
                self._log_error_limit(i, consecutive_errors)
                return self._forced_finish(history, repl, answer_state, i, started, why="errors")

            decision: dict[str, Any] | None = None
            for k, args in finals.items():
                cand, err = _final_from_args(args, has_code=bool(codes) or skipped > 0)
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

            if self._past_deadline():
                # Issue #51: as in the fence loop. Every call still gets its tool reply.
                if self.depth > 0:
                    raise self._timeout_error(repl, answer_state)
                self._flush_tool_outputs(
                    history, kinds, calls, outputs, fenced, fenced_results, TIME_UP
                )
                log(decision)
                self.logger.event(
                    "timeout",
                    depth=self.depth,
                    turn=i,
                    during="turn",
                    skipped_blocks=skipped + len(fenced) - len(fenced_results),
                )
                return self._forced_finish(history, repl, answer_state, i, started, why="time")

            # One tool message per call, in call order, each answering its tool_call_id.
            for k, call in enumerate(calls):
                msg = {"role": "tool", "tool_call_id": call.id}
                pieces = [_Piece(outputs[k], shrinkable=True)]
                self._append_pieces(history, kinds, msg, pieces, "repl")

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
            if self._wants_decompose_nudge():
                notes.append(self._decompose_nudge())
            for note in notes:
                self.printer.note(note)

            parts: list[str | tuple[str, str]] = []
            for k, res in enumerate(fenced_results, 1):
                header = f"[block {k} output]" if len(fenced_results) > 1 else "[output]"
                parts.append((header, res.output or "(no output)"))
            if fenced_results:
                parts.append(fence_slip_note())
            parts.extend(notes)
            if i < n:
                parts.append(turn_prompt(i + 1, n, protocol="tools"))
            if parts:
                kind = "repl" if fenced_results else "note"
                self._append_pieces(history, kinds, {"role": "user"}, _join_parts(parts), kind)
            log(decision)

        return self._forced_finish(history, repl, answer_state, iterations, started)

    # --- pieces -----------------------------------------------------------

    def _flush_outputs(
        self,
        history: list[dict[str, Any]],
        kinds: list[str],
        blocks: list[str],
        results: list[ExecResult],
        why: str,
    ) -> None:
        """Append a stopping turn's block outputs before its forced finish.

        ``results`` may be shorter than ``blocks`` when time ran out (issue #51); the
        blocks that never ran get one line saying so.
        """
        not_run = len(blocks) - len(results)
        note = f"[{not_run} later block(s) not run: {why}]" if not_run > 0 else ""
        if self.cfg.planner_style == "upstream-rlm-v0" and self.cfg.protocol == "fence":
            for block, res in zip(blocks, results, strict=False):
                pieces = _upstream_pieces(block, res, self.cfg.output_truncate_chars)
                self._append_pieces(history, kinds, {"role": "user"}, pieces, "repl")
            if note:
                self._append(history, kinds, {"role": "user", "content": note}, "note")
            return
        parts: list[str | tuple[str, str]] = [
            (f"[block {k} output]" if len(blocks) > 1 else "[output]", res.output or "(no output)")
            for k, res in enumerate(results, 1)
        ]
        if note:
            parts.append(note)
        if parts:
            self._append_pieces(history, kinds, {"role": "user"}, _join_parts(parts), "repl")

    def _flush_tool_outputs(
        self,
        history: list[dict[str, Any]],
        kinds: list[str],
        calls: list[ToolCall],
        outputs: dict[int, str],
        fenced: list[str],
        fenced_results: list[ExecResult],
        why: str,
    ) -> None:
        """Tools protocol: one tool reply per call (a call that never ran says so)."""
        for k, call in enumerate(calls):
            pieces = [_Piece(outputs.get(k, f"Not run: {why}."), shrinkable=True)]
            msg = {"role": "tool", "tool_call_id": call.id}
            self._append_pieces(history, kinds, msg, pieces, "repl")
        if fenced:
            self._flush_outputs(history, kinds, fenced, fenced_results, why)

    def _past_deadline(self) -> bool:
        b = self._budget
        return b is not None and b.deadline is not None and time.monotonic() > b.deadline

    def _deadline_kw(self) -> dict[str, Any]:
        """``deadline=`` for a loop request (issue #51), only when the run has one."""
        b = self._budget
        return {"deadline": b.deadline} if b is not None and b.deadline is not None else {}

    def _timeout_error(
        self, repl: REPL | None = None, answer_state: dict[str, Any] | None = None
    ) -> RLMTimeout:
        partial = self._partial(repl, answer_state) if repl is not None else None
        return RLMTimeout(
            f"run exceeded max_timeout={self.cfg.max_timeout:g}s", partial_answer=partial
        )

    def _log_error_limit(self, turn: int, consecutive: int) -> None:
        self.logger.event(
            "error_limit",
            depth=self.depth,
            turn=turn,
            consecutive_errors=consecutive,
            max_errors=self.cfg.max_errors,
        )
        self.printer.note(
            f"{consecutive} consecutive REPL errors (max_errors={self.cfg.max_errors}); "
            "forcing a final answer"
        )

    def _exec(self, repl: REPL, code: str) -> ExecResult:
        res = repl.execute(code)
        self._last_output = res.output
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

    def _append_pieces(
        self,
        history: list[dict[str, Any]],
        kinds: list[str],
        msg: dict[str, Any],
        pieces: list[_Piece],
        kind: str,
    ) -> None:
        """Append ``msg`` with its content built from ``pieces``, which compaction may
        later shrink (issue #49)."""
        self._pieces[len(history)] = pieces
        self._append(history, kinds, {**msg, "content": "".join(p.text for p in pieces)}, kind)

    def _root_call(
        self, history: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> tuple[Completion, list[str]]:
        notes: list[str] = []
        # ``tools`` only travels when set, so fence-protocol clients need not accept it.
        # Issue #51: the request is capped by the run's deadline; running into it (or
        # starting past it) raises RLMTimeout so the loop can take the forced finish.
        extra: dict[str, Any] = {"tools": tools} if tools else {}
        extra.update(self._deadline_kw())
        completion = self._deadline_call(history, extra)
        if (
            completion.finish_reason == "length"
            and not completion.content.strip()
            and not completion.tool_calls
        ):
            notes.append(
                "[note] the previous attempt spent its whole output budget thinking; "
                "it was retried without thinking."
            )
            completion = self._deadline_call(history, {**extra, "enable_thinking": False})
            completion.attempts += 1
        elif self._cut_mid_reply(completion):
            completion = self._continue_reply(history, extra, completion, notes)
        return completion, notes

    def _cut_mid_reply(self, completion: Completion) -> bool:
        """Prompt v0.2 (issue #61): the reply hit the output limit after it had started,
        and what arrived is not a usable action (no complete code block, an unclosed
        one, or no FINAL). v0.1 only retried a reply with no content at all."""
        if (
            self.cfg.prompt_version == "v0.1"
            or self.cfg.planner_style != "reclamo"
            or completion.finish_reason != "length"
            or completion.tool_calls
            or not completion.content.strip()
        ):
            return False
        if completion.content_from_reasoning:
            return True  # the "content" is cut-off thinking: no answer began
        content = completion.content
        complete = find_code_blocks(content, strict=True)
        if len(find_code_blocks(content)) > len(complete):
            return True  # a code block was cut open
        return not complete and find_final(content) is None

    def _continue_reply(
        self,
        history: list[dict[str, Any]],
        extra: dict[str, Any],
        cut: Completion,
        notes: list[str],
    ) -> Completion:
        """Ask once, thinking off, for the rest of a cut-off reply and join the parts.
        Cut-off thinking (no reply begun) is retried without thinking instead."""
        if cut.content_from_reasoning:
            notes.append(
                "[note] the previous attempt spent its whole output budget thinking; "
                "it was retried without thinking."
            )
            retry = self._deadline_call(history, {**extra, "enable_thinking": False})
            retry.attempts = cut.attempts + 1
            return retry
        asked = [
            *history,
            {"role": "assistant", "content": cut.content},
            {"role": "user", "content": CONTINUE_PROMPT},
        ]
        rest = self._deadline_call(asked, {**extra, "enable_thinking": False})
        notes.append(
            "[note] the previous reply hit the output limit part-way; it was continued "
            "once and the two parts were joined."
        )
        return dataclasses.replace(
            cut,
            content=cut.content + rest.content,
            finish_reason=rest.finish_reason,
            latency=cut.latency + rest.latency,
            attempts=cut.attempts + 1,
        )

    def _deadline_call(self, history: list[dict[str, Any]], extra: dict[str, Any]) -> Completion:
        if self._past_deadline():
            raise self._timeout_error()
        try:
            completion = self.client.complete(history, "root", **extra)
        except openai.APIError as exc:
            if self._past_deadline():
                raise self._timeout_error() from exc
            raise
        self._budget_add(completion)
        return completion

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
            if self._past_deadline():
                raise self._timeout_error()  # issue #51: no new request past the deadline
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
            served: dict[str, Any] = {}
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
                completion = self.client.complete(
                    [{"role": "user", "content": prompt}], "sub", **self._deadline_kw()
                )
                budget.add(completion)
                answer = completion.content
                served = self._served(completion, "sub")
            latency = time.monotonic() - t0
            self.logger.subcall(
                depth=self.depth,
                kind=kind,
                ran_as="rlm_query" if recurse else "llm_query",
                prompt_chars=prompt_chars,
                answer_chars=len(answer),
                latency=round(latency, 3),
                run_subcalls=budget.subcalls,
                **served,
            )
            self.printer.subcall(kind, prompt_chars, len(answer), latency)
            answers.append(answer)
        return answers

    def _wants_decompose_nudge(self) -> bool:
        """One sub-call this turn got nearly the whole context, and the context is
        larger than one call can read. Never when the context fits in one call: then a
        single big sub-call is a legitimate strategy (paper App. C.1 (1a): "see if it is
        sufficient to just fit it in a few sub-LLM calls")."""
        return (
            self._context_chars > self.cfg.effective_subcall_chars
            and self._turn_max_prompt >= 0.9 * self._context_chars
        )

    def _decompose_nudge(self) -> str:
        return decompose_nudge(
            self.cfg.prompt_version, self._context_chars, self.cfg.effective_subcall_chars
        )

    def _check_limits(self, repl: REPL, answer_state: dict[str, Any] | None) -> None:
        assert self._budget is not None
        b = self._budget
        if b.deadline is not None and time.monotonic() > b.deadline:
            raise self._timeout_error(repl, answer_state)
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
        """Out of turns, time or errors: one more model call that sees the REPL state.

        The model is shown ``answer['content']`` and every usual answer variable that
        exists, so a stale variable cannot silently beat an answer the model just
        printed (independent eval, Neuromancer large), and a good value already in
        the REPL is one ``FINAL_VAR`` away (paper E.2). If the reply is not a usable
        final, fall back: answer dict, then an answer variable, then the reply's
        prose with code and thinking removed, then "".
        """
        stop = FORCED_STOP_REASONS[why]
        dict_content = (answer_state or {}).get("content")
        dict_value = str(dict_content) if dict_content else None
        found_vars: list[tuple[str, str]] = []
        for name in ANSWER_VAR_NAMES:
            var = repl.get_var(name)
            if var.found:
                found_vars.append((name, var.value_str or ""))
        shown = [("answer['content']", dict_value)] if dict_value is not None else []
        shown += found_vars

        tools_mode = self.cfg.protocol == "tools"
        prompt = forced_final_prompt(why, self.cfg.protocol)
        state = forced_final_state(shown, self._last_output)
        if state:
            prompt = f"{state}\n\n{prompt}"
        if self.cfg.planner_style == "upstream-rlm-v0":
            # That style never stores the query (it rides in the per-turn prompt).
            prompt = f'The original prompt: "{self._query}".\n\n{prompt}'
        tools = tool_specs(self.cfg.output_truncate_chars) if tools_mode else None
        messages = self._forced_messages(history, prompt, tools)
        if messages is None:
            completion = Completion("", None, None, "context_overflow", 0.0)
        else:
            completion = self._forced_call(messages, tools, why)
        content = completion.content

        candidates: list[FinalCandidate] = []
        for call in completion.tool_calls or []:
            if call.name != "final_answer":
                continue
            args, _err = _parse_tool_args(call)
            tool_cand = _final_from_args(args, has_code=False)[0] if args is not None else None
            if tool_cand is not None:
                candidates.append(tool_cand)
        text_cand = find_final(content)
        if text_cand is not None:
            # Code in the forced reply never runs, so it does not invalidate the FINAL.
            candidates.append(dataclasses.replace(text_cand, has_code=False))

        answer = ""
        source = "empty"
        detail: dict[str, Any] = {}
        for cand in candidates:
            accepted, value, reason, kind = self._judge_final(cand, repl, None, answer_state)
            detail = {"candidate": cand.value, "kind": kind or cand.kind, "rejected": reason}
            if accepted:
                answer, source = value or "", "model"
                break
        else:
            if dict_value is not None:
                answer, source = dict_value, "answer_dict"
            elif found_vars:
                name, answer = found_vars[0]
                source = "variable"
                detail["variable"] = name
            elif not candidates:
                # Only prose with no FINAL attempt at all; a rejected FINAL's text
                # (a plan, a missing variable) is not an answer either.
                prose = strip_code(content)
                if prose and not looks_like_plan(prose) and not prose.endswith(":"):
                    answer, source = prose, "reply_text"
        self.logger.event(
            "forced_finish",
            source=source,
            why=why,
            depth=self.depth,
            shown=[name for name, _ in shown],
            content=content,
            reasoning=completion.reasoning,
            tool_calls=[dataclasses.asdict(c) for c in completion.tool_calls or []],
            **self._served(completion, "root"),
            **detail,
        )
        return self._finish(answer, stop, iterations, started)

    def _forced_messages(
        self,
        history: list[dict[str, Any]],
        prompt: str,
        tools: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]] | None:
        """The forced finish's request, made to fit the window (issue #49).

        Normally the history with ``prompt`` added to its last user message, as before.
        If that would not fit, REPL outputs are shrunk first; failing that, the request
        is cut to the opening messages (system prompt, query or context metadata) plus
        ``prompt``, which shows the REPL state. Returns None when even that cannot fit,
        and the forced finish then falls back to the REPL values without a model call.
        """
        extra = (estimate_tokens(json.dumps(tools)) if tools else 0) + estimate_tokens(prompt)
        extra += MESSAGE_OVERHEAD_TOKENS
        budget = self._input_budget()
        kinds = self._kinds if len(self._kinds) == len(history) else []
        if request_tokens(history, extra) > budget and kinds:
            if self._shrink_outputs(history, kinds, budget - extra):
                self._push_history_safe()
        if request_tokens(history, extra) <= budget or not kinds:
            if history and history[-1]["role"] == "user":
                history[-1]["content"] = f"{history[-1]['content']}\n\n{prompt}"
            else:
                msg = {"role": "user", "content": prompt}
                self._append(history, kinds=[], msg=msg, kind="repl")
            return history
        opening = [dict(m) for m, k in zip(history, kinds, strict=True) if k in OPENING_KINDS]
        if opening and opening[-1]["role"] == "user":
            opening[-1]["content"] = f"{opening[-1]['content']}\n\n{prompt}"
        else:
            opening.append({"role": "user", "content": prompt})
        size = request_tokens(opening, extra - estimate_tokens(prompt))
        fits = size <= budget
        self.logger.event(
            "context_overflow",
            depth=self.depth,
            during="forced_finish",
            history_tokens=request_tokens(history, extra),
            reduced_tokens=size,
            budget_tokens=budget,
            context_tokens=self.cfg.context_tokens,
            max_tokens=self.cfg.root.max_tokens,
            action="opening_messages_only" if fits else "no_model_call",
        )
        return opening if fits else None

    def _forced_timeout(self) -> float:
        """Issue #51: a forced finish may run FORCED_FINISH_TIMEOUT past the deadline."""
        limit = self.cfg.root.timeout
        b = self._budget
        if b is None or b.deadline is None:
            return limit
        left = max(b.deadline - time.monotonic(), 0.0)
        return min(limit, left + FORCED_FINISH_TIMEOUT)

    def _forced_call(
        self, history: list[dict[str, Any]], tools: list[dict[str, Any]] | None, why: str
    ) -> Completion:
        """The forced finish's model call, bounded whatever the reason (issue #51).

        One attempt with no HTTP retry and a capped request timeout. Past the deadline
        thinking is off. Otherwise the configured thinking is used and, as in the loop,
        a reply that spent its whole budget thinking is retried once without thinking,
        but only while the deadline has not passed. A failed request does not lose the
        run: the fallbacks (answer dict, answer variable) still apply.
        """
        extra: dict[str, Any] = {"tools": tools} if tools else {}

        def attempt(thinking: bool | None) -> Completion | None:
            try:
                c = self.client.complete(
                    history,
                    "root",
                    enable_thinking=thinking,
                    timeout=self._forced_timeout(),
                    retry=False,
                    **extra,
                )
            except openai.APIError as exc:
                self.logger.event(
                    "forced_finish_error",
                    depth=self.depth,
                    why=why,
                    error=f"{type(exc).__name__}: {exc}"[:500],
                )
                return None
            self._budget_add(c)
            return c

        completion = attempt(False if why == "time" else None)
        if (
            completion is not None
            and why != "time"
            and completion.finish_reason == "length"
            and not completion.content.strip()
            and not completion.tool_calls
            and not self._past_deadline()
        ):
            retried = attempt(False)
            if retried is not None:
                retried.attempts += 1
                completion = retried
        if completion is None:
            return Completion(
                content="", reasoning=None, usage=None, finish_reason="error", latency=0.0
            )
        return completion

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
            **self._served(completion, "root"),
            **extra,
        )

    def _served(self, completion: Completion, role: str) -> dict[str, Any]:
        """Which endpoint and model served a call (served id, else the requested one)."""
        return {
            "endpoint": completion.endpoint or self.cfg.endpoint(role).base_url,
            "model": completion.model or self.cfg.role(role).model,
        }

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

    def _input_budget(self) -> int:
        """Prompt tokens a root request may use (issue #49): the window minus the root
        reply's ``max_tokens`` minus a margin for estimate error."""
        ctx = self.cfg.context_tokens
        budget = ctx - self.cfg.root.max_tokens - FIT_MARGIN * ctx
        return int(max(budget, MIN_BUDGET_FRACTION * ctx))

    def _context_overflow(
        self,
        history: list[dict[str, Any]],
        repl: REPL,
        answer_state: dict[str, Any] | None,
        iterations: int,
        started: float,
        extra: int,
    ) -> RLMResult:
        """Issue #49 last resort: the next request cannot be made to fit, so do not send
        it (the server would answer 400); log the sizes and take the forced finish."""
        size, budget = request_tokens(history, extra), self._input_budget()
        self.logger.event(
            "context_overflow",
            depth=self.depth,
            during="turn",
            turn=iterations + 1,
            request_tokens=size,
            budget_tokens=budget,
            context_tokens=self.cfg.context_tokens,
            max_tokens=self.cfg.root.max_tokens,
        )
        self.printer.note(
            f"the next request (~{size} est. tokens) cannot fit the input budget of {budget} "
            f"(context_tokens={self.cfg.context_tokens} - max_tokens="
            f"{self.cfg.root.max_tokens} - margin) even after compaction; forcing a final answer"
        )
        return self._forced_finish(history, repl, answer_state, iterations, started, why="context")

    def _shrink_outputs(
        self, history: list[dict[str, Any]], kinds: list[str], target: int
    ) -> list[int]:
        """Shrink intact REPL outputs, largest first (ties: oldest), until the history
        fits ``target`` tokens (issue #49). Each shrunk output keeps its head and tail
        around a stub pointing at the full text in the REPL's ``history``. Returns the
        history indexes changed; the history may still not fit."""
        changed: set[int] = set()
        stub_tokens = estimate_tokens(FIT_STUB.format(cut=10**6, total=10**6))
        while True:
            excess = request_tokens(history) - target
            if excess <= 0:
                break
            best: tuple[tuple[int, int], int, _Piece] | None = None
            for idx, pieces in self._pieces.items():
                if idx >= len(kinds) or kinds[idx] != "repl":
                    continue
                for piece in pieces:
                    if not piece.shrinkable:
                        continue
                    key = (estimate_tokens(piece.text), -idx)
                    if best is None or key > best[0]:
                        best = (key, idx, piece)
            if best is None:
                break
            (tokens, _), idx, piece = best
            current = len(piece.orig) if piece.kept < 0 else piece.kept
            want = tokens - excess - stub_tokens
            keep = int(current * want / tokens) if want > 0 and tokens else 0
            if keep < MIN_KEPT_CHARS or keep >= current:
                keep = 0
            if keep == 0 and estimate_tokens(piece.orig) <= stub_tokens:
                piece.shrinkable = False  # already smaller than a stub: leave it
                continue
            piece.text = _clip_middle(piece.orig, keep)
            piece.kept = keep
            if keep == 0:
                piece.shrinkable = False
            history[idx] = {**history[idx], "content": "".join(p.text for p in self._pieces[idx])}
            changed.add(idx)
        return sorted(changed)

    def _push_history_safe(self) -> None:
        if self._repl is not None:
            self._push_history(self._repl)

    def _maybe_compact(
        self,
        history: list[dict[str, Any]],
        kinds: list[str],
        repl: REPL,
        turn: int,
        extra: int = 0,
    ) -> bool:
        """Make the next root request fit the input budget (issue #49).

        ``extra`` counts what the request carries besides ``history`` (the upstream
        per-turn prompt, the tool specs). Step 1, as before: stub REPL outputs older than
        the last KEEP_RECENT_TURNS and, if still over, summarize them with one sub-call.
        Step 2: shrink the remaining REPL outputs, largest first, which handles a single
        turn whose outputs alone overflow the window. Returns False when the request
        still cannot fit; the caller then takes the forced finish instead of sending it.
        """
        cfg = self.cfg
        budget = self._input_budget()

        def estimate() -> int:
            return request_tokens(history, extra)

        before = estimate()
        if before <= budget:
            return True

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
            self._pieces.pop(idx, None)

        summarized = False
        summary_served: dict[str, Any] = {}
        if elided and estimate() > budget and not self._past_deadline():
            body = "\n\n".join(f"--- turn {t} ---\n{text}" for t, text in elided)
            prompt = (
                "Below are outputs from earlier steps of a data-analysis session. Summarize "
                f"what was learned in under {SUMMARY_CHARS} characters: facts found, variable "
                "names created and what they hold, and anything still unresolved.\n\n"
                f"{body[: cfg.effective_subcall_chars]}"
            )
            try:
                completion = self.client.complete(
                    [{"role": "user", "content": prompt}], "sub", **self._deadline_kw()
                )
            except openai.APIError:
                if not self._past_deadline():
                    raise
                # Issue #51: the summary ran into the deadline; the next root call
                # takes the forced finish, which never reads this placeholder's turn.
                completion = Completion("(not summarized: " + TIME_UP + ")", None, None, None, 0.0)
            self._budget_add(completion)
            summary_served = self._served(completion, "sub")
            first, last = elided[0][0], elided[-1][0]
            history[old[0]] = {
                **history[old[0]],
                "content": (
                    f"[Summary of elided REPL output from turns {first}-{last}]\n"
                    f"{completion.content.strip()[:SUMMARY_CHARS]}"
                ),
            }
            summarized = True

        shrunk = self._shrink_outputs(history, kinds, budget - extra)
        if not elided and not shrunk:
            return False  # nothing left to shrink: the caller takes the forced finish
        self._push_history(repl)
        after = estimate()
        self.logger.compaction(
            depth=self.depth,
            turn=turn,
            before_tokens=round(before),
            after_tokens=round(after),
            budget_tokens=budget,
            elided_turns=[t for t, _ in elided],
            summarized=summarized,
            shrunk_messages=shrunk,
            **{f"summary_{k}": v for k, v in summary_served.items()},
        )
        self.printer.note(
            f"compacted history: {round(before)} -> {round(after)} est. tokens "
            f"(budget {budget}); full history is in the REPL as `history`"
        )
        return after <= budget

    def _push_history(self, repl: REPL) -> None:
        literal = json.dumps(json.dumps(self._full_history, ensure_ascii=True))
        repl.execute(f"import json as _json\nhistory = _json.loads({literal})")


__all__ = [
    "RLM",
    "RLMResult",
    "RunBudget",
    "describe_context",
    "estimate_tokens",
    "request_tokens",
]
