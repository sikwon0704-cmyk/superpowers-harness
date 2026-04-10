"""Tests for validate_contract.py state transitions and completion gate."""

import json
from pathlib import Path

import pytest

from validate_contract import (
    can_transition,
    check_completion_gate,
    save_contract,
)


# -- Helpers --

def _setup_project(tmp_path: Path, goal_id: str = "g1") -> Path:
    """Create a project with contract, progress, and trace for gate checks."""
    (tmp_path / ".harness" / "contracts").mkdir(parents=True)
    (tmp_path / ".harness" / "artifacts").mkdir(parents=True)
    (tmp_path / ".harness" / "progress").mkdir(parents=True)

    contract = {
        "goal_id": goal_id,
        "user_goal": "test feature",
        "acceptance_criteria": [
            {"id": "AC-1", "text": "Feature works", "status": "met", "evidence": ["test passed"]},
        ],
        "required_evidence": ["test output", "review verdict", "qa verdict"],
        "status": "review",
    }
    save_contract(tmp_path, goal_id, contract)

    (tmp_path / ".harness" / "progress" / f"{goal_id}.md").write_text(
        f"# Progress: {goal_id}\n\n- AC-1 done\n", encoding="utf-8")

    (tmp_path / ".harness" / "artifacts" / "trace.jsonl").write_text(
        json.dumps({
            "event": "tool_use",
            "test_results": [{"runner": "pytest", "passed": True}],
        }) + "\n",
        encoding="utf-8",
    )
    return tmp_path


def _write_artifact(tmp_path: Path, goal_id: str, prefix: str, verdict: str, evidence_refs: list[str]):
    path = tmp_path / ".harness" / "artifacts" / f"{prefix}-{goal_id}-001.json"
    path.write_text(json.dumps({
        "verdict": verdict,
        "evidence_refs": evidence_refs,
    }), encoding="utf-8")


# -- Valid transitions --

class TestValidTransitions:
    def test_draft_to_active(self):
        contract = {"goal_id": "g1", "status": "draft",
                     "acceptance_criteria": [{"id": "AC-1", "text": "x", "status": "unmet"}]}
        ok, reason = can_transition(contract, "active")
        assert ok, reason

    def test_active_to_review(self):
        contract = {"goal_id": "g1", "status": "active",
                     "acceptance_criteria": [{"id": "AC-1", "text": "x", "status": "met", "evidence": ["t"]}]}
        ok, reason = can_transition(contract, "review")
        assert ok, reason

    def test_review_to_done_criteria_only(self):
        """Without project_dir, only criteria check is performed (backward compat)."""
        contract = {"goal_id": "g1", "status": "review",
                     "acceptance_criteria": [{"id": "AC-1", "text": "x", "status": "met", "evidence": ["t"]}]}
        ok, reason = can_transition(contract, "done")
        assert ok, reason


# -- Invalid transitions --

class TestInvalidTransitions:
    def test_draft_to_done_blocked(self):
        contract = {"goal_id": "g1", "status": "draft",
                     "acceptance_criteria": [{"id": "AC-1", "text": "x", "status": "met", "evidence": ["t"]}]}
        ok, reason = can_transition(contract, "done")
        assert not ok
        assert "cannot transition" in reason

    def test_done_to_active_blocked(self):
        contract = {"goal_id": "g1", "status": "done",
                     "acceptance_criteria": [{"id": "AC-1", "text": "x", "status": "met", "evidence": ["t"]}]}
        ok, reason = can_transition(contract, "active")
        assert not ok
        assert "cannot transition" in reason


# -- Completion gate --

class TestCompletionGate:
    def test_all_criteria_met_done_allowed(self, tmp_path: Path):
        """Full gate passes when review, QA, evidence, and criteria all satisfied."""
        proj = _setup_project(tmp_path)
        _write_artifact(proj, "g1", "review", "APPROVE", ["review verdict"])
        _write_artifact(proj, "g1", "qa", "APPROVE", ["qa verdict", "test output"])

        contract = json.loads(
            (proj / ".harness" / "contracts" / "g1.json").read_text())
        ok, blockers = check_completion_gate(proj, contract)
        assert ok, f"should pass but blocked: {blockers}"

    def test_missing_review_blocks_done(self, tmp_path: Path):
        """No review artifact -> completion blocked."""
        proj = _setup_project(tmp_path)
        _write_artifact(proj, "g1", "qa", "APPROVE", ["qa verdict", "test output"])

        contract = json.loads(
            (proj / ".harness" / "contracts" / "g1.json").read_text())
        ok, blockers = check_completion_gate(proj, contract)
        assert not ok
        assert any("review" in b.lower() for b in blockers)

    def test_missing_qa_blocks_done(self, tmp_path: Path):
        """No QA artifact -> completion blocked."""
        proj = _setup_project(tmp_path)
        _write_artifact(proj, "g1", "review", "APPROVE", ["review verdict"])

        contract = json.loads(
            (proj / ".harness" / "contracts" / "g1.json").read_text())
        ok, blockers = check_completion_gate(proj, contract)
        assert not ok
        assert any("qa" in b.lower() for b in blockers)

    def test_unmet_criteria_blocks_done(self, tmp_path: Path):
        """Unmet acceptance criteria -> completion blocked."""
        proj = _setup_project(tmp_path)
        _write_artifact(proj, "g1", "review", "APPROVE", ["review verdict"])
        _write_artifact(proj, "g1", "qa", "APPROVE", ["qa verdict", "test output"])

        contract = json.loads(
            (proj / ".harness" / "contracts" / "g1.json").read_text())
        contract["acceptance_criteria"][0]["status"] = "unmet"
        save_contract(proj, "g1", contract)

        ok, blockers = check_completion_gate(proj, contract)
        assert not ok
        assert any("unmet" in b for b in blockers)
