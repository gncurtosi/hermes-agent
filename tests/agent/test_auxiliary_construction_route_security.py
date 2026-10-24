"""Public auxiliary APIs must not abandon a pinned route before inference starts."""
import asyncio
from types import SimpleNamespace
from typing import Any

import hermes_yaml as yaml
import pytest

import agent.auxiliary_client as aux
from providers.base import ProviderProfile

PIN = "antigravity-subscription-directsdk"
MODEL = "gemini-3.8-flash-medium"
FOREIGN = {"provider": "custom", "model": "approved-fixture-model",
           "base_url": "http://127.0.0.1:9/v1", "api_key": "fixture-key"}
MESSAGES = [{"role": "user", "content": "Fixture request"}]


@pytest.fixture
def construction(tmp_path, monkeypatch):
    import providers
    from hermes_cli import auth

    home = tmp_path / "hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HOME", str(tmp_path))
    events = []

    class BrokenProfile(ProviderProfile):
        def create_client(self, **kwargs):
            events.append(("construct", self.name))
            raise RuntimeError("fixture constructor failure")

    for name, pinned in ((PIN, True), ("fixture-ordinary", False)):
        profile = BrokenProfile(name=name, auth_type="external_process", base_url="agy://local",
                                fallback_models=(MODEL,), strict_catalog=pinned,
                                explicit_route_only=pinned)
        monkeypatch.setitem(providers._REGISTRY, name, profile)
        providers.register_provider(profile)
    monkeypatch.setattr(auth, "resolve_external_process_provider_credentials",
                        lambda provider: {"api_key": "fixture-key", "base_url": "agy://local"})
    monkeypatch.setattr(aux, "_client_cache", {})
    monkeypatch.setattr(aux, "_aux_unhealthy_until", {})
    monkeypatch.setattr(aux, "_aux_unhealthy_reason", {})
    monkeypatch.setattr(aux, "_aux_unhealthy_logged_at", {})

    def configure(default=PIN, task_provider=None, task_fallback=True):
        tasks: dict[str, Any] = {
            task: {"fallback_chain": [FOREIGN] if task_fallback else []} for task in ("compression", "vision")}
        if task_provider:
            tasks["compression"].update(provider=task_provider, model=MODEL)
        (home / "config.yaml").write_text(yaml.safe_dump({
            "model": {"provider": default, "default": MODEL},
            "fallback_providers": [FOREIGN], "auxiliary": tasks,
        }))

    def physical(client, kwargs, **options):
        events.append(("inference", options.get("provider"), kwargs["model"]))
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content="approved response", tool_calls=None), finish_reason="stop")])

    async def async_physical(*args, **kwargs):
        return physical(*args, **kwargs)

    monkeypatch.setattr(aux, "_relay_sync_completion", physical)
    monkeypatch.setattr(aux, "_relay_async_completion", async_physical)
    configure()
    with aux.scoped_runtime_main({}):
        yield configure, events
    for client, _, _ in list(aux._client_cache.values()):
        aux._close_cached_client(client)


def invoke(async_mode, **kwargs):
    args: dict[str, Any] = dict(task="compression", messages=MESSAGES, **kwargs)
    return asyncio.run(aux.async_call_llm(**args)) if async_mode else aux.call_llm(**args)


@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize("task", ["compression", "vision"])
def test_public_constructor_failure_never_selects_foreign_route(construction, async_mode, task):
    _, events = construction
    call = dict(task=task, provider=PIN, model=MODEL, messages=MESSAGES,
                main_runtime={"provider": "fixture-ordinary", "model": MODEL})
    with pytest.raises(aux.AuxiliaryClientUnavailable):
        if async_mode:
            asyncio.run(aux.async_call_llm(**call))
        else:
            aux.call_llm(**call)
    assert events == [("construct", PIN)]


@pytest.mark.parametrize("async_mode", [False, True])
def test_public_ordinary_constructor_failure_keeps_configured_fallback(construction, async_mode):
    _, events = construction
    result = invoke(async_mode, provider="fixture-ordinary", model=MODEL,
                    main_runtime={"provider": "fixture-ordinary", "model": MODEL})
    assert result.choices[0].message.content == "approved response"
    assert events[0] == ("construct", "fixture-ordinary")
    assert events[1][0] == "inference" and events[1][2] == FOREIGN["model"]
    assert len(events) == 2


@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize("bad_model", ["unknown-model", "gemini-3.8-flash-HIGH", "gpt-6.1-sol"])
def test_public_pinned_model_rejection_precedes_construction(construction, async_mode, bad_model):
    _, events = construction
    with pytest.raises(ValueError, match="catalog"):
        invoke(async_mode, provider=PIN, model=bad_model, main_runtime={"provider": PIN, "model": MODEL})
    assert events == []


def test_compression_unavailable_helper_cannot_escape_pin(construction):
    _, events = construction
    assert aux._try_configured_fallback_for_unavailable_client("compression", PIN) == (None, None, "")
    assert events == []


@pytest.mark.parametrize("origin,allowed", [(PIN, False), ("fixture-ordinary", True)])
def test_nested_main_chain_uses_explicit_snapshot_not_profile_default(construction, origin, allowed):
    configure, _ = construction
    configure("fixture-ordinary" if origin == PIN else PIN)
    client, model, _ = aux._try_main_fallback_chain(
        "compression", "auto", main_runtime={"provider": origin, "model": MODEL})
    assert (client is not None) is allowed
    if allowed:
        assert client is not None
        assert model == FOREIGN["model"]
        client.close()


