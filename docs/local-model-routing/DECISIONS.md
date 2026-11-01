# Architecture Decision Records (ADRs), Security Invariants & Known Limitations

## ADR-001: Native Model Map Backend as Primary Delegation Authority

- **Status**: Accepted & Operational
- **Context**: Hermes supports multiple delegation backends: `single`, `model_map`, and `profile_routes`. Earlier prototypes evaluated multi-agent wrappers and external script dispatchers.
- **Decision**: Standardize exclusively on the native `model_map` backend provided by the `advanced-delegation` plugin. `fast` is established as the default route.
- **Consequences**: Delegation decisions are declarative, inspectable via `hermes delegation config --show`, and enforced uniformly without introducing external runtime dependencies.

---

## ADR-002: Isolation of Claude DirectSDK Routes from Automatic Fallback Chains

- **Status**: Accepted & Enforced
- **Context**: The official `claude-subscription-directsdk-experimental` plugin runs as an external process (`/home/gabo/.local/bin/claude`) authenticating via `~/.claude/` OAuth sessions. Hermes core commit `b6a5c0d728` introduced strict `AccountBinding` verification (`_codex_principal_identity`, exact account pins) on fallback candidate transitions to prevent credential leaks across accounts.
- **Problem Encountered**: When an automatic fallback was attempted between an in-memory client and an external process, the fallback machine threw `AccountBindingError: Resolved model_map changed account credential`.
- **Rejected Alternative 1: Synthetic Credential Workaround**: Injecting fake account IDs or bypassing `_check_account` in core code. Rejected because it violates security boundaries, risks credential collision, and breaks on upstream core updates.
- **Rejected Alternative 2: Falling Back to Anthropic Pay-Per-Token API**: Rejected because user policy strictly forbids commercial pay-per-token API metering.
- **Decision**: Configure all Claude Pro DirectSDK routes with `fallback_providers: []`. On quota exhaustion or 429, the subagent returns a clean failure. The parent orchestrator evaluates the failure and executes an explicit, audited re-delegation to another route if appropriate.
- **Consequences**: Zero risk of credential corruption. Explicit audit trail for all failover actions.

---

## ADR-003: Enforcement of Maximum Two Fallbacks per Route

- **Status**: Accepted & Enforced
- **Context**: Candidate configurations previously specified chains of 3 or 4 fallback models.
- **Decision**: Limit every route's `fallback_providers` list to at most **2** entries.
- **Rationale**: Hermes core enforces `len(fallback_providers) <= 2` in `prepare_model_map_route` (`agent/delegation_fallback.py`). Violating this limit causes an immediate `ValueError`. Furthermore, bounded chains prevent unbounded latency and cascading rate-limit loops across providers.

---

## ADR-004: Version-Pinned Claude Identifiers

- **Status**: Accepted & Enforced
- **Context**: Generic model aliases such as `claude-3-7-sonnet` or unversioned aliases can resolve dynamically to different model revisions, disrupting prompt cache hit rates and context length expectations.
- **Decision**: Pin explicit Claude 5.5 identifiers with explicit context window parameters: `claude-opus-5-5[1m]`, `claude-sonnet-5-5[1m]`, and `claude-haiku-5-5[1m]`.
- **Consequences**: Predictable prompt caching, verified 1M context capabilities, and immunity to backend alias remapping.

---

## ADR-005: Elimination of Synthetic Replacement Routes

- **Status**: Accepted & Enforced
- **Context**: Historical configurations accumulated 68 routes, including suffixes like `__replacement_1` and `__replacement_2`.
- **Decision**: Prune all synthetic replacement aliases, retaining a clean, authoritative catalog of **21 functional routes**.
- **Rationale**: Replacement routes did not function as automatic fallbacks (which require declaration inside `fallback_providers`). They inflated configuration size, confused operators, and risked accidental selection of suboptimal models.

---

## ADR-006: Auxiliary Goal Judge Dynamic Auto-Resolution

- **Status**: Accepted & Enforced
- **Context**: Hermes includes an auxiliary goal evaluation subsystem (`auxiliary.goal_judge`).
- **Decision**: Retain `auxiliary.goal_judge.provider: auto`.
- **Rationale**: Dynamic auto-resolution binds the orchestrator's authenticated client (`gemini-3.8-flash-medium` via Antigravity) at turn evaluation time. It requires no distinct credentials or separate API routing.

---

## Known Limitations

1. **Manual vs. Automatic Failover**: A failed Claude Pro route (`fallback_providers: []`) requires parent orchestrator awareness to re-delegate. It cannot transparently swap underneath an active turn.
2. **Fixed-Effort Model Incompatibilities**: Models such as `gemini-4-argon-high` and `gpt-6-astra` are fixed at `high` reasoning effort. Setting `reasoning_effort: medium` on these routes triggers catalog validation errors.
3. **Cross-Profile Isolation**: Model Map configurations reside in `~/.hermes/config.yaml`. Profiles located under `~/.hermes/profiles/<name>/` maintain their own configuration state and do not inherit root routes automatically.
