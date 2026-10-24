"""Apply the existing explicit-route policy before auxiliary recovery changes identity."""
from __future__ import annotations


def recovery_pins_route(provider: str | None, *, main_runtime: dict | None = None, client=None) -> bool:
    """An explicit auxiliary selection owns its route; auto inherits the bound session.

    A configured fallback list is not permission to override an explicit_route_only
    profile. There is no account-safe recovery contract for such a profile, so even
    same-provider pool rotation fails closed. Do not read legacy cross-session mirrors.
    """
    from agent import auxiliary_client as aux
    from hermes_cli.route_pin import effective_provider_pins_route, provider_pins_route

    identity = (provider or "").strip().lower()
    effective = aux._effective_provider_for_client(client, "") if client is not None else ""
    if provider_pins_route(identity) or provider_pins_route(effective):
        return True
    if identity not in {"", "auto", "main"}:
        return False
    runtime = main_runtime if main_runtime is not None else aux._RUNTIME_MAIN_CONTEXT.get()
    runtime = aux._normalize_main_runtime(runtime if runtime is not None else {})
    origins = (runtime.get("provider"), runtime.get("requested_provider"))
    if any(provider_pins_route(origin) for origin in origins):
        return True
    if any(origin and origin != "auto" for origin in origins):
        return False
    return effective_provider_pins_route(None)


def vision_model_default(provider, main_model, requested_model, *, main_runtime):
    """A pinned vision request keeps its exact model instead of a catalog replacement."""
    from agent import auxiliary_client as aux
    from hermes_cli.route_pin import provider_pins_route, validate_selection

    if provider_pins_route(provider):
        model = requested_model or main_model
        validate_selection(provider, model, main_runtime.get("base_url"))
        return model
    return aux._resolve_provider_vision_default(provider)
