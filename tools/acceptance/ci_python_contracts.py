"""Offline CI preparation and exact executed-body accounting (stdlib only).

Host work is data copying plus a real --without-pip venv. Tests and their helper
imports run only through isolated.py. This is not a second sandbox constructor.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    class _ResultStream(Protocol):
        """The write, flush and line interface consumed by TextTestResult."""

        def write(self, value: str, /) -> object: ...
        def flush(self) -> object: ...
        def writeln(self, value: str | None = None, /) -> None: ...

    _PhaseBase = unittest.TextTestResult[_ResultStream]
else:
    _PhaseBase = unittest.TextTestResult

ROOT = Path(__file__).resolve().parents[2]
CI_CLASSES = ("Reports", "Registrations", "ExecutorLifecycle", "FixturePublication", "PythonSandbox", "PythonCarrier")
WORKFLOW_COMMAND = (
    'uv run --offline --no-sync python -B -I -S tools/acceptance/ci_python_contracts.py '
    '--state-root "$RUNNER_TEMP/acceptance-python"'
)
# Explicit import + inert registration operands, not a copy of the worktree,
# its credentials, installed environment, graph output or operator files.
SOURCE_FILES = (
    "pyproject.toml",
    ".github/workflows/test.yml",
    "tools/acceptance/isolated.py",
    "tools/acceptance/ci_python_contracts.py",
    "tools/acceptance/guard.py",
    "tools/acceptance/run.py",
    "tools/acceptance/owned_command.py",
    "tools/acceptance/csp.py",
    "tools/acceptance/infra-cases.json",
    "tools/acceptance/tests/contracts.py",
    "tools/acceptance/tests/executor_lifecycle.py",
    "tools/acceptance/tests/isolated_python.py",
    "tools/reticle/setup.py",
    "tools/reticle/validate_results.py",
    "tools/reticle/run.py",
    "tools/reticle/incident-protocol-cases.json",
    "packages/apps/terminal/package.json",
    "packages/apps/terminal/tsconfig.json",
    "packages/apps/terminal/tsconfig.e2e-infra.json",
    "packages/apps/terminal/eslint.config.mjs",
    "packages/apps/terminal/playwright.incident-protocol.config.ts",
    "packages/apps/terminal/e2e/incident-delivery-protocol.control.ts",
)


def sha(path: Path) -> str:
    """Hash an explicit input without importing it."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_inventory(root: Path) -> dict[str, str]:
    """Bind every projected public file to its exact bytes."""
    return {name: sha(root / name) for name in SOURCE_FILES}


def expected_identities(root: Path, classes: tuple[str, ...] = CI_CLASSES) -> list[str]:
    """Independently collect named test methods as data, without test imports.

    Args:
        root: Source-only checkout containing the maintained test modules.
        classes: Complete named class inventory for this invocation.

    Returns:
        Sorted class/method identities, preserving multiplicity.
    """
    found = {}
    for name in ("contracts.py", "executor_lifecycle.py", "isolated_python.py"):
        tree = ast.parse((root / "tools/acceptance/tests" / name).read_text())
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name in classes:
                found[node.name] = [
                    node.name + "." + method.name
                    for method in node.body
                    if isinstance(method, ast.FunctionDef) and method.name.startswith("test_")
                ]
    if set(found) != set(classes) or any(not rows for rows in found.values()):
        raise RuntimeError("Missing required CI contract class or bodies")
    return sorted(identity for rows in found.values() for identity in rows)


def verify_execution(expected: list[str], receipt: dict) -> None:
    """Refuse collection-only, omitted, duplicate, failed or skipped bodies.

    Args:
        expected: Independently collected required identity multiset.
        receipt: Actual unittest phase and outcome receipt.

    Raises:
        RuntimeError: Any identity, phase, outcome or total fails admission.
    """
    rows = receipt.get("cases", [])
    if Counter(row["id"] for row in rows) != Counter(expected):
        raise RuntimeError("Executed CI identities differ from the required union")
    if any(
        row.get("outcome") != "passed"
        or row.get("phases")
        != ["setup-enter", "setup-return", "body-enter", "body-return", "teardown-enter", "teardown-return"]
        for row in rows
    ):
        raise RuntimeError("CI body or setup/teardown did not complete successfully")
    if receipt.get("successful") is not True or receipt.get("tests_run") != len(expected):
        raise RuntimeError("CI result totals disagree with executed identities")


