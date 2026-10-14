"""Composition seam for shared no-training context and scoped portable learning."""
from __future__ import annotations

from pathlib import Path

from flinttrade_ai.knowledge_store import KnowledgeMemory, KnowledgeScope, KnowledgeStore
from flinttrade_ai.memory_ledger import MemoryLedger
from flinttrade_ai.skill_system import SkillRegistry
from flinttrade_core.service_providers import RightsResolution


class KnowledgeRuntime:
    """One ledger per workspace; stock/recall consumers share it without a model server.

    The core composition root supplies licence evidence and the exact session
    scope. It retains this owner until all bound consumers/background jobs stop.
    A missing/corrupt ledger raises; there is no empty in-memory replacement.
    """

    def __init__(self, workspace: Path, *, stock_rights: RightsResolution,
                 skills_dir: Path | None = None) -> None:
        self.workspace = Path(workspace)
        self.ledger = MemoryLedger(workspace / "knowledge")
        self.store = KnowledgeStore(self.ledger)
        self.stock_rights = stock_rights
        self.skills_dir = skills_dir
        self.registry = self.skills()
        self.input_issues: list[dict[str, str]] = []
        self.refresh_inputs()

    def skills(self, scope: KnowledgeScope | None = None) -> SkillRegistry:
        """Bind stock and eligible adaptations to the exact run, not a UI app."""
        registry = SkillRegistry(self.skills_dir, knowledge_store=self.store, stock_rights=self.stock_rights,
                                 run_id=scope.run_id if scope else None)
        registry.knowledge_scope = scope
        return registry

    def ingest_skill(self, name: str, *, source: str = "skill_drafts",
                     rights: RightsResolution | None = None, scope: KnowledgeScope | None = None,
                     evidence_ids: tuple[str, ...] = ()) -> str:
        """Retain a workspace input as a candidate; never move it or trust YAML rights."""
        from flinttrade_ai.knowledge_ingest import read_package
        if source not in {"skills", "skill_drafts"}:
            raise ValueError("invalid skill input source")
        files = read_package(self.workspace / source, name)
        return self.store.propose(name, files, proposer="workspace-input", source_ref=f"{source}/{name}.md",
                                  rights=rights, scope=scope, evidence_ids=evidence_ids)

    def refresh_inputs(self) -> list[dict[str, str]]:
        """Snapshot retained inputs in place with unknown rights; never mass-migrate.

        Unreadable/malformed inputs stay untouched and unavailable. They cannot
        remove bundled procedures or become trusted through frontmatter status.
        """
        rows, issues = [], []
        for source in ("skills", "skill_drafts"):
            root = self.workspace / source
            if root.is_symlink():
                issues.append({"source": source, "state": "unavailable"})
                continue
            for path in sorted(root.glob("*.md")):
                try:
                    version = self.ingest_skill(path.stem, source=source)
                except (OSError, ValueError):
                    issues.append({"source": source, "name": path.stem, "state": "unavailable"})
                else:
                    rows.append({"source": source, "name": path.stem, "version_id": version})
        self.input_issues = issues
        return rows

    def memory(self, scope: KnowledgeScope, *, rights: RightsResolution) -> KnowledgeMemory:
        """Return a scoped writer/reader; unscoped vector memories are not authority."""
        return KnowledgeMemory(self.ledger, scope, rights=rights)

    def close(self) -> None:
        """Release the shared owner after its consumers have quiesced."""
        self.ledger.close()
