"""Configuration: dataclasses, TOML profiles and API-key resolution.

Profiles are TOML tables under ``[profiles.<name>]``. The built-in ones live in
``BUILTIN_PROFILES_TOML`` below; a user file (``~/.config/reclamo/profiles.toml``
by default, or the path in ``RECLAMO_PROFILES``) can override fields of a
built-in profile or add new profiles. Two environment variables override any
profile at load time: ``RECLAMO_BASE_URL`` and ``RECLAMO_MODEL``.

The API key is never stored on the config. ``resolve_api_key`` reads it from the
environment variable named by ``api_key_env`` (default ``RECLAMO_API_KEY``) and,
failing that, from the stdout of ``api_key_cmd``.
"""

from __future__ import annotations

import dataclasses
import os
import shlex
import subprocess
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_API_KEY_ENV = "RECLAMO_API_KEY"
PROFILES_ENV = "RECLAMO_PROFILES"
BASE_URL_ENV = "RECLAMO_BASE_URL"
MODEL_ENV = "RECLAMO_MODEL"
DEFAULT_USER_PROFILES = Path("~/.config/reclamo/profiles.toml")

# Qwen3 sampling presets from the model card; top_k and min_p are non-standard
# parameters and travel to the server in the request body's top level via
# ``extra_body`` (see client.py).
BUILTIN_PROFILES_TOML = """
[profiles.pluto]
base_url = "http://pluto:8083/v1"
api_key_cmd = "pass pluto/flashnext-api-key"
concurrency = 1
context_tokens = 32768

[profiles.pluto.root]
model = "qwen3.8-flash-next"
max_tokens = 4096
enable_thinking = true
reasoning_effort = "medium"
sampling = { temperature = 0.6, top_p = 0.95, top_k = 20, min_p = 0.0 }

[profiles.pluto.sub]
model = "qwen3.8-flash-next"
max_tokens = 2048
enable_thinking = false
sampling = { temperature = 0.7, top_p = 0.8, top_k = 20, presence_penalty = 1.0 }

# Any OpenAI-compatible server. Point it somewhere with RECLAMO_BASE_URL and
# RECLAMO_MODEL; the key comes from RECLAMO_API_KEY.
[profiles.openai-compatible]
base_url = "http://localhost:8000/v1"
concurrency = 1
context_tokens = 32768

[profiles.openai-compatible.root]
model = "default"
max_tokens = 4096
enable_thinking = false
sampling = { temperature = 0.6, top_p = 0.95 }

[profiles.openai-compatible.sub]
model = "default"
max_tokens = 2048
enable_thinking = false
sampling = { temperature = 0.7, top_p = 0.8 }
"""


class ConfigError(ValueError):
    """A profile is missing, malformed, or names an unknown field."""


class APIKeyError(RuntimeError):
    """No API key could be resolved. The message never contains key material."""


@dataclass(kw_only=True)
class ModelConfig:
    """Per-role model settings. Roles are ``root`` (the RLM loop) and ``sub`` (llm_query)."""

    model: str
    max_tokens: int = 4096
    enable_thinking: bool = False
    reasoning_effort: str | None = None
    sampling: dict[str, Any] = field(default_factory=dict)
    timeout: float = 300.0  # seconds per request


@dataclass(kw_only=True)
class RLMConfig:
    """One resolved profile: endpoint, limits and the two role configs."""

    name: str = "custom"
    base_url: str
    api_key_env: str = DEFAULT_API_KEY_ENV
    api_key_cmd: str | None = None
    concurrency: int = 1
    context_tokens: int = 32768
    subcall_chars: int = 12_000
    max_iterations: int = 20
    max_depth: int = 1
    max_subcalls_per_run: int = 64
    max_subcalls_per_exec: int = 24
    output_truncate_chars: int = 2_000
    max_timeout: float = 1_800.0  # whole run, seconds
    exec_timeout: float = 120.0  # one REPL exec, seconds
    subcall_timeout: float = 300.0  # one llm_query/rlm_query, seconds
    max_errors: int = 3  # consecutive REPL errors before giving up
    max_tokens_total: int | None = None  # whole run, prompt + completion; None = no limit
    max_retries: int = 3  # HTTP retries per LM call
    retry_backoff: float = 1.0  # seconds; doubles each retry
    sft_log: bool = False  # also write sft.jsonl (one line per root turn)
    root: ModelConfig
    sub: ModelConfig

    def role(self, role: str) -> ModelConfig:
        if role == "root":
            return self.root
        if role == "sub":
            return self.sub
        raise ValueError(f"unknown role {role!r}; expected 'root' or 'sub'")

    @classmethod
    def from_dict(cls, name: str, data: Mapping[str, Any]) -> RLMConfig:
        data = dict(data)
        roles: dict[str, ModelConfig] = {}
        for role in ("root", "sub"):
            raw = data.pop(role, None)
            if not isinstance(raw, Mapping):
                raise ConfigError(f"profile {name!r}: missing [profiles.{name}.{role}] table")
            roles[role] = _build(ModelConfig, raw, f"profile {name!r} role {role!r}")
        if "base_url" not in data:
            raise ConfigError(f"profile {name!r}: base_url is required")
        return _build(cls, {"name": name, **data, **roles}, f"profile {name!r}")


