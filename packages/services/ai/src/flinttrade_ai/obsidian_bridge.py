"""Obsidian vault connector.

Lets the native AI agent read and write the operator's Obsidian vault — a folder
of markdown notes — so it can pull research/context and persist trade journals,
strategy write-ups, and post-market notes back into the operator's knowledge
base.

A vault is just a directory of ``.md`` files. This connector is a thin, safe
wrapper over that directory: every path is resolved and confined to the vault
root (no traversal escapes), and note names without an extension get ``.md``.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger("flinttrade.ai.obsidian")


class ObsidianError(Exception):
    """Raised for vault access errors (missing vault, path escape, missing note)."""


class ObsidianVault:
    """Safe read/write access to an Obsidian vault directory.

    Args:
        vault_path: Filesystem path to the Obsidian vault root.
    """

    def __init__(self, vault_path: str | Path) -> None:
        self._root = Path(vault_path).expanduser()

    @property
    def root(self) -> Path:
        return self._root

    @property
    def available(self) -> bool:
        """True when the configured vault directory exists."""
        return self._root.is_dir()

    # ------------------------------------------------------------------
    # Path safety
    # ------------------------------------------------------------------

    def _resolve(self, rel: str, *, must_exist: bool = False) -> Path:
        """Resolve ``rel`` within the vault, confirming it does not escape root."""
        if not self.available:
            raise ObsidianError(f"Obsidian vault not found at {self._root}")
        rel = rel.strip().lstrip("/\\")
        if not rel:
            raise ObsidianError("Note path is required")
        root = self._root.resolve()
        candidate = (root / rel).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise ObsidianError("Note path escapes the vault") from exc
        if candidate.suffix.lower() != ".md":
            candidate = candidate.with_suffix(".md")
        if must_exist and not candidate.is_file():
            raise ObsidianError(f"Note not found: {rel}")
        return candidate

    def _rel(self, path: Path) -> str:
        return path.resolve().relative_to(self._root.resolve()).as_posix()

    # ------------------------------------------------------------------
    # Notes
    # ------------------------------------------------------------------

    def list_notes(self) -> list[str]:
        """Return vault-relative paths of every markdown note (sorted)."""
        if not self.available:
            return []
        root = self._root.resolve()
        return sorted(p.relative_to(root).as_posix() for p in root.rglob("*.md") if p.is_file())

    def read_note(self, rel: str) -> str:
        """Return the contents of a note."""
        path = self._resolve(rel, must_exist=True)
        return path.read_text(encoding="utf-8")

    def write_note(self, rel: str, content: str) -> str:
        """Create or overwrite a note. Returns its vault-relative path."""
        path = self._resolve(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        logger.info("Wrote Obsidian note %s (%d chars)", self._rel(path), len(content))
        return self._rel(path)

    def append_note(self, rel: str, content: str) -> str:
        """Append to a note (creating it if absent). Returns its relative path."""
        path = self._resolve(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = path.read_text(encoding="utf-8") if path.is_file() else ""
        sep = "" if not existing or existing.endswith("\n") else "\n"
        path.write_text(existing + sep + content, encoding="utf-8")
        return self._rel(path)

    def delete_note(self, rel: str) -> None:
        """Delete a note."""
        path = self._resolve(rel, must_exist=True)
        path.unlink()

    def search(self, query: str, limit: int = 20) -> list[dict[str, str]]:
        """Return notes whose name or body contains ``query`` (case-insensitive)."""
        if not query.strip():
            return []
        needle = query.lower()
        hits: list[dict[str, str]] = []
        for rel in self.list_notes():
            try:
                body = self.read_note(rel)
            except ObsidianError:  # pragma: no cover - race: deleted mid-scan
                continue
            if needle in rel.lower() or needle in body.lower():
                snippet = next(
                    (line.strip() for line in body.splitlines() if needle in line.lower()),
                    "",
                )
                hits.append({"path": rel, "snippet": snippet[:200]})
            if len(hits) >= limit:
                break
        return hits
