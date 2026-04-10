"""Evaluate and promote learned rules from failure retros.

Promotion criteria (ALL must be true):
  - Recurrence risk is high
  - Generalizable beyond this instance
  - Short and specific
  - Scopable to file paths
  - Verifiable by tests or review

After promotion, this script:
  1. Writes the rule to .claude/rules/learned/<name>.md
  2. Updates the source retro file's "Promoted?" field
  3. Optionally appends to agent-memory for role-specific lessons

Usage:
    python promote_rule.py <project_dir>
    Reads JSON from stdin with: name, scope, rule_text, retro_file (optional), agent (optional)
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


def check_duplicate(project_dir: Path, rule_text: str) -> str | None:
    """Check if a similar rule already exists. Returns the file name if found."""
    learned_dir = project_dir / ".claude" / "rules" / "learned"
    if not learned_dir.exists():
        return None

    text_lower = rule_text.strip().lower()
    for rule_file in learned_dir.glob("*.md"):
        if rule_file.name == "README.md":
            continue
        content = rule_file.read_text(encoding="utf-8").lower()
        for line in text_lower.split("\n"):
            line = line.strip("- #").strip()
            if len(line) > 20 and line in content:
                return rule_file.name

    return None


def _update_retro_file(retro_path: Path, promoted: bool, rule_file: str) -> None:
    """Update the Promoted? field in a failure retro markdown file."""
    if not retro_path.exists():
        return
    content = retro_path.read_text(encoding="utf-8")
    if promoted:
        replacement = f"promoted → `{rule_file}`"
    else:
        replacement = "not promoted (duplicate or not generalizable)"
    content = re.sub(
        r"(?m)^(##\s*Promoted\?\s*\n\n?).*$",
        rf"\g<1>{replacement}",
        content,
        count=1,
    )
    # Fallback: if the regex didn't match (different formatting), append
    if replacement not in content:
        content = content.rstrip() + f"\n\n## Promoted?\n\n{replacement}\n"
    retro_path.write_text(content, encoding="utf-8")


def _update_agent_memory(project_dir: Path, agent: str, lesson: str) -> None:
    """Append a lesson to the specified agent's MEMORY.md."""
    memory_path = project_dir / ".claude" / "agent-memory" / agent / "MEMORY.md"
    if not memory_path.exists():
        memory_path.parent.mkdir(parents=True, exist_ok=True)
        memory_path.write_text(f"# {agent.title()} Memory\n\n", encoding="utf-8")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    entry = f"\n## Lesson — {ts}\n\n{lesson}\n"
    with open(memory_path, "a", encoding="utf-8") as f:
        f.write(entry)


def evaluate_promotion_criteria(
    rule_text: str,
    scope: str,
    recurrence_risk: str = "unknown",
) -> tuple[bool, list[str]]:
    """Evaluate the 5 promotion criteria. Returns (pass, list_of_reasons).

    Criteria:
      1. Recurrence risk — caller must indicate via recurrence_risk param
      2. Generalizable — rule text should not reference specific filenames/line numbers
      3. Short and specific — rule text < 500 chars, > 20 chars
      4. Scopable — scope is not empty/wildcard-only
      5. Verifiable — rule contains actionable verb (must/should/always/never/check/verify/test)
    """
    reasons: list[str] = []

    # 1. Recurrence risk — only "high" qualifies for promotion
    if recurrence_risk != "high":
        reasons.append(f"recurrence risk is '{recurrence_risk}' — only 'high' risk failures are promoted")

    # 2. Generalizable — reject if it references specific line numbers or commit hashes
    if re.search(r"line\s+\d{2,}", rule_text, re.IGNORECASE):
        reasons.append("rule references specific line numbers — not generalizable")
    if re.search(r"[0-9a-f]{7,40}", rule_text) and "sha" not in rule_text.lower():
        # Looks like a commit hash
        if re.search(r"\b[0-9a-f]{7,40}\b", rule_text):
            reasons.append("rule appears to reference a specific commit hash — not generalizable")

    # 3. Short and specific
    text_len = len(rule_text.strip())
    if text_len < 20:
        reasons.append(f"rule text too short ({text_len} chars) — not specific enough")
    if text_len > 500:
        reasons.append(f"rule text too long ({text_len} chars) — should be concise")

    # 4. Scopable
    if not scope or scope in ("**/*", "*"):
        reasons.append("scope is too broad — specify target file paths")

    # 5. Verifiable — contains actionable language
    verifiable_patterns = r"\b(must|should|always|never|check|verify|test|ensure|require|validate|forbid|block)\b"
    if not re.search(verifiable_patterns, rule_text, re.IGNORECASE):
        reasons.append("rule lacks verifiable language (must/should/always/never/check/verify/test)")

    return len(reasons) == 0, reasons


def promote(
    project_dir: Path,
    name: str,
    scope: str,
    rule_text: str,
    retro_file: str = "",
    agent: str = "",
    recurrence_risk: str = "unknown",
) -> dict:
    """Write a learned rule file and close the retro loop. Returns a report."""
    learned_dir = project_dir / ".claude" / "rules" / "learned"
    learned_dir.mkdir(parents=True, exist_ok=True)

    # Evaluate promotion criteria
    criteria_ok, criteria_reasons = evaluate_promotion_criteria(rule_text, scope, recurrence_risk)
    if not criteria_ok:
        if retro_file:
            retro_path = Path(retro_file) if Path(retro_file).is_absolute() else project_dir / retro_file
            _update_retro_file(retro_path, False, "")
        return {"promoted": False, "reason": f"failed promotion criteria: {'; '.join(criteria_reasons)}"}

    # Check for duplicates
    dup = check_duplicate(project_dir, rule_text)
    if dup:
        # Update retro even on duplicate
        if retro_file:
            retro_path = Path(retro_file) if Path(retro_file).is_absolute() else project_dir / retro_file
            _update_retro_file(retro_path, False, "")
        return {"promoted": False, "reason": f"duplicate detected: {dup}"}

    # Sanitize name for filename
    safe_name = name.lower().replace(" ", "-").replace("/", "-")
    path = learned_dir / f"{safe_name}.md"

    if path.exists():
        return {"promoted": False, "reason": f"file already exists: {path.name}"}

    content = f"""---
paths:
  - "{scope}"
---

# {name}

{rule_text}
"""
    path.write_text(content, encoding="utf-8")

    result = {"promoted": True, "file": str(path.relative_to(project_dir))}

    # Close the retro loop: update retro file
    if retro_file:
        retro_path = Path(retro_file) if Path(retro_file).is_absolute() else project_dir / retro_file
        _update_retro_file(retro_path, True, path.relative_to(project_dir).as_posix())
        result["retro_updated"] = True

    # Role-specific memory update
    if agent:
        _update_agent_memory(project_dir, agent, rule_text)
        result["memory_updated"] = agent

    return result


def main() -> None:
    if len(sys.argv) < 2:
        print(json.dumps({"error": "usage: promote_rule.py <project_dir>"}))
        sys.exit(1)

    project_dir = Path(sys.argv[1])

    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, OSError):
        data = {}

    name = data.get("name", "unnamed-rule")
    scope = data.get("scope", "**/*")
    rule_text = data.get("rule_text", "")
    retro_file = data.get("retro_file", "")
    agent = data.get("agent", "")
    recurrence_risk = data.get("recurrence_risk", "unknown")

    if not rule_text:
        print(json.dumps({"error": "rule_text is required"}))
        sys.exit(1)

    result = promote(project_dir, name, scope, rule_text, retro_file, agent, recurrence_risk)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
