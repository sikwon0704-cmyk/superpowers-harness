"""Build and maintain the artifact index at .harness/artifacts/index.json.

Scans .harness/artifacts/ for review/qa JSON files and .harness/failures/
for failure retro markdown files, then writes a structured index.

Usage:
    python build_artifact_index.py <project_dir>
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


def _extract_goal_and_ts(filename: str, prefix: str) -> tuple[str, str]:
    """Extract goal_id and timestamp from artifact filename.

    Pattern: <prefix>-<goal_id>-<ts>.json or <goal_id>-<ts>.md
    """
    name = filename.rsplit(".", 1)[0]  # strip extension
    if prefix and name.startswith(prefix + "-"):
        rest = name[len(prefix) + 1:]
    else:
        rest = name
    # Split on last dash group that looks like a timestamp (digits/hyphens)
    parts = rest.rsplit("-", 1)
    if len(parts) == 2 and parts[1].isdigit():
        return parts[0], parts[1]
    return rest, ""


def build_index(project_dir: Path) -> dict:
    """Scan artifacts and failures, return the index dict."""
    index = {
        "reviews": [],
        "qa": [],
        "failures": [],
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }

    artifacts_dir = project_dir / ".harness" / "artifacts"
    failures_dir = project_dir / ".harness" / "failures"

    # Review artifacts
    if artifacts_dir.exists():
        for f in sorted(artifacts_dir.glob("review-*.json"), key=lambda p: p.stat().st_mtime):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                goal_id, ts = _extract_goal_and_ts(f.name, "review")
                index["reviews"].append({
                    "file": f.name,
                    "goal_id": goal_id,
                    "verdict": data.get("verdict", "unknown"),
                    "ts": ts,
                })
            except (json.JSONDecodeError, OSError):
                continue

    # QA artifacts
    if artifacts_dir.exists():
        for f in sorted(artifacts_dir.glob("qa-*.json"), key=lambda p: p.stat().st_mtime):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                goal_id, ts = _extract_goal_and_ts(f.name, "qa")
                index["qa"].append({
                    "file": f.name,
                    "goal_id": goal_id,
                    "verdict": data.get("verdict", "unknown"),
                    "ts": ts,
                })
            except (json.JSONDecodeError, OSError):
                continue

    # Failure retros
    if failures_dir.exists():
        for f in sorted(failures_dir.glob("*.md"), key=lambda p: p.stat().st_mtime):
            goal_id, ts = _extract_goal_and_ts(f.name, "")
            index["failures"].append({
                "file": f.name,
                "goal_id": goal_id,
                "ts": ts,
            })

    return index


def write_index(project_dir: Path) -> Path:
    """Build and write the index file. Returns the index path."""
    index = build_index(project_dir)
    index_path = project_dir / ".harness" / "artifacts" / "index.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")
    return index_path


def main() -> None:
    if len(sys.argv) < 2:
        print(json.dumps({"error": "usage: build_artifact_index.py <project_dir>"}))
        sys.exit(1)

    project_dir = Path(sys.argv[1])
    path = write_index(project_dir)
    index = json.loads(path.read_text(encoding="utf-8"))
    print(json.dumps(index, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
