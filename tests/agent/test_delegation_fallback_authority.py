"""Operator model_map chains are bounded exceptions, never blanket pin bypasses."""
from types import SimpleNamespace

import pytest

from tools.delegate_tool_routes import _route_to_task_route


def route_config(label="critical_audit", chain=None):
    option = {"name": label, "description": "fixture route", "provider": "custom",
              "model": "claude-fixture", "base_url": "http://127.0.0.1:9/v1",
              "api_key": "fixture-primary", "reasoning_effort": "high"}
    if chain is not None:
        option["fallback_providers"] = chain
    cfg = {"backend": "model_map", "backends": {"model_map": {"options": [option]}}}
    route = {k: v for k, v in option.items() if k not in {"name", "description"}}
    return {**route, "label": label}, cfg


@pytest.mark.parametrize("label", ["critical_audit", "independent_science_review",
                                    "review_openai_author", "review_claude_author"])
def test_review_label_is_not_actual_author_provenance(label):
    route, cfg = route_config(label)
    with pytest.raises(ValueError, match="actual author"):
        _route_to_task_route(route, SimpleNamespace(), {}, cfg, "model_map")


def test_operator_chain_survives_pin_and_uses_each_exact_route(monkeypatch):
    from agent.agent_init_fallback import _init_fallback_chain
    from agent.chat_completion_helpers import try_activate_fallback
    from tools.delegate_tool_config import _resolve_child_fallback_chain
    import providers
    from providers.base import ProviderProfile

    chain = [{"provider": "fixture-backup", "model": "gemini-fixture",
              "base_url": "http://127.0.0.1:10/v1", "api_key": "fixture-backup-key",
              "reasoning_effort": "medium"},
             {"provider": "custom", "model": "gpt-fixture", "base_url": "http://127.0.0.1:11/v1",
              "api_key": "fixture-last-key", "reasoning_effort": "low"}]
    route, cfg = route_config("implementation", chain)
    route["provider"] = cfg["backends"]["model_map"]["options"][0]["provider"] = "fixture-pin"
    for provider, model, base in [("fixture-pin", "claude-fixture", route["base_url"]),
                                  ("fixture-backup", "gemini-fixture", chain[0]["base_url"])]:
        profile = ProviderProfile(name=provider, base_url=base, strict_catalog=True,
                                  explicit_route_only=True, fallback_models=(model,))
        monkeypatch.setitem(providers._REGISTRY, provider, profile)
    from agent import auxiliary_client
    calls = []

    def resolve(provider, model, **kwargs):
        calls.append((provider, model, kwargs))
        return SimpleNamespace(base_url=kwargs["explicit_base_url"], api_key=kwargs["explicit_api_key"]), model

    monkeypatch.setattr(auxiliary_client, "resolve_provider_client", resolve)
    resolved = _route_to_task_route(route, SimpleNamespace(), {}, cfg, "model_map")
    declared = _resolve_child_fallback_chain(SimpleNamespace(), resolved.routing_cfg, pinned=True)
    agent = SimpleNamespace(provider="fixture-pin", model="claude-fixture", base_url=route["base_url"],
                            api_key="fixture-primary", api_mode="chat_completions", quiet_mode=True,
                            _credential_pool=None, _credential_pool_entry_id=None,
                            _anthropic_prompt_cache_policy=lambda **kw: (False, False),
                            _ensure_lmstudio_runtime_loaded=lambda: None,
                            _is_azure_openai_url=lambda url: False, _is_direct_openai_url=lambda url: False,
                            _provider_model_requires_responses_api=lambda *a, **kw: False,
                            _buffer_diagnostic_status=lambda *a: None, context_compressor=None,
                            _cached_system_prompt="stable prompt", request_overrides={},
                            _client_kwargs={}, _replace_primary_openai_client=lambda **kw: None)
    _init_fallback_chain(agent, declared)
    assert agent._fallback_chain == chain
    from agent.error_classifier import FailoverReason
    assert try_activate_fallback(agent, reason=FailoverReason.overloaded) is True
    assert (agent.provider, agent.model, agent.base_url.rstrip("/"), agent.api_key) == (
        "fixture-backup", "gemini-fixture", chain[0]["base_url"], "fixture-backup-key")
    assert agent.reasoning_config == {"enabled": True, "effort": "medium"}
    assert try_activate_fallback(agent, reason=FailoverReason.overloaded) is True
    assert (agent.provider, agent.model, agent.base_url.rstrip("/"), agent.api_key) == (
        "custom", "gpt-fixture", chain[1]["base_url"], "fixture-last-key")
    assert agent.reasoning_config == {"enabled": True, "effort": "low"}
    assert try_activate_fallback(agent) is False
    assert agent._cached_system_prompt == "stable prompt"
    assert [(p, m) for p, m, _ in calls] == [(e["provider"], e["model"]) for e in chain]


