"""Tests for pretool_guard.py — allow/deny matrix (Superpowers edition)."""

import json
from pathlib import Path

import pytest

from pretool_guard import guard


def _event(tool_name: str, tool_input: dict, agent_name: str = "", cwd: str = "") -> dict:
    return {"tool_name": tool_name, "tool_input": tool_input, "agent_name": agent_name, "cwd": cwd}


# --- Global policy tests (role-independent) ---

class TestGlobalSecretAccess:
    def test_deny_env_read(self):
        code, msg = guard(_event("Read", {"file_path": "/project/.env"}))
        assert code == 2
        assert "DENIED" in msg

    def test_deny_secrets_dir(self):
        code, msg = guard(_event("Read", {"file_path": "/project/secrets/api.key"}))
        assert code == 2

    def test_deny_pem_file(self):
        code, msg = guard(_event("Write", {"file_path": "/project/cert.pem"}))
        assert code == 2

    def test_deny_credentials(self):
        code, msg = guard(_event("Edit", {"file_path": "/project/credentials.json"}))
        assert code == 2

    def test_allow_normal_file(self):
        code, msg = guard(_event("Read", {"file_path": "/project/src/app.ts"}))
        assert code == 0

    def test_deny_env_in_bash(self):
        code, msg = guard(_event("Bash", {"command": "cat .env"}))
        assert code == 2


class TestGlobalGitInternal:
    def test_deny_git_internal_edit(self):
        code, msg = guard(_event("Edit", {"file_path": "/project/.git/config"}))
        assert code == 2

    def test_deny_git_internal_write(self):
        code, msg = guard(_event("Write", {"file_path": "/project/.git/hooks/pre-commit"}))
        assert code == 2

    def test_allow_gitignore(self):
        code, msg = guard(_event("Edit", {"file_path": "/project/.gitignore"}))
        assert code == 0


class TestGlobalDestructiveBash:
    def test_deny_force_push(self):
        code, msg = guard(_event("Bash", {"command": "git push --force origin main"}))
        assert code == 2

    def test_deny_force_push_short(self):
        code, msg = guard(_event("Bash", {"command": "git push -f origin main"}))
        assert code == 2

    def test_deny_rm_rf(self):
        code, msg = guard(_event("Bash", {"command": "rm -rf /"}))
        assert code == 2

    def test_deny_git_reset_hard(self):
        code, msg = guard(_event("Bash", {"command": "git reset --hard HEAD~3"}))
        assert code == 2

    def test_allow_normal_git(self):
        code, msg = guard(_event("Bash", {"command": "git push origin feature"}))
        assert code == 0

    def test_allow_normal_rm(self):
        code, msg = guard(_event("Bash", {"command": "rm temp.txt"}))
        assert code == 0


# --- Role-based policy tests (Superpowers 4-role system) ---

class TestRoleCodeReviewer:
    def test_deny_code_edit(self):
        code, msg = guard(_event("Edit", {"file_path": "/project/src/app.ts"}, "code-reviewer"))
        assert code == 2
        assert "code-reviewer" in msg

    def test_allow_review_artifact_write(self):
        code, msg = guard(_event("Write", {"file_path": "/project/.harness/artifacts/review-g1-20260409.json"}, "code-reviewer"))
        assert code == 0

    def test_allow_read(self):
        code, msg = guard(_event("Read", {"file_path": "/project/src/app.ts"}, "code-reviewer"))
        assert code == 0

    def test_deny_bash_file_write(self):
        code, msg = guard(_event("Bash", {"command": "echo 'data' > output.txt"}, "code-reviewer"))
        assert code == 2
        assert "code-reviewer" in msg

    def test_deny_bash_sed_inplace(self):
        code, msg = guard(_event("Bash", {"command": "sed -i 's/old/new/' file.txt"}, "code-reviewer"))
        assert code == 2

    def test_allow_bash_readonly(self):
        code, msg = guard(_event("Bash", {"command": "grep -r 'pattern' src/"}, "code-reviewer"))
        assert code == 0


class TestRoleQaBrowser:
    def test_deny_code_write(self):
        code, msg = guard(_event("Write", {"file_path": "/project/src/index.ts"}, "qa-browser"))
        assert code == 2

    def test_allow_qa_artifact_write(self):
        code, msg = guard(_event("Write", {"file_path": "/project/.harness/artifacts/qa-g1-20260409.json"}, "qa-browser"))
        assert code == 0

    def test_deny_bash_file_write(self):
        code, msg = guard(_event("Bash", {"command": "printf 'data' > report.txt"}, "qa-browser"))
        assert code == 2


class TestRoleImplementer:
    def test_deny_rules_edit(self):
        code, msg = guard(_event("Edit", {"file_path": "/project/.claude/rules/learned/new-rule.md"}, "implementer"))
        assert code == 2
        assert "rule-curator" in msg

    def test_deny_core_rules_edit(self):
        code, msg = guard(_event("Edit", {"file_path": "/project/.claude/rules/core.md"}, "implementer"))
        assert code == 2
        assert "implementer" in msg

    def test_allow_code_edit(self):
        code, msg = guard(_event("Edit", {"file_path": "/project/src/app.ts"}, "implementer"))
        assert code == 0

    def test_deny_contract_modify(self):
        code, msg = guard(_event("Edit", {"file_path": "/project/.harness/contracts/goal-1.json"}, "implementer"))
        assert code == 2
        assert "implementer" in msg


class TestRuleCurator:
    def test_allow_learned_rules(self):
        code, msg = guard(_event("Write", {"file_path": "/project/.claude/rules/learned/new.md"}, "rule-curator"))
        assert code == 0

    def test_allow_agent_memory(self):
        code, msg = guard(_event("Write", {"file_path": "/project/.claude/agent-memory/session.json"}, "rule-curator"))
        assert code == 0

    def test_allow_failures(self):
        code, msg = guard(_event("Write", {"file_path": "/project/.harness/failures/retro-001.json"}, "rule-curator"))
        assert code == 0


