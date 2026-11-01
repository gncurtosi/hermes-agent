# Hermes Model Map Routing Catalog & Fallback Semantics

## 1. Catalog Architecture

The native Hermes Model Map backend (`plugins/advanced-delegation/model_map.py`) exposes **exactly 21 verified named routes** configured in `~/.hermes/config.yaml`.

Each route is defined by:
- `name`: Unique option string passed to `delegate_task(option=...)`.
- `provider`: Resolved provider plugin name.
- `model`: Canonical model identifier or pinned version.
- `reasoning_effort`: `low`, `medium`, or `high`.
- `fallback_providers`: Ordered list of up to **2** fallback targets.

---

## 2. Complete Inventory of Active Routes (21 Routes)

| # | Route Name | Provider | Primary Model | Effort | Fallback 1 | Fallback 2 | Primary Task Purpose |
|---|---|---|---|---|---|---|---|
| 1 | `fast` *(Default)* | `antigravity-subscription-directsdk` | `gemini-3.8-flash-medium` | `medium` | `openai-codex` / `gpt-6-luna` | `openai-codex` / `gpt-6.1-terra` | Rapid lightweight execution & default scouting |
| 2 | `complex_code_sol` | `openai-codex` | `gpt-6.1-sol` | `medium` | `openai-codex` / `gpt-6.1-terra` | `antigravity-subscription-directsdk` / `claude-sonnet-5-5-medium` | Advanced algorithmic coding & reasoning |
| 3 | `complex_code_terra` | `openai-codex` | `gpt-6.1-terra` | `medium` | `openai-codex` / `gpt-6.1-sol` | `antigravity-subscription-directsdk` / `claude-sonnet-5-5-medium` | Production engineering & test suite development |
| 4 | `scientific_research` | `claude-subscription-directsdk-experimental` | `claude-opus-5-5[1m]` | `medium` | *None* (`[]`) | *None* (`[]`) | Deep scientific, physics, FEM crash & mathematical research |
| 5 | `architecture` | `claude-subscription-directsdk-experimental` | `claude-opus-5-5[1m]` | `medium` | *None* (`[]`) | *None* (`[]`) | Systems & software architecture, scalability tradeoffs |
| 6 | `hpc_release` | `openai-codex` | `gpt-6.1-terra` | `medium` | `openai-codex` / `gpt-6.1-sol` | `antigravity-subscription-directsdk` / `claude-sonnet-5-5-medium` | HPC packaging & release qualification |
| 7 | `claude_opus_55` | `claude-subscription-directsdk-experimental` | `claude-opus-5-5[1m]` | `medium` | *None* (`[]`) | *None* (`[]`) | Dedicated Claude Pro Opus 5.5 invocation (standalone) |
| 8 | `claude_sonnet_55` | `claude-subscription-directsdk-experimental` | `claude-sonnet-5-5[1m]` | `medium` | *None* (`[]`) | *None* (`[]`) | Dedicated Claude Pro Sonnet 5.5 invocation (standalone) |
| 9 | `claude_haiku_55` | `claude-subscription-directsdk-experimental` | `claude-haiku-5-5[1m]` | `medium` | *None* (`[]`) | *None* (`[]`) | Dedicated Claude Pro Haiku 5.5 fast invocation (standalone) |
| 10 | `review_openai_author` | `antigravity-subscription-directsdk` | `claude-sonnet-5-5-medium` | `medium` | *None* (`[]`) | *None* (`[]`) | Cross-family independent review of OpenAI artifacts |
| 11 | `review_claude_author` | `openai-codex` | `gpt-6.1-terra` | `medium` | *None* (`[]`) | *None* (`[]`) | Cross-family independent review of Claude artifacts |
| 12 | `orchestration` | `antigravity-subscription-directsdk` | `gemini-3.8-flash-medium` | `medium` | `openai-codex` / `gpt-6-luna` | `openai-codex` / `gpt-6.1-terra` | Mission coordination & pipeline orchestration |
| 13 | `complex_planning` | `antigravity-subscription-directsdk` | `gemini-4-argon-high` | `high` | *None* (`[]`) | *None* (`[]`) | High-complexity architectural reasoning & planning |
| 14 | `critical_audit` | `openai-codex` | `gpt-6-astra` | `high` | *None* (`[]`) | *None* (`[]`) | Critical code audit & deep formal verification |
| 15 | `triage` | `openai-codex` | `gpt-6-luna` | `low` | *None* (`[]`) | *None* (`[]`) | Lightweight issue triage & bounded analysis |
| 16 | `routine` | `antigravity-subscription-directsdk` | `gemini-3.8-flash-medium` | `medium` | *None* (`[]`) | *None* (`[]`) | Routine operations & status reporting |
| 17 | `maintenance` | `antigravity-subscription-directsdk` | `gemini-3.8-flash-medium` | `medium` | *None* (`[]`) | *None* (`[]`) | Hermes housekeeping & environment maintenance |
| 18 | `experimental_baselines` | `antigravity-subscription-directsdk` | `gpt-oss-120b-medium` | `medium` | *None* (`[]`) | *None* (`[]`) | Open weights benchmark baseline comparison |
| 19 | `agy__gemini-4-argon-high` | `antigravity-subscription-directsdk` | `gemini-4-argon-high` | `high` | *None* (`[]`) | *None* (`[]`) | Dedicated Antigravity Argon High reserve |
| 20 | `agy__claude-opus-5-5-medium` | `antigravity-subscription-directsdk` | `claude-opus-5-5-medium` | `medium` | *None* (`[]`) | *None* (`[]`) | Antigravity Claude Opus 5.5 Medium reserve |
| 21 | `agy__claude-sonnet-5-5-medium` | `antigravity-subscription-directsdk` | `claude-sonnet-5-5-medium` | `medium` | *None* (`[]`) | *None* (`[]`) | Antigravity Claude Sonnet 5.5 Medium reserve |

