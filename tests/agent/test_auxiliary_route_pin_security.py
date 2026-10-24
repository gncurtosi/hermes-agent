"""Pinned auxiliary recovery never consumes configured foreign routes or another credential.

Real registry, configuration, fallback-client construction, and credential-pool storage are
used against a private HERMES_HOME. The ladder driver substitutes only physical inference.
"""
import asyncio
from types import SimpleNamespace

import pytest
import hermes_yaml as yaml

import agent.auxiliary_client as aux
from agent.credential_pool import load_pool
from hermes_cli.auth import read_credential_pool, write_credential_pool
from providers.base import ProviderProfile

PIN = "antigravity-subscription-directsdk"
MODEL = "gemini-3.8-flash-medium"
FOREIGN = {"provider": "custom", "model": "operator-approved-alternate",
           "base_url": "http://127.0.0.1:9/v1", "api_key": "fixture-alternate"}


class ApiError(Exception):
    def __init__(self, status):
        super().__init__(f"Error code: {status}")
        self.status_code = status


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    import providers

    home = tmp_path / "hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HOME", str(tmp_path))
    profile = ProviderProfile(name=PIN, aliases=("agy",), auth_type="external_process",
                              base_url="agy://local", explicit_route_only=True, strict_catalog=True)
    monkeypatch.setitem(providers._REGISTRY, PIN, profile)
    monkeypatch.setitem(providers._ALIASES, "agy", PIN)
    providers.register_provider(profile)
    monkeypatch.setattr(aux, "_aux_unhealthy_until", {})
    monkeypatch.setattr(aux, "_aux_unhealthy_reason", {})
    monkeypatch.setattr(aux, "_aux_unhealthy_logged_at", {})

    def configure(provider=PIN):
        config = {"model": {"provider": provider, "default": MODEL},
                  "fallback_providers": [FOREIGN],
                  "auxiliary": {"compression": {"fallback_chain": [FOREIGN]}}}
        (home / "config.yaml").write_text(yaml.safe_dump(config))

    configure()
    with aux.scoped_runtime_main({}):
        yield configure


def route(provider=PIN, runtime=None):
    base = "agy://local" if provider in {PIN, "agy", "auto"} else "https://openrouter.ai/api/v1"
    return aux._LadderRoute(
        client=SimpleNamespace(base_url=base, api_key="fixture-credential-1"),
        task="compression", tag="", async_mode=False, base_info=base,
        resolved_provider=provider, resolved_model=MODEL, resolved_base_url=base,
        resolved_api_key="fixture-credential-1", resolved_api_mode="chat_completions",
        final_model=MODEL, main_runtime=runtime, route_info={}, timeout=1,
    )


def seed_pool(provider):
    write_credential_pool(provider, [
        {"id": f"credential-{i}", "label": f"fixture account {i}", "auth_type": "api_key",
         "priority": i, "source": "manual", "access_token": f"fixture-credential-{i}"}
        for i in (1, 2)
    ])
    pool = load_pool(provider)
    assert pool.has_credentials()
    return read_credential_pool(provider)


@pytest.mark.parametrize("provider", [PIN, "agy", "auto"])
@pytest.mark.parametrize("status", [401, 402, 429])
def test_provider_fallback_refuses_pinned_route(isolated, provider, status):
    steps = []

    def physical_attempt(step):
        steps.append(step)
        return "foreign response"

    request = route(provider, {"provider": PIN, "model": MODEL})
    assert aux._drive_ladder(aux._ladder_provider_fallback(ApiError(status), request), physical_attempt) is None
    assert steps == []
    assert request.route_info == {}


@pytest.mark.parametrize("provider", [PIN, "agy", "auto"])
def test_main_chain_refuses_pinned_origin(isolated, provider):
    with aux.scoped_runtime_main({"provider": PIN, "model": MODEL}):
        assert aux._try_main_fallback_chain("compression", provider, "rate limit") == (None, None, "")


@pytest.mark.parametrize("status", [401, 402, 429])
def test_credential_rung_cannot_rotate_pinned_account(isolated, status):
    before = seed_pool(PIN)
    request = route()
    error = ApiError(status)
    steps = []

    def physical_attempt(step):
        steps.append(step)
        return "retried with another credential"

    assert aux._drive_ladder(aux._ladder_credential_rungs(error, request, {}, False), physical_attempt) == (None, error)
    assert steps == []
    assert read_credential_pool(PIN) == before


@pytest.mark.parametrize("status", [401, 402, 429])
def test_pool_recovery_does_not_touch_pinned_credentials(isolated, status):
    before = seed_pool(PIN)
    assert aux._recover_provider_pool(PIN, ApiError(status), failed_api_key="fixture-credential-1") is False
    assert read_credential_pool(PIN) == before


