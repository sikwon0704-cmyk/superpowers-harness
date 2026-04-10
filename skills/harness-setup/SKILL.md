---
name: harness-setup
description: Use when starting a new project or when .harness/ directory doesn't exist — initializes quality tracking, contract system, and learned rules infrastructure
---

# Harness Setup — Initialize Quality Infrastructure

Scan the project and scaffold `.harness/` and `.claude/rules/learned/` directories.

<HARD-GATE>
NEVER overwrite existing files. If `.harness/` already exists, only add missing files
and report drift.
</HARD-GATE>

## Checklist

1. **Detect project profile** — run `detect_project_profile.py` to identify language, framework, and commands
2. **Review detected profile** — show results to human partner, confirm before proceeding
3. **Scaffold directories** — run `scaffold_runtime.py` to create `.harness/` and `.claude/rules/learned/`
4. **Show created files** — list what was created, skipped, and drifted
5. **Explain next steps** — "Describe your goal to start the quality loop"

## Run

```bash
python "${CLAUDE_PLUGIN_ROOT}/hooks/lib/detect_project_profile.py" "${CLAUDE_PROJECT_DIR}"
python "${CLAUDE_PLUGIN_ROOT}/hooks/lib/scaffold_runtime.py" "${CLAUDE_PROJECT_DIR}"
```

## What Gets Created

```
.harness/
  config.json             # guard/trace settings (all opt-in)
  profile.json            # detected project profile
  goals/                  # goal documents
  contracts/              # acceptance criteria + state machine
  plans/                  # implementation plans
  progress/               # session summaries
  artifacts/              # review/QA evidence, trace.jsonl
  failures/               # failure retro documents
  templates/              # contract, goal, plan, failure-retro templates

.claude/
  rules/learned/          # promoted rules from failure retros
  agent-memory/           # per-role accumulated knowledge
```

## After Setup

- Use `superpowers:brainstorming` to design your feature
- Use `superpowers:contract-gate` to create acceptance criteria
- Use `superpowers:writing-plans` to create implementation plans
- The harness will track progress and enforce quality gates automatically
