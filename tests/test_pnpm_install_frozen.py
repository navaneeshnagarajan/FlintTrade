"""Node install-path gate (sub-spec §5.2 / §13.6): every CI/infra node install is frozen.

Companion to test_no_unhashed_pip_install.py. Scans CI workflows, the Dockerfile,
infra/scripts shell, the web installers and the desktop bootstrap resources for node
dependency installs and asserts:

  * every `pnpm install` is `--frozen-lockfile`
  * no bare `npm install` / `npm ci` of workspace deps survives the pnpm migration
    (corepack bootstrap lines are exempt)

Also asserts the workspace lockfile + config landed: pnpm-lock.yaml, pnpm-workspace.yaml
(strictPeerDependencies, since pnpm 10 no longer reads settings from .npmrc), and a
sha512-pinned packageManager field.

Finally it polices what may live in a ``.npmrc``: the settings that decide what ends
up in ``node_modules`` — or which pnpm runs — belong in ``pnpm-workspace.yaml`` alone.
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
# so quoted literals must still be scanned. Covers `-c` (POSIX shells), `/c`
# (cmd's slash spelling) and `-Command` (powershell/pwsh) alike.
_EVALUATOR_RE = re.compile(
    r"\b(?:eval|iex|Invoke-Expression)\b|\b(?:bash|sh|pwsh|powershell|cmd)\b[^\n]*?\s(?:[-/]c\b|-Command\b)",
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
def test_strict_peer_deps_declared_where_pnpm_will_read_it() -> None:
    """Strict peer resolution must be declared in ``pnpm-workspace.yaml``.

    This used to assert ``.npmrc`` as well, because pnpm 9 read
    ``strict-peer-dependencies`` from there. pnpm 10 reads only auth and
    registry keys out of ``.npmrc`` and takes every other setting from
    ``pnpm-workspace.yaml``, so the 9.15.0 -> 10.34.5 bump deleted ``.npmrc``
    and the YAML is now the sole source. Asserting the deleted file would fail;
    asserting neither would let the setting be dropped silently.
    """
    assert not (_REPO_ROOT / ".npmrc").exists(), (
        ".npmrc is back: pnpm 10 ignores its settings, so a setting parked there is a setting "
        "that silently does nothing. Put it in pnpm-workspace.yaml instead."
    )
    workspace = (_REPO_ROOT / "pnpm-workspace.yaml").read_text(encoding="utf-8")
    assert "strictPeerDependencies: true" in workspace, (
        "pnpm-workspace.yaml lost strictPeerDependencies (pnpm 10+ reads this)"
    )
    # The other half of the same policy. Asserting only the strict flag would let the
    # opposite behaviour return through autoInstallPeers, which silently materialises
    # missing peers instead of failing the install.
    assert "autoInstallPeers: false" in workspace, (
        "pnpm-workspace.yaml lost autoInstallPeers: false (peers must be declared, not conjured)"
    )


# Settings that decide what ends up in ``node_modules``, or which pnpm runs. Every one
# of these is owned by ``pnpm-workspace.yaml``; pnpm 10 does not take any of them from
# a ``.npmrc``, so one parked there is either inert or — worse — a contradiction that
# reads as policy. Written in npm's kebab spelling; the camelCase spelling that
# pnpm-workspace.yaml uses is normalised onto it before the comparison.
#
# Deliberately NOT listed: `audit`, `fund`, `loglevel` and friends. npm genuinely still
# reads those from a project .npmrc, they only affect console output, and they cannot
# alter a resolved tree. packages/apps/site/.npmrc keeps three of them for that reason.
_RESOLUTION_SETTINGS = frozenset(
    {
        # Peer resolution. `legacy-peer-deps` is the one that bit us: it is npm-only —
        # pnpm has no such setting at any version — and it means "ignore
        # peerDependencies entirely", the exact inverse of strictPeerDependencies: true.
        # It sat in packages/apps/terminal/.npmrc reading like enforced policy while
        # pnpm, the only installer this repo uses, had never once honoured it.
        "legacy-peer-deps",
        "strict-peer-dependencies",
        "auto-install-peers",
        "dedupe-peer-dependents",
        "resolve-peers-from-workspace-root",
        # Layout and store.
        "node-linker",
        "shamefully-hoist",
        "hoist",
        "hoist-pattern",
        "public-hoist-pattern",
        "package-import-method",
        "verify-store-integrity",
        # Version selection and the lockfile.
        "save-exact",
        "resolution-mode",
        "frozen-lockfile",
        "prefer-frozen-lockfile",
        "shared-workspace-lockfile",
        "link-workspace-packages",
        "prefer-workspace-packages",
        "overrides",
        "audit-level",
        # Which pnpm runs, and what it is allowed to execute.
        "manage-package-manager-versions",
        "package-manager-strict-version",
        "only-built-dependencies",
        "ignore-dep-scripts",
        "enable-pre-post-scripts",
    }
)

_PRUNED_DIRS = {"node_modules", ".git", ".local", "dist", "build", ".venv", "target"}


def _iter_npmrc_files():
    """Yield every ``.npmrc`` in the working tree, skipping vendored trees."""
    stack = [_REPO_ROOT]
    while stack:
        current = stack.pop()
        for entry in current.iterdir():
            if entry.is_dir():
                if entry.name not in _PRUNED_DIRS:
                    stack.append(entry)
            elif entry.name == ".npmrc":
                yield entry


def _declared_keys(text: str) -> list[str]:
    """Return the setting keys an ``.npmrc`` body declares, in npm's kebab spelling.

    Args:
        text: The file contents.

    Returns:
        Lower-cased, kebab-spelled keys; comments, blank lines and ``[section]``
        headers are skipped.
    """
    keys: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith((";", "#", "[")) or "=" not in stripped:
            continue
        raw = stripped.split("=", 1)[0].strip()
        # `camelCase` -> `kebab-case`, so `autoInstallPeers` and `auto-install-peers`
        # are the same key to this check.
        keys.append(re.sub(r"(?<=[a-z0-9])([A-Z])", r"-\1", raw).lower())
    return keys


@pytest.mark.unit
def test_no_npmrc_declares_a_setting_pnpm_takes_from_the_workspace_yaml() -> None:
    """A resolution setting in ``.npmrc`` is inert at best and a lie at worst.

    pnpm 10 has no ``legacy-peer-deps`` at all, and takes its resolution, store and
    self-management settings from ``pnpm-workspace.yaml``. npm reads ``.npmrc``, but
    this repo never installs workspace dependencies with npm — ``pnpm install
    --frozen-lockfile`` is the only blessed form, and the test above enforces it.
    """
    violations: list[str] = []
    for path in _iter_npmrc_files():
        rel = path.relative_to(_REPO_ROOT).as_posix()
        for key in _declared_keys(path.read_text(encoding="utf-8")):
            if key in _RESOLUTION_SETTINGS:
                violations.append(f"{rel}: {key}")
    assert not violations, (
        "These .npmrc settings govern dependency resolution, the store or the pnpm pin. "
        "pnpm 10 reads them from pnpm-workspace.yaml, not .npmrc, so they do nothing "
        "where they are — move them:\n" + "\n".join(violations)
    )


@pytest.mark.unit
def test_the_terminal_npmrc_stays_deleted() -> None:
    """``packages/apps/terminal/.npmrc`` held exactly one line: ``legacy-peer-deps=true``.

    Nothing read it. pnpm never had the setting; npm has it but never installs this
    workspace. What it did do was contradict ``strictPeerDependencies: true`` in
    ``pnpm-workspace.yaml`` for anyone who opened the file, so it was deleted rather
    than migrated.
    """
    assert not (_REPO_ROOT / "packages/apps/terminal/.npmrc").exists(), (
        "packages/apps/terminal/.npmrc is back. pnpm 10 does not read package-level "
        "settings from it, and its only setting (legacy-peer-deps) is npm-only and "
        "contradicts pnpm-workspace.yaml's strictPeerDependencies: true."
    )


@pytest.mark.unit
def test_package_manager_pinned_with_sha512() -> None:
    pkg = json.loads((_REPO_ROOT / "package.json").read_text(encoding="utf-8"))
    pm = pkg.get("packageManager", "")
    assert pm.startswith("pnpm@"), f"packageManager not pinned to pnpm: {pm!r}"
    assert re.fullmatch(r"pnpm@\d+\.\d+\.\d+\+sha512\.[0-9a-f]{128}", pm), (
        "packageManager missing canonical sha512 integrity (Security H13)"
    )
