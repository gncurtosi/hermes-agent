"""Registered pinned providers retain policy through custom-prefixed public requests."""
import asyncio
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import hermes_yaml as yaml
import pytest

import agent.auxiliary_client as aux
from hermes_cli.auth import read_credential_pool
from tests.agent.test_auxiliary_route_pin_security import ApiError, seed_pool
from tests.agent.test_auxiliary_construction_route_security import (
    MODEL,
    PIN,
    MESSAGES,
    construction as construction_fixture,
)


@pytest.fixture
def construction(tmp_path, monkeypatch):
    yield from construction_fixture.__wrapped__(tmp_path, monkeypatch)


@pytest.fixture(autouse=True)
def registered_alias(construction, monkeypatch):
    import providers
    from hermes_cli import auth

    monkeypatch.setitem(providers._ALIASES, "agy", PIN)
    monkeypatch.setitem(auth.PROVIDER_REGISTRY, "agy", auth.PROVIDER_REGISTRY[PIN])


@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize("task", ["compression", "vision"])
@pytest.mark.parametrize("provider", [PIN, "custom:" + PIN, "agy", "custom:agy"])
def test_public_prefixed_constructor_failure_keeps_pin(construction, async_mode, task, provider):
    _, events = construction
    call: dict[str, Any] = dict(task=task, provider=provider, model=MODEL, messages=MESSAGES,
                                main_runtime={"provider": "fixture-ordinary", "model": MODEL})
    with pytest.raises(aux.AuxiliaryClientUnavailable):
        if async_mode:
            asyncio.run(aux.async_call_llm(**call))
        else:
            aux.call_llm(**call)
    assert events == [("construct", PIN)]


@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize("task", ["compression", "vision"])
@pytest.mark.parametrize("provider", [PIN, "custom:" + PIN, "agy", "custom:agy"])
@pytest.mark.parametrize("selection", ["arguments", "task_config"])
def test_public_pinned_endpoint_override_is_rejected(construction, async_mode, task, provider, selection):
    _, events = construction
    override = dict(provider=provider, model=MODEL, base_url="https://foreign.invalid/v1",
                    api_key="fixture-key")
    call: dict[str, Any] = dict(task=task, messages=MESSAGES,
                                main_runtime={"provider": "fixture-ordinary", "model": MODEL})
    if selection == "task_config":
        path = Path(os.environ["HERMES_HOME"]) / "config.yaml"
        config = yaml.safe_load(path.read_text())
        config["auxiliary"][task].update(override)
        path.write_text(yaml.safe_dump(config))
    else:
        call.update(override)
    with pytest.raises(ValueError, match="pins its endpoint"):
        if async_mode:
            asyncio.run(aux.async_call_llm(**call))
        else:
            aux.call_llm(**call)
    assert events == []


@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize("task", ["compression", "vision"])
@pytest.mark.parametrize("provider", [PIN, "custom:" + PIN, "agy", "custom:agy"])
def test_public_prefixed_model_rejection_precedes_construction(construction, async_mode, task, provider):
    _, events = construction
    call: dict[str, Any] = dict(task=task, provider=provider, model="unlisted-model", messages=MESSAGES,
                                main_runtime={"provider": "fixture-ordinary", "model": MODEL})
    with pytest.raises(ValueError, match="catalog"):
        if async_mode:
            asyncio.run(aux.async_call_llm(**call))
        else:
            aux.call_llm(**call)
    assert events == []


@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize("task", ["compression", "vision"])
@pytest.mark.parametrize("provider", [PIN, "custom:" + PIN, "custom:agy"])
@pytest.mark.parametrize("status", [401, 402, 429])
def test_public_prefixed_request_recovery_keeps_account(construction, monkeypatch, async_mode, task, provider, status):
    from providers import get_provider_profile

    _, events = construction
    before = seed_pool(PIN)

    class NativeFixture:
        HERMES_SKIP_ASYNC_WRAP = True
        base_url = "agy://local"
        api_key = "fixture-credential-1"

    profile = get_provider_profile(PIN)
    assert profile is not None
    monkeypatch.setattr(profile, "create_client", lambda **kwargs: NativeFixture())
    error = ApiError(status)
    attempts = []

    def physical(client, kwargs, **options):
        attempts.append((options.get("provider"), kwargs["model"]))
        if kwargs["model"] == MODEL:
            raise error
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content="foreign response", tool_calls=None), finish_reason="stop")])

    async def async_physical(*args, **kwargs):
        return physical(*args, **kwargs)

    monkeypatch.setattr(aux, "_relay_sync_completion", physical)
    monkeypatch.setattr(aux, "_relay_async_completion", async_physical)
    call: dict[str, Any] = dict(task=task, provider=provider, model=MODEL, messages=MESSAGES,
                                main_runtime={"provider": "fixture-ordinary", "model": "ordinary-model"})
    with pytest.raises(ApiError) as failure:
        if async_mode:
            asyncio.run(aux.async_call_llm(**call))
        else:
            aux.call_llm(**call)
    assert failure.value is error
    assert len(attempts) == 1 and attempts[0][1] == MODEL
    assert read_credential_pool(PIN) == before
    assert events == []


@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize("provider", ["fixture-ordinary", "custom:fixture-ordinary"])
def test_public_ordinary_provider_retains_authorized_fallback(construction, async_mode, provider):
    _, events = construction
    call: dict[str, Any] = dict(task="compression", provider=provider, model=MODEL, messages=MESSAGES,
                                main_runtime={"provider": PIN, "model": MODEL})
    result = asyncio.run(aux.async_call_llm(**call)) if async_mode else aux.call_llm(**call)
    assert result.choices[0].message.content == "approved response"
    assert events[0] == ("construct", "fixture-ordinary")
    assert events[1][0] == "inference" and events[1][1] == "fallback_chain[0](custom)"


@pytest.mark.parametrize("async_mode", [False, True])
def test_public_generic_custom_endpoint_is_not_a_pinned_plugin(construction, async_mode):
    _, events = construction
    call: dict[str, Any] = dict(task="compression", provider="custom:ordinary-endpoint", model="own-model",
                                base_url="http://127.0.0.1:9/v1", api_key="fixture-key", messages=MESSAGES,
                                main_runtime={"provider": PIN, "model": MODEL})
    result = asyncio.run(aux.async_call_llm(**call)) if async_mode else aux.call_llm(**call)
    assert result.choices[0].message.content == "approved response"
    assert events == [("inference", "custom", "own-model")]


@pytest.mark.parametrize("provider", [PIN, "custom:" + PIN, "custom:agy"])
def test_compression_feasibility_cannot_construct_foreign_fallback(construction, provider):
    from tests.agent.test_compression_feasibility import _make_agent

    configure, events = construction
    configure("fixture-ordinary", task_provider=provider)
    agent: Any = _make_agent()
    agent._check_compression_model_feasibility()
    assert events == [("construct", PIN)]
    assert agent._compression_warning and "unavailable" in agent._compression_warning