def authorized_agent(label="implementation", model="gemini-backup", fallback2=False):
    from agent.agent_init_fallback import _init_fallback_chain
    from tools.delegate_tool_config import _resolve_child_fallback_chain
    chain = [{"provider": "custom", "model": model, "base_url": "http://127.0.0.1:10/v1",
              "api_key": "fixture-backup", "reasoning_effort": "medium"}]
    if fallback2:
        chain.insert(0, {**chain[0], "model": "gemini-first"})
    route, cfg = route_config(label, chain)
    resolved = _route_to_task_route(route, SimpleNamespace(), {}, cfg, "model_map")
    agent = SimpleNamespace(**{k: route[k] for k in ("provider", "model", "base_url", "api_key")},
                            quiet_mode=True, _credential_pool=None, _credential_pool_entry_id=None,
                            reasoning_config={"enabled": True, "effort": "high"},
                            api_mode="chat_completions", context_compressor=None, request_overrides={},
                            _client_kwargs={}, _replace_primary_openai_client=lambda **kw: None,
                            _anthropic_prompt_cache_policy=lambda **kw: (False, False),
                            _ensure_lmstudio_runtime_loaded=lambda: None,
                            _is_azure_openai_url=lambda url: False, _is_direct_openai_url=lambda url: False,
                            _provider_model_requires_responses_api=lambda *a, **kw: False)
    _init_fallback_chain(agent, _resolve_child_fallback_chain(SimpleNamespace(), resolved.routing_cfg, True))
    return agent


@pytest.mark.parametrize("executor", ["execute_tool_calls_concurrent", "execute_tool_calls_sequential",
                                      "_execute_tool_calls_sequential", "execute_tool_calls_segmented"])
def test_dispatch_closes_fallback_before_any_tool_can_execute(monkeypatch, executor):
    from agent import tool_executor as tools
    from agent import terminal_approval_batch as batch
    from agent.chat_completion_helpers import try_activate_fallback
    agent = authorized_agent()

    def stop(*a, **kw):
        raise RuntimeError("stop probe")

    monkeypatch.setattr(tools, "_budget_for_agent", stop)
    monkeypatch.setattr(tools, "get_active_env", stop)
    monkeypatch.setattr(batch, "terminal_approval_runs", stop)
    with pytest.raises(RuntimeError, match="stop probe"):
        getattr(tools, executor)(agent, SimpleNamespace(tool_calls=[SimpleNamespace()]), [], "fixture-task")
    assert getattr(agent, "_model_map_tool_barrier", False) is True
    assert try_activate_fallback(agent) is False
    assert agent._fallback_index == 0


def test_model_map_cannot_rotate_to_another_account():
    from agent.client_lifecycle import ClientLifecycleMixin
    from agent.agent_runtime_helpers import recover_with_credential_pool
    agent = authorized_agent()
    agent.api_mode, agent._client_kwargs = "chat_completions", {}
    agent._reapply_route_client_config = lambda **kw: None
    agent._replace_primary_openai_client = lambda **kw: None
    other = SimpleNamespace(access_token="fixture-other-account", base_url=agent.base_url, id="other")
    assert ClientLifecycleMixin._swap_credential(agent, other) is False
    assert recover_with_credential_pool(agent, status_code=402, has_retried_429=False) == (False, False)