def test_unlisted_pool_identity_cannot_be_borrowed_by_auto_pinned_request(isolated):
    request = route("auto", {"provider": PIN, "model": MODEL})
    foreign_before = seed_pool("openrouter")
    # An auto client's host would ordinarily select this pool. Origin authorization must win.
    request = request._replace(client=SimpleNamespace(base_url="https://openrouter.ai/api/v1",
                                                       api_key="fixture-credential-1"),
                               base_info="https://openrouter.ai/api/v1")
    error = ApiError(402)
    assert aux._drive_ladder(aux._ladder_credential_rungs(error, request, {}, False),
                             lambda step: "unauthorized pooled response") == (None, error)
    assert read_credential_pool("openrouter") == foreign_before


def test_ordinary_provider_keeps_explicitly_configured_fallback(isolated):
    isolated("openrouter")
    steps = []

    def physical_attempt(step):
        steps.append(step)
        return "approved response"

    response = aux._drive_ladder(aux._ladder_provider_fallback(ApiError(402), route("openrouter")),
                                 physical_attempt)
    assert response == "approved response"
    assert len(steps) == 1 and steps[0].kind == "fallback"
    assert steps[0].args[1] == FOREIGN["model"]


def test_explicit_auxiliary_route_keeps_own_authorized_fallback(isolated):
    # Selecting an independent ordinary auxiliary route is distinct from recovering the pinned route.
    with aux.scoped_runtime_main({"provider": PIN, "model": MODEL}):
        result = aux._drive_ladder(aux._ladder_provider_fallback(ApiError(402), route("openrouter")),
                                   lambda step: "operator auxiliary fallback")
    assert result == "operator auxiliary fallback"


def test_main_chain_obeys_ordinary_session_not_pinned_profile_default(isolated):
    with aux.scoped_runtime_main({"provider": "openrouter", "model": "ordinary-model"}):
        client, model, provider = aux._try_main_fallback_chain("compression", "auto", "rate limit")
    assert provider == "custom" and model == FOREIGN["model"]
    assert client is not None
    client.close()


def test_ordinary_pool_recovery_still_rotates(isolated):
    isolated("openrouter")
    before = seed_pool("openrouter")
    assert aux._recover_provider_pool("openrouter", ApiError(402), failed_api_key="fixture-credential-1") is True
    assert read_credential_pool("openrouter") != before
    entry = load_pool("openrouter").peek()
    assert entry is not None and entry.id == "credential-2"


@pytest.mark.parametrize("status", [401, 402, 429])
@pytest.mark.parametrize("async_mode", [False, True])
def test_full_recovery_uses_origin_snapshot_not_changed_profile(isolated, status, async_mode):
    isolated("openrouter")
    before = seed_pool(PIN)
    request = route("auto", {"provider": PIN, "model": MODEL})
    error = ApiError(status)
    ladder = aux._aux_recovery_ladder(
        error, client=request.client, kwargs={"model": MODEL}, task="compression",
        async_mode=async_mode, base_info=request.base_info, resolved_provider="auto",
        resolved_model=MODEL, resolved_base_url=request.resolved_base_url,
        resolved_api_key=request.resolved_api_key, resolved_api_mode=request.resolved_api_mode,
        final_model=MODEL, max_tokens=None, main_runtime=request.main_runtime, route_info={},
    )
    attempts = []

    def physical_attempt(step):
        attempts.append(step)
        return "unauthorized recovery"

    async def async_physical_attempt(step):
        return physical_attempt(step)

    with pytest.raises(ApiError) as failure:
        if async_mode:
            asyncio.run(aux._drive_ladder_async(ladder, async_physical_attempt))
        else:
            aux._drive_ladder(ladder, physical_attempt)
    assert failure.value is error
    assert attempts == []
    assert read_credential_pool(PIN) == before


def test_effective_client_identity_cannot_hide_behind_an_ordinary_label(isolated):
    isolated("openrouter")
    request = route("openrouter", {"provider": "openrouter", "model": "ordinary-model"})
    request.client._hermes_aux_effective_provider = PIN
    assert aux._drive_ladder(aux._ladder_provider_fallback(ApiError(402), request),
                             lambda step: "foreign response") is None


def test_ambiguous_profile_policy_fails_closed(isolated, monkeypatch):
    from providers import get_provider_profile

    profile = get_provider_profile(PIN)
    assert profile is not None
    monkeypatch.setattr(profile, "explicit_route_only", "true")
    with pytest.raises(ValueError, match="ambiguous explicit_route_only"):
        aux._recover_provider_pool(PIN, ApiError(402))
