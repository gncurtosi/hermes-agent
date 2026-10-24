"""Provider-scoped exact selection and no-automatic-route-substitution policy.

Ported from the frozen route_pin contract. These predicates gate existing Hermes
resolvers and recovery paths; they do not select a replacement route.
"""
from __future__ import annotations


def policy_profile(provider: str | None):
    from providers import get_provider_profile

    name = (provider or "").strip().lower()
    if not name or name == "auto":
        return None
    if name.startswith("custom:"):
        # Client resolution strips this prefix before looking up the registered
        # provider. Policy must inspect that same identity, not generic custom.
        from agent.auxiliary_client import _normalize_aux_provider

        name = _normalize_aux_provider(name)
    profile = get_provider_profile(name)
    if profile is not None:
        for field in ("strict_catalog", "explicit_route_only"):
            if type(getattr(profile, field, False)) is not bool:
                raise ValueError(f"Provider {profile.name!r} has an ambiguous {field} policy")
    return profile


def pinned_profile(provider: str | None):
    profile = policy_profile(provider)
    return profile if profile is not None and profile.explicit_route_only else None


def provider_pins_route(provider: str | None) -> bool:
    return pinned_profile(provider) is not None


def effective_provider_pins_route(requested: str | None) -> bool:
    from hermes_cli.runtime_provider import resolve_requested_provider

    return provider_pins_route(resolve_requested_provider(requested))


def missing_model_message(provider: str) -> str:
    profile = pinned_profile(provider)
    name = profile.name if profile is not None else provider
    return (f"Provider {name!r} was selected without a model. Pass an exact model from its own catalog; "
            "the configured default and other providers will not be used.")


def validate_selection(provider: str | None, model: str | None, base_url: str | None = None) -> None:
    """Reject an ambiguous, unlisted, or foreign-endpoint selection before credentials/I/O."""
    profile = policy_profile(provider)
    if profile is None:
        return
    if profile.explicit_route_only:
        if not (model or "").strip():
            raise ValueError(missing_model_message(profile.name))
        if base_url and base_url.rstrip("/") != profile.base_url.rstrip("/"):
            raise ValueError(f"Provider {profile.name!r} pins its endpoint; no other transport was tried")
    if profile.strict_catalog:
        catalog = profile.declared_models()
        if not catalog or model not in catalog:
            raise ValueError(
                f"{model!r} is not in the live {profile.name} catalog. No substitute model or transport "
                "was used; choose a listed model or switch explicitly with --provider.")
