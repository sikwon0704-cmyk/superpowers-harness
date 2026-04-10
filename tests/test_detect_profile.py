"""Tests for detect_project_profile.py."""

from pathlib import Path

from detect_project_profile import detect


def test_empty_target(empty_target: Path):
    result = detect(empty_target)
    assert result["profile"] == "unknown"
    assert result["needs_redetect"] is True
    assert result["commands"]["test"] == ""


def test_js_app(js_app: Path):
    result = detect(js_app)
    assert result["profile"] == "js"
    assert result["language"] == "typescript"
    assert result["commands"]["test"] == "jest"
    assert result["commands"]["build"] == "tsc"
    assert result["commands"]["lint"] == "eslint src/"
    assert result["needs_redetect"] is False


def test_python_api(python_api: Path):
    result = detect(python_api)
    assert result["profile"] == "python"
    assert result["language"] == "python"
    assert result["commands"]["test"] == "python -m pytest"
    assert result["commands"]["lint"] == "ruff check ."
    assert result["needs_redetect"] is False


def test_go_cli(go_cli: Path):
    result = detect(go_cli)
    assert result["profile"] == "go"
    assert result["language"] == "go"
    assert result["commands"]["test"] == "go test ./..."
    assert result["commands"]["build"] == "go build ./..."
    assert result["needs_redetect"] is False
