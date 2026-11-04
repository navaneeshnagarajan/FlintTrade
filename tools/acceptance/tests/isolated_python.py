"""Native Python-profile refusals and executed-body CI omission controls.

The parent carrier exercises the real outer launcher. Kernel postconditions are
replayed through its *same* GUARD, because nested user namespaces are not a
portable prerequisite after the outer capability drop. Preflight refusals still
invoke the actual CLI; no simulated sandbox or environment-only positive exists.
"""

from __future__ import annotations

import ctypes
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]


def deny_unshare() -> None:
    """Make the native namespace syscall unavailable in this child only."""

    class Filter(ctypes.Structure):
        _fields_ = [("code", ctypes.c_ushort), ("jt", ctypes.c_ubyte), ("jf", ctypes.c_ubyte), ("k", ctypes.c_uint)]

    class Program(ctypes.Structure):
        _fields_ = [("len", ctypes.c_ushort), ("filter", ctypes.POINTER(Filter))]

    number = {"x86_64": 272, "aarch64": 97}[platform.machine()]
    filters = (Filter * 4)(
        Filter(0x20, 0, 0, 0), Filter(0x15, 0, 1, number), Filter(0x06, 0, 0, 0x50001), Filter(0x06, 0, 0, 0x7FFF0000)
    )
    program = Program(4, filters)
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(38, 1, 0, 0, 0) or libc.prctl(22, 2, ctypes.byref(program), 0, 0):
        raise RuntimeError("Could not install child-only namespace refusal control")


