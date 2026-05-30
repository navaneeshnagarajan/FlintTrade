"""SC-07 / supply-chain §2.3 gate: every FlintTrade install path is hash-verified.

Scans CI workflows, the Dockerfile, and infra shell scripts for dependency
installs that pull an unhashed ``requirements.txt`` or run ``pip install`` /
``uv pip install`` without ``--require-hashes``. The only blessed forms are:

  * ``uv sync --frozen``                                  (uv.lock is hashed)
  * ``pip install --require-hashes -r requirements.lock`` (pip, hashed)
  * ``uv pip install --require-hashes -r requirements.lock``

OpenAlgo's own external requirements.txt (we don't control its hashing) is
exempt — those lines reference the OpenAlgo install dir.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]

_SCAN_GLOBS = (
    ".github/workflows/*.yml",
    ".github/workflows/*.yaml",
    "Dockerfile",
    "infra/**/*.sh",
    "scripts/**/*.sh",
)

# A line that installs from a requirements file.
_INSTALL_RE = re.compile(r"\b(pip3?|uv pip)\s+install\b")
_REQ_FILE_RE = re.compile(r"requirements(\.lock|[\w.-]*\.txt)")


def _iter_files():
    for pattern in _SCAN_GLOBS:
        if "*" in pattern:
            yield from _REPO_ROOT.glob(pattern)
        else:
            p = _REPO_ROOT / pattern
            if p.exists():
                yield p


def _is_external_openalgo(line: str) -> bool:
    return "openalgo" in line.lower()


def test_no_unhashed_pip_install() -> None:
    violations: list[str] = []
    for path in _iter_files():
        rel = path.relative_to(_REPO_ROOT).as_posix()
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if not _INSTALL_RE.search(stripped):
                continue
            if _is_external_openalgo(stripped):
                continue  # OpenAlgo's own deps — out of our control
            references_req = bool(_REQ_FILE_RE.search(stripped)) or "-r " in stripped
            if not references_req:
                continue  # e.g. `pip install --upgrade pip setuptools wheel`
            # An install that touches a requirements file MUST be hash-verified.
            if "--require-hashes" in stripped:
                continue
            if "requirements.txt" in stripped:
                violations.append(f"{rel}:{n}: unhashed requirements.txt install → {stripped}")
            else:
                violations.append(f"{rel}:{n}: install without --require-hashes → {stripped}")

    assert not violations, "Unhashed install paths found (SC-07):\n" + "\n".join(violations)


def test_lock_file_is_hashed() -> None:
    """requirements.lock must actually carry --hash entries."""
    lock = (_REPO_ROOT / "requirements.lock").read_text(encoding="utf-8")
    assert "--hash=sha256:" in lock


@pytest.mark.parametrize(
    "workflow", [".github/workflows/test.yml", ".github/workflows/nightly-cross-platform.yml"]
)
def test_ci_uses_frozen_sync(workflow) -> None:
    text = (_REPO_ROOT / workflow).read_text(encoding="utf-8")
    assert "uv sync --frozen" in text
