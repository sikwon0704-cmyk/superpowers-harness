"""PostToolUse trace logger.

Appends a JSONL entry to .harness/artifacts/trace.jsonl after each tool use.
Also handles SubagentStart/Stop events when called with --event flag.

Enrichments beyond basic logging:
  - changed-files snapshot for Edit/Write
  - test result detection from Bash output
  - evidence candidate collection
  - artifact index maintenance

Usage:
    Invoked by hooks.json PostToolUse / SubagentStart / SubagentStop events.
    Reads JSON from stdin.
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

TEST_RESULT_PATTERNS = [
    # pytest
    (r"(\d+)\s+passed", "pytest"),
    (r"FAILED", "pytest"),
    # jest
    (r"Tests:\s+(\d+)\s+passed", "jest"),
    (r"Test Suites:\s+(\d+)\s+passed", "jest"),
    # go test
    (r"^ok\s+", "go_test"),
    (r"^FAIL\s+", "go_test"),
    # generic
    (r"BUILD\s+(SUCCESS|FAILED)", "build"),
    (r"lint.*?(passed|failed|error)", "lint"),
]


def _is_tracing_enabled(project_dir: Path) -> bool:
    """Check if tracing is enabled via .harness/config.json.

    Returns False if:
      - .harness/ directory doesn't exist
      - config.json has trace_enabled set to false
    Returns True otherwise (default: tracing is on).
    """
    harness_dir = project_dir / ".harness"
    if not harness_dir.exists():
        return False

    config_path = harness_dir / "config.json"
    if not config_path.exists():
        return True

    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        return config.get("trace_enabled", True) is not False
    except (json.JSONDecodeError, OSError):
        return True


def log_trace(project_dir: Path, entry: dict) -> None:
    """Append a trace entry to the JSONL log."""
    trace_path = project_dir / ".harness" / "artifacts" / "trace.jsonl"
    trace_path.parent.mkdir(parents=True, exist_ok=True)

    line = json.dumps(entry, ensure_ascii=False)
    with open(trace_path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def update_changed_files_index(project_dir: Path, file_path: str, tool: str) -> None:
    """Maintain a running list of files changed in this session."""
    index_path = project_dir / ".harness" / "artifacts" / "changed-files.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)

    data: dict = {"files": {}}
    if index_path.exists():
        try:
            data = json.loads(index_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    files = data.setdefault("files", {})
    if file_path not in files:
        files[file_path] = {"first_touched": datetime.now(timezone.utc).isoformat(), "tools": []}
    if tool not in files[file_path]["tools"]:
        files[file_path]["tools"].append(tool)

    data["last_updated"] = datetime.now(timezone.utc).isoformat()
    index_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def detect_test_results(command: str, output: str) -> list[dict]:
    """Scan command output for test/build/lint results."""
    results = []
    for pattern, runner in TEST_RESULT_PATTERNS:
        if re.search(pattern, output, re.MULTILINE | re.IGNORECASE):
            passed = "FAIL" not in output.upper() and "FAILED" not in output.upper()
            results.append({
                "runner": runner,
                "passed": passed,
                "snippet": output[:500],
            })
            break  # one match per output is enough
    return results


def collect_evidence_candidate(project_dir: Path, entry: dict) -> None:
    """If this trace entry looks like evidence, add it to the candidate list."""
    evidence_path = project_dir / ".harness" / "artifacts" / "evidence-candidates.jsonl"
    evidence_path.parent.mkdir(parents=True, exist_ok=True)

    # Evidence candidates: test results, review/qa artifacts, build results
    dominated = entry.get("test_results") or entry.get("event") in ("subagent_start", "subagent_stop")
    if not dominated:
        return

    line = json.dumps({
        "ts": entry.get("ts"),
        "type": "test_result" if entry.get("test_results") else "subagent_event",
        "agent": entry.get("agent", ""),
        "summary": entry.get("test_results", [{}])[0].get("snippet", "")[:200] if entry.get("test_results") else "",
    }, ensure_ascii=False)
    with open(evidence_path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def main() -> None:
    """Entry point for PostToolUse / SubagentStart / SubagentStop hook.

    Official PostToolUse stdin:
      { session_id, cwd, tool_name, tool_use_id, tool_input, tool_response }
    Official SubagentStart/Stop stdin:
      { session_id, cwd, agent_type, agent_id }
    """
    if len(sys.argv) < 2:
        sys.exit(0)

    project_dir_arg = sys.argv[1]
    event_type = "tool_use"
    if "--event" in sys.argv:
        idx = sys.argv.index("--event")
        if idx + 1 < len(sys.argv):
            event_type = sys.argv[idx + 1]

    try:
        raw = sys.stdin.read()
        event = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, OSError):
        event = {}

    # Determine project dir: prefer cwd from event, fall back to arg
    cwd = event.get("cwd", "")
    project_dir = Path(cwd) if cwd else Path(project_dir_arg)

    # Check if tracing is enabled before doing any work
    if not _is_tracing_enabled(project_dir):
        sys.exit(0)

    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event_type,
        "tool": event.get("tool_name", ""),
        "agent": event.get("agent_type", ""),  # official: agent_type
    }

    tool_input = event.get("tool_input", {})
    # Official: tool_response; legacy: tool_result
    tool_result = event.get("tool_response", event.get("tool_result", {}))
    tool_name = event.get("tool_name", "")

    # File path tracking
    if "file_path" in tool_input:
        entry["file"] = tool_input["file_path"]
        # Track changed files for Edit/Write
        if tool_name in ("Edit", "Write"):
            update_changed_files_index(project_dir, tool_input["file_path"], tool_name)
    elif "command" in tool_input:
        cmd = tool_input["command"]
        entry["command"] = cmd[:200]

    # Tool result status
    if isinstance(tool_result, dict):
        entry["result"] = "error" if tool_result.get("is_error") else "ok"
        # Detect test/build results from Bash output
        if tool_name == "Bash" and not tool_result.get("is_error"):
            output = str(tool_result.get("output", ""))
            test_results = detect_test_results(
                tool_input.get("command", ""), output)
            if test_results:
                entry["test_results"] = test_results

    log_trace(project_dir, entry)
    collect_evidence_candidate(project_dir, entry)


if __name__ == "__main__":
    main()
