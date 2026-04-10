"""Tests for restore_runtime_context.py."""

import json
from pathlib import Path

import pytest

from scaffold_runtime import scaffold
from validate_contract import save_contract
from restore_runtime_context import restore


@pytest.fixture
def project_with_state(tmp_path: Path) -> Path:
    """Project with scaffold + active goal + contract + failure."""
    scaffold(tmp_path)

    goal_id = "goal-20260410-001"
    goals_dir = tmp_path / ".harness" / "goals"
    goals_dir.mkdir(parents=True, exist_ok=True)
    (goals_dir / f"{goal_id}.md").write_text(
        f"# Goal: {goal_id}\n\n- **Status**: active\n\n## User Goal\n\nAdd login.\n",
        encoding="utf-8",
    )

    save_contract(tmp_path, goal_id, {
        "goal_id": goal_id,
        "user_goal": "Add login",
        "acceptance_criteria": [
            {"id": "AC-1", "text": "Email validated", "status": "met", "evidence": ["test"]},
            {"id": "AC-2", "text": "Password checked", "status": "unmet", "evidence": []},
            {"id": "AC-3", "text": "Redirect works", "status": "unmet", "evidence": []},
        ],
        "required_evidence": ["test output"],
        "status": "active",
    })

    failures_dir = tmp_path / ".harness" / "failures"
    failures_dir.mkdir(parents=True, exist_ok=True)
    (failures_dir / f"{goal_id}-20260410-100000.md").write_text(
        "# Failure: validation bypass\n\n## Root Cause\nMissing check.\n",
        encoding="utf-8",
    )

    return tmp_path


def test_no_harness_outputs_setup_recommended(tmp_target: Path):
    """No .harness/ directory -> setup_recommended is True."""
    ctx = restore(tmp_target)

    assert ctx["harness_exists"] is False
    assert ctx["setup_recommended"] is True
    assert ctx["active_goal"] is None


def test_active_goal_restoration(project_with_state: Path):
    """Active goal is found and reported."""
    ctx = restore(project_with_state)

    assert ctx["harness_exists"] is True
    assert ctx["active_goal"] == "goal-20260410-001"
    assert ctx["active_goal_phase"] == "active"
    assert ctx["contract_status"] == "active"


def test_unmet_criteria_listing(project_with_state: Path):
    """Unmet criteria are listed; met criteria are excluded."""
    ctx = restore(project_with_state)

    assert len(ctx["unmet_criteria"]) == 2
    unmet_ids = [c["id"] for c in ctx["unmet_criteria"]]
    assert "AC-2" in unmet_ids
    assert "AC-3" in unmet_ids
    assert "AC-1" not in unmet_ids


def test_recent_failures_listing(project_with_state: Path):
    """Recent failures are parsed from .harness/failures/."""
    ctx = restore(project_with_state)

    assert len(ctx["recent_failures"]) == 1
    fail = ctx["recent_failures"][0]
    assert isinstance(fail, dict)
    assert "goal-20260410-001" in fail["file"]
    assert "root_cause" in fail


def test_json_output_format(project_with_state: Path):
    """Output can be serialized as hookSpecificOutput JSON."""
    ctx = restore(project_with_state)

    # Build the same output format as main()
    context_lines = []
    if ctx["active_goal"]:
        context_lines.append(
            f"[Harness] Active goal: {ctx['active_goal']} "
            f"(phase: {ctx.get('active_goal_phase', '?')})"
        )
        if ctx["unmet_criteria"]:
            ids = [c["id"] for c in ctx["unmet_criteria"]]
            context_lines.append(f"[Harness] Unmet criteria: {', '.join(ids)}")

    output = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": "\n".join(context_lines),
        }
    }

    serialized = json.dumps(output)
    parsed = json.loads(serialized)
    assert "hookSpecificOutput" in parsed
    assert "additionalContext" in parsed["hookSpecificOutput"]
    assert "goal-20260410-001" in parsed["hookSpecificOutput"]["additionalContext"]
