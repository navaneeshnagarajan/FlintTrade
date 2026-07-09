"""Guard: every terminal vitest test file must run in a CI shard.

CI splits the terminal's vitest suite across hand-listed path arguments in
``.github/workflows/test.yml`` (node-core + node-widget-tests-1/2a/2b/3). A test
file whose path is not under any of those prefixes runs in NO CI job — it passes
locally and silently never runs on push, which is exactly how a broken
safety-relevant suite (orders/account) or a mock-shape-drift test can rot
unnoticed.

This meta-test reconstructs the shard coverage from test.yml and fails, listing
the offenders, if any ``*.test.ts(x)`` under the terminal ``src/`` tree is
uncovered. Genuinely-excluded suites (e.g. TradeIdea, which OOMs the runner) are
allowlisted here WITH a reason, so an exclusion is a deliberate, reviewed choice
rather than an accident.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "test.yml"
TERMINAL_SRC = ROOT / "packages" / "apps" / "terminal" / "src"

# Suites deliberately excluded from CI, each with a reason. Keep this list short
# and justified — every entry is a test file that never runs on push.
DOCUMENTED_EXCLUSIONS: dict[str, str] = {
    "src/widgets/utility/TradeIdea/": "OOMs the 7GB CI runner (vitest module-resolution overhead); passes locally with --max-old-space-size=8192",
}


def _covered_prefixes() -> set[str]:
    """Reconstruct the ``src/...`` path prefixes CI's vitest shards cover.

    Handles both direct ``vitest run ... src/a/ src/b/`` argument lists and the
    ``for d in X Y Z; do ... "src/widgets/utility/$d/"`` loop shard.
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    prefixes: set[str] = set()

    # Literal src/ path tokens on any line that invokes vitest.
    for line in text.splitlines():
        if "vitest run" in line:
            prefixes.update(re.findall(r"src/[\w./@-]+", line))

    # Expand `for <var> in <dirs>; do` loops whose body templates a src/ path
    # with `$<var>` (the node-widget-tests-2b utility-widget loop).
    for var, dirs in re.findall(r"for\s+(\w+)\s+in\s+([\w\s]+?);\s*do", text):
        template = re.search(rf'src/[\w./@-]*\${var}[\w./@-]*', text)
        if not template:
            continue
        for d in dirs.split():
            prefixes.add(template.group(0).replace(f"${var}", d))

    return prefixes


def _rel_test_files() -> list[str]:
    return sorted(
        f"src/{p.relative_to(TERMINAL_SRC).as_posix()}"
        for p in TERMINAL_SRC.rglob("*.test.ts*")
        if p.suffix in (".ts", ".tsx")
    )


def test_every_vitest_test_file_runs_in_a_ci_shard() -> None:
    prefixes = _covered_prefixes()
    assert prefixes, "parsed no vitest shard prefixes from test.yml — parser or workflow changed"

    exclusions = tuple(DOCUMENTED_EXCLUSIONS)
    uncovered = [
        f
        for f in _rel_test_files()
        if not any(f.startswith(p) for p in prefixes) and not f.startswith(exclusions)
    ]

    assert not uncovered, (
        f"{len(uncovered)} terminal test file(s) run in NO CI shard — add their "
        f"directory to a node-* job in .github/workflows/test.yml (or, if truly "
        f"excluded, to DOCUMENTED_EXCLUSIONS with a reason):\n  "
        + "\n  ".join(uncovered)
    )


def test_documented_exclusions_still_exist() -> None:
    # An exclusion for a suite that no longer exists is stale — drop it so the
    # allowlist keeps meaning something.
    for excluded in DOCUMENTED_EXCLUSIONS:
        matches = list(TERMINAL_SRC.parent.glob(excluded + "**/*.test.ts*"))
        assert matches, f"DOCUMENTED_EXCLUSIONS entry {excluded!r} matches no test files — remove it"
