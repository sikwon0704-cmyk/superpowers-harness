"""Restore harness runtime context at session start.

Reads .harness/ state and produces a JSON summary of:
- Whether harness is set up
- Active goal and its phase
- Unmet acceptance criteria
- Recent failures
- Setup recommendation if harness is missing

Usage:
    python restore_runtime_context.py <project_dir>
"""

import json
import sys
from pathlib import Path


def restore(project_dir: Path) -> dict:
    """Build a session context summary from .harness/ state."""
    harness_dir = project_dir / ".harness"
    context = {
        "harness_exists": harness_dir.exists(),
        "setup_recommended": not harness_dir.exists(),
        "active_goal": None,
        "active_goal_phase": None,
        "contract_status": None,
        "unmet_criteria": [],
        "recent_failures": [],
        "profile": None,
    }

    if not harness_dir.exists():
        return context

    # Load profile
    profile_path = harness_dir / "profile.json"
    if profile_path.exists():
        try:
            context["profile"] = json.loads(profile_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    # Find active goal (most recent non-done goal)
    goals_dir = harness_dir / "goals"
    if goals_dir.exists():
        goal_files = sorted(goals_dir.glob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True)
        for gf in goal_files:
            content = gf.read_text(encoding="utf-8")
            for status in ("draft", "active", "review"):
                if f"Status: {status}" in content or f"**Status**: {status}" in content:
                    context["active_goal"] = gf.stem
                    context["active_goal_phase"] = status
                    break
            if context["active_goal"]:
                break

    # Load contract for active goal
    if context["active_goal"]:
        contract_path = harness_dir / "contracts" / f"{context['active_goal']}.json"
        if contract_path.exists():
            try:
                contract = json.loads(contract_path.read_text(encoding="utf-8"))
                context["contract_status"] = contract.get("status")
                context["unmet_criteria"] = [
                    {"id": ac["id"], "text": ac.get("text", "")}
                    for ac in contract.get("acceptance_criteria", [])
                    if ac.get("status") == "unmet"
                ]
            except (json.JSONDecodeError, OSError):
                pass

    # Recent failures (up to 3) — parse retro content for structural re-injection
    failures_dir = harness_dir / "failures"
    if failures_dir.exists():
        fail_files = sorted(failures_dir.glob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True)[:3]
        for ff in fail_files:
            entry: dict = {"file": ff.stem}
            try:
                content = ff.read_text(encoding="utf-8")
                entry.update(_parse_retro_sections(content))
            except OSError:
                pass
            context["recent_failures"].append(entry)

    return context


def _parse_retro_sections(content: str) -> dict:
    """Extract structured fields from a failure retro markdown file."""
    sections: dict[str, str] = {}
    current_key = None
    current_lines: list[str] = []

    heading_map = {
        "root cause": "root_cause",
        "why previous checks missed it": "why_missed",
        "remediation": "remediation",
        "candidate rule": "candidate_rule",
        "next replan": "next_replan",
    }

    for line in content.split("\n"):
        if line.startswith("## "):
            if current_key and current_lines:
                sections[current_key] = "\n".join(current_lines).strip()
            heading = line[3:].strip().lower()
            current_key = heading_map.get(heading)
            current_lines = []
        elif current_key is not None:
            current_lines.append(line)

    if current_key and current_lines:
        sections[current_key] = "\n".join(current_lines).strip()

    return sections


def main() -> None:
    """Entry point for SessionStart hook.

    Official stdin schema: { session_id, cwd, hook_event_name, source }
    Official output: hookSpecificOutput.additionalContext on stdout (exit 0)
    Also supports CLI: restore_runtime_context.py <project_dir>
    """
    # Determine project dir from stdin event or CLI arg
    project_dir = None
    if len(sys.argv) >= 2:
        project_dir = Path(sys.argv[1])
    else:
        try:
            raw = sys.stdin.read()
            event = json.loads(raw) if raw.strip() else {}
            cwd = event.get("cwd", "")
            if cwd:
                project_dir = Path(cwd)
        except (json.JSONDecodeError, OSError):
            pass

    if project_dir is None:
        sys.exit(0)

    result = restore(project_dir)

    # Format as hookSpecificOutput for Claude Code context injection
    context_lines = []
    if result["setup_recommended"]:
        context_lines.append("[Harness] Not initialized. Run /harness-setup to begin.")
    elif result["active_goal"]:
        context_lines.append(f"[Harness] Active goal: {result['active_goal']} (phase: {result.get('active_goal_phase', '?')})")
        if result["unmet_criteria"]:
            ids = [c["id"] for c in result["unmet_criteria"]]
            context_lines.append(f"[Harness] Unmet criteria: {', '.join(ids)}")
        if result["recent_failures"]:
            for fail in result["recent_failures"]:
                if isinstance(fail, dict):
                    context_lines.append(f"[Harness] Failure: {fail.get('file', '?')}")
                    if fail.get("root_cause"):
                        context_lines.append(f"  Root cause: {fail['root_cause']}")
                    if fail.get("why_missed"):
                        context_lines.append(f"  Why missed: {fail['why_missed']}")
                    if fail.get("remediation"):
                        context_lines.append(f"  Remediation: {fail['remediation']}")
                    if fail.get("candidate_rule"):
                        context_lines.append(f"  Candidate rule: {fail['candidate_rule']}")
                else:
                    context_lines.append(f"[Harness] Failure: {fail}")

    if context_lines:
        output = {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": "\n".join(context_lines),
            }
        }
        print(json.dumps(output))

    sys.exit(0)


if __name__ == "__main__":
    main()
