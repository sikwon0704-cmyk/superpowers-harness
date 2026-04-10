"""PreToolUse guard — block policy violations.

Official Claude Code PreToolUse stdin schema:
  { session_id, cwd, tool_name, tool_use_id, tool_input, permission_mode }

Output:
  - exit 0 = allow (optionally with hookSpecificOutput JSON on stdout)
  - exit 2 = deny (reason on stderr)

Agent identity is read from agent_type (official common field) first,
then falls back to agent_name for backward compatibility with tests.

Superpowers role system (4 roles):
  - implementer
  - code-reviewer
  - qa-browser
  - rule-curator
  - (empty = main session, global guard only)
"""

import json
import re
import sys
from pathlib import Path

# Allow sibling imports when invoked directly
if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from hook_io import read_event, deny, allow_silent


# --- Global deny patterns ---

SECRET_PATTERNS = [
    r"\.env($|[./\\])",
    r"secrets[/\\]",
    r"credentials",
    r"\.pem$",
    r"\.key$",
    r"id_rsa",
    r"\.secret",
]

GIT_INTERNAL_PATTERN = r"\.git[/\\]"

DESTRUCTIVE_BASH_PATTERNS = [
    r"git\s+push\s+.*--force",
    r"git\s+push\s+-f\b",
    r"rm\s+-rf\s+[/\\.]",
    r"git\s+reset\s+--hard",
]


def _normalize(path: str) -> str:
    """Normalize path separators for consistent matching."""
    return path.replace("\\", "/")


def _is_harness_path(path: str) -> bool:
    p = _normalize(path)
    return ".harness" in p or ".claude" in p


def _resolve_file_path(raw_path: str, cwd: str) -> str:
    """Resolve file_path against cwd to prevent traversal attacks."""
    if not raw_path:
        return ""
    try:
        return str(Path(raw_path).resolve())
    except (ValueError, OSError):
        return raw_path


def _load_config(cwd: str) -> dict:
    """Load .harness/config.json or return defaults."""
    if not cwd:
        return {"guard_enabled": True}
    config_path = Path(cwd) / ".harness" / "config.json"
    if not config_path.exists():
        return {"guard_enabled": True}
    try:
        return json.loads(config_path.read_text())
    except (json.JSONDecodeError, OSError):
        return {"guard_enabled": True}


# --- Global checks ---

def check_secret_access(tool_name: str, tool_input: dict) -> str | None:
    paths_to_check = []
    if tool_name in ("Read", "Edit", "Write"):
        paths_to_check.append(tool_input.get("file_path", ""))
    elif tool_name == "Bash":
        paths_to_check.append(tool_input.get("command", ""))
    elif tool_name in ("Glob", "Grep"):
        paths_to_check.extend([tool_input.get("pattern", ""), tool_input.get("path", "")])

    for path in paths_to_check:
        for pat in SECRET_PATTERNS:
            if re.search(pat, path, re.IGNORECASE):
                return f"DENIED: access to secret/sensitive file matching '{pat}'"
    return None


def check_git_internal(tool_name: str, tool_input: dict) -> str | None:
    if tool_name in ("Edit", "Write"):
        path = tool_input.get("file_path", "")
        if re.search(GIT_INTERNAL_PATTERN, path):
            return "DENIED: direct modification of .git/ internals is forbidden"
    return None


def check_destructive_bash(tool_name: str, tool_input: dict) -> str | None:
    if tool_name != "Bash":
        return None
    cmd = tool_input.get("command", "")
    for pat in DESTRUCTIVE_BASH_PATTERNS:
        if re.search(pat, cmd, re.IGNORECASE):
            return f"DENIED: destructive command blocked (matched '{pat}')"
    return None


def check_evidence_gate(tool_name: str, tool_input: dict, cwd: str) -> str | None:
    if tool_name != "Bash":
        return None
    cmd = tool_input.get("command", "")
    if "validate_contract" in cmd and "--transition" in cmd and "done" in cmd:
        if cwd:
            artifacts = Path(cwd) / ".harness" / "artifacts"
            if not artifacts.exists():
                return "DENIED: cannot transition to done — no artifacts directory"
            review_files = sorted(
                artifacts.glob("review-*.json"),
                key=lambda f: f.stat().st_mtime,
                reverse=True,
            )
            if not review_files:
                return "DENIED: cannot transition to done — no review artifact found"
            try:
                review = json.loads(review_files[0].read_text(encoding="utf-8"))
                if review.get("verdict") != "APPROVE":
                    return (
                        f"DENIED: cannot transition to done — review verdict is "
                        f"'{review.get('verdict')}', not APPROVE"
                    )
            except (json.JSONDecodeError, OSError):
                return "DENIED: cannot transition to done — review artifact unreadable"
            qa_files = sorted(
                artifacts.glob("qa-*.json"),
                key=lambda f: f.stat().st_mtime,
                reverse=True,
            )
            if not qa_files:
                return "DENIED: cannot transition to done — no QA artifact found"
            try:
                qa = json.loads(qa_files[0].read_text(encoding="utf-8"))
                if qa.get("verdict") != "APPROVE":
                    return (
                        f"DENIED: cannot transition to done — QA verdict is "
                        f"'{qa.get('verdict')}', not APPROVE"
                    )
            except (json.JSONDecodeError, OSError):
                return "DENIED: cannot transition to done — QA artifact unreadable"
    return None


