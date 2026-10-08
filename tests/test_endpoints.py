"""Per-role endpoints (#36): root and sub on different servers, keys and semaphores."""

from __future__ import annotations

import dataclasses
import json
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from reclamo.cli import main
from reclamo.client import LMClient
from reclamo.config import (
    BUILTIN_PROFILES_TOML,
    APIKeyError,
    ConfigError,
    ModelConfig,
    RLMConfig,
    load_config,
    resolve_api_key,
    resolve_api_keys,
)
from tests.conftest import FakeServer, chat_response, make_config

KEY_A = "sk-root-SECRET-aaaa"
KEY_B = "sk-sub-SECRET-bbbb"
NO_ENV: dict[str, str] = {}
MSG = [{"role": "user", "content": "q"}]


def _two_endpoint_cfg(a: FakeServer, b: FakeServer, **overrides: Any) -> RLMConfig:
    cfg = make_config(a.base_url, **overrides)
    sub = dataclasses.replace(cfg.sub, model="sub-model", base_url=b.base_url)
    root = dataclasses.replace(cfg.root, model="root-model")
    return dataclasses.replace(cfg, root=root, sub=sub)


def _posts(server: FakeServer) -> list[Any]:
    return [r for r in server.requests if r.method == "POST"]


def _write_profiles(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "profiles.toml"
    p.write_text(text, encoding="utf-8")
    return p


def _split_profile(tmp_path: Path, a: str, b: str, *, extra: str = "") -> Path:
    """Profile-level endpoint = b (the reader); root overrides to a (the planner)."""
    return _write_profiles(
        tmp_path,
        f"""
[profiles.split]
base_url = "{b}"
api_key_env = "SUB_KEY"
max_iterations = 4
{extra}
[profiles.split.root]
base_url = "{a}"
api_key_env = "ROOT_KEY"
model = "root-model"
enable_thinking = true
[profiles.split.sub]
model = "sub-model"
""",
    )


# --- config: inheritance and validation ----------------------------------------


def test_builtin_pluto_is_one_shared_endpoint() -> None:
    cfg = load_config("pluto", user_file="/nonexistent", env=NO_ENV)
    (ep,) = cfg.endpoints()
    assert ep.base_url == "http://pluto:8083/v1"
    assert ep.roles == ("root", "sub")
    assert ep.concurrency == 1
    assert ep.api_key_env == "RECLAMO_API_KEY"
    assert ep.api_key_cmd == "pass pluto/flashnext-api-key"
    assert cfg.endpoint("root") == cfg.endpoint("sub") == ep


def test_unset_role_fields_inherit_profile(tmp_path: Path) -> None:
    profiles = _split_profile(tmp_path, "http://a/v1", "http://b/v1", extra="concurrency = 3")
    cfg = load_config("split", profiles, env=NO_ENV)
    root, sub = cfg.endpoint("root"), cfg.endpoint("sub")
    assert (root.base_url, root.api_key_env, root.concurrency) == ("http://a/v1", "ROOT_KEY", 3)
    assert (sub.base_url, sub.api_key_env, sub.concurrency) == ("http://b/v1", "SUB_KEY", 3)
    assert [ep.roles for ep in cfg.endpoints()] == [("root",), ("sub",)]


def test_role_concurrency_and_key_cmd_override(tmp_path: Path) -> None:
    profiles = _write_profiles(
        tmp_path,
        """
[profiles.p]
base_url = "http://b/v1"
api_key_cmd = "pass shared"
[profiles.p.root]
model = "m"
base_url = "http://a/v1"
api_key_cmd = "pass local"
concurrency = 4
[profiles.p.sub]
model = "m"
""",
    )
    cfg = load_config("p", profiles, env=NO_ENV)
    assert cfg.endpoint("root").api_key_cmd == "pass local"
    assert cfg.endpoint("root").concurrency == 4
    assert cfg.endpoint("sub").api_key_cmd == "pass shared"
    assert cfg.endpoint("sub").concurrency == 1


def test_roles_sharing_a_url_must_agree() -> None:
    with pytest.raises(ConfigError, match="share base_url"):
        make_config("http://x/v1", root=ModelConfig(model="m", api_key_env="OTHER"))
    with pytest.raises(ConfigError, match="share base_url"):
        make_config("http://x/v1", sub=ModelConfig(model="m", concurrency=2))
    # naming the profile URL explicitly on a role is the same endpoint
    cfg = make_config("http://x/v1", sub=ModelConfig(model="m", base_url="http://x/v1"))
    assert len(cfg.endpoints()) == 1


def test_reclamo_base_url_collapses_role_urls(tmp_path: Path) -> None:
    profiles = _split_profile(tmp_path, "http://a/v1", "http://b/v1")
    # one URL for everything; give the roles one key source so they agree
    profiles.write_text(profiles.read_text().replace('api_key_env = "ROOT_KEY"\n', ""))
    cfg = load_config("split", profiles, env={"RECLAMO_BASE_URL": "http://only/v1"})
    (ep,) = cfg.endpoints()
    assert ep.base_url == "http://only/v1" and ep.roles == ("root", "sub")


def test_resolve_api_keys_per_endpoint(tmp_path: Path) -> None:
    profiles = _split_profile(tmp_path, "http://a/v1", "http://b/v1")
    cfg = load_config("split", profiles, env=NO_ENV)
    keys = resolve_api_keys(cfg, env={"ROOT_KEY": KEY_A, "SUB_KEY": KEY_B})
    assert keys == {"http://a/v1": KEY_A, "http://b/v1": KEY_B}


def test_endpoint_key_error_names_endpoint_not_key(tmp_path: Path) -> None:
    profiles = _split_profile(tmp_path, "http://a/v1", "http://b/v1")
    cfg = load_config("split", profiles, env=NO_ENV)
    with pytest.raises(APIKeyError, match=r"set ROOT_KEY.*endpoint http://a/v1") as exc:
        resolve_api_key(cfg.endpoint("root"), env={"SUB_KEY": KEY_B})
    assert KEY_B not in str(exc.value)


# --- client: routing, keys, concurrency ----------------------------------------


def test_root_hits_a_and_sub_hits_b(fake_server: FakeServer, fake_server_b: FakeServer) -> None:
    cfg = _two_endpoint_cfg(fake_server, fake_server_b)
    keys = {fake_server.base_url: KEY_A, fake_server_b.base_url: KEY_B}
    client = LMClient(cfg, keys, sleep=lambda _s: None)
    r = client.complete(MSG, "root")
    s = client.complete(MSG, "sub")

    (pa,), (pb,) = _posts(fake_server), _posts(fake_server_b)
    assert pa.body["model"] == "root-model" and pa.headers["authorization"] == f"Bearer {KEY_A}"
    assert pb.body["model"] == "sub-model" and pb.headers["authorization"] == f"Bearer {KEY_B}"
    assert pa.body["chat_template_kwargs"]["enable_thinking"] is True
    assert pb.body["chat_template_kwargs"]["enable_thinking"] is False
    assert r.endpoint == fake_server.base_url and s.endpoint == fake_server_b.base_url
    assert client.calls == 2
    assert KEY_A not in repr(client) and KEY_B not in repr(client)


def test_single_key_string_still_works_and_resolves_role_keys(
    fake_server: FakeServer, fake_server_b: FakeServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = _two_endpoint_cfg(fake_server, fake_server_b)
    cfg = dataclasses.replace(cfg, sub=dataclasses.replace(cfg.sub, api_key_env="SUB_KEY"))
    monkeypatch.setenv("SUB_KEY", KEY_B)
    client = LMClient(cfg, KEY_A, sleep=lambda _s: None)  # profile-level key only
    client.complete(MSG, "root")
    client.complete(MSG, "sub")
    assert _posts(fake_server)[0].headers["authorization"] == f"Bearer {KEY_A}"
    assert _posts(fake_server_b)[0].headers["authorization"] == f"Bearer {KEY_B}"


def test_list_models_per_role(fake_server: FakeServer, fake_server_b: FakeServer) -> None:
    fake_server.models, fake_server_b.models = ["planner"], ["reader"]
    client = LMClient(_two_endpoint_cfg(fake_server, fake_server_b), KEY_A)
    assert client.list_models("root") == ["planner"]
    assert client.list_models("sub") == ["reader"]


def _bg(client: LMClient, role: str) -> threading.Thread:
    t = threading.Thread(target=client.complete, args=(MSG, role), daemon=True)
    t.start()
    return t


def test_sub_not_serialised_behind_root_on_another_host(
    fake_server: FakeServer, fake_server_b: FakeServer
) -> None:
    fake_server.gate = threading.Event()  # the root's server holds every request
    client = LMClient(_two_endpoint_cfg(fake_server, fake_server_b), KEY_A)
    root = _bg(client, "root")
    assert fake_server.entered.wait(5)
    started = time.monotonic()
    client.complete(MSG, "sub")  # would wait for the gate behind a shared semaphore
    assert time.monotonic() - started < 5
    assert root.is_alive()
    fake_server.gate.set()
    root.join(5)
    assert not root.is_alive()


def test_same_endpoint_roles_share_one_semaphore(fake_server: FakeServer) -> None:
    fake_server.gate = threading.Event()
    client = LMClient(make_config(fake_server.base_url, concurrency=1), KEY_A)
    root = _bg(client, "root")
    assert fake_server.entered.wait(5)
    sub = _bg(client, "sub")
    time.sleep(0.2)
    assert len(_posts(fake_server)) == 1  # sub waits for the root call to finish
    fake_server.gate.set()
    root.join(5)
    sub.join(5)
    assert len(_posts(fake_server)) == 2
    assert fake_server.max_in_flight == 1


def test_max_in_flight_is_per_endpoint(fake_server: FakeServer, fake_server_b: FakeServer) -> None:
    fake_server.handler_delay = fake_server_b.handler_delay = 0.1
    cfg = _two_endpoint_cfg(fake_server, fake_server_b, concurrency=1)
    cfg = dataclasses.replace(cfg, sub=dataclasses.replace(cfg.sub, concurrency=2))
    client = LMClient(cfg, KEY_A)
    threads = [_bg(client, role) for role in ("root", "sub") * 4]
    for t in threads:
        t.join(10)
    assert len(_posts(fake_server)) == 4 and len(_posts(fake_server_b)) == 4
    assert fake_server.max_in_flight == 1
    assert fake_server_b.max_in_flight == 2


# --- CLI: run logs, ping ---------------------------------------------------------


def test_run_logs_endpoint_and_model_per_call(
    fake_server: FakeServer,
    fake_server_b: FakeServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("ROOT_KEY", KEY_A)
    monkeypatch.setenv("SUB_KEY", KEY_B)
    fake_server.script(
        chat_response('```repl\nprint(llm_query("what is it?"))\n```', model="root-served"),
        chat_response("FINAL(done)", model="root-served"),
    )
    fake_server_b.script(chat_response("a greeting", model="sub-served"))
    profiles = _split_profile(tmp_path, fake_server.base_url, fake_server_b.base_url)
    ctx = tmp_path / "ctx.txt"
    ctx.write_text("hello world\n", encoding="utf-8")
    log_dir = tmp_path / "runs"
    argv = ["run", "--profile", "split", "--profiles", str(profiles), "--context", str(ctx)]
    rc = main([*argv, "-q", "What is it?", "--log-dir", str(log_dir), "--json"])
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert json.loads(captured.out)["answer"] == "done"
    assert len(_posts(fake_server)) == 2 and len(_posts(fake_server_b)) == 1

    (log,) = log_dir.glob("*.jsonl")
    text = log.read_text(encoding="utf-8")
    for key in (KEY_A, KEY_B):
        assert key not in text
        assert key not in captured.out and key not in captured.err
    records = [json.loads(line) for line in text.splitlines()]
    meta = next(r for r in records if r["type"] == "metadata")
    assert [(e["base_url"], e["roles"]) for e in meta["endpoints"]] == [
        (fake_server.base_url, ["root"]),
        (fake_server_b.base_url, ["sub"]),
    ]
    turns = [r for r in records if r["type"] == "iteration"]
    assert [(t["endpoint"], t["model"]) for t in turns] == [
        (fake_server.base_url, "root-served")
    ] * 2
    (sub,) = [r for r in records if r["type"] == "subcall"]
    assert (sub["endpoint"], sub["model"]) == (fake_server_b.base_url, "sub-served")


def test_ping_reports_every_endpoint(
    fake_server: FakeServer,
    fake_server_b: FakeServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("ROOT_KEY", KEY_A)
    monkeypatch.setenv("SUB_KEY", KEY_B)
    fake_server.models, fake_server_b.models = ["planner"], ["reader"]
    fake_server.script(
        chat_response("pong", model="planner"),
        chat_response("pong", reasoning_content="hmm", model="planner"),
    )
    fake_server_b.script(chat_response("pong", model="reader"))
    profiles = _split_profile(tmp_path, fake_server.base_url, fake_server_b.base_url)

    assert main(["ping", "--profile", "split", "--profiles", str(profiles)]) == 0
    captured = capsys.readouterr()
    out = captured.out
    assert f"base_url: {fake_server.base_url}\nroles:    root\nmodels:   planner" in out
    assert f"base_url: {fake_server_b.base_url}\nroles:    sub\nmodels:   reader" in out
    assert "model:    planner" in out and "model:    reader" in out
    assert out.count("thinking: yes") == 1  # only the root's endpoint gets the thinking probe
    assert len(_posts(fake_server)) == 2 and len(_posts(fake_server_b)) == 1
    assert _posts(fake_server)[0].headers["authorization"] == f"Bearer {KEY_A}"
    assert _posts(fake_server_b)[0].headers["authorization"] == f"Bearer {KEY_B}"
    for key in (KEY_A, KEY_B):
        assert key not in out and key not in captured.err


def test_ping_one_endpoint_down_exits_1_but_reports_both(
    fake_server: FakeServer,
    fake_server_b: FakeServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("ROOT_KEY", KEY_A)
    monkeypatch.setenv("SUB_KEY", KEY_B)
    fake_server.script(401)
    profiles = _split_profile(tmp_path, fake_server.base_url, fake_server_b.base_url)
    assert main(["ping", "--profile", "split", "--profiles", str(profiles)]) == 1
    captured = capsys.readouterr()
    assert "request failed: AuthenticationError" in captured.err
    assert f"[{fake_server.base_url}]" in captured.err
    assert f"base_url: {fake_server_b.base_url}" in captured.out
    assert "reply:    'ok'" in captured.out  # the reader endpoint still answered


def test_readme_planner_8b_example_parses(tmp_path: Path) -> None:
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    block = next(b for b in readme.split("```toml\n")[1:] if "[profiles.planner-8b]" in b)
    profiles = _write_profiles(tmp_path, block.split("```")[0])
    cfg = load_config("planner-8b", profiles, env=NO_ENV)
    root, sub = cfg.endpoint("root"), cfg.endpoint("sub")
    assert (root.base_url, cfg.root.model) == ("http://localhost:8080/v1", "qwen3-8b-rlm")
    assert root.api_key_env == "RECLAMO_PLANNER_API_KEY"
    assert (sub.base_url, cfg.sub.model) == ("http://pluto:8083/v1", "qwen3.8-flash-next")
    assert (sub.api_key_cmd, sub.concurrency) == ("pass pluto/flashnext-api-key", 1)
    assert "planner-8b" not in BUILTIN_PROFILES_TOML  # documented, not built in


def test_readme_rlm_qwen3_8b_example_parses(tmp_path: Path) -> None:
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    block = next(b for b in readme.split("```toml\n")[1:] if "[profiles.rlm-qwen3-8b]" in b)
    profiles = _write_profiles(tmp_path, block.split("```")[0])
    cfg = load_config("rlm-qwen3-8b", profiles, env=NO_ENV)
    assert cfg.planner_style == "upstream-rlm-v0" and cfg.protocol == "fence"
    assert cfg.output_truncate_chars == 20_000
    root, sub = cfg.endpoint("root"), cfg.endpoint("sub")
    assert (root.base_url, cfg.root.enable_thinking) == ("http://localhost:8080/v1", False)
    assert cfg.root.sampling == {"temperature": 0.7, "top_p": 0.8, "top_k": 20, "min_p": 0.0}
    assert (sub.base_url, cfg.sub.model) == ("http://pluto:8083/v1", "qwen3.8-flash-next")
    assert "rlm-qwen3-8b" not in BUILTIN_PROFILES_TOML
