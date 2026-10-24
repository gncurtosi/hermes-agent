"""Frozen exact-catalog/route-pin contracts against the official provider/runtime seams."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from providers.base import ProviderProfile

CATALOG = ("model-low", "model-medium", "model-high")
FOREIGN = [{"provider": "openai-codex", "model": "gpt-6.1-sol"},
           {"provider": "anthropic", "model": "claude-sonnet-5-5"}]


@pytest.fixture
def strict(monkeypatch):
    import providers

    class AccountProfile(ProviderProfile):
        def declared_models(self):
            return list(CATALOG)

    profile = AccountProfile(name="strict-process", aliases=("strict-alias",),
                             auth_type="external_process", base_url="process://strict",
                             strict_catalog=True, explicit_route_only=True)
    monkeypatch.setitem(providers._REGISTRY, profile.name, profile)
    monkeypatch.setitem(providers._ALIASES, "strict-alias", profile.name)
    monkeypatch.setattr(providers, "_PROVIDER_LIST_CACHE", None)
    providers.register_provider(profile)
    return profile


@pytest.mark.parametrize("model", CATALOG)
def test_valid_exact_ids_are_accepted(strict, model):
    from hermes_cli.models_validate import validate_requested_model

    assert validate_requested_model(model, strict.name, base_url=strict.base_url)["accepted"]
    assert strict.fallback_models == ()


@pytest.mark.parametrize("model", ["model-mediu", "sonnet", "gpt-6.1-sol", "MODEL-medium"])
@pytest.mark.parametrize("explicit", [False, True])
def test_selection_rejects_unlisted_ids_before_credentials(strict, monkeypatch, model, explicit):
    from hermes_cli import model_switch as ms

    credentials = Mock(side_effect=AssertionError("must reject before credentials"))
    monkeypatch.setattr(ms, "_resolve_switch_credentials", credentials)
    result = ms.switch_model(model, strict.name, "model-medium",
                             explicit_provider=strict.name if explicit else "")
    assert not result.success
    assert result.target_provider == strict.name
    credentials.assert_not_called()


def test_global_alias_collision_cannot_override_exact_route(strict, monkeypatch):
    from hermes_cli import model_switch as ms

    monkeypatch.setattr(ms, "_ensure_direct_aliases", lambda: None)
    monkeypatch.setattr(ms, "DIRECT_ALIASES", {
        "model-medium": ms.DirectAlias("foreign", "anthropic", "https://foreign.invalid")})
    assert ms.resolve_alias("model-medium", strict.name) == (strict.name, "model-medium", "model-medium")


def test_missing_catalog_fails_closed(strict, monkeypatch):
    from hermes_cli.model_switch import switch_model

    def unavailable():
        raise RuntimeError("account catalog unavailable")

    monkeypatch.setattr(strict, "declared_models", unavailable)
    result = switch_model("model-medium", strict.name, "model-low", explicit_provider=strict.name)
    assert not result.success
    assert "account catalog unavailable" in result.error_message


@pytest.mark.parametrize("provider", ["strict-process", "strict-alias"])
def test_runtime_rejects_unknown_model_before_resolution(strict, monkeypatch, provider):
    from hermes_cli import runtime_provider as rp

    ladder = Mock(side_effect=AssertionError("must reject before credentials"))
    monkeypatch.setattr(rp, "_ladder_rungs", ladder)
    with pytest.raises(ValueError):
        rp.resolve_runtime_provider(requested=provider, target_model="gpt-6.1-sol")
    ladder.assert_not_called()


@pytest.mark.parametrize("provider", ["strict-process", "strict-alias"])
def test_runtime_requires_explicit_model(strict, monkeypatch, provider):
    from hermes_cli import runtime_provider as rp

    monkeypatch.setattr(rp, "_get_model_config", lambda: {"provider": "openai-codex", "default": "gpt-6.1-sol"})
    with pytest.raises(ValueError):
        rp.resolve_runtime_provider(requested=provider)


@pytest.mark.parametrize("requested", ["strict-process", "strict-alias", None, "auto"])
def test_auth_resolution_never_walks_foreign_chain(strict, monkeypatch, requested):
    from hermes_cli import runtime_provider as rp
    from hermes_cli.auth import AuthError

    seen = []
    def resolve(requested=None, **kwargs):
        seen.append(requested)
        raise AuthError("native quota unavailable", provider=strict.name)

    monkeypatch.setattr(rp, "resolve_runtime_provider", resolve)
    monkeypatch.setattr(rp, "_get_model_config", lambda: {"provider": strict.name, "default": "model-medium"})
    with pytest.raises(AuthError):
        rp.resolve_runtime_with_fallback({"fallback_providers": FOREIGN}, requested=requested, target_model="model-medium")
    assert seen == [requested]


def test_non_pinned_auth_resolution_retains_official_fallback(strict, monkeypatch):
    from hermes_cli import runtime_provider as rp
    from hermes_cli.auth import AuthError

    seen = []
    def resolve(requested=None, **kwargs):
        seen.append(requested)
        if requested == "openrouter":
            raise AuthError("missing key", provider="openrouter")
        return {"provider": requested}

    monkeypatch.setattr(rp, "resolve_runtime_provider", resolve)
    runtime, entry = rp.resolve_runtime_with_fallback({"fallback_providers": FOREIGN}, requested="openrouter")
    assert seen == ["openrouter", "openai-codex"]
    assert runtime["provider"] == entry["provider"] == "openai-codex"


@pytest.mark.parametrize("reason", ["rate_limit", "billing", "auth", "auth_permanent", "unknown", "server_error"])
def test_all_error_reasons_cannot_activate_foreign_fallback(strict, reason):
    from agent.chat_completion_helpers import try_activate_fallback
    from agent.error_classifier import FailoverReason

    agent = SimpleNamespace(provider=strict.name, model="model-medium", _fallback_chain=list(FOREIGN),
                            _fallback_index=0, _fallback_model=FOREIGN[0])
    assert try_activate_fallback(agent, FailoverReason(reason)) is False
    assert (agent.provider, agent.model) == (strict.name, "model-medium")
    assert agent._fallback_chain == []
    assert agent._fallback_model is None


def test_client_construction_error_does_not_fall_through(strict, monkeypatch):
    from agent.provider_client_factory import _provider_supplied_client

    monkeypatch.setattr(strict, "create_client", Mock(side_effect=OSError("native client unavailable")))
    with pytest.raises(RuntimeError, match="no other provider"):
        _provider_supplied_client(SimpleNamespace(provider=strict.name), {"base_url": strict.base_url})


def test_automatic_route_binding_is_refused_before_client_resolution(strict, monkeypatch):
    from agent.route_binding import bind_route_entry

    resolver = Mock(side_effect=AssertionError("foreign client must not be resolved"))
    monkeypatch.setattr("agent.auxiliary_client.resolve_provider_client", resolver)
    agent = SimpleNamespace(provider=strict.name, model="model-medium")
    with pytest.raises(ValueError):
        bind_route_entry(agent, FOREIGN[0], "openai-codex", "gpt-6.1-sol")
    resolver.assert_not_called()


def test_credential_rotation_does_not_change_account_or_endpoint(strict):
    from agent.client_lifecycle import ClientLifecycleMixin

    agent = SimpleNamespace(provider=strict.name, model="model-medium", base_url=strict.base_url)
    assert ClientLifecycleMixin._swap_credential(agent, SimpleNamespace()) is False
    assert (agent.provider, agent.model, agent.base_url) == (strict.name, "model-medium", strict.base_url)


def test_credential_pool_recovery_does_not_rotate(strict):
    from agent.agent_runtime_helpers import recover_with_credential_pool

    pool = Mock()
    agent = SimpleNamespace(provider=strict.name, _credential_pool=pool)
    assert recover_with_credential_pool(agent, status_code=429, has_retried_429=True) == (False, True)
    assert pool.mock_calls == []


def test_primary_transport_recovery_cannot_apply_foreign_snapshot(strict):
    from agent.agent_runtime_helpers import try_recover_primary_transport
    import openai

    agent = SimpleNamespace(provider=strict.name, model="model-medium", base_url=strict.base_url)
    error = openai.APIConnectionError(request=__import__("httpx").Request("POST", "https://unused.invalid"))
    assert try_recover_primary_transport(agent, error, retry_count=3, max_retries=3) is False
    assert (agent.provider, agent.model, agent.base_url) == (strict.name, "model-medium", strict.base_url)


def test_local_valueerror_settlement_stays_pinned(strict, monkeypatch):
    from agent.error_classifier import classify_api_error
    from agent.turn_api_error import settle_unrecovered_error
    from agent.chat_completion_helpers import try_activate_fallback

    agent = SimpleNamespace(provider=strict.name, model="model-medium", log_prefix="", verbose=False,
                            _credential_pool=None, _fallback_chain=list(FOREIGN), _fallback_index=0,
                            _fallback_model=FOREIGN[0], _has_pending_fallback=lambda: True,
                            _buffer_diagnostic_status=lambda *args: None)
    agent._try_activate_fallback = lambda **kwargs: try_activate_fallback(agent, **kwargs)
    error = ValueError("unclassified local validation failure")
    monkeypatch.setattr("agent.turn_api_error.settle_delivered_partial", lambda *args: None)
    monkeypatch.setattr("agent.turn_api_error.nonretryable_client_error_result",
                        lambda *args, **kwargs: {"failed": True})
    retry = SimpleNamespace(copilot_stale_cred_retry_attempted=False, primary_recovery_attempted=False)
    result = settle_unrecovered_error(
        agent, api_error=error, classified=classify_api_error(error, provider=strict.name), _retry=retry,
        status_code=None, error_msg=str(error), is_context_length_error=False, is_rate_limited=False,
        _is_zai_coding_overload=False, _provider=strict.name, _base=strict.base_url, _model=agent.model,
        messages=[], api_messages=[], api_kwargs={}, active_system_prompt="", conversation_history=None,
        approx_tokens=10, retry_count=0, max_retries=3, compression_attempts=0, api_call_count=1)
    assert result.action == "return" and result.result["failed"]
    assert (agent.provider, agent.model) == (strict.name, "model-medium")
    assert agent._fallback_chain == []


@pytest.mark.parametrize("model", [None, "gpt-6.1-sol", "model-mediu"])
def test_canonical_dashboard_and_cli_launch_reject_foreign_default(strict, model, tmp_path):
    from gateway.session_policy import build_policy

    params = {"provider": strict.name, "cwd": str(tmp_path), "source": "cli"}
    if model is not None:
        params["model"] = model
    config = {"model": {"provider": "openai-codex", "default": "gpt-6.1-sol"}}
    with pytest.raises(ValueError):
        build_policy(params, config, profile_terminal=False)


@pytest.mark.parametrize("model", [None, "gpt-6.1-sol", "model-mediu"])
def test_legacy_dashboard_composer_rejects_invalid_selection(strict, model):
    from contextlib import nullcontext
    from tui_gateway.methods_session_model_guard import model_override_conflict

    params = {"provider": strict.name}
    if model is not None:
        params["model"] = model
    result = model_override_conflict(params, nullcontext())
    assert result and result["provider"] == strict.name


def test_auxiliary_failure_does_not_escape_pinned_main(strict, monkeypatch):
    from agent import auxiliary_client as aux

    monkeypatch.setattr(aux, "_try_main_provider_route", lambda *args: None)
    fallback = Mock(side_effect=AssertionError("no auxiliary provider substitution"))
    monkeypatch.setattr(aux, "_try_configured_fallback_chain", fallback)
    monkeypatch.setattr(aux, "_try_main_fallback_chain", fallback)
    assert aux._resolve_auto_route({"provider": strict.name, "model": "model-medium",
                                    "base_url": strict.base_url}, "title_generation") == (None, None, "")
    fallback.assert_not_called()
