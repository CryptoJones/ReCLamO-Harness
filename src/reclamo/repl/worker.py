"""ReCLamO REPL worker: runs model-written Python in a persistent namespace.

Stand-alone and stdlib-only on purpose. It is started as ``python -I worker.py``
by ``subprocess_repl.py`` and, in the Docker sandbox, inside ``python:3.12-slim``
with no network, so it must not import anything from ``reclamo``.

Protocol (JSON lines; epic #8 decision 7):

- The worker dups the real stdout to a private file object for protocol writes,
  then points fd 1 at fd 2 so stray C-level writes to stdout can never land in
  the protocol stream. User ``print`` is captured in-process during each exec.
- parent -> worker: ``init``, ``exec``, ``llm_result``, ``get_var``, ``shutdown``.
- worker -> parent: ``ready`` (at start-up), ``init_ok``, ``llm_request`` (then it
  blocks until the matching ``llm_result``), ``exec_result``, ``var``.

Nothing secret ever reaches this process: the parent scrubs the environment and
the only way out is the ``llm_request`` message.
"""

from __future__ import annotations

import ast
import builtins
import contextlib
import io
import json
import os
import sys
import traceback
import types
from typing import Any

TRUNCATE_DEFAULT = 2_000
VAR_REPR_LIMIT = 2_000

# Names the harness owns. They are put back after every exec if the model
# rebinds or deletes them (``context`` only if deleted: slicing it in place is
# unwise, but the model may have meant it).
RESERVED = ("context", "llm_query", "llm_query_batched", "rlm_query", "SHOW_VARS", "FINAL_VAR")


class _Protocol:
    """Owns the two protocol streams and the request ids."""

    def __init__(self) -> None:
        self.out = os.fdopen(os.dup(1), "w", buffering=1, encoding="utf-8")
        self.inp = open(0, encoding="utf-8", closefd=False)
        self.next_id = 0

    def send(self, msg: dict[str, Any]) -> None:
        self.out.write(json.dumps(msg) + "\n")
        self.out.flush()

    def recv(self) -> dict[str, Any] | None:
        line = self.inp.readline()
        if not line:
            return None
        line = line.strip()
        return json.loads(line) if line else {}


