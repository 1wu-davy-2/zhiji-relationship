#!/usr/bin/env python3
"""Validate the distributable zhiji skill without third-party packages."""

from __future__ import annotations

import re
import subprocess
import sys
from math import ceil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ERRORS: list[str] = []
MIN_KNOWLEDGE_DOCUMENTS = 20
MIN_PRACTICAL_DOCUMENTS = 20
SKILL_MAX_LINES = 150
SKILL_MAX_CHARACTERS = 5_000
SKILL_MAX_APPROX_TOKENS = 4_500

# Required reference files that define the three-persona runtime contract.
# Knowledge and practical documents are covered by the count checks below.
REQUIRED_KNOWLEDGE: tuple[str, ...] = ()
REQUIRED_PRACTICAL: tuple[str, ...] = ()
REQUIRED_PERSPECTIVES: tuple[str, ...] = (
    "references/perspective/goutoujunshi/SKILL.md",
    "references/perspective/tong-jincheng/SKILL.md",
    "references/perspective/fengge/SKILL.md",
)
REQUIRED_SUPPORTING: tuple[str, ...] = (
    "references/persona-routing.md",
)

# Scenario files that must be present under tests/ in full (non-runtime) mode.
REQUIRED_SCENARIOS: tuple[str, ...] = (
    "combined-integration-scenarios.md",
)


def require(path: str) -> Path:
    """Assert that ROOT/path exists; record an error if it does not."""
    target = ROOT / path
    if not target.exists():
        ERRORS.append(f"missing required path: {path}")
    return target


# ---------------------------------------------------------------------------
# Frontmatter
# ---------------------------------------------------------------------------

def validate_frontmatter() -> None:
    """Check that SKILL.md has valid YAML frontmatter with the correct skill name."""
    skill = require("SKILL.md")
    if not skill.is_file():
        return

    content = skill.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", content, re.DOTALL)
    if not match:
        ERRORS.append("SKILL.md has invalid YAML frontmatter boundaries")
        return

    frontmatter = match.group(1)
    keys = re.findall(r"^([A-Za-z0-9_-]+):", frontmatter, re.MULTILINE)
    if keys != ["name", "description"]:
        ERRORS.append(f"SKILL.md frontmatter keys must be name, description; got {keys}")

    name_match = re.search(r"^name:\s*([^\n]+)$", frontmatter, re.MULTILINE)
    description_match = re.search(r"^description:\s*(.+)$", frontmatter, re.MULTILINE)
    name = name_match.group(1).strip() if name_match else ""
    description = description_match.group(1).strip() if description_match else ""

    # Skill name must be exactly "zhiji" and match the slug pattern.
    if name != "zhiji" or not re.fullmatch(r"[a-z0-9-]{1,64}", name):
        ERRORS.append(f"invalid skill name: {name!r}")
    if not description or len(description) > 1024 or "<" in description or ">" in description:
        ERRORS.append("description is empty, too long, or contains angle brackets")


# ---------------------------------------------------------------------------
# SKILL.md size budget
# ---------------------------------------------------------------------------

def approximate_token_count(content: str) -> int:
    """Return a conservative, dependency-free budget estimate for mixed Chinese text."""
    cjk = len(re.findall(r"[㐀-䶿一-鿿豈-﫿]", content))
    latin_words = len(re.findall(r"[A-Za-z0-9_]+", content))
    other = len(re.findall(r"[^\sA-Za-z0-9_㐀-䶿一-鿿豈-﫿]", content))
    return cjk + ceil(latin_words * 1.3) + ceil(other / 4)


