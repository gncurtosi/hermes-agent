from types import SimpleNamespace

import pytest


def test_explicit_endpoint_without_token_must_not_select_pool(monkeypatch):
    from agent import auxiliary_client

    def forbid(*args, **kwargs):
        pytest.fail("partial explicit binding selected a credential pool")

    monkeypatch.setattr(auxiliary_client, "_select_pool_entry", forbid)
    monkeypatch.setattr(auxiliary_client, "_create_openai_client", forbid)
    client, model = auxiliary_client.resolve_provider_client(
        "openai-codex", model="gpt-fixture", raw_codex=True,
        explicit_base_url="https://chatgpt.com/backend-api/codex")
    assert client is None and model is None


def test_explicit_empty_token_must_not_select_pool(monkeypatch):
    from agent import auxiliary_client

    def forbid(*args, **kwargs):
        pytest.fail("empty explicit binding selected a credential pool")

    monkeypatch.setattr(auxiliary_client, "_select_pool_entry", forbid)
    monkeypatch.setattr(auxiliary_client, "_create_openai_client", forbid)
    client, model = auxiliary_client.resolve_provider_client(
        "openai-codex", model="gpt-fixture", raw_codex=True,
        explicit_api_key="", explicit_base_url="https://chatgpt.com/backend-api/codex")
    assert client is None and model is None


def test_explicit_token_without_endpoint_fails_closed(monkeypatch):
    from agent import auxiliary_client

    def forbid(*args, **kwargs):
        pytest.fail("partial explicit binding selected a credential pool")

    monkeypatch.setattr(auxiliary_client, "_select_pool_entry", forbid)
    monkeypatch.setattr(auxiliary_client, "_create_openai_client", forbid)
    client, model = auxiliary_client.resolve_provider_client(
        "openai-codex", model="gpt-fixture", raw_codex=True,
        explicit_api_key="fixture-token")
    assert client is None and model is None


def test_explicit_pair_wins_over_ambient_pool(monkeypatch):
    from agent import auxiliary_client
    from tests.agent.test_delegation_account_binding import codex_token

    def forbid(*args, **kwargs):
        pytest.fail("explicit binding selected a credential pool")

    monkeypatch.setattr(auxiliary_client, "_select_pool_entry", forbid)
    monkeypatch.setattr(auxiliary_client, "_create_openai_client", lambda **kw: SimpleNamespace(**kw))
    token = codex_token()
    endpoint = "https://chatgpt.com/backend-api/codex"
    client, model = auxiliary_client.resolve_provider_client(
        "openai-codex", model="gpt-fixture", raw_codex=True,
        explicit_api_key=token, explicit_base_url=endpoint)
    assert client.api_key == token
    assert client.base_url == endpoint
    assert model == "gpt-fixture"
