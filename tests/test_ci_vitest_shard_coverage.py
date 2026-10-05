"""Require every terminal Vitest file to run in exactly one CI command.

Resolve literal and loop-expanded source arguments from the five required
terminal contexts. There are no exclusions. Matching a loop's common directory
prefix would falsely cover unlisted widgets, including the former TradeIdea gap.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "test.yml"
TERMINAL_SRC = ROOT / "packages" / "apps" / "terminal" / "src"
CI_LANES = (
    "node-core-tests", "node-widget-tests-1", "node-widget-tests-2a",
    "node-widget-tests-2b", "node-widget-tests-3",
)


def _resolved_paths(command: str) -> list[str]:
    """Resolve the exact source arguments without widening shell loop paths."""
    loops = {
        variable: directories.split()
        for variable, directories in re.findall(r"for\s+(\w+)\s+in\s+([\w\s-]+?);\s*do", command)
    }
    paths: list[str] = []
    for line in command.splitlines():
        if "vitest run" not in line or line.lstrip().startswith("#"):
            continue
        assert not re.search(r"(?:--exclude|--shard|--changed|--related|--project|--testNamePattern|-t)(?:\s|=)", line), (
            f"Vitest selection cannot shrink an exhaustive CI lane: {line}"
        )
        for target in re.findall(r"src/[\w./@${}-]+", line):
            variable = re.search(r"\$(\w+)|\$\{(\w+)\}", target)
            if variable is None:
                assert "$" not in target, f"Unresolved Vitest target: {target}"
                paths.append(target)
                continue
            name = variable.group(1) or variable.group(2)
            assert name in loops, f"Unresolved Vitest loop variable: {target}"
            paths.extend(target.replace(variable.group(0), directory) for directory in loops[name])
    return paths


def _coverage_targets() -> list[tuple[str, str]]:
    """Keep command ownership so overlaps within or between lanes are visible."""
    jobs = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]
    targets = []
    for lane in CI_LANES:
        assert lane in jobs, f"Required terminal context missing: {lane}"
        for step in jobs[lane]["steps"]:
            owner = f"{lane}: {step.get('name', 'unnamed step')}"
            targets.extend((owner, path) for path in _resolved_paths(step.get("run", "")))
    return targets


def _rel_test_files() -> list[str]:
    return sorted(
        f"src/{path.relative_to(TERMINAL_SRC).as_posix()}"
        for path in TERMINAL_SRC.rglob("*.test.ts*")
        if path.suffix in (".ts", ".tsx")
    )


def test_every_vitest_test_file_runs_in_exactly_one_ci_command() -> None:
    targets = _coverage_targets()
    files = _rel_test_files()
    assert targets and files, "Terminal coverage must not be vacuous"
    incorrect = {
        file: [owner for owner, path in targets if file.startswith(path)]
        for file in files
        if sum(file.startswith(path) for _, path in targets) != 1
    }
    assert not incorrect, f"Terminal files need exactly one CI command, with no exclusions: {incorrect}"
    # A helper directory can contain no tests yet (src/test-utils), but every
    # argument must resolve so a misspelling cannot silently hide coverage.
    missing = [path for _, path in targets if not (TERMINAL_SRC.parent / path).exists()]
    assert not missing, f"CI Vitest paths do not exist: {missing}"


def test_loop_resolution_does_not_cover_unlisted_widgets() -> None:
    command = """for d in Alerts News; do
      npx vitest run --pool=forks --maxWorkers=1 --no-file-parallelism "src/widgets/utility/$d/" || FAIL=1
    done"""
    assert _resolved_paths(command) == ["src/widgets/utility/Alerts/", "src/widgets/utility/News/"]


def test_tradeidea_is_an_isolated_bounded_required_step() -> None:
    job = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["node-widget-tests-2b"]
    steps = [step for step in job["steps"] if "src/widgets/utility/TradeIdea/" in step.get("run", "")]
    assert len(steps) == 1, "TradeIdea must run once in its own required step"
    step = steps[0]
    assert _resolved_paths(step["run"]) == ["src/widgets/utility/TradeIdea/"]
    assert "--pool=forks --maxWorkers=1 --no-file-parallelism" in step["run"]
    assert step["env"]["NODE_OPTIONS"] == "--max-old-space-size=4096"
    assert not step.get("continue-on-error", False)
    assert "||" not in step["run"]
    assert step.get("timeout-minutes", job["timeout-minutes"]) <= 5
