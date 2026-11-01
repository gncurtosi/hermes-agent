# Hermes Local Model Map Routing Architecture

## 1. Executive Summary

This directory documents the production **native Model Map delegation architecture** running on Hermes Agent (`v0.8.0`) at commit `b6a5c0d728` on branch `fix/model-map-fallback-authority-20261026`.

The deployment enforces strict consumer subscription isolation across three commercial AI ecosystems:
1. **Google Antigravity Subscription** (`antigravity-subscription-directsdk`, v0.4.1) — drives the main orchestrator (`gemini-3.8-flash-medium`) and reserve models.
2. **OpenAI Codex Subscription** (`openai-codex`) — drives engineering implementation, hard debugging, and cross-family review.
3. **Anthropic Claude Pro Subscription** (`claude-subscription-directsdk-experimental`, v0.3.3) — drives scientific research, architecture, and cross-family review.

All model routing is executed natively by Hermes Agent through the `advanced-delegation` plugin (`v0.2.1`) using `model_map`. No external routing daemon, no paid per-token commercial APIs, and no separate billing keys are used or required.

```
+----------------------------------------------------------------------------------+
|                     HERMES ORCHESTRATOR (gemini-3.8-flash-medium)                |
|                     Provider: antigravity-subscription-directsdk                 |
+----------------------------------------------------------------------------------+
                                         |
                         native delegate_task(option=...)
                                         v
+----------------------------------------------------------------------------------+
|                       ADVANCED DELEGATION: MODEL MAP                             |
|                              (21 Active Routes)                                  |
|                               Default: fast                                      |
+----------------------------------------------------------------------------------+
        |                                   |                              |
        v                                   v                              v
+-----------------------+       +-----------------------+      +-----------------------+
|     OpenAI Codex      |       |      Antigravity      |      |   Claude DirectSDK    |
|     Subscription      |       |      Subscription     |      |       Claude Pro      |
|                       |       |                       |      |                       |
| - gpt-6.1-sol (M)     |       | - gemini-3.8-flash (M)|      | - claude-opus-5-5[1m] |
| - gpt-6.1-terra (M)   |       | - gemini-4-argon (H)  |      | - claude-sonnet-5-5   |
| - gpt-6-luna (M)      |       | - claude-opus-5-5-high|      | - claude-haiku-5-5    |
| - gpt-6-astra (H)     |       | - claude-sonnet-5-5-m |      |                       |
|                       |       | - gemini-3.8-flash (L)|      |                       |
| [Account-Pin Enforced]|       | [Gateway Auth Port]   |      | [fallback_providers:[]|
+-----------------------+       +-----------------------+      +-----------------------+
        |                                                                  |
        +-------------> Fallback Chain: max depth <= 2 <-------------------+
```

---

## 2. Directory Layout & Document Index

