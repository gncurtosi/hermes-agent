"""Narrow operator authority for official model_map chains, not a router.

A private typed envelope carries authority across the existing fallback_model seam.
JSON/tool arguments and inherited global chains cannot mint it. No child is replayed.
"""
from __future__ import annotations

from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, field, replace

_REVIEW_ROLES = frozenset({"independent_science_review", "critical_audit",
                           "review_openai_author", "review_claude_author"})
_PRIMARY_FIELDS = ("provider", "model", "base_url", "api_key", "api_mode", "reasoning_effort", "service_tier")


class AccountBindingError(ValueError):
    """A local identity/endpoint refusal is not provider unavailability."""


@dataclass(frozen=True)
class DelegationTaskContext:
    author_family: str | None = None
    bounded_suitable: bool = False
    source: str = "trusted-artifact-context"
    parent_model: str | None = None
    parent_provider: str | None = None
    contributor_families: frozenset = frozenset()


_task_context: ContextVar[DelegationTaskContext | None] = ContextVar("delegation_task_context", default=None)


@contextmanager
def delegation_task_context(*, author_family=None, bounded_suitable=False):
    """Trusted caller assertion for THIS artifact/task; never a model-facing field.

    Bind separately for different authors/tasks. Unknown/mixed authors remain None.
    The route snapshots this before asynchronous dispatch; no parent context leaks.
    """
    if author_family not in {None, "openai", "anthropic", "google"}:
        raise ValueError("Unknown actual author family")
    if type(bounded_suitable) is not bool:
        raise ValueError("bounded_suitable must be a boolean")
    token = _task_context.set(DelegationTaskContext(
        author_family, bounded_suitable, contributor_families=frozenset({author_family})))
    try:
        yield
    finally:
        _task_context.reset(token)


def model_family(model):
    """Unknown model families cannot establish independent review."""
    slug = str(model).lower().split("/")[-1]
    for prefix, family in (("claude-", "anthropic"), ("gemini-", "google"), ("gpt-", "openai")):
        if slug.startswith(prefix):
            return family
    return None


def runtime_task_context(parent):
    """Actual runtime identity only; task arguments and role names confer no trust."""
    explicit = _task_context.get()
    model, provider = getattr(parent, "model", None), getattr(parent, "provider", None)
    if explicit is not None:
        return replace(explicit, parent_model=model, parent_provider=provider)
    contributors = _runtime_contributors(parent)
    author = next(iter(contributors)) if len(contributors) == 1 else None
    return DelegationTaskContext(author, False, "parent-runtime", model, provider, contributors)


def _runtime_contributors(parent):
    model, provider = getattr(parent, "model", None), getattr(parent, "provider", None)
    family = model_family(model)
    known = {"openai-codex": "openai", "openai": "openai", "anthropic": "anthropic", "gemini": "google"}
    if not isinstance(provider, str) or provider in {"", "auto"} or known.get(provider, family) != family:
        family = None
    inherited = getattr(parent, "_delegation_contributor_families", frozenset())
    policy = getattr(parent, "_model_map_policy", None)
    if isinstance(policy, ModelMapPolicy):
        inherited = inherited | policy.context.contributor_families
        inherited = inherited | {model_family(policy.primary["model"])}
    transitions = getattr(parent, "_model_map_transitions", [])
    return frozenset(inherited) | {family} | {model_family(t.get("model")) for t in transitions}


def inherit_task_contributors(child, routing_cfg, parent=None):
    policy = (routing_cfg or {}).get("_model_map_policy")
    context = policy.context if isinstance(policy, ModelMapPolicy) else (routing_cfg or {}).get("_delegation_task_context")
    child._delegation_contributor_families = (
        context.contributor_families if isinstance(context, DelegationTaskContext) else _runtime_contributors(parent))


def record_child_contributors(parent, child):
    if parent is None:
        return
    # Sibling completions may arrive on different workers; reuse the owning parent's lock.
    with getattr(parent, "_active_children_lock", None) or nullcontext():
        parent._delegation_contributor_families = (
            getattr(parent, "_delegation_contributor_families", frozenset()) | _runtime_contributors(child))


