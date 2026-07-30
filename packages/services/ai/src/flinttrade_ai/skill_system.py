"""Skill system for FlintTrade AI agents.

Domain knowledge is stored as markdown files with YAML frontmatter and loaded
on-demand into LLM system prompts. Adapts the progressive-disclosure pattern
from Vibe-Trading's SkillsLoader: one-line summaries injected into the system
prompt; full content loaded only when the agent explicitly requests a skill.

Usage::

    from flinttrade_ai.skill_system import SkillRegistry

    registry = SkillRegistry()  # defaults to packages/services/ai/skills/

    # List names + descriptions for the system prompt
    section = registry.get_system_prompt_section()

    # Load full content when the agent selects a skill
    skill = registry.load_skill("risk_management")
    print(skill.content)

    # Fuzzy search
    results = registry.search_skills("stop loss position sizing")
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from flinttrade_core.source_root import discover_source_root

logger = logging.getLogger("flinttrade.ai.skills")

# ---------------------------------------------------------------------------
# Public type: lightweight summary (name + description, no content)
# ---------------------------------------------------------------------------

_CATEGORY_ORDER: list[str] = [
    "data",
    "strategy",
    "analysis",
    "execution",
    "safety",
    "compliance",
    "crypto",
    "other",
]


class SkillSummary(BaseModel):
    """Lightweight skill descriptor — injected into the LLM system prompt.

    Attributes:
        name: Unique skill identifier (matches the markdown filename stem).
        category: Broad domain grouping used for ordering in the system prompt.
        description: One-line human-readable description.
    """

    name: str
    category: str
    description: str


class SkillConfig(BaseModel):
    """Full skill definition including the markdown body.

    Attributes:
        name: Unique skill identifier.
        category: Broad domain grouping.
        description: One-line description.
        content: Full markdown body (everything after the YAML frontmatter).
        metadata: Any extra frontmatter keys as a raw dict.
    """

    name: str
    category: str
    description: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split YAML frontmatter from the markdown body.

    Args:
        text: Full file content (UTF-8).

    Returns:
        Tuple of (metadata dict, body string). If no frontmatter is found,
        metadata is empty and body is the full text.
    """
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", text, re.DOTALL)
    if not match:
        return {}, text.strip()
    try:
        meta: dict[str, Any] = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        meta = {}
    return meta, match.group(2).strip()