def check_contract_status_bypass(tool_name: str, tool_input: dict, cwd: str) -> str | None:
    """Block direct writes that set contract status to 'done' outside validate_contract."""
    if tool_name == "Edit":
        path = _normalize(tool_input.get("file_path", ""))
        content = tool_input.get("new_string", "")
    elif tool_name == "Write":
        path = _normalize(tool_input.get("file_path", ""))
        content = tool_input.get("content", "")
    elif tool_name == "Bash":
        cmd = tool_input.get("command", "")
        if ".harness/contracts/" in cmd and re.search(r'"status"\s*:\s*"done"', cmd):
            return (
                "DENIED: cannot set contract status to 'done' directly "
                "— use validate_contract --transition done"
            )
        if re.search(r"\b(?:cp|mv)\s+.*\.harness/contracts/", cmd):
            return (
                "DENIED: cannot copy/move files into .harness/contracts/ "
                "— use validate_contract for state transitions"
            )
        return None
    else:
        return None

    if ".harness/contracts/" not in path:
        return None
    if re.search(r'"status"\s*:\s*"done"', content):
        return (
            "DENIED: cannot set contract status to 'done' directly "
            "— use validate_contract --transition done"
        )
    return None


def check_contract_required(tool_name: str, tool_input: dict, cwd: str) -> str | None:
    """Opt-in contract requirement: only enforced when config.json sets contract_required=true."""
    if tool_name not in ("Edit", "Write"):
        return None
    if not cwd:
        return None
    path = _normalize(tool_input.get("file_path", ""))
    if ".harness" in path or ".claude" in path:
        return None
    harness_dir = Path(cwd) / ".harness"
    if not harness_dir.exists():
        return None
    # opt-in: config.json must explicitly enable this guard
    config_path = harness_dir / "config.json"
    try:
        config = json.loads(config_path.read_text()) if config_path.exists() else {}
    except (json.JSONDecodeError, OSError):
        config = {}
    if not config.get("contract_required", False):
        return None
    # no contracts directory → pass
    contracts_dir = harness_dir / "contracts"
    if not contracts_dir.exists():
        return None
    contract_files = list(contracts_dir.glob("*.json"))
    if not contract_files:
        return None
    # active/review contract exists → pass
    for cf in contract_files:
        try:
            c = json.loads(cf.read_text(encoding="utf-8"))
            if c.get("status") in ("active", "review"):
                return None
        except (json.JSONDecodeError, OSError):
            continue
    return "DENIED: no active contract — create a goal before editing product code"


def check_push_discipline(
    tool_name: str,
    tool_input: dict,
    agent_name: str,
    skill_name: str,
    is_hook_context: bool = False,
) -> str | None:
    if tool_name != "Bash":
        return None
    cmd = tool_input.get("command", "")
    if not re.search(r"git\s+push\b", cmd, re.IGNORECASE):
        return None
    if re.search(r"--force|-f\b", cmd, re.IGNORECASE):
        return None  # handled by destructive check
    if not agent_name:
        if is_hook_context:
            return "DENIED: git push blocked — agent identity unknown in hook context"
        return None  # user-direct — allowed
    if agent_name.lower() == "release" or skill_name.lower() == "release":
        return None
    return "DENIED: git push is restricted to the release flow — use /release"


# --- Bash file-write patterns for read-only role enforcement ---

BASH_WRITE_PATTERNS: list[str] = [
    r"(?:^|[|;&])\s*(?:echo|printf)\b.*?>\s*\S",   # echo/printf > file
    r"(?:^|[|;&])\s*cat\b.*?>\s*\S",                 # cat > file
    r"\btee\s+(?:-a\s+)?\S",                          # tee file
    r"\bsed\s+-i",                                     # sed -i (in-place)
    r"\bcp\s+",                                        # cp (file copy)
    r"\bmv\s+",                                        # mv (file move/rename)
    r"\btouch\s+",                                     # touch (create/update file)
    r"\binstall\s+-",                                  # install (file install)
    r"\bdd\s+.*\bof=",                                 # dd of=file
    r"python[23]?\s+.*?(?:open\(|\.write\()",         # python file write
    r"node\s+-e\s+.*?(?:writeFile|fs\.)",             # node file write
]


# --- Role-specific .harness write scopes (Superpowers 4-role system) ---

HARNESS_WRITE_SCOPES: dict[str, list[str]] = {
    "implementer": [".harness/progress/", ".harness/artifacts/trace"],
    "code-reviewer": [".harness/artifacts/review-"],
    "qa-browser": [".harness/artifacts/qa-"],
    "rule-curator": [".harness/failures/", ".claude/rules/learned/", ".claude/agent-memory/"],
}