@dataclass(frozen=True)
class AccountBinding:
    endpoint: str
    source: str
    principal: tuple | None = field(default=None, repr=False)
    credential: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class ModelMapPolicy:
    label: str
    primary: dict = field(repr=False)
    chain: tuple = field(repr=False)
    context: DelegationTaskContext
    independent: bool
    accounts: tuple = field(repr=False)


class AuthorizedFallbackChain(list):
    """Internal, non-JSON authority envelope; normal fallback lists confer none."""

    def __init__(self, chain, policy):
        super().__init__(deepcopy(chain))
        self.policy = policy


def _check_independence(entry, context):
    if context.author_family is None:
        raise ValueError("Independent review requires known actual author family")
    family = model_family(entry.get("model"))
    if family is None or family == context.author_family:
        raise ValueError("Independent review route is not independent of actual author")


def _route_key(entry):
    return (entry["provider"], entry["model"], entry.get("base_url", "").rstrip("/"))


def _validate_entry(entry):
    from hermes_cli.route_pin import policy_profile, validate_selection
    from hermes_cli.fallback_config import resolve_entry_api_key
    from hermes_constants import parse_reasoning_effort
    if not isinstance(entry, dict):
        raise ValueError("model_map fallback must be a route mapping")
    for key in ("provider", "model"):
        value = entry.get(key)
        if not isinstance(value, str) or not value or value != value.strip() or value == "auto":
            raise ValueError(f"model_map needs an exact {key}")
    if parse_reasoning_effort(entry.get("reasoning_effort")) is None:
        raise ValueError("model_map routes require explicit valid reasoning_effort")
    profile = policy_profile(entry["provider"])
    credential = resolve_entry_api_key(entry)
    if (not (profile and profile.explicit_route_only) and not credential
            and entry["provider"] not in {"openai-codex", "anthropic"}):
        raise ValueError("model_map requires an exact account pin, not implicit pooled credentials")
    endpoint = entry.get("base_url") or (profile.base_url if profile else "")
    if not isinstance(endpoint, str) or not endpoint or endpoint != endpoint.strip():
        raise ValueError("model_map needs an exact endpoint (explicit or provider-owned)")
    validate_selection(entry["provider"], entry["model"], endpoint)
    return endpoint


def _snapshot_account(entry):
    from hermes_cli.fallback_config import resolve_entry_api_key
    endpoint = _validate_entry(entry)
    if entry["provider"] == "openai-codex":
        from agent.credential_pool import _codex_principal_identity
        creds = _readonly_codex_credentials()
        principal = _codex_principal_identity(creds.get("api_key"))
        if principal is None:
            raise ValueError("model_map Codex account identity is unknown")
        resolved_endpoint = creds["base_url"]
        if entry.get("base_url") and endpoint.rstrip("/") != resolved_endpoint.rstrip("/"):
            raise ValueError("model_map Codex account endpoint differs from configuration")
        from hermes_cli.route_pin import validate_selection
        validate_selection(entry["provider"], entry["model"], resolved_endpoint)
        return AccountBinding(resolved_endpoint, "codex-readonly-principal", principal)
    credential = resolve_entry_api_key(entry)
    if entry["provider"] == "anthropic" and not credential:
        from agent.anthropic_credentials import read_claude_code_credentials, is_claude_code_token_valid
        creds = read_claude_code_credentials()
        if not creds or not is_claude_code_token_valid(creds) or not creds.get("accessToken"):
            raise ValueError("model_map Anthropic account needs a valid existing Claude Code login")
        return AccountBinding(endpoint, "claude-code-readonly-exact", credential=creds["accessToken"])
    return AccountBinding(endpoint, "configured-credential" if credential else "provider-owned", credential=credential)