def _load_skill_file(path: Path) -> SkillConfig | None:
    """Parse a single skill markdown file.

    Args:
        path: Absolute path to the .md file.

    Returns:
        SkillConfig on success, None if the file is missing or malformed.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        logger.warning("Cannot read skill file: %s", path)
        return None

    meta, body = _parse_frontmatter(text)

    name = str(meta.get("name", path.stem))
    category = str(meta.get("category", "other"))
    description = str(meta.get("description", ""))

    if not name:
        logger.warning("Skill file has no name: %s", path)
        return None

    extra = {k: v for k, v in meta.items() if k not in ("name", "category", "description")}

    return SkillConfig(
        name=name,
        category=category,
        description=description,
        content=body,
        metadata=extra,
    )


# ---------------------------------------------------------------------------
# SkillRegistry — public API
# ---------------------------------------------------------------------------


def _default_skills_dir(module_file: Path | str | None = None) -> Path:
    """Return the AI skill directory inside the managed source checkout."""
    source_root = discover_source_root(module_file=module_file or __file__)
    return source_root / "packages" / "services" / "ai" / "skills"


class SkillRegistry:
    """Registry of domain-knowledge skill files.

    Scans a directory for ``*.md`` files with YAML frontmatter on initialisation.
    Supports on-demand full-content loading, fuzzy search, and system-prompt
    generation following the progressive-disclosure pattern.

    Attributes:
        skills_dir: Directory containing the skill markdown files.
    """

    def __init__(self, skills_dir: Path | None = None) -> None:
        """Initialise the registry and scan the skill directory.

        Args:
            skills_dir: Directory containing ``*.md`` skill files. Defaults to
                ``packages/services/ai/skills/`` in the managed source checkout.
        """
        if skills_dir is None:
            skills_dir = _default_skills_dir()
        self.skills_dir: Path = skills_dir
        self._skills: dict[str, SkillConfig] = {}
        self._scan()

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _scan(self) -> None:
        """Scan ``skills_dir`` for markdown skill files and cache summaries.

        Non-markdown files and files that fail to parse are silently skipped.
        """
        if not self.skills_dir.exists():
            logger.warning("Skills directory not found: %s", self.skills_dir)
            return

        loaded = 0
        for path in sorted(self.skills_dir.glob("*.md")):
            skill = _load_skill_file(path)
            if skill is not None:
                self._skills[skill.name] = skill
                loaded += 1

        logger.debug("Loaded %d skills from %s", loaded, self.skills_dir)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_skills(self) -> list[SkillSummary]:
        """Return a summary list of all registered skills.

        Returns:
            List of SkillSummary sorted by category order then name.
        """
        def _sort_key(s: SkillSummary) -> tuple[int, str]:
            try:
                cat_idx = _CATEGORY_ORDER.index(s.category)
            except ValueError:
                cat_idx = len(_CATEGORY_ORDER)
            return (cat_idx, s.name)

        summaries = [
            SkillSummary(name=s.name, category=s.category, description=s.description)
            for s in self._skills.values()
        ]
        return sorted(summaries, key=_sort_key)

    def load_skill(self, name: str) -> SkillConfig:
        """Load the full skill document on demand.

        Args:
            name: Skill name as declared in the frontmatter.

        Returns:
            SkillConfig with the full markdown content.

        Raises:
            KeyError: If no skill with the given name is registered.
        """
        if name not in self._skills:
            available = ", ".join(sorted(self._skills))
            raise KeyError(
                f"Unknown skill '{name}'. Available skills: {available}"
            )
        return self._skills[name]

    def search_skills(self, query: str) -> list[SkillSummary]:
        """Fuzzy keyword search across skill names and descriptions.

        Splits the query into tokens and returns skills whose name or
        description contains *all* tokens (case-insensitive).  Returns an
        unordered subset of :meth:`list_skills`.

        Args:
            query: Space-separated search terms.

        Returns:
            List of matching SkillSummary objects.
        """
        tokens = [t.lower() for t in query.split() if t]
        if not tokens:
            return self.list_skills()

        results: list[SkillSummary] = []
        for skill in self._skills.values():
            haystack = f"{skill.name} {skill.description}".lower()
            if all(tok in haystack for tok in tokens):
                results.append(
                    SkillSummary(
                        name=skill.name,
                        category=skill.category,
                        description=skill.description,
                    )
                )
        return results

    def get_system_prompt_section(self) -> str:
        """Generate the skills section for injection into an LLM system prompt.

        Groups skills by category in the canonical order. Each entry is a
        single line: ``  - <name>: <description>``.

        Returns:
            Formatted multi-line string. Returns ``"(no skills loaded)"``
            if the registry is empty.
        """
        summaries = self.list_skills()
        if not summaries:
            return "(no skills loaded)"

        groups: dict[str, list[SkillSummary]] = {}
        for s in summaries:
            groups.setdefault(s.category, []).append(s)

        lines: list[str] = ["## Available Skills\n"]
        for cat in [c for c in _CATEGORY_ORDER if c in groups] + [
            c for c in sorted(groups) if c not in _CATEGORY_ORDER
        ]:
            lines.append(f"### {cat}")
            for s in groups[cat]:
                lines.append(f"  - {s.name}: {s.description}")

        return "\n".join(lines)

    def reload(self) -> None:
        """Re-scan the skills directory to pick up new or changed files.

        Useful for hot-reload scenarios during development.
        """
        self._skills.clear()
        self._scan()

    def __len__(self) -> int:
        """Return the number of registered skills."""
        return len(self._skills)

    def __contains__(self, name: str) -> bool:
        """Check if a skill name is registered."""
        return name in self._skills
