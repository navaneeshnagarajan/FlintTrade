"""Real normal-factory Reticle fixture STOP/EOF custody regressions.

Run inside the maintained no-egress launcher with the explicitly qualified
interpreter. The process owns synthetic state and inert external transports.
"""
from pathlib import Path
import hashlib
import json
import os
import socket
import subprocess
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[3]


class CoreLifecycle(unittest.TestCase):
    """Verify that STOP and EOF release every real normal-factory owner."""

    def exercise(self, stop: str) -> None:
        """Exercise the fixture protocol and check owner and listener cleanup.

        Args:
            stop: Protocol input; an empty string closes stdin without STOP.

        Raises:
            AssertionError: The fixture protocol or same-owner cleanup differs.
            subprocess.TimeoutExpired: The existing fixture deadline expires.
        """
        python = os.environ.get('FLINTTRADE_E2E_PYTHON', '')
        self.assertTrue(python, 'Explicit qualified interpreter required')
        key = hashlib.sha256(uuid.uuid4().bytes).hexdigest()
        output = Path('/run/test/artifacts/playwright') / ('reticle-lifecycle-' + key) / 'normal-core'
        env = dict(os.environ, FLINTTRADE_E2E_SOURCE_ROOT=str(ROOT),
                   FLINTTRADE_E2E_CORE_STATE=str(output.parent / 'bootstrap.json'),
                   PYTHONPATH=os.pathsep.join([str(ROOT), *map(str, ROOT.glob('packages/*/*/src'))]))
        result = subprocess.run([
            python, str(ROOT / 'tools/reticle/harness/core-server.py'),
            '--port', '5100', '--case-key', key, '--output', str(output),
        ], input=stop, capture_output=True, text=True, env=env, timeout=60)
        output.parent.mkdir(parents=True, exist_ok=True)
        (output.parent / 'server.log').write_text(result.stdout + result.stderr)
        self.assertIn('R24_CORE_READY', result.stdout, result.stderr)
        shutdown = json.loads((output / 'shutdown.json').read_text())
        # Observe only: joining/draining here could repair the fixture under test.
        self.assertEqual(shutdown['remaining_threads'], [], shutdown)
        for field in ['admission_drained', 'listener_stopped', 'listener_closed_probe']:
            self.assertIs(shutdown[field], True, field)
        self.assertTrue(shutdown['owners'], shutdown)
        self.assertIn('SYSTEM_INCIDENTS', shutdown['owners'])
        self.assertTrue(all(row['closed'] for row in shutdown['owners'].values()), shutdown)
        self.assertEqual(result.returncode == 0, bool(stop), result.stderr)
        if not stop:
            self.assertIn('owned fixture ended without STOP', result.stderr)
        with socket.socket() as check:
            self.assertNotEqual(check.connect_ex(('127.0.0.1', 5100)), 0)
        with socket.socket() as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(('127.0.0.1', 5100))

    def test_stop_releases_every_real_factory_owner(self) -> None:
        """STOP succeeds only after every real factory owner is released."""
        self.exercise('STOP\n')

    def test_eof_refuses_protocol_but_releases_every_real_factory_owner(self) -> None:
        """EOF refuses the protocol while still releasing the same owners."""
        self.exercise('')


if __name__ == '__main__':
    unittest.main(verbosity=2)
