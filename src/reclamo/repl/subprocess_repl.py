"""Run the REPL worker as a local subprocess (``python -I worker.py``).

The parent owns the protocol pump: it sends ``exec`` messages, answers the
worker's ``llm_request`` messages through the caller's handler, and enforces a
per-exec wall-clock timeout. A worker that hangs or dies is killed and
relaunched with the same context; the model is told its variables are gone.

The child's environment is scrubbed to a handful of harmless variables. No API
key, no ``RECLAMO_*``, no ``OPENAI_*`` ever reaches it.
"""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

from reclamo.config import RLMConfig
from reclamo.repl.base import REPL, ExecResult, LLMHandler, VarResult

WORKER_PATH = Path(__file__).with_name("worker.py")
_SAFE_ENV_KEYS = ("PATH", "LANG", "LC_ALL", "SYSTEMROOT")


class WorkerDied(RuntimeError):
    """The worker process exited (or its stdout closed) while we were waiting."""


class SubprocessREPL(REPL):
    def __init__(
        self,
        cfg: RLMConfig,
        llm_handler: LLMHandler,
        *,
        python: str = sys.executable,
    ) -> None:
        self.cfg = cfg
        self._handler = llm_handler
        self._python = python
        self._tmp: str | None = None
        self._context_path: str | None = None
        self._context_kind = "str"
        self._proc: subprocess.Popen[str] | None = None
        self._lines: queue.Queue[str | None] = queue.Queue()
        self._stderr_tail: deque[str] = deque(maxlen=50)
        self._next_id = 0
        self.restarts = 0
        self.total_subcalls = 0

    # --- lifecycle --------------------------------------------------------

    def start(self, context: Any, kind: str = "str") -> None:
        self._tmp = tempfile.mkdtemp(prefix="reclamo-repl-")
        self._context_kind = kind
        name = "context.json" if kind == "json" else "context.txt"
        self._context_path = os.path.join(self._tmp, name)
        with open(self._context_path, "w", encoding="utf-8") as fh:
            if kind == "json":
                json.dump(context, fh)
            else:
                fh.write(context if isinstance(context, str) else str(context))
        self._launch()

    def close(self) -> None:
        self._stop_worker(graceful=True)
        if self._tmp:
            shutil.rmtree(self._tmp, ignore_errors=True)
            self._tmp = None

    def _child_env(self) -> dict[str, str]:
        assert self._tmp is not None
        env = {k: os.environ[k] for k in _SAFE_ENV_KEYS if k in os.environ}
        env.setdefault("PATH", "/usr/bin:/bin")
        env["HOME"] = self._tmp
        env["TMPDIR"] = self._tmp
        env["LANG"] = env.get("LANG") or "C.UTF-8"
        return env

    def _launch(self) -> None:
        assert self._tmp is not None and self._context_path is not None
        self._lines = queue.Queue()
        self._stderr_tail.clear()
        self._proc = subprocess.Popen(
            [self._python, "-I", str(WORKER_PATH)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=self._tmp,
            env=self._child_env(),
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        threading.Thread(target=self._pump_stdout, args=(self._proc,), daemon=True).start()
        threading.Thread(target=self._pump_stderr, args=(self._proc,), daemon=True).start()

        deadline = time.monotonic() + self.cfg.exec_timeout
        ready = self._recv(deadline)
        if ready.get("type") != "ready":
            raise WorkerDied(f"worker did not say ready: {ready}")
        self._send(
            {
                "type": "init",
                "context_path": self._context_path,
                "context_kind": self._context_kind,
                "truncate": self.cfg.output_truncate_chars,
                "max_subcalls_per_exec": self.cfg.max_subcalls_per_exec,
            }
        )
        init = self._recv(deadline)
        if init.get("type") != "init_ok":
            raise WorkerDied(f"worker failed to load the context: {init}")

    def _pump_stdout(self, proc: subprocess.Popen[str]) -> None:
        assert proc.stdout is not None
        q = self._lines
        try:
            for line in proc.stdout:
                q.put(line)
        finally:
            q.put(None)

    def _pump_stderr(self, proc: subprocess.Popen[str]) -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            self._stderr_tail.append(line.rstrip("\n"))

    def _stop_worker(self, *, graceful: bool) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        if graceful and proc.poll() is None:
            try:
                self._send({"type": "shutdown"}, proc)
                proc.wait(timeout=1.0)
            except (OSError, ValueError, subprocess.TimeoutExpired, WorkerDied):
                pass
        if proc.poll() is None:
            proc.kill()
            try:
                proc.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                pass
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            try:
                if stream:
                    stream.close()
            except OSError:
                pass

    def _restart(self) -> None:
        self._stop_worker(graceful=False)
        self.restarts += 1
        self._launch()

    # --- protocol ---------------------------------------------------------

    def _send(self, msg: dict[str, Any], proc: subprocess.Popen[str] | None = None) -> None:
        proc = proc or self._proc
        if proc is None or proc.stdin is None:
            raise WorkerDied("worker is not running")
        try:
            proc.stdin.write(json.dumps(msg) + "\n")
            proc.stdin.flush()
        except (BrokenPipeError, OSError, ValueError) as exc:
            raise WorkerDied(f"worker stdin closed: {exc}") from None

    def _recv(self, deadline: float) -> dict[str, Any]:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            try:
                line = self._lines.get(timeout=min(remaining, 0.5))
            except queue.Empty:
                continue
            if line is None:
                tail = "\n".join(self._stderr_tail)
                raise WorkerDied(tail.strip() or "worker exited")
            line = line.strip()
            if not line:
                continue
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue  # never trust the stream blindly

    # --- REPL API ---------------------------------------------------------

    def execute(self, code: str) -> ExecResult:
        if self._proc is None:
            raise RuntimeError("call start() first")
        self._next_id += 1
        rid = self._next_id
        timeout = self.cfg.exec_timeout
        deadline = time.monotonic() + timeout
        try:
            self._send({"type": "exec", "id": rid, "code": code})
            while True:
                msg = self._recv(deadline)
                kind = msg.get("type")
                if kind == "llm_request":
                    paused = time.monotonic()
                    reply = self._handle_llm_request(msg)
                    deadline += time.monotonic() - paused  # model time is not REPL time
                    self._send(reply)
                elif kind == "exec_result" and msg.get("id") == rid:
                    self.total_subcalls += int(msg.get("subcalls") or 0)
                    return ExecResult(
                        stdout=msg.get("stdout") or "",
                        stderr=msg.get("stderr") or "",
                        error=msg.get("error"),
                        truncated_chars=int(msg.get("truncated_chars") or 0),
                        answer=msg.get("answer"),
                        vars=list(msg.get("vars") or []),
                        subcalls=int(msg.get("subcalls") or 0),
                    )
        except TimeoutError:
            return self._recover(f"timeout after {timeout:g}s")
        except WorkerDied as exc:
            detail = str(exc).splitlines()[-1] if str(exc) else "no output"
            return self._recover(f"REPL crashed ({detail})")

    def _recover(self, what: str) -> ExecResult:
        """Relaunch the worker after ``what`` went wrong; report either outcome."""
        try:
            self._restart()
        except (TimeoutError, WorkerDied, OSError) as exc:
            self._stop_worker(graceful=False)  # leaves _proc=None: next call fails loudly
            detail = str(exc).strip().splitlines()[-1] if str(exc).strip() else type(exc).__name__
            return ExecResult(
                error=f"{what}; REPL could not be restarted: {detail}",
                restarted=True,
            )
        return ExecResult(error=f"{what}; REPL restarted, variables lost", restarted=True)

    def _handle_llm_request(self, msg: dict[str, Any]) -> dict[str, Any]:
        kind = str(msg.get("kind") or "llm_query")
        prompts = [str(p) for p in (msg.get("prompts") or [])]
        try:
            answers = [str(a) for a in self._handler(kind, prompts)]
            if len(answers) != len(prompts):
                raise ValueError(
                    f"handler returned {len(answers)} answers for {len(prompts)} prompts"
                )
        except Exception as exc:  # noqa: BLE001 - becomes an exception in user code
            return {"type": "llm_result", "id": msg.get("id"), "ok": False, "error": _one_line(exc)}
        return {"type": "llm_result", "id": msg.get("id"), "ok": True, "value": answers}

    def get_var(self, name: str) -> VarResult:
        if self._proc is None:
            raise RuntimeError("call start() first")
        deadline = time.monotonic() + self.cfg.exec_timeout
        try:
            self._send({"type": "get_var", "name": name})
            while True:
                msg = self._recv(deadline)
                if msg.get("type") == "var" and msg.get("name") == name:
                    return VarResult(
                        name=name,
                        found=bool(msg.get("found")),
                        value_repr=msg.get("value_repr"),
                        value_str=msg.get("value_str"),
                    )
        except (TimeoutError, WorkerDied):
            self._recover("get_var failed")
            return VarResult(name=name, found=False)


def _one_line(exc: BaseException) -> str:
    text = str(exc).strip().splitlines()
    return f"{type(exc).__name__}: {text[0] if text else ''}".rstrip(": ")


__all__ = ["SubprocessREPL", "WorkerDied", "WORKER_PATH"]