class PhaseResult(_PhaseBase):
    """Record actual unittest phase entry/return, not merely collection/start."""

    def __init__(
        self, stream: _ResultStream, descriptions: bool, verbosity: int, *, durations: int | None = None
    ) -> None:
        super().__init__(stream, descriptions, verbosity, durations=durations)
        self.rows = []
        self.saved = {}

    def startTest(self, test: unittest.TestCase) -> None:
        """Wrap phase calls without replacing any test assertion or fixture."""
        super().startTest(test)
        row = {
            "id": ".".join(test.id().split(".")[-2:]),
            "native_id": test.id(),
            "phases": [],
            "outcome": "unfinished",
            "subtests": [],
        }
        self.rows.append(row)
        self.saved[test] = []
        for name, phase in (("_callSetUp", "setup"), ("_callTestMethod", "body"), ("_callTearDown", "teardown")):
            original = getattr(test, name)
            self.saved[test].append((name, original))

            def call(*args, _original=original, _phase=phase, **kwargs):
                row["phases"].append(_phase + "-enter")
                value = _original(*args, **kwargs)
                row["phases"].append(_phase + "-return")
                return value

            setattr(test, name, call)

    def stopTest(self, test: unittest.TestCase) -> None:
        """Restore the test instance after its native result is recorded."""
        for name, original in self.saved.pop(test):
            setattr(test, name, original)
        super().stopTest(test)

    def addSuccess(self, test: unittest.TestCase) -> None:
        """Record the native successful result."""
        self.rows[-1]["outcome"] = "passed"
        super().addSuccess(test)

    def addError(self, test: unittest.TestCase, err: tuple) -> None:
        """Retain native setup/body/teardown error semantics."""
        self.rows[-1]["outcome"] = "error"
        super().addError(test, err)

    def addFailure(self, test: unittest.TestCase, err: tuple) -> None:
        """Retain a native assertion failure."""
        self.rows[-1]["outcome"] = "failed"
        super().addFailure(test, err)

    def addSkip(self, test: unittest.TestCase, reason: str) -> None:
        """Record skips distinctly so the CI union cannot admit them."""
        self.rows[-1]["outcome"] = "skipped"
        super().addSkip(test, reason)

    def addSubTest(self, test: unittest.TestCase, subtest: unittest.TestCase, err: tuple | None) -> None:
        """Do not translate failed subtests into successful parent bodies."""
        self.rows[-1]["subtests"].append({"native_id": subtest.id(), "outcome": "passed" if err is None else "failed"})
        if err is not None:
            self.rows[-1]["outcome"] = "failed-subtest"
        super().addSubTest(test, subtest, err)


def contract_main() -> None:
    """Run normal unittest selection and retain body/import/source receipts."""
    program = unittest.main(
        module="__main__",
        verbosity=2,
        exit=False,
        testRunner=unittest.TextTestRunner(verbosity=2, resultclass=PhaseResult),
    )
    result = program.result
    if not isinstance(result, PhaseResult):
        raise RuntimeError("Missing executed-phase recorder")
    imports = {}
    for name, module in sorted(sys.modules.items()):
        path = getattr(module, "__file__", None)
        if path and Path(path).is_file():
            imports[name] = {"path": str(Path(path).resolve()), "sha256": sha(Path(path))}
    receipt = {
        "cases": result.rows,
        "tests_run": result.testsRun,
        "successful": result.wasSuccessful(),
        "argv": sys.argv,
        "python": sys.executable,
        "version": platform.python_version(),
        "imports": imports,
        "sources": source_inventory(ROOT),
        "python_executable_sha256": sha(Path(sys.executable).resolve()),
        "base_prefix": sys.base_prefix,
        "sys_path": sys.path,
        "uv": {
            "sha256": sha(Path("/tools/bin/uv")),
            "version": subprocess.check_output(["/tools/bin/uv", "--version"], text=True).strip(),
        },
    }
    Path("/run/test/artifacts/contracts-execution.json").write_text(json.dumps(receipt, indent=2) + "\n")
    raise SystemExit(0 if result.wasSuccessful() else 1)


def prepare(checkout: Path, output: Path) -> Path:
    """Project explicit source data and create a real sterile selected venv.

    Args:
        checkout: Real checkout; private metadata is never copied.
        output: Fresh caller-owned preparation directory outside the checkout.

    Returns:
        The prepared source-only directory with its newly created venv.
    """
    source = output / "source"
    source.mkdir()
    for name in SOURCE_FILES:
        original = checkout / name
        if any(parent.is_symlink() for parent in [original, *original.parents] if parent != checkout.parent):
            raise RuntimeError("Projection symlink refused: " + name)
        if not original.is_file():
            raise RuntimeError("Missing projected input: " + name)
        target = source / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, target)
    subprocess.run(
        [sys.executable, "-B", "-I", "-S", "-m", "venv", "--without-pip", str(source / ".venv")],
        check=True,
        timeout=30,
        env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
    )
    return source


