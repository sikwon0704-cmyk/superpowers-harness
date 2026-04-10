"""Guardrail matrix tests — role x tool x policy combinations.

Validates the pretool_guard enforces correct access control across
all roles in the Superpowers 4-role system.
"""

import pytest

from pretool_guard import guard


def _ev(tool: str, inp: dict, agent: str = "") -> dict:
    return {"tool_name": tool, "tool_input": inp, "agent_name": agent}


# -- Role x Tool matrix: specific scenarios from requirements --

class TestCodeReviewerMatrix:
    """code-reviewer (reviewer): read-only access, no code edits."""

    def test_reviewer_edit_blocked(self):
        code, _ = guard(_ev("Edit", {"file_path": "/p/src/app.ts"}, "code-reviewer"))
        assert code == 2, "code-reviewer should be blocked from Edit on product code"

    def test_reviewer_read_allowed(self):
        code, _ = guard(_ev("Read", {"file_path": "/p/src/app.ts"}, "code-reviewer"))
        assert code == 0, "code-reviewer should be allowed to Read product code"

    def test_reviewer_grep_allowed(self):
        code, _ = guard(_ev("Grep", {"pattern": "TODO", "path": "/p/src/"}, "code-reviewer"))
        assert code == 0, "code-reviewer should be allowed to Grep"

    def test_reviewer_write_blocked(self):
        code, _ = guard(_ev("Write", {"file_path": "/p/src/new.ts"}, "code-reviewer"))
        assert code == 2, "code-reviewer should be blocked from Write on product code"

    def test_reviewer_can_write_review_artifact(self):
        code, _ = guard(_ev("Write", {"file_path": "/p/.harness/artifacts/review-g1-20260410.json"}, "code-reviewer"))
        assert code == 0, "code-reviewer should be allowed to write review artifacts"


class TestImplementerMatrix:
    """implementer: can edit product code, cannot touch .claude/rules/."""

    def test_implementer_edit_product_code_allowed(self):
        code, _ = guard(_ev("Edit", {"file_path": "/p/src/app.ts"}, "implementer"))
        assert code == 0, "implementer should be allowed to Edit product code"

    def test_implementer_edit_rules_blocked(self):
        code, _ = guard(_ev("Edit", {"file_path": "/p/.claude/rules/core.md"}, "implementer"))
        assert code == 2, "implementer should be blocked from editing .claude/rules/"

    def test_implementer_edit_learned_rules_blocked(self):
        code, _ = guard(_ev("Edit", {"file_path": "/p/.claude/rules/learned/new.md"}, "implementer"))
        assert code == 2, "implementer should be blocked from editing learned rules"

    def test_implementer_write_product_code_allowed(self):
        code, _ = guard(_ev("Write", {"file_path": "/p/src/new-file.ts"}, "implementer"))
        assert code == 0, "implementer should be allowed to Write new product files"

    def test_implementer_write_rules_blocked(self):
        code, _ = guard(_ev("Write", {"file_path": "/p/.claude/rules/testing.md"}, "implementer"))
        assert code == 2, "implementer should be blocked from writing .claude/rules/"


class TestRuleCuratorMatrix:
    """rule-curator: can write to .claude/rules/learned/."""

    def test_curator_write_learned_rule_allowed(self):
        code, _ = guard(_ev("Write", {"file_path": "/p/.claude/rules/learned/new-rule.md"}, "rule-curator"))
        assert code == 0, "rule-curator should be allowed to write learned rules"

    def test_curator_edit_learned_rule_allowed(self):
        code, _ = guard(_ev("Edit", {"file_path": "/p/.claude/rules/learned/existing.md"}, "rule-curator"))
        assert code == 0, "rule-curator should be allowed to edit learned rules"

    def test_curator_read_product_code_allowed(self):
        code, _ = guard(_ev("Read", {"file_path": "/p/src/app.ts"}, "rule-curator"))
        assert code == 0, "rule-curator should be allowed to read product code"


class TestQaBrowserMatrix:
    """qa-browser: same read-only constraints as code-reviewer."""

    def test_qa_edit_blocked(self):
        code, _ = guard(_ev("Edit", {"file_path": "/p/src/app.ts"}, "qa-browser"))
        assert code == 2, "qa-browser should be blocked from editing product code"

    def test_qa_read_allowed(self):
        code, _ = guard(_ev("Read", {"file_path": "/p/src/app.ts"}, "qa-browser"))
        assert code == 0, "qa-browser should be allowed to read"

    def test_qa_write_blocked(self):
        code, _ = guard(_ev("Write", {"file_path": "/p/src/app.ts"}, "qa-browser"))
        assert code == 2, "qa-browser should be blocked from writing product code"

    def test_qa_can_write_qa_artifact(self):
        code, _ = guard(_ev("Write", {"file_path": "/p/.harness/artifacts/qa-g1-20260410.json"}, "qa-browser"))
        assert code == 0, "qa-browser should be allowed to write QA artifacts"


class TestGlobalDeny:
    """Global policy: all roles blocked from secrets, destructive ops."""

    @pytest.mark.parametrize("role", ["", "implementer", "code-reviewer", "qa-browser", "rule-curator"])
    def test_env_file_blocked(self, role: str):
        code, _ = guard(_ev("Read", {"file_path": "/p/.env"}, role))
        assert code == 2, f"role={role!r} should be blocked from reading .env"

    @pytest.mark.parametrize("role", ["", "implementer", "code-reviewer", "qa-browser", "rule-curator"])
    def test_force_push_blocked(self, role: str):
        code, _ = guard(_ev("Bash", {"command": "git push --force origin main"}, role))
        assert code == 2, f"role={role!r} should be blocked from force push"

    def test_git_internal_write_blocked(self):
        code, _ = guard(_ev("Edit", {"file_path": "/p/.git/config"}, ""))
        assert code == 2

    def test_rm_rf_blocked(self):
        code, _ = guard(_ev("Bash", {"command": "rm -rf /"}, ""))
        assert code == 2

    def test_credentials_blocked(self):
        code, _ = guard(_ev("Read", {"file_path": "/p/credentials.json"}, ""))
        assert code == 2


class TestEdgeCases:
    """Edge cases and normal operations that should pass."""

    def test_empty_event_allowed(self):
        code, _ = guard({})
        assert code == 0

    def test_normal_git_allowed(self):
        code, _ = guard(_ev("Bash", {"command": "git status"}, ""))
        assert code == 0

    def test_npm_test_allowed(self):
        code, _ = guard(_ev("Bash", {"command": "npm test"}, ""))
        assert code == 0

    def test_unknown_tool_allowed(self):
        code, _ = guard(_ev("WebSearch", {"query": "python docs"}, ""))
        assert code == 0
