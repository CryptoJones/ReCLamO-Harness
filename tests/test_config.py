from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from reclamo.config import (
    APIKeyError,
    ConfigError,
    ModelConfig,
    RLMConfig,
    load_config,
    load_profiles,
    resolve_api_key,
)

NO_ENV: dict[str, str] = {}


def test_builtin_pluto_profile() -> None:
    cfg = load_config("pluto", user_file="/nonexistent/profiles.toml", env=NO_ENV)
    assert cfg.name == "pluto"
    assert cfg.base_url == "http://pluto:8083/v1"
    assert cfg.api_key_env == "RECLAMO_API_KEY"
    assert cfg.api_key_cmd == "pass pluto/flashnext-api-key"
    assert cfg.concurrency == 2  # Strata "parallel": 2 since 2026-10-08
    assert cfg.context_tokens == 32768
    assert cfg.subcall_chars is None and cfg.prompt_version == "v0.2"
    # (32,768 - 4,096) tokens * 0.85 * 3 chars/token
    assert cfg.effective_subcall_chars == 73_113
    # v0.2 defaults (issue #61)
    assert (cfg.max_iterations, cfg.max_depth) == (30, 1)
    assert (cfg.max_subcalls_per_run, cfg.max_subcalls_per_exec) == (256, 64)
    assert cfg.output_truncate_chars == 20_000
    assert cfg.max_timeout == 3_600.0
    assert (cfg.root.max_tokens, cfg.sub.max_tokens) == (8_192, 4_096)
    assert cfg.root.model == "qwen3.8-flash-next"
    assert cfg.root.enable_thinking is True
    assert cfg.root.sampling == {"temperature": 0.6, "top_p": 0.95, "top_k": 20, "min_p": 0.0}
    assert cfg.sub.enable_thinking is False
    assert cfg.sub.sampling["presence_penalty"] == 1.0


def test_prompt_v01_reproduces_the_published_defaults() -> None:
    import dataclasses

    cfg = load_config("pluto", user_file="/nonexistent/profiles.toml", env=NO_ENV)
    old = dataclasses.replace(cfg, prompt_version="v0.1")
    assert (old.max_iterations, old.output_truncate_chars, old.max_timeout) == (20, 2_000, 1_800.0)
    assert (old.max_subcalls_per_run, old.max_subcalls_per_exec) == (64, 24)
    assert (old.root.max_tokens, old.sub.max_tokens) == (4_096, 2_048)
    assert (old.root.timeout, old.sub.timeout) == (300.0, 300.0)
    assert old.effective_subcall_chars == 12_000
    # and back again
    again = dataclasses.replace(old, prompt_version="v0.2")
    assert (again.max_iterations, again.root.max_tokens) == (30, 8_192)


def test_explicit_values_beat_the_version_defaults(tmp_path) -> None:
    import dataclasses

    user = tmp_path / "p.toml"
    user.write_text(
        "[profiles.pluto]\nmax_iterations = 12\n[profiles.pluto.root]\nmax_tokens = 6000\n"
    )
    cfg = load_config("pluto", user_file=user, env=NO_ENV)
    assert (cfg.max_iterations, cfg.root.max_tokens, cfg.output_truncate_chars) == (
        12,
        6_000,
        20_000,
    )
    old = dataclasses.replace(cfg, prompt_version="v0.1")
    assert (old.max_iterations, old.root.max_tokens, old.output_truncate_chars) == (
        12,
        6_000,
        2_000,
    )
    # an explicit change made with replace is kept too
    assert dataclasses.replace(cfg, max_timeout=900.0).max_timeout == 900.0


def test_root_max_tokens_follows_thinking() -> None:
    import dataclasses

    cfg = load_config("pluto", user_file="/nonexistent/profiles.toml", env=NO_ENV)
    off = dataclasses.replace(cfg, root=dataclasses.replace(cfg.root, enable_thinking=False))
    assert off.root.max_tokens == 4_096 and cfg.root.max_tokens == 8_192
    assert "defaults_resolved" not in repr(cfg)


def test_defaults_resolved_is_not_a_profile_key(tmp_path) -> None:
    user = tmp_path / "p.toml"
    user.write_text("[profiles.pluto]\ndefaults_resolved = {}\n")
    with pytest.raises(ConfigError, match="unknown field"):
        load_config("pluto", user_file=user, env=NO_ENV)


def test_builtin_pluto_long_profile() -> None:
    cfg = load_config("pluto-long", user_file="/nonexistent/profiles.toml", env=NO_ENV)
    pluto = load_config("pluto", user_file="/nonexistent/profiles.toml", env=NO_ENV)
    assert cfg.context_tokens == 131_072 and cfg.concurrency == 2
    assert cfg.root.timeout >= 1_800 and cfg.sub.timeout >= 1_800
    assert (cfg.base_url, cfg.api_key_cmd) == (pluto.base_url, pluto.api_key_cmd)
    for role in ("root", "sub"):
        a, b = cfg.role(role), pluto.role(role)
        assert (a.model, a.sampling, a.enable_thinking, a.max_tokens) == (
            b.model, b.sampling, b.enable_thinking, b.max_tokens,
        )  # fmt: skip
    assert pluto.context_tokens == 32_768  # pluto's window unchanged
    assert (pluto.root.timeout, pluto.sub.timeout) == (900.0, 900.0)  # v0.2 default
    assert cfg.max_iterations == pluto.max_iterations == 30


def test_builtin_openai_compatible_profile() -> None:
    cfg = load_config("openai-compatible", user_file="/nonexistent", env=NO_ENV)
    assert cfg.base_url == "http://localhost:8000/v1"
    assert cfg.api_key_cmd is None
    assert cfg.root.enable_thinking is False


