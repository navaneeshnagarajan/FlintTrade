"""Static-bytecode preparation and real normal-factory startup regressions.

Run only in the maintained isolated namespace with its qualified interpreter.
No factory, authority check or cleanup owner is replaced.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import socket
import subprocess
import sys
import unittest
import uuid
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[3]
HERE = ROOT / "tools/reticle"
CACHE = Path("/run/test/cache/reticle-python")


class ProtocolStartup(unittest.TestCase):
    """Verify static preparation and checked-bytecode normal-factory startup."""

    def helper(self) -> ModuleType:
        """Load only the static preparation helper, not application modules."""
        path = HERE / "prepare_python.py"
        self.assertTrue(path.is_file(), "Public normal-factory driver lacks static bytecode preparation")
        spec = importlib.util.spec_from_file_location("reticle_prepare_python", path)
        self.assertIsNotNone(spec)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_static_preparation_never_executes_source_and_rejects_stale_bytecode(self) -> None:
        """Checked hashes, not timestamp reuse, bind prepared executable bytes."""
        helper = self.helper()
        root = Path("/run/test/cache") / ("static-control-" + uuid.uuid4().hex)
        root.mkdir()
        source = root / "static_operand.py"
        marker = root / "must-not-exist"
        source.write_text(f'from pathlib import Path\nPath({str(marker)!r}).write_text("executed")\nvalue = 1\n')
        before = source.read_bytes()
        cache = root / "bytecode"
        records = helper.compile_sources([source], cache)
        self.assertEqual(source.read_bytes(), before)
        self.assertFalse(marker.exists(), "Preparation executed the source")
        self.assertEqual(len(records), 1)
        compiled = Path(records[0]["bytecode"]).read_bytes()
        self.assertEqual(int.from_bytes(compiled[4:8], "little"), 3)
        self.assertEqual(compiled[8:16], importlib.util.source_hash(before))
        self.assertEqual(records[0]["source_sha256"], hashlib.sha256(before).hexdigest())
        stamp = source.stat()
        source.write_bytes(before.replace(b"value = 1", b"value = 2"))
        os.utime(source, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        code = "import sys;sys.path.insert(0,sys.argv[1]);import static_operand;print(static_operand.value)"
        result = subprocess.run(
            [sys.executable, "-B", "-X", "pycache_prefix=" + str(cache), "-c", code, str(root)],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        self.assertEqual(result.stdout.strip(), "2")
        self.assertTrue(marker.exists(), "The ordinary import did not execute its source")
        with self.assertRaises(FileExistsError):
            helper.compile_sources([source], cache)

    def test_normal_factory_reads_prepared_source_and_closes_same_owners(self) -> None:
        """A fresh real factory must not recompile its immutable import closure."""
        self.helper()
        prepared = subprocess.run(
            [sys.executable, "-B", str(HERE / "prepare_python.py")], capture_output=True, text=True, timeout=180
        )
        Path("/run/test/artifacts/startup-preparation.log").write_text(prepared.stdout + prepared.stderr)
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        key = hashlib.sha256(uuid.uuid4().bytes).hexdigest()
        output = Path("/run/test/artifacts/playwright") / ("protocol-startup-" + key) / "normal-core"
        audit = output.parent / "compiled-sources.json"
        code = """import json
import pathlib
import runpy
import sys
main, output = sys.argv[1], pathlib.Path(sys.argv[2])
sys.argv = [main, *sys.argv[3:]]
compiled = []
def observe(event: str, values: tuple[object, ...]) -> None:
    '''Record compilation events without altering source loading.

    Args:
        event: Interpreter audit event name.
        values: Positional arguments supplied by the interpreter audit hook.
    '''
    if event == 'compile' and str(values[1]).endswith('.py'):
        caller = sys._getframe(1)
        frame = caller
        source_loader = False
        while frame is not None:
            source_loader |= (frame.f_code.co_filename == '<frozen importlib._bootstrap_external>'
                              and frame.f_code.co_name == 'source_to_code')
            frame = frame.f_back
        compiled.append({'source': str(values[1]), 'source_loader': source_loader,
                         'caller': [caller.f_code.co_filename, caller.f_code.co_name]})
sys.addaudithook(observe)
try:
    runpy.run_path(main, run_name='__main__')
finally:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(compiled, indent=2))
"""
        server = HERE / "harness/core-server.py"
        env = dict(
            os.environ,
            PYTHONPYCACHEPREFIX=str(CACHE),
            FLINTTRADE_E2E_SOURCE_ROOT=str(ROOT),
            FLINTTRADE_E2E_CORE_STATE=str(output.parent / "bootstrap.json"),
            PYTHONPATH=os.pathsep.join([str(ROOT), *map(str, ROOT.glob("packages/*/*/src"))]),
        )
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                "-c",
                code,
                str(server),
                str(audit),
                "--port",
                "5100",
                "--case-key",
                key,
                "--output",
                str(output),
            ],
            input="STOP\n",
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )
        (output.parent / "server.log").write_text(result.stdout + result.stderr)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("R24_CORE_READY", result.stdout)
        startup = json.loads((output / "startup.json").read_text())
        self.assertEqual(startup["factory"], "flinttrade_core.app.create_flask_app")
        self.assertEqual(startup["case_key"], key)
        self.assertIs(startup["full_operator_session"], True)
        self.assertIs(startup["backend_broker_lease_ready"], False)
        self.assertEqual(startup["provider_calls_during_startup"], 0)
        self.assertIs(startup["http_limiter_enabled"], True)
        shutdown = json.loads((output / "shutdown.json").read_text())
        self.assertEqual(shutdown["lifecycle"], "_DesktopShutdownRecoveryOwner.release")
        self.assertEqual(shutdown["remaining_threads"], [])
        for field in ["admission_drained", "listener_stopped", "listener_closed_probe"]:
            self.assertIs(shutdown[field], True)
        self.assertIn("SYSTEM_INCIDENTS", shutdown["owners"])
        self.assertTrue(all(row["closed"] for row in shutdown["owners"].values()))
        with socket.socket() as check:
            self.assertNotEqual(check.connect_ex(("127.0.0.1", 5100)), 0)
        # Count actual import-loader compilation, not legitimate dynamic AST
        # inspection (for example AnyIO's lazy-import map) or runpy's __main__.
        # Keep every event above; observe only after genuine owner cleanup.
        compiled = [row for row in json.loads(audit.read_text()) if row["source_loader"]]
        self.assertEqual(compiled, [], "Normal factory recompiled immutable Python inputs")


if __name__ == "__main__":
    unittest.main(verbosity=2)
