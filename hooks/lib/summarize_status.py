"""Summarize current harness state for PreCompact/SessionEnd.

Writes a summary to .harness/progress/session-summary.md so that
the next session or post-compaction context can pick up cleanly.

Usage:
    python summarize_status.py <project_dir>
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def summarize(project_dir: Path) -> str:
    """Generate a markdown summary of current harness state."""
    harness_dir = project_dir / ".harness"
    lines = [f"# Session Summary — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}", ""]

    if not harness_dir.exists():
        lines.append("No harness initialized. Run `/harness-setup` to begin.")
        return "\n".join(lines)

    # Active goal
    goals_dir = harness_dir / "goals"
    active_goal = None
    if goals_dir.exists():
        for gf in sorted(goals_dir.glob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True):
            content = gf.read_text(encoding="utf-8")
            if any(f"Status: {s}" in content or f"**Status**: {s}" in content for s in ("draft", "active", "review")):
                active_goal = gf.stem
                break

    if active_goal:
        lines.append(f"## Active Goal: `{active_goal}`")
    else:
        lines.append("## No active goal")

    # Contract status
    if active_goal:
        contract_path = harness_dir / "contracts" / f"{active_goal}.json"
        if contract_path.exists():
            try:
                contract = json.loads(contract_path.read_text(encoding="utf-8"))
                lines.append(f"\nContract status: **{contract.get('status', 'unknown')}**")
                lines.append("\n### Acceptance Criteria")
                for ac in contract.get("acceptance_criteria", []):
                    mark = "x" if ac.get("status") == "met" else " "
                    lines.append(f"- [{mark}] {ac.get('id', '?')}: {ac.get('text', '')}")
            except (json.JSONDecodeError, OSError):
                lines.append("\n(contract file unreadable)")

    # Recent failures
    failures_dir = harness_dir / "failures"
    if failures_dir.exists():
        fail_files = sorted(failures_dir.glob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True)[:3]
        if fail_files:
            lines.append("\n### Recent Failures")
            for ff in fail_files:
                lines.append(f"- `{ff.name}`")

    lines.append("")
    return "\n".join(lines)


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: summarize_status.py <project_dir>", file=sys.stderr)
        sys.exit(1)

    project_dir = Path(sys.argv[1])
    summary = summarize(project_dir)

    # Write to progress directory
    progress_dir = project_dir / ".harness" / "progress"
    progress_dir.mkdir(parents=True, exist_ok=True)
    (progress_dir / "session-summary.md").write_text(summary, encoding="utf-8")

    # Rebuild artifact index
    try:
        import importlib.util
        idx_script = Path(__file__).resolve().parent / "build_artifact_index.py"
        if idx_script.exists():
            spec = importlib.util.spec_from_file_location("build_artifact_index", idx_script)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            mod.write_index(project_dir)
    except Exception:
        pass  # index rebuild is best-effort

    sys.stdout.buffer.write(summary.encode("utf-8"))
    sys.stdout.buffer.write(b"\n")


if __name__ == "__main__":
    main()