def _readonly_codex_credentials():
    """Reject multi-principal stores BEFORE a resolver can select one arbitrarily."""
    import json
    from agent.credential_pool import _codex_principal_identity
    from hermes_cli.auth import _auth_file_path
    from hermes_cli.auth_codex import resolve_codex_runtime_credentials
    path = _auth_file_path()
    try:
        store = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
        rows = store.get("credential_pool", {}).get("openai-codex", [])
        token = store.get("providers", {}).get("openai-codex", {}).get("tokens", {}).get("access_token")
        tokens = [token] if token else []
        tokens.extend(row["access_token"] for row in rows if row.get("access_token"))
    except (ValueError, TypeError, AttributeError, KeyError):
        raise AccountBindingError("model_map Codex account store has ambiguous principal metadata") from None
    identities = {_codex_principal_identity(token) for token in tokens}
    if None in identities or len(identities) > 1:
        raise AccountBindingError("model_map Codex account has ambiguous multiple principals")
    creds = resolve_codex_runtime_credentials(read_only=True)
    identity = _codex_principal_identity(creds.get("api_key"))
    if identities and identity not in identities:
        raise AccountBindingError("model_map Codex resolved an ambiguous account principal")
    return creds


def _check_account(binding, token, headers):
    if binding.principal is not None:
        from agent.credential_pool import _codex_principal_identity
        if _codex_principal_identity(token) != binding.principal:
            raise AccountBindingError("Resolved model_map changed Codex account principal")
        headers = {str(k).lower(): v for k, v in (headers or {}).items()}
        if headers.get("chatgpt-account-id") != binding.principal[0]:
            raise AccountBindingError("Resolved model_map Codex account header identity changed")
        authorization = headers.get("authorization")
        if authorization is not None and authorization != f"Bearer {token}":
            raise AccountBindingError("Resolved model_map Codex authorization header changed")
    elif binding.credential is not None and token != binding.credential:
        raise AccountBindingError("Resolved model_map changed account credential")


def resolution_credentials(policy, index):
    """Private resolution hints, never materialised into model_map/YAML or reports."""
    binding = policy.accounts[index]
    if binding.principal is not None:
        from agent.codex_headers import codex_account_headers
        creds = _readonly_codex_credentials()
        token = creds.get("api_key")
        _check_account(binding, token, codex_account_headers(token or ""))
        if creds.get("base_url", "").rstrip("/") != binding.endpoint.rstrip("/"):
            raise AccountBindingError("Resolved model_map Codex account endpoint changed")
        return binding.endpoint, token
    if binding.source == "claude-code-readonly-exact":
        from agent.anthropic_credentials import read_claude_code_credentials, is_claude_code_token_valid
        creds = read_claude_code_credentials()
        if not creds or not is_claude_code_token_valid(creds):
            raise AccountBindingError("model_map Anthropic borrowed account is no longer valid")
        _check_account(binding, creds.get("accessToken"), {})
    return binding.endpoint, binding.credential


def prepare_model_map_route(route, config, backend, parent=None):
    """Grant authority ONLY to an exact operator-configured named option's own list."""
    if backend != "model_map" or not route.get("label"):
        return route
    context = runtime_task_context(parent)
    label = route["label"]
    if label in _REVIEW_ROLES:
        _check_independence(route, context)
    options = config.get("backends", {}).get("model_map", {}).get("options", [])
    entries = [o for o in options if isinstance(o, dict) and o.get("name") == label]
    if len(entries) != 1:
        raise ValueError("model_map route has no unique operator-configured option")
    entry = entries[0]
    expected = {k: entry[k] for k in _PRIMARY_FIELDS if k in entry}
    chain = entry.get("fallback_providers", [])
    if not isinstance(chain, list) or len(chain) > 2:
        raise ValueError("model_map allows at most two ordered fallback providers")
    expected.update(label=label, **({"fallback_providers": chain} if "fallback_providers" in entry else {}))
    if route != expected:
        raise ValueError("model_map route differs from operator configuration")
    independent = label in _REVIEW_ROLES or entry.get("independent_review") is True
    if independent:
        _check_independence(route, context)
    if not chain:
        # No transition authority is needed; retain legacy implicit-auth resolution.
        return {**route, "fallback_providers": [], "_delegation_task_context": context}
    seen = set()
    for candidate in [route, *chain]:
        _validate_entry(candidate)
        key = _route_key(candidate)
        if key in seen:
            raise ValueError("model_map fallback chain contains a loop")
        seen.add(key)
    accounts = tuple(_snapshot_account(candidate) for candidate in [route, *chain])
    policy = ModelMapPolicy(label, deepcopy(route), tuple(deepcopy(chain)), context, independent, accounts)
    # Explicit [] prevents delegation/global inheritance, including on chainless options.
    return {**route, "fallback_providers": deepcopy(chain), "_model_map_policy": policy}


