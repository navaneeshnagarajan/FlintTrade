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
    "Makefile",
    "infra/**/*.sh",
    "scripts/**/*.sh",
    # PowerShell installers are a first-class install path (the Windows one-liner is
    # `irm https://flinttrade.vercel.app/web-install.ps1 | iex`), so an unhashed
    # `pip install -r requirements.txt` there is exactly as dangerous as in shell.
    "scripts/**/*.ps1",
)

# A line that installs from a requirements file.
_INSTALL_RE = re.compile(r"\b(pip3?|uv pip)\s+install\b")
_REQ_FILE_RE = re.compile(r"requirements(\.lock|[\w.-]*\.txt)")

# A line that hands a string to an evaluator: there the quoted text *is* the command,
# so its quoted literals must still be scanned.
_EVALUATOR_RE = re.compile(
    r"\b(?:eval|iex|Invoke-Expression)\b|\b(?:bash|sh|pwsh|powershell|cmd)\b[^\n]*?\s-c\b",
    re.IGNORECASE,
)
_QUOTED_RE = re.compile(r"(['\"])(?:\\.|(?!\1).)*\1")


def _executable_text(line: str) -> str:
    """Blank quoted literals so a diagnostic that merely names a command is not flagged.

    The PowerShell installers say things like ``Fail "pip install failed."`` — a message,
    not an invocation. Lines that pass a string to an evaluator are returned untouched.

    Args:
        line: A single source line.

    Returns:
        The line with non-evaluated quoted literals blanked out.
    """
    if _EVALUATOR_RE.search(line):
        return line
    return _QUOTED_RE.sub(" ", line)


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


@pytest.mark.unit
def test_no_unhashed_pip_install() -> None:
    violations: list[str] = []
    for path in _iter_files():
        rel = path.relative_to(_REPO_ROOT).as_posix()
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            # `#` opens a comment in YAML, Make, shell and PowerShell alike.
            if stripped.startswith("#"):
                continue
            if not _INSTALL_RE.search(_executable_text(stripped)):
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


@pytest.mark.unit
def test_lock_file_is_hashed() -> None:
    """requirements.lock must actually carry --hash entries."""
    lock = (_REPO_ROOT / "requirements.lock").read_text(encoding="utf-8")
    assert "--hash=sha256:" in lock


@pytest.mark.unit
def test_install_paths_sync_uv_for_repo_local_broker_sdk_pins() -> None:
    """Install scripts must sync uv.lock so git-pinned broker SDKs reach .venv."""
    expected = {
        "infra/scripts/setup.sh": "uv sync --frozen --all-packages",
        "infra/install/update.sh": "uv sync --frozen --all-packages --no-dev",
        "infra/install/install-native.sh": "uv sync --frozen --all-packages --no-dev",
    }
    missing = [
        f"{path}: missing {snippet!r}"
        for path, snippet in expected.items()
        if snippet not in (_REPO_ROOT / path).read_text(encoding="utf-8")
    ]

    assert not missing, "Install paths must sync uv.lock broker SDK pins:\n" + "\n".join(missing)


@pytest.mark.unit
@pytest.mark.parametrize(
    "workflow", [".github/workflows/test.yml", ".github/workflows/nightly-cross-platform.yml"]
)
def test_ci_uses_frozen_sync(workflow: str) -> None:
    text = (_REPO_ROOT / workflow).read_text(encoding="utf-8")
    assert "uv sync --frozen" in text
