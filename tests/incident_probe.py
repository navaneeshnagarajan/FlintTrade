# Test source: GNU AGPL v3, as licensed in the repository LICENSE.
"""Synthetic normal-factory fixture for browser/native incident regressions.

No saved workspace, wire capture or recipient is loaded. Run only in a disposable
no-egress test environment. The caller owns the process and its temporary HOME.
"""

from __future__ import annotations

import argparse
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import time
from unittest.mock import MagicMock, patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
for source in ROOT.glob("packages/*/*/src"):
    sys.path.insert(0, str(source))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--native-wire", type=Path)
    mode.add_argument("--port", type=int)
    args = parser.parse_args()
    os.environ.pop("FLINTTRADE_DESKTOP", None)
    key = os.environ.get("INCIDENT_PROBE_API_KEY") or uuid4().hex
    os.environ["FLINTTRADE_API_KEY"] = key
    spec = importlib.util.spec_from_file_location("_incident_scratch", ROOT / "tests/scratch_workspace.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("Missing repository scratch-workspace fixture")
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    from flinttrade_core.app import create_flask_app
    from flinttrade_core.desktop import _DesktopShutdownRecoveryOwner

    with tempfile.TemporaryDirectory(prefix="flinttrade-incident-probe-") as temporary:
        workspace = Path(temporary) / "workspace"
        workspace.mkdir(mode=0o700)
        fixture.seed_master_password(workspace)
        os.environ["FLINTTRADE_WORKSPACE_DIR"] = str(workspace)
        app = create_flask_app(safety=MagicMock(order_reservations_durable=True), contract_manager=MagicMock())

        @app.get("/synthetic-incident-failure")
        def failure():
            return {"error": "inert"}, 503

        try:
            if args.native_wire:
                from flinttrade_core import desktop_notify

                wire = io.StringIO()
                with (
                    patch.dict(os.environ, {"FLINTTRADE_DESKTOP": "1"}),
                    patch.object(desktop_notify.sys, "stdout", wire),
                ):
                    client = app.test_client()
                    response = client.get("/synthetic-incident-failure", headers={"X-API-Key": key}, buffered=True)
                    assert response.status_code == 503
                    owner = app.config["SYSTEM_INCIDENTS"]
                    owner.deliver_pending()
                    receipt = next(
                        d for d in owner.snapshot()["incidents"][0]["deliveries"] if d["channel"] == "desktop"
                    )
                    owner.deliver_pending()
                    assert wire.getvalue().count("FLINTTRADE_NOTIFY\t") == 1
                    assert receipt["attempts"] == 1
                args.native_wire.write_text(json.dumps({"wire": wire.getvalue(), "receipt": receipt}))
            else:
                from werkzeug.serving import make_server

                server = make_server("127.0.0.1", args.port, app, threaded=True)
                signal.signal(signal.SIGTERM, lambda *unused: sys.exit(0))
                print("INCIDENT_HTTP_READY", flush=True)
                try:
                    server.serve_forever()
                finally:
                    server.server_close()
        finally:
            owner = app.config["SYSTEM_INCIDENTS"]
            _DesktopShutdownRecoveryOwner(app).release(deadline=time.monotonic() + 10)
            assert owner.closed
            print("INCIDENT_OWNER_CLOSED", flush=True)


if __name__ == "__main__":
    main()