def test_env_overrides_base_url_and_model() -> None:
    env = {"RECLAMO_BASE_URL": "http://box:1234/v1", "RECLAMO_MODEL": "other"}
    cfg = load_config("openai-compatible", user_file="/nonexistent", env=env)
    assert cfg.base_url == "http://box:1234/v1"
    assert cfg.root.model == "other" and cfg.sub.model == "other"


def test_user_file_overrides_and_adds(tmp_path: Path) -> None:
    user = tmp_path / "profiles.toml"
    user.write_text(
        """
[profiles.pluto]
concurrency = 2
[profiles.pluto.sub]
max_tokens = 512

[profiles.lab]
base_url = "http://lab:9000/v1"
[profiles.lab.root]
model = "m-root"
[profiles.lab.sub]
model = "m-sub"
""",
        encoding="utf-8",
    )
    pluto = load_config("pluto", user_file=user, env=NO_ENV)
    assert pluto.concurrency == 2
    assert pluto.sub.max_tokens == 512
    assert pluto.sub.model == "qwen3.8-flash-next"  # deep merge keeps the rest
    assert pluto.root.sampling["top_k"] == 20

    lab = load_config("lab", user_file=user, env=NO_ENV)
    assert lab.base_url == "http://lab:9000/v1"
    assert lab.root.model == "m-root" and lab.sub.model == "m-sub"
    assert lab.max_depth == 1  # defaults apply


def test_user_file_via_env(tmp_path: Path) -> None:
    user = tmp_path / "p.toml"
    user.write_text("[profiles.pluto]\ncontext_tokens = 8192\n", encoding="utf-8")
    cfg = load_config("pluto", env={"RECLAMO_PROFILES": str(user)})
    assert cfg.context_tokens == 8192


def test_unknown_profile_lists_available() -> None:
    with pytest.raises(ConfigError, match="unknown profile 'nope'; available: .*pluto"):
        load_config("nope", user_file="/nonexistent", env=NO_ENV)


def test_unknown_field_is_an_error(tmp_path: Path) -> None:
    user = tmp_path / "p.toml"
    user.write_text("[profiles.pluto]\nconcurency = 2\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="unknown field.*concurency"):
        load_config("pluto", user_file=user, env=NO_ENV)


def test_missing_role_table_is_an_error() -> None:
    with pytest.raises(ConfigError, match=r"missing \[profiles.x.sub\]"):
        RLMConfig.from_dict("x", {"base_url": "u", "root": {"model": "m"}})


def test_missing_base_url_is_an_error() -> None:
    with pytest.raises(ConfigError, match="base_url is required"):
        RLMConfig.from_dict("x", {"root": {"model": "m"}, "sub": {"model": "m"}})


def test_invalid_toml_is_an_error(tmp_path: Path) -> None:
    user = tmp_path / "p.toml"
    user.write_text("[profiles.pluto\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="invalid TOML"):
        load_profiles(user, env=NO_ENV)


# --- key resolution ---------------------------------------------------------


def _cfg(**kw: Any) -> RLMConfig:
    base = {
        "name": "t",
        "base_url": "http://x/v1",
        "root": ModelConfig(model="m"),
        "sub": ModelConfig(model="m"),
    }
    base.update(kw)
    return RLMConfig(**base)


def test_env_var_wins_over_cmd() -> None:
    cfg = _cfg(api_key_cmd="false")
    assert resolve_api_key(cfg, env={"RECLAMO_API_KEY": " sk-env \n"}) == "sk-env"


def test_custom_api_key_env_name() -> None:
    cfg = _cfg(api_key_env="MY_KEY")
    assert resolve_api_key(cfg, env={"MY_KEY": "sk-mine"}) == "sk-mine"


def test_cmd_used_when_env_unset() -> None:
    py = sys.executable
    cfg = _cfg(api_key_cmd=f"\"{py}\" -c \"print('sk-from-cmd'); print('second line')\"")
    assert resolve_api_key(cfg, env=NO_ENV) == "sk-from-cmd"


def test_pluto_profile_invokes_pass_with_expected_argv() -> None:
    cfg = load_config("pluto", user_file="/nonexistent", env=NO_ENV)
    seen: list[list[str]] = []

    def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        seen.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="sk-pass\n", stderr="")

    assert resolve_api_key(cfg, env=NO_ENV, run=fake_run) == "sk-pass"
    assert seen == [["pass", "pluto/flashnext-api-key"]]


def test_no_env_and_no_cmd_is_clear() -> None:
    with pytest.raises(APIKeyError, match="set RECLAMO_API_KEY, or add api_key_cmd"):
        resolve_api_key(_cfg(), env=NO_ENV)


def test_cmd_failure_is_clear_and_does_not_leak() -> None:
    cfg = _cfg(api_key_cmd="pass pluto/flashnext-api-key")

    def failing_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            argv, 2, stdout="", stderr="gpg: decryption failed: No secret key\n"
        )

    with pytest.raises(APIKeyError) as exc:
        resolve_api_key(cfg, env=NO_ENV, run=failing_run)
    msg = str(exc.value)
    assert "RECLAMO_API_KEY is unset" in msg
    assert "exited 2" in msg and "No secret key" in msg


def test_cmd_not_found_is_clear() -> None:
    cfg = _cfg(api_key_cmd="definitely-not-a-real-binary-xyz arg")
    with pytest.raises(APIKeyError, match="was not found"):
        resolve_api_key(cfg, env=NO_ENV)


def test_cmd_prints_nothing_is_clear() -> None:
    cfg = _cfg(api_key_cmd=f'"{sys.executable}" -c "pass"')
    with pytest.raises(APIKeyError, match="printed nothing"):
        resolve_api_key(cfg, env=NO_ENV)
