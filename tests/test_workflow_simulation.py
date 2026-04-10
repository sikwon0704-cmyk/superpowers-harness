"""End-to-end workflow simulation.

Simulates the exact sequence of hook calls that Claude Code makes
during a real development session with harness enabled.
"""

import json
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "hooks" / "lib"

sys.path.insert(0, str(SCRIPTS_DIR))


def run_script(script_name: str, project_dir: str, stdin_data: str = "", extra_args: list = None):
    """Run a hook script the way Claude Code would invoke it."""
    cmd = [sys.executable, str(SCRIPTS_DIR / script_name)]
    if extra_args:
        cmd.extend(extra_args)
    else:
        cmd.append(project_dir)
    env = {**__import__("os").environ, "PYTHONIOENCODING": "utf-8"}
    result = subprocess.run(
        cmd, input=stdin_data, capture_output=True, text=True, timeout=30,
        encoding="utf-8", env=env,
    )
    return result


def run_guard(event_json: dict):
    """Run pretool_guard.py with a hook event on stdin."""
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "pretool_guard.py")],
        input=json.dumps(event_json),
        capture_output=True, text=True, timeout=10
    )
    return result


def run_trace(event_json: dict, project_dir: str):
    """Run posttool_trace.py with a PostToolUse event."""
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "posttool_trace.py"), project_dir],
        input=json.dumps(event_json),
        capture_output=True, text=True, timeout=10
    )
    return result