def _check_harness_write_scope(path: str, agent_lower: str) -> str | None:
    allowed = HARNESS_WRITE_SCOPES.get(agent_lower)
    if allowed is None:
        return None  # unknown role → pass through
    normalized = path.replace("\\", "/")
    for prefix in allowed:
        if prefix in normalized:
            return None
    return f"DENIED: {agent_lower} cannot write to this path — outside allowed scope"


def check_role_policy(tool_name: str, tool_input: dict, agent_name: str) -> str | None:
    """Role-based guard for Superpowers' 4-role system.

    Roles: implementer, code-reviewer, qa-browser, rule-curator.
    Empty agent_name (main session) → no role guard (return None).
    Unknown agent_name → pass through (return None).
    """
    if not agent_name:
        return None
    agent_lower = agent_name.lower()

    # Unknown roles pass through gracefully
    if agent_lower not in HARNESS_WRITE_SCOPES:
        return None

    # Bash file-write detection for read-only roles
    if tool_name == "Bash" and agent_lower in ("code-reviewer", "qa-browser"):
        cmd = tool_input.get("command", "")
        for pat in BASH_WRITE_PATTERNS:
            if re.search(pat, cmd, re.IGNORECASE):
                return (
                    f"DENIED: {agent_lower} cannot write files via Bash "
                    f"— use the appropriate tool or delegate"
                )
        return None

    # Only Edit/Write need path-based checks
    if tool_name not in ("Edit", "Write"):
        return None

    np = _normalize(tool_input.get("file_path", ""))

    # Learned rules: rule-curator only
    if ".claude/rules/learned" in np and agent_lower != "rule-curator":
        return "DENIED: only rule-curator can modify .claude/rules/learned/"

    # Contract files: implementer / code-reviewer / qa-browser cannot modify
    if ".harness/contracts/" in np and agent_lower in ("implementer", "code-reviewer", "qa-browser"):
        return f"DENIED: {agent_lower} cannot modify contracts"

    if agent_lower in ("code-reviewer", "qa-browser"):
        if _is_harness_path(np):
            return _check_harness_write_scope(np, agent_lower)
        return f"DENIED: {agent_name} cannot modify product code — report findings only"

    if agent_lower == "implementer":
        if ".claude/rules" in np:
            return "DENIED: implementer cannot modify .claude/rules/ — delegate to rule-curator"
        if _is_harness_path(np):
            return _check_harness_write_scope(np, agent_lower)

    if agent_lower == "rule-curator":
        if _is_harness_path(np):
            return _check_harness_write_scope(np, agent_lower)

    return None


# --- Main entry point ---

def guard(event: dict) -> tuple[int, str]:
    """Evaluate a PreToolUse event. Returns (exit_code, message).

    Accepts both official Claude Code schema (cwd, tool_response) and
    the legacy test schema (project_dir, agent_name) for backward compat.
    """
    tool_name = event.get("tool_name", "")
    tool_input = event.get("tool_input", {})
    cwd = event.get("cwd", event.get("project_dir", ""))
    agent_name = event.get("agent_type", "") or event.get("agent_name", "")
    skill_name = event.get("skill_name", "")

    # Config-based enable/disable
    config = _load_config(cwd)
    if not config.get("guard_enabled", True):
        return 0, ""

    guard_global_only = config.get("guard_global_only", False)

    # Resolve file_path to prevent traversal
    if "file_path" in tool_input and cwd:
        resolved = _resolve_file_path(tool_input["file_path"], cwd)
        tool_input = {**tool_input, "file_path": resolved}

    # Global checks — always run
    for checker in [check_secret_access, check_git_internal, check_destructive_bash]:
        result = checker(tool_name, tool_input)
        if result:
            return 2, result

    # Evidence gate
    evidence_result = check_evidence_gate(tool_name, tool_input, cwd)
    if evidence_result:
        return 2, evidence_result

    # Contract status bypass (block direct "done" writes)
    bypass_result = check_contract_status_bypass(tool_name, tool_input, cwd)
    if bypass_result:
        return 2, bypass_result

    # Push discipline
    is_hook = bool(event.get("session_id") or event.get("hook_event_name"))
    push_result = check_push_discipline(tool_name, tool_input, agent_name, skill_name, is_hook)
    if push_result:
        return 2, push_result

    # Contract required (opt-in)
    contract_result = check_contract_required(tool_name, tool_input, cwd)
    if contract_result:
        return 2, contract_result

    # Role-based checks — skip if guard_global_only
    if not guard_global_only:
        role_result = check_role_policy(tool_name, tool_input, agent_name)
        if role_result:
            return 2, role_result

    return 0, ""


def main() -> None:
    event = read_event()
    exit_code, message = guard(event)

    if exit_code == 2 and message:
        deny(message)
    else:
        allow_silent()


if __name__ == "__main__":
    main()
