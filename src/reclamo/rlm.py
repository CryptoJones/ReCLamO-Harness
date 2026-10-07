"""The Recursive Language Model loop.

``RLM.completion(context, query)`` runs up to ``max_iterations`` turns. Each
turn the root model writes code, the REPL runs it, and the model sees a short
output. The history is append-only (one user message per turn carrying the
REPL output and the next ``Turn i/N`` line) so a server with a prefix cache
reuses it. Sub-calls made from inside the REPL (``llm_query``,
``llm_query_batched``, ``rlm_query``) come back to this process through the
REPL's handler, which enforces the per-run budget and, for ``rlm_query``,
starts a child ``RLM`` one level deeper.

``rlm_query(prompt)`` semantics: the prompt becomes the child's *context* and
the child gets a fixed query telling it to carry out the task in that context.
That way a child can slice and search what it was handed, which is the whole
point of recursing. At ``max_depth`` it degrades to a plain ``llm_query``.

Termination, in priority order per turn: an ``answer`` dict marked ready in
the REPL; then a ``FINAL`` / ``FINAL_VAR`` candidate in the prose (rejected,
with a corrective message, when it sits next to unexecuted code, names a
missing variable, or reads like a plan the first time it is seen). When turns
run out the loop prefers an answer that already exists in the REPL over asking
the model again (paper failure E.2).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from reclamo.client import Completion, Usage
from reclamo.config import RLMConfig
from reclamo.errors import RLMErrorLimit, RLMTimeout, RLMTokenLimit
from reclamo.logger import TrajectoryLogger, VerbosePrinter
from reclamo.parsing import FinalCandidate, find_code_blocks, find_final
from reclamo.prompts import (
    ContextMeta,
    build_system_prompt,
    decompose_nudge,
    final_rejection,
    forced_final_prompt,
    reverify_nudge,
    turn_prompt,
)
from reclamo.repl.base import REPL, ExecResult, LLMHandler
from reclamo.repl.subprocess_repl import SubprocessREPL


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
NO_ACTION_PROMPT = (
    "That message had no code and no final answer. Reply with exactly one ```repl code "
    "block, or FINAL(...) / FINAL_VAR(...) when the answer is ready."
)
RLM_QUERY_PROMPT = (
    "The context holds a task handed down by a parent process: instructions and the "
    "data they apply to. Carry out the task and finish with the result."
)
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


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


@dataclass
class RunBudget:
    """Shared by a root RLM and every child it spawns."""

    max_subcalls: int
    deadline: float | None
    max_tokens: int | None
    started: float = field(default_factory=time.monotonic)
    subcalls: int = 0
    subcall_chars: int = 0
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


def _default_repl_factory(cfg: RLMConfig, handler: LLMHandler) -> REPL:
    return SubprocessREPL(cfg, handler)


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
        self._full_history: list[dict[str, str]] = []

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
            self._check_limits(repl, answer_state)
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
                res = repl.execute(block)
                results.append(res)
                self.printer.output(k, res.output)
                if res.answer is not None:
                    answer_state = res.answer

            if blocks:
                consecutive_errors = consecutive_errors + 1 if any(r.error for r in results) else 0
                if consecutive_errors >= cfg.max_errors:
                    self._log_iteration(i, messages_in, completion, blocks, results, notes, None)
                    raise RLMErrorLimit(
                        f"{consecutive_errors} consecutive REPL errors "
                        f"(max_errors={cfg.max_errors})",
                        partial_answer=self._partial(repl, answer_state),
                    )

            for res in results:
                if res.answer_ready:
                    answer = (res.answer or {}).get("content") or ""
                    decision = {"kind": "answer_dict", "accepted": True}
                    self._log_iteration(
                        i, messages_in, completion, blocks, results, notes, decision
                    )
                    return self._finish(answer, "answer_dict", i, started)

            cand = find_final(content)
            decision: dict[str, Any] | None = None
            if cand is not None:
                accepted, value, reason, stop = self._judge_final(cand, repl, rejected_plan)
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
            for note in notes:
                self.printer.note(note)

            parts.extend(notes)
            if i < n:
                parts.append(turn_prompt(i + 1, n))
            self._append(history, kinds, {"role": "user", "content": "\n\n".join(parts)}, "repl")
            self._log_iteration(i, messages_in, completion, blocks, results, notes, decision)

        return self._forced_finish(history, repl, answer_state, iterations, started)

    # --- pieces -----------------------------------------------------------

    def _append(
        self, history: list[dict[str, str]], kinds: list[str], msg: dict[str, str], kind: str
    ) -> None:
        history.append(msg)
        kinds.append(kind)
        self._full_history.append(msg)

    def _root_call(self, history: list[dict[str, str]]) -> tuple[Completion, list[str]]:
        notes: list[str] = []
        completion = self.client.complete(history, "root")
        self._budget_add(completion)
        if completion.finish_reason == "length" and not completion.content.strip():
            notes.append(
                "[note] the previous attempt spent its whole output budget thinking; "
                "it was retried without thinking."
            )
            completion = self.client.complete(history, "root", enable_thinking=False)
            self._budget_add(completion)
            completion.attempts += 1
        return completion, notes

    def _budget_add(self, completion: Completion) -> None:
        assert self._budget is not None
        self._budget.add(completion)

    def _judge_final(
        self, cand: FinalCandidate, repl: REPL, rejected_plan: str | None
    ) -> tuple[bool, str | None, str | None, str]:
        """Return (accepted, value, rejection reason, stop_reason)."""
        if cand.has_code:
            return False, None, "it was sent in the same message as code that had not run yet.", ""
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

    def _handle_subcall(self, kind: str, prompts: list[str]) -> list[str]:
        """REPL handler: budget, logging, and the rlm_query -> child RLM dispatch."""
        assert self._budget is not None
        budget = self._budget
        cfg = self.cfg
        answers: list[str] = []
        for prompt in prompts:
            if budget.subcalls >= budget.max_subcalls:
                raise RuntimeError(
                    f"sub-call budget for this run exhausted ({budget.max_subcalls}); "
                    "finish with what you have"
                )
            budget.subcalls += 1
            budget.subcall_chars += len(prompt)
            self._turn_max_prompt = max(self._turn_max_prompt, len(prompt))
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
                answer = child.completion(prompt, RLM_QUERY_PROMPT).answer
            else:
                completion = self.client.complete([{"role": "user", "content": prompt}], "sub")
                budget.add(completion)
                answer = completion.content
            latency = time.monotonic() - t0
            self.logger.subcall(
                depth=self.depth,
                kind=kind,
                ran_as="rlm_query" if recurse else "llm_query",
                prompt_chars=len(prompt),
                answer_chars=len(answer),
                latency=round(latency, 3),
                run_subcalls=budget.subcalls,
            )
            self.printer.subcall(kind, len(prompt), len(answer), latency)
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
        history: list[dict[str, str]],
        repl: REPL,
        answer_state: dict[str, Any] | None,
        iterations: int,
        started: float,
    ) -> RLMResult:
        """Out of turns: use what exists in the REPL before asking the model again."""
        existing = self._partial(repl, answer_state)
        if existing is not None:
            self.logger.event("forced_finish", method="existing_value", depth=self.depth)
            return self._finish(existing, "max_iterations", iterations, started)

        prompt = forced_final_prompt()
        if history and history[-1]["role"] == "user":
            history[-1]["content"] = f"{history[-1]['content']}\n\n{prompt}"
        else:
            self._append(history, kinds=[], msg={"role": "user", "content": prompt}, kind="repl")
        completion, _notes = self._root_call(history)
        content = completion.content
        answer = content.strip()
        cand = find_final(content)
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
        )
        return self._finish(answer, "max_iterations", iterations, started)

    def _finish(self, answer: str, reason: str, iterations: int, started: float) -> RLMResult:
        assert self._budget is not None
        elapsed = time.monotonic() - started
        self.logger.final(
            depth=self.depth,
            answer=answer,
            stop_reason=reason,
            iterations=iterations,
            subcalls=self._budget.subcalls,
            usage=dataclasses.asdict(self._budget.usage),
            elapsed=round(elapsed, 3),
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
        )

    # --- compaction (epic #8 decision 8) ----------------------------------

    def _maybe_compact(
        self, history: list[dict[str, str]], kinds: list[str], repl: REPL, turn: int
    ) -> None:
        cfg = self.cfg
        limit = 0.85 * cfg.context_tokens

        def estimate() -> float:
            return sum(len(m["content"]) for m in history) / CHARS_PER_TOKEN

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
            history[idx] = {
                "role": "user",
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
                "role": "user",
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
