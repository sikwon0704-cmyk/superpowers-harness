"""Validate and manage contract state transitions.

Contracts follow: draft → active → review → done | failed

Completion gate (done) requires ALL of:
  - All acceptance criteria met
  - At least one review artifact with verdict=APPROVE
  - At least one QA artifact with verdict=APPROVE
  - All required_evidence types present

Usage:
    python validate_contract.py <project_dir> <goal_id> [--transition <new_status>]
    python validate_contract.py <project_dir> <goal_id> --check
"""

import json
import sys
from pathlib import Path

VALID_STATUSES = {"draft", "active", "review", "done", "failed"}
VALID_TRANSITIONS = {
    "draft": {"active"},
    "active": {"review", "failed"},
    "review": {"done", "failed", "active"},  # active = re-open after REQUEST_CHANGES
    "done": set(),
    "failed": {"active"},  # retry
}
CRITERION_STATUSES = {"unmet", "met", "failed"}


def load_contract(project_dir: Path, goal_id: str) -> dict | None:
    """Load a contract from .harness/contracts/."""
    path = project_dir / ".harness" / "contracts" / f"{goal_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def save_contract(project_dir: Path, goal_id: str, contract: dict) -> None:
    """Save a contract back to disk."""
    path = project_dir / ".harness" / "contracts" / f"{goal_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(contract, indent=2, ensure_ascii=False), encoding="utf-8")


def validate(contract: dict) -> list[str]:
    """Return a list of validation errors. Empty list means valid."""
    errors = []

    if "goal_id" not in contract:
        errors.append("missing goal_id")
    if "status" not in contract:
        errors.append("missing status")
    elif contract["status"] not in VALID_STATUSES:
        errors.append(f"invalid status: {contract['status']}")

    criteria = contract.get("acceptance_criteria", [])
    if not criteria:
        errors.append("no acceptance_criteria defined")

    for i, ac in enumerate(criteria):
        if "id" not in ac:
            errors.append(f"criterion {i}: missing id")
        if "text" not in ac:
            errors.append(f"criterion {i}: missing text")
        if ac.get("status") not in CRITERION_STATUSES:
            errors.append(f"criterion {i}: invalid status '{ac.get('status')}'")

    return errors