def main() -> int:
    """Prepare offline data, then run the maintained exact CI union in isolation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root", type=Path, required=True)
    args = parser.parse_args()
    if not sys.flags.isolated or not sys.flags.no_site or not sys.flags.dont_write_bytecode or sys.flags.optimize:
        parser.error("Host preparation requires non-optimised python -B -I -S")
    if platform.python_version() != "3.14.8":
        parser.error("Selected uv interpreter must be Python 3.14.8; received " + platform.python_version())
    state = args.state_root.resolve()
    if state.is_relative_to(ROOT) or ROOT.is_relative_to(state):
        parser.error("CI state must be outside checkout")
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    output = Path(tempfile.mkdtemp(prefix="ci-python-", dir=state))
    record = {
        "selected_python": sys.executable,
        "selected_version": platform.python_version(),
        "base_python": str(Path(sys.executable).resolve()),
        "source_checkout": str(ROOT),
        "output": str(output),
        "host_imports": {
            name: str(Path(path).resolve())
            for name, module in sorted(sys.modules.items())
            if (path := getattr(module, "__file__", None))
        },
        "steps": [],
    }
    receipt_path = output / "ci-receipt.json"
    try:
        for tool in ("/usr/bin/bwrap", "/usr/sbin/ip", "/usr/bin/readlink"):
            if not os.access(tool, os.X_OK):
                raise RuntimeError("Missing sandbox prerequisite: " + tool + "; no automatic installation")
        uv = shutil.which("uv")
        if uv is None:
            raise RuntimeError("Missing selected uv executable")
        source = prepare(ROOT, output)
        record["sources"] = source_inventory(source)
        record["venv_config"] = (source / ".venv/pyvenv.cfg").read_text()
        record["venv_links"] = {
            str(path.relative_to(source)): os.readlink(path)
            for path in (source / ".venv").rglob("*")
            if path.is_symlink()
        }
        record["uv"] = {"path": str(Path(uv).resolve()), "sha256": sha(Path(uv))}
        expected = expected_identities(source)
        record["required_identities"] = expected
        python = source / ".venv/bin/python"
        argv = [
            sys.executable,
            "-B",
            "-I",
            "-S",
            str(source / "tools/acceptance/isolated.py"),
            "--profile",
            "python-tests",
            "--label",
            "ci-python-contracts",
            "--source",
            str(source),
            "--state-root",
            str(output),
            "--uv",
            uv,
            "--python-root",
            str(Path(sys.base_prefix).resolve()),
            "--",
            str(python),
            "-S",
            "tools/acceptance/tests/contracts.py",
            *CI_CLASSES,
        ]
        log = output / "launcher.log"
        with log.open("w") as stream:
            child = subprocess.run(
                argv,
                stdout=stream,
                stderr=subprocess.STDOUT,
                env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "HOME": str(Path.home())},
                stdin=subprocess.DEVNULL,
                check=False,
            )
        record["steps"].append({"argv": argv, "exit": child.returncode, "log": str(log)})
        raw = log.read_text()
        print(raw, flush=True)
        native, _ = json.JSONDecoder().raw_decode(raw)
        record["sandbox_receipt"] = native
        if child.returncode != 0 or not native["isolation_guard_passed"]:
            raise RuntimeError("Isolated CI contracts failed; see retained launcher log")
        body_path = Path(native["run_directory"]) / "artifacts/contracts-execution.json"
        bodies = json.loads(body_path.read_text())
        verify_execution(expected, bodies)
        if bodies["sources"] != record["sources"] or source_inventory(source) != record["sources"]:
            raise RuntimeError("Source identity changed across CI execution")
        if bodies["version"] != record["selected_version"] or bodies["python"] != str(python):
            raise RuntimeError("Selected interpreter changed across CI execution")
        if bodies["uv"]["sha256"] != record["uv"]["sha256"] or bodies["python_executable_sha256"] != sha(
            Path(sys.executable).resolve()
        ):
            raise RuntimeError("Selected runtime bytes changed across CI execution")
        for module in bodies["imports"].values():
            path = Path(module["path"])
            if not (path.is_relative_to(Path(sys.base_prefix).resolve()) or path.is_relative_to(source / "tools")):
                raise RuntimeError("Unexpected imported helper outside stdlib/test closure: " + str(path))
        record["body_receipt"] = {"path": str(body_path), "sha256": sha(body_path)}
        record["verified"] = True
        return 0
    except Exception as exc:
        record["verified"] = False
        record["error"] = {"type": type(exc).__name__, "message": str(exc)}
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        receipt_path.write_text(json.dumps(record, indent=2) + "\n")
        print(json.dumps({"receipt": str(receipt_path), "verified": record.get("verified", False)}), flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
