#!/usr/bin/env python3
"""Verify that every tracked mention of the public site URL agrees with flint.toml.

``flint.toml``'s ``[project] site_url`` is the single source of truth for the
public FlintTrade domain. The literal URL still has to appear in the docs — a
reader pastes ``curl … | bash`` *before* cloning the repository, so the domain
cannot be resolved from config at read time — which is exactly why a moved
domain used to mean a manual hunt through two dozen files.

This checker is the other half of that contract (``scripts/apply-site-url.py``
is the rewrite half). It is the site-URL sibling of
``scripts/check-version-consistency.py`` and enforces four invariants:

1. ``[project] site_url`` exists and is a bare ``https://host`` origin.
2. Every file in :data:`SITE_URL_FILES` still spells that exact URL. A file that
   drifted to an old domain no longer contains the canonical one and fails here.
3. No listed file names any other site-shaped origin. Legitimate non-site hosts
   (GitHub, nodejs.org, loopback…) are allowlisted in :data:`NON_SITE_HOSTS`, so
   a leftover ``https://old-domain.example/install.sh`` is reported by line.
4. No *unlisted* tracked file spells the canonical URL or serves one of the
   canonical install routes from another host. This keeps
   :data:`SITE_URL_FILES` complete: a new hardcoded mention must join the list,
   so the scripted rewrite can never silently miss a file. This last invariant
   needs ``git ls-files``; without git it degrades to the first three rather
   than failing a checkout that has no work tree.

Usage:
    python scripts/check-site-url-consistency.py
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Tracked sources that spell the public site URL literally. Keep this list in
# step with reality — invariant 4 above fails the check when it drifts, and
# scripts/apply-site-url.py rewrites exactly these files.
SITE_URL_FILES = [
    "docs/DESKTOP.md",
    "docs/USER_GUIDE.md",
    "docs/setup/QUICKSTART.md",
    "docs/setup/linux.md",
    "docs/setup/macos.md",
    "docs/setup/raspberry-pi.md",
    "docs/setup/windows.md",
    "infra/scripts/setup.sh",
    "packages/apps/site/src/app/api/desktop-release/route.test.ts",
    "packages/apps/site/src/app/download/page.tsx",
    "packages/apps/site/src/app/layout.tsx",
    "packages/apps/site/src/lib/desktop-copy.test.ts",
    "readme.md",
    "scripts/install/flinttrade-install.ps1",
    "scripts/install/flinttrade-install.sh",
    "scripts/install/flinttrade-uninstall.sh",
    "scripts/install/flinttrade-web-install.ps1",
    "scripts/install/flinttrade-web-install.sh",
    "tests/test_no_unhashed_pip_install.py",
    "tests/test_pnpm_install_frozen.py",
    "tests/test_web_install_scripts.py",
    "tests/test_windows_command_docs.py",
]

# flint.toml holds the canonical value itself, so it is never a "mention".
SITE_URL_AUTHORITY = "flint.toml"

# Paths the public site serves as the one-command bootstrap contract. A URL with
# one of these exact paths is a FlintTrade site URL whatever host precedes it,
# which is how a stale domain is recognised without knowing what it used to be.
SITE_ROUTES = (
    "/web-install.sh",
    "/web-install.ps1",
    "/install.sh",
    "/install.ps1",
    "/uninstall.sh",
    "/uninstall.ps1",
    "/download",
    "/api/desktop-release",
)

# Routes distinctive enough to identify a stale FlintTrade domain on sight. A
# foreign host serving one of these is almost certainly an un-rewritten old
# domain; a foreign host serving "/download" is almost certainly somebody else's
# download page, so that route is deliberately excluded here even though it is a
# real route of ours. Detection value without the false positives.
IDENTIFYING_ROUTES = frozenset(
    {
        "/web-install.sh",
        "/web-install.ps1",
        "/install.sh",
        "/install.ps1",
        "/uninstall.sh",
        "/uninstall.ps1",
        "/api/desktop-release",
    }
)

# Hosts that legitimately appear alongside the site URL in the listed files.
# Anything else spelled there is treated as a competing site origin.
NON_SITE_HOSTS = frozenset(
    {
        "127.0.0.1",
        "::1",
        "api.github.com",
        "codeload.github.com",
        "git-scm.com",
        "github.com",
        "localhost",
        "nodejs.org",
        "python.org",
        "raw.githubusercontent.com",
        "registry.npmjs.org",
    }
)

TEXT_SUFFIXES = frozenset(
    {
        ".cjs",
        ".css",
        ".html",
        ".js",
        ".json",
        ".jsx",
        ".md",
        ".mdx",
        ".mjs",
        ".ps1",
        ".psm1",
        ".py",
        ".sh",
        ".toml",
        ".ts",
        ".tsx",
        ".txt",
        ".yaml",
        ".yml",
    }
)

# A bare https origin: scheme + host, no path, no query, no trailing slash.
SITE_URL_PATTERN = re.compile(r"^https://[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?(?::\d{1,5})?$")

# Any URL in running text, including its path, stopping at shell/markup punctuation.
_URL_RE = re.compile(r"https?://([A-Za-z0-9._:-]*)((?:/[^\s'\"`)\]}>,;|\\]*)?)")


def read_site_url(root: Path = ROOT) -> str:
    """Return the canonical public site URL declared in flint.toml.

    Args:
        root: Repository root to read ``flint.toml`` from.

    Returns:
        The bare ``https://host`` origin, without a trailing slash.

    Raises:
        SystemExit: If the key is missing or is not a bare https origin.
    """
    with (root / SITE_URL_AUTHORITY).open("rb") as handle:
        data = tomllib.load(handle)
    project = data.get("project")
    site_url = project.get("site_url") if isinstance(project, dict) else None
    if not isinstance(site_url, str) or not SITE_URL_PATTERN.match(site_url):
        raise SystemExit(
            f"{SITE_URL_AUTHORITY} [project] site_url must be a bare https origin "
            f'(e.g. "https://example.dev"), got {site_url!r}'
        )
    return site_url


def site_host(site_url: str) -> str:
    """Return the host portion of *site_url* (scheme stripped)."""
    return site_url.split("://", 1)[1]


def tracked_text_files(root: Path = ROOT) -> tuple[str, ...]:
    """Return every tracked repo-relative text path, or ``()`` when git is unusable.

    Args:
        root: Repository root to enumerate.

    Returns:
        Repo-relative POSIX paths of tracked files with a scannable text suffix.
    """
    git = shutil.which("git")
    if git is None:
        return ()
    result = subprocess.run(
        [git, "ls-files", "-z"], cwd=root, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        return ()
    return tuple(
        entry
        for entry in result.stdout.split("\0")
        if entry and _is_scannable_text(root / entry)
    )


def _is_scannable_text(path: Path) -> bool:
    """Return True when *path* is a tracked text file worth scanning.

    Suffix alone is not enough: this repository tracks extensionless text files
    (``notice``, ``LICENSE``, ``VERSION``) and an allowlist of suffixes silently
    excused every one of them, which defeated the completeness invariant this
    guard exists to hold. Anything not in :data:`TEXT_SUFFIXES` is therefore
    sniffed instead of skipped — a NUL byte in the first block means binary.

    Args:
        path: Absolute path to a tracked entry.

    Returns:
        True when the file exists and reads as text.
    """
    if not path.is_file():
        return False
    if path.suffix.lower() in TEXT_SUFFIXES:
        return True
    try:
        return b"\0" not in path.read_bytes()[:8192]
    except OSError:
        return False


def foreign_site_urls(text: str, canonical_host: str) -> list[tuple[int, str]]:
    """Find URLs that serve a FlintTrade install route from the wrong host.

    A stale domain betrays itself by serving one of *our* routes — ``/install.sh``,
    ``/web-install.ps1``, ``/download`` and friends. Any other third-party link is
    none of this guard's business: an earlier revision flagged every host outside
    :data:`NON_SITE_HOSTS`, which meant adding an ordinary reference link to the
    readme or a setup page failed the build with a misleading "competing site
    origin" message.

    :data:`NON_SITE_HOSTS` is still consulted, for hosts that legitimately serve a
    path of the same shape (``github.com/.../download``, for instance).

    Args:
        text: File contents to scan.
        canonical_host: The host declared in flint.toml.

    Returns:
        ``(line_number, matched_url)`` pairs, in file order.
    """
    found: list[tuple[int, str]] = []
    for match in _URL_RE.finditer(text):
        # Trailing sentence punctuation is not part of the host ("…vercel.app.").
        host = match.group(1).rstrip(".:-")
        path = match.group(2)
        bare_host = host.split(":", 1)[0]
        if not bare_host or bare_host == canonical_host or host == canonical_host:
            continue
        if bare_host in NON_SITE_HOSTS:
            continue
        if path.rstrip("/") not in IDENTIFYING_ROUTES:
            continue
        found.append((text.count("\n", 0, match.start()) + 1, match.group(0)))
    return found


def collect_failures(root: Path = ROOT) -> list[str]:
    """Return every site-URL disagreement, one human-readable line each.

    Args:
        root: Repository root to check.

    Returns:
        Failure descriptions naming the file (and line, where a stale literal was
        located). An empty list means every tracked surface agrees with flint.toml.
    """
    site_url = read_site_url(root)
    canonical_host = site_host(site_url)
    failures: list[str] = []
    listed = set(SITE_URL_FILES)

    for rel in SITE_URL_FILES:
        path = root / rel
        if not path.is_file():
            failures.append(f"{rel}: listed in SITE_URL_FILES but missing from the repository")
            continue
        text = path.read_text(encoding="utf-8")
        if site_url not in text:
            failures.append(f"{rel}: does not mention the canonical site URL {site_url}")
        for line, url in foreign_site_urls(text, canonical_host):
            failures.append(f"{rel}:{line}: serves a canonical install route from {url} (expected {site_url})")

    for rel in tracked_text_files(root):
        if rel in listed or rel == SITE_URL_AUTHORITY:
            continue
        text = (root / rel).read_text(encoding="utf-8", errors="ignore")
        if site_url in text:
            line = text.count("\n", 0, text.index(site_url)) + 1
            failures.append(
                f"{rel}:{line}: spells the site URL but is absent from SITE_URL_FILES "
                "(add it, or the scripted rewrite will skip this file)"
            )
        for line, url in foreign_site_urls(text, canonical_host):
            failures.append(f"{rel}:{line}: serves a canonical install route from {url} (expected {site_url})")

    return failures


def main() -> int:
    """Print every disagreement and return a shell exit code."""
    site_url = read_site_url()
    failures = collect_failures()
    if failures:
        print("Site URL consistency check failed:")
        for failure in failures:
            print(f"  - {failure}")
        print(
            "\nFor a domain move, run: python scripts/apply-site-url.py <new-url>"
            f"\nOtherwise correct the file(s) above to {site_url} — re-running the apply "
            "script with the URL already in flint.toml cannot repair a hand-edited file."
        )
        return 1
    print(f"Site URL consistency check passed for {site_url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
