"""Guard: shebang and git executable bit agree for every linted Python file.

ruff's ``EXE`` family (adopted 2026-07-30) reads the file's permission bits, so
``EXE001`` ("shebang is present but file is not executable") and ``EXE002``
("file is executable but no shebang is present") can only fire where those bits
exist.  On Windows there is no exec bit, so ruff skips both rules entirely: a
Windows contributor can add ``#!/usr/bin/env python3`` to a file tracked at mode
100644, watch ``python scripts/ft.py lint`` go green locally, and only discover
the breakage when the Ubuntu ``python-tests`` job fails.  That is precisely how
``packages/apps/desktop/resources/bootstrap/flinttrade-safe-rmtree.py`` reached
``main``.

This meta-test reconstructs the ruff lint roots from the CI workflow (the same
``packages/`` and ``tests/`` arguments ``scripts/ft.py lint`` passes) and reads
the recorded modes straight out of the git index, so it reports the identical
verdict on every platform.

Scope note: ``scripts/**`` is deliberately NOT covered by the strict direction.
Roughly thirty helpers there carry a shebang at mode 100644, and they are
outside the ruff lint path — the documented entry point is
``python scripts/ft.py <cmd>``, never ``./scripts/foo.py``.  Widening the ruff
lint path to ``scripts/`` widens this guard with it, which will then fail until
those modes (or shebangs) are reconciled.  That is the intended coupling, not an
accident.
"""

from __future__ import annotations

import subprocess
from itertools import takewhile
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "test.yml"
EXECUTABLE_MODE = "100755"


def _ruff_lint_roots() -> tuple[str, ...]:
    """Return the repo-relative directories CI hands to ``ruff check``."""
    for line in WORKFLOW.read_text(encoding="utf-8").splitlines():
        if "uv run ruff check" not in line or line.lstrip().startswith("#"):
            continue
        arguments = line.split("uv run ruff check", 1)[1].split()
        roots = tuple(token.rstrip("/") for token in takewhile(lambda t: not t.startswith("-"), arguments))
        if roots:
            return roots
    raise AssertionError(f"No `uv run ruff check` invocation found in {WORKFLOW}.")


def _tracked_python_modes() -> dict[str, str]:
    """Map every tracked ``.py`` path to the file mode recorded in the git index."""
    records = subprocess.check_output(["git", "ls-files", "-s", "-z"], cwd=ROOT, text=True).split("\0")
    modes: dict[str, str] = {}
    for record in records:
        if not record:
            continue
        metadata, _, rel_path = record.partition("\t")
        if not rel_path.endswith(".py"):
            continue
        modes[rel_path] = metadata.split()[0]
    return modes


def _has_shebang(rel_path: str) -> bool:
    path = ROOT / rel_path
    if not path.is_file():  # staged deletion, or a checkout with sparse paths
        return False
    return path.read_bytes().startswith(b"#!")


def test_ci_lints_the_roots_this_guard_covers() -> None:
    assert _ruff_lint_roots() == ("packages", "tests")


def test_linted_python_with_a_shebang_is_executable_in_the_index() -> None:
    """EXE001: a shebang inside the ruff lint path requires mode 100755."""
    roots = _ruff_lint_roots()
    offenders = sorted(
        rel_path
        for rel_path, mode in _tracked_python_modes().items()
        if rel_path.split("/")[0] in roots and mode != EXECUTABLE_MODE and _has_shebang(rel_path)
    )

    assert offenders == [], (
        "These files carry a shebang but are not mode 100755 in the git index, so ruff's EXE001 "
        "fails on Linux CI while passing on Windows. Either drop the shebang (correct when the file "
        "is only ever spawned with an explicit interpreter) or run "
        f"`git update-index --chmod=+x <path>`: {offenders}"
    )


def test_no_tracked_python_is_executable_without_a_shebang() -> None:
    """EXE002, checked repo-wide: mode 100755 without a shebang is never intended."""
    offenders = sorted(
        rel_path
        for rel_path, mode in _tracked_python_modes().items()
        if mode == EXECUTABLE_MODE and not _has_shebang(rel_path)
    )

    assert offenders == [], (
        "These files are mode 100755 in the git index but have no shebang, so direct execution "
        "would fall through to the shell. Either add a shebang or run "
        f"`git update-index --chmod=-x <path>`: {offenders}"
    )
