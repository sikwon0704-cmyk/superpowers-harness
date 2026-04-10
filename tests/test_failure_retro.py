"""Tests for write_failure_retro.py — failure retro file creation."""

import re
from pathlib import Path

import pytest

from write_failure_retro import write_retro


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / ".harness" / "failures").mkdir(parents=True)
    return tmp_path


def test_write_retro(project: Path):
    """write_retro creates a markdown file in .harness/failures/."""
    data = {
        "symptom": "API returns 500",
        "root_cause": "null pointer in handler",
        "remediation": "add null check",
    }
    path = write_retro(project, "goal-1", data)

    assert path.exists()
    assert path.parent == project / ".harness" / "failures"
    assert path.suffix == ".md"
    assert path.name.startswith("goal-1-")

    content = path.read_text(encoding="utf-8")
    assert "API returns 500" in content
    assert "null pointer in handler" in content


def test_retro_template_fields(project: Path):
    """All required sections are present in the retro file."""
    data = {
        "symptom": "test failure",
        "root_cause": "missing mock",
        "why_missed": "no integration test",
        "remediation": "add mock setup",
        "candidate_rule": "Always mock external deps",
    }
    path = write_retro(project, "goal-2", data)
    content = path.read_text(encoding="utf-8")

    required_sections = [
        "## Symptom",
        "## Root Cause",
        "## Why Previous Checks Missed It",
        "## Remediation",
        "## Candidate Rule",
        "## Promoted?",
        "## Next Replan",
    ]
    for section in required_sections:
        assert section in content, f"Missing section: {section}"

    # Promoted? defaults to pending
    assert "pending" in content


def test_retro_timestamp_format(project: Path):
    """Filename contains a valid YYYYMMDD-HHMMSS timestamp."""
    path = write_retro(project, "goal-3", {"symptom": "ts test"})

    # Filename format: goal-3-YYYYMMDD-HHMMSS.md
    stem = path.stem  # e.g. "goal-3-20260410-143022"
    match = re.search(r"(\d{8}-\d{6})$", stem)
    assert match, f"Timestamp not found in filename: {path.name}"

    ts = match.group(1)
    # Validate it parses as a real datetime
    from datetime import datetime
    parsed = datetime.strptime(ts, "%Y%m%d-%H%M%S")
    assert parsed.year >= 2024
