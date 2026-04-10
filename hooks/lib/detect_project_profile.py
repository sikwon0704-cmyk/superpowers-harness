"""Detect project profile from repository root.

Scans for manifest files (package.json, pyproject.toml, go.mod, etc.)
and extracts language, framework, and build/test/lint/typecheck commands.

Returns a JSON profile to stdout. Falls back to profile="unknown" when
no manifest is found.

Usage:
    python detect_project_profile.py <project_dir>
"""

import json
import sys
from pathlib import Path


def detect_js(project_dir: Path) -> dict | None:
    """Detect JS/TS project from package.json."""
    pkg = project_dir / "package.json"
    if not pkg.exists():
        return None

    try:
        data = json.loads(pkg.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    scripts = data.get("scripts", {})
    deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}

    framework = "unknown"
    if "next" in deps:
        framework = "next"
    elif "react" in deps:
        framework = "react"
    elif "vue" in deps:
        framework = "vue"
    elif "express" in deps:
        framework = "express"
    elif "fastify" in deps:
        framework = "fastify"

    language = "typescript" if ("typescript" in deps or (project_dir / "tsconfig.json").exists()) else "javascript"

    return {
        "profile": "js",
        "language": language,
        "framework": framework,
        "commands": {
            "build": scripts.get("build", ""),
            "test": scripts.get("test", ""),
            "lint": scripts.get("lint", ""),
            "typecheck": scripts.get("typecheck", ""),
        },
        "needs_redetect": False,
        "assumptions": [],
    }


def detect_python(project_dir: Path) -> dict | None:
    """Detect Python project from pyproject.toml or requirements*.txt."""
    pyproject = project_dir / "pyproject.toml"
    has_requirements = any(project_dir.glob("requirements*.txt"))

    if not pyproject.exists() and not has_requirements:
        return None

    commands = {"build": "", "test": "", "lint": "", "typecheck": ""}
    framework = "unknown"
    assumptions = []

    if pyproject.exists():
        text = pyproject.read_text(encoding="utf-8")

        # Detect test runner
        if "pytest" in text:
            commands["test"] = "python -m pytest"
        elif "unittest" in text:
            commands["test"] = "python -m unittest discover"

        # Detect linter
        if "ruff" in text:
            commands["lint"] = "ruff check ."
        elif "flake8" in text:
            commands["lint"] = "flake8 ."
        elif "pylint" in text:
            commands["lint"] = "pylint src/"

        # Detect type checker
        if "mypy" in text:
            commands["typecheck"] = "mypy ."
        elif "pyright" in text:
            commands["typecheck"] = "pyright"

        # Detect framework
        if "django" in text:
            framework = "django"
        elif "fastapi" in text:
            framework = "fastapi"
        elif "flask" in text:
            framework = "flask"
    else:
        assumptions.append("no pyproject.toml found, detected via requirements*.txt only")
        commands["test"] = "python -m pytest"

    return {
        "profile": "python",
        "language": "python",
        "framework": framework,
        "commands": commands,
        "needs_redetect": False,
        "assumptions": assumptions,
    }


def detect_go(project_dir: Path) -> dict | None:
    """Detect Go project from go.mod."""
    gomod = project_dir / "go.mod"
    if not gomod.exists():
        return None

    text = gomod.read_text(encoding="utf-8")
    framework = "unknown"
    if "gin-gonic" in text:
        framework = "gin"
    elif "gorilla/mux" in text:
        framework = "gorilla"
    elif "echo" in text:
        framework = "echo"

    return {
        "profile": "go",
        "language": "go",
        "framework": framework,
        "commands": {
            "build": "go build ./...",
            "test": "go test ./...",
            "lint": "golangci-lint run",
            "typecheck": "go vet ./...",
        },
        "needs_redetect": False,
        "assumptions": [],
    }