| Document | Description | Purpose |
|---|---|---|
| [`README.md`](file:///home/gabo/.hermes/hermes-agent/docs/local-model-routing/README.md) | Architectural overview, component lifecycle, invariants | System entrypoint and reference hub |
| [`MODEL_MAP.md`](file:///home/gabo/.hermes/hermes-agent/docs/local-model-routing/MODEL_MAP.md) | Exact 21 routes, primary models, reasoning tiers, fallbacks | Routing lookup table and transition semantics |
| [`SUBSCRIPTION_AUTH.md`](file:///home/gabo/.hermes/hermes-agent/docs/local-model-routing/SUBSCRIPTION_AUTH.md) | Subscription boundaries, account-pinning, Claude isolation | Security boundaries, credential handling |
| [`OPERATIONS.md`](file:///home/gabo/.hermes/hermes-agent/docs/local-model-routing/OPERATIONS.md) | CLI commands, smoke tests, runtime audit, recovery | Day-to-day operations and diagnostics |
| [`DECISIONS.md`](file:///home/gabo/.hermes/hermes-agent/docs/local-model-routing/DECISIONS.md) | ADRs, rejected alternatives, known limitations | Architectural rationale and safety guardrails |
| [`config.example.yaml`](file:///home/gabo/.hermes/hermes-agent/docs/local-model-routing/config.example.yaml) | Sanitized, reproducible configuration example | Clean reference template for deployment |

---

## 3. Core Architectural Components

### 3.1 Primary Orchestrator
- **Model**: `gemini-3.8-flash-medium`
- **Provider**: `antigravity-subscription-directsdk`
- **Reasoning Tier**: Medium
- **Role**: Root turn execution, planning, task decomposition, and native `delegate_task` dispatch. Communicates locally with the Antigravity gateway on `127.0.0.1:41403`.

### 3.2 Auxiliary Systems
- **`auxiliary.goal_judge`**: Configured as `provider: auto`.
- **Behavior**: Hermes dynamically inherits the orchestrator's client (`gemini-3.8-flash-medium` via `antigravity-subscription-directsdk`) for session goal verification without allocating separate credentials or requiring additional provider configs.

### 3.3 Delegation Engine (`model_map`)
- Implemented in `plugins/advanced-delegation/model_map.py` (`ModelMapDelegationProvider`).
- Converts caller options (`option: <route_name>`) into fully resolved `TaskRoute` objects containing credentials, reasoning effort, and an ordered sequence of up to 2 `fallback_providers`.
- **Default Route**: `fast` (`gemini-3.8-flash-medium` with fallback to `gpt-6-luna` then `gpt-6.1-terra`).

### 3.4 Fallback Execution Machine
- Core logic resides in `agent/delegation_fallback.py` and `agent/chat_completion_helpers.py`.
- Operates on explicit HTTP status / client error codes (e.g. `429 RateLimit`, `503 Unavailable`).
- **Enforcement Rules**:
  - Maximum **2 fallback providers** per route (hard limit checked in `prepare_model_map_route`).
  - Strict credential and account-binding validation (`_check_account`).
  - Unsafe credential replay across different account principals is blocked with `AccountBindingError`.
  - Fails closed when all configured fallbacks are exhausted (returns `False`, never loops indefinitely).

---

## 4. Key Architectural Invariants

1. **Zero Pay-Per-Token Billing**: All models route through validated consumer subscriptions (Claude Pro OAuth CLI, OpenAI Codex subscription headers, Google Antigravity desktop gateway). No meter billing is used.
2. **Account Pinning & Isolation**: Commit `b6a5c0d728` introduced strict account identity validation (`_codex_principal_identity`). A fallback transition cannot jump across distinct account principals or switch to implicit credential pools.
3. **Claude DirectSDK Fallback Isolation (`fallback_providers: []`)**: Because Claude DirectSDK (`v0.3.3`) runs via external process (`/home/gabo/.local/bin/claude`), its runtime OAuth token lives in `~/.claude/` without an explicit account-binding interface. To prevent credential mismatch and security violations, all Claude DirectSDK routes are explicitly configured with **zero automatic fallbacks**. When a Claude route hits quota, it fails cleanly back to the parent orchestrator, which makes a deliberate, audited re-delegation choice.
4. **Independent Scientific Review**: Cross-family verification is preserved at the routing level. Review of OpenAI-authored artifacts routes to Claude Sonnet 5.5 (`review_openai_author`), while review of Claude-authored artifacts routes to Codex Terra (`review_claude_author`).

---

## 5. Official Hermes Documentation References

- [Hermes Agent Documentation](https://hermes-agent.nousresearch.com/docs)
- [Hermes Model Providers & Plugins](https://hermes-agent.nousresearch.com/docs/developer-guide/model-provider-plugin)
- [Hermes Delegation Architecture](https://hermes-agent.nousresearch.com/docs/developer-guide/delegation)
- [Hermes Package Management](https://hermes-agent.nousresearch.com/docs/reference/package-management)
