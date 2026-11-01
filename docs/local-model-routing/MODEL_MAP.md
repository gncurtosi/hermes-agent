# Hermes Model Map Routing Catalog & Fallback Semantics

## 1. Catalog Architecture

The native Hermes Model Map backend (`plugins/advanced-delegation/model_map.py`) exposes **21 verified named routes** configured in `~/.hermes/config.yaml`.

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
| 1 | `scientific_research` | `claude-subscription-directsdk-experimental` | `claude-opus-5-5[1m]` | `medium` | *None* (`[]`) | *None* (`[]`) | Demanding physics, FEM crash, contact mechanics, GENESYS scientific inquiry |
| 2 | `architecture` | `claude-subscription-directsdk-experimental` | `claude-opus-5-5[1m]` | `medium` | *None* (`[]`) | *None* (`[]`) | System architecture, scalability tradeoffs, model-level redesigns |
| 3 | `fast` *(Default)* | `antigravity-subscription-directsdk` | `gemini-3.8-flash-medium` | `medium` | `openai-codex` / `gpt-6-luna` | `openai-codex` / `gpt-6.1-terra` | Default routine tasks, repository scouting, quick queries |
| 4 | `routine` | `antigravity-subscription-directsdk` | `gemini-3.8-flash-medium` | `medium` | `openai-codex` / `gpt-6-luna` | `openai-codex` / `gpt-6.1-terra` | Lightweight coordination, triage, log summarization |
| 5 | `complex_code_sol` | `openai-codex` | `gpt-6.1-sol` | `medium` | `openai-codex` / `gpt-6.1-terra` | `antigravity-subscription-directsdk` / `claude-sonnet-5-5-medium` | Complex algorithmic coding, deep refactoring, new feature development |
| 6 | `complex_code_terra` | `openai-codex` | `gpt-6.1-terra` | `medium` | `openai-codex` / `gpt-6.1-sol` | `antigravity-subscription-directsdk` / `claude-sonnet-5-5-medium` | Production engineering, automation, unit/integration test suites |
| 7 | `hpc_release` | `openai-codex` | `gpt-6.1-terra` | `medium` | `openai-codex` / `gpt-6.1-sol` | `antigravity-subscription-directsdk` / `claude-sonnet-5-5-medium` | HPC job packaging, deployment scripts, release qualification |
| 8 | `implementation` | `openai-codex` | `gpt-6.1-terra` | `medium` | `openai-codex` / `gpt-6.1-sol` | `antigravity-subscription-directsdk` / `claude-sonnet-5-5-medium` | Routine software implementation and code fixes |
| 9 | `hard_debugging` | `openai-codex` | `gpt-6.1-terra` | `medium` | `openai-codex` / `gpt-6.1-sol` | `antigravity-subscription-directsdk` / `claude-sonnet-5-5-medium` | Difficult numerical, DDP, memory, or concurrency bugs |
| 10 | `review_claude_author` | `openai-codex` | `gpt-6.1-terra` | `medium` | `openai-codex` / `gpt-6.1-sol` | `antigravity-subscription-directsdk` / `claude-sonnet-5-5-medium` | Independent cross-family review of Claude-authored artifacts |
| 11 | `review_openai_author` | `claude-subscription-directsdk-experimental` | `claude-sonnet-5-5[1m]` | `medium` | *None* (`[]`) | *None* (`[]`) | Independent cross-family review of Codex-authored artifacts |
| 12 | `claude_opus_55` | `claude-subscription-directsdk-experimental` | `claude-opus-5-5[1m]` | `medium` | *None* (`[]`) | *None* (`[]`) | Dedicated Claude Pro Opus 5.5 invocation |
| 13 | `claude_sonnet_55` | `claude-subscription-directsdk-experimental` | `claude-sonnet-5-5[1m]` | `medium` | *None* (`[]`) | *None* (`[]`) | Dedicated Claude Pro Sonnet 5.5 invocation |
| 14 | `claude_haiku_55` | `claude-subscription-directsdk-experimental` | `claude-haiku-5-5[1m]` | `medium` | *None* (`[]`) | *None* (`[]`) | Dedicated Claude Pro Haiku 5.5 fast invocation |
| 15 | `argon_deep` | `antigravity-subscription-directsdk` | `gemini-4-argon-high` | `high` | *None* (`[]`) | *None* (`[]`) | High-effort Gemini 4 Argon planning and synthesis |
| 16 | `astra_heavy` | `openai-codex` | `gpt-6-astra` | `high` | *None* (`[]`) | *None* (`[]`) | Heavy mathematical analysis and Codex deep reasoning |
| 17 | `antigravity_opus` | `antigravity-subscription-directsdk` | `claude-opus-5-5-high` | `high` | *None* (`[]`) | *None* (`[]`) | High-effort Antigravity Claude Opus reserve |
| 18 | `antigravity_sonnet` | `antigravity-subscription-directsdk` | `claude-sonnet-5-5-medium` | `medium` | *None* (`[]`) | *None* (`[]`) | Medium-effort Antigravity Claude Sonnet reserve |
| 19 | `direct_opus__high` | `claude-subscription-directsdk-experimental` | `claude-opus-5-5[1m]` | `high` | *None* (`[]`) | *None* (`[]`) | Claude Pro Opus 5.5 high-effort direct subscription |
| 20 | `routine__low` | `antigravity-subscription-directsdk` | `gemini-3.8-flash-low` | `low` | *None* (`[]`) | *None* (`[]`) | Minimal quota usage for bounded triage |
| 21 | `haiku__low` | `claude-subscription-directsdk-experimental` | `claude-haiku-5-5[1m]` | `low` | *None* (`[]`) | *None* (`[]`) | Low-effort Claude Pro Haiku 5.5 bounded task execution |

---

## 3. Fallback Hierarchy & Scopes

Hermes recognizes three distinct tiers of fallback configuration:

```
+-------------------------------------------------------------------------+
| 1. GLOBAL FALLBACKS (config.yaml: fallback_providers)                   |
|    Applies to the main orchestrator agent only. In production: []       |
+-------------------------------------------------------------------------+
                                    |
                                    v
+-------------------------------------------------------------------------+
| 2. DELEGATION-LEVEL DEFAULT FALLBACKS                                   |
|    Inherited if a delegation backend does not define its own routes.   |
+-------------------------------------------------------------------------+
                                    |
                                    v
+-------------------------------------------------------------------------+
| 3. PER-ROUTE FALLBACKS (options[].fallback_providers)                   |
|    Evaluated strictly per named route in model_map. Maximum depth: 2.   |
|    Overrides global settings for that delegated subagent.               |
+-------------------------------------------------------------------------+
```

### Key Invariants:
- **Route-specific isolation**: Per-route `fallback_providers` override global fallback settings completely for that task.
- **Depth limit**: Native Hermes core restricts `len(fallback_providers) <= 2`. Any configuration declaring 3 or more fallback providers is rejected during validation in `prepare_model_map_route`.

---

## 4. Configured Fallback Chains

### Chain A: Routine / Fast (`fast`, `routine`)
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

### Chain C: Codex Production (`complex_code_terra`, `hpc_release`, `implementation`, `hard_debugging`, `review_claude_author`)
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
