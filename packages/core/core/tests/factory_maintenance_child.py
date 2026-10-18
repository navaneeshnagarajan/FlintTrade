"""Disposable real-entrypoint child for factory maintenance integration tests."""
from __future__ import annotations

import json
import os
import secrets
import sys
import threading
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import urlopen


def main():
    kind, history, directory = sys.argv[1:]
    root = Path(directory)
    os.environ["HOME"] = str(root)
    for key in tuple(os.environ):
        if key.startswith(("FLINTTRADE_", "PYTEST_")) or key in {"DUCKDB_PATH", "SANDBOX_DB_PATH", "AUTH_STATE_DB"}:
            os.environ.pop(key)
    workspace = root / ".flinttrade"
    os.environ.update(FLINTTRADE_WORKSPACE_DIR=str(workspace), FLINTTRADE_HOME=str(workspace),
                      FLINTTRADE_INSTALLATION_STATE_DIR=str(root / ".flinttrade-installation"),
                      FLINTTRADE_API_KEY=secrets.token_urlsafe(32))
    # Exercise normal startup threads, with only external transport inert.
    import urllib.request
    def inert_urlopen(request, *args, **kwargs):
        url = request.full_url if hasattr(request, "full_url") else request
        if urlsplit(url).hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise URLError("synthetic external transport unavailable")
        return urlopen(request, *args, **kwargs)
    urllib.request.urlopen = inert_urlopen

    from flinttrade_core import app as core, desktop
    from flinttrade_core.backend_instance import acquire_backend_instance_lease
    from flinttrade_core.maintenance_history import initialise_fresh_history
    from flinttrade_core.workspace import Workspace

    lease = acquire_backend_instance_lease()
    if history == "fresh":
        assert initialise_fresh_history(workspace, lease)
    Workspace(home_dir=workspace).initialise()
    core.set_master_password(secrets.token_urlsafe(32))
    lease.release()
    owners = {}

    def record(app, port=None):
        for key in ("EXECUTION_SESSIONS", "PROTECTION_SERVICES", "MODEL_RUN_SERVICES", "DATA_RUNTIME"):
            owners[key] = app.config[key]
        owners["maintenance"] = app.extensions.get("flinttrade.maintenance")
        # Actual factory routes, no installer or authority injected by this child.
        assert app.test_client().get("/healthz").status_code == 200
        (root / "ready.json").write_text(json.dumps({"port": port, "maintenance": owners["maintenance"] is not None}))

    if kind == "async":
        runtime = core.FlintTradeApp()
        original_wait = runtime._wait_for_shutdown_result
        async def ready_wait():
            record(runtime._flask_app, int(runtime._flask_server_owner._server.effective_port))
            return await original_wait()
        runtime._wait_for_shutdown_result = ready_wait
        core._resolve_backend_port = lambda: 0
        runtime.run()
        assert runtime._stop_completed
    elif kind == "desktop":
        original = desktop._build_app
        def record_build(proof):
            app = original(proof)
            owners["app"] = app
            return app
        desktop._build_app = record_build
        desktop.serve(0, ready_writer=lambda line: record(owners["app"], int(line.split("port=")[1])))
    else:
        stopped = threading.Event()
        app = core._get_wsgi_app(shutdown_callback=stopped.set)
        record(app)
        assert stopped.wait(45)
        worker = app.extensions["flinttrade.wsgi_stop_thread"]
        worker.join(5)
        assert not worker.is_alive()
    assert owners["EXECUTION_SESSIONS"].closed
    assert owners["MODEL_RUN_SERVICES"].closed
    assert owners["DATA_RUNTIME"].closed
    assert owners["PROTECTION_SERVICES"]._closed
    assert owners["maintenance"].closed.is_set()
    assert not owners["maintenance"].thread.is_alive()
    (root / "finished.json").write_text(json.dumps({"drained": True, "entries_rearmed": False}))


if __name__ == "__main__":
    main()
