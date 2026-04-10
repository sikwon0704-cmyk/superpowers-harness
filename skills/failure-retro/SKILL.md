---
name: failure-retro
description: Use when a review returns REQUEST_CHANGES, QA fails, tests fail after implementation, or any quality gate is not met — documents root cause and evaluates rule promotion
---

# Failure Retro — Turn Failures Into Knowledge

When something fails, don't just fix it. Document why, evaluate whether this is a
pattern, and decide if a learned rule should prevent recurrence.

<HARD-GATE>
NEVER skip the root cause step. Symptom-level fixes without root cause analysis
are the failure mode this skill prevents.
</HARD-GATE>

## Checklist

1. **Document symptom** — what went wrong, visible to the user
2. **Find root cause** — use `superpowers:systematic-debugging` if needed
3. **Explain why checks missed it** — which test/review/gate should have caught this
4. **Write remediation** — what was done to fix it
5. **Evaluate candidate rule** — does this failure meet promotion criteria?
6. **Run promotion** — if promoting, use `promote_rule.py`
7. **Update contract** — mark failed criteria, trigger replan if needed

## Running the Retro

```bash
# Write the retro document
echo '{"goal_id":"<id>","symptom":"...","root_cause":"...","why_missed":"...","remediation":"...","candidate_rule":"...","next_replan":"..."}' | python "${CLAUDE_PLUGIN_ROOT}/hooks/lib/write_failure_retro.py" "${CLAUDE_PROJECT_DIR}"

# Evaluate and promote a rule (if criteria met)
echo '{"retro_file":".harness/failures/<file>.md","rule_name":"...","rule_text":"...","paths":["src/**"],"recurrence_risk":"high","generalizable":true,"agent":"code-reviewer"}' | python "${CLAUDE_PLUGIN_ROOT}/hooks/lib/promote_rule.py" "${CLAUDE_PROJECT_DIR}"
```

## Promotion Criteria (ALL must be true)

- Recurrence risk is high
- Generalizable beyond this specific instance
- Short and specific (one rule, one file scope)
- Verifiable by tests or code review

## Anti-Pattern: "This Was a One-Off"

If you're confident this exact failure will never happen again, fine. But if the
*category* of failure (missing edge case test, unhandled error type, forgotten
migration) could recur, that's a rule.
