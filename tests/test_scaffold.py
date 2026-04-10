"""Tests for scaffold_runtime.py."""

import json
from pathlib import Path

import pytest

from scaffold_runtime import scaffold


def test_scaffold_creates_harness(tmp_target: Path):
    """Scaffolding creates .harness/ directory structure."""
    report = scaffold(tmp_target)

    assert (tmp_target / ".harness").is_dir()
    assert (tmp_target / ".harness" / "profile.json").exists()
    assert (tmp_target / ".harness" / "config.json").exists()
    assert (tmp_target / ".harness" / "templates" / "contract.json").exists()
    assert (tmp_target / ".harness" / "templates" / "goal.md").exists()
    assert len(report["created"]) > 0
    assert len(report["skipped"]) == 0


def test_scaffold_creates_learned_dir(tmp_target: Path):
    """.claude/rules/learned/ directory is created."""
    scaffold(tmp_target)

    learned_dir = tmp_target / ".claude" / "rules" / "learned"
    assert learned_dir.is_dir()
    assert (learned_dir / "README.md").exists()


def test_scaffold_no_overwrite(tmp_target: Path):
    """Existing files are never overwritten."""
    rules_dir = tmp_target / ".claude" / "rules" / "learned"
    rules_dir.mkdir(parents=True)
    original_content = "# My custom learned rules\n"
    (rules_dir / "README.md").write_text(original_content)

    report = scaffold(tmp_target)

    assert ".claude/rules/learned/README.md" in report["skipped"]
    assert (rules_dir / "README.md").read_text() == original_content


def test_scaffold_drift_detection(tmp_target: Path):
    """Changed files are reported as drifted."""
    # First scaffold to create files
    scaffold(tmp_target)

    # Modify a template-managed file
    readme_path = tmp_target / ".claude" / "rules" / "learned" / "README.md"
    readme_path.write_text("# Completely different content\n")

    # Second scaffold detects drift
    report = scaffold(tmp_target)

    assert len(report["drifted"]) > 0
    drifted_files = [d["file"] for d in report["drifted"]]
    assert ".claude/rules/learned/README.md" in drifted_files


def test_scaffold_dry_run(tmp_target: Path):
    """--dry-run reports what would be created without creating files."""
    report = scaffold(tmp_target, dry_run=True)

    assert len(report["created"]) > 0
    assert not (tmp_target / ".claude").exists()
    assert not (tmp_target / ".harness").exists()