class Worker:
    def __init__(self, proto: _Protocol) -> None:
        self.proto = proto
        self.ns: dict[str, Any] = {}
        self.truncate = TRUNCATE_DEFAULT
        self.max_subcalls_per_exec = 24
        self.subcalls_this_exec = 0
        self.context: Any = None
        self.reserved: dict[str, Any] = {}

    # --- lifecycle --------------------------------------------------------

    def init(self, msg: dict[str, Any]) -> None:
        self.truncate = int(msg.get("truncate", TRUNCATE_DEFAULT))
        self.max_subcalls_per_exec = int(msg.get("max_subcalls_per_exec", 24))
        path = msg["context_path"]
        kind = msg.get("context_kind", "str")
        with open(path, encoding="utf-8", errors="replace") as fh:
            self.context = json.load(fh) if kind == "json" else fh.read()
        self.reserved = {
            "context": self.context,
            "llm_query": self.llm_query,
            "llm_query_batched": self.llm_query_batched,
            "rlm_query": self.rlm_query,
            "SHOW_VARS": self.show_vars,
            "FINAL_VAR": self.final_var,
        }
        self.ns = {"__name__": "__main__", "__builtins__": builtins, "answer": {}}
        self.ns.update(self.reserved)
        self.proto.send(
            {
                "type": "init_ok",
                "context_kind": type(self.context).__name__,
                "context_len": _length(self.context),
            }
        )

    def serve(self) -> None:
        self.proto.send({"type": "ready"})
        while True:
            msg = self.proto.recv()
            if msg is None:
                return
            kind = msg.get("type")
            if kind == "init":
                self.init(msg)
            elif kind == "exec":
                self.proto.send(self.execute(msg))
            elif kind == "get_var":
                self.proto.send(self.get_var(msg["name"]))
            elif kind == "shutdown":
                return
            elif kind:
                self.proto.send({"type": "error", "error": f"unexpected message {kind!r}"})

    # --- builtins exposed to the model ------------------------------------

    def _request(self, kind: str, prompts: list[str]) -> list[str]:
        for p in prompts:
            if not isinstance(p, str):
                raise TypeError(f"{kind} prompts must be str, got {type(p).__name__}")
        if self.subcalls_this_exec + len(prompts) > self.max_subcalls_per_exec:
            raise RuntimeError(
                f"sub-call cap reached: at most {self.max_subcalls_per_exec} sub-calls per "
                f"code block ({self.subcalls_this_exec} used, {len(prompts)} requested). "
                "Batch more text per prompt, or spread the work over several turns."
            )
        self.subcalls_this_exec += len(prompts)
        self.proto.next_id += 1
        rid = self.proto.next_id
        self.proto.send({"type": "llm_request", "id": rid, "kind": kind, "prompts": prompts})
        while True:
            reply = self.proto.recv()
            if reply is None:
                raise RuntimeError("parent closed the connection while waiting for the model")
            if reply.get("type") == "llm_result" and reply.get("id") == rid:
                break
        if not reply.get("ok"):
            raise RuntimeError(str(reply.get("error") or "sub-call failed"))
        value = reply.get("value")
        if not isinstance(value, list):
            value = [value]
        return [str(v) for v in value]

    def llm_query(self, prompt: str) -> str:
        """Ask a fresh model one question; it sees only ``prompt``."""
        return self._request("llm_query", [prompt])[0]

    def llm_query_batched(self, prompts: list[str]) -> list[str]:
        """Ask several questions; answers come back in the same order."""
        prompts = list(prompts)
        if not prompts:
            return []
        return self._request("llm_query_batched", prompts)

    def rlm_query(self, prompt: str) -> str:
        """Ask a nested RLM (it gets its own REPL). The parent may downgrade it."""
        return self._request("rlm_query", [prompt])[0]

    def show_vars(self) -> None:
        """Print the variables created so far with their types and sizes."""
        rows = []
        for name, value in sorted(self.ns.items()):
            if name in self.reserved or name.startswith("_") or name == "answer":
                continue
            if isinstance(value, types.ModuleType | types.FunctionType | type):
                continue
            size = _length(value)
            desc = type(value).__name__ + (f" (len {size:,})" if size is not None else "")
            rows.append(f"{name}: {desc}")
        print("\n".join(rows) if rows else "(no variables yet)")

    def final_var(self, name: str) -> str:
        """Return the text of a variable; the loop treats a FINAL_VAR as the answer."""
        if name not in self.ns:
            raise NameError(f"FINAL_VAR: no variable named {name!r}")
        return str(self.ns[name])

    # --- exec -------------------------------------------------------------

    def execute(self, msg: dict[str, Any]) -> dict[str, Any]:
        code = msg.get("code", "")
        self.subcalls_this_exec = 0
        out, err = io.StringIO(), io.StringIO()
        error: str | None = None

        try:
            tree = ast.parse(code, filename="<repl>")
        except SyntaxError as exc:
            error = f"SyntaxError: {exc.msg} (line {exc.lineno})"
        else:
            body = list(tree.body)
            last: ast.Expression | None = None
            if body and isinstance(body[-1], ast.Expr):
                last = ast.Expression(body[-1].value)
                ast.copy_location(last, body[-1])
                ast.fix_missing_locations(last)
                body = body[:-1]
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                try:
                    if body:
                        module = ast.Module(body=body, type_ignores=[])
                        exec(compile(module, "<repl>", "exec"), self.ns)  # noqa: S102
                    if last is not None:
                        value = eval(compile(last, "<repl>", "eval"), self.ns)  # noqa: S307
                        if value is not None:
                            print(repr(value))
                except SystemExit:
                    error = "SystemExit: exit() is not available in the REPL"
                except BaseException as exc:  # noqa: BLE001 - report everything
                    error = _format_error(exc)

        self._restore_reserved()
        stdout, dropped_out = _truncate(out.getvalue(), self.truncate)
        stderr, dropped_err = _truncate(err.getvalue(), self.truncate)
        return {
            "type": "exec_result",
            "id": msg.get("id"),
            "stdout": stdout,
            "stderr": stderr,
            "error": error,
            "truncated_chars": dropped_out + dropped_err,
            "answer": self._answer_state(),
            "vars": self._user_vars(),
            "subcalls": self.subcalls_this_exec,
        }

    def _restore_reserved(self) -> None:
        for name, value in self.reserved.items():
            if name == "context":
                if "context" not in self.ns:
                    self.ns["context"] = value
            elif self.ns.get(name) is not value:
                self.ns[name] = value
        if not isinstance(self.ns.get("answer"), dict):
            self.ns["answer"] = {}

    def _answer_state(self) -> dict[str, Any] | None:
        answer = self.ns.get("answer")
        if not isinstance(answer, dict) or not answer:
            return None
        content = answer.get("content")
        return {
            "ready": bool(answer.get("ready")),
            "content": None if content is None else str(content),
        }

    def _user_vars(self) -> list[str]:
        names = []
        for name, value in self.ns.items():
            if name in self.reserved or name == "answer" or name.startswith("_"):
                continue
            if isinstance(value, types.ModuleType):
                continue
            names.append(name)
        return sorted(names)

    def get_var(self, name: str) -> dict[str, Any]:
        if name not in self.ns:
            return {"type": "var", "name": name, "found": False}
        value = self.ns[name]
        rep = repr(value)
        if len(rep) > VAR_REPR_LIMIT:
            rep = rep[:VAR_REPR_LIMIT] + f"... [{len(rep) - VAR_REPR_LIMIT} more chars]"
        return {
            "type": "var",
            "name": name,
            "found": True,
            "value_repr": rep,
            "value_str": str(value),
        }


def _length(value: Any) -> int | None:
    try:
        return len(value)
    except TypeError:
        return None


def _truncate(text: str, limit: int) -> tuple[str, int]:
    if limit <= 0 or len(text) <= limit:
        return text, 0
    dropped = len(text) - limit
    return text[:limit] + f"\n[truncated: {dropped} chars; store it in a variable]", dropped


def _format_error(exc: BaseException) -> str:
    line = f"{type(exc).__name__}: {exc}".splitlines()[0] if str(exc) else type(exc).__name__
    user_lines = [
        f.lineno for f in traceback.extract_tb(exc.__traceback__) if f.filename == "<repl>"
    ]
    if user_lines:
        line += f" (line {user_lines[-1]})"
    return line


def _no_input(*_args: Any, **_kwargs: Any) -> str:
    raise RuntimeError("input() is not available in the REPL")


def main() -> int:
    proto = _Protocol()
    # fd 1 is the protocol's only route out; after dup'ing it above, point it at
    # stderr so nothing else (C extensions, os.write(1, ...)) can write into it.
    os.dup2(2, 1)
    sys.stdout = io.TextIOWrapper(os.fdopen(os.dup(2), "wb"), encoding="utf-8", line_buffering=True)
    builtins.input = _no_input
    Worker(proto).serve()
    return 0


if __name__ == "__main__":
    sys.exit(main())
