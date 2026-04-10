"""Scaffold .claude/ and .harness/ into a target project directory.

Uses detect_project_profile to determine the project type, then copies
templates with variable substitution.

Safe merge strategy:
  - New files are created with variable substitution.
  - Existing files are never overwritten.
  - CLAUDE.md gets special handling: if the harness section marker is
    absent from an existing file, the template content is appended
    (safe merge) rather than silently skipped.
  - Drift detection reports divergences for all other text files.

Usage:
    python scaffold_runtime.py <project_dir> [--dry-run]
"""

import difflib
import json
import shutil
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = SCRIPT_DIR.parent / "templates"
DETECT_SCRIPT = SCRIPT_DIR / "detect_project_profile.py"

DEFAULT_CONFIG = {
    "guard_enabled": True,
    "guard_global_only": False,
    "contract_required": False,
    "trace_enabled": True,
}


def load_profile(project_dir: Path) -> dict:
    """Run detection or load existing profile."""
    existing = project_dir / ".harness" / "profile.json"
    if existing.exists():
        try:
            return json.loads(existing.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    import importlib.util
    spec = importlib.util.spec_from_file_location("detect_project_profile", DETECT_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.detect(project_dir)


def substitute(content: str, profile: dict) -> str:
    """Replace {{var}} placeholders with profile values."""
    commands = profile.get("commands", {})
    replacements = {
        "profile": profile.get("profile", "unknown"),
        "language": profile.get("language", "unknown"),
        "framework": profile.get("framework", "unknown"),
        "commands.build": commands.get("build", ""),
        "commands.test": commands.get("test", ""),
        "commands.lint": commands.get("lint", ""),
        "commands.typecheck": commands.get("typecheck", ""),
    }
    result = content
    for key, value in replacements.items():
        result = result.replace("{{" + key + "}}", value)
    return result


def _compute_drift(template_content: str, installed_content: str, rel_path: str) -> dict | None:
    """Compare template vs installed content.  Return a drift dict or None."""
    if template_content == installed_content:
        return None
    diff_lines = list(difflib.unified_diff(
        template_content.splitlines(keepends=True),
        installed_content.splitlines(keepends=True),
        fromfile=f"template/{rel_path}",
        tofile=f"installed/{rel_path}",
        n=2,
    ))
    if not diff_lines:
        return None
    return {
        "file": rel_path,
        "diff_lines": len(diff_lines),
        "diff_preview": "".join(diff_lines[:30]),
    }


HARNESS_MARKER = "# Project Harness"


def _safe_merge_claude_md(existing: str, template: str) -> str | None:
    """Append harness section to existing CLAUDE.md if marker is absent.

    Returns the merged content, or None if no merge is needed (marker
    already present).
    """
    if HARNESS_MARKER in existing:
        return None  # already merged
    separator = "\n\n" if existing.rstrip() else ""
    return existing.rstrip() + separator + template


def scaffold(project_dir: Path, dry_run: bool = False) -> dict:
    """Copy templates into project_dir, substituting profile variables.

    Returns a report dict with 'created', 'skipped', 'drifted', and 'profile'.
    """
    project_dir = Path(project_dir)
    profile = load_profile(project_dir)

    report = {
        "profile": profile,
        "created": [],
        "skipped": [],
        "merged": [],
        "drifted": [],
    }

    for section, prefix in [("claude", ".claude"), ("harness", ".harness")]:
        src_root = TEMPLATES_DIR / section
        dst_root = project_dir / prefix

        if not src_root.exists():
            continue

        for src_file in sorted(src_root.rglob("*")):
            if src_file.is_dir():
                continue

            rel = src_file.relative_to(src_root)
            dst_file = dst_root / rel
            rel_posix = dst_file.relative_to(project_dir).as_posix()

            if dst_file.exists():
                # Safe merge for CLAUDE.md: append harness section if absent
                if rel.as_posix() == "CLAUDE.md" and src_file.suffix == ".md":
                    template_content = substitute(
                        src_file.read_text(encoding="utf-8"), profile)
                    try:
                        installed_content = dst_file.read_text(encoding="utf-8")
                    except OSError:
                        installed_content = ""
                    merged = _safe_merge_claude_md(installed_content, template_content)
                    if merged is not None:
                        if not dry_run:
                            dst_file.write_text(merged, encoding="utf-8")
                        report.setdefault("merged", []).append(rel_posix)
                    else:
                        report["skipped"].append(rel_posix)
                        drift = _compute_drift(template_content, installed_content, rel_posix)
                        if drift:
                            report["drifted"].append(drift)
                    continue

                report["skipped"].append(rel_posix)

                # Drift detection for text files
                if src_file.suffix in (".md", ".json", ".txt", ".yaml", ".yml"):
                    template_content = substitute(
                        src_file.read_text(encoding="utf-8"), profile)
                    try:
                        installed_content = dst_file.read_text(encoding="utf-8")
                    except OSError:
                        installed_content = ""
                    drift = _compute_drift(template_content, installed_content, rel_posix)
                    if drift:
                        report["drifted"].append(drift)
                continue

            if dry_run:
                report["created"].append(rel_posix)
                continue

            dst_file.parent.mkdir(parents=True, exist_ok=True)

            if src_file.suffix in (".md", ".json", ".txt", ".yaml", ".yml"):
                content = src_file.read_text(encoding="utf-8")
                content = substitute(content, profile)
                dst_file.write_text(content, encoding="utf-8")
            else:
                shutil.copy2(src_file, dst_file)

            report["created"].append(rel_posix)

    # Write profile.json
    profile_dst = project_dir / ".harness" / "profile.json"
    if not profile_dst.exists() and not dry_run:
        profile_dst.parent.mkdir(parents=True, exist_ok=True)
        profile_dst.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")
        report["created"].append(".harness/profile.json")
    elif profile_dst.exists():
        report["skipped"].append(".harness/profile.json")

    # Write config.json with defaults
    config_dst = project_dir / ".harness" / "config.json"
    if not config_dst.exists() and not dry_run:
        config_dst.parent.mkdir(parents=True, exist_ok=True)
        config_dst.write_text(json.dumps(DEFAULT_CONFIG, indent=2, ensure_ascii=False), encoding="utf-8")
        report["created"].append(".harness/config.json")
    elif config_dst.exists():
        report["skipped"].append(".harness/config.json")

    return report


def main() -> None:
    if len(sys.argv) < 2:
        print(json.dumps({"error": "usage: scaffold_runtime.py <project_dir> [--dry-run]"}))
        sys.exit(1)

    project_dir = Path(sys.argv[1])
    dry_run = "--dry-run" in sys.argv

    report = scaffold(project_dir, dry_run=dry_run)
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
