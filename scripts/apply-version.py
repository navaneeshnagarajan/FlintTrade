#!/usr/bin/env python3
"""Propagate a new release version across every publishable surface.

The repository's release contract spans ~25 files (see
``scripts/check-version-consistency.py``). release-please bumps the canonical
root ``package.json`` and ``changelog.md``; this script propagates that version
everywhere else so the release PR lands consistent. Each edit is
already-applied tolerant and ``VERSION`` is written last, so an interrupted run
can simply be re-run. It self-verifies by running the consistency checker.

Usage:
    python scripts/apply-version.py v0.6.0-beta.2
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location(
    "check_version_consistency", ROOT / "scripts" / "check-version-consistency.py"
)
assert _spec is not None and _spec.loader is not None
_checker = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_checker)

TAG_RE = re.compile(r"^v\d+\.\d+\.\d+(?:-[0-9A-Za-z][0-9A-Za-z.-]*)?$")

CARGO_LOCKS = (
    ("packages/apps/desktop/src-tauri/Cargo.lock", "flinttrade-desktop"),
    ("packages/core/ticks/Cargo.lock", "tick-engine"),
)


def _replace_once(path: Path, pattern: str, replacement: str, already: str) -> None:
    """Apply one anchored substitution; tolerate an edit that already happened."""
    text = path.read_text(encoding="utf-8")
    new_text, count = re.subn(pattern, replacement, text, count=1, flags=re.MULTILINE)
    if count == 1:
        path.write_text(new_text, encoding="utf-8")
        return
    if already in text:
        return
    raise SystemExit(f"apply-version: no match for {pattern!r} in {path.relative_to(ROOT)}")


def _replace_all_tags(path: Path, old_tag: str, new_tag: str) -> None:
    """Replace both tag (v-prefixed) and bare mentions of the old version."""
    text = path.read_text(encoding="utf-8")
    updated = text.replace(old_tag, new_tag).replace(
        old_tag.removeprefix("v"), new_tag.removeprefix("v")
    )
    if updated != text:
        path.write_text(updated, encoding="utf-8")


def _changelog_section(bare: str) -> str:
    """Extract the released section for *bare* from changelog.md, if present."""
    text = (ROOT / "changelog.md").read_text(encoding="utf-8")
    match = re.search(
        rf"^## \[{re.escape(bare)}\][^\n]*\n(.*?)(?=^## \[|\Z)", text, re.MULTILINE | re.DOTALL
    )
    return match.group(1).strip() if match else ""


def main() -> int:
    if len(sys.argv) != 2 or not TAG_RE.match(sys.argv[1]):
        print(__doc__)
        return 2
    new_tag = sys.argv[1]
    new_bare = new_tag.removeprefix("v")
    old_tag = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    old_bare = old_tag.removeprefix("v")

    if old_tag != new_tag:
        _replace_once(
            ROOT / "flint.toml",
            rf'^version = "{re.escape(old_tag)}"$',
            f'version = "{new_tag}"',
            already=f'version = "{new_tag}"',
        )

        for rel in _checker.PACKAGE_JSONS:
            _replace_once(
                ROOT / rel,
                rf'^(\s*)"version": "{re.escape(old_bare)}"',
                rf'\1"version": "{new_bare}"',
                already=f'"version": "{new_bare}"',
            )

        for path in sorted((ROOT / "packages").glob("*/*/pyproject.toml")):
            _replace_once(
                path,
                rf'^version = "{re.escape(old_bare)}"$',
                f'version = "{new_bare}"',
                already=f'version = "{new_bare}"',
            )

        _replace_once(
            ROOT / "packages/apps/desktop/src-tauri/tauri.conf.json",
            rf'^(\s*)"version": "{re.escape(old_bare)}"',
            rf'\1"version": "{new_bare}"',
            already=f'"version": "{new_bare}"',
        )

        for rel in _checker.CARGO_MANIFESTS:
            _replace_once(
                ROOT / rel,
                rf'^version = "{re.escape(old_bare)}"$',
                f'version = "{new_bare}"',
                already=f'version = "{new_bare}"',
            )
        # Keep the committed lockfiles in step so --locked builds stay green.
        for lock, crate in CARGO_LOCKS:
            _replace_once(
                ROOT / lock,
                rf'^(name = "{crate}"\n)version = "{re.escape(old_bare)}"$',
                rf'\1version = "{new_bare}"',
                already=f'name = "{crate}"\nversion = "{new_bare}"',
            )

        _replace_once(
            ROOT / "packages/core/ticks/python/tick_engine/__init__.py",
            rf'^__version__ = "{re.escape(old_bare)}"$',
            f'__version__ = "{new_bare}"',
            already=f'__version__ = "{new_bare}"',
        )

        for rel in _checker.CURRENT_TAG_FILES:
            _replace_all_tags(ROOT / rel, old_tag, new_tag)

        # Last, so an interrupted run keeps the old tag and can be re-run.
        (ROOT / "VERSION").write_text(f"{new_tag}\n", encoding="utf-8")

    # Release note: create from the changelog section (release-please writes it
    # before this script runs in the release PR), or a stub the maintainer edits.
    note = ROOT / f"docs/releases/{new_tag}.md"
    if not note.exists():
        body = _changelog_section(new_bare) or "_Release notes pending._"
        # The stability disclaimer is part of the release contract:
        # tests/test_restructure_goals.py pins "not production ready" in every
        # current release note while the project is pre-1.0.
        disclaimer = (
            f"FlintTrade `{new_tag}` is a beta prerelease. It is not production ready; "
            "use Explore and Practice modes before connecting any live broker workflow.\n"
        )
        note.write_text(f"# FlintTrade {new_tag}\n\n{disclaimer}\n{body}\n", encoding="utf-8")

    generator = ROOT / "packages/apps/site/scripts/generate-content.mjs"
    gen_text = generator.read_text(encoding="utf-8")
    if f"docs/releases/{new_tag}.md" not in gen_text:
        entry = (
            f"  ['docs/releases/{new_tag}.md', 'releases/{new_tag}', 'Releases', "
            f"'FlintTrade {new_tag} release notes'],\n"
        )
        gen_text, count = re.subn(
            r"^const releaseDocs = \[\n", f"const releaseDocs = [\n{entry}", gen_text, count=1, flags=re.MULTILINE
        )
        if count != 1:
            raise SystemExit("apply-version: could not find releaseDocs in generate-content.mjs")
        generator.write_text(gen_text, encoding="utf-8")

    result = subprocess.run([sys.executable, str(ROOT / "scripts/check-version-consistency.py")], check=False)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
