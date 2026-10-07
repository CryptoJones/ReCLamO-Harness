"""REPL back-ends: where model-written code runs."""

from __future__ import annotations

from reclamo.config import RLMConfig
from reclamo.repl.base import REPL, ExecResult, LLMHandler, VarResult
from reclamo.repl.docker_repl import DockerREPL, DockerUnavailable
from reclamo.repl.subprocess_repl import SubprocessREPL

SANDBOXES = ("subprocess", "docker")


def make_repl(cfg: RLMConfig, handler: LLMHandler) -> REPL:
    """Build the REPL selected by ``cfg.sandbox``."""
    if cfg.sandbox == "docker":
        return DockerREPL(cfg, handler)
    if cfg.sandbox == "subprocess":
        return SubprocessREPL(cfg, handler)
    raise ValueError(f"unknown sandbox {cfg.sandbox!r}; expected one of {SANDBOXES}")


__all__ = [
    "REPL",
    "SANDBOXES",
    "DockerREPL",
    "DockerUnavailable",
    "ExecResult",
    "LLMHandler",
    "SubprocessREPL",
    "VarResult",
    "make_repl",
]
