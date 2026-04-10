"""Tests for hook_io.py — stdin reading, deny, and allow_with_context."""

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "hooks" / "lib"


def _run_snippet(code: str, stdin_data: str = "") -> subprocess.CompletedProcess:
    """Run a short Python snippet that imports from hook_io."""
    return subprocess.run(
        [sys.executable, "-c", code],
        input=stdin_data,
        capture_output=True,
        text=True,
        env={**__import__("os").environ, "PYTHONPATH": str(SCRIPTS_DIR)},
        timeout=10,
    )


class TestReadEvent:
    def test_read_event_empty_stdin(self):
        code = textwrap.dedent("""\
            from hook_io import read_event
            import json, sys
            result = read_event()
            print(json.dumps(result))
        """)
        result = _run_snippet(code, stdin_data="")
        assert result.returncode == 0
        assert json.loads(result.stdout.strip()) == {}

    def test_read_event_valid_json(self):
        code = textwrap.dedent("""\
            from hook_io import read_event
            import json
            result = read_event()
            print(json.dumps(result))
        """)
        payload = json.dumps({"tool_name": "Read", "cwd": "/tmp"})
        result = _run_snippet(code, stdin_data=payload)
        assert result.returncode == 0
        parsed = json.loads(result.stdout.strip())
        assert parsed["tool_name"] == "Read"


class TestDeny:
    def test_deny_exit_code(self):
        code = textwrap.dedent("""\
            from hook_io import deny
            deny("not allowed")
        """)
        result = _run_snippet(code)
        assert result.returncode == 2
        assert "not allowed" in result.stderr


class TestAllowWithContext:
    def test_allow_with_context_format(self):
        code = textwrap.dedent("""\
            from hook_io import allow_with_context
            allow_with_context("injected context", "PreToolUse")
        """)
        result = _run_snippet(code)
        assert result.returncode == 0
        output = json.loads(result.stdout.strip())
        assert "hookSpecificOutput" in output
        hso = output["hookSpecificOutput"]
        assert hso["additionalContext"] == "injected context"
        assert hso["hookEventName"] == "PreToolUse"