def _build(kind: type, raw: Mapping[str, Any], where: str) -> Any:
    allowed = {f.name for f in dataclasses.fields(kind)}
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ConfigError(f"{where}: unknown field(s) {', '.join(unknown)}")
    try:
        return kind(**raw)
    except TypeError as exc:  # missing required field
        raise ConfigError(f"{where}: {exc}") from None


def _deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = dict(base)
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(out.get(key), Mapping):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _profiles_from_toml(text: str, where: str) -> dict[str, dict[str, Any]]:
    try:
        doc = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{where}: invalid TOML: {exc}") from None
    profiles = doc.get("profiles", {})
    if not isinstance(profiles, dict):
        raise ConfigError(f"{where}: [profiles] must be a table")
    return profiles


def load_profiles(
    user_file: str | os.PathLike[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Return raw profile tables: built-ins, deep-merged with the user file if present."""
    env = os.environ if env is None else env
    profiles = _profiles_from_toml(BUILTIN_PROFILES_TOML, "built-in profiles")
    if user_file is None:
        user_file = env.get(PROFILES_ENV) or DEFAULT_USER_PROFILES
    path = Path(user_file).expanduser()
    if path.is_file():
        user_profiles = _profiles_from_toml(path.read_text(encoding="utf-8"), str(path))
        for name, table in user_profiles.items():
            profiles[name] = _deep_merge(profiles.get(name, {}), table)
    return profiles


def load_config(
    profile: str = "pluto",
    user_file: str | os.PathLike[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> RLMConfig:
    """Resolve one profile to an ``RLMConfig``, applying env overrides."""
    env = os.environ if env is None else env
    profiles = load_profiles(user_file, env=env)
    if profile not in profiles:
        known = ", ".join(sorted(profiles))
        raise ConfigError(f"unknown profile {profile!r}; available: {known}")
    table = dict(profiles[profile])
    if env.get(BASE_URL_ENV):
        table["base_url"] = env[BASE_URL_ENV]
    if env.get(MODEL_ENV):
        for role in ("root", "sub"):
            table[role] = {**table.get(role, {}), "model": env[MODEL_ENV]}
    return RLMConfig.from_dict(profile, table)


def resolve_api_key(
    cfg: RLMConfig,
    *,
    env: Mapping[str, str] | None = None,
    run: Any = subprocess.run,
) -> str:
    """Return the API key from ``cfg.api_key_env``, else from ``cfg.api_key_cmd``.

    ``run`` is ``subprocess.run`` by default and is injectable for tests. The key is
    returned to the caller only; it is not logged, cached on ``cfg`` or echoed in
    any exception text.
    """
    env = os.environ if env is None else env
    key = (env.get(cfg.api_key_env) or "").strip()
    if key:
        return key

    if not cfg.api_key_cmd:
        raise APIKeyError(
            f"no API key: set {cfg.api_key_env}, or add api_key_cmd to profile {cfg.name!r}"
        )

    argv = shlex.split(cfg.api_key_cmd)
    try:
        proc = run(argv, capture_output=True, text=True, timeout=30, check=False)
    except FileNotFoundError:
        raise APIKeyError(
            f"no API key: {cfg.api_key_env} is unset and the command {argv[0]!r} "
            f"from api_key_cmd was not found"
        ) from None
    except subprocess.TimeoutExpired:
        raise APIKeyError(
            f"no API key: {cfg.api_key_env} is unset and api_key_cmd timed out after 30s"
        ) from None
    if proc.returncode != 0:
        detail = (proc.stderr or "").strip().splitlines()
        tail = f": {detail[-1]}" if detail else ""
        raise APIKeyError(
            f"no API key: {cfg.api_key_env} is unset and api_key_cmd "
            f"({cfg.api_key_cmd!r}) exited {proc.returncode}{tail}"
        )
    key = (proc.stdout or "").strip().splitlines()
    if not key or not key[0].strip():
        raise APIKeyError(
            f"no API key: {cfg.api_key_env} is unset and api_key_cmd "
            f"({cfg.api_key_cmd!r}) printed nothing"
        )
    return key[0].strip()
