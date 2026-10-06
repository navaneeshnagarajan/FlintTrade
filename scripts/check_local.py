"""Standard-library planning and secret scanning for ``ft.py check``.

Affected checks are a feedback loop. Only the explicitly exhaustive gate (or a
conservative unavailable-diff fallback) is reported as full verification. App
suites run sequentially so jsdom and Electron do not compete for memory.
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType, SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass
class Check:
    """One required command and its environment additions."""

    label: str
    argv: tuple[str, ...]
    env: dict[str, str] = field(default_factory=dict)


def build_plan(
    surfaces: Mapping[str, bool],
    *,
    python: str,
    python_command: Sequence[str],
    pnpm: Sequence[str],
    pytest_env: Mapping[str, str],
    cargo: str | None = None,
) -> list[Check]:
    """Select required checks without executing or installing any tool.

    Python selection is deliberately conservative: its command must cover all
    package suites when ``python`` is selected, otherwise repository/script
    invariants. The caller builds that command using the task runner's resolver.
    """
    plan = [
        Check("Version consistency", (python, "scripts/check-version-consistency.py")),
        Check("Site URL consistency", (python, "scripts/check-site-url-consistency.py")),
        # Check is a fixed gate: interactive -k/-m/shard preferences cannot
        # shrink it while its output claims exhaustive verification.
        Check("Python tests" if surfaces.get("python") else "Repository and script invariants", tuple(python_command),
              {**pytest_env, "PYTEST_ADDOPTS": ""}),
    ]
    if surfaces.get("rust") and cargo is not None:
        plan.append(Check("Rust ticks tests", (cargo, "test", "--manifest-path", "packages/core/ticks/Cargo.toml"),
                          {"PYO3_PYTHON": python}))
    if surfaces.get("python"):
        plan.append(Check("Python lint", (python, "-m", "ruff", "check", "packages/", "tests/", "scripts/__tests__/")))
    if surfaces.get("dependencies"):
        plan.extend([
            Check("Broker lock consistency", (python, "scripts/check-brokers-lock.py")),
            Check("NOTICE consistency", (python, "scripts/generate-notice.py", "--check")),
            Check("Dependency provenance", (python, "scripts/check-no-git-deps.py")),
            Check("Python lock export consistency", (python, "scripts/check-uv-lock-export-drift.py")),
            Check("HTTP cache dependency contract",
                  (*pnpm, "exec", "node", "--test", "scripts/__tests__/http-cache-semantics.test.mjs")),
        ])
    if surfaces.get("terminal"):
        plan.extend([
            Check("Terminal lint", (*pnpm, "--dir", "packages/apps/terminal", "run", "lint")),
            Check("Full terminal tests", (*pnpm, "--dir", "packages/apps/terminal", "exec", "vitest", "run",
                                          "--pool=forks", "--maxWorkers=1", "--no-file-parallelism"),
                  {"NODE_OPTIONS": f"{os.environ.get('NODE_OPTIONS', '')} --max-old-space-size=8192".strip()}),
            # The build script already runs tsc --noEmit; do not run it twice.
            Check("Terminal typecheck and build", (*pnpm, "--dir", "packages/apps/terminal", "run", "build")),
        ])
    if surfaces.get("site"):
        for script in ("test", "typecheck", "build"):
            plan.append(Check(f"Site {script}", (*pnpm, "--dir", "packages/apps/site", "run", script)))
    if surfaces.get("desktop"):
        for script in ("typecheck", "test:electron"):
            plan.append(Check(f"Desktop {script}", (*pnpm, "--dir", "packages/apps/desktop", "run", script)))
    plan.append(Check("Secrets scan", (python, "scripts/check_local.py", "--secrets")))
    return plan


def scan_secrets(root: Path = REPO_ROOT, *, paths: Sequence[str] | None = None) -> int:
    """Check tracked and unignored source files without printing matched values.

    Uses the existing CI credential patterns and covers TypeScript and module
    JavaScript alongside Python, JavaScript and TOML. Missing inventory or an
    unreadable source file is a gate failure, not a clean scan.
    """
    if paths is None:
        try:
            result = subprocess.run(
                ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                cwd=root, capture_output=True, check=False,
            )
        except OSError as exc:
            print(f"error: secrets inventory unavailable: {exc}", file=sys.stderr)
            return 1
        if result.returncode != 0:
            print("error: secrets inventory unavailable (git ls-files failed)", file=sys.stderr)
            return 1
        paths = sorted({os.fsdecode(item) for item in result.stdout.split(b"\0") if item})
    patterns = (
        re.compile(r"BROKER_API_KEY\s*=\s*['\"][^'\"]+['\"]"),
        # Provider prefixes and URL-safe key bodies include hyphens/underscores.
        re.compile(r"sk-[a-zA-Z0-9_-]{20,}"),
    )
    failed = False
    for relative in paths:
        source = root / relative
        if source.suffix not in {".py", ".js", ".ts", ".tsx", ".mjs", ".cjs", ".toml"}:
            continue
        if source.name == ".env.example" or not source.exists():
            continue
        try:
            content = source.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            print(f"error: cannot scan {relative}", file=sys.stderr)
            failed = True
            continue
        for line_number, line in enumerate(content.splitlines(), 1):
            if any(pattern.search(line) for pattern in patterns):
                print(f"Potential secret: {relative}:{line_number}")
                failed = True
    if not failed:
        print("Secrets scan passed.")
    return int(failed)


def _non_negative(value: str) -> int:
    """Validate a bounded-runner override before any check is started."""
    try:
        workers = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("workers must be a non-negative integer") from exc
    if workers < 0:
        raise argparse.ArgumentTypeError("workers must be a non-negative integer")
    return workers


def run_checks(args: Sequence[str], *, runner: ModuleType | SimpleNamespace) -> int:
    """Classify committed/worktree changes, print the plan, and run it sequentially."""
    parser = argparse.ArgumentParser(prog="python scripts/ft.py check")
    parser.add_argument("--full", action="store_true", help="run the exhaustive pre-push gate")
    parser.add_argument("--base", default="origin/main", help="base used for committed changes")
    parser.add_argument("--dry-run", action="store_true", help="print checks without executing them")
    parser.add_argument("--workers", type=_non_negative, help="pytest workers (0 disables xdist)")
    options = parser.parse_args(list(args))
    classifier = runner._load_module_from_path(
        "_flinttrade_check_changes", Path(__file__).with_name("check_changes.py")
    )
    paths = [] if options.full else classifier.changed_paths(base=options.base, include_worktree=True, root=runner.REPO_ROOT)
    full = options.full or paths is None
    surfaces = classifier.classify_paths(paths or [], full=full)
    runner.info("Gate: full (exhaustive local verification)" if full else
                "Gate: affected (run check --full before pushing)")
    if paths is None:
        runner.info("Changed paths unavailable - selecting every surface.")
    if not any(surfaces.values()):
        runner.info("No changed surfaces; no checks selected.")
        return 0
    runner.info("Selected surfaces: " + ", ".join(name for name, selected in surfaces.items() if selected))
    pytest_args = [] if surfaces.get("python") else ["tests", "scripts/__tests__"]
    if options.workers is not None:
        pytest_args.extend(["--workers", str(options.workers)])
    # Resolve plugins against the very same fixed environment the gate executes,
    # not interactive addopts which are deliberately excluded from this gate.
    test_env = runner.pytest_env({"PYTEST_ADDOPTS": ""})
    try:
        python_command = runner.pytest_argv([*pytest_args, "-v"], env=test_env)
    except ValueError as exc:
        runner.fail(str(exc))
        return 2
    python = python_command[0]
    pnpm = runner.pnpm_argv()
    needs_node = any(surfaces.get(name) for name in ("terminal", "desktop", "site", "dependencies"))
    cargo = runner.shutil.which("cargo")
    if surfaces.get("rust") and cargo is None:
        runner.info("cargo not found - Rust ticks tests are optional on this host")
    plan = build_plan(surfaces, python=python, python_command=python_command, pnpm=pnpm or ["pnpm"],
                      pytest_env=test_env, cargo=cargo)
    for check in plan:
        runner.info(f"\n{check.label}:")
        runner.info(subprocess.list2cmdline(check.argv) if runner.IS_WINDOWS else shlex.join(check.argv))
        for name, value in check.env.items():
            if name in {"NODE_OPTIONS", "PYO3_PYTHON"}:
                runner.info(f"  environment: {name}={value}")
    if options.dry_run:
        runner.info("Dry run only; no check results.")
        return 0
    if needs_node and pnpm is None:
        runner.fail("Node/pnpm is required for the selected gate; run setup before checking.")
        return 1
    for check in plan:
        runner.header(check.label)
        if cargo is not None and check.argv[0] == cargo:
            env = runner.rust_test_env(python) | check.env
        elif check.argv[0] == python:
            env = runner.python_env(check.env)
        else:
            env = runner.ci_env() | check.env
        try:
            code = runner.run(check.argv, env=env, check=False)
        except OSError as exc:
            runner.fail(f"Cannot run {check.label}: {exc}")
            return 1
        if code != 0:
            runner.fail(f"{check.label} failed (exit {code}). Gate did not pass.")
            return code
    runner.info("Full local gate passed." if full else "Affected checks passed; full pre-push gate remains required.")
    return 0


def main(args: Sequence[str] | None = None) -> int:
    """Expose the dependency-free secret scanner used by the check plan."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--secrets", action="store_true", required=True)
    parser.parse_args(args)
    return scan_secrets()


if __name__ == "__main__":
    raise SystemExit(main())
