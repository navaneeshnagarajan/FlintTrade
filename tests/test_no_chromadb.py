"""Guard: chromadb must not remain on any Python dependency surface."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_CHROMADB_TOKEN = re.compile(r"(?i)(?:^|[\s\"'=\[,])chromadb(?:$|[\s\"'=<>~\],])")

_MANIFESTS = (
    ROOT / "packages" / "services" / "ai" / "pyproject.toml",
    ROOT / "requirements.txt",
    ROOT / "uv.lock",
    ROOT / "requirements.lock",
)

_ACTIVE_ARCHITECTURE_SURFACES = (
    ROOT / "readme.md",
    ROOT / "CLAUDE.md",
    ROOT / "packages" / "services" / "ai" / "README.md",
    ROOT / "packages" / "core" / "core" / "src" / "flinttrade_core" / "app.py",
    ROOT / ".env.example",
    ROOT / "templates" / "package-purposes.yml",
    ROOT / "docs" / "USER_GUIDE.md",
)


def test_chromadb_is_absent_from_python_dependency_surfaces() -> None:
    """Fail if chromadb remains in manifests, locks, or requirements."""
    hits: list[str] = []
    for path in _MANIFESTS:
        text = path.read_text(encoding="utf-8")
        if _CHROMADB_TOKEN.search(text):
            hits.append(str(path.relative_to(ROOT)))
    assert hits == [], "chromadb must not remain in: " + ", ".join(hits)


def test_active_architecture_docs_describe_the_local_vector_store() -> None:
    """Current architecture and env surfaces must not advertise the removed backend.

    Migration notes in changelog.md may still name legacy ``chroma.sqlite3``;
    that file is covered by ``test_legacy_vector_upgrade_policy_is_documented``
    and is intentionally not listed here.
    """
    hits: list[str] = []
    for path in _ACTIVE_ARCHITECTURE_SURFACES:
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if "chroma" in line.lower():
                hits.append(f"{path.relative_to(ROOT)}:{line_number}")
    assert hits == [], "active architecture text still advertises chroma: " + ", ".join(hits)


def test_legacy_vector_upgrade_policy_is_documented() -> None:
    """Operators must be warned that legacy vectors are preserved but not auto-migrated."""
    changelog = (ROOT / "changelog.md").read_text(encoding="utf-8").lower()

    assert "chroma.sqlite3" in changelog
    assert "flinttrade_vectors.sqlite" in changelog
    assert "left untouched" in changelog
    assert "refuses" in changelog
