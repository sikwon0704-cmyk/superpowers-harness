---
name: codex-plan-review
description: Use immediately after writing-plans completes and a plan document exists — sends the plan to Codex for independent external review before implementation begins
---

# Codex Plan Review — External Review of Implementation Plans

After `writing-plans` produces a plan, send it to Codex for independent review.
Codex runs externally and returns only its findings — a second opinion before you commit to implementation.

**Announce at start:** "I'm using the codex-plan-review skill to get an external review of the plan from Codex."

## Checklist

1. **Locate the plan file** — find the most recent plan in `docs/superpowers/plans/` or the user's preferred plan location
2. **Read the plan** — load the full plan content
3. **Send to Codex for review** — invoke `/codex:rescue --wait` with the plan content and review instructions
4. **Present Codex feedback** — show the full Codex response to the human partner without modification
5. **Confirm action** — ask the human partner: "Apply Codex feedback to the plan, skip, or discuss?"
6. **If applying** — invoke `writing-plans` skill again with the original spec + Codex feedback as additional context
7. **Final plan confirmed** — proceed to implementation

## Step 3: Codex Rescue Invocation

Use this exact pattern to invoke `/codex:rescue`:

```
/codex:rescue --wait Review this implementation plan for risks, gaps, missing edge cases, incorrect assumptions, and overlooked dependencies. Be specific about what's wrong and suggest concrete fixes. Here is the plan:

[full plan content]
```

<HARD-GATE>
- Do NOT skip the Codex review step. The whole point of this skill is external validation.
- Do NOT modify or summarize Codex's output. Present it verbatim.
- Do NOT auto-apply feedback without human partner confirmation.
</HARD-GATE>

## If Codex Is Not Available

If `/codex:rescue` fails or Codex is not installed:
1. Tell the human partner: "Codex is not available. Run `/codex:setup` to install, or skip this review."
2. If skipping, proceed directly to implementation with the current plan.

## After This Skill

Once the final plan is confirmed (with or without Codex feedback), the next skill in the pipeline is `subagent-driven-development` or `executing-plans`.
