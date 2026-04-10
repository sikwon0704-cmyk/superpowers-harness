"""E2E test: failure retro -> rule promotion learning loop."""

from pathlib import Path

import pytest

from write_failure_retro import write_retro
from promote_rule import promote


def test_full_learning_loop(tmp_path: Path):
    """End-to-end: scaffold -> contract -> retro -> promote -> verify."""
    project = tmp_path / "project"

    # 1. Scaffold a minimal .harness/ structure
    (project / ".harness" / "failures").mkdir(parents=True)
    (project / ".harness" / "contracts").mkdir(parents=True)
    (project / ".harness" / "goals").mkdir(parents=True)
    (project / ".claude" / "rules" / "learned").mkdir(parents=True)

    # 2. Create a contract and goal (minimal files)
    contract = {
        "goal_id": "g-auth-fix",
        "status": "active",
        "description": "Fix authentication bypass vulnerability",
    }
    contract_path = project / ".harness" / "contracts" / "g-auth-fix.json"
    import json
    contract_path.write_text(json.dumps(contract), encoding="utf-8")

    goal_path = project / ".harness" / "goals" / "g-auth-fix.md"
    goal_path.write_text("# Goal: Fix auth bypass\n\nValidate session tokens.\n", encoding="utf-8")

    # 3. Write a failure retro
    retro_data = {
        "symptom": "Auth bypass: unauthenticated users access /admin",
        "root_cause": "Missing session token validation in middleware",
        "why_missed": "No integration test for auth middleware",
        "remediation": "Add token check in auth middleware before route handler",
        "candidate_rule": "Always validate session tokens in middleware",
    }
    retro_path = write_retro(project, "g-auth-fix", retro_data)

    assert retro_path.exists()
    retro_content = retro_path.read_text(encoding="utf-8")
    assert "pending" in retro_content  # Promoted? starts as pending

    # 4. Promote a rule from the retro
    result = promote(
        project,
        name="validate-session-tokens",
        scope="src/middleware/**",
        rule_text="- Must always validate session tokens in auth middleware before passing to route handlers.",
        retro_file=str(retro_path),
        agent="rule-curator",
        recurrence_risk="high",
    )
    assert result["promoted"] is True

    # 5. Verify the rule exists in .claude/rules/learned/
    rule_path = project / ".claude" / "rules" / "learned" / "validate-session-tokens.md"
    assert rule_path.exists()
    rule_content = rule_path.read_text(encoding="utf-8")
    assert "session tokens" in rule_content
    assert "src/middleware/**" in rule_content

    # 6. Verify the retro's "Promoted?" field is updated
    updated_retro = retro_path.read_text(encoding="utf-8")
    assert "pending" not in updated_retro
    assert "promoted" in updated_retro.lower()
    assert "validate-session-tokens" in updated_retro
