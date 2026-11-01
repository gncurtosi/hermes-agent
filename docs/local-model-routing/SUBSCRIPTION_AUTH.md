# Hermes Subscription Authentication & Provider Isolation

## 1. Zero Commercial API Billing Principle

All model routing in this Hermes deployment relies exclusively on authenticated, authorized **consumer and developer subscriptions**:

```
+--------------------------------------------------------------------------------+
| PROVIDER SUBSCRIPTIONS (ZERO PER-TOKEN API BILLING)                            |
+--------------------------------------------------------------------------------+
| 1. Anthropic Claude Pro    -> Local Claude Code CLI (~/.claude/ OAuth session)  |
| 2. OpenAI Codex Enterprise -> Local ChatGPT Codex session (chatgpt-account-id)  |
| 3. Google Antigravity      -> Local Antigravity Desktop Gateway (127.0.0.1:41403)|
+--------------------------------------------------------------------------------+
```

**Security and Invariant Rule**:
- Environment variables `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, and `GEMINI_API_KEY` are **never set** in `.env` or the runtime shell.
- No synthetic credit cards, metered tokens, or commercial API endpoints are reached.

---

## 2. Provider Authentication Boundaries

### 2.1 Anthropic Claude Pro (`claude-subscription-directsdk-experimental`)
- **Plugin Version**: `0.3.3`
- **Auth Mechanism**: `external_process`
- **Executable**: `/home/gabo/.local/bin/claude` (Claude Code CLI v2.1.314)
- **Credential Store**: Managed independently by the Claude CLI in `~/.claude/` via local OAuth tokens (`sk-ant-oat01...`).
- **Runtime Integration**: Hermes spawns the Claude binary as an external worker process using JSON-RPC/stdio. Hermes itself never reads, stores, or re-transmits raw Anthropic OAuth tokens.
- **Account Boundary Contract**:
  The Claude CLI handles its own session state and does not expose an `--account-id` parameter or principal hash to the Hermes parent process. As a result, Hermes cannot cryptographically verify whether a fallback invocation remains pinned to the same account session.

### 2.2 OpenAI Codex (`openai-codex`)
- **Transport**: Direct HTTPS to the authorized ChatGPT Codex endpoint (`https://chatgpt.com/backend-api/codex`).
- **Authentication**: Bearer session token stored securely in Hermes credential state.
- **Account Header Binding**: Each request includes the mandatory `chatgpt-account-id` header derived via `agent/codex_headers.py`.
- **Account Identity Enforcement**: Verified via `_codex_principal_identity(token, headers)` in `agent/delegation_fallback.py`.

### 2.3 Google Antigravity (`antigravity-subscription-directsdk`)
- **Plugin Version**: `0.4.1`
- **Auth Mechanism**: Local desktop gateway RPC at `http://127.0.0.1:41403`.
- **Authentication**: Antigravity local session handshake; handles token refresh, quota pools, and sandbox isolation through the user's logged-in desktop environment.

---

## 3. The External-Process Account-Binding Limitation (ADR-002)

### Root Cause Analysis
Commit `b6a5c0d728` introduced strict account pinning in `agent/delegation_fallback.py` to prevent credential leakage and cross-tenant replay:

```python
def _check_account(binding, token, headers):
    if binding.principal is not None:
        from agent.credential_pool import _codex_principal_identity
        if _codex_principal_identity(token, headers) != binding.principal:
            raise AccountBindingError("Resolved model_map Codex account header identity changed")
    if binding.endpoint is not None and binding.endpoint != (token or ""):
        raise AccountBindingError("Resolved model_map changed account credential")
```

When Hermes attempts an automatic fallback transition, it validates the candidate against the original task's `AccountBinding`. Because `claude-subscription-directsdk-experimental` uses `auth_type: external_process`, its credentials are not managed via Hermes's in-memory credential pools. Attempting to fall back from an in-memory client into an external process (or vice-versa) causes an `AccountBindingError`.

### Formal Policy: Zero Automatic Fallback on Claude DirectSDK
To respect this invariant safely without modifying upstream security gates or synthesizing credentials:
- All Claude DirectSDK routes explicitly declare `fallback_providers: []`.
- When Claude Pro quota is exhausted or encounters a 429, the child agent immediately returns an error.
- The parent orchestrator (Gemini 3.8 Flash) receives this clean failure report and makes an **explicit, audited choice** to re-delegate to an authorized secondary route (e.g. `complex_code_terra` or `antigravity_sonnet`).
- **Manual or parent-orchestrated re-delegation is an intentional dispatch decision; it is NOT an unverified automatic fallback transition.**

---

## 4. Quota Exhaustion & Recovery Protocol

| Provider | Quota Exhaustion Behavior | Recovery / Reset Cycle | Operational Action |
|---|---|---|---|
| **Claude Pro DirectSDK** | Returns 429 RateLimit or external process exit | Rolling 5-hour window per model tier | Fail to parent orchestrator; parent delegates to Codex Terra or Antigravity Sonnet |
| **OpenAI Codex** | Returns HTTP 429 with reset timestamp | Weekly / daily rolling allowance | Automatically falls back to secondary Codex tier or Antigravity Claude Sonnet |
| **Google Antigravity** | Returns 429 or capacity pause | Gateway dynamic reset | Automatically falls back to Codex Luna/Terra |

---

## 5. Credential Sanitization Guidelines for Operators

1. **Never copy `~/.claude/` session files** into the Hermes repository or configuration directory.
2. **Never add `api_key` strings** to `config.yaml` or candidate YAML files.
3. **Sanitize all logs and transcripts**: Ensure no authorization headers, bearer tokens, or session IDs are included in documentation, issue trackers, or PRs.