def validate_skill_budget() -> None:
    """Enforce the line, character, and approximate-token ceilings on SKILL.md."""
    skill = ROOT / "SKILL.md"
    if not skill.is_file():
        return

    content = skill.read_text(encoding="utf-8")
    lines = len(content.splitlines())
    characters = len(content)
    approx_tokens = approximate_token_count(content)

    if lines > SKILL_MAX_LINES:
        ERRORS.append(f"SKILL.md exceeds {SKILL_MAX_LINES} lines: {lines}")
    if characters > SKILL_MAX_CHARACTERS:
        ERRORS.append(
            f"SKILL.md exceeds {SKILL_MAX_CHARACTERS} characters: {characters}"
        )
    if approx_tokens > SKILL_MAX_APPROX_TOKENS:
        ERRORS.append(
            "SKILL.md exceeds approximate token budget "
            f"{SKILL_MAX_APPROX_TOKENS}: {approx_tokens}"
        )


# ---------------------------------------------------------------------------
# File inventory
# ---------------------------------------------------------------------------

def validate_inventory(runtime_only: bool) -> None:
    """Assert required files exist and reference-document counts meet minimums.

    In --runtime mode, README.md, LICENSE, and test scenario files are skipped,
    but the perspective sub-skill SKILL.md is always required because it is part
    of the distributable runtime content.
    """
    require("agents/openai.yaml")

    if not runtime_only:
        require("README.md")
        require("LICENSE")

    # --- Document-count minimums ---
    knowledge = list((ROOT / "references/knowledge").glob("*.md"))
    practical = list((ROOT / "references/practical").glob("*.md"))
    if len(knowledge) < MIN_KNOWLEDGE_DOCUMENTS:
        ERRORS.append(
            f"expected at least {MIN_KNOWLEDGE_DOCUMENTS} knowledge documents, "
            f"found {len(knowledge)}"
        )
    if len(practical) < MIN_PRACTICAL_DOCUMENTS:
        ERRORS.append(
            f"expected at least {MIN_PRACTICAL_DOCUMENTS} practical documents, "
            f"found {len(practical)}"
        )

    # --- Specific required reference files ---
    for filename in REQUIRED_KNOWLEDGE:
        require(f"references/knowledge/{filename}")
    for filename in REQUIRED_PRACTICAL:
        require(f"references/practical/{filename}")

    # --- Required perspective and routing files (always checked) ---
    for path in REQUIRED_PERSPECTIVES + REQUIRED_SUPPORTING:
        require(path)

    # --- Test scenario files (full mode only) ---
    if not runtime_only:
        for filename in REQUIRED_SCENARIOS:
            require(f"tests/{filename}")

    # --- Agent prompt must reference the skill by variable name ---
    agent = ROOT / "agents/openai.yaml"
    if agent.is_file() and "$zhiji" not in agent.read_text(encoding="utf-8"):
        ERRORS.append("agents/openai.yaml default prompt must mention $zhiji")


# ---------------------------------------------------------------------------
# Routing-table coverage and regression scenarios
# ---------------------------------------------------------------------------

def validate_routes_and_regressions(runtime_only: bool) -> None:
    """Check SKILL.md routing-table entries and (in full mode) integration-scenario
    coverage markers in tests/combined-integration-scenarios.md.

    In --runtime mode the scenario file check is skipped entirely, but the
    routing-table check always runs.
    """
    skill = ROOT / "SKILL.md"
    if skill.is_file():
        content = skill.read_text(encoding="utf-8")

        # The perspective sub-directory must appear as an explicit routing entry
        # so the agent knows to consult it when the routing table is evaluated.
        if "references/perspective/" not in content:
            ERRORS.append(
                "SKILL.md missing required routing-table entry: references/perspective/"
            )

    # In --runtime mode, skip documentation/ and tests/ checks entirely.
    if runtime_only:
        return

    # --- Coverage markers for tests/combined-integration-scenarios.md ---
    scenarios = ROOT / "tests/combined-integration-scenarios.md"
    if scenarios.is_file():
        content = scenarios.read_text(encoding="utf-8")
        # These markers assert that activation, safety precedence, single-persona,
        # combination, and knowledge/perspective routing paths are exercised.
        coverage_markers = (
            "style-activation",
            "safety-over-style",
            "dual-routing-correct",
            "single-persona-routing",
            "three-persona-routing",
            "custom-routing",
            "fengge-activation",
            "init-onboarding",
        )
        for marker in coverage_markers:
            if marker not in content:
                ERRORS.append(
                    "combined integration scenarios missing coverage marker: "
                    f"{marker}"
                )


