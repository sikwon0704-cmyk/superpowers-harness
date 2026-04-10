---
name: contract-gate
description: Use when starting implementation of a goal, before declaring work complete, or when checking if quality gates have been met — manages acceptance criteria and enforces completion requirements
---

# Contract Gate — Acceptance Criteria Tracking

Track what "done" means for every goal. No work is complete without evidence
that every acceptance criterion has been met, reviewed, and verified.

<HARD-GATE>
NEVER declare a goal complete without:
1. ALL acceptance criteria status = "met" with evidence
2. At least one code review with verdict APPROVE
3. At least one QA check with verdict APPROVE
This is enforced by validate_contract.py — you cannot bypass it.
</HARD-GATE>

## When to Create a Contract

After `superpowers:brainstorming` produces a spec, extract acceptance criteria:

```bash
# Create a new contract
python "${CLAUDE_PLUGIN_ROOT}/hooks/lib/validate_contract.py" "${CLAUDE_PROJECT_DIR}" --create --goal-id <goal_id>
```

## Status Transitions

```
draft → active           (plan confirmed)
active → review          (implementation + self-check done)
active → failed          (unrecoverable → trigger superpowers:failure-retro)
review → done            (reviewer APPROVE + QA APPROVE + all criteria met)
review → active          (REQUEST_CHANGES received → fix and re-review)
failed → active          (retry after remediation)
```

## Checking Gate Status

```bash
python "${CLAUDE_PLUGIN_ROOT}/hooks/lib/validate_contract.py" "${CLAUDE_PROJECT_DIR}" --check --goal-id <goal_id>
```

## Integration with Superpowers Workflow

| Superpowers Step | Contract Action |
|---|---|
| `brainstorming` completes with spec | Create contract (draft) with extracted ACs |
| `writing-plans` completes | Transition draft → active |
| `subagent-driven-development` or `executing-plans` | Contract stays active |
| `requesting-code-review` → APPROVE | Review artifact recorded |
| `verification-before-completion` passes | QA artifact recorded |
| `finishing-a-development-branch` | Attempt active → review → done |
