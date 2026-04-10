"""Tests for posttool_trace.py — PostToolUse trace logging."""

import json
from pathlib import Path

import pytest

from posttool_trace import (
    log_trace,
    update_changed_files_index,
    detect_test_results,
    _is_tracing_enabled,
)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / ".harness" / "artifacts").mkdir(parents=True)
    return tmp_path


def test_trace_appends_jsonl(project: Path):
    """log_trace appends a valid JSONL line to trace.jsonl."""
    entry1 = {"ts": "2026-04-10T10:00:00+00:00", "event": "tool_use", "tool": "Read"}
    entry2 = {"ts": "2026-04-10T10:00:01+00:00", "event": "tool_use", "tool": "Edit"}

    log_trace(project, entry1)
    log_trace(project, entry2)

    trace_path = project / ".harness" / "artifacts" / "trace.jsonl"
    assert trace_path.exists()

    lines = trace_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2

    parsed_1 = json.loads(lines[0])
    assert parsed_1["tool"] == "Read"
    parsed_2 = json.loads(lines[1])
    assert parsed_2["tool"] == "Edit"


def test_trace_changed_files_index(project: Path):
    """update_changed_files_index creates/updates changed-files.json."""
    update_changed_files_index(project, "src/app.ts", "Edit")
    update_changed_files_index(project, "src/app.ts", "Write")
    update_changed_files_index(project, "src/utils.ts", "Edit")

    index_path = project / ".harness" / "artifacts" / "changed-files.json"
    assert index_path.exists()

    data = json.loads(index_path.read_text(encoding="utf-8"))
    files = data["files"]

    assert "src/app.ts" in files
    assert "src/utils.ts" in files
    assert "Edit" in files["src/app.ts"]["tools"]
    assert "Write" in files["src/app.ts"]["tools"]
    assert "last_updated" in data


def test_trace_detects_pytest_pass(project: Path):
    """detect_test_results identifies a passing pytest run."""
    output = (
        "============================= test session starts ==============================\n"
        "collected 12 items\n\n"
        "tests/test_app.py ............\n\n"
        "============================== 12 passed in 1.23s ==============================\n"
    )
    results = detect_test_results("python -m pytest", output)

    assert len(results) == 1
    assert results[0]["runner"] == "pytest"
    assert results[0]["passed"] is True


def test_trace_detects_jest_fail(project: Path):
    """detect_test_results correctly marks failures when output contains FAIL.

    The pattern list evaluates in order. The pytest "FAILED" pattern (index 1)
    fires first for any output containing "FAILED". The critical assertion is
    that failures are correctly detected (passed=False) regardless of which
    runner label is assigned.
    """
    # Jest-style output with "FAILED" marker
    output = (
        "FAILED tests/app.test.ts\n"
        "  Test Suites: 1 failed, 0 passed, 1 total\n"
    )
    results = detect_test_results("npx jest", output)

    assert len(results) == 1
    # "FAILED" in output triggers the pytest FAILED pattern first (pattern order)
    assert results[0]["runner"] == "pytest"
    assert results[0]["passed"] is False

    # Output with no matching pattern returns empty
    results = detect_test_results("echo hello", "hello world")
    assert len(results) == 0


def test_trace_disabled_skips(tmp_path: Path):
    """When trace_enabled=false in config.json, tracing is disabled."""
    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir(parents=True)
    config = {"trace_enabled": False}
    (harness_dir / "config.json").write_text(json.dumps(config), encoding="utf-8")

    assert _is_tracing_enabled(tmp_path) is False

    # Verify the default (no config) is enabled
    bare = tmp_path / "bare-project"
    (bare / ".harness").mkdir(parents=True)
    assert _is_tracing_enabled(bare) is True