# ---------------------------------------------------------------------------
# Runtime boundary whitelist
# ---------------------------------------------------------------------------

def validate_runtime_boundaries() -> None:
    """Ensure raw research files are untracked and that no non-runtime content
    (documentation/, tests/, etc.) is nested inside the runtime allowlist.

    references/perspective/ is a sub-tree of references/ and therefore already
    covered by that root; it is listed separately to make the allowlist intent
    explicit and auditable.
    """
    if (ROOT / ".git").exists():
        tracked_research = subprocess.run(
            ["git", "ls-files", "--", "research"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        for path in tracked_research:
            ERRORS.append(
                f"raw research must remain untracked and outside runtime content: {path}"
            )

    # Directories and files that form the distributable runtime surface.
    runtime_roots = (
        ROOT / "SKILL.md",
        ROOT / "agents",
        ROOT / "references",
        ROOT / "references/perspective",   # explicit; already covered by references/
        ROOT / "scripts",
        ROOT / "assets",
    )
    # Path components that must never appear inside the runtime allowlist.
    forbidden_parts = {"research", "documentation", "tests", ".git", "__pycache__"}

    for runtime_root in runtime_roots:
        if not runtime_root.exists():
            continue
        paths = (runtime_root,) if runtime_root.is_file() else runtime_root.rglob("*")
        for path in paths:
            if forbidden_parts.intersection(path.relative_to(ROOT).parts):
                ERRORS.append(
                    "non-runtime content nested inside runtime allowlist: "
                    f"{path.relative_to(ROOT)}"
                )
            if path.is_file() and path.suffix in {".pyc", ".pyo"}:
                ERRORS.append(
                    f"compiled test/runtime artifact found: {path.relative_to(ROOT)}"
                )


# ---------------------------------------------------------------------------
# Markdown link integrity
# ---------------------------------------------------------------------------

def validate_markdown_links() -> None:
    """Report any local markdown links that resolve to non-existent files."""
    link_pattern = re.compile(r"\]\(([^)]+)\)")
    for markdown in ROOT.rglob("*.md"):
        text = markdown.read_text(encoding="utf-8")
        for raw_target in link_pattern.findall(text):
            target = raw_target.strip().split("#", 1)[0]
            if not target or re.match(r"^(?:https?://|mailto:)", target):
                continue
            resolved = (markdown.parent / target).resolve()
            if not resolved.exists():
                ERRORS.append(
                    f"broken local link in {markdown.relative_to(ROOT)}: {raw_target}"
                )


# ---------------------------------------------------------------------------
# Placeholder scan
# ---------------------------------------------------------------------------

def validate_placeholders() -> None:
    """Fail if any tracked text file still contains the template marker TODO."""
    for path in ROOT.rglob("*"):
        if not path.is_file() or ".git" in path.parts:
            continue
        if path.suffix.lower() not in {".md", ".yaml", ".yml", ".py"}:
            continue
        text = path.read_text(encoding="utf-8")
        if "[" + "TODO" in text:
            ERRORS.append(f"template placeholder in {path.relative_to(ROOT)}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    unexpected_args = [arg for arg in sys.argv[1:] if arg != "--runtime"]
    if unexpected_args:
        print(f"ERROR: unsupported arguments: {' '.join(unexpected_args)}")
        return 2
    runtime_only = "--runtime" in sys.argv[1:]

    validate_frontmatter()
    validate_skill_budget()
    validate_inventory(runtime_only)
    validate_routes_and_regressions(runtime_only)
    validate_runtime_boundaries()
    validate_markdown_links()
    validate_placeholders()

    if ERRORS:
        for error in ERRORS:
            print(f"ERROR: {error}")
        return 1

    print("zhiji validation passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
