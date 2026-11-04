"""Real inert subprocess controls at the maintained runner's execute seam.

Run only inside the qualified isolation launcher. Listener readiness is witnessed
before judging cleanup; observations are saved before any test-owned rescue.
"""

import importlib.util
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
HERE = ROOT / "tools/acceptance"
sys.path.insert(0, str(HERE))
import csp  # noqa: E402

# A direct child, detached child and detached grandchild each own a listener.
# Explicit readiness, not a startup sleep, gates all observations.
CHILD = r"""
import json, os, socket, subprocess, sys, time
from pathlib import Path
root=Path(sys.argv[1]); depth=int(sys.argv[2]); mode=sys.argv[3]
s=socket.socket(); s.bind(('127.0.0.1',0)); s.listen()
stat=Path('/proc/self/stat').read_text().rsplit(')',1)[1].split()
row={'pid':os.getpid(),'ppid':os.getppid(),'pgid':os.getpgrp(),'sid':os.getsid(0),'start':stat[19],'port':s.getsockname()[1]}
(root/(str(depth)+'.json')).write_text(json.dumps(row))
if depth<2: subprocess.Popen([sys.executable,__file__,str(root),str(depth+1),mode],start_new_session=True)
if depth==0:
 deadline=time.monotonic()+3
 while not (root/'2.json').exists():
  if time.monotonic()>deadline: raise RuntimeError('descendant failed to become ready')
  time.sleep(.005)
 while not (root/'observed').exists():
  if time.monotonic()>deadline: raise RuntimeError('observer did not witness readiness')
  time.sleep(.005)
 if mode in {'exit','normal'}: raise SystemExit(37 if mode=='exit' else 0)
 if mode=='signal': os.kill(os.getpid(),signal.SIGTERM)
while True: time.sleep(10)
""".replace("import json, os, socket", "import json, os, signal, socket")


def identity(pid: int) -> dict[str, int | str] | None:
    """Read a process generation, or return None if it has disappeared.

    Args:
        pid: Exact observed process identifier.

    Returns:
        Kernel identity fields, or None for an absent process.
    """
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return {
            "pid": pid,
            "ppid": int(fields[1]),
            "pgid": int(fields[2]),
            "sid": int(fields[3]),
            "start": fields[19],
            "state": fields[0],
        }
    except FileNotFoundError:
        return None


def listening(port: int) -> bool:
    """Probe an inert listener without deriving process ownership.

    Args:
        port: Loopback port reported by the fixture.

    Returns:
        Whether the loopback listener accepts a connection.
    """
    with socket.socket() as sock:
        sock.settimeout(0.1)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _publish_owner(path: Path, owner: dict[str, int | str] | None) -> None:
    """Publish the synthetic stopped-owner observation for the fixture reader."""
    pending = path.with_suffix(".pending")
    pending.write_text(json.dumps(owner))
    pending.replace(path)


