"""Read-only account authority and real caller provenance for model_map."""
import base64
import json
from types import SimpleNamespace

import pytest

from tools.delegate_tool_routes import _route_to_task_route
from tests.agent.test_delegation_fallback_authority import route_config


def test_chainless_option_keeps_implicit_auth_and_disables_inherited_fallback():
    from tools.delegate_tool_config import _resolve_child_fallback_chain
    route, cfg = route_config("repository_scout", [])
    route.pop("api_key")
    cfg["backends"]["model_map"]["options"][0].pop("api_key")
    cfg["fallback_providers"] = [{"provider": "custom", "model": "unapproved"}]
    resolved = _route_to_task_route(route, SimpleNamespace(), {}, cfg, "model_map")
    assert _resolve_child_fallback_chain(SimpleNamespace(), resolved.routing_cfg, True) == []


def codex_token(account="fixture-account", subject="fixture-subject", generation=1):
    payload = {"sub": subject, "exp": 4102444800, "generation": generation,
               "https://api.openai.com/auth": {"chatgpt_account_id": account}}
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"fixture.{encoded}.signature"


@pytest.fixture
def codex_store(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    from pathlib import Path
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    path = tmp_path / "auth.json"

    def write(token, pool=None):
        path.write_text(json.dumps({"providers": {"openai-codex": {
            "tokens": {"access_token": token, "refresh_token": "fixture-refresh"}}},
            "credential_pool": {"openai-codex": pool or []}}))
    write(codex_token())
    return path, write


def codex_route():
    chain = [{"provider": "custom", "model": "gemini-backup", "base_url": "http://127.0.0.1:10/v1",
              "api_key": "fixture-backup", "reasoning_effort": "medium"}]
    _, cfg = route_config("implementation", chain)
    primary = {"provider": "openai-codex", "model": "gpt-fixture", "reasoning_effort": "high"}
    option = cfg["backends"]["model_map"]["options"][0]
    option.clear()
    option.update(name="implementation", **primary, fallback_providers=chain)
    return {**primary, "label": "implementation", "fallback_providers": chain}, cfg


def test_codex_primary_readonly_binding_accepts_same_principal_rotation(codex_store, monkeypatch):
    from agent.delegation_fallback import install_policy
    from tools.delegate_tool_config import _resolve_child_fallback_chain
    from hermes_cli import auth_codex
    path, write = codex_store
    resolve = auth_codex.resolve_codex_runtime_credentials
    calls = []

    def readonly(**kwargs):
        calls.append(kwargs)
        assert kwargs == {"read_only": True}
        return resolve(**kwargs)

    monkeypatch.setattr(auth_codex, "resolve_codex_runtime_credentials", readonly)
    before = path.read_bytes()
    route, cfg = codex_route()
    resolved = _route_to_task_route(route, SimpleNamespace(), {}, cfg, "model_map")
    assert path.read_bytes() == before
    assert not path.with_name("auth.lock").exists()
    envelope = _resolve_child_fallback_chain(SimpleNamespace(), resolved.routing_cfg, True)
    rotated = codex_token(generation=2)
    write(rotated)
    agent = SimpleNamespace(provider="openai-codex", model="gpt-fixture",
                            base_url=resolved.creds["base_url"], api_key=rotated,
                            _client_kwargs={"default_headers": {"ChatGPT-Account-ID": "fixture-account"}})
    install_policy(agent, envelope)
    assert calls
    assert "signature" not in repr(envelope.policy)


def test_codex_explicit_raw_client_does_not_select_or_mutate_pool(monkeypatch):
    from agent import auxiliary_client

    def forbid(*args, **kwargs):
        pytest.fail("An explicitly bound credential must not select/refresh a pool")

    monkeypatch.setattr(auxiliary_client, "_select_pool_entry", forbid)
    monkeypatch.setattr(auxiliary_client, "_create_openai_client", lambda **kw: SimpleNamespace(
        api_key=kw["api_key"], base_url=kw["base_url"], default_headers=kw["default_headers"], close=lambda: None))
    token = codex_token()
    client, model = auxiliary_client.resolve_provider_client(
        "openai-codex", model="gpt-fixture", raw_codex=True,
        explicit_api_key=token, explicit_base_url="https://chatgpt.com/backend-api/codex")
    try:
        assert client.api_key == token
        assert client.default_headers["ChatGPT-Account-ID"] == "fixture-account"
        assert model == "gpt-fixture"
    finally:
        if client is not None:
            client.close()


@pytest.mark.parametrize("other", [codex_token(subject="other-subject"), "unknown-principal"])
def test_codex_rejects_ambiguous_multiple_principals(codex_store, other):
    _, write = codex_store
    write(codex_token(), [{"id": "other", "access_token": other}])
    route, cfg = codex_route()
    with pytest.raises(ValueError, match="ambiguous.*principal"):
        _route_to_task_route(route, SimpleNamespace(), {}, cfg, "model_map")


def test_haiku_fallback_uses_existing_borrowed_login_without_pool_or_refresh(tmp_path, monkeypatch):
    from agent import anthropic_credentials, auxiliary_client
    from agent.route_binding import bind_route_entry
    from agent.agent_init_fallback import _init_fallback_chain
    from tools.delegate_tool_config import _resolve_child_fallback_chain
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    from pathlib import Path
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    claude = tmp_path / ".claude"
    claude.mkdir()
    path = claude / ".credentials.json"
    path.write_text(json.dumps({"claudeAiOauth": {"accessToken": "sk-ant-oat01-fixture", "expiresAt": 4102444800000}}))
    monkeypatch.setattr(anthropic_credentials, "adopt_external_logins_enabled", lambda: True, raising=False)
    chain = [{"provider": "anthropic", "model": "claude-haiku-4-5", "reasoning_effort": "low"}]
    route, cfg = route_config("maintenance", chain)
    resolved = _route_to_task_route(route, SimpleNamespace(), {}, cfg, "model_map")
    envelope = _resolve_child_fallback_chain(SimpleNamespace(), resolved.routing_cfg, True)
    agent = SimpleNamespace(provider=route["provider"], model=route["model"], base_url=route["base_url"],
                            api_key=route["api_key"], _credential_pool=None, _credential_pool_entry_id=None, quiet_mode=True)
    _init_fallback_chain(agent, envelope)
    agent._fallback_index = 1
    captured = []

    def resolve(provider, model, **kwargs):
        captured.append(kwargs)
        return SimpleNamespace(base_url=kwargs["explicit_base_url"], api_key=kwargs["explicit_api_key"]), model

    monkeypatch.setattr(auxiliary_client, "resolve_provider_client", resolve)
    before = path.read_bytes()
    # Stop immediately AFTER account validation and before installing the native client.
    monkeypatch.setattr("agent.client_lifecycle._swap_fallback_clients", lambda *a: (_ for _ in ()).throw(RuntimeError("validated")))
    with pytest.raises(RuntimeError, match="validated"):
        bind_route_entry(agent, chain[0], "anthropic", chain[0]["model"])
    assert captured[0]["explicit_api_key"] == "sk-ant-oat01-fixture"
    assert captured[0]["explicit_base_url"].rstrip("/") == "https://api.anthropic.com"
    assert path.read_bytes() == before


@pytest.mark.parametrize("axis", ["account", "subject", "header", "authorization", "endpoint"])
def test_codex_primary_checks_token_and_account_header_independently(codex_store, axis):
    from agent.delegation_fallback import install_policy
    from tools.delegate_tool_config import _resolve_child_fallback_chain
    route, cfg = codex_route()
    resolved = _route_to_task_route(route, SimpleNamespace(), {}, cfg, "model_map")
    envelope = _resolve_child_fallback_chain(SimpleNamespace(), resolved.routing_cfg, True)
    headers = {"ChatGPT-Account-ID": "fixture-account"}
    token = codex_token()
    endpoint = resolved.creds["base_url"]
    if axis == "account":
        token = codex_token(account="other-account")
    elif axis == "subject":
        token = codex_token(subject="other-subject")
    elif axis == "header":
        headers["ChatGPT-Account-ID"] = "other-account"
    elif axis == "authorization":
        headers["Authorization"] = "Bearer wrong-token"
    else:
        endpoint = "https://wrong.invalid/codex"
    agent = SimpleNamespace(provider="openai-codex", model="gpt-fixture", base_url=endpoint, api_key=token,
                            _client_kwargs={"default_headers": headers})
    with pytest.raises(ValueError, match="changed|differs"):
        install_policy(agent, envelope)
    assert not hasattr(agent, "_model_map_policy")


def test_authorized_child_never_loads_or_refreshes_a_pool(codex_store, monkeypatch):
    from tools import delegate_tool_config
    from tests.agent.test_delegation_fallback_authority import authorized_agent
    agent = authorized_agent()
    monkeypatch.setattr(delegate_tool_config, "_loaded_pool", lambda *a: pytest.fail("pool loading may refresh/adopt"))
    assert delegate_tool_config._resolve_child_credential_pool("anthropic", SimpleNamespace(),
        routing_cfg={"_model_map_policy": agent._model_map_policy}) is None


def test_codex_changed_fallback_principal_stops_chain_instead_of_skipping_to_next(codex_store, monkeypatch):
    from agent import auxiliary_client
    from agent.agent_init_fallback import _init_fallback_chain
    from agent.chat_completion_helpers import try_activate_fallback
    from agent.error_classifier import FailoverReason
    from tools.delegate_tool_config import _resolve_child_fallback_chain
    codex = {"provider": "openai-codex", "model": "gpt-fixture", "reasoning_effort": "medium"}
    other = {"provider": "custom", "model": "gemini-backup", "base_url": "http://127.0.0.1:10/v1",
             "api_key": "fixture-backup", "reasoning_effort": "low"}
    route, cfg = route_config("repository_scout", [codex, other])
    resolved = _route_to_task_route(route, SimpleNamespace(), {}, cfg, "model_map")
    agent = SimpleNamespace(**{k: route[k] for k in ("provider", "model", "base_url", "api_key")},
        quiet_mode=True, _credential_pool=None, _credential_pool_entry_id=None)
    _init_fallback_chain(agent, _resolve_child_fallback_chain(SimpleNamespace(), resolved.routing_cfg, True))
    calls = []

    def resolve(provider, model, **kwargs):
        calls.append(provider)
        return SimpleNamespace(base_url=kwargs["explicit_base_url"], api_key=codex_token(subject="other-subject"),
            default_headers={"ChatGPT-Account-ID": "fixture-account"}), model

    monkeypatch.setattr(auxiliary_client, "resolve_provider_client", resolve)
    assert try_activate_fallback(agent, reason=FailoverReason.overloaded) is False
    assert calls == ["openai-codex"]
    assert agent.provider == "custom" and agent.model == "claude-fixture"