def test_model_map_provenance_records_reason_and_keeps_prompt():
    from agent.delegation_fallback import finish_bind
    from agent.chat_completion_helpers import rewrite_prompt_model_identity
    from agent.error_classifier import FailoverReason
    from agent.delegation_fallback import fallback_blocked
    agent = authorized_agent()
    agent._cached_system_prompt = "Model: claude-fixture\nProvider: custom\nunchanged"
    original = agent._cached_system_prompt
    assert fallback_blocked(agent, FailoverReason.billing) is False
    # The binder's independent guard must not replace the failure reason.
    assert fallback_blocked(agent) is False
    finish_bind(agent, agent._fallback_chain[0])
    rewrite_prompt_model_identity(agent, "gemini-backup", "custom")
    assert agent._model_map_transitions[0]["reason"] == "billing"
    assert agent._cached_system_prompt == original


def test_model_map_does_not_lease_a_different_account():
    from tools.delegate_tool_child_run import _lease_child_credential
    agent = authorized_agent()

    class NoLease:
        def acquire_lease(self):
            pytest.fail("account lease would mutate the exact selected account")

    agent._credential_pool = NoLease()
    assert _lease_child_credential(agent) == (None, None)


def test_model_map_effort_rejection_cannot_silently_use_route_default():
    from agent.chat_completion_helpers import _reasoning_config_for_wire
    agent = authorized_agent()
    agent._reasoning_effort_rejected = True
    with pytest.raises(ValueError, match="effort"):
        _reasoning_config_for_wire(agent)


def test_independent_fallback_cannot_enter_actual_authors_family():
    from agent.delegation_fallback import delegation_task_context, check_bind
    with delegation_task_context(author_family="openai"):
        agent = authorized_agent("critical_audit", "gpt-backup")
    agent._fallback_index = 1
    with pytest.raises(ValueError, match="not independent"):
        check_bind(agent, agent._fallback_chain[0], "custom", "gpt-backup")
    # The trusted context was snapshotted; later ambient context cannot grant authority.
    with pytest.raises(ValueError, match="actual author"):
        authorized_agent("critical_audit")


def test_review_openai_label_cannot_hide_an_actual_anthropic_author():
    from agent.delegation_fallback import delegation_task_context
    with delegation_task_context(author_family="anthropic"):
        with pytest.raises(ValueError, match="not independent"):
            authorized_agent("review_openai_author")


@pytest.mark.parametrize("suitable", [False, True])
def test_terra_requires_trusted_bounded_suitability(suitable):
    from agent.delegation_fallback import delegation_task_context, check_bind
    with delegation_task_context(bounded_suitable=suitable):
        agent = authorized_agent(model="gpt-5.6-terra", fallback2=True)
    agent._fallback_index = 2
    entry = agent._fallback_chain[1]
    if suitable:
        check_bind(agent, entry, "custom", entry["model"])
    else:
        with pytest.raises(ValueError, match="bounded task suitability"):
            check_bind(agent, entry, "custom", entry["model"])


def test_inherited_global_chain_never_grants_model_map_authority():
    from tools.delegate_tool_config import _resolve_child_fallback_chain
    route, cfg = route_config("implementation")
    cfg["fallback_providers"] = [{"provider": "custom", "model": "unapproved"}]
    resolved = _route_to_task_route(route, SimpleNamespace(), {}, cfg, "model_map")
    assert list(_resolve_child_fallback_chain(SimpleNamespace(), resolved.routing_cfg, True)) == []


@pytest.mark.parametrize("corruption", ["loop", "unbounded", "effort", "route", "malformed"])
def test_only_exact_bounded_configured_chains_are_accepted(corruption):
    entry = {"provider": "custom", "model": "gemini-fixture", "base_url": "http://127.0.0.1:10/v1",
             "api_key": "fixture-backup", "reasoning_effort": "medium"}
    chain = [entry]
    corrupt = {
        "loop": lambda: chain.append(dict(entry)),
        "unbounded": lambda: chain.extend([dict(entry), dict(entry)]),
        "effort": lambda: entry.update(reasoning_effort="typo"),
        "malformed": lambda: chain.append(None),
        "route": lambda: None,
    }
    corrupt[corruption]()
    route, cfg = route_config("implementation", chain)
    if corruption == "route":
        route = {**route, "model": "substitute"}
    with pytest.raises(ValueError):
        _route_to_task_route(route, SimpleNamespace(), {}, cfg, "model_map")


