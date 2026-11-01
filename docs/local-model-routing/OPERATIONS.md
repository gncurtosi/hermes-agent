# Hermes Model Map Operational Runbook & Verification Procedures

## 1. Verified Operator CLI Commands

All commands listed below have been verified against the installed Hermes Agent CLI (`v0.8.0`).

### 1.1 Inspecting Active Delegation & Fallbacks

```bash
# Display active delegation backend, default route, and all 21 options
hermes delegation config --show

# Inspect model fallback chains and current failover status
hermes fallback list

# Inspect active root model
hermes config get model

# Inspect active root provider
hermes config get provider

# Inspect active default Model Map route
hermes config get delegation.backends.model_map.default

# Set or change the default Model Map route
hermes config set delegation.backends.model_map.default fast
```

### 1.2 Interactive Slash Commands (Inside Chat / TUI)

| Command | Syntax / Example | Purpose |
|---|---|---|
| `/model` | `/model` | Displays active model, provider, reasoning effort, and context limits |
| `/model` (Switch) | `/model claude-opus-5-5[1m] --provider claude-subscription-directsdk-experimental --reasoning medium` | Switches session to version-pinned Claude Pro Opus 5.5 |
| `/model` (Codex) | `/model gpt-6.1-terra --provider openai-codex --reasoning medium` | Switches session to Codex Terra |
| `/delegation` | `/delegation` | Displays delegation status, backend (`model_map`), and registered routes |
| `/status` | `/status` | Displays system health, tool status, active profile, and token consumption |
| `/new` | `/new` | Resets conversation context and cached prefixes for a clean turn session |

---

## 2. Explicit Subagent Delegation Guide

When invoking subagents via `delegate_task`, pass the exact route name in the `option` parameter:

### 2.1 Routine & Quick Tasks (`fast`)
```python
delegate_task(tasks=[{
    "goal": "Scout repository structure and locate configuration parsers",
    "option": "fast"
}])
```

### 2.2 Deep Algorithmic Coding (`complex_code_sol`)
```python
delegate_task(tasks=[{
    "goal": "Implement vectorized spatial partitioning algorithm for mesh contact search",
    "option": "complex_code_sol"
}])
```

### 2.3 Production Software Engineering (`complex_code_terra`)
```python
delegate_task(tasks=[{
    "goal": "Develop unit tests for fallback authority and run pytest suite",
    "option": "complex_code_terra"
}])
```

### 2.4 Scientific Research & Physics Inquiry (`scientific_research`)
```python
delegate_task(tasks=[{
    "goal": "Analyze rigid-body nodal momentum conservation and verify impact boundary conditions",
    "context": "Preserve physical invariants from ADR-001: static clamps fixed at 0.00mm, moving rigid evolves with vx=-8.89m/s",
    "option": "scientific_research"
}])
```

### 2.5 Systems Architecture (`architecture`)
```python
delegate_task(tasks=[{
    "goal": "Evaluate microservice vs modular monolith architecture for checkpoint ingestion",
    "option": "architecture"
}])
```

### 2.6 Independent Cross-Family Review
```python
# Review of Codex-authored implementation using Claude Sonnet 5.5:
delegate_task(tasks=[{
    "goal": "Review the PR changes in tools/delegate_tool.py for security and edge cases",
    "option": "review_openai_author"
}])

# Review of Claude-authored scientific derivations using Codex Terra:
delegate_task(tasks=[{
    "goal": "Independently verify mathematical derivations and mesh boundary proofs",
    "option": "review_claude_author"
}])
```

### 2.7 HPC Release Preparation (`hpc_release`)
```python
delegate_task(tasks=[{
    "goal": "Prepare local Slurm submission scripts and validate container mount configurations",
    "option": "hpc_release"
}])
```

---

## 3. Auditing Real Execution: Requested Route vs. Executed Model

Because subagents may experience fallback transitions, the operator must audit the **effective executing client**, not merely the requested option.

### Audit Procedure:
1. Inspect subagent execution logs in `~/.hermes/logs/hermes.log` or transcript records.
2. Check the `TaskRoute.report()` string output:
   - A clean primary run reports: `Route: <option> -> <provider>/<model>`
   - A fallback run reports: `[Fallback Activated] <primary_model> -> <fallback_model> (Reason: rate_limited)`
3. Verify response headers in the transcript: `chatgpt-account-id` for Codex, local process PID for DirectSDK.

---
## 4. Smoke Test Suite

Run this command to execute the non-destructive smoke test suite verifying route resolution, catalog consistency, and fallback mechanics:

```bash
cd /home/gabo/.hermes/hermes-agent
python3 -c "
from utils import fast_safe_load
from plugins.antigravity_directsdk.model_catalog import normalize_antigravity_model
from plugins.claude_directsdk.model_catalog import normalize_claude_model

with open('/home/gabo/.hermes/config.yaml') as f:
    cfg = fast_safe_load(f)

opts = cfg['delegation']['backends']['model_map']['options']
print(f'Validating {len(opts)} Model Map options...')
for o in opts:
    p, m = o['provider'], o['model']
    if p == 'antigravity-subscription-directsdk':
        assert normalize_antigravity_model(m), f'Invalid AGY model: {m}'
    elif p == 'claude-subscription-directsdk-experimental':
        assert normalize_claude_model(m), f'Invalid Claude model: {m}'
    elif p == 'openai-codex':
        assert m in ['gpt-6.1-sol', 'gpt-6.1-terra', 'gpt-6-luna', 'gpt-6-astra'], f'Invalid Codex model: {m}'
print('SMOKE TEST PASS: All 21 routes validated successfully.')"
```

---

## 5. Backup, Rollback, and Upgrade Procedures

### 5.1 Safe Configuration Backup
```bash
# Create a timestamped, local untracked backup of active configuration
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
cp /home/gabo/.hermes/config.yaml /home/gabo/.hermes/config.yaml.bak_${TIMESTAMP}
chmod 600 /home/gabo/.hermes/config.yaml.bak_${TIMESTAMP}
echo "Backup created at /home/gabo/.hermes/config.yaml.bak_${TIMESTAMP}"
```

### 5.2 Rollback Procedure
If a configuration change or upgrade destabilizes routing:
```bash
# Restore known good configuration
cp /home/gabo/.hermes/config.yaml.bak_${TIMESTAMP} /home/gabo/.hermes/config.yaml
# Verify restored configuration syntax
hermes delegation config --show
```

### 5.3 Repeatable Upgrade Checklist
When upgrading Hermes Agent core (`hermes update`):
1. **Step 1: Snapshot Version & Fingerprint**
   Record `hermes version`, git commit SHA, and SHA256 of `~/.hermes/config.yaml`.
2. **Step 2: Backup Configuration**
   Run the backup command above to retain the pre-upgrade YAML.
3. **Step 3: Review Upstream Changelog**
   Check for changes to `agent/delegation_fallback.py`, `tools/delegate_tool.py`, or `plugins/advanced-delegation/`.
4. **Step 4: Verify Plugin Integrity**
   Ensure `claude-subscription-directsdk-experimental` (v0.3.3) and `antigravity-subscription-directsdk` (v0.4.1) remain active in `~/.hermes/plugins/`.
5. **Step 5: Verify Fallback Invariants**
   Confirm no route exceeds 2 fallbacks and Claude routes maintain `fallback_providers: []`.
6. **Step 6: Run Acceptance Smoke Tests**
   Execute the Python smoke test script and run test suite via pytest.