class ExecutorLifecycle(unittest.TestCase):
    """Exercise real command custody with independent ready-listener witnesses."""

    def setUp(self) -> None:
        """Require isolation and create owned fixtures plus an unrelated canary."""
        from guard import guard

        guard()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.script = self.directory / "children.py"
        self.script.write_text(CHILD)
        spec = importlib.util.spec_from_file_location("maintained_acceptance_run", HERE / "run.py")
        assert spec is not None and spec.loader is not None
        self.runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.runner)
        self.rows = []
        self.observation = {}
        self.addCleanup(self.rescue)
        canary_dir = self.directory / "canary"
        canary_dir.mkdir()
        self.canary = subprocess.Popen([sys.executable, self.script, canary_dir, "2", "canary"], start_new_session=True)
        self.addCleanup(self.close_canary)
        deadline = time.monotonic() + 3
        while not (canary_dir / "2.json").exists():
            if time.monotonic() >= deadline:
                self.fail("unrelated owner did not become ready")
            time.sleep(0.005)
        self.canary_row = json.loads((canary_dir / "2.json").read_text())
        self.assertTrue(listening(self.canary_row["port"]))

    def close_canary(self) -> None:
        """Close and reap only the canary created by this test."""
        if self.canary.poll() is None:
            self.canary.kill()
        self.canary.wait(timeout=3)

    def rescue(self) -> None:
        """Rescue exact fixture generations after saving passive observations."""
        # Never used as acceptance evidence. Signal only exact fresh generations.
        for row in self.rows:
            current = identity(row["pid"])
            if current and current["start"] == row["start"]:
                fd = os.pidfd_open(row["pid"])
                try:
                    current = identity(row["pid"])
                    if current and current["start"] == row["start"]:
                        signal.pidfd_send_signal(fd, signal.SIGKILL)
                finally:
                    os.close(fd)

    @contextmanager
    def _runner_context(self, lane: Callable[..., int]) -> Iterator[None]:
        """Select the real runner with a scenario-specific inert command lane.

        Args:
            lane: Test lane supplying the native command at the execute seam.

        Yields:
            Control with output and argv scoped to this test only.
        """
        with (
            patch.object(self.runner, "OUT", self.directory),
            patch.object(csp, "run", lane),
            patch.object(sys, "argv", ["run.py", "default", "--python", sys.executable]),
        ):
            yield

    def invoke(self, mode: str = "timeout") -> None:
        """Run a ready detached tree and verify native and cleanup outcomes.

        Args:
            mode: Ordinary exit, nonzero exit, signal, timeout or interruption.
        """
        ready = threading.Event()
        errors = []

        def observe():
            deadline = time.monotonic() + 3
            try:
                while time.monotonic() < deadline:
                    paths = [self.directory / f"{n}.json" for n in range(3)]
                    try:
                        rows = [json.loads(p.read_text()) for p in paths]
                    except (FileNotFoundError, json.JSONDecodeError):
                        time.sleep(0.005)
                        continue
                    self.rows = rows
                    # The exited root may already be gone in the nonzero control.
                    self.assertTrue(all(listening(r["port"]) for r in rows))
                    ready.set()
                    (self.directory / "observed").touch()
                    if mode == "interrupt":
                        os.kill(os.getpid(), signal.SIGINT)
                    return
                raise AssertionError("owned listeners never became ready")
            except BaseException as exc:
                errors.append(exc)

        observer = threading.Thread(target=observe)
        observer.start()
        command = [sys.executable, self.script, self.directory, "0", mode]

        def _external_lane(env: dict[str, str], execute: Callable[..., int], case: str | None) -> int:
            return execute(command, "owned-control", 4, env)

        try:
            with self._runner_context(_external_lane):
                if mode == "timeout":
                    with self.assertRaises(subprocess.TimeoutExpired):
                        self.runner.main()
                elif mode == "interrupt":
                    with self.assertRaises(KeyboardInterrupt):
                        self.runner.main()
                else:
                    self.assertEqual(self.runner.main(), 0 if mode == "normal" else 1)
        finally:
            observer.join(4)
            self.observation = {
                "ready": ready.is_set(),
                "readiness_errors": [str(error) for error in errors],
                "owned": self.rows,
                "after": [identity(r["pid"]) for r in self.rows],
                "ports_open": [listening(r["port"]) for r in self.rows],
                "canary_before": self.canary_row,
                "canary_after": identity(self.canary.pid),
                "canary_open": listening(self.canary_row["port"]),
            }
            receipt_path = self.directory / "acceptance-execution.json"
            if receipt_path.exists():
                self.observation["execution"] = json.loads(receipt_path.read_text())
            out = Path("/run/test/artifacts") / (self.id() + ".json")
            out.write_text(json.dumps(self.observation, indent=2))
            self.assertFalse(observer.is_alive())
            self.assertEqual(errors, [])
            self.assertTrue(ready.is_set(), "No live readiness witness")
        self.assertFalse(any(self.observation["ports_open"]), self.observation)
        self.assertEqual(self.observation["after"], [None, None, None], self.observation)
        self.assertTrue(self.observation["canary_open"])
        self.assertEqual(self.observation["canary_after"]["start"], self.canary_row["start"])
        self.assertIsNone(self.canary.poll())
        receipt = json.loads((self.directory / "acceptance-execution.json").read_text())
        self.assertEqual(len(receipt["commands"]), 1)
        command = receipt["commands"][0]
        self.assertEqual(command["outcome"], {"timeout": "timeout", "interrupt": "cancelled"}.get(mode, "exited"))
        self.assertEqual(
            command["exit"], {"timeout": -9, "interrupt": -9, "exit": 37, "signal": -15, "normal": 0}[mode]
        )
        self.assertEqual(command["timeout_seconds"], 4)
        self.assertTrue(command["ownership"]["cleanup_complete"])
        self.assertTrue(all(receipt["cleanup"].values()))
        self.observation["command_receipt"] = command
        out.write_text(json.dumps(self.observation, indent=2))

    def _stopped_handoff(self, mode: str) -> None:
        """Observe a stopped exact owner before any test-owned rescue.

        Args:
            mode: Small, large or interrupted large request scenario.
        """
        directory = self.directory / mode
        directory.mkdir()
        owner = None
        with (directory / "controller.log").open("w") as log:
            controller = subprocess.Popen(
                [sys.executable, __file__, "--handoff", str(directory), mode],
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            try:
                deadline = time.monotonic() + 3
                while not (directory / "owner.json").exists():
                    self.assertIsNone(controller.poll())
                    self.assertLess(time.monotonic(), deadline)
                    time.sleep(0.005)
                owner = json.loads((directory / "owner.json").read_text())
                # Existing .2 execution + 5 cleanup + 1 delivery; .8 only
                # bounds this independent observer, never the executor.
                try:
                    controller.wait(timeout=7)
                except subprocess.TimeoutExpired:
                    pass
                receipt_path = directory / "acceptance-execution.json"
                observation = {
                    "controller_exit_before_rescue": controller.poll(),
                    "receipt_before_rescue": json.loads(receipt_path.read_text()) if receipt_path.exists() else None,
                    "owner_before_rescue": identity(owner["pid"]),
                    "native_started_before_rescue": (directory / "must-not-start").exists(),
                    "canary_after": identity(self.canary.pid),
                    "canary_open": listening(self.canary_row["port"]),
                    "rescue_before_observation": False,
                }
                output = Path("/run/test/artifacts") / (self.id() + "-" + mode + ".json")
                output.write_text(json.dumps(observation, indent=2))
                current = identity(owner["pid"])
                self.assertIsNotNone(current)
                self.assertEqual(current["start"], owner["start"])
                fd = os.pidfd_open(owner["pid"])
                try:
                    self.assertEqual(identity(owner["pid"])["start"], owner["start"])
                    signal.pidfd_send_signal(fd, signal.SIGCONT)
                finally:
                    os.close(fd)
                controller.wait(timeout=8)
                observation["native_started_after_rescue"] = (directory / "must-not-start").exists()
                observation["controller_exit_after_rescue"] = controller.returncode
                output.write_text(json.dumps(observation, indent=2))
                self.assertIsNotNone(observation["controller_exit_before_rescue"], "Unbounded handoff")
                receipt = observation["receipt_before_rescue"]
                self.assertIsNotNone(receipt, "Missing command failure receipt before rescue")
                command = receipt["commands"][0]
                self.assertIsNone(command["exit"])
                self.assertIn(command["exception"]["type"], {"TimeoutExpired", "KeyboardInterrupt"})
                self.assertFalse(command.get("ownership", {}).get("cleanup_complete", False))
                self.assertFalse(observation["native_started_before_rescue"])
                self.assertFalse(observation["native_started_after_rescue"])
                self.assertTrue(observation["canary_open"])
                self.assertEqual(observation["canary_after"]["start"], self.canary_row["start"])
            finally:
                if controller.poll() is None:
                    controller.kill()
                    controller.wait(timeout=3)
                if owner is not None:
                    current = identity(owner["pid"])
                    if current and current["start"] == owner["start"]:
                        fd = os.pidfd_open(owner["pid"])
                        try:
                            if identity(owner["pid"])["start"] == owner["start"]:
                                signal.pidfd_send_signal(fd, signal.SIGKILL)
                        finally:
                            os.close(fd)

    def test_large_request_handoff_is_bounded_without_rejecting_valid_env(self) -> None:
        """Keep exec-valid large requests supported and stopped handoffs bounded."""
        from owned_command import run_owned

        record = {}
        env = dict(os.environ, **{f"OWNED_LARGE_{n}": "x" * 32768 for n in range(16)})
        with (self.directory / "positive.log").open("w") as log:
            code = run_owned(
                [sys.executable, "-c", "print('valid-large-env')"],
                cwd=ROOT,
                env=env,
                stdout=log,
                timeout=3,
                receipt_path=self.directory / "positive.ownership.json",
                record=record,
            )
        (Path("/run/test/artifacts") / (self.id() + "-positive.json")).write_text(json.dumps(record, indent=2))
        self.assertEqual(code, 0)
        self.assertTrue(record["ownership"]["cleanup_complete"])
        for mode in ("small", "large"):
            with self.subTest(mode=mode):
                self._stopped_handoff(mode)

    def test_interrupted_full_handoff_cancels_without_blocking_delivery(self) -> None:
        """Interrupt a real full request socket without blocking cancellation."""
        self._stopped_handoff("interrupt")

    def test_timeout_closes_detached_descendants_before_native_probe(self) -> None:
        """Timeout closes detached descendants before native probe."""
        self.invoke()

    def test_normal_completion_drains_strays_and_preserves_zero(self) -> None:
        """Normal completion drains strays and preserves zero."""
        self.invoke("normal")

    def test_nonzero_exit_drains_strays_without_hiding_failure(self) -> None:
        """Nonzero exit drains strays without hiding failure."""
        self.invoke("exit")

    def test_native_signal_is_not_translated_to_success(self) -> None:
        """Native signal is not translated to success."""
        self.invoke("signal")

    def test_keyboard_interrupt_drains_before_native_probe(self) -> None:
        """Keyboard interrupt drains before native probe."""
        self.invoke("interrupt")

    def test_spawn_exception_records_failure_without_native_exit(self) -> None:
        """Spawn exception records failure without native exit."""
        from owned_command import OwnershipError

        def _external_lane(env: dict[str, str], execute: Callable[..., int], case: str | None) -> int:
            return execute(["/does-not-exist/owned-command"], "spawn-failure", 4, env)

        with self._runner_context(_external_lane):
            with self.assertRaises(OwnershipError):
                self.runner.main()
        receipt = json.loads((self.directory / "acceptance-execution.json").read_text())
        command = receipt["commands"][0]
        self.assertIsNone(command["exit"])
        self.assertEqual(command["outcome"], "owner_error")
        self.assertEqual(command["ownership"]["error"]["type"], "FileNotFoundError")
        self.assertTrue(command["ownership"]["cleanup_complete"])
        self.assertTrue(listening(self.canary_row["port"]))
        (Path("/run/test/artifacts") / (self.id() + ".json")).write_text(json.dumps(receipt, indent=2))

    def test_expired_budget_does_not_start_a_command(self) -> None:
        """Expired budget does not start a command."""
        marker = self.directory / "must-not-exist"

        def _external_lane(env: dict[str, str], execute: Callable[..., int], case: str | None) -> int:
            return execute(
                [sys.executable, "-c", "from pathlib import Path;Path(" + repr(str(marker)) + ").touch()"],
                "expired",
                0,
                env,
            )

        with self._runner_context(_external_lane):
            with self.assertRaises(subprocess.TimeoutExpired):
                self.runner.main()
        self.assertFalse(marker.exists())
        receipt = json.loads((self.directory / "acceptance-execution.json").read_text())
        command = receipt["commands"][0]
        self.assertIsNone(command["exit"])
        self.assertEqual(command["outcome"], "timeout")
        self.assertEqual(command["ownership"]["children"], [])
        self.assertTrue(command["ownership"]["cleanup_complete"])
        (Path("/run/test/artifacts") / (self.id() + ".json")).write_text(json.dumps(receipt, indent=2))

    def test_foreign_and_stale_generation_claims_are_refused(self) -> None:
        """Foreign and stale generation claims are refused."""
        from owned_command import OwnershipError, _claim, _identity

        original = _identity(self.canary.pid)
        with self.assertRaises(OwnershipError):
            _claim(os.getpid())  # Not this process's child.
        with self.assertRaises(OwnershipError):
            _claim(self.canary.pid, {**original, "start": "stale-generation"})
        fd, observed = _claim(self.canary.pid, original)
        os.close(fd)  # Positive generation claim; no signal is sent.
        self.assertEqual(observed, original)
        self.assertTrue(listening(self.canary_row["port"]))
        (Path("/run/test/artifacts") / (self.id() + ".json")).write_text(
            json.dumps(
                {
                    "before": original,
                    "after": _identity(self.canary.pid),
                    "foreign_refused": True,
                    "stale_refused": True,
                    "pid_reuse_forced": False,
                },
                indent=2,
            )
        )

    def test_high_descriptor_channel_keeps_ready_descendants_owned(self) -> None:
        """High descriptor channel keeps ready descendants owned."""
        descriptors = []
        try:
            while not descriptors or descriptors[-1] < 1100:
                descriptors.append(os.open("/dev/null", os.O_RDONLY))
            self.invoke("normal")
            self.assertGreaterEqual(self.observation["command_receipt"]["ownership"]["controller_fd"], 1024)
            self.assertEqual(os.fstat(descriptors[-1]).st_rdev, os.stat("/dev/null").st_rdev)
        finally:
            for descriptor in descriptors:
                os.close(descriptor)

    def test_same_generation_can_change_session_without_losing_custody(self) -> None:
        """Same generation can change session without losing custody."""
        from owned_command import _claim, _identity

        ready, release, changed = [self.directory / name for name in ("ready", "release", "changed")]
        code = (
            f"from pathlib import Path;import os,time;Path({str(ready)!r}).touch();\n"
            f"while not Path({str(release)!r}).exists(): time.sleep(.005)\n"
            f"os.setsid();Path({str(changed)!r}).touch();time.sleep(10)"
        )
        child = subprocess.Popen([sys.executable, "-c", code])
        try:
            deadline = time.monotonic() + 3
            while not ready.exists():
                if time.monotonic() >= deadline:
                    self.fail("child not ready")
                time.sleep(0.005)
            before = _identity(child.pid)
            release.touch()
            while not changed.exists():
                if time.monotonic() >= deadline:
                    self.fail("child did not change session")
                time.sleep(0.005)
            self.assertNotEqual(_identity(child.pid)["sid"], before["sid"])
            fd, after = _claim(child.pid, before)
            os.close(fd)
            self.assertEqual(after["start"], before["start"])
        finally:
            child.kill()
            child.wait(timeout=3)

    def test_controller_death_closes_detached_listeners_without_test_rescue(self) -> None:
        """Controller death closes detached listeners without test rescue."""
        log = (self.directory / "controller.log").open("w")
        self.addCleanup(log.close)
        controller = subprocess.Popen(
            [sys.executable, __file__, "--controller", str(self.directory), str(self.script)],
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + 3
            while True:
                try:
                    self.rows = [json.loads((self.directory / f"{n}.json").read_text()) for n in range(3)]
                    break
                except (FileNotFoundError, json.JSONDecodeError):
                    if time.monotonic() >= deadline:
                        self.fail("controller children not ready")
                    time.sleep(0.005)
            self.assertTrue(all(listening(r["port"]) for r in self.rows))
            (self.directory / "observed").touch()
            controller_identity = identity(controller.pid)
            controller.kill()  # Exact fresh Popen; no process search or group kill.
            self.assertEqual(controller.wait(timeout=3), -9)
            deadline = time.monotonic() + 6
            receipt = {}
            while time.monotonic() < deadline:
                try:
                    receipt = json.loads((self.directory / "parent-death.ownership.json").read_text())
                except FileNotFoundError:
                    pass
                if receipt.get("cleanup_complete"):
                    break
                time.sleep(0.005)
            observation = {
                "controller": controller_identity,
                "controller_exit": controller.returncode,
                "owned": self.rows,
                "after": [identity(r["pid"]) for r in self.rows],
                "ports_open": [listening(r["port"]) for r in self.rows],
                "canary_before": self.canary_row,
                "canary_after": identity(self.canary.pid),
                "canary_open": listening(self.canary_row["port"]),
                "ownership": receipt,
            }
            (Path("/run/test/artifacts") / (self.id() + ".json")).write_text(json.dumps(observation, indent=2))
            self.assertTrue(receipt["cleanup_complete"])
            self.assertEqual(receipt["outcome"], "cancelled")
            self.assertEqual(receipt["cancellation"], "controller_eof")
            self.assertEqual(observation["after"], [None, None, None])
            self.assertFalse(any(observation["ports_open"]))
            self.assertTrue(observation["canary_open"])
            self.assertEqual(observation["canary_after"]["start"], self.canary_row["start"])
        finally:
            if controller.poll() is None:
                controller.kill()
                controller.wait(timeout=3)


class FixturePublication(unittest.TestCase):
    """Keep fixture readiness separate from an in-progress JSON write."""

    def setUp(self) -> None:
        """Require isolation and allocate a private publication directory."""
        from guard import guard

        guard()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)

    def test_owner_json_is_published_only_after_complete_write(self) -> None:
        """An open, incomplete fixture write must not announce reader readiness."""
        target = self.directory / "owner.json"
        owner = identity(os.getpid())
        opened, release = threading.Event(), threading.Event()
        failures = []
        original = Path.write_text

        def held_write(path: Path, data: str, *args, **kwargs) -> int:
            if path.parent != self.directory or not path.name.startswith("owner."):
                return original(path, data, *args, **kwargs)
            with path.open("w") as stream:
                opened.set()
                if not release.wait(3):
                    raise RuntimeError("fixture publication was not released")
                return stream.write(data)

        def publish() -> None:
            try:
                _publish_owner(target, owner)
            except BaseException as error:
                failures.append(error)

        writer = threading.Thread(target=publish)
        with patch.object(Path, "write_text", held_write):
            writer.start()
            try:
                self.assertTrue(opened.wait(3), "Fixture writer did not open")
                self.assertFalse(target.exists(), "Incomplete owner JSON became visible")
            finally:
                release.set()
                writer.join(3)
        self.assertFalse(writer.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(json.loads(target.read_text()), owner)


if __name__ == "__main__":
    if sys.argv[1:2] == ["--handoff"]:
        import owned_command
        import run as runner

        directory, mode = Path(sys.argv[2]), sys.argv[3]
        real_popen = subprocess.Popen

        def _paused(argv, *args, **kwargs):
            process = real_popen(argv, *args, **kwargs)
            if len(argv) < 4 or str(argv[3]) != str(HERE / "owned_command.py"):
                return process
            fd = os.pidfd_open(process.pid)
            try:
                signal.pidfd_send_signal(fd, signal.SIGSTOP)
            finally:
                os.close(fd)
            os.waitpid(process.pid, os.WUNTRACED)
            _publish_owner(directory / "owner.json", identity(process.pid))
            if mode == "interrupt":

                def interrupt():
                    time.sleep(0.05)
                    os.kill(os.getpid(), signal.SIGINT)

                threading.Thread(target=interrupt).start()
            return process

        def _handoff_lane(env: dict[str, str], execute: Callable[..., int], case: str | None) -> int:
            child_env = dict(env)
            if mode != "small":
                child_env.update({f"OWNED_LARGE_{n}": "x" * 32768 for n in range(16)})
            marker = directory / "must-not-start"
            return execute(
                [sys.executable, "-c", f"from pathlib import Path;Path({str(marker)!r}).touch()"],
                "handoff",
                0.2,
                child_env,
            )

        with (
            patch.object(owned_command.subprocess, "Popen", _paused),
            patch.object(runner, "OUT", directory),
            patch.object(csp, "run", _handoff_lane),
            patch.object(sys, "argv", ["run.py", "default", "--python", sys.executable]),
        ):
            raise SystemExit(runner.main())
    if sys.argv[1:2] == ["--controller"]:
        directory, script = map(Path, sys.argv[2:])
        import run as runner

        def _external_lane(env: dict[str, str], execute: Callable[..., int], case: str | None) -> int:
            return execute([sys.executable, script, directory, "0", "hold"], "parent-death", 30, env)

        with (
            patch.object(runner, "OUT", directory),
            patch.object(csp, "run", _external_lane),
            patch.object(sys, "argv", ["run.py", "default", "--python", sys.executable]),
        ):
            raise SystemExit(runner.main())
    unittest.main(verbosity=2)