@pytest.mark.parametrize("axis", ["model", "base_url", "provider", "api_key"])
def test_resolver_cannot_substitute_any_authorized_route_axis(monkeypatch, axis):
    from agent.route_binding import bind_route_entry
    from agent import auxiliary_client
    agent = authorized_agent()
    entry = agent._fallback_chain[0]
    agent._fallback_index = 1
    agent.api_mode = "chat_completions"
    before = (agent.provider, agent.model, agent.base_url, agent.api_key)
    client = SimpleNamespace(base_url=entry["base_url"], api_key=entry["api_key"],
                             _hermes_aux_effective_provider=entry["provider"])
    model = entry["model"]
    if axis == "model":
        model = "substitute"
    else:
        setattr(client, "_hermes_aux_effective_provider" if axis == "provider" else axis, "substitute")
    monkeypatch.setattr(auxiliary_client, "resolve_provider_client", lambda *a, **kw: (client, model))
    with pytest.raises(ValueError, match="changed"):
        bind_route_entry(agent, entry, entry["provider"], entry["model"])
    assert (agent.provider, agent.model, agent.base_url, agent.api_key) == before


def test_model_map_rejects_implicit_unpinned_account_selection():
    route, cfg = route_config("implementation", [{"provider": "custom", "model": "gemini-backup",
        "base_url": "http://127.0.0.1:10/v1", "api_key": "fixture-backup", "reasoning_effort": "medium"}])
    del route["api_key"]
    del cfg["backends"]["model_map"]["options"][0]["api_key"]
    with pytest.raises(ValueError, match="account"):
        _route_to_task_route(route, SimpleNamespace(), {}, cfg, "model_map")


def test_model_map_normalization_cannot_change_exact_model(monkeypatch):
    from agent import auxiliary_client
    from agent.route_binding import bind_route_entry
    import hermes_cli.model_normalize as normalizer
    agent = authorized_agent()
    entry = agent._fallback_chain[0]
    agent._fallback_index = 1
    client = SimpleNamespace(base_url=entry["base_url"], api_key=entry["api_key"])
    monkeypatch.setattr(auxiliary_client, "resolve_provider_client", lambda *a, **kw: (client, entry["model"]))
    monkeypatch.setattr(normalizer, "normalize_model_for_provider", lambda *a: "substitute")
    with pytest.raises(ValueError, match="changed"):
        bind_route_entry(agent, entry, entry["provider"], entry["model"])
    assert agent.model == "claude-fixture"


def test_pinned_destination_needs_own_operator_authority(monkeypatch):
    import providers
    from providers.base import ProviderProfile
    from agent.route_binding import bind_route_entry
    profile = ProviderProfile(name="fixture-destination", explicit_route_only=True, strict_catalog=True,
                              base_url="http://127.0.0.1:12/v1", fallback_models=("gemini-fixture",))
    monkeypatch.setitem(providers._REGISTRY, profile.name, profile)
    agent = SimpleNamespace(provider="custom")
    entry = {"provider": profile.name, "model": "gemini-fixture", "base_url": profile.base_url}
    with pytest.raises(ValueError, match="explicit operator"):
        bind_route_entry(agent, entry, entry["provider"], entry["model"])


def test_each_route_is_attempted_once_even_if_outer_index_is_reset():
    from agent.delegation_fallback import check_bind
    agent = authorized_agent()
    entry = agent._fallback_chain[0]
    agent._fallback_index = 1
    check_bind(agent, entry, entry["provider"], entry["model"])
    agent._fallback_index = 1
    with pytest.raises(ValueError, match="already attempted"):
        check_bind(agent, entry, entry["provider"], entry["model"])


def test_fallback_report_has_reason_route_and_effective_effort_without_secrets():
    from agent.delegation_fallback import finish_bind
    from tools.delegate_tool_child_run import _route_report
    agent = authorized_agent()
    agent._delegate_route = {"backend": "model_map", "label": "implementation"}
    agent._fallback_activated = True
    agent._model_map_fallback_reason = "billing"
    finish_bind(agent, agent._fallback_chain[0])
    report = _route_report(agent)
    assert report["reasoning_effort"] == "medium"
    assert report["fallback_transitions"][0]["reason"] == "billing"
    assert "api_key" not in report["fallback_transitions"][0]