def _find_latest_artifact(project_dir: Path, goal_id: str, prefix: str) -> dict | None:
    """Find the most recent artifact file matching prefix-<goal_id>-*.json."""
    artifacts_dir = project_dir / ".harness" / "artifacts"
    if not artifacts_dir.exists():
        return None
    matches = sorted(
        artifacts_dir.glob(f"{prefix}-{goal_id}-*.json"),
        key=lambda f: f.stat().st_mtime, reverse=True,
    )
    if not matches:
        return None
    try:
        return json.loads(matches[0].read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def check_completion_gate(project_dir: Path, contract: dict) -> tuple[bool, list[str]]:
    """Verify all hard completion requirements for a 'done' transition.

    Returns (pass, list_of_blocking_reasons).
    """
    goal_id = contract.get("goal_id", "")
    blockers: list[str] = []

    # 1. All criteria must be met AND have at least one evidence item
    criteria = contract.get("acceptance_criteria", [])
    unmet = [ac for ac in criteria if ac.get("status") != "met"]
    if unmet:
        ids = [ac.get("id", "?") for ac in unmet]
        blockers.append(f"unmet criteria: {', '.join(ids)}")
    # Check per-criterion evidence
    for ac in criteria:
        if ac.get("status") == "met" and not ac.get("evidence"):
            blockers.append(f"criterion {ac.get('id', '?')} is 'met' but has no evidence")

    # 2. Review artifact with APPROVE verdict
    review = _find_latest_artifact(project_dir, goal_id, "review")
    if review is None:
        blockers.append("no review artifact found")
    elif review.get("verdict") != "APPROVE":
        blockers.append(f"review verdict is '{review.get('verdict')}', not APPROVE")

    # 3. QA artifact with APPROVE verdict
    qa = _find_latest_artifact(project_dir, goal_id, "qa")
    if qa is None:
        blockers.append("no QA artifact found")
    elif qa.get("verdict") != "APPROVE":
        blockers.append(f"QA verdict is '{qa.get('verdict')}', not APPROVE")

    # 4. Required evidence — prefer artifact-backed refs over free-form strings
    required = contract.get("required_evidence", [])

    # Collect evidence from artifacts (strong) and criteria (weak)
    artifact_evidence: set[str] = set()
    if review:
        for ref in review.get("evidence_refs", []):
            artifact_evidence.add(str(ref).lower())
    if qa:
        for ref in qa.get("evidence_refs", []):
            artifact_evidence.add(str(ref).lower())

    # Auto-inject semantic evidence tokens from verdicts
    if review and review.get("verdict") == "APPROVE":
        artifact_evidence.add("review verdict")
    if qa and qa.get("verdict") == "APPROVE":
        artifact_evidence.add("qa verdict")

    # Also check trace.jsonl for test/build/lint execution records
    trace_evidence: set[str] = set()
    trace_path = project_dir / ".harness" / "artifacts" / "trace.jsonl"
    if trace_path.exists():
        try:
            for line in trace_path.read_text(encoding="utf-8").strip().split("\n"):
                if not line.strip():
                    continue
                entry = json.loads(line)
                if entry.get("test_results"):
                    for tr in entry["test_results"]:
                        trace_evidence.add(tr.get("runner", "").lower())
                        if tr.get("passed"):
                            trace_evidence.add("test passed")
                            trace_evidence.add("relevant test output")
        except (json.JSONDecodeError, OSError):
            pass

    # Criterion-level evidence (weaker — accepted but flagged)
    criterion_evidence: set[str] = set()
    for ac in criteria:
        for ev in ac.get("evidence", []):
            if isinstance(ev, str):
                criterion_evidence.add(ev.lower())

    all_evidence = artifact_evidence | trace_evidence | criterion_evidence

    for req in required:
        req_lower = req.lower()
        if not any(req_lower in ev for ev in all_evidence):
            blockers.append(f"missing required evidence: '{req}'")

    # 5. Progress file must exist for this goal
    progress_dir = project_dir / ".harness" / "progress"
    progress_files = list(progress_dir.glob(f"{goal_id}*")) if progress_dir.exists() else []
    if not progress_files:
        blockers.append(f"no progress file found for {goal_id}")

    # 6. Trace must contain at least one test/build/lint execution
    if not trace_evidence:
        blockers.append("no test/build/lint execution found in trace")

    # 7. If failures exist for this goal, retro must be completed
    failures_dir = project_dir / ".harness" / "failures"
    if failures_dir.exists():
        fail_files = list(failures_dir.glob(f"{goal_id}-*"))
        if fail_files:
            # Check that at least one retro has remediation filled
            has_retro_complete = False
            for ff in fail_files:
                try:
                    content = ff.read_text(encoding="utf-8")
                    if "remediation" in content.lower() or "## Remediation" in content:
                        has_retro_complete = True
                        break
                except OSError:
                    pass
            if not has_retro_complete:
                blockers.append("failure retro exists but remediation not documented")

    return len(blockers) == 0, blockers


def can_transition(
    contract: dict,
    new_status: str,
    project_dir: Path | None = None,
) -> tuple[bool, str]:
    """Check if a status transition is allowed.

    When project_dir is provided and new_status is 'done', the full
    completion gate (review/QA/evidence) is enforced.  When project_dir
    is None, only criteria-level checks are performed (backward compat).
    """
    current = contract.get("status", "draft")

    if new_status not in VALID_STATUSES:
        return False, f"invalid target status: {new_status}"

    if new_status not in VALID_TRANSITIONS.get(current, set()):
        return False, f"cannot transition from '{current}' to '{new_status}'"

    if new_status == "done":
        if project_dir is not None:
            ok, blockers = check_completion_gate(project_dir, contract)
            if not ok:
                return False, f"completion gate blocked: {'; '.join(blockers)}"
        else:
            # Lightweight check: criteria only
            criteria = contract.get("acceptance_criteria", [])
            unmet = [ac for ac in criteria if ac.get("status") != "met"]
            if unmet:
                ids = [ac.get("id", "?") for ac in unmet]
                return False, f"cannot complete: unmet criteria: {', '.join(ids)}"

    return True, ""


def transition(contract: dict, new_status: str) -> dict:
    """Apply a status transition. Caller must check can_transition first."""
    contract["status"] = new_status
    return contract


def is_complete(contract: dict) -> bool:
    """Check if all completion conditions are met."""
    if contract.get("status") != "done":
        return False
    criteria = contract.get("acceptance_criteria", [])
    return all(ac.get("status") == "met" for ac in criteria)


def main() -> None:
    if len(sys.argv) < 3:
        print(json.dumps({"error": "usage: validate_contract.py <project_dir> <goal_id> [--transition <status>] [--check]"}))
        sys.exit(1)

    project_dir = Path(sys.argv[1])
    goal_id = sys.argv[2]

    contract = load_contract(project_dir, goal_id)
    if contract is None:
        print(json.dumps({"error": f"contract not found for {goal_id}"}))
        sys.exit(1)

    if "--check" in sys.argv:
        errors = validate(contract)
        print(json.dumps({"valid": len(errors) == 0, "errors": errors}))
        sys.exit(0 if not errors else 1)

    if "--transition" in sys.argv:
        idx = sys.argv.index("--transition")
        if idx + 1 >= len(sys.argv):
            print(json.dumps({"error": "missing status after --transition"}))
            sys.exit(1)
        new_status = sys.argv[idx + 1]
        ok, reason = can_transition(contract, new_status, project_dir)
        if not ok:
            print(json.dumps({"error": reason}))
            sys.exit(1)
        contract = transition(contract, new_status)
        save_contract(project_dir, goal_id, contract)
        print(json.dumps({"status": new_status, "goal_id": goal_id}))
        sys.exit(0)

    # Default: validate and report
    errors = validate(contract)
    print(json.dumps({
        "goal_id": goal_id,
        "status": contract.get("status"),
        "valid": len(errors) == 0,
        "errors": errors,
        "criteria_summary": {
            ac.get("id", "?"): ac.get("status", "unknown")
            for ac in contract.get("acceptance_criteria", [])
        },
    }))


if __name__ == "__main__":
    main()
