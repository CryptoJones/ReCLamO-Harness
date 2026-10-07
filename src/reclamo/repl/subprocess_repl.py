"""Run the REPL worker as a local subprocess (``python -I worker.py``).

The child's environment is scrubbed to a handful of harmless variables. No API
key, no ``RECLAMO_*``, no ``OPENAI_*`` ever reaches it. The protocol pump,
timeout and recovery live in ``ProcessREPL``.
"""

from __future__ import annotations

import os
import subprocess
import sys

from reclamo.config import RLMConfig
from reclamo.repl.base import LLMHandler
from reclamo.repl.process_repl import WORKER_PATH, ProcessREPL, WorkerDied

_SAFE_ENV_KEYS = ("PATH", "LANG", "LC_ALL", "SYSTEMROOT")


class SubprocessREPL(ProcessREPL):
    def __init__(
        self,
        cfg: RLMConfig,
        llm_handler: LLMHandler,
        *,
        python: str = sys.executable,
    ) -> None:
        super().__init__(cfg, llm_handler)
        self._python = python

    def _child_env(self) -> dict[str, str]:
        assert self._tmp is not None
        env = {k: os.environ[k] for k in _SAFE_ENV_KEYS if k in os.environ}
        env.setdefault("PATH", "/usr/bin:/bin")
        env["HOME"] = self._tmp
        env["TMPDIR"] = self._tmp
        env["LANG"] = env.get("LANG") or "C.UTF-8"
        return env

    def _popen(self) -> subprocess.Popen[str]:
        assert self._tmp is not None
        return subprocess.Popen(
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

    def _worker_context_path(self) -> str:
        return self.host_context_path


__all__ = ["SubprocessREPL", "WorkerDied", "WORKER_PATH"]
