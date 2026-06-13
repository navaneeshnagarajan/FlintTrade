"""Native-desktop backend entry point.

This is the process the Tauri desktop shell launches as a bundled *sidecar*.
It serves the full FlintTrade backend — the gated order path, every REST
blueprint, and the built React terminal — on a loopback port, then blocks
until the parent process terminates it.

Design goals (distinct from :func:`flinttrade_core.app.FlintTradeApp.run`):

* **Lean and resilient when frozen.** PyInstaller bundles only what the
  serving path needs; the heavy automation loops (cron scheduler, Telegram
  bot, overnight optimiser) are deliberately *not* started here, so the
  packaged binary stays small and never fails to boot because an optional
  ML dependency could not be collected. Those features remain reachable
  per-request through their blueprints, which lazy-import their own deps and
  degrade gracefully when unavailable.
* **No ``.env`` dependency.** Configuration comes from ``workspace.json``
  under ``~/.flinttrade/`` (auto-created on first launch). Infrastructure
  defaults (OpenAlgo on ``127.0.0.1:5000``, empty API key) are baked into
  :class:`flinttrade_core.config.Settings`, so a fresh install runs with no
  files to edit — the user configures OpenAlgo, if they want it, from the
  in-app Settings panel.
* **Loopback only.** The server always binds ``127.0.0.1`` — never a routable
  interface — so the desktop backend is unreachable from the network.
* **Lifecycle handshake.** Once the listening socket is bound, a single
  ``FLINTTRADE_BACKEND_READY port=<port>`` line is written to stdout. The
  Tauri shell waits for that line (and/or polls the health endpoint) before
  pointing its window at ``http://127.0.0.1:<port>``.

Usage::

    python -m flinttrade_core.desktop            # serve on the default port
    python -m flinttrade_core.desktop --port 0   # ask the OS for a free port
    FLINTTRADE_BACKEND_PORT=5123 flinttrade-desktop-backend
"""

from __future__ import annotations

import argparse
import os
import sys

# Importing the app module first applies the UTF-8 stdout reconfigure and the
# frozen-mode sys.path / dist-path wiring (see ``flinttrade_core.app``).
from .app import create_flask_app
from .workspace import Workspace

#: Default loopback port for the desktop backend. Kept distinct from OpenAlgo's
#: 5000-5009 range (see CLAUDE.md). Overridable via ``--port`` or the
#: ``FLINTTRADE_BACKEND_PORT`` environment variable.
DEFAULT_PORT = 5100

#: Stdout sentinel the Tauri shell waits for before loading the UI.
READY_SENTINEL = "FLINTTRADE_BACKEND_READY"


def _ensure_workspace() -> Workspace:
    """Create ``~/.flinttrade/`` with defaults on first launch.

    A freshly installed desktop app has no workspace yet. Initialising it here
    means the very first boot writes ``workspace.json`` and the data/log/archive
    directories, so every downstream component (config, vault, audit log) finds
    the layout it expects without the user running any CLI command.

    Returns:
        The initialised :class:`Workspace`.
    """
    ws = Workspace()
    if not ws.is_initialized:
        ws.initialise()
    return ws


def _build_app() -> object:
    """Construct the Flask app with the full safety + order-routing surface.

    Mirrors the wiring :meth:`FlintTradeApp.start` performs, minus the async
    automation loops: a :class:`SafetySystem`, :class:`AuditLogger`, and
    :class:`OpenAlgoClient` are passed in so the gated order path and the
    safety endpoints are fully live. The broker router, credential vault,
    registry, and contract manager are self-bootstrapped inside
    :func:`create_flask_app` when not supplied.

    Each of these is best-effort: if a piece cannot be built (e.g. the engine
    package is unavailable in a stripped build), the app still serves with that
    capability degraded rather than refusing to boot.
    """
    safety = None
    audit = None
    client = None

    try:
        from flinttrade_data.audit_logger import AuditLogger  # noqa: PLC0415

        audit = AuditLogger()
        audit.log_event("DESKTOP_START")
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[desktop] audit logger unavailable: {exc}", file=sys.stderr)

    try:
        from .config import Settings  # noqa: PLC0415
        from .openalgo_client import OpenAlgoClient  # noqa: PLC0415

        client = OpenAlgoClient(Settings.from_env())
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[desktop] OpenAlgo client unavailable: {exc}", file=sys.stderr)

    try:
        from flinttrade_engine.safety import SafetyConfig, SafetySystem  # noqa: PLC0415

        safety = SafetySystem(SafetyConfig(check_market_hours=True))
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[desktop] safety system unavailable: {exc}", file=sys.stderr)

    return create_flask_app(safety=safety, audit=audit, client=client)


def _resolve_port(cli_port: int | None) -> int:
    """Resolve the listen port from the CLI arg, env, then the default.

    Args:
        cli_port: Value of ``--port`` (``None`` when the flag is absent).

    Returns:
        The port to bind. ``0`` means "let the OS choose a free port"; the
        actual bound port is reported in the ready handshake.
    """
    if cli_port is not None:
        return cli_port
    raw = os.environ.get("FLINTTRADE_BACKEND_PORT", "").strip()
    if raw:
        try:
            return int(raw)
        except ValueError:
            print(
                f"[desktop] ignoring non-integer FLINTTRADE_BACKEND_PORT={raw!r}",
                file=sys.stderr,
            )
    return DEFAULT_PORT


def serve(port: int) -> None:
    """Bind the loopback socket and serve forever (blocking).

    Uses Waitress — the same production WSGI server the rest of FlintTrade
    runs on — created explicitly so the listening socket is open *before* the
    ready handshake is emitted. This removes the race where the Tauri shell
    would otherwise poll a port that is not yet accepting connections.

    Args:
        port: Loopback port to bind. ``0`` asks the OS for a free port.
    """
    app = _build_app()

    from waitress.server import create_server  # noqa: PLC0415

    server = create_server(app, host="127.0.0.1", port=port, ident="FlintTrade", threads=8)
    bound_port = server.effective_port

    # Handshake — one line, flushed, so the parent can read it synchronously.
    print(f"{READY_SENTINEL} port={bound_port}", flush=True)

    try:
        server.run()
    except (KeyboardInterrupt, SystemExit):  # pragma: no cover - signal path
        pass


def main(argv: list[str] | None = None) -> None:
    """CLI entry point — parse args, init workspace, serve.

    Args:
        argv: Argument vector (defaults to ``sys.argv[1:]``).
    """
    parser = argparse.ArgumentParser(
        prog="flinttrade-desktop-backend",
        description="FlintTrade native-desktop backend (loopback API + bundled terminal).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Loopback port to bind (default: $FLINTTRADE_BACKEND_PORT or 5100; 0 = OS-chosen).",
    )
    args = parser.parse_args(argv)

    _ensure_workspace()
    serve(_resolve_port(args.port))


if __name__ == "__main__":
    main()
