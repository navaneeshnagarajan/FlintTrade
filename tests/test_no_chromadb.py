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


def test_chromadb_is_absent_from_python_dependency_surfaces() -> None:
    """Fail if chromadb remains in manifests, locks, or requirements."""
    hits: list[str] = []
    for path in _MANIFESTS:
        text = path.read_text(encoding="utf-8")
        if _CHROMADB_TOKEN.search(text):
            hits.append(str(path.relative_to(ROOT)))
    assert hits == [], "chromadb must not remain in: " + ", ".join(hits)
