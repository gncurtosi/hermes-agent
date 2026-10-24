"""Provider-owned client construction, shared by main and auxiliary requests.

Registered profiles own non-HTTP transports. Pinned construction failures must not
be converted into a standard-client or subscription fallback.
"""
from __future__ import annotations

from typing import Any


def _provider_supplied_client(agent, client_kwargs: dict) -> Any | None:
    """Resolve the main profile by name or endpoint; preserve its failure policy."""
    from agent.agent_runtime_helpers import _profile_for_base_url, _ra

    try:
        from providers import get_provider_profile
    except Exception:
        return None
    profile = None
    provider_name = (getattr(agent, "provider", "") or "").strip()
    if provider_name:
        try:
            profile = get_provider_profile(provider_name)
        except Exception:
            profile = None
    if profile is None:
        base_url = str(client_kwargs.get("base_url", "") or "").strip()
        if base_url:
            profile = _profile_for_base_url(base_url)
    if profile is None:
        return None
    try:
        return profile.create_client(**client_kwargs)
    except Exception as error:
        if profile.explicit_route_only:
            raise RuntimeError(f"Provider {profile.name!r} could not create its client; no other provider was tried") from error
        _ra().logger.warning(
            "Provider profile %r failed to create a client; falling back to the standard client path",
            getattr(profile, "name", provider_name) or "?", exc_info=True,
        )
        return None


def _api_key_profile_supplied_client(provider: str, **client_kwargs: Any) -> Any | None:
    """Ask an API-key profile for its transport before constructing a standard client."""
    from agent import auxiliary_client as aux
    from hermes_cli.route_pin import provider_pins_route

    try:
        from providers import get_provider_profile
        profile = get_provider_profile(provider)
    except Exception:
        return None
    if profile is None:
        return None
    try:
        return profile.create_client(**client_kwargs)
    except Exception as error:
        if provider_pins_route(provider):
            raise RuntimeError(f"Pinned provider {provider!r} could not create its client; no other transport was tried") from error
        aux.logger.warning("resolve_provider_client: provider profile %r failed to create an "
                           "auxiliary client; falling back to the standard client path",
                           provider, exc_info=True)
        return None


def _resolve_external_process_branch(req, creds: dict[str, Any]) -> tuple[Any, str | None]:
    """Construct the registered external-process transport after exact route validation."""
    from agent import auxiliary_client as aux
    from hermes_cli.route_pin import validate_selection

    logger = aux.logger
    provider = req.provider
    selected_model = req.model or (req.main_runtime.get("model") if req.main_runtime else None) or aux._read_main_model_for_aux()
    validate_selection(provider, selected_model, req.explicit_base_url or creds.get("base_url"))
    final_model = aux._normalize_resolved_model(selected_model, provider)
    try:
        from providers import get_provider_profile
        profile = get_provider_profile(provider)
    except Exception:
        logger.debug("External-process profile lookup failed for %s", provider, exc_info=True)
        profile = None
    if profile is not None:
        api_key = str(creds.get("api_key", "")).strip()
        base_url = str(creds.get("base_url", "")).strip()
        if not final_model:
            aux.logger.warning("resolve_provider_client: %s requested but no model was provided or configured", provider)
            return None, None
        if not api_key or not base_url:
            aux.logger.warning("resolve_provider_client: %s requested but external process credentials are incomplete", provider)
            return None, None
        try:
            client = profile.create_client(
                api_key=api_key, base_url=base_url,
                command=str(creds.get("command", "")).strip() or None, args=list(creds.get("args") or []))
        except Exception:
            logger.warning("resolve_provider_client: profile %r failed to create an external-process client",
                           provider, exc_info=True)
            client = None
        if client is not None:
            aux.logger.debug("resolve_provider_client: %s (%s)", provider, final_model)
            return aux._route_client(req, client, final_model)
    aux._log_once_debug(aux._LOGGED_UNSUPPORTED_EXTPROC_KEYS, provider,
                        "resolve_provider_client: external-process provider %s not directly supported", provider)
    return None, None
