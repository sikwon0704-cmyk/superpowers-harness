"""Shared test fixtures for superpowers harness tests."""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = PROJECT_ROOT / "tests" / "fixtures"
SCRIPTS_DIR = PROJECT_ROOT / "hooks" / "lib"
TEMPLATES_DIR = PROJECT_ROOT / "hooks" / "templates"

sys.path.insert(0, str(SCRIPTS_DIR))


@pytest.fixture
def project_root() -> Path:
    return PROJECT_ROOT


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def scripts_dir() -> Path:
    return SCRIPTS_DIR


@pytest.fixture
def templates_dir() -> Path:
    return TEMPLATES_DIR


@pytest.fixture
def empty_target(fixtures_dir: Path) -> Path:
    return fixtures_dir / "empty-target"


@pytest.fixture
def js_app(fixtures_dir: Path) -> Path:
    return fixtures_dir / "js-app"


@pytest.fixture
def python_api(fixtures_dir: Path) -> Path:
    return fixtures_dir / "python-api"


@pytest.fixture
def go_cli(fixtures_dir: Path) -> Path:
    return fixtures_dir / "go-cli"


@pytest.fixture
def tmp_target(tmp_path: Path) -> Path:
    """A fresh temporary directory to use as a scaffold target."""
    target = tmp_path / "target"
    target.mkdir()
    return target


@pytest.fixture
def tmp_target_with_existing_claude(tmp_path: Path) -> Path:
    """Temporary target that already has a .claude/ directory."""
    target = tmp_path / "target"
    target.mkdir()
    claude_dir = target / ".claude"
    claude_dir.mkdir()
    (claude_dir / "CLAUDE.md").write_text("# Existing CLAUDE.md\nDo not overwrite.\n")
    return target
