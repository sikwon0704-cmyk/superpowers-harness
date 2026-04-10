"""Tests for hooks.json — schema validity and script existence."""

import json
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
HOOKS_JSON = PROJECT_ROOT / "hooks" / "hooks.json"


@pytest.fixture
def hooks_data() -> dict:
    return json.loads(HOOKS_JSON.read_text(encoding="utf-8"))


class TestHooksJsonValid:
    def test_hooks_json_valid(self, hooks_data: dict):
        """hooks.json is valid JSON with a top-level 'hooks' dict."""
        assert "hooks" in hooks_data
        assert isinstance(hooks_data["hooks"], dict)
        # Must define at least SessionStart and PreToolUse
        assert "SessionStart" in hooks_data["hooks"]
        assert "PreToolUse" in hooks_data["hooks"]


class TestAllScriptsExist:
    def test_all_scripts_exist(self, hooks_data: dict):
        """Every script referenced via 'python ...hooks/lib/X.py' must exist."""
        missing = []
        for event_name, entries in hooks_data["hooks"].items():
            for entry in entries:
                for hook in entry.get("hooks", []):
                    cmd = hook.get("command", "")
                    # Extract python script paths like hooks/lib/foo.py
                    if "hooks/lib/" in cmd:
                        # Extract the script filename after hooks/lib/
                        parts = cmd.split("hooks/lib/")
                        if len(parts) > 1:
                            script_name = parts[1].split('"')[0].split("'")[0].split()[0]
                            script_path = PROJECT_ROOT / "hooks" / "lib" / script_name
                            if not script_path.exists():
                                missing.append(f"{event_name}: {script_name}")
        assert missing == [], f"Missing scripts: {missing}"


class TestSessionStartChains:
    def test_session_start_chains_both(self, hooks_data: dict):
        """SessionStart must chain both session-start hook AND restore_runtime_context."""
        session_hooks = hooks_data["hooks"]["SessionStart"]
        all_commands = []
        for entry in session_hooks:
            for hook in entry.get("hooks", []):
                all_commands.append(hook.get("command", ""))

        combined = " ".join(all_commands)
        assert "session-start" in combined, "SessionStart must include session-start hook"
        assert "restore_runtime_context" in combined, "SessionStart must include restore_runtime_context"
