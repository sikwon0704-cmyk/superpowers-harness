"""Tests for promote_rule.py — rule promotion from failure retros."""

from pathlib import Path

import pytest

from promote_rule import promote, check_duplicate
from write_failure_retro import write_retro


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / ".claude" / "rules" / "learned").mkdir(parents=True)
    (tmp_path / ".claude" / "agent-memory" / "reviewer").mkdir(parents=True)
    (tmp_path / ".harness" / "failures").mkdir(parents=True)
    return tmp_path


def test_promote_creates_rule_file(project: Path):
    """Successful promotion creates a .md file in .claude/rules/learned/."""
    result = promote(
        project,
        name="validate-input",
        scope="src/**/*.ts",
        rule_text="- Always validate request body before processing.",
        recurrence_risk="high",
    )
    assert result["promoted"] is True

    rule_path = project / ".claude" / "rules" / "learned" / "validate-input.md"
    assert rule_path.exists()

    content = rule_path.read_text(encoding="utf-8")
    assert "validate request body" in content
    assert "src/**/*.ts" in content


def test_promote_updates_retro(project: Path):
    """After promotion, the retro file's Promoted? field is updated."""
    retro_data = {
        "symptom": "test failure",
        "root_cause": "missing validation",
        "remediation": "add check",
        "candidate_rule": "Always validate",
    }
    retro_path = write_retro(project, "g1", retro_data)

    result = promote(
        project,
        name="validate-always",
        scope="src/**",
        rule_text="- Always validate input before handler execution.",
        retro_file=str(retro_path),
        recurrence_risk="high",
    )
    assert result["promoted"] is True
    assert result.get("retro_updated") is True

    content = retro_path.read_text(encoding="utf-8")
    assert "promoted" in content.lower()
    assert "validate-always" in content


def test_promote_duplicate_detected(project: Path):
    """Duplicate rule text is rejected on second promotion attempt."""
    rule_text = "- Must always validate input before processing in handlers."

    promote(
        project,
        name="dup-rule-1",
        scope="src/**/*.ts",
        rule_text=rule_text,
        recurrence_risk="high",
    )

    result = promote(
        project,
        name="dup-rule-2",
        scope="src/**/*.ts",
        rule_text=rule_text,
        recurrence_risk="high",
    )
    assert result["promoted"] is False
    assert "duplicate" in result["reason"].lower()


def test_promote_updates_agent_memory(project: Path):
    """When agent is specified, the agent's MEMORY.md is updated."""
    result = promote(
        project,
        name="reviewer-lesson",
        scope="src/api/**/*.ts",
        rule_text="- Always check for null returns in API handlers before processing.",
        agent="reviewer",
        recurrence_risk="high",
    )
    assert result["promoted"] is True
    assert result.get("memory_updated") == "reviewer"

    memory_path = project / ".claude" / "agent-memory" / "reviewer" / "MEMORY.md"
    content = memory_path.read_text(encoding="utf-8")
    assert "null returns" in content


def test_promote_rejection_criteria(project: Path):
    """Rule that fails promotion criteria is rejected."""
    # recurrence_risk is not "high" → rejection
    result = promote(
        project,
        name="low-risk-rule",
        scope="src/**",
        rule_text="- Should always check error handling in try-catch blocks.",
        recurrence_risk="low",
    )
    assert result["promoted"] is False
    assert "recurrence risk" in result["reason"]

    # Rule text too short → rejection
    result = promote(
        project,
        name="short-rule",
        scope="src/**",
        rule_text="check it",
        recurrence_risk="high",
    )
    assert result["promoted"] is False
    assert "too short" in result["reason"]

    # Scope too broad → rejection
    result = promote(
        project,
        name="broad-rule",
        scope="**/*",
        rule_text="- Must always validate everything before doing anything.",
        recurrence_risk="high",
    )
    assert result["promoted"] is False
    assert "scope" in result["reason"].lower()
