"""Node install-path gate (sub-spec §5.2 / §13.6): every CI/infra node install is frozen.

Companion to test_no_unhashed_pip_install.py. Scans CI workflows, the Dockerfile, and
infra/scripts shell for node dependency installs and asserts:

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

_REPO_ROOT = Path(__file__).resolve().parents[1]

_SCAN_GLOBS = (
    ".github/workflows/*.yml",
    ".github/workflows/*.yaml",
    "Dockerfile",
    "infra/**/*.sh",
    "scripts/**/*.sh",
)

_PNPM_INSTALL_RE = re.compile(r"\bpnpm\s+install\b")
_NPM_INSTALL_RE = re.compile(r"\bnpm\s+(install|ci)\b")


def _iter_files():
    for pattern in _SCAN_GLOBS:
        if "*" in pattern:
            yield from _REPO_ROOT.glob(pattern)
        else:
            p = _REPO_ROOT / pattern
            if p.exists():
                yield p


def test_pnpm_installs_are_frozen() -> None:
    violations: list[str] = []
    for path in _iter_files():
        rel = path.relative_to(_REPO_ROOT).as_posix()
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            s = line.strip()
            if s.startswith("#"):
                continue
            # YAML job/step labels (`name:` / `- name:`) are descriptions, not commands.
            if s.startswith("name:") or s.startswith("- name:"):
                continue
            if _PNPM_INSTALL_RE.search(s) and "--frozen-lockfile" not in s:
                # `pnpm install --frozen-lockfile` is the only blessed form
                violations.append(f"{rel}:{n}: pnpm install without --frozen-lockfile → {s}")
            if _NPM_INSTALL_RE.search(s) and "openalgo" not in s.lower():
                violations.append(f"{rel}:{n}: bare npm install/ci (use pnpm) → {s}")
    assert not violations, "Unfrozen node installs found:\n" + "\n".join(violations)


def test_pnpm_workspace_files_present() -> None:
    assert (_REPO_ROOT / "pnpm-lock.yaml").is_file(), "pnpm-lock.yaml missing at repo root"
    assert (_REPO_ROOT / "pnpm-workspace.yaml").is_file(), "pnpm-workspace.yaml missing"


def test_npmrc_strict_peer_deps() -> None:
    npmrc = (_REPO_ROOT / ".npmrc").read_text(encoding="utf-8")
    assert "strict-peer-dependencies=true" in npmrc


def test_package_manager_pinned_with_sha512() -> None:
    pkg = json.loads((_REPO_ROOT / "package.json").read_text(encoding="utf-8"))
    pm = pkg.get("packageManager", "")
    assert pm.startswith("pnpm@"), f"packageManager not pinned to pnpm: {pm!r}"
    assert "+sha512-" in pm, "packageManager missing sha512 integrity (Security H13)"
