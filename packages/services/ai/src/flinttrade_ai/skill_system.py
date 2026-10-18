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

import hashlib
import json
import logging
import re
from dataclasses import asdict
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
        meta = yaml.safe_load(match.group(1))
    except yaml.YAMLError as error:
        raise ValueError("invalid skill frontmatter") from error
    if meta is None:
        meta = {}
    if not isinstance(meta, dict):
        raise ValueError("skill frontmatter must be a mapping")
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

    try:
        meta, body = _parse_frontmatter(text)
    except ValueError:
        return None

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

    def __init__(self, skills_dir: Path | None = None, *, knowledge_store: Any | None = None,
                 stock_rights: Any | None = None, run_id: str | None = None) -> None:
        """Initialise the registry and scan the skill directory.

        Args:
            skills_dir: Directory containing ``*.md`` skill files. Defaults to
                ``packages/services/ai/skills/`` in the managed source checkout.
        """
        if skills_dir is None:
            skills_dir = _default_skills_dir()
        self.skills_dir: Path = skills_dir
        self._skills: dict[str, SkillConfig] = {}
        self._packages: dict[str, dict[str, str]] = {}
        self.knowledge_store, self.stock_rights, self.run_id = knowledge_store, stock_rights, run_id
        self.knowledge_scope: Any | None = None
        self._scan()
        if self.knowledge_store is not None:
            if stock_rights is None:
                raise ValueError("stock package rights required")
            for name, package in self._packages.items():
                version = hashlib.sha256(json.dumps(package, sort_keys=True).encode()).hexdigest()
                self.knowledge_store.stock(name, version, package, stock_rights)

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
            if path.is_symlink():
                raise ValueError("skill document must not be a symlink")
            skill = _load_skill_file(path)
            if skill is not None:
                package = {path.name: path.read_text(encoding="utf-8")}
                for key in ("references", "scripts"):
                    for relative in skill.metadata.get(key, []):
                        member = self.skills_dir / relative
                        if member.is_symlink() or not member.resolve().is_relative_to(self.skills_dir.resolve()):
                            raise ValueError("skill member escapes package")
                        package[relative] = member.read_text(encoding="utf-8")
                self._packages[skill.name] = package
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

        summaries = [SkillSummary(name=item["name"], category=item["category"], description=item["description"])
                     for item in self.catalogue() if item["enabled"]]
        return sorted(summaries, key=_sort_key)

    @staticmethod
    def _package_skill(name: str, package: dict[str, str]) -> SkillConfig:
        main = name + ".md" if name + ".md" in package else "SKILL.md"
        metadata, body = _parse_frontmatter(package[main])
        return SkillConfig(name=name, category=str(metadata.get("category", "other")),
                           description=str(metadata.get("description", "")), content=body,
                           metadata={key: value for key, value in metadata.items()
                                     if key not in {"name", "category", "description"}})

    def catalogue(self) -> list[dict[str, Any]]:
        """Curation view; inactive candidates are never advertised to model selection."""
        if self.knowledge_store is None:
            return [{"name": skill.name, "category": skill.category, "description": skill.description,
                     "state": "local", "enabled": True} for skill in self._skills.values()]
        rows = self.knowledge_store.catalogue(scope=self.knowledge_scope, run_id=self.run_id)
        for row in rows:
            package = self.knowledge_store.version(row["version_id"])["files"]
            skill = self._package_skill(row["name"], package)
            row.update(category=skill.category, description=skill.description)
        return rows

    def _selected_package(self, name: str, *, pin: bool = False) -> tuple[SkillConfig, dict[str, str], str | None]:
        if self.knowledge_store is not None:
            version_id = (self.knowledge_store.pin(self.run_id, name, scope=self.knowledge_scope)
                          if pin and self.run_id else
                          self.knowledge_store.resolve(name, run_id=self.run_id, scope=self.knowledge_scope))
            package = self.knowledge_store.version(version_id)["files"]
            return self._package_skill(name, package), package, version_id
        if name not in self._skills:
            raise KeyError(f"Unknown skill '{name}'. Available skills: {', '.join(sorted(self._skills))}")
        return self._skills[name].model_copy(deep=True), self._packages[name], None

    def load_skill(self, name: str) -> SkillConfig:
        """Load the full skill document on demand.

        Args:
            name: Skill name as declared in the frontmatter.

        Returns:
            SkillConfig with the full markdown content.

        Raises:
            KeyError: If no skill with the given name is registered.
        """
        return self._selected_package(name)[0]

    def context(self, names: list[str], *, max_bytes: int = 32768) -> tuple[str, dict[str, Any]]:
        """Return selected whole procedures/references and exact supplied-byte receipts.

        Scripts are hashed as package members, never executed. Selection is explicit;
        a too-large selection refuses rather than silently dropping procedure steps.
        """
        blocks, receipts = [], []
        for name in dict.fromkeys(names):
            skill, package, version_id = self._selected_package(name, pin=True)
            if self.knowledge_store is None and skill.metadata.get("source") == "autonomous-agent-reflection":
                raise ValueError("learned skills require independent ledger validation")
            hashes = {key: hashlib.sha256(value.encode()).hexdigest() for key, value in sorted(package.items())}
            package_hash = hashlib.sha256(json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            text = f"## Procedure: {name}\n{skill.content}"
            references = list(skill.metadata.get("references", []))
            for reference in references:
                text += f"\n### Reference: {reference}\n{package[reference]}"
            blocks.append(text)
            receipts.append({"name": name, "package_hash": package_hash, "files": hashes,
                             "references": references, "version_id": version_id,
                             "supplied_hash": hashlib.sha256(text.encode()).hexdigest()})
        text = "\n\n".join(blocks)
        if len(text.encode()) > max_bytes:
            raise ValueError("selected skill context exceeds byte budget")
        receipt = {"skills": receipts, "context_hash": hashlib.sha256(text.encode()).hexdigest(),
                   "run_id": self.run_id, "scope": asdict(self.knowledge_scope) if self.knowledge_scope else None}
        if self.knowledge_store is not None:
            receipt["receipt_id"] = self.knowledge_store.record_context(receipt)
        return text, receipt

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
        for skill in self.list_skills():
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
        self._packages.clear()
        self._scan()
        if self.knowledge_store is not None:
            for name, package in self._packages.items():
                version = hashlib.sha256(json.dumps(package, sort_keys=True).encode()).hexdigest()
                self.knowledge_store.stock(name, version, package, self.stock_rights)

    def __len__(self) -> int:
        """Return the number of registered skills."""
        return len(self.list_skills())

    def __contains__(self, name: str) -> bool:
        """Check if a skill name is registered."""
        try:
            self._selected_package(name)
        except (KeyError, ValueError):
            return False
        return True
