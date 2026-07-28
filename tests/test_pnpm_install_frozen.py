"""Node install-path gate (sub-spec §5.2 / §13.6): every CI/infra node install is frozen.

Companion to test_no_unhashed_pip_install.py. Scans CI workflows, the Dockerfile,
infra/scripts shell, the web installers and the desktop bootstrap resources for node
dependency installs and asserts:

  * every `pnpm install` is `--frozen-lockfile`
  * no bare `npm install` / `npm ci` of workspace deps survives the pnpm migration
    (corepack bootstrap lines are exempt)

Also asserts the workspace lockfile + config landed: pnpm-lock.yaml, pnpm-workspace.yaml,
.npmrc (strict-peer-dependencies), and a sha512-pinned packageManager field.
"""

from __future__ import annotations

import json
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
    # PowerShell installers are a first-class install path (the Windows one-liner is
    # `irm https://flinttrade.vercel.app/web-install.ps1 | iex`), so they are held to the
    # same lockfile discipline as their POSIX siblings. `#` comments in both languages.
    "scripts/**/*.ps1",
    # The desktop bootstrap resources are where the node install ACTUALLY runs: the web
    # installers delegate, and Electron shells out to these two scripts to build the
    # managed source checkout. Scanning only the delegating installers made the
    # PowerShell/shell globs above vacuous for pnpm.
    "packages/apps/desktop/resources/**/*.sh",
    "packages/apps/desktop/resources/**/*.ps1",
)

_PNPM_INSTALL_RE = re.compile(r"\bpnpm\s+install\b")
_NPM_INSTALL_RE = re.compile(r"\bnpm\s+(install|ci)\b")

# The same install written as an argument array, which the plain forms above cannot see:
#
#     Invoke-Checked $Node @($CorepackJs, "pnpm", "install", "--frozen-lockfile")
#
# Matched against the RAW line, because `_executable_text` blanks quoted literals — and
# here the quoted literals are the command. Requiring the two words in *separate*
# adjacent literals keeps a diagnostic message ("pnpm install failed.") out of scope.
_PNPM_INSTALL_ARGV_RE = re.compile(r"""(['"])pnpm\1\s*,\s*(['"])install\2""")
_NPM_INSTALL_ARGV_RE = re.compile(r"""(['"])npm\1\s*,\s*(['"])(?:install|ci)\2""")

# A line that hands a string to an evaluator: there the quoted text *is* the command,
# so quoted literals must still be scanned.
_EVALUATOR_RE = re.compile(
    r"\b(?:eval|iex|Invoke-Expression)\b|\b(?:bash|sh|pwsh|powershell|cmd)\b[^\n]*?\s-c\b",
    re.IGNORECASE,
)
# One branch per quote style, with backslash excluded from the plain-character
# branch so it can only be consumed by the escape branch — the two alternatives
# never overlap, which keeps the scan linear (CodeQL py/redos on the previous
# backreference form: an unterminated quote full of escapes backtracked
# exponentially).
_QUOTED_RE = re.compile(r"'(?:\\.|[^\\'])*(?:\\)?'|\"(?:\\.|[^\\\"])*(?:\\)?\"")


def _executable_text(line: str) -> str:
    """Blank quoted literals so a diagnostic that merely names a command is not flagged.

    The PowerShell installers say things like ``Fail "pnpm install failed."`` — a message,
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


@pytest.mark.unit
def test_pnpm_installs_are_frozen() -> None:
    violations: list[str] = []
    for path in _iter_files():
        rel = path.relative_to(_REPO_ROOT).as_posix()
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            s = line.strip()
            # `#` opens a comment in YAML, shell and PowerShell alike.
            if s.startswith("#"):
                continue
            # YAML job/step labels (`name:` / `- name:`) are descriptions, not commands.
            if s.startswith("name:") or s.startswith("- name:"):
                continue
            command = _executable_text(s)
            if (_PNPM_INSTALL_RE.search(command) or _PNPM_INSTALL_ARGV_RE.search(s)) and (
                "--frozen-lockfile" not in s
            ):
                # `pnpm install --frozen-lockfile` is the only blessed form
                violations.append(f"{rel}:{n}: pnpm install without --frozen-lockfile → {s}")
            if (
                _NPM_INSTALL_RE.search(command) or _NPM_INSTALL_ARGV_RE.search(s)
            ) and "openalgo" not in s.lower():
                violations.append(f"{rel}:{n}: bare npm install/ci (use pnpm) → {s}")
    assert not violations, "Unfrozen node installs found:\n" + "\n".join(violations)


@pytest.mark.unit
def test_pnpm_workspace_files_present() -> None:
    assert (_REPO_ROOT / "pnpm-lock.yaml").is_file(), "pnpm-lock.yaml missing at repo root"
    assert (_REPO_ROOT / "pnpm-workspace.yaml").is_file(), "pnpm-workspace.yaml missing"


@pytest.mark.unit
def test_npmrc_strict_peer_deps() -> None:
    npmrc = (_REPO_ROOT / ".npmrc").read_text(encoding="utf-8")
    assert "strict-peer-dependencies=true" in npmrc


@pytest.mark.unit
def test_package_manager_pinned_with_sha512() -> None:
    pkg = json.loads((_REPO_ROOT / "package.json").read_text(encoding="utf-8"))
    pm = pkg.get("packageManager", "")
    assert pm.startswith("pnpm@"), f"packageManager not pinned to pnpm: {pm!r}"
    assert re.fullmatch(r"pnpm@\d+\.\d+\.\d+\+sha512\.[0-9a-f]{128}", pm), (
        "packageManager missing canonical sha512 integrity (Security H13)"
    )
