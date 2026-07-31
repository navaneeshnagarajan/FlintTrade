"""Guard: the terminal's ``any``/suppression gate is still wired to a CI job.

The house rules ban an explicit ``any``, ``@ts-ignore`` and a bare
``@ts-expect-error``. ``tsc --noEmit`` enforces none of them - ``strict`` permits
an explicit ``any`` by design, and a pragma is a comment - so the whole gate is
four ESLint rules in ``packages/apps/terminal/eslint.config.mjs``.

That arrangement has already failed once in this repository, in both directions:

* an ``eslint.config.mjs`` claimed ``@typescript-eslint/no-explicit-any`` while
  none of its plugins were installed and no job ran it, so the rule was
  decoration;
* its replacement, ``scripts/check-terminal-type-safety.py``, did run, but
  matched regular expressions and missed ``type Payload = any`` outright.

The rules' own behaviour is covered by
``packages/apps/terminal/src/__tests__/eslint-local-rules.test.ts`` (vitest,
node-core-tests). Those tests stay green even if nothing ever invokes ESLint, so
this file covers the other link in the chain: that a CI job actually runs the
lint script, and that the config still enables the two local rules as errors.

Lives in ``tests/`` rather than ``scripts/__tests__/`` because only the former is
collected - ``testpaths`` is ``["tests"]``, CI runs ``packages/*/*/tests/ tests/``
and ``ft.py test`` globs the same two, so a guard placed in ``scripts/__tests__/``
would itself never run.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "test.yml"
TERMINAL = ROOT / "packages" / "apps" / "terminal"
ESLINT_CONFIG = TERMINAL / "eslint.config.mjs"
LOCAL_RULES = TERMINAL / "eslint-local-rules.mjs"

# The rules that carry the house rules no other gate in the repo can enforce.
REQUIRED_RULES = ("local/no-explicit-any", "local/no-ts-suppression")


def test_local_rules_module_exists() -> None:
    """The AST rules that replaced the regular-expression script are present."""
    assert LOCAL_RULES.is_file(), f"{LOCAL_RULES.relative_to(ROOT).as_posix()} is missing"


@pytest.mark.parametrize("rule", REQUIRED_RULES)
def test_eslint_config_enables_rule_as_error(rule: str) -> None:
    """Each local rule is enabled at ``error``, not ``warn`` or ``off``."""
    text = ESLINT_CONFIG.read_text(encoding="utf-8")
    assert re.search(rf'"{re.escape(rule)}":\s*"error"', text), (
        f'{rule} is not enabled as "error" in eslint.config.mjs - the gate it carries is off'
    )


def test_eslint_config_registers_the_local_plugin() -> None:
    """The ``local/`` prefix resolves, so the rules above are not dead names."""
    text = ESLINT_CONFIG.read_text(encoding="utf-8")
    assert "eslint-local-rules.mjs" in text, "eslint.config.mjs does not import the local rules module"
    assert re.search(r"local:\s*localRules", text), "eslint.config.mjs does not register the `local` plugin"


def test_terminal_package_exposes_a_lint_script() -> None:
    """``pnpm run lint`` exists and fails on any warning."""
    manifest = json.loads((TERMINAL / "package.json").read_text(encoding="utf-8"))
    lint = manifest.get("scripts", {}).get("lint", "")
    assert "eslint" in lint, f"terminal package.json has no eslint lint script (found {lint!r})"
    assert "--max-warnings=0" in lint, "the lint script must fail on warnings, or a downgraded rule passes CI"


def test_a_ci_job_runs_the_terminal_lint_script() -> None:
    """Some job in test.yml invokes the terminal's lint script.

    Without this the config could be perfect and never execute - the exact
    failure that got the previous eslint.config.mjs deleted.
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    assert re.search(r"run:\s*pnpm --dir packages/apps/terminal run lint", text), (
        "no CI job runs `pnpm --dir packages/apps/terminal run lint`; the terminal lint gate is unenforced"
    )


def test_workflow_does_not_invoke_the_deleted_regex_script() -> None:
    """The superseded scanner is not resurrected as a CI step.

    A prose reference explaining why it went is fine; a ``run:`` line is not,
    because the script no longer exists and the step would fail.
    """
    for line in WORKFLOW.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        assert "check-terminal-type-safety.py" not in stripped, f"test.yml still executes the deleted script: {stripped}"