def child_fallback_envelope(chain, routing_cfg):
    policy = routing_cfg.get("_model_map_policy") if isinstance(routing_cfg, dict) else None
    if not isinstance(policy, ModelMapPolicy):
        if (isinstance(routing_cfg, dict) and routing_cfg.get("fallback_providers") == []
                and isinstance(routing_cfg.get("_delegation_task_context"), DelegationTaskContext)):
            return []
        return chain
    if list(chain or []) != list(policy.chain):
        raise ValueError("model_map fallback chain changed during resolution")
    return AuthorizedFallbackChain(chain or [], policy)


def install_policy(agent, fallback_model):
    if not isinstance(fallback_model, AuthorizedFallbackChain):
        return
    policy = fallback_model.policy
    kwargs = getattr(agent, "_client_kwargs", None) or {}
    _check_account(policy.accounts[0], getattr(agent, "api_key", None), kwargs.get("default_headers"))
    client = getattr(agent, "client", None)
    if client is not None:
        _check_account(policy.accounts[0], client.api_key, getattr(client, "default_headers", None))
    if _route_key({"provider": agent.provider, "model": agent.model, "base_url": agent.base_url}) != (
            policy.primary["provider"], policy.primary["model"], policy.accounts[0].endpoint.rstrip("/")):
        raise ValueError("Resolved model_map primary differs from configured route")
    agent._model_map_policy = policy
    agent._model_map_attempted = set()
    agent._model_map_tool_barrier = False
    agent._model_map_transitions = []


def pinned_agent(agent):
    from hermes_cli.route_pin import provider_pins_route
    return isinstance(getattr(agent, "_model_map_policy", None), ModelMapPolicy) or provider_pins_route(getattr(agent, "provider", None))


def fallback_blocked(agent, reason=None):
    policy = getattr(agent, "_model_map_policy", None)
    if isinstance(policy, ModelMapPolicy):
        if reason is not None:
            agent._model_map_fallback_reason = str(getattr(reason, "value", None) or reason)
        return getattr(agent, "_model_map_tool_barrier", False) is True
    blocked = pinned_agent(agent)
    if blocked:
        agent._fallback_chain, agent._fallback_model = [], None
    return blocked


def fallback_allowed(agent, reason, *, should_fallback=True):
    """Authority permits provider failure recovery, not local policy/security bypass."""
    if not isinstance(getattr(agent, "_model_map_policy", None), ModelMapPolicy):
        return True
    allowed = {"auth", "auth_permanent", "billing", "rate_limit", "upstream_rate_limit",
               "upstream_blocked", "overloaded", "server_error", "timeout", "model_not_found",
               "model_entitlement", "incomplete_response"}
    return should_fallback is True and getattr(reason, "value", reason) in allowed


def classified_fallback_allowed(agent, classified):
    # Retryable availability verdicts use the retry budget rather than should_fallback.
    availability = classified.retryable and classified.reason.value in {"overloaded", "server_error", "timeout"}
    return fallback_allowed(agent, classified.reason, should_fallback=classified.should_fallback or availability)


