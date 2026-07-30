#!/usr/bin/env python3
"""Propagate a new public site URL across every tracked surface that spells it.

The literal domain has to stay in the docs — a reader runs ``curl … | bash``
before cloning, so nothing can be resolved from ``flint.toml`` at read time.
That makes a domain move a rewrite problem, not an abstraction problem: this
script is the site-URL twin of ``scripts/apply-version.py``. It updates the
single authority (``flint.toml``'s ``[project] site_url``), rewrites every file
in ``scripts/check-site-url-consistency.py``'s ``SITE_URL_FILES``, reports what
changed, and self-verifies by running that checker.

The rewrite targets the *host*, so it catches both shapes in one pass: a full
``https://host/route`` URL, and the bare host some surfaces name on its own (an
allowlist key, a redirect host).

``flint.toml`` is written last, so an interrupted run leaves the authority still
naming the old host and re-running the same command finishes the job. That is a
convenience, not a transactional guarantee: files are rewritten one at a time
with no rollback, so a run interrupted midway leaves a mixed tree until it is
repeated. Run ``scripts/check-site-url-consistency.py`` afterwards — it names
every file that still disagrees.
``tests/test_site_url_single_source.py`` holds the same invariant in CI.

Regenerate the public site afterwards so the generated MDX picks up the doc
edits:

    npx --yes pnpm@10.34.5 --dir packages/apps/site run generate:content

Usage:
    python scripts/apply-site-url.py https://flinttrade.dev
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location(
    "check_site_url_consistency", ROOT / "scripts" / "check-site-url-consistency.py"
)
assert _spec is not None and _spec.loader is not None
_checker = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_checker)


def _rewrite(path: Path, old_url: str, new_url: str) -> int:
    """Rewrite every mention of *old_url* (and its bare host) in one file.

    Args:
        path: File to rewrite in place.
        old_url: The previous canonical origin, e.g. ``https://old.example``.
        new_url: The new canonical origin.

    Returns:
        The number of replacements made; ``0`` when the file was already current.
    """
    # newline="" on both ends: the repository is LF-only (.gitattributes says
    # `* text=auto eol=lf`), and Python's default newline translation would
    # rewrite every line of every touched file to CRLF on a Windows checkout.
    with path.open(encoding="utf-8", newline="") as handle:
        text = handle.read()
    # Rewriting the host alone covers both shapes in one pass — `https://host/x`
    # and a bare `host` — and cannot double-apply when the new host contains the
    # old one as a substring.
    old_host = _checker.site_host(old_url)
    new_host = _checker.site_host(new_url)
    replacements = text.count(old_host)
    updated = text.replace(old_host, new_host)
    if updated != text:
        with path.open("w", encoding="utf-8", newline="") as handle:
            handle.write(updated)
    return replacements


def main() -> int:
    """Rewrite the site URL everywhere and return a shell exit code."""
    if len(sys.argv) != 2 or not _checker.SITE_URL_PATTERN.match(sys.argv[1]):
        print(__doc__)
        return 2
    new_url = sys.argv[1]
    old_url = _checker.read_site_url(ROOT)

    if old_url == new_url:
        print(f"apply-site-url: flint.toml already declares {new_url}; re-checking every surface")
    else:
        total = 0
        for rel in _checker.SITE_URL_FILES:
            path = ROOT / rel
            if not path.is_file():
                raise SystemExit(f"apply-site-url: listed file is missing: {rel}")
            count = _rewrite(path, old_url, new_url)
            total += count
            print(f"  {rel}: {count} replacement(s)" if count else f"  {rel}: already current")

        # Last, so an interrupted run keeps the old URL and can simply be re-run.
        authority = ROOT / _checker.SITE_URL_AUTHORITY
        if _rewrite(authority, old_url, new_url) == 0:
            raise SystemExit(
                f"apply-site-url: no {old_url} to replace in {_checker.SITE_URL_AUTHORITY}"
            )
        print(f"\napply-site-url: {old_url} -> {new_url} ({total} replacement(s) across "
              f"{len(_checker.SITE_URL_FILES)} file(s), plus {_checker.SITE_URL_AUTHORITY})")
        print(
            "Regenerate the site content so the published docs follow: "
            "npx --yes pnpm@10.34.5 --dir packages/apps/site run generate:content"
        )

    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/check-site-url-consistency.py")], check=False
    )
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
