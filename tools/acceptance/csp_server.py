"""Anonymous normal factory for the installed CSP tests; no dev server or APIs."""

from __future__ import annotations

import sys

if sys.flags.optimize:
    raise RuntimeError("Python optimisation refused before CSP factory import")

import argparse
import json
import os
import re
import secrets
import socket
import threading
import time
from pathlib import Path

from guard import guard


def main() -> None:
    guard()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-key", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch("[0-9a-f]{64}", args.case_key):
        parser.error("Expected a sha256 case identity")
    if not args.output.resolve().is_relative_to("/run/test/artifacts/playwright"):
        parser.error("CSP evidence must be test-scoped under the public artifact root")
    args.output.mkdir(parents=True, exist_ok=False)
    workspace = Path("/run/test/home/workspaces") / args.case_key
    workspace.mkdir(mode=0o700, parents=True, exist_ok=False)
    os.environ["FLINTTRADE_WORKSPACE_DIR"] = str(workspace)
    os.environ["FLINTTRADE_API_KEY"] = secrets.token_urlsafe(32)
    os.environ["FLINTTRADE_FRONTEND_DIST"] = "/run/test/artifacts/installed-dist"
    master = workspace / "master_password"
    master.write_text(secrets.token_urlsafe(48))
    master.chmod(0o600)
    with socket.socket() as check:
        check.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        check.bind(("127.0.0.1", 5173))
    network = []
    (args.output / "network.json").write_text("[]\n")

    def audit(event, details):
        if event == "socket.connect":
            address = details[1]
            allowed = isinstance(address, tuple) and address[0] == "127.0.0.1" and address[1] == 5173
            network.append({"address": str(address), "allowed": allowed})
            (args.output / "network.json").write_text(json.dumps(network, indent=2))
            if not allowed:
                raise RuntimeError("Non-owned transport is forbidden in CSP acceptance")

    sys.addaudithook(audit)
    from flinttrade_core.app import _close_runtime_request_admission, _run_flask_server, create_flask_app
    from flinttrade_core.csp import CSP_POLICY
    from flinttrade_core.desktop import _DesktopShutdownRecoveryOwner

    initial_threads = {thread.ident for thread in threading.enumerate()}
    app = create_flask_app()
    listener = None
    recovery = _DesktopShutdownRecoveryOwner(app)
    try:
        if (
            app.config["BACKEND_LEASE_READY"]
            or app.config["DATA_RUNTIME"].active_sources != 0
            or "SERVICE_TASK_DISPATCHER" in app.config
        ):
            raise RuntimeError("Anonymous frozen normal factory required")
        listener = _run_flask_server(app, port=5173, host="127.0.0.1")
        (args.output / "startup.json").write_text(
            json.dumps(
                {
                    "factory": "flinttrade_core.app.create_flask_app",
                    "pid": os.getpid(),
                    "workspace": str(workspace),
                    "case_key": args.case_key,
                    "port": 5173,
                    "account_created": False,
                    "native_frozen": True,
                    "csp_policy": CSP_POLICY,
                    "http_limiter_enabled": app.config.get("RATELIMIT_ENABLED", True),
                },
                indent=2,
            )
        )
        source_root = Path(__file__).resolve().parents[2]
        origins = {
            name: str(module.__file__)
            for name, module in sys.modules.items()
            if name.startswith(("flinttrade_", "packages.")) and getattr(module, "__file__", None)
        }
        (args.output / "source-origins.json").write_text(json.dumps(origins, indent=2))
        if any(
            path.endswith(".py") and not Path(path).resolve().is_relative_to(source_root) for path in origins.values()
        ):
            raise RuntimeError("Factory imported application source outside this checkout")
        print("R33_CORE_READY", flush=True)
        if sys.stdin.readline().strip() != "STOP":
            raise RuntimeError("Owned CSP fixture ended without STOP")
    finally:
        result = {
            "admission_drained": False,
            "listener_stopped": False,
            "owners_released": False,
            "lifecycle": "_DesktopShutdownRecoveryOwner.release",
        }
        try:
            tracker = _close_runtime_request_admission(app)
            result["admission_drained"] = tracker.wait_for_idle(timeout=10)
            result["listener_stopped"] = listener.stop(timeout=10) if listener else True
            recovery.release(deadline=time.monotonic() + 20)
            result["owners_released"] = True
        finally:
            for thread in threading.enumerate():
                if thread.ident not in initial_threads:
                    thread.join(timeout=2)
            with socket.socket() as check:
                result["listener_closed_probe"] = check.connect_ex(("127.0.0.1", 5173)) != 0
            result["remaining_threads"] = [
                thread.name for thread in threading.enumerate() if thread.ident not in initial_threads
            ]
            (args.output / "shutdown.json").write_text(json.dumps(result, indent=2))
        if (
            not all(
                result[key]
                for key in ["admission_drained", "listener_stopped", "listener_closed_probe", "owners_released"]
            )
            or result["remaining_threads"]
        ):
            raise RuntimeError("CSP factory cleanup incomplete: " + json.dumps(result))


if __name__ == "__main__":
    main()
