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
    ROOT / "packages" / "core" / "core" / "src" / "flinttrade_core" / "app.py",
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
    """Current architecture surfaces must not advertise the removed backend."""
    hits: list[str] = []
    for path in _ACTIVE_ARCHITECTURE_SURFACES:
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if "chromadb" in line.lower():
                hits.append(f"{path.relative_to(ROOT)}:{line_number}")
    assert hits == [], "active architecture text still advertises chromadb: " + ", ".join(hits)