def check_bind(agent, entry, provider, model):
    """Gate source AND destination before client construction. Consume attempts once."""
    from hermes_cli.route_pin import provider_pins_route, validate_selection
    policy = getattr(agent, "_model_map_policy", None)
    if not isinstance(policy, ModelMapPolicy):
        if pinned_agent(agent) or provider_pins_route(provider):
            raise ValueError("Pinned provider requires an explicit operator model/provider switch")
        validate_selection(provider, model, entry.get("base_url"))
        return
    index = getattr(agent, "_fallback_index", 0) - 1
    if (fallback_blocked(agent) or not 0 <= index < len(policy.chain)
            or entry != policy.chain[index] or (provider, model) != (entry["provider"], entry["model"])):
        raise ValueError("Unauthorized model_map fallback transition")
    key = _route_key(entry)
    if key in agent._model_map_attempted:
        raise ValueError("model_map route already attempted")
    agent._model_map_attempted.add(key)
    _validate_entry(entry)
    if policy.independent:
        _check_independence(entry, policy.context)
    if (policy.label == "implementation" and index == 1 and "terra" in model.lower()
            and not policy.context.bounded_suitable):
        raise ValueError("Terra fallback requires trusted bounded task suitability")


def check_resolved(agent, entry, client, resolved_model, model, provider):
    """The existing resolver must honor exact selection; never repair/substitute it."""
    policy = getattr(agent, "_model_map_policy", None)
    if not isinstance(policy, ModelMapPolicy):
        return
    binding = policy.accounts[agent._fallback_index]
    if resolved_model != model or str(client.base_url).rstrip("/") != binding.endpoint.rstrip("/"):
        raise AccountBindingError("Resolved model_map fallback changed model or endpoint")
    effective = getattr(client, "_hermes_aux_effective_provider", provider)
    if effective != provider:
        raise AccountBindingError("Resolved model_map fallback changed provider/account")
    _check_account(binding, client.api_key, getattr(client, "default_headers", None))


def finish_bind(agent, entry):
    if not isinstance(getattr(agent, "_model_map_policy", None), ModelMapPolicy):
        return
    from hermes_constants import parse_reasoning_effort
    agent.reasoning_config = parse_reasoning_effort(entry["reasoning_effort"])
    agent._credential_pool = agent._credential_pool_entry_id = None
    route = getattr(agent, "_delegate_route", None)
    route_label = route.get("label") if isinstance(route, dict) else None
    agent._model_map_transitions.append({
        "provider": agent.provider, "model": agent.model, "base_url": agent.base_url,
        "reason": getattr(agent, "_model_map_fallback_reason", "provider failure"),
        "reasoning_effort": entry["reasoning_effort"],
        **({"route": route_label} if route_label else {}),
    })


def mark_tool_barrier(agent):
    """Set before ANY tool dispatch, including reads, errors, denied or inline tools."""
    if isinstance(getattr(agent, "_model_map_policy", None), ModelMapPolicy):
        agent._model_map_tool_barrier = True


def transition_report(agent):
    transitions = getattr(agent, "_model_map_transitions", None)
    if not isinstance(transitions, list):
        return {}
    clean = []
    for t in transitions:
        if isinstance(t, dict):
            clean.append({
                k: v for k, v in t.items()
                if not any(secret in k.lower() for secret in ("key", "token", "secret", "auth", "password"))
            })
    return {"fallback_transitions": clean}


def caller_report(routing_cfg):
    policy = routing_cfg.get("_model_map_policy")
    context = policy.context if isinstance(policy, ModelMapPolicy) else routing_cfg.get("_delegation_task_context")
    if not isinstance(context, DelegationTaskContext):
        return {}
    return {"author_provenance": {
        "source": context.source, "parent_model": context.parent_model, "parent_provider": context.parent_provider,
        "author_family": context.author_family,
        "contributor_families": sorted(f or "unknown" for f in context.contributor_families)}}


def check_reasoning(agent):
    if not isinstance(getattr(agent, "_model_map_policy", None), ModelMapPolicy):
        return
    flags = ("_reasoning_effort_rejected", "_reasoning_disable_rejected", "_ephemeral_reasoning_off")
    if any(getattr(agent, flag, False) is True for flag in flags):
        raise ValueError("model_map effort cannot be silently changed after rejection")