---

## 3. Fallback Hierarchy & Scopes

Hermes recognizes three distinct tiers of fallback configuration:

```
+-----------------------------------------------------------------------------------------+
| 1. GLOBAL FALLBACKS (config.yaml: fallback_providers)                                   |
|    Applies to the main orchestrator agent only.                                         |
|    Active configuration:                                                                |
|      1. openai-codex / gpt-6.1-terra                                                    |
|      2. antigravity-subscription-directsdk / claude-sonnet-5-5-medium                     |
+-----------------------------------------------------------------------------------------+
                                             |
                                             v
+-----------------------------------------------------------------------------------------+
| 2. DELEGATION-LEVEL DEFAULT FALLBACKS                                                   |
|    Inherited if a delegation backend does not define its own routes.                    |
+-----------------------------------------------------------------------------------------+
                                             |
                                             v
+-----------------------------------------------------------------------------------------+
| 3. PER-ROUTE FALLBACKS (delegation.backends.model_map.options[].fallback_providers)     |
|    Evaluated strictly per named route in model_map. Maximum depth: 2.                   |
|    Overrides global settings for that delegated subagent.                               |
+-----------------------------------------------------------------------------------------+
```

### Key Invariants:
- **Route-specific isolation**: Per-route `fallback_providers` override global fallback settings completely for that delegated subagent task.
- **Depth limit**: Native Hermes core restricts `len(fallback_providers) <= 2`. Any configuration declaring 3 or more fallback providers is rejected during validation in `prepare_model_map_route`.

---

## 4. Configured Fallback Chains

### Chain A: Rapid Execution & Orchestration (`fast`, `orchestration`)
```
[Primary: Antigravity / gemini-3.8-flash-medium] (Effort: Medium)
       |
       | (429 RateLimit / 503 ServiceUnavailable)
       v
[Fallback 1: OpenAI Codex / gpt-6-luna] (Effort: Medium)
       |
       | (429 RateLimit / 503 ServiceUnavailable)
       v
[Fallback 2: OpenAI Codex / gpt-6.1-terra] (Effort: Medium)
       |
       v
[Fail Closed: Agent returns error, no infinite loop]
```

### Chain B: Codex Engineering (`complex_code_sol`)
```
[Primary: OpenAI Codex / gpt-6.1-sol] (Effort: Medium)
       |
       | (429 RateLimit / 503 ServiceUnavailable)
       v
[Fallback 1: OpenAI Codex / gpt-6.1-terra] (Effort: Medium)
       |
       | (429 RateLimit / 503 ServiceUnavailable)
       v
[Fallback 2: Antigravity / claude-sonnet-5-5-medium] (Effort: Medium)
       |
       v
[Fail Closed: Account boundary preserved]
```

### Chain C: Codex Production (`complex_code_terra`, `hpc_release`)
```
[Primary: OpenAI Codex / gpt-6.1-terra] (Effort: Medium)
       |
       | (429 RateLimit / 503 ServiceUnavailable)
       v
[Fallback 1: OpenAI Codex / gpt-6.1-sol] (Effort: Medium)
       |
       | (429 RateLimit / 503 ServiceUnavailable)
       v
[Fallback 2: Antigravity / claude-sonnet-5-5-medium] (Effort: Medium)
       |
       v
[Fail Closed]
```

---

## 5. Why `__replacement` Routes Are NOT Fallback Chains

Historical configurations frequently contained routes named with suffixes like `scientific_research__replacement_1` or `architecture__replacement_2`.

**Crucial Architectural Distinction**:
- A separately named option (e.g. `scientific_research__replacement_1`) is an **independent route in the dictionary**, NOT an automatic fallback transition of `scientific_research`.
- The native fallback machine transitions automatically **only** when candidates are listed inside the `fallback_providers: [...]` array of that specific route.
- If `scientific_research` has `fallback_providers: []`, Hermes will **never** automatically fall over to `scientific_research__replacement_1`.
- In the active production catalog, all spurious replacement duplicates have been removed or consolidated into explicit, tested routes.

---

## 6. Model Pinning vs. Reasoning Effort

- **Claude 5.5 Pinning**: DirectSDK models require explicit pinned version strings (`claude-opus-5-5[1m]`, `claude-sonnet-5-5[1m]`, `claude-haiku-5-5[1m]`) to guarantee consistent prompt cache behavior and 1-million context support.
- **Fixed-Effort vs Flexible-Effort Models**:
  - `gemini-4-argon-high` has **fixed `high` effort** in the Antigravity catalog. Attempting to run it with `reasoning_effort: medium` triggers an `effort_conflict` error in `exact_catalog.py`.
  - `gpt-6-astra` has **fixed `high` effort** in the Codex catalog.
  - Codex Sol (`gpt-6.1-sol`) and Terra (`gpt-6.1-terra`) flexibly support `low`, `medium`, and `high` effort tiers.