class PythonSandbox(unittest.TestCase):
    """Exercise cold prerequisite refusals and the common kernel guard."""

    def setUp(self) -> None:
        """Require the real outer boundary before creating inert fixtures."""
        sys.path.insert(0, str(ROOT / "tools/acceptance"))
        from guard import guard

        guard()
        self.outer = json.loads(Path("/run/test/artifacts/isolation.json").read_text())
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.source = self.directory / "source"
        self.source.mkdir()
        (self.source / "pyproject.toml").write_text('[project]\nname="inert-controls"\nversion="0.0.0"\n')
        self.state = self.directory / "state"
        self.state.mkdir()
        self.python_root = Path(sys.base_prefix).resolve()
        subprocess.run(
            [sys.executable, "-I", "-S", "-m", "venv", "--without-pip", str(self.source / ".venv")],
            check=True,
            timeout=30,
        )
        self.launcher = ROOT / "tools/acceptance/isolated.py"
        self.marker = self.directory / "native-sentinel"
        self.command = [
            str(self.source / ".venv/bin/python"),
            "-I",
            "-S",
            "-c",
            "from pathlib import Path;Path('/run/test/artifacts/native-sentinel').write_text('executed')",
        ]
        self.records = []
        self.addCleanup(self.save)

    def save(self) -> None:
        """Retain every native subcontrol independently of unittest totals."""
        (Path("/run/test/artifacts") / (self.id() + ".json")).write_text(json.dumps(self.records, indent=2))

    def invoke(
        self, extra: list[str] | None = None, *, deny_namespace: bool = False
    ) -> subprocess.CompletedProcess[str]:
        """Invoke the actual CLI, preserving raw refusal and sentinel state."""
        argv = [
            sys.executable,
            "-I",
            "-S",
            str(self.launcher),
            "--profile",
            "python-tests",
            "--label",
            "profile-control",
            "--source",
            str(self.source),
            "--state-root",
            str(self.state),
            "--uv",
            "/tools/bin/uv",
            "--python-root",
            str(self.python_root),
            *(extra or []),
            "--",
            *self.command,
        ]
        result = subprocess.run(
            argv, capture_output=True, text=True, timeout=45, preexec_fn=deny_unshare if deny_namespace else None
        )
        sentinels = [str(p) for p in self.state.glob("flinttrade-*/artifacts/native-sentinel")]
        self.records.append(
            {
                "kind": "actual-launcher",
                "argv": argv,
                "exit": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "sentinels": sentinels,
            }
        )
        self.assertEqual(sentinels, [], "Refusal executed the native sentinel")
        return result

    def replay(
        self, *, env: dict | None = None, boundary: dict | None = None, cwd: Path = ROOT
    ) -> subprocess.CompletedProcess[str]:
        """Execute the exact maintained guard under genuine kernel conditions."""
        import isolated

        outer = self.outer
        argv = [
            sys.executable,
            "-I",
            "-S",
            "-c",
            isolated.GUARD,
            json.dumps(outer["environment"]),
            json.dumps(outer["host_namespaces"]),
            json.dumps(outer["hidden"]),
            json.dumps(boundary or outer["boundary"]),
            sys.executable,
            "-I",
            "-S",
            "-c",
            "from pathlib import Path;Path(" + repr(str(self.marker)) + ").touch()",
        ]
        result = subprocess.run(
            argv, cwd=cwd, env=outer["environment"] if env is None else env, capture_output=True, text=True, timeout=30
        )
        self.records.append(
            {
                "kind": "common-guard-replay",
                "argv": argv,
                "exit": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "sentinel": self.marker.exists(),
            }
        )
        return result

    def refused(self, result: subprocess.CompletedProcess[str], message: str) -> None:
        """Require the intended refusal and absence of a native side effect."""
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(message, result.stdout + result.stderr)
        self.assertFalse(self.marker.exists())

    def test_python_profile_runs_without_node_assets_or_pnpm(self) -> None:
        """The actual outer launcher and its common guard admit a native child."""
        outer = self.outer
        self.assertIn(outer["boundary"]["profile"], ("full", "python-tests"))
        self.assertTrue(all(outer["namespaces"][key] != value for key, value in outer["host_namespaces"].items()))
        self.assertTrue(
            all(
                int(outer["status"][key].strip(), 16) == 0 for key in ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb")
            )
        )
        self.assertEqual(outer["status"]["NoNewPrivs"].strip(), "1")
        self.assertEqual(outer["supplementary_groups"], os.getgroups())
        if outer["boundary"]["profile"] == "python-tests":
            self.assertFalse((ROOT / "node_modules").exists())
            self.assertFalse(Path("/tools/bin/pnpm").exists())
        result = self.replay()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(self.marker.exists())

    def test_missing_python_prerequisite_precedes_native_execution(self) -> None:
        """No interpreter or dependency fallback is attempted."""
        shutil.rmtree(self.source / ".venv")
        self.refused(self.invoke(), "Missing prerequisite")

    def test_dirty_and_private_source_precede_native_execution(self) -> None:
        """Real checkout/private entries are refused, including nested ones."""
        for name in (".git", ".local", "graphify-out", "nested/.ssh"):
            with self.subTest(name=name):
                target = self.source / name
                target.mkdir(parents=True)
                self.refused(self.invoke(), "Source-only input required")
                target.rmdir()

    def test_escaping_source_symlink_precedes_native_execution(self) -> None:
        """An existing external target is not mistaken for a closed input."""
        target = self.directory / "private-data"
        target.write_text("inert privacy marker")
        (self.source / "escape").symlink_to(target)
        self.refused(self.invoke(), "Escaping input symlink")

    def test_escaping_runtime_root_precedes_native_execution(self) -> None:
        """An unrelated/broad runtime root cannot authorise the interpreter."""
        self.refused(self.invoke(["--python-root", str(self.directory)]), "escapes the declared Python runtime root")

    def test_runtime_root_symlink_and_installed_venv_are_refused(self) -> None:
        """Neither root indirection nor installed startup hooks qualify."""
        link = self.directory / "runtime-link"
        link.symlink_to(self.python_root, target_is_directory=True)
        self.refused(self.invoke(["--python-root", str(link)]), "Symlink source/runtime root refused")
        site = next((self.source / ".venv/lib").glob("python*/site-packages"))
        (site / "untrusted.pth").write_text("import this_must_not_run\n")
        self.refused(self.invoke(), "refuses installed site-packages")

    def test_invalid_profile_inputs_and_no_full_fallback(self) -> None:
        """Full assets remain mandatory and cannot leak into Python mode."""
        for extra, message in [
            (["--assets", str(self.directory)], "refuses Node/assets/pnpm/browser"),
            (["--browsers", str(self.directory)], "refuses Node/assets/pnpm/browser"),
            (["--profile", "full"], "Full profile requires"),
            (["--timeout", "0"], "Timeout must be"),
            (["--label", "../invalid"], "Invalid evidence label"),
        ]:
            with self.subTest(extra=extra):
                self.refused(self.invoke(extra), message)
        selected = self.command
        try:
            for executable in ("node", "pnpm", "/usr/bin/python3", "/hidden/python"):
                with self.subTest(executable=executable):
                    self.command = [executable, *selected[1:]]
                    self.refused(self.invoke(), "requires the selected Python command")
        finally:
            self.command = selected

    def test_tampered_profile_and_environment_fail_common_guard(self) -> None:
        """Neither a forged profile nor extra environment reaches native code."""
        for key, value in [
            ("HOME", "/tampered"),
            ("FLINTTRADE_SANDBOX_PROFILE", "forged"),
            ("PYTHONPATH", "/untrusted"),
        ]:
            with self.subTest(key=key):
                env = dict(self.outer["environment"], **{key: value})
                self.refused(self.replay(env=env), "AssertionError")
        boundary = dict(self.outer["boundary"], profile="forged")
        self.refused(self.replay(boundary=boundary), "AssertionError")

    def test_writable_source_fails_common_guard_before_native_execution(self) -> None:
        """A real writable mount, not a pretend permission mode, is rejected."""
        boundary = dict(self.outer["boundary"], readonly=[str(self.source)])
        self.refused(self.replay(boundary=boundary, cwd=self.source), "writable input")

    def test_unavailable_namespace_fails_before_native_execution(self) -> None:
        """A real child-only denied unshare cannot trigger a weaker launch."""
        result = self.invoke(deny_namespace=True)
        self.refused(result, "bwrap:")
        receipt, _ = json.JSONDecoder().raw_decode(result.stdout)
        self.assertIs(receipt["isolation_guard_passed"], False)
        self.assertNotIn("\nISOLATION_VERIFIED ", result.stdout)


