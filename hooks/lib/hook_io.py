"""Shared I/O utilities for hook scripts.

Normalizes the official Claude Code hook event JSON schema into
a consistent internal format, and provides output helpers.

Official stdin fields used across events:
  - session_id, cwd, hook_event_name, permission_mode
  - tool_name, tool_input, tool_response  (PreToolUse / PostToolUse)
  - prompt  (UserPromptSubmit)
  - agent_type, agent_id  (SubagentStart / SubagentStop)
  - source  (SessionStart)

Output conventions:
  - exit 0 + stdout JSON with hookSpecificOutput → context injection / allow
  - exit 2 + stderr message → deny with reason
"""

import json
import sys
from pathlib import Path


def read_event() -> dict:
    """Read and parse the hook event from stdin."""
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, OSError):
        return {}


def get_cwd(event: dict) -> str:
    """Get the project working directory from the event."""
    return event.get("cwd", "")


def get_tool_name(event: dict) -> str:
    return event.get("tool_name", "")


def get_tool_input(event: dict) -> dict:
    return event.get("tool_input", {})


def get_tool_response(event: dict) -> dict:
    """Get tool execution result (PostToolUse)."""
    resp = event.get("tool_response", {})
    return resp if isinstance(resp, dict) else {}


def get_agent_type(event: dict) -> str:
    """Get agent type from SubagentStart/Stop events."""
    return event.get("agent_type", "")


def get_prompt(event: dict) -> str:
    """Get user prompt text from UserPromptSubmit."""
    return event.get("prompt", "")


def get_file_path(event: dict) -> str:
    """Get file_path from tool_input, resolved against cwd to prevent traversal."""
    raw = event.get("tool_input", {}).get("file_path", "")
    if not raw:
        return ""
    cwd = get_cwd(event)
    if cwd:
        try:
            resolved = str(Path(raw).resolve())
            return resolved
        except (ValueError, OSError):
            pass
    return raw


def deny(reason: str) -> None:
    """Output a deny decision: reason to stderr, exit 2."""
    print(reason, file=sys.stderr)
    sys.exit(2)


def allow_with_context(context: str, event_name: str = "") -> None:
    """Output an allow decision with additional context injection."""
    output = {
        "hookSpecificOutput": {
            "hookEventName": event_name,
            "additionalContext": context,
        }
    }
    print(json.dumps(output))
    sys.exit(0)


def allow_silent() -> None:
    """Allow without output."""
    sys.exit(0)
