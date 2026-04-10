"""Write a failure retro file to .harness/failures/.

Usage:
    python write_failure_retro.py <project_dir> <goal_id> --symptom <s> --root-cause <c> --remediation <r>
    Or: reads JSON from stdin with symptom, root_cause, why_missed, remediation, candidate_rule fields.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def write_retro(project_dir: Path, goal_id: str, data: dict) -> Path:
    """Write a failure retro markdown file. Returns the file path."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    failures_dir = project_dir / ".harness" / "failures"
    failures_dir.mkdir(parents=True, exist_ok=True)

    path = failures_dir / f"{goal_id}-{ts}.md"
    content = f"""# Failure Retro: {goal_id} — {ts}

## Symptom

{data.get('symptom', '(not specified)')}

## Root Cause

{data.get('root_cause', '(not specified)')}

## Why Previous Checks Missed It

{data.get('why_missed', '(not specified)')}

## Remediation

{data.get('remediation', '(not specified)')}

## Candidate Rule

{data.get('candidate_rule', '(none)')}

## Promoted?

pending

## Next Replan

{data.get('next_replan', '(to be determined)')}
"""
    path.write_text(content, encoding="utf-8")
    return path


def main() -> None:
    if len(sys.argv) < 3:
        print(json.dumps({"error": "usage: write_failure_retro.py <project_dir> <goal_id>"}))
        sys.exit(1)

    project_dir = Path(sys.argv[1])
    goal_id = sys.argv[2]

    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, OSError):
        data = {}

    path = write_retro(project_dir, goal_id, data)
    print(json.dumps({"written": str(path)}))


if __name__ == "__main__":
    main()