def detect_rust(project_dir: Path) -> dict | None:
    """Detect Rust project from Cargo.toml."""
    cargo = project_dir / "Cargo.toml"
    if not cargo.exists():
        return None

    return {
        "profile": "rust",
        "language": "rust",
        "framework": "unknown",
        "commands": {
            "build": "cargo build",
            "test": "cargo test",
            "lint": "cargo clippy",
            "typecheck": "cargo check",
        },
        "needs_redetect": False,
        "assumptions": [],
    }


def _extract_makefile_targets(makefile: Path) -> dict[str, str]:
    """Extract build/test/lint targets from a Makefile."""
    commands: dict[str, str] = {}
    try:
        text = makefile.read_text(encoding="utf-8")
    except OSError:
        return commands

    import re
    target_map = {
        "build": re.compile(r"^(build)\s*:", re.MULTILINE),
        "test": re.compile(r"^(test|check)\s*:", re.MULTILINE),
        "lint": re.compile(r"^(lint|format)\s*:", re.MULTILINE),
        "typecheck": re.compile(r"^(typecheck|type-check|types)\s*:", re.MULTILINE),
    }
    for key, pattern in target_map.items():
        if pattern.search(text):
            target_name = pattern.search(text).group(1)
            commands[key] = f"make {target_name}"
    return commands


def _extract_ci_commands(project_dir: Path) -> dict[str, str]:
    """Extract run commands from GitHub Actions workflow files."""
    import re
    commands: dict[str, str] = {}
    ci_files = list(project_dir.glob(".github/workflows/*.yml")) + \
               list(project_dir.glob(".github/workflows/*.yaml"))

    keyword_map = {
        "build": ["build", "compile"],
        "test": ["test", "pytest", "jest", "go test", "cargo test"],
        "lint": ["lint", "eslint", "ruff", "flake8", "golangci-lint", "clippy"],
        "typecheck": ["typecheck", "tsc", "mypy", "pyright", "go vet"],
    }

    for ci_file in ci_files[:3]:  # cap at 3 files
        try:
            text = ci_file.read_text(encoding="utf-8")
        except OSError:
            continue
        # Find 'run:' lines
        for match in re.finditer(r"run:\s*(.+)", text):
            cmd = match.group(1).strip().strip("|").strip()
            if not cmd or cmd.startswith("#"):
                continue
            for key, keywords in keyword_map.items():
                if key not in commands:
                    for kw in keywords:
                        if kw in cmd.lower():
                            commands[key] = cmd
                            break
    return commands


def _extract_readme_commands(project_dir: Path) -> dict[str, str]:
    """Extract commands from README code blocks (```bash or ```sh sections)."""
    import re
    commands: dict[str, str] = {}

    readme = None
    for name in ("README.md", "README", "README.rst", "README.txt"):
        candidate = project_dir / name
        if candidate.exists():
            readme = candidate
            break
    if not readme:
        return commands

    try:
        text = readme.read_text(encoding="utf-8")
    except OSError:
        return commands

    keyword_map = {
        "build": ["build", "compile"],
        "test": ["test", "pytest", "jest", "go test", "cargo test"],
        "lint": ["lint", "eslint", "ruff", "flake8", "clippy"],
        "typecheck": ["typecheck", "tsc", "mypy", "pyright", "go vet"],
    }

    # Find code blocks
    for block in re.finditer(r"```(?:bash|sh|shell|console)?\s*\n(.*?)```", text, re.DOTALL):
        block_text = block.group(1)
        for line in block_text.strip().split("\n"):
            cmd = line.strip().lstrip("$ ").strip()
            if not cmd or cmd.startswith("#"):
                continue
            for key, keywords in keyword_map.items():
                if key not in commands:
                    for kw in keywords:
                        if kw in cmd.lower():
                            commands[key] = cmd
                            break
    return commands


