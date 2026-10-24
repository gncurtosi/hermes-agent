# Operator-authorized delegation fallback chains

`agent/delegation_fallback.py` is a bounded exception to provider route pins, not
an alternate router. It uses the existing official `model_map` provider's
`fallback_providers` and the existing child/fallback lifecycle. It never creates
or replays a child task.

Only a named route matching the operator's `delegation.backends.model_map.options`
entry exactly receives a private typed authority envelope. A delegation-wide,
parent-inherited, JSON-supplied, or another backend's chain cannot authorize a
pinned transition. Named model-map routes without their own chain receive `[]`,
not an inherited chain. At most two replacement entries are accepted. Duplicate
routes, malformed entries, missing/invalid effort, and ambiguous endpoints are
refused. Each destination is checked independently against its provider's exact
catalog and endpoint policy before client construction; resolved model, endpoint,
provider identity and an explicitly selected credential must agree.

Every route in an authorized chain must specify `reasoning_effort`. The selected
replacement's effort wins over global reasoning settings. Rejection cannot
silently remove the effort on the next request. Credential rotation and child
pool leasing cannot select a different account for these children. Provider-owned
account selection remains fixed. The authority reader never refreshes, adopts,
leases, or writes credentials.

Any tool-dispatch attempt permanently closes fallback for the child, including
read-only, inline, denied, malformed, parallel and segmented calls. This is an
intentionally conservative side-effect barrier; it is not reset between turns.
Attempted destinations cannot be revisited if an outer retry resets its index.
Cached prompt identity is not rewritten for these transitions.

## Trusted artifact context

Independent review cannot infer authorship from a role label or task text.
The production `_route_to_task_route` path snapshots the parent's actual runtime
model/provider. Known model families establish author identity; unknown, conflicting,
or mixed contributor families fail closed for independent review. Child construction
inherits contributor families and returning children conservatively extend the parent's
contributors. Route reports include the provenance source and runtime model/provider.
Trusted internal callers can override this for a particular artifact before routing:

```python
from agent.delegation_fallback import delegation_task_context

with delegation_task_context(author_family="openai", bounded_suitable=False):
    # Invoke the normal delegation lifecycle here, not a custom router.
    ...
```

The recognized actual author families are `openai`, `anthropic`, and `google`.
Unknown or mixed provenance must remain `None`. Metadata is snapshotted into the
route before background dispatch. Bind tasks separately when their authors or
suitability differ; do not populate this context from model-supplied assertions.
`independent_science_review`, `critical_audit`, `review_openai_author`, and
`review_claude_author` require known provenance; an option may also declare
`independent_review: true`. Unknown reviewer families or any replacement in the
actual author's family are refused. Labels naming an author are not evidence.

Only Terra in `implementation`'s second fallback position requires the trusted
caller to assert `bounded_suitable=True` for the actual task. Other Terra roles
(including repository scouting, experimental baselines, and maintenance) do not
inherit that restriction. No model-facing suitability switch is added.

Delegation results retain their existing route report and add
`fallback_transitions` with the reason, actual provider/model/endpoint and effort.
Credential values and account identifiers are not included. Ordinary providers
need explicit credential selection or a provider-owned `explicit_route_only` pin.
Two existing authentication sources have private, read-only bindings:

- `openai-codex`: the existing read-only runtime resolver and stable
  `(chatgpt_account_id, sub)` helper establish one unambiguous principal plus its
  exact endpoint. A rotated token for the same principal is accepted. Both the
  actual token and the independently constructed account header must match;
  different subjects in a shared workspace are different principals.
- `anthropic`: the existing Claude Code reader snapshots a valid borrowed access
  credential and its endpoint. With no authenticated stable principal claim,
  conservative exact credential equality is required; rotation fails closed.

No credential is copied into model_map configuration or logs. Chainless options
retain legacy authentication resolution and require no new account pin; explicit
`[]` still suppresses inherited fallback. Only allowlisted provider, quota, and
availability failures can activate an authorized transition. Classified local or
security-policy refusals cannot gain authority from the chain. Account/endpoint
binding failures terminate the walk rather than being treated as unavailable routes.
Boot-time primary
credential-resolution or client-construction failures still fail closed before a
child runs; this change does not replay failed construction through another route.