class TestFullWorkflowSimulation:
    """Simulates a complete development session with harness."""

    @pytest.fixture(autouse=True)
    def setup_project(self, tmp_path):
        """Create a fake Python project to work with."""
        self.project_dir = tmp_path / "my-project"
        self.project_dir.mkdir()

        # Create a minimal Python project
        (self.project_dir / "pyproject.toml").write_text(
            '[project]\nname = "my-project"\nversion = "0.1.0"\n'
            'requires-python = ">=3.10"\n\n'
            '[project.optional-dependencies]\ndev = ["pytest"]\n\n'
            '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n'
        )
        (self.project_dir / "src").mkdir()
        (self.project_dir / "src" / "main.py").write_text('print("hello")\n')
        (self.project_dir / "tests").mkdir()

        self.pd = str(self.project_dir)

    # ── Step 1: Session Start BEFORE harness setup ──────────────────

    def test_step1_session_start_no_harness(self):
        """First session start — no .harness/ → recommends setup."""
        r = run_script("restore_runtime_context.py", self.pd)
        assert r.returncode == 0
        out = json.loads(r.stdout)
        ctx = out["hookSpecificOutput"]["additionalContext"]
        assert "setup_recommended" in ctx or "harness-setup" in ctx.lower() or "Not initialized" in ctx

    # ── Step 2: Harness Setup (scaffold) ────────────────────────────

    def test_step2_scaffold(self):
        """Run scaffold → .harness/ and .claude/rules/learned/ created."""
        r = run_script("scaffold_runtime.py", self.pd)
        assert r.returncode == 0

        harness = self.project_dir / ".harness"
        assert harness.exists()
        assert (harness / "goals").is_dir()
        assert (harness / "contracts").is_dir()
        assert (harness / "artifacts").is_dir()
        assert (harness / "failures").is_dir()
        assert (harness / "progress").is_dir()

        # profile.json created
        profile = json.loads((harness / "profile.json").read_text())
        assert profile["language"] == "python"

        # config.json created
        config = json.loads((harness / "config.json").read_text())
        assert config["guard_enabled"] is True
        assert config["contract_required"] is False

        # .claude/rules/learned/ created
        assert (self.project_dir / ".claude" / "rules" / "learned").is_dir()

    # ── Step 3: Session Start AFTER harness setup ───────────────────

    def test_step3_session_start_with_harness(self):
        """After scaffold, session start restores harness state (no active goal = silent exit)."""
        run_script("scaffold_runtime.py", self.pd)

        r = run_script("restore_runtime_context.py", self.pd)
        assert r.returncode == 0
        # With harness but no active goal/failures, restore outputs nothing (silent allow)
        # This is correct behavior — no context to inject
        if r.stdout.strip():
            out = json.loads(r.stdout)
            ctx = out["hookSpecificOutput"]["additionalContext"]
            assert isinstance(ctx, str)

    # ── Step 4: Create goal + contract ──────────────────────────────

    def test_step4_create_goal_and_contract(self):
        """Create a goal and contract for login-api."""
        run_script("scaffold_runtime.py", self.pd)

        harness = self.project_dir / ".harness"
        goal_id = "login-api"

        # Write goal document
        goal_md = (
            f"# Goal: {goal_id}\n\n"
            f"- **Created**: 2026-04-10\n"
            f"- **Updated**: 2026-04-10\n"
            f"- **Status**: draft\n"
            f"- **Active Contract**: {goal_id}\n\n"
            f"## User Goal\n\nBuild a login API with JWT tokens\n"
        )
        (harness / "goals" / f"{goal_id}.md").write_text(goal_md)

        # Write contract
        contract = {
            "goal_id": goal_id,
            "user_goal": "Build a login API with JWT tokens",
            "acceptance_criteria": [
                {"id": "AC-1", "text": "POST /login returns 200 with valid credentials", "status": "unmet", "evidence": []},
                {"id": "AC-2", "text": "JWT token issued on success", "status": "unmet", "evidence": []},
                {"id": "AC-3", "text": "Password hashing with bcrypt", "status": "unmet", "evidence": []},
            ],
            "required_evidence": ["relevant test output", "review verdict", "qa verdict"],
            "status": "draft",
        }
        (harness / "contracts" / f"{goal_id}.json").write_text(json.dumps(contract, indent=2))

        # Verify contract exists
        assert (harness / "contracts" / f"{goal_id}.json").exists()
        loaded = json.loads((harness / "contracts" / f"{goal_id}.json").read_text())
        assert loaded["status"] == "draft"
        assert len(loaded["acceptance_criteria"]) == 3

    # ── Step 5: Contract transition draft → active ──────────────────

    def test_step5_contract_draft_to_active(self):
        """Transition contract from draft to active."""
        run_script("scaffold_runtime.py", self.pd)

        harness = self.project_dir / ".harness"
        goal_id = "login-api"

        contract = {
            "goal_id": goal_id,
            "user_goal": "Build login API",
            "acceptance_criteria": [
                {"id": "AC-1", "text": "POST /login works", "status": "unmet", "evidence": []},
            ],
            "required_evidence": ["relevant test output", "review verdict", "qa verdict"],
            "status": "draft",
        }
        contract_path = harness / "contracts" / f"{goal_id}.json"
        contract_path.write_text(json.dumps(contract))

        # Transition: draft → active
        import validate_contract
        ok, msg = validate_contract.can_transition(contract, "active")
        assert ok, f"Transition failed: {msg}"

        contract["status"] = "active"
        contract_path.write_text(json.dumps(contract))

        loaded = json.loads(contract_path.read_text())
        assert loaded["status"] == "active"

    # ── Step 6: Guard checks during implementation ──────────────────

    def test_step6_guard_allows_normal_edit(self):
        """Guard allows normal file edits during implementation."""
        run_script("scaffold_runtime.py", self.pd)

        r = run_guard({
            "cwd": self.pd,
            "tool_name": "Edit",
            "tool_input": {"file_path": f"{self.pd}/src/main.py", "old_string": "hello", "new_string": "world"},
        })
        assert r.returncode == 0

    def test_step6_guard_blocks_env(self):
        """Guard blocks .env access."""
        run_script("scaffold_runtime.py", self.pd)

        r = run_guard({
            "cwd": self.pd,
            "tool_name": "Read",
            "tool_input": {"file_path": f"{self.pd}/.env"},
        })
        assert r.returncode == 2
        assert "DENIED" in r.stderr or "secret" in r.stderr.lower()

    def test_step6_guard_blocks_force_push(self):
        """Guard blocks git push --force."""
        r = run_guard({
            "cwd": self.pd,
            "tool_name": "Bash",
            "tool_input": {"command": "git push --force origin main"},
        })
        assert r.returncode == 2

    def test_step6_guard_blocks_reviewer_edit(self):
        """Guard blocks code-reviewer from editing product code."""
        run_script("scaffold_runtime.py", self.pd)

        r = run_guard({
            "cwd": self.pd,
            "tool_name": "Edit",
            "tool_input": {"file_path": f"{self.pd}/src/main.py"},
            "agent_type": "code-reviewer",
        })
        assert r.returncode == 2

    def test_step6_guard_allows_reviewer_read(self):
        """Guard allows code-reviewer to read files."""
        r = run_guard({
            "cwd": self.pd,
            "tool_name": "Read",
            "tool_input": {"file_path": f"{self.pd}/src/main.py"},
            "agent_type": "code-reviewer",
        })
        assert r.returncode == 0

    # ── Step 7: Trace logging during implementation ─────────────────

    def test_step7_trace_records_tool_calls(self):
        """PostToolUse trace logs tool calls to trace.jsonl."""
        run_script("scaffold_runtime.py", self.pd)
        harness = self.project_dir / ".harness"

        # Simulate an Edit tool call
        event = {
            "cwd": self.pd,
            "tool_name": "Edit",
            "tool_input": {"file_path": f"{self.pd}/src/auth.py"},
            "tool_response": {},
        }
        r = run_trace(event, self.pd)
        assert r.returncode == 0

        trace_file = harness / "artifacts" / "trace.jsonl"
        assert trace_file.exists()
        lines = trace_file.read_text().strip().split("\n")
        assert len(lines) >= 1
        entry = json.loads(lines[0])
        assert entry["tool"] == "Edit"

    def test_step7_trace_detects_test_results(self):
        """Trace detects pytest output in Bash tool response."""
        run_script("scaffold_runtime.py", self.pd)
        harness = self.project_dir / ".harness"

        event = {
            "cwd": self.pd,
            "tool_name": "Bash",
            "tool_input": {"command": "pytest tests/ -v"},
            "tool_response": {"output": "3 passed in 0.5s"},
        }
        r = run_trace(event, self.pd)
        assert r.returncode == 0

        trace_file = harness / "artifacts" / "trace.jsonl"
        lines = trace_file.read_text().strip().split("\n")
        last = json.loads(lines[-1])
        # trace should detect pytest results and store them
        assert "test_results" in last or "pytest" in json.dumps(last).lower()

    # ── Step 8: Review artifact creation ────────────────────────────

    def test_step8_review_artifact(self):
        """code-reviewer creates review artifact."""
        run_script("scaffold_runtime.py", self.pd)
        harness = self.project_dir / ".harness"

        goal_id = "login-api"
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        review = {
            "reviewer": "code-reviewer",
            "verdict": "APPROVE",
            "blocking_findings": [],
            "non_blocking_findings": ["Consider adding input validation"],
            "missing_tests": [],
            "evidence_refs": ["pytest 3 passed"],
        }
        artifact_path = harness / "artifacts" / f"review-{goal_id}-{ts}.json"
        artifact_path.write_text(json.dumps(review, indent=2))
        assert artifact_path.exists()

        loaded = json.loads(artifact_path.read_text())
        assert loaded["verdict"] == "APPROVE"

    # ── Step 9: QA artifact creation ────────────────────────────────

    def test_step9_qa_artifact(self):
        """QA creates qa artifact."""
        run_script("scaffold_runtime.py", self.pd)
        harness = self.project_dir / ".harness"

        goal_id = "login-api"
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        qa = {
            "qa": "qa-browser",
            "verdict": "APPROVE",
            "criteria_checked": ["AC-1", "AC-2", "AC-3"],
            "evidence_refs": ["manual verification"],
        }
        artifact_path = harness / "artifacts" / f"qa-{goal_id}-{ts}.json"
        artifact_path.write_text(json.dumps(qa, indent=2))
        assert artifact_path.exists()

    # ── Step 10: Complete contract (full gate check) ────────────────

    def test_step10_completion_gate(self):
        """Full completion gate: all AC met + review + QA → done."""
        run_script("scaffold_runtime.py", self.pd)
        harness = self.project_dir / ".harness"
        goal_id = "login-api"
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")

        # Create active contract with all criteria met
        contract = {
            "goal_id": goal_id,
            "user_goal": "Build login API",
            "acceptance_criteria": [
                {"id": "AC-1", "text": "POST /login works", "status": "met", "evidence": ["test passed"]},
                {"id": "AC-2", "text": "JWT issued", "status": "met", "evidence": ["test passed"]},
                {"id": "AC-3", "text": "bcrypt hashing", "status": "met", "evidence": ["test passed"]},
            ],
            "required_evidence": ["relevant test output", "review verdict", "qa verdict"],
            "status": "review",
        }
        (harness / "contracts" / f"{goal_id}.json").write_text(json.dumps(contract))

        # Create review artifact
        review = {"reviewer": "code-reviewer", "verdict": "APPROVE", "blocking_findings": [], "evidence_refs": ["test passed"]}
        (harness / "artifacts" / f"review-{goal_id}-{ts}.json").write_text(json.dumps(review))

        # Create QA artifact
        qa = {"qa": "qa-browser", "verdict": "APPROVE", "criteria_checked": ["AC-1", "AC-2", "AC-3"]}
        (harness / "artifacts" / f"qa-{goal_id}-{ts}.json").write_text(json.dumps(qa))

        # Create progress file
        (harness / "progress" / f"{goal_id}.md").write_text("# Progress\nAll criteria met.\n")

        # Create trace with test execution (test_results must be a list of dicts)
        trace_entry = {"ts": ts, "tool": "Bash", "command": "pytest", "test_results": [{"runner": "pytest", "passed": True}]}
        (harness / "artifacts" / "trace.jsonl").write_text(json.dumps(trace_entry) + "\n")

        # Attempt transition: review → done (with full gate check)
        import validate_contract
        ok, msg = validate_contract.can_transition(contract, "done", project_dir=self.project_dir)
        assert ok, f"Completion gate blocked: {msg}"

        # Apply transition
        contract["status"] = "done"
        (harness / "contracts" / f"{goal_id}.json").write_text(json.dumps(contract))
        loaded = json.loads((harness / "contracts" / f"{goal_id}.json").read_text())
        assert loaded["status"] == "done"

    def test_step10_completion_gate_blocks_without_review(self):
        """Completion gate blocks done without review artifact."""
        run_script("scaffold_runtime.py", self.pd)
        harness = self.project_dir / ".harness"
        goal_id = "login-api"

        contract = {
            "goal_id": goal_id,
            "user_goal": "Build login API",
            "acceptance_criteria": [
                {"id": "AC-1", "text": "works", "status": "met", "evidence": ["test"]},
            ],
            "required_evidence": ["relevant test output", "review verdict", "qa verdict"],
            "status": "review",
        }
        (harness / "contracts" / f"{goal_id}.json").write_text(json.dumps(contract))

        # NO review artifact, NO QA artifact
        import validate_contract
        ok, msg = validate_contract.can_transition(contract, "done", project_dir=self.project_dir)
        assert not ok, "Should have blocked — no review artifact"
        assert "review" in msg.lower() or "evidence" in msg.lower() or "gate" in msg.lower()

    # ── Step 11: Failure path — retro + rule promotion ──────────────

    def test_step11_failure_retro_and_promotion(self):
        """Failure → retro → rule promotion → learned rule created."""
        run_script("scaffold_runtime.py", self.pd)
        harness = self.project_dir / ".harness"

        # Create .claude/rules/learned/ and agent-memory
        learned_dir = self.project_dir / ".claude" / "rules" / "learned"
        learned_dir.mkdir(parents=True, exist_ok=True)
        memory_dir = self.project_dir / ".claude" / "agent-memory" / "code-reviewer"
        memory_dir.mkdir(parents=True, exist_ok=True)

        # Step A: Write failure retro
        retro_input = {
            "symptom": "JWT token expires but returns 500 instead of 401",
            "root_cause": "Error handler doesn't catch TokenExpiredError",
            "why_missed": "No test for expired token case",
            "remediation": "Added TokenExpiredError handler + expired token test",
            "candidate_rule": "Auth changes must include expired/invalid token edge case tests",
            "next_replan": "Re-verify AC-2 with new tests",
        }
        r = run_script("write_failure_retro.py", self.pd,
                        stdin_data=json.dumps(retro_input),
                        extra_args=[self.pd, "login-api"])
        assert r.returncode == 0, f"write_failure_retro failed: {r.stderr}"

        # Verify retro file created
        retro_files = list((harness / "failures").glob("login-api-*.md"))
        assert len(retro_files) == 1
        retro_content = retro_files[0].read_text(encoding="utf-8")
        assert "TokenExpiredError" in retro_content
        assert "## Root Cause" in retro_content

        # Step B: Promote rule
        promote_input = {
            "retro_file": str(retro_files[0]),
            "name": "auth-expired-token-test",
            "rule_text": "Auth-related changes must always include tests for expired and invalid token edge cases",
            "scope": "src/auth/**",
            "recurrence_risk": "high",
            "agent": "code-reviewer",
        }
        r = run_script("promote_rule.py", self.pd, stdin_data=json.dumps(promote_input))
        assert r.returncode == 0

        result = json.loads(r.stdout)
        assert result["promoted"] is True

        # Verify rule file created
        rule_files = list(learned_dir.glob("*.md"))
        assert len(rule_files) >= 1
        rule_content = rule_files[0].read_text()
        assert "expired" in rule_content.lower() or "token" in rule_content.lower()
        assert "paths:" in rule_content

        # Verify retro updated
        retro_updated = retro_files[0].read_text(encoding="utf-8")
        assert "promoted" in retro_updated.lower() or "yes" in retro_updated.lower() or "Promoted" in retro_updated

    # ── Step 12: Session continuity (summarize → restore) ───────────

    def test_step12_session_continuity(self):
        """Summarize status → next session restores state."""
        run_script("scaffold_runtime.py", self.pd)
        harness = self.project_dir / ".harness"
        goal_id = "login-api"

        # Create an active goal
        (harness / "goals" / f"{goal_id}.md").write_text(
            f"# Goal: {goal_id}\n- **Status**: active\n\n## User Goal\nBuild login API\n"
        )
        contract = {
            "goal_id": goal_id,
            "acceptance_criteria": [
                {"id": "AC-1", "text": "POST /login works", "status": "met", "evidence": ["test"]},
                {"id": "AC-2", "text": "JWT issued", "status": "unmet", "evidence": []},
            ],
            "status": "active",
        }
        (harness / "contracts" / f"{goal_id}.json").write_text(json.dumps(contract))

        # Step A: Summarize (simulates PreCompact/SessionEnd)
        r = run_script("summarize_status.py", self.pd)
        assert r.returncode == 0
        summary_path = harness / "progress" / "session-summary.md"
        assert summary_path.exists()
        summary = summary_path.read_text(encoding="utf-8")
        assert goal_id in summary

        # Step B: Restore in "new session" (simulates SessionStart)
        r = run_script("restore_runtime_context.py", self.pd)
        assert r.returncode == 0
        out = json.loads(r.stdout)
        ctx = out["hookSpecificOutput"]["additionalContext"]

        # Should contain active goal info
        assert goal_id in ctx or "login" in ctx.lower()

    # ── Step 13: Guard disabled via config ──────────────────────────

    def test_step13_guard_disabled(self):
        """guard_enabled=false → all checks skipped."""
        run_script("scaffold_runtime.py", self.pd)
        harness = self.project_dir / ".harness"

        # Disable guard
        config = {"guard_enabled": False, "contract_required": False, "trace_enabled": True}
        (harness / "config.json").write_text(json.dumps(config))

        # Even .env access should pass
        r = run_guard({
            "cwd": self.pd,
            "tool_name": "Read",
            "tool_input": {"file_path": f"{self.pd}/.env"},
        })
        assert r.returncode == 0

    # ── Step 14: Trace disabled via config ──────────────────────────

    def test_step14_trace_disabled(self):
        """trace_enabled=false → no trace written."""
        run_script("scaffold_runtime.py", self.pd)
        harness = self.project_dir / ".harness"

        config = {"guard_enabled": True, "contract_required": False, "trace_enabled": False}
        (harness / "config.json").write_text(json.dumps(config))

        event = {
            "cwd": self.pd,
            "tool_name": "Edit",
            "tool_input": {"file_path": f"{self.pd}/src/main.py"},
            "tool_response": {},
        }
        r = run_trace(event, self.pd)
        assert r.returncode == 0

        trace_file = harness / "artifacts" / "trace.jsonl"
        assert not trace_file.exists() or trace_file.read_text().strip() == ""

    # ── Step 15: No harness → everything passes silently ────────────

    def test_step15_no_harness_graceful(self):
        """Without .harness/, all hooks pass silently."""
        # Guard passes
        r = run_guard({
            "cwd": self.pd,
            "tool_name": "Edit",
            "tool_input": {"file_path": f"{self.pd}/src/main.py"},
        })
        assert r.returncode == 0

        # Trace passes (no .harness/)
        r = run_trace({
            "cwd": self.pd,
            "tool_name": "Edit",
            "tool_input": {"file_path": f"{self.pd}/src/main.py"},
            "tool_response": {},
        }, self.pd)
        assert r.returncode == 0

        # Restore passes
        r = run_script("restore_runtime_context.py", self.pd)
        assert r.returncode == 0
