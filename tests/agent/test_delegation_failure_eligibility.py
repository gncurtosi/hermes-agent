"""Authorised route changes never bypass local policy or replay completed tools."""
from types import SimpleNamespace

import pytest

from agent.error_classifier import FailoverReason
from tests.agent.test_delegation_fallback_authority import authorized_agent


@pytest.mark.parametrize("reason", [FailoverReason.unknown, FailoverReason.format_error,
    FailoverReason.content_policy_blocked, FailoverReason.data_policy_denied,
    FailoverReason.provider_policy_blocked, FailoverReason.ssl_cert_verification,
    FailoverReason.reasoning_mandatory])
def test_authority_is_not_permission_to_bypass_local_or_security_failures(reason, monkeypatch):
    from agent.chat_completion_helpers import try_activate_fallback
    from agent import auxiliary_client
    agent = authorized_agent()
    monkeypatch.setattr(auxiliary_client, "resolve_provider_client", lambda *a, **kw: pytest.fail("must not resolve"))
    assert try_activate_fallback(agent, reason=reason) is False
    assert agent._fallback_index == 0


def test_codex_app_server_classifier_opt_out_is_respected(monkeypatch):
    from agent import turn_recovery
    from agent.error_classifier import ClassifiedError
    agent = authorized_agent()
    agent._has_pending_fallback = lambda: True
    agent._buffer_diagnostic_status = lambda *a: None
    agent._try_activate_fallback = lambda **kw: pytest.fail("classifier denied fallback")
    monkeypatch.setattr(turn_recovery, "classify_api_error", lambda *a, **kw:
        ClassifiedError(FailoverReason.billing, should_fallback=False))
    assert turn_recovery.activate_codex_app_server_fallback(agent, {"error": "fixture"}) is False


def test_codex_app_server_failure_after_tools_never_replays(monkeypatch):
    from agent import turn_recovery
    from agent.error_classifier import ClassifiedError
    agent = authorized_agent()
    agent._has_pending_fallback = lambda: True
    agent._buffer_diagnostic_status = lambda *a: None
    agent._try_activate_fallback = lambda **kw: pytest.fail("app-server tools may already have run")
    monkeypatch.setattr(turn_recovery, "classify_api_error", lambda *a, **kw:
        ClassifiedError(FailoverReason.rate_limit, should_fallback=True))
    result = {"error": "fixture", "messages": [{"role": "tool", "content": "submitted"}]}
    assert turn_recovery.activate_codex_app_server_fallback(agent, result) is False
    assert agent._fallback_index == 0


def test_classifier_opt_out_cannot_be_overridden_by_model_map():
    from agent.delegation_fallback import fallback_allowed
    agent = authorized_agent()
    assert fallback_allowed(agent, FailoverReason.billing, should_fallback=False) is False
    assert fallback_allowed(agent, FailoverReason.billing, should_fallback=True) is True


def test_real_executed_side_effect_is_not_replayed_after_provider_failure(monkeypatch):
    from agent import tool_executor as executor
    from agent.chat_completion_helpers import try_activate_fallback
    agent = authorized_agent()
    agent._interrupt_requested = False
    agent._should_emit_quiet_tool_messages = lambda: False
    counter = []

    def execute(_agent, args, ctx):
        counter.append("submitted")
        return "submitted-once"

    monkeypatch.setitem(executor.INLINE_TOOL_EXECUTORS, "fixture_submit_once", execute)
    # Keep the actual sequential dispatch/call path; stub only middleware/persistence boundaries.
    monkeypatch.setattr(executor, "_run_sequential_tool_execution_middleware", lambda _agent, **kw:
        SimpleNamespace(args=kw["function_args"], result=kw["execute"](kw["function_args"])))
    rows = []
    monkeypatch.setattr(executor, "_publish_sequential_result", lambda *args, **kw:
        rows.append(args[3].result) or True)
    call = SimpleNamespace(id="once", function=SimpleNamespace(name="fixture_submit_once", arguments="{}"))
    executor._execute_tool_calls_sequential(agent, SimpleNamespace(tool_calls=[call]), [], "fixture-task", finalize=False)
    assert counter == ["submitted"]
    assert rows == ["submitted-once"]
    assert try_activate_fallback(agent, reason=FailoverReason.rate_limit) is False
    assert counter == ["submitted"]
    assert agent._fallback_index == 0