class TestUnknownAgent:
    """Unknown agent names should only hit global policies."""
    def test_allow_normal_edit(self):
        code, msg = guard(_event("Edit", {"file_path": "/project/src/app.ts"}, "unknown-agent"))
        assert code == 0

    def test_deny_secrets(self):
        code, msg = guard(_event("Read", {"file_path": "/project/.env"}, "unknown-agent"))
        assert code == 2


class TestNoAgent:
    """No agent name means only global policies apply."""
    def test_allow_all_normal(self):
        code, msg = guard(_event("Edit", {"file_path": "/project/src/app.ts"}))
        assert code == 0


# --- Config-based guard toggle ---

class TestConfigGuardEnabled:
    def test_guard_disabled_allows_secrets(self, tmp_path: Path):
        """When guard_enabled=false, even secret access is allowed."""
        harness = tmp_path / ".harness"
        harness.mkdir()
        (harness / "config.json").write_text(json.dumps({"guard_enabled": False}))
        code, msg = guard(_event("Read", {"file_path": "/project/.env"}, cwd=str(tmp_path)))
        assert code == 0

    def test_guard_enabled_denies_secrets(self, tmp_path: Path):
        harness = tmp_path / ".harness"
        harness.mkdir()
        (harness / "config.json").write_text(json.dumps({"guard_enabled": True}))
        code, msg = guard(_event("Read", {"file_path": "/project/.env"}, cwd=str(tmp_path)))
        assert code == 2


class TestConfigGuardGlobalOnly:
    def test_global_only_skips_role_checks(self, tmp_path: Path):
        """When guard_global_only=true, role policies are not enforced."""
        harness = tmp_path / ".harness"
        harness.mkdir()
        (harness / "config.json").write_text(json.dumps({"guard_global_only": True}))
        # code-reviewer editing product code would normally be denied
        code, msg = guard(_event(
            "Edit", {"file_path": "/project/src/app.ts"}, "code-reviewer", cwd=str(tmp_path),
        ))
        assert code == 0

    def test_global_only_still_blocks_secrets(self, tmp_path: Path):
        """guard_global_only skips role checks but global checks still run."""
        harness = tmp_path / ".harness"
        harness.mkdir()
        (harness / "config.json").write_text(json.dumps({"guard_global_only": True}))
        code, msg = guard(_event("Read", {"file_path": "/project/.env"}, cwd=str(tmp_path)))
        assert code == 2


# --- Contract required (opt-in) ---

class TestContractRequired:
    def test_no_config_allows_edit(self, tmp_path: Path):
        """Without contract_required in config, edits are allowed."""
        code, msg = guard(_event("Edit", {"file_path": "/project/src/app.ts"}, cwd=str(tmp_path)))
        assert code == 0

    def test_contract_required_with_active_contract(self, tmp_path: Path):
        """Active contract exists — edits allowed."""
        harness = tmp_path / ".harness"
        harness.mkdir()
        (harness / "config.json").write_text(json.dumps({"contract_required": True}))
        contracts = harness / "contracts"
        contracts.mkdir()
        (contracts / "goal-1.json").write_text(json.dumps({"status": "active"}))
        code, msg = guard(_event("Edit", {"file_path": str(tmp_path / "src" / "app.ts")}, cwd=str(tmp_path)))
        assert code == 0

    def test_contract_required_no_active_contract(self, tmp_path: Path):
        """contract_required=true but no active contract — edits denied."""
        harness = tmp_path / ".harness"
        harness.mkdir()
        (harness / "config.json").write_text(json.dumps({"contract_required": True}))
        contracts = harness / "contracts"
        contracts.mkdir()
        (contracts / "goal-1.json").write_text(json.dumps({"status": "done"}))
        code, msg = guard(_event("Edit", {"file_path": str(tmp_path / "src" / "app.ts")}, cwd=str(tmp_path)))
        assert code == 2
        assert "no active contract" in msg

    def test_contract_required_harness_path_exempt(self, tmp_path: Path):
        """Edits to .harness/ paths are exempt from contract requirement."""
        harness = tmp_path / ".harness"
        harness.mkdir()
        (harness / "config.json").write_text(json.dumps({"contract_required": True}))
        contracts = harness / "contracts"
        contracts.mkdir()
        (contracts / "goal-1.json").write_text(json.dumps({"status": "done"}))
        code, msg = guard(_event("Edit", {"file_path": str(harness / "progress" / "notes.json")}, cwd=str(tmp_path)))
        assert code == 0


# --- Bash file-write detection for read-only roles ---

class TestBashWriteDetection:
    @pytest.mark.parametrize("cmd", [
        "echo 'hello' > file.txt",
        "printf 'data' > out.log",
        "cat input.txt > copy.txt",
        "tee output.log",
        "sed -i 's/a/b/' config.yml",
        "cp src.txt dst.txt",
        "mv old.txt new.txt",
        "touch newfile.txt",
    ])
    def test_reviewer_bash_writes_denied(self, cmd: str):
        code, msg = guard(_event("Bash", {"command": cmd}, "code-reviewer"))
        assert code == 2, f"Expected deny for: {cmd}"

    @pytest.mark.parametrize("cmd", [
        "grep -r 'pattern' src/",
        "git log --oneline",
        "cat README.md",
        "ls -la",
        "python -c 'print(1)'",
    ])
    def test_reviewer_readonly_bash_allowed(self, cmd: str):
        code, msg = guard(_event("Bash", {"command": cmd}, "code-reviewer"))
        assert code == 0, f"Expected allow for: {cmd}"
