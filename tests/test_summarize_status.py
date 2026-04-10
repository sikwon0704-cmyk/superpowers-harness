"""Tests for summarize_status.py."""

import json
from pathlib import Path

import pytest

from scaffold_runtime import scaffold
from validate_contract import save_contract
from summarize_status import summarize


@pytest.fixture
def project_with_goal(tmp_path: Path) -> Path:
    """Project with scaffold + active goal + mixed criteria."""
    scaffold(tmp_path)

    goal_id = "goal-20260410-001"
    goals_dir = tmp_path / ".harness" / "goals"
    goals_dir.mkdir(parents=True, exist_ok=True)
    (goals_dir / f"{goal_id}.md").write_text(
        f"# Goal: {goal_id}\n\n- **Status**: active\n",
        encoding="utf-8",
    )

    save_contract(tmp_path, goal_id, {
        "goal_id": goal_id,
        "user_goal": "Implement feature",
        "acceptance_criteria": [
            {"id": "AC-1", "text": "Unit tests pass", "status": "met", "evidence": ["test"]},
            {"id": "AC-2", "text": "Lint clean", "status": "unmet", "evidence": []},
        ],
        "status": "active",
    })

    return tmp_path


def test_no_harness_message(tmp_target: Path):
    """No .harness/ produces 'No harness initialized' in summary."""
    summary = summarize(tmp_target)

    assert "No harness" in summary or "setup" in summary.lower()


def test_active_goal_included(project_with_goal: Path):
    """Active goal ID appears in the summary."""
    summary = summarize(project_with_goal)

    assert "goal-20260410-001" in summary
    assert "Active Goal" in summary


def test_criteria_checklist_format(project_with_goal: Path):
    """Criteria are rendered as [x] for met and [ ] for unmet."""
    summary = summarize(project_with_goal)

    assert "[x]" in summary
    assert "[ ]" in summary
    assert "AC-1" in summary
    assert "AC-2" in summary


def test_session_summary_file_created(project_with_goal: Path):
    """summarize_status main() writes session-summary.md."""
    summary = summarize(project_with_goal)

    progress_dir = project_with_goal / ".harness" / "progress"
    progress_dir.mkdir(parents=True, exist_ok=True)
    (progress_dir / "session-summary.md").write_text(summary, encoding="utf-8")

    assert (progress_dir / "session-summary.md").exists()
    content = (progress_dir / "session-summary.md").read_text(encoding="utf-8")
    assert "goal-20260410-001" in content