class PythonCarrier(unittest.TestCase):
    """Bind the maintained workflow to actual executed identities."""

    def test_host_preparation_requires_explicit_no_bytecode_flag(self) -> None:
        """Isolated mode does not inherit PYTHONDONTWRITEBYTECODE."""
        with tempfile.TemporaryDirectory() as temp:
            result = subprocess.run(
                [sys.executable, "-I", "-S", str(ROOT / "tools/acceptance/ci_python_contracts.py"),
                 "--state-root", temp],
                capture_output=True, text=True, timeout=30,
                env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("requires non-optimised python -B -I -S", result.stderr)
            self.assertEqual(list(Path(temp).iterdir()), [])

    def test_ci_selection_contains_all_lifecycle_bodies(self) -> None:
        """The selected union contains every existing lifecycle identity."""
        from ci_python_contracts import expected_identities

        expected = expected_identities(ROOT)
        names = [name for name in expected if name.startswith("ExecutorLifecycle.")]
        self.assertEqual(len(names), 13)
        self.assertIn("ExecutorLifecycle.test_large_request_handoff_is_bounded_without_rejecting_valid_env", names)
        self.assertIn("ExecutorLifecycle.test_interrupted_full_handoff_cancels_without_blocking_delivery", names)

    def test_workflow_omission_is_not_satisfied_by_import_registration(self) -> None:
        """Removing the carrier step fails the original CI registration oracle."""
        import contracts
        from ci_python_contracts import WORKFLOW_COMMAND

        original = Path.read_text
        target = ROOT / ".github/workflows/test.yml"

        def read(path, *args, **kwargs):
            text = original(path, *args, **kwargs)
            return text.replace(WORKFLOW_COMMAND, "true") if path == target else text

        with patch.object(Path, "read_text", read):
            with self.assertRaisesRegex(AssertionError, "CI is missing"):
                contracts.Registrations().test_ci_runs_the_synthetic_contract_subset()

    def test_source_projection_excludes_real_metadata_and_keeps_exact_bytes(self) -> None:
        """Private inputs stay out; the new venv is created by selected Python."""
        from ci_python_contracts import SOURCE_FILES, prepare, source_inventory

        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            checkout = base / "checkout"
            for name in SOURCE_FILES:
                target = checkout / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / name, target)
            subprocess.run(["/usr/bin/git", "init", "--quiet", str(checkout)], check=True, timeout=10)
            for name in (".local", "graphify-out", ".ssh"):
                (checkout / name).mkdir()
                (checkout / name / "private-marker").write_text("inert privacy control")
            out = base / "prepared"
            out.mkdir()
            source = prepare(checkout, out)
            self.assertEqual(source_inventory(source), source_inventory(checkout))
            self.assertFalse(any((source / name).exists() for name in (".git", ".local", "graphify-out", ".ssh")))
            result = subprocess.run(
                [
                    str(source / ".venv/bin/python"),
                    "-I",
                    "-S",
                    "-c",
                    "import platform;print(platform.python_version())",
                ],
                capture_output=True,
                text=True,
                check=True,
                timeout=10,
            )
            self.assertEqual(result.stdout.strip(), platform.python_version())
            self.assertFalse(any(next((source / ".venv/lib").glob("python*/site-packages")).iterdir()))

    def test_projection_rejects_escaping_source_before_preparation(self) -> None:
        """An allowlisted filename cannot smuggle a symlink target into CI."""
        from ci_python_contracts import prepare

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            checkout = root / "checkout"
            checkout.mkdir()
            (root / "operator-marker").write_text("inert control")
            (checkout / "pyproject.toml").symlink_to(root / "operator-marker")
            out = root / "out"
            out.mkdir()
            with self.assertRaisesRegex(RuntimeError, "Projection symlink refused"):
                prepare(checkout, out)
            self.assertFalse((out / "source/.venv").exists())

    def test_real_subset_omission_cannot_count_as_ci_execution(self) -> None:
        """Execute Reports alone; importing lifecycle controls does not count."""
        from ci_python_contracts import expected_identities, verify_execution

        result = subprocess.run(
            [sys.executable, "-S", str(ROOT / "tools/acceptance/tests/contracts.py"), "Reports"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        path = Path("/run/test/artifacts/contracts-execution.json")
        receipt = json.loads(path.read_text())
        output = Path("/run/test/artifacts") / (self.id() + ".json")
        output.write_text(
            json.dumps(
                {"exit": result.returncode, "stdout": result.stdout, "stderr": result.stderr, "receipt": receipt},
                indent=2,
            )
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(receipt["cases"])
        self.assertTrue(all(row["id"].startswith("Reports.") for row in receipt["cases"]))
        self.assertTrue(all("body-return" in row["phases"] for row in receipt["cases"]))
        with self.assertRaisesRegex(RuntimeError, "Executed CI identities"):
            verify_execution(expected_identities(ROOT), receipt)
        expected = [row["id"] for row in receipt["cases"]]
        verify_execution(expected, receipt)
        for mutation in ("setup-only", "skip", "duplicate", "wrong-total"):
            changed = deepcopy(receipt)
            if mutation == "setup-only":
                changed["cases"][0]["phases"] = ["setup-enter", "setup-return"]
            elif mutation == "skip":
                changed["cases"][0]["outcome"] = "skipped"
            elif mutation == "duplicate":
                changed["cases"].append(changed["cases"][0])
            else:
                changed["tests_run"] += 1
            with self.subTest(mutation=mutation), self.assertRaises(RuntimeError):
                verify_execution(expected, changed)


if __name__ == "__main__":
    unittest.main(verbosity=2)