@pytest.mark.parametrize("async_mode", [False, True])
def test_public_auto_pinned_origin_overrides_ordinary_default(construction, async_mode):
    configure, events = construction
    configure("fixture-ordinary")
    with pytest.raises(aux.AuxiliaryClientUnavailable):
        invoke(async_mode, provider="auto", model=MODEL, main_runtime={"provider": PIN, "model": MODEL})
    assert events == [("construct", PIN)]


def test_auto_vision_never_probes_aggregators_after_pinned_failure(construction, monkeypatch):
    _, events = construction
    monkeypatch.setattr(aux, "_resolve_provider_vision_default", lambda provider: None)
    monkeypatch.setattr(aux, "_main_model_supports_vision", lambda provider, model: True)

    def forbidden(*args, **kwargs):
        pytest.fail("Pinned vision route reached foreign backend selection")

    monkeypatch.setattr(aux, "_resolve_strict_vision_backend", forbidden)
    assert aux.resolve_vision_provider_client(
        provider="auto", main_runtime={"provider": PIN, "model": MODEL}) == (None, None, None)
    assert events == [("construct", PIN)]


@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize("origin", [PIN, "fixture-ordinary"])
def test_public_recovery_keeps_snapshot_after_profile_and_context_change(construction, monkeypatch, async_mode, origin):
    from providers import get_provider_profile

    configure, events = construction
    conflicting = "fixture-ordinary" if origin == PIN else PIN
    configure(conflicting, task_fallback=False)

    class NativeFixture:
        HERMES_SKIP_ASYNC_WRAP = True
        base_url = "agy://local"
        api_key = "fixture-key"

    class CapacityError(Exception):
        status_code = 402

    def construct(**kwargs):
        events.append(("construct", origin))
        return NativeFixture()

    profile = get_provider_profile(origin)
    assert profile is not None
    monkeypatch.setattr(profile, "create_client", construct)
    error = CapacityError("Error code: 402")
    attempts = []

    def physical(client, kwargs, **options):
        attempts.append((options.get("provider"), kwargs["model"]))
        if len(attempts) == 1:
            configure(conflicting, task_fallback=False)
            aux._RUNTIME_MAIN_CONTEXT.set({"provider": conflicting, "model": "changed-default"})
            raise error
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content="approved response", tool_calls=None), finish_reason="stop")])

    async def async_physical(*args, **kwargs):
        return physical(*args, **kwargs)

    monkeypatch.setattr(aux, "_relay_sync_completion", physical)
    monkeypatch.setattr(aux, "_relay_async_completion", async_physical)
    call: dict[str, Any] = dict(provider="auto", model=MODEL, main_runtime={"provider": origin, "model": MODEL})
    if origin == PIN:
        with pytest.raises(CapacityError) as failure:
            invoke(async_mode, **call)
        assert failure.value is error
        assert attempts == [(PIN, MODEL)]
    else:
        assert invoke(async_mode, **call).choices[0].message.content == "approved response"
        assert attempts[0] == (origin, MODEL)
        assert len(attempts) == 2 and attempts[1][1] == FOREIGN["model"]
    assert events == [("construct", origin)]


def test_pinned_auto_vision_preserves_model_instead_of_catalog_vision_default(construction, monkeypatch):
    _, events = construction
    monkeypatch.setattr(aux, "_resolve_provider_vision_default", lambda provider: "gemini-4-argon-high")
    monkeypatch.setattr(aux, "_main_model_supports_vision", lambda provider, model: True)
    assert aux.resolve_vision_provider_client(
        provider="auto", main_runtime={"provider": PIN, "model": MODEL}) == (None, None, None)
    assert events == [("construct", PIN)]


@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize("model", ["unknown-model", "gemini-3.8-flash-HIGH", "gpt-6.1-sol"])
def test_public_auto_vision_rejects_invalid_model_before_construction(construction, monkeypatch, async_mode, model):
    _, events = construction
    monkeypatch.setattr(aux, "_main_model_supports_vision", lambda provider, model: True)
    call: dict[str, Any] = dict(task="vision", provider="auto", model=model, messages=MESSAGES,
                                main_runtime={"provider": PIN, "model": MODEL})
    with pytest.raises(ValueError, match="catalog"):
        if async_mode:
            asyncio.run(aux.async_call_llm(**call))
        else:
            aux.call_llm(**call)
    assert events == []


@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize("model", ["unknown-model", "gemini-3.8-flash-HIGH", "gpt-6.1-sol", "google/gemini-3.8-flash-medium"])
def test_public_auto_text_rejects_unknown_model_and_namespace_substitution(construction, monkeypatch, async_mode, model):
    from providers import get_provider_profile

    _, events = construction

    class NativeFixture:
        HERMES_SKIP_ASYNC_WRAP = True
        base_url = "agy://local"
        api_key = "fixture-key"

    profile = get_provider_profile(PIN)
    assert profile is not None
    monkeypatch.setattr(profile, "create_client", lambda **kwargs: NativeFixture())
    with pytest.raises(ValueError, match="catalog"):
        invoke(async_mode, provider="auto", model=model, main_runtime={"provider": PIN, "model": MODEL})
    assert events == []
