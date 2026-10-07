"""Run the REPL worker inside a locked-down Docker container.

Same worker, same stdio protocol (``docker run -i`` forwards stdin/stdout), so
sub-calls still travel over the pipe and the container needs **no network**:

    docker run -i --rm --name reclamo-<id> --network none --read-only
      --tmpfs /tmp:rw,size=256m --memory 2g --pids-limit 256 --cpus 2
      --security-opt no-new-privileges --cap-drop ALL --user 65534:65534
      -e LANG=C.UTF-8 -e HOME=/tmp
      -v <scratch>:/work:ro -v <worker.py>:/reclamo/worker.py:ro -w /tmp
      python:3.12-slim python -I /reclamo/worker.py

The scratch directory holding the context lives under ``~/.cache/reclamo/sandbox``
(Docker on macOS only shares paths under the home directory by default) and is
made world-readable because the container runs as ``nobody``. Each launch gets
a fresh container name; close, timeout and crash all ``docker kill`` it rather
than trusting ``--rm`` alone.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

from reclamo.config import RLMConfig
from reclamo.repl.base import LLMHandler
from reclamo.repl.process_repl import WORKER_PATH, ProcessREPL

DEFAULT_IMAGE = "python:3.12-slim"
SANDBOX_ROOT = Path("~/.cache/reclamo/sandbox").expanduser()


class DockerUnavailable(RuntimeError):
    """Docker is not installed, or the daemon is not running / not reachable."""


def check_docker(docker: str = "docker") -> None:
    """Raise ``DockerUnavailable`` with a clear message unless ``docker info`` works."""
    if shutil.which(docker) is None:
        raise DockerUnavailable(
            f"{docker!r} is not installed or not on PATH; install Docker or use "
            "--sandbox subprocess"
        )
    try:
        proc = subprocess.run(
            [docker, "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise DockerUnavailable("`docker info` timed out; is the Docker daemon running?") from None
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip().splitlines()
        tail = detail[-1] if detail else "no output"
        raise DockerUnavailable(
            f"the Docker daemon is not reachable (`docker info` failed: {tail}); start Docker "
            "or use --sandbox subprocess"
        )


class DockerREPL(ProcessREPL):
    def __init__(
        self,
        cfg: RLMConfig,
        llm_handler: LLMHandler,
        *,
        image: str | None = None,
        docker: str = "docker",
    ) -> None:
        super().__init__(cfg, llm_handler)
        self.image = image or cfg.docker_image or DEFAULT_IMAGE
        self._docker = docker
        self.container: str | None = None

    # --- hooks ------------------------------------------------------------

    def _make_scratch_dir(self) -> str:
        check_docker(self._docker)
        SANDBOX_ROOT.mkdir(parents=True, exist_ok=True)
        for p in (SANDBOX_ROOT.parent, SANDBOX_ROOT):
            os.chmod(p, 0o755)
        return tempfile.mkdtemp(prefix="run-", dir=SANDBOX_ROOT)

    def _context_written(self) -> None:
        assert self._tmp is not None
        os.chmod(self._tmp, 0o755)
        os.chmod(self.host_context_path, 0o644)

    def _worker_context_path(self) -> str:
        return f"/work/{self._context_file}"

    def run_args(self) -> list[str]:
        assert self._tmp is not None and self.container is not None
        cfg = self.cfg
        return [
            self._docker,
            "run",
            "-i",
            "--rm",
            "--name",
            self.container,
            "--network",
            "none",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,size=256m",
            "--memory",
            cfg.docker_memory,
            "--pids-limit",
            "256",
            "--cpus",
            f"{cfg.docker_cpus:g}",
            "--security-opt",
            "no-new-privileges",
            "--cap-drop",
            "ALL",
            "--user",
            "65534:65534",
            "-e",
            "LANG=C.UTF-8",
            "-e",
            "HOME=/tmp",
            "-v",
            f"{self._tmp}:/work:ro",
            "-v",
            f"{WORKER_PATH}:/reclamo/worker.py:ro",
            "-w",
            "/tmp",
            self.image,
            "python",
            "-I",
            "/reclamo/worker.py",
        ]

    def _popen(self) -> subprocess.Popen[str]:
        self.container = f"reclamo-{uuid.uuid4().hex[:12]}"
        return subprocess.Popen(
            self.run_args(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )

    def _kill_worker(self, proc: subprocess.Popen[str]) -> None:
        self._docker_kill()
        proc.kill()

    def _stop_worker(self, *, graceful: bool) -> None:
        super()._stop_worker(graceful=graceful)
        self._docker_kill()  # belt and braces: --rm is not enough if the CLI died first
        self.container = None

    def _docker_kill(self) -> None:
        if not self.container:
            return
        try:
            subprocess.run(
                [self._docker, "kill", self.container],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass


__all__ = ["DEFAULT_IMAGE", "DockerREPL", "DockerUnavailable", "check_docker"]