def _detect_workspace(project_dir: Path) -> list[str]:
    """Detect monorepo/workspace configuration files."""
    hints: list[str] = []

    # pnpm workspace
    if (project_dir / "pnpm-workspace.yaml").exists():
        hints.append("pnpm workspace detected — monorepo")
    # npm/yarn workspaces in package.json
    pkg = project_dir / "package.json"
    if pkg.exists():
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
            if "workspaces" in data:
                hints.append("npm/yarn workspaces detected — monorepo")
        except (json.JSONDecodeError, OSError):
            pass
    # Cargo workspace
    cargo = project_dir / "Cargo.toml"
    if cargo.exists():
        try:
            text = cargo.read_text(encoding="utf-8")
            if "[workspace]" in text:
                hints.append("Cargo workspace detected — monorepo")
        except OSError:
            pass
    # Go workspace
    if (project_dir / "go.work").exists():
        hints.append("Go workspace detected — monorepo")
    # Nx / Turborepo
    if (project_dir / "nx.json").exists():
        hints.append("Nx workspace detected — monorepo")
    if (project_dir / "turbo.json").exists():
        hints.append("Turborepo detected — monorepo")
    # Lerna
    if (project_dir / "lerna.json").exists():
        hints.append("Lerna workspace detected — monorepo")

    return hints


def detect_unknown(project_dir: Path) -> dict:
    """Fallback profile when no manifest is found.

    Attempts to extract commands from Makefile, CI workflows, and README.
    """
    assumptions = ["no recognized manifest file found"]
    commands = {"build": "", "test": "", "lint": "", "typecheck": ""}

    # Try Makefile
    makefile = project_dir / "Makefile"
    if makefile.exists():
        make_cmds = _extract_makefile_targets(makefile)
        if make_cmds:
            assumptions.append(f"Makefile targets found: {', '.join(make_cmds.keys())}")
            for k, v in make_cmds.items():
                if not commands[k]:
                    commands[k] = v

    # Try CI workflows
    ci_cmds = _extract_ci_commands(project_dir)
    if ci_cmds:
        assumptions.append(f"CI commands extracted: {', '.join(ci_cmds.keys())}")
        for k, v in ci_cmds.items():
            if not commands[k]:
                commands[k] = v

    # Try README code blocks for commands
    readme_cmds = _extract_readme_commands(project_dir)
    if readme_cmds:
        assumptions.append(f"README commands extracted: {', '.join(readme_cmds.keys())}")
        for k, v in readme_cmds.items():
            if not commands[k]:
                commands[k] = v

    # Detect workspace files (monorepo hints)
    workspace_hints = _detect_workspace(project_dir)
    if workspace_hints:
        assumptions.extend(workspace_hints)

    # Note Dockerfile presence
    if (project_dir / "Dockerfile").exists():
        assumptions.append("Dockerfile present — containerized project")

    has_any = any(commands.values())
    if not has_any:
        if any(project_dir.glob(".github/workflows/*.yml")) or any(project_dir.glob(".github/workflows/*.yaml")):
            assumptions.append("GitHub Actions workflows present but no run commands extracted")

    return {
        "profile": "unknown",
        "language": "unknown",
        "framework": "unknown",
        "commands": commands,
        "needs_redetect": not has_any,
        "assumptions": assumptions,
    }


# Detection order: most specific first
DETECTORS = [
    detect_js,
    detect_python,
    detect_go,
    detect_rust,
]


def detect(project_dir: str | Path) -> dict:
    """Run all detectors and return the first match, or unknown fallback."""
    project_dir = Path(project_dir)
    if not project_dir.is_dir():
        return detect_unknown(project_dir)

    for detector in DETECTORS:
        result = detector(project_dir)
        if result is not None:
            return result

    return detect_unknown(project_dir)


def main() -> None:
    if len(sys.argv) < 2:
        print(json.dumps({"error": "usage: detect_project_profile.py <project_dir>"}))
        sys.exit(1)

    project_dir = Path(sys.argv[1])
    profile = detect(project_dir)
    print(json.dumps(profile, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
