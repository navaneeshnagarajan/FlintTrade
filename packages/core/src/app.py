"""FlintTrade application entry point — wires all packages together.

Includes a lightweight Flask API server (port 5100) for FlintTrade-specific
endpoints that are separate from the OpenAlgo API (port 5000).

Usage:
    python packages/core/src/app.py
    # or: make start
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# UTF-8 stdout/stderr reconfigure — must happen BEFORE any import that may
# emit to the console (structlog, Flask, etc.).  On Windows the default
# console encoding is cp1252, which crashes when log records contain emojis
# or ANSI colour codes.  We flip stdout/stderr to UTF-8 early; if the
# attribute is not available (Python <3.7 / non-stream stdout) we fall back
# silently so this never breaks startup.
# ---------------------------------------------------------------------------
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass

import asyncio
import logging
import os
import secrets
import signal
import threading
from pathlib import Path
from typing import Any

# Ensure repo root is on sys.path for cross-package imports
_REPO_ROOT = str(Path(__file__).resolve().parents[3])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import hmac  # noqa: E402
import time  # noqa: E402

import structlog  # noqa: E402
from flask import Flask, g as _flask_g, jsonify, request  # noqa: E402
from flask_cors import CORS  # noqa: E402
from flask_limiter import Limiter  # noqa: E402
from flask_limiter.util import get_remote_address  # noqa: E402
import sentry_sdk  # noqa: E402
from sentry_sdk.integrations.flask import FlaskIntegration  # noqa: E402

from .config import Settings  # noqa: E402
from .openalgo_client import OpenAlgoClient  # noqa: E402
from .workspace import workspace_dir as _workspace_dir  # noqa: E402
from packages.data.src.audit_logger import AuditLogger  # noqa: E402
# engine imports are deferred into FlintTradeApp.__init__() to break the
# core↔engine circular import.  See PLC0415 comments throughout this file.
# Heavy optional modules are imported lazily inside FlintTradeApp.__init__()
# to avoid a 2-5 s startup penalty when ChromaDB / LLM / Telegram deps load.
# CronManager, TelegramBot, LLMClient, LLMConfig, RAGEngine

# Ensure the gateway src directory is on sys.path so bare gateway imports resolve.
_GATEWAY_SRC = str(Path(_REPO_ROOT) / "packages" / "gateway" / "src")
if _GATEWAY_SRC not in sys.path:
    sys.path.insert(0, _GATEWAY_SRC)

from packages.gateway.src.registry import BrokerRegistry  # noqa: E402
from packages.gateway.src.credentials import CredentialStore  # noqa: E402
from packages.gateway.src.auth import gateway_bp  # noqa: E402
from packages.gateway.src.contracts import ContractManager  # noqa: E402

logger = logging.getLogger("flinttrade")


def _reconnect_saved_accounts(
    registry: BrokerRegistry,
    credential_store: CredentialStore,
    reconnect_logger: logging.Logger,
) -> None:
    """Reconnect previously saved broker accounts on startup.

    Iterates over every account persisted in the CredentialStore and attempts
    to re-authenticate each one against the registry.  Failures are logged as
    warnings so that a single bad account does not block the rest.

    Args:
        registry: The live BrokerRegistry to populate with sessions.
        credential_store: The CredentialStore that holds persisted credentials.
        reconnect_logger: Logger instance to use for progress messages.
    """
    from packages.gateway.src.session import BrokerSession  # noqa: PLC0415

    saved = credential_store.list_accounts()
    if not saved:
        reconnect_logger.info("No saved broker accounts to reconnect")
        return

    reconnect_logger.info("Reconnecting %d saved broker account(s)...", len(saved))
    for acct in saved:
        account_id: str = acct["account_id"]
        broker: str = acct["broker"]
        label: str = acct["label"]
        try:
            creds = credential_store.retrieve(account_id)
            session = BrokerSession(account_id, broker, label)
            session.authenticate(creds)
            registry._sessions[account_id] = session
            if acct.get("is_primary"):
                registry._primary = account_id
            reconnect_logger.info("  Connected: %s (%s)", label, broker)
        except Exception as exc:
            reconnect_logger.warning("  Failed: %s (%s): %s", label, broker, exc)


def _read_version() -> str:
    """Read version from VERSION file at repo root."""
    version_file = Path(_REPO_ROOT) / "VERSION"
    if version_file.exists():
        return version_file.read_text().strip()
    return "0.0.0-dev"


# ---------------------------------------------------------------------------
# Master password — cached module-level so all call-sites share a single
# value within a process.  File-backed so it survives restarts.
# ---------------------------------------------------------------------------

_MASTER_PASSWORD: str | None = None


def _get_master_password() -> str:
    """Get or generate the credential-store master password.

    Priority (mirrors ``_get_jwt_secret`` in auth_routes.py):
      1. ``MASTER_PASSWORD`` environment variable.
      2. Persisted secret at ``~/.flinttrade/master_password``.
      3. Generate a fresh ``secrets.token_urlsafe(64)`` and persist it.

    If the file cannot be written (read-only filesystem, permission error)
    we still return the generated value so the current session can continue.
    Subsequent calls within the same process return the cached value.
    """
    global _MASTER_PASSWORD
    if _MASTER_PASSWORD:
        return _MASTER_PASSWORD

    # 1. Environment variable override
    env_password = os.environ.get("MASTER_PASSWORD", "")
    if env_password:
        _MASTER_PASSWORD = env_password
        return _MASTER_PASSWORD

    # 2. Read from persisted file
    password_file = _workspace_dir() / "master_password"
    try:
        if password_file.exists():
            stored = password_file.read_text().strip()
            if stored:
                _MASTER_PASSWORD = stored
                return _MASTER_PASSWORD
    except OSError:
        pass

    # 3. Generate a new password and persist it (best-effort)
    new_password = secrets.token_urlsafe(64)
    try:
        password_file.parent.mkdir(parents=True, exist_ok=True)
        password_file.write_text(new_password)
        password_file.chmod(0o600)
        logger.info(
            "Generated new credential-store master password at %s", password_file
        )
    except OSError as exc:
        logger.warning(
            "Could not persist MASTER_PASSWORD to %s: %s — using ephemeral value "
            "(credentials saved this session will not be decryptable after restart)",
            password_file,
            exc,
        )

    _MASTER_PASSWORD = new_password
    return _MASTER_PASSWORD


# ---------------------------------------------------------------------------
# workspace.json reader — OpenAlgo overrides from user config
# ---------------------------------------------------------------------------


def _read_openalgo_from_workspace() -> dict[str, Any]:
    """Read OpenAlgo overrides from ``~/.flinttrade/workspace.json``.

    Returns a dict with any of ``api_key``, ``host``, ``ws_port`` keys that
    are present and non-empty.  Returns an empty dict if the file is
    missing, unreadable, or doesn't contain an ``openalgo`` section.

    workspace.json wins over .env because it's user-edited through the UI
    (Setup wizard, Settings page) while .env is the dev-machine fallback.
    """
    import json  # noqa: PLC0415

    try:
        from .workspace import Workspace  # noqa: PLC0415
        ws = Workspace()
        path = ws.config_path
    except Exception:
        # Fallback: direct workspace.json path (respects FLINTTRADE_WORKSPACE_DIR)
        path = _workspace_dir() / "workspace.json"

    if not path.exists():
        return {}

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not read workspace.json at %s: %s", path, exc)
        return {}

    openalgo = data.get("openalgo") or {}
    if not isinstance(openalgo, dict):
        return {}

    result: dict[str, Any] = {}
    for key in ("api_key", "host", "ws_port"):
        val = openalgo.get(key)
        if val:
            result[key] = val
    return result


def _apply_workspace_openalgo_overrides() -> None:
    """Apply workspace.json OpenAlgo overrides to process environment.

    Called once during ``create_flask_app()`` — writes values into
    ``os.environ`` so that subsequent ``Settings.from_env()`` calls pick
    them up.  workspace.json takes precedence over .env.
    """
    overrides = _read_openalgo_from_workspace()
    if not overrides:
        return

    if "api_key" in overrides:
        os.environ["OPENALGO_API_KEY"] = str(overrides["api_key"])
    if "host" in overrides:
        os.environ["OPENALGO_HOST"] = str(overrides["host"])
    if "ws_port" in overrides:
        os.environ["OPENALGO_WS_PORT"] = str(overrides["ws_port"])

    logger.info(
        "Applied OpenAlgo overrides from workspace.json (%s)",
        ", ".join(sorted(overrides.keys())),
    )


# ---------------------------------------------------------------------------
# DuckDB stale .wal cleanup — remove orphan write-ahead-log files on boot
# ---------------------------------------------------------------------------


def _cleanup_stale_duckdb_wals() -> None:
    """Remove ``*.wal`` lock files whose ``.db`` is not actively locked.

    When the backend crashes ungracefully DuckDB's write-ahead-log files
    can linger and block the next startup with ``IOException: The process
    cannot access the file because it is being used by another process``.

    For every ``*.wal`` in ``~/.flinttrade/`` we probe the sibling ``.db``
    by opening it read-only.  If that succeeds the lock is stale and we
    delete the ``.wal``; if it fails another process holds the lock and
    we leave it alone.
    """
    flinttrade_dir = _workspace_dir()
    if not flinttrade_dir.exists():
        return

    try:
        wal_files = list(flinttrade_dir.glob("*.wal"))
    except OSError:
        return

    if not wal_files:
        return

    try:
        import duckdb  # noqa: PLC0415
    except ImportError:
        # DuckDB not installed — nothing to validate against
        return

    cleaned = 0
    for wal in wal_files:
        db_file = wal.with_suffix("")  # strip .wal → leaves .db / .duckdb etc.
        # If the .wal pairs with a file that doesn't exist, just clear it.
        if not db_file.exists():
            try:
                wal.unlink()
                cleaned += 1
            except OSError:
                pass
            continue

        # Probe: can we open the DB read-only?  If yes → no live process
        # holds the write lock → the .wal is stale.
        try:
            conn = duckdb.connect(str(db_file), read_only=True)
            conn.close()
        except Exception as exc:
            # Another process holds the lock, or the DB is corrupt — skip.
            logger.warning(
                "Skipping stale-WAL cleanup for %s (DB appears locked or broken): %s",
                db_file.name,
                exc,
            )
            continue

        try:
            wal.unlink()
            cleaned += 1
        except OSError as exc:
            logger.warning("Could not delete stale WAL %s: %s", wal, exc)

    if cleaned:
        logger.info("Cleaned %d stale DuckDB write-ahead-log file(s)", cleaned)


# ---------------------------------------------------------------------------
# Flask API server — FlintTrade-specific endpoints (port 5100)
# ---------------------------------------------------------------------------


def create_flask_app(
    safety: Any | None = None,
    scheduler: Any | None = None,
    cron: Any | None = None,
    audit: AuditLogger | None = None,
    client: OpenAlgoClient | None = None,
    registry: BrokerRegistry | None = None,
    credential_store: CredentialStore | None = None,
    contract_manager: ContractManager | None = None,
    rag: Any | None = None,
) -> Flask:
    """Create the Flask app with FlintTrade API routes.

    Args:
        safety: SafetySystem instance to expose via safety endpoints.
        scheduler: StrategyScheduler instance for strategy lifecycle endpoints.
        cron: CronManager instance for cron job management endpoints.
        audit: AuditLogger instance for audit log endpoints.
        client: OpenAlgoClient instance for MCP bridge and backtest data.
        registry: BrokerRegistry for multi-broker account management.
        credential_store: CredentialStore for encrypted credential persistence.
        contract_manager: ContractManager for broker symbol contract data.
        rag: RAGEngine instance for knowledge base queries.

    Returns:
        Flask application with all FlintTrade API endpoints registered.
    """
    # ------------------------------------------------------------------
    # Pre-init hygiene:
    #   * Clear stale DuckDB .wal files from a previous crashed process.
    #   * Apply workspace.json overrides for OpenAlgo (host/api_key/ws_port)
    #     so Settings.from_env() reads the fresh UI-written values.
    # Both are best-effort — failures here must never prevent startup.
    # ------------------------------------------------------------------
    try:
        _cleanup_stale_duckdb_wals()
    except Exception as exc:
        logger.warning("DuckDB WAL cleanup failed: %s", exc)

    try:
        _apply_workspace_openalgo_overrides()
    except Exception as exc:
        logger.warning("workspace.json override failed: %s", exc)

    # ------------------------------------------------------------------
    # Static frontend — serve the built React bundle from
    # packages/terminal/dist/ with SPA fallback for client-side routes.
    # If the build output is missing we fall back to API-only mode and
    # log a clear warning.
    # ------------------------------------------------------------------
    _dist_path = Path(_REPO_ROOT) / "packages" / "terminal" / "dist"
    _dist_index = _dist_path / "index.html"
    _frontend_available = _dist_index.exists()

    if _frontend_available:
        # Point Flask's built-in static_folder at the React build.  We use
        # a dedicated static_url_path (``/_static_flask``) so Flask's
        # default catch-all route does not pre-empt the SPA fallback
        # registered later — we serve all of the root-level dist files
        # (assets/, favicon.svg, index.html) through our fallback so
        # the NotFound → index.html redirect can work cleanly.
        app = Flask(
            __name__,
            static_folder=str(_dist_path),
            static_url_path="/_static_flask",
        )
    else:
        app = Flask(__name__)
        logger.warning(
            "Frontend not built — run `npm run build` in packages/terminal. "
            "Backend will serve API only."
        )
    app.config["_FRONTEND_AVAILABLE"] = _frontend_available
    app.config["_DIST_PATH"] = _dist_path

    # ------------------------------------------------------------------
    # Structured logging — ONE pipeline for both structlog calls and
    # stdlib logging calls.  Dual-emit bug (same event logged twice,
    # once pretty + once JSON) was caused by PrintLoggerFactory writing
    # to stdout *and* a bridge handler on root *also* writing to stdout.
    # Fix: route structlog through stdlib (LoggerFactory), then format
    # at the stdlib handler using ProcessorFormatter.  One event → one
    # line.
    #
    # Also disable click's ANSI colouring so Werkzeug's request log
    # doesn't embed escape codes in the log file.  Must be set BEFORE
    # werkzeug's first import triggers click initialisation.
    # ------------------------------------------------------------------
    os.environ.setdefault("ANSI_COLORS_DISABLED", "1")
    os.environ.setdefault("NO_COLOR", "1")

    _render_processor = (
        structlog.dev.ConsoleRenderer(colors=False)
        if app.debug
        else structlog.processors.JSONRenderer()
    )

    # Shared pre-chain applied to every event from either source.
    _shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
    ]

    structlog.configure(
        processors=[
            *_shared_processors,
            # Hand off to stdlib's ProcessorFormatter for the final render.
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    _sentinel_attr = "_flinttrade_structlog_bridge"
    _root_logger = logging.getLogger()
    # Kill any pre-existing handler (e.g. from an earlier basicConfig call
    # or a previous create_flask_app() invocation) so we can't double-emit.
    for _h in list(_root_logger.handlers):
        _root_logger.removeHandler(_h)

    _formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            # Drop the raw LogRecord and _from_structlog meta keys before
            # rendering, otherwise JSON output leaks the absolute install
            # path (C:\Users\...\app.py, line numbers) into every event.
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            _render_processor,
        ],
        foreign_pre_chain=_shared_processors,
    )
    _handler = logging.StreamHandler()
    _handler.setFormatter(_formatter)
    setattr(_handler, _sentinel_attr, True)
    _root_logger.addHandler(_handler)
    _root_logger.setLevel(logging.INFO)

    # ------------------------------------------------------------------
    # Production-mode path rewrite (WSGI-level, runs before URL dispatch).
    # In dev, Vite strips the `/ft-api` prefix before requests reach us
    # (see packages/terminal/vite.config.ts server.proxy). When the
    # backend serves the built frontend directly, no such proxy exists,
    # so the backend receives the full `/ft-api/v1/...` path while all
    # blueprints are registered under `/v1/...` or `/api/v1/...`.
    # A before_request handler runs AFTER Flask's URL match, so we wrap
    # wsgi_app instead to mutate the environ before routing.
    # ------------------------------------------------------------------
    _inner_wsgi = app.wsgi_app

    def _ft_api_prefix_stripper(environ: dict, start_response: Any) -> Any:
        raw_path = environ.get("PATH_INFO", "") or ""
        if raw_path.startswith("/ft-api/"):
            environ["PATH_INFO"] = raw_path[len("/ft-api"):]
        elif raw_path == "/ft-api":
            environ["PATH_INFO"] = "/"
        return _inner_wsgi(environ, start_response)

    app.wsgi_app = _ft_api_prefix_stripper  # type: ignore[assignment]

    # ------------------------------------------------------------------
    # CORS — allow requests from the Vite dev server and any origins
    # configured via the CORS_ORIGINS environment variable.
    # ------------------------------------------------------------------
    CORS(
        app,
        origins=os.environ.get(
            "CORS_ORIGINS", "http://127.0.0.1:5173"
        ).split(","),
        methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=[
            "Content-Type",
            "X-API-Key",
            "X-FlintTrade-Mode",
            "Authorization",
        ],
    )

    # ------------------------------------------------------------------
    # Rate limiting — 50 req/s default; tighter limits applied per-route
    # via @limiter.limit() on individual blueprints/views.
    # ------------------------------------------------------------------
    limiter = Limiter(
        get_remote_address,
        app=app,
        default_limits=["50 per second"],
        storage_uri="memory://",
    )
    app.config["LIMITER"] = limiter

    # Custom token-bucket rate limiter — finer-grained per-(user, endpoint)
    # control. Consumed via the ``@rate_limit("endpoint", user_rate, global_rate)``
    # decorator from ``packages.core.src.rate_limiter``. Applied to order,
    # bracket, strategy-start, and webhook routes to enforce the documented
    # caps: orders 10/s per user (100/s global), smart orders 2/s (20/s),
    # webhooks 5/s (50/s).
    from .rate_limiter import RateLimiter as _RateLimiter  # noqa: PLC0415
    _rate_limiter = _RateLimiter(global_rate=100, per_user_rate=10)
    _rate_limiter.set_limit("orders", user_rate=10, global_rate=100)
    _rate_limiter.set_limit("smart_orders", user_rate=2, global_rate=20)
    _rate_limiter.set_limit("webhook", user_rate=5, global_rate=50)
    app.config["RATE_LIMITER"] = _rate_limiter

    # ------------------------------------------------------------------
    # Error tracking — Sentry SDK pointing at a Glitchtip instance (MIT).
    # Only initialised when GLITCHTIP_DSN is set in the environment; safe
    # to leave unset in development.
    # ------------------------------------------------------------------
    _glitchtip_dsn = os.environ.get("GLITCHTIP_DSN", "")
    if _glitchtip_dsn:
        sentry_sdk.init(
            dsn=_glitchtip_dsn,
            integrations=[FlaskIntegration()],
            traces_sample_rate=0.1,
            environment="production" if not app.debug else "development",
        )
        logger.info("Glitchtip error tracking initialised")

    # Store injected instances on app.config so endpoint closures can access them
    app.config["SAFETY"] = safety
    app.config["SCHEDULER"] = scheduler
    app.config["CRON"] = cron
    app.config["AUDIT"] = audit
    app.config["CLIENT"] = client

    # --- Gateway initialization ---
    if registry is None:
        registry = BrokerRegistry()

    if credential_store is None:
        flinttrade_dir = _workspace_dir()
        master_password = _get_master_password()
        credential_store = CredentialStore(flinttrade_dir / "credentials.db", master_password)

    if contract_manager is None:
        flinttrade_dir = _workspace_dir()
        contracts_dir = flinttrade_dir / "contracts"
        contracts_dir.mkdir(exist_ok=True)
        contract_manager = ContractManager(contracts_dir)

    app.config["REGISTRY"] = registry
    app.config["CREDENTIAL_STORE"] = credential_store
    app.config["CONTRACT_MANAGER"] = contract_manager
    app.config["OAUTH_STATES"] = {}

    # Store RAG instance
    app.config["RAG"] = rag

    # Register gateway blueprint (mounts at /v1/)
    app.register_blueprint(gateway_bp)

    # Register analysis blueprint (/api/v1/gex, /api/v1/volsurface, etc.)
    from packages.screener.src.analysis_routes import analysis_bp  # noqa: PLC0415
    app.register_blueprint(analysis_bp)

    # Register stock screener blueprint (/v1/stocks/*)
    from packages.screener.src.stock_routes import stock_bp  # noqa: PLC0415
    app.register_blueprint(stock_bp)

    # Register market scanner blueprint (/v1/scanner/* — external: /ft-api/v1/scanner/*)
    from packages.screener.src.scanner_routes import scanner_bp  # noqa: PLC0415
    app.register_blueprint(scanner_bp)

    # Register OI analytics blueprint (/v1/oi/* — external: /ft-api/v1/oi/*)
    from packages.screener.src.oi_analytics_routes import oi_analytics_bp  # noqa: PLC0415
    app.register_blueprint(oi_analytics_bp)

    # Register Mutual Fund NAV blueprint (/api/v1/mf/search, /mf/nav, /mf/categories)
    from packages.screener.src.mf_routes import mf_bp  # noqa: PLC0415
    app.register_blueprint(mf_bp)

    # Register breadth + volatility cone blueprints (/v1/breadth/*, /v1/analytics/volcone — external: /ft-api/v1/*)
    from packages.screener.src.breadth_routes import breadth_bp  # noqa: PLC0415
    app.register_blueprint(breadth_bp)

    # Register Action Center blueprint (/api/v1/action-center/*)
    from packages.engine.src.action_center import ActionCenter  # noqa: PLC0415
    from packages.engine.src.action_center_routes import action_center_bp  # noqa: PLC0415
    action_center = ActionCenter()
    app.config["ACTION_CENTER"] = action_center
    app.register_blueprint(action_center_bp)

    # Register Security blueprint and middleware (/api/v1/security/*)
    from .security import SecurityMonitor  # noqa: PLC0415
    from .security_routes import register_security_middleware, security_bp  # noqa: PLC0415
    security_monitor = SecurityMonitor()
    app.config["SECURITY_MONITOR"] = security_monitor
    app.register_blueprint(security_bp)
    register_security_middleware(app, security_monitor)

    # Register persistent SecurityTracker (DuckDB-backed 404/IP-ban log)
    from packages.data.src.security_tracker import SecurityTracker as _SecurityTracker  # noqa: PLC0415
    _security_db = _workspace_dir() / "security.db"
    app.config["SECURITY_TRACKER"] = _SecurityTracker(str(_security_db))

    # Register LoginActivity + SessionTracker (DuckDB-backed)
    from packages.data.src.activity_log import LoginActivity as _LoginActivity  # noqa: PLC0415
    from packages.data.src.activity_log import SessionTracker as _SessionTracker  # noqa: PLC0415
    _login_db = _workspace_dir() / "activity.db"
    app.config["LOGIN_ACTIVITY"] = _LoginActivity(str(_login_db))
    app.config["SESSION_TRACKER"] = _SessionTracker(str(_login_db))

    # Register P&L tracker blueprint (/api/v1/pnl-tracker/*)
    from packages.data.src.pnl_routes import pnl_bp  # noqa: PLC0415
    app.register_blueprint(pnl_bp)

    # Register Order Flow blueprint (synthetic footprint data)
    from packages.data.src.orderflow_routes import orderflow_bp  # noqa: PLC0415
    app.register_blueprint(orderflow_bp)

    # Register Tax Report blueprint (/v1/tax/*)
    from packages.data.src.tax_routes import tax_bp  # noqa: PLC0415
    app.register_blueprint(tax_bp)

    # Register Historify watchlist blueprint
    from packages.historical.src.watchlist_routes import historify_bp  # noqa: PLC0415
    app.register_blueprint(historify_bp)

    # Register TradingView signals blueprint (/v1/tv/*)
    from packages.screener.src.tv_routes import tv_bp  # noqa: PLC0415
    app.register_blueprint(tv_bp)

    # Register monitoring blueprint (/api/v1/health, /api/v1/traffic/*, /api/v1/latency/*)
    from .monitoring_routes import monitoring_bp  # noqa: PLC0415
    app.register_blueprint(monitoring_bp)

    # Register frontend error ingestion + changelog reader (/v1/errors, /v1/changelog
    # — external URLs: /ft-api/v1/errors, /ft-api/v1/changelog). Previously referenced
    # by the terminal but not wired, causing 404s on fire-and-forget error reports.
    from .error_log import ErrorLog as _ErrorLog  # noqa: PLC0415
    from .frontend_error_routes import frontend_errors_bp  # noqa: PLC0415
    _error_db = _workspace_dir() / "error_log.duckdb"
    try:
        app.config["ERROR_LOG"] = _ErrorLog(db_path=str(_error_db))
    except Exception as exc:
        logger.warning("ErrorLog initialisation failed (%s); /v1/errors will log warnings only", exc)
        app.config["ERROR_LOG"] = None
    app.register_blueprint(frontend_errors_bp)

    # Register Strategy Runner blueprint (/api/v1/strategies/*)
    from packages.engine.src.strategy_routes import strategy_bp  # noqa: PLC0415
    app.register_blueprint(strategy_bp)

    # Register Engine Sandbox blueprint (/v1/sandbox-config/*) — config/leverage/squareoff.
    # Uses the /v1/sandbox-config prefix to avoid collision with the data sandbox
    # blueprint below, which owns /v1/sandbox.
    from packages.engine.src.sandbox_routes import sandbox_bp  # noqa: PLC0415
    from packages.engine.src.sandbox import SandboxEngine as _EngineSandboxEngine  # noqa: PLC0415
    app.config["SANDBOX_ENGINE"] = _EngineSandboxEngine(account_id="default")
    app.register_blueprint(sandbox_bp)

    # Register Data Sandbox blueprint (/v1/sandbox/*) — paper trading engine
    # (capital, orders, positions, P&L, reset, export/import)
    from packages.data.src.sandbox_routes import data_sandbox_bp  # noqa: PLC0415
    from packages.data.src.sandbox_engine import SandboxEngine as _DataSandboxEngine  # noqa: PLC0415
    app.config["DATA_SANDBOX_ENGINE"] = _DataSandboxEngine()
    app.register_blueprint(data_sandbox_bp)

    # Initialise persistent error log (always active — not gated by dev mode).
    # Stored on app.config so admin_routes and the error handler can access it.
    from .error_log import ErrorLog  # noqa: PLC0415

    _error_log_path = _workspace_dir() / "error_log.duckdb"
    _error_log = ErrorLog(_error_log_path)
    app.config["ERROR_LOG"] = _error_log

    # ------------------------------------------------------------------
    # Global unhandled-exception handler — persists errors to DuckDB
    # before re-raising so Flask's default 500 handler takes over.
    # ------------------------------------------------------------------
    @app.errorhandler(Exception)
    def _log_unhandled_exception(exc: Exception) -> Any:
        """Persist every unhandled exception to the structured error log.

        Werkzeug ``HTTPException`` instances (404, 405, 415, …) are not
        real errors — they represent deliberately returned HTTP status
        codes and must be passed straight through with their own payload,
        otherwise a simple 404 bubbles up as a misleading 500.  Real
        exceptions are logged and converted to a plain HTTP 500 JSON
        response so we never leak internal tracebacks to clients.
        """
        from werkzeug.exceptions import HTTPException  # noqa: PLC0415

        if isinstance(exc, HTTPException):
            return exc  # Flask will render the HTTPException normally.

        try:
            _error_log.log(
                route=request.path,
                method=request.method,
                status_code=500,
                request_body=request.get_json(silent=True, force=True),
                error=exc,
                user_id=None,  # user context not available at this layer
            )
        except Exception:
            # Never let the error logger itself crash the request.
            pass
        return jsonify({"status": "error", "message": "Internal server error"}), 500

    # Initialise TrafficLogger (DuckDB-backed, always active).
    # @before_request / @after_request hooks record every HTTP request.
    from .traffic_logger import TrafficLogger as _TrafficLogger, should_skip_path as _skip_path  # noqa: PLC0415

    _traffic_log_path = _workspace_dir() / "traffic_log.duckdb"
    _traffic_logger = _TrafficLogger(_traffic_log_path)
    app.config["TRAFFIC_LOGGER"] = _traffic_logger

    @app.before_request
    def _traffic_start() -> None:
        """Record the request start time for traffic duration measurement."""
        import time as _time  # noqa: PLC0415
        _flask_g._traffic_start = _time.monotonic()

    @app.after_request
    def _traffic_log(response: Any) -> Any:
        """Persist request details to TrafficLogger after each response."""
        try:
            if not _skip_path(request.path):
                import time as _time  # noqa: PLC0415
                start = getattr(_flask_g, "_traffic_start", None)
                duration_ms = (_time.monotonic() - start) * 1000 if start is not None else 0.0
                _traffic_logger.log(
                    ip=request.remote_addr or "unknown",
                    method=request.method,
                    path=request.path,
                    status_code=response.status_code,
                    duration_ms=duration_ms,
                    user_agent=request.headers.get("User-Agent"),
                    request_size=request.content_length,
                    response_size=response.content_length,
                )
        except Exception as _exc:
            logger.debug("suppressed: %s", _exc)  # Never let traffic logging break the response
        return response

    # Initialise LatencyMonitor (DuckDB-backed, always active).
    # The order router wraps this via monitoring_routes.get_latency_tracker()
    # for in-memory stats; this provides persistent DuckDB-backed storage.
    from packages.engine.src.latency_monitor import LatencyMonitor as _LatencyMonitor  # noqa: PLC0415

    _latency_log_path = _workspace_dir() / "latency_log.duckdb"
    _latency_monitor = _LatencyMonitor(_latency_log_path)
    app.config["LATENCY_MONITOR"] = _latency_monitor

    # Initialise APIAnalyzer (DuckDB-backed, opt-in via ENABLE_ANALYZER=true).
    _analyzer_enabled = os.environ.get("ENABLE_ANALYZER", "").lower() in ("1", "true", "yes")
    if _analyzer_enabled:
        from .api_analyzer import APIAnalyzer as _APIAnalyzer  # noqa: PLC0415

        _analyzer_path = _workspace_dir() / "api_analyzer.duckdb"
        _api_analyzer = _APIAnalyzer(_analyzer_path)
        app.config["API_ANALYZER"] = _api_analyzer

        @app.after_request
        def _analyzer_log(response: Any) -> Any:
            """Persist full request + response to APIAnalyzer when enabled."""
            try:
                import time as _time  # noqa: PLC0415
                start = getattr(_flask_g, "_traffic_start", None)
                duration_ms = (_time.monotonic() - start) * 1000 if start is not None else 0.0
                _api_analyzer.log_call(
                    route=request.path,
                    method=request.method,
                    request_body=request.get_json(silent=True, force=True),
                    response_status=response.status_code,
                    response_body=None,  # Not parsing response body to avoid re-reading stream
                    duration_ms=duration_ms,
                )
            except Exception as _exc:
                logger.debug("suppressed: %s", _exc)
            return response

        logger.info("API Analyser enabled — capturing all requests")

    # Initialise module-level EventBus singleton.
    from .event_bus import bus as _event_bus  # noqa: PLC0415
    app.config["EVENT_BUS"] = _event_bus
    logger.info("EventBus initialised")

    # Register admin blueprint (dev/debug only)
    if app.debug or os.environ.get("FLINTTRADE_DEV"):
        from .admin_routes import admin_bp  # noqa: PLC0415
        app.register_blueprint(admin_bp)
        # Register infrastructure admin routes (traffic/latency/analyzer)
        from .infra_routes import infra_bp  # noqa: PLC0415
        app.register_blueprint(infra_bp)
        logger.info("Admin endpoints registered (dev mode)")

    # Register Activity Log blueprint (/api/v1/admin/activity)
    # Always registered — SEBI audit access is not restricted to dev mode.
    from packages.data.src.activity_routes import activity_bp  # noqa: PLC0415
    _activity_db = _workspace_dir() / "activity.db"
    from packages.data.src.activity_log import ActivityLog as _ActivityLog  # noqa: PLC0415
    app.config["ACTIVITY_LOG"] = _ActivityLog(str(_activity_db))
    app.register_blueprint(activity_bp)
    logger.info("Activity log endpoint registered at /api/v1/admin/activity")

    # Register extracted inline-route blueprints
    from .indicators_routes import indicators_bp  # noqa: PLC0415
    app.register_blueprint(indicators_bp)

    from packages.ai.src.advisor_routes import advisor_bp  # noqa: PLC0415
    app.register_blueprint(advisor_bp)

    from packages.ai.src.ai_routes import ai_bp  # noqa: PLC0415
    app.register_blueprint(ai_bp)

    from packages.ai.src.signal_routes import signal_bp  # noqa: PLC0415
    app.register_blueprint(signal_bp)

    from .backtest_routes import backtest_bp  # noqa: PLC0415
    app.register_blueprint(backtest_bp)

    from .operations_routes import operations_bp  # noqa: PLC0415
    app.register_blueprint(operations_bp)

    # Register Order proxy blueprint (/v1/orders/*) — CRITICAL SAFETY LAYER.
    # All order requests from the frontend must pass through here so that
    # mode enforcement (explore/practice/live) is applied before any
    # real-money order reaches OpenAlgo.
    from .order_routes import orders_bp  # noqa: PLC0415
    app.register_blueprint(orders_bp)

    # Register AI Team blueprint (/api/v1/ai/team/*)
    from packages.ai.src.team_routes import team_bp  # noqa: PLC0415
    app.register_blueprint(team_bp)

    # Register Fundamental Screener blueprint (/api/v1/fundamentals/*)
    from packages.screener.src.fundamental_routes import fundamental_bp  # noqa: PLC0415
    app.register_blueprint(fundamental_bp)

    # Register IPO Tracker blueprint (/api/v1/ipo/*)
    from packages.screener.src.ipo_routes import ipo_bp  # noqa: PLC0415
    app.register_blueprint(ipo_bp)

    # Register Earnings Calendar blueprint (/v1/earnings/* — external: /ft-api/v1/earnings/*)
    from packages.screener.src.earnings_routes import earnings_bp  # noqa: PLC0415
    app.register_blueprint(earnings_bp)

    # Register Pivot Calculator blueprint (/v1/pivots/* — external: /ft-api/v1/pivots/*)
    from packages.screener.src.pivot_routes import pivot_bp  # noqa: PLC0415
    app.register_blueprint(pivot_bp)

    # Register Economic Calendar blueprint (/v1/economic/* — external: /ft-api/v1/economic/*)
    from packages.screener.src.economic_routes import economic_bp  # noqa: PLC0415
    app.register_blueprint(economic_bp)

    # Register Audit Trail blueprint (/v1/audit/* — external: /ft-api/v1/audit/*)
    from packages.data.src.audit_routes import audit_bp  # noqa: PLC0415
    app.register_blueprint(audit_bp)

    # Register Analytics extensions blueprint (/v1/indicators/vwap, /v1/analytics/pairs,
    # /v1/analytics/mtf — external: /ft-api/v1/indicators/*, /ft-api/v1/analytics/*)
    from packages.screener.src.analytics_routes import analytics_bp  # noqa: PLC0415
    app.register_blueprint(analytics_bp)

    # Register WhatsApp Alerts blueprint (/api/v1/alerts/whatsapp/*)
    from packages.automation.src.whatsapp_routes import whatsapp_bp  # noqa: PLC0415
    app.register_blueprint(whatsapp_bp)

    # Register Historical Expiry Tracker blueprint (/api/v1/historical/*)
    from packages.historical.src.expiry_tracker_routes import expiry_tracker_bp  # noqa: PLC0415
    app.register_blueprint(expiry_tracker_bp)

    # Register Holidays + Market Timings blueprint (/api/v1/holidays, /api/v1/market/timings)
    from packages.historical.src.holidays_routes import holidays_bp  # noqa: PLC0415
    app.register_blueprint(holidays_bp)

    # Register Intervals blueprint (/api/v1/intervals)
    from packages.historical.src.intervals_routes import intervals_bp  # noqa: PLC0415
    app.register_blueprint(intervals_bp)

    # Register Instruments blueprint (/api/v1/instruments)
    from packages.historical.src.instruments_routes import instruments_bp  # noqa: PLC0415
    app.register_blueprint(instruments_bp)

    # Register Symbol Search blueprint (/api/v1/search)
    from packages.historical.src.search_routes import search_bp  # noqa: PLC0415
    app.register_blueprint(search_bp)

    # Register Broker Capabilities blueprint (/api/v1/broker/capabilities)
    from packages.gateway.src.capabilities_routes import capabilities_bp  # noqa: PLC0415
    app.register_blueprint(capabilities_bp)

    # Register Leverage / Margin blueprint (/api/v1/leverage/margin/current)
    from packages.engine.src.leverage_routes import leverage_bp  # noqa: PLC0415
    app.register_blueprint(leverage_bp)

    # Register PNL by Symbols blueprint (/api/v1/pnl/symbols)
    from packages.data.src.pnl_symbols_routes import pnl_symbols_bp  # noqa: PLC0415
    app.register_blueprint(pnl_symbols_bp)

    # Register Bracket Order blueprint (/api/v1/orders/bracket*)
    from packages.engine.src.bracket_routes import bracket_bp  # noqa: PLC0415
    app.register_blueprint(bracket_bp)

    # Register Position Sizer blueprint (/api/v1/position/*)
    from packages.engine.src.position_sizer_routes import position_bp  # noqa: PLC0415
    app.register_blueprint(position_bp)

    # Register Voice Orders blueprint (/api/v1/voice/*)
    from packages.integration.src.voice_orders import voice_bp  # noqa: PLC0415
    app.register_blueprint(voice_bp)

    # Register n8n bridge blueprint (/api/v1/automation/n8n/*)
    from packages.automation.src.n8n_routes import n8n_bp  # noqa: PLC0415
    app.register_blueprint(n8n_bp)

    # Register QuestDB bridge blueprint (/api/v1/data/questdb/*)
    from packages.data.src.questdb_routes import questdb_bp  # noqa: PLC0415
    app.register_blueprint(questdb_bp)

    # Register Excel bridge blueprint (/api/v1/integration/excel/*)
    from packages.integration.src.excel_routes import excel_bp  # noqa: PLC0415
    app.register_blueprint(excel_bp)

    # ------------------------------------------------------------------
    # Blueprints discovered as defined-but-not-registered during the
    # 2026-05-19 multi-agent audit (Python audit, API contract audit).
    # Registering them activates their routes:
    #
    #   webhook_bp                — /v1/webhook/<source>, /v1/webhook/log
    #                               (TradingView + ChartInk webhook receivers)
    #   payoff_bp                 — /v1/payoff/{analyse,curve}, /v1/regime/current,
    #                               /v1/analytics/correlation
    #   health_bp                 — /health, /health/detail, /healthz, /readyz,
    #                               /api/v1/ping (K8s + LB probes; /api/v1/ping
    #                               is already in `_PUBLIC_V1_PREFIXES`)
    #   optimiser_bp              — /v1/portfolio/{optimise,frontier}
    #   permutation_bp            — /v1/backtest/{permutation,walkforward}
    #   admin_action_center_bp    — /admin/action-center/{pending,approve,reject,history}
    #                               (separate from `action_center_bp` which lives
    #                               under /api/v1/action-center for normal users)
    #   engine order_bp           — /api/v1/orders/{basket,split,options-strategy}
    #                               (advanced orders; distinct from core's safety
    #                               proxy `orders_bp` which currently lives at
    #                               /v1/orders/* — frontend uses the /api/v1/
    #                               form, so these route additions reduce the
    #                               apparent 404 surface today.)
    # ------------------------------------------------------------------
    from packages.integration.src.webhook_routes import webhook_bp  # noqa: PLC0415
    app.register_blueprint(webhook_bp)

    from packages.screener.src.payoff_routes import payoff_bp  # noqa: PLC0415
    app.register_blueprint(payoff_bp)

    from .health_routes import health_bp  # noqa: PLC0415
    app.register_blueprint(health_bp)

    # backtest-engine has a hyphen in its directory name which prevents standard
    # `from packages.backtest_engine.src.X` imports — inject src/ onto sys.path
    # the same way backtest_routes.py:_load_backtest_engine does, then import
    # the route modules by bare name.
    import importlib  # noqa: PLC0415
    from pathlib import Path as _Path  # noqa: PLC0415
    _be_src = str(_Path(__file__).resolve().parents[3] / "packages" / "backtest-engine" / "src")
    _be_src_added = _be_src not in sys.path
    if _be_src_added:
        sys.path.insert(0, _be_src)
    try:
        _opt_mod = importlib.import_module("optimiser_routes")
        app.register_blueprint(_opt_mod.optimiser_bp)
        _perm_mod = importlib.import_module("permutation_routes")
        app.register_blueprint(_perm_mod.permutation_bp)
    finally:
        if _be_src_added and _be_src in sys.path:
            sys.path.remove(_be_src)

    from packages.engine.src.action_center_routes import admin_action_center_bp  # noqa: PLC0415
    app.register_blueprint(admin_action_center_bp)

    from packages.engine.src.order_routes import order_bp as engine_order_bp  # noqa: PLC0415
    app.register_blueprint(engine_order_bp)

    # Register Workspace Preset blueprint (/v1/presets/* — external: /ft-api/v1/presets/*)
    from .preset_routes import preset_bp  # noqa: PLC0415
    app.register_blueprint(preset_bp)

    # Register Log Stream blueprint (/v1/logs/*) — SSE + REST log streaming
    from .log_stream import log_stream_bp  # noqa: PLC0415
    app.register_blueprint(log_stream_bp)

    # Register Keyboard Shortcuts blueprint (/v1/shortcuts/*) — per-user DuckDB persistence
    from .shortcuts_routes import shortcuts_bp  # noqa: PLC0415
    app.register_blueprint(shortcuts_bp)

    # Register Docs Search blueprint (/v1/docs/*) — full-text search + changelog
    from .docs_search_routes import docs_search_bp  # noqa: PLC0415
    app.register_blueprint(docs_search_bp)

    # Register Auth blueprint (/v1/auth/*) — public endpoints, no API key required
    from .auth_service import AuthService as _AuthService  # noqa: PLC0415
    from .auth_routes import auth_bp  # noqa: PLC0415
    _auth_db = _workspace_dir() / "auth.db"
    app.config["AUTH_SERVICE"] = _AuthService(db_path=_auth_db)
    app.register_blueprint(auth_bp)

    # Register Multi-user blueprint (/v1/users/*) — opt-in via FLINTTRADE_MULTI_USER=1
    if os.environ.get("FLINTTRADE_MULTI_USER", "").strip() in ("1", "true", "yes"):
        from .user_manager import UserManager as _UserManager  # noqa: PLC0415
        from .user_routes import users_bp  # noqa: PLC0415
        app.config["USER_MANAGER"] = _UserManager(db_path=_auth_db)
        app.register_blueprint(users_bp)
        logger.info("Multi-user mode enabled — /v1/users/* endpoints registered")

    # Reconnect saved accounts (best-effort, don't block startup)
    try:
        _reconnect_saved_accounts(registry, credential_store, logger)
    except Exception as exc:
        logger.error("Account reconnection failed: %s", exc)

    # Paths that are legitimately public (no API key needed):
    # - Health check endpoint (also exempted by endpoint name in require_auth)
    # - Admin introspect (already gated by FLINTTRADE_DEV in admin_routes)
    # - OAuth callbacks (browser redirect — no API key in URL)
    # - Frontend error reporting (/api/v1/errors — must be reachable before auth)
    _PUBLIC_V1_PREFIXES = (
        "/v1/admin/health",
        "/v1/admin/introspect",
        "/v1/auth/",          # Auth endpoints are public (login, setup, status)
        "/v1/auth/callback",
        "/v1/errors",         # Frontend error reporting — public, rate-limited.
                              # Blueprint mounted at /v1/errors (see
                              # frontend_error_routes.py:Blueprint(..., url_prefix="/v1")).
                              # Persists to ErrorLog (DuckDB) for post-mortem.
        "/api/v1/errors",     # Same purpose, different sink: this path is
                              # handled by `operations_bp.receive_frontend_error`
                              # which forwards to structlog + Sentry/Glitchtip
                              # instead of DuckDB. Kept public so the React app,
                              # the Chrome extension, and external automation
                              # can all fire-and-forget error reports without
                              # an API key — neither sink leaks sensitive data
                              # back to the caller.
        "/v1/changelog",      # Frontend changelog viewer — public, paired with /v1/errors.
        "/api/v1/ping",       # Liveness probe — no auth required
        "/v1/config/openalgo",          # Setup wizard — public, localhost-only
        "/v1/test-connection",          # Setup wizard — public, localhost-only
    )

    @app.before_request
    def _bind_request_context() -> None:
        """Bind per-request fields into the structlog context variable store.

        Attaches a unique request ID (from the X-Request-ID header, or a
        freshly generated hex token), the HTTP method, and the path so that
        every log line emitted during this request carries them automatically.
        """
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request.headers.get(
                "X-Request-ID", secrets.token_hex(8)
            ),
            method=request.method,
            path=request.path,
        )

    @app.after_request
    def _log_request(response: Any) -> Any:
        """Emit a structured log line for every completed HTTP response."""
        _req_log = structlog.get_logger()
        _req_log.info(
            "request",
            status=response.status_code,
            content_length=response.content_length,
        )
        return response

    @app.after_request
    def _add_security_headers(response: Any) -> Any:
        """Add security headers to every response (only when not already set).

        CSP is intentionally omitted here — Nginx handles it at the proxy
        layer so the header is applied once rather than duplicated.
        """
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("X-XSS-Protection", "1; mode=block")
        response.headers.setdefault(
            "Referrer-Policy", "strict-origin-when-cross-origin"
        )
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        return response

    @app.before_request
    def require_auth() -> Any:
        """Require API key authentication on all endpoints.

        Only specific public paths are exempted:
        - Health check and admin introspect (dev-gated)
        - OAuth callback (browser redirect, no API key in URL)
        - Static files and SPA HTML fallback (React bundle)
        All other /v1/ endpoints require the same API key auth.
        """
        # Allow health check, static files, and SPA fallback without auth
        if request.endpoint in ("monitoring.health", "static", "_spa_fallback"):
            return None
        # Allow OPTIONS for CORS preflight
        if request.method == "OPTIONS":
            return None
        # Allow specific public /v1/ paths only
        if any(request.path.startswith(prefix) for prefix in _PUBLIC_V1_PREFIXES):
            return None

        api_key = (
            request.headers.get("X-API-Key")
            or request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        )

        expected_key = os.environ.get("OPENALGO_API_KEY", "")
        if not expected_key:
            logger.warning("OPENALGO_API_KEY not set — all requests will be rejected")
            return jsonify({"status": "error", "message": "Server not configured"}), 503

        if not api_key or not hmac.compare_digest(api_key, expected_key):
            # Record auth failure for brute-force detection
            try:
                sec = app.config.get("SECURITY_MONITOR")
                if sec:
                    sec.record_auth_failure(request.remote_addr or "unknown")
            except Exception as _exc:
                logger.debug("suppressed: %s", _exc)
            return jsonify({"status": "error", "message": "Unauthorized"}), 401

        return None

    @app.before_request
    def _require_json_content_type() -> Any:
        """Reject POST/PUT/PATCH requests that don't send JSON."""
        if request.method in ("POST", "PUT", "PATCH") and request.content_length:
            content_type = request.content_type or ""
            if "json" not in content_type and "text/event-stream" not in content_type:
                return jsonify({
                    "status": "error",
                    "message": "Content-Type must be application/json",
                }), 415
        return None

    @app.before_request
    def _record_request_start() -> None:
        """Store request start time for latency calculation."""
        _flask_g._request_start = time.monotonic()

    @app.after_request
    def _record_traffic(response: Any) -> Any:
        """Record method, path, status, and duration in TrafficCounter."""
        try:
            from .monitoring_routes import get_traffic_counter  # noqa: PLC0415

            start = getattr(_flask_g, "_request_start", None)
            duration_ms = (time.monotonic() - start) * 1000 if start is not None else 0.0
            get_traffic_counter().record(
                method=request.method,
                path=request.path,
                status=response.status_code,
                duration_ms=duration_ms,
            )
        except Exception as _exc:
            logger.debug("suppressed: %s", _exc)  # Never let monitoring break the response
        return response

    @app.after_request
    def _track_404s(response: Any) -> Any:
        """Persist 404 events in SecurityTracker for flood detection.

        Runs after the response is built so we know the real status code.
        Best-effort — never disrupts the response pipeline.
        """
        if response.status_code == 404:
            try:
                skt = app.config.get("SECURITY_TRACKER")
                if skt is not None:
                    skt.track_404(request.remote_addr or "unknown", request.path)
            except Exception as _exc:
                logger.debug("suppressed: %s", _exc)
        return response

    @app.before_request
    def _session_heartbeat() -> None:
        """Update last_active for the session carried in the Authorization header.

        Only fires when a valid Bearer token is present AND a SessionTracker
        has been registered.  Best-effort — never blocks the request.
        """
        try:
            auth_header = request.headers.get("Authorization", "")
            if not auth_header.startswith("Bearer "):
                return
            token = auth_header.removeprefix("Bearer ").strip()
            if not token:
                return
            st = app.config.get("SESSION_TRACKER")
            if st is not None:
                st.heartbeat(token)
        except Exception as _exc:
            logger.debug("suppressed: %s", _exc)

    # --- inline route handlers extracted to blueprints ---
    # indicators_bp  → packages/core/src/indicators_routes.py
    # advisor_bp     → packages/ai/src/advisor_routes.py
    # ai_bp          → packages/ai/src/ai_routes.py
    # signal_bp      → packages/ai/src/signal_routes.py
    # backtest_bp    → packages/core/src/backtest_routes.py
    # operations_bp  → packages/core/src/operations_routes.py

    # ------------------------------------------------------------------
    # MCP bridge — register handlers that route through OpenAlgo
    # ------------------------------------------------------------------
    try:
        from packages.ai.src.mcp_bridge import MCPBridge  # noqa: PLC0415

        _mcp_bridge = MCPBridge()

        def _mcp_place_order(**params: Any) -> dict[str, Any]:
            """Route MCP place_order through OpenAlgo (sync wrapper)."""
            from .openalgo_client import OpenAlgoClient  # noqa: PLC0415
            client = OpenAlgoClient(Settings.from_env())
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(client.place_order(**params))
            finally:
                loop.run_until_complete(client.close())
                loop.close()

        def _mcp_get_positions(**params: Any) -> dict[str, Any]:
            """Route MCP get_positions through OpenAlgo (sync wrapper)."""
            from .openalgo_client import OpenAlgoClient  # noqa: PLC0415
            client = OpenAlgoClient(Settings.from_env())
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(client.positionbook())
            finally:
                loop.run_until_complete(client.close())
                loop.close()

        _mcp_bridge.register_handler("place_order", _mcp_place_order)
        _mcp_bridge.register_handler("get_positions", _mcp_get_positions)
        logger.info("MCP bridge initialised with place_order, get_positions handlers")
    except Exception:
        logger.debug("MCP bridge not available — skipping handler registration")

    # ------------------------------------------------------------------
    # Config persistence endpoint — /ft-api/v1/config/openalgo
    # Accepts {api_key, host, ws_port} from the Setup wizard, persists
    # them to workspace.json, and hot-reloads app.config["CLIENT"] so no
    # process restart is needed.
    # ------------------------------------------------------------------
    # Registered at /v1/... (not /ft-api/v1/...) because the WSGI prefix
    # stripper normalises /ft-api/v1/X → /v1/X before URL dispatch, and the
    # Vite dev proxy does the same rewrite. So a single /v1/... registration
    # is reachable from both environments.
    @app.route("/v1/config/openalgo", methods=["POST"])
    @limiter.limit("10 per minute")
    def _set_openalgo_config() -> Any:
        """Persist OpenAlgo connection settings from the UI.

        Security: only accept requests from loopback (127.0.0.1) since the
        payload includes the OpenAlgo API key. The default require_auth
        layer still applies unless the caller is already authenticated —
        however the Setup wizard runs *before* the user has an API key,
        so we also permit requests that originate from localhost without
        an API-key header.

        Request JSON: ``{"api_key": "...", "host": "...", "ws_port": 8765}``
        """
        remote = request.remote_addr or ""
        if remote not in ("127.0.0.1", "::1", "localhost"):
            return jsonify({
                "status": "error",
                "message": "This endpoint is only reachable from localhost",
            }), 403

        payload = request.get_json(silent=True) or {}
        api_key = str(payload.get("api_key", "")).strip()
        host = str(payload.get("host", "")).strip()
        ws_port = payload.get("ws_port")

        if not api_key and not host and ws_port is None:
            return jsonify({
                "status": "error",
                "message": "At least one of api_key, host, ws_port is required",
            }), 400

        # Persist to workspace.json
        try:
            from .workspace import Workspace  # noqa: PLC0415
            ws = Workspace()
            if not ws.config_path.exists():
                ws.initialize()
            if api_key:
                ws.set("openalgo.api_key", api_key)
            if host:
                ws.set("openalgo.host", host)
            if ws_port is not None:
                ws.set("openalgo.ws_port", int(ws_port))
        except Exception as exc:
            logger.error("Failed to persist OpenAlgo config to workspace.json: %s", exc)
            return jsonify({
                "status": "error",
                "message": f"Could not persist config: {exc}",
            }), 500

        # Re-apply overrides into process env so any code reading .env picks
        # up the new values immediately.
        try:
            _apply_workspace_openalgo_overrides()
        except Exception:
            pass

        # Hot-reload OpenAlgoClient so subsequent backend→OpenAlgo calls
        # use the fresh credentials without requiring a restart.
        try:
            new_settings = Settings.from_env()
            new_client = OpenAlgoClient(new_settings)
            old_client = app.config.get("CLIENT")
            app.config["CLIENT"] = new_client
            # Best-effort close of the previous client's HTTP pool.
            if old_client is not None:
                try:
                    loop = asyncio.new_event_loop()
                    try:
                        loop.run_until_complete(old_client.close())
                    finally:
                        loop.close()
                except Exception:
                    pass
        except Exception as exc:
            logger.warning(
                "OpenAlgo config saved but client reinitialisation failed: %s", exc
            )
            return jsonify({
                "status": "partial",
                "message": f"Config saved but client not reloaded: {exc}",
            }), 200

        return jsonify({
            "status": "ok",
            "message": "OpenAlgo config saved and client reloaded",
        }), 200

    # ------------------------------------------------------------------
    # Connection-test endpoint — /ft-api/v1/test-connection
    # Used by the Setup wizard + Settings › Connection. The browser cannot
    # call OpenAlgo's /api/v1/ping directly because OpenAlgo does not send
    # CORS headers for our origin (and we will not modify OpenAlgo). We
    # proxy the test through our backend so it runs server-to-server with
    # no CORS involvement.
    # ------------------------------------------------------------------
    @app.route("/v1/test-connection", methods=["POST"])
    @limiter.limit("10 per minute")
    def _test_openalgo_connection() -> Any:
        """Server-side OpenAlgo connectivity + auth test.

        Accepts the exact ``{host, api_key}`` the user typed in the wizard,
        pings OpenAlgo, and returns a structured result. HTTP status is
        always 200 — the real outcome lives in the JSON body so the
        frontend can distinguish reachable/unreachable/auth-failed without
        tripping on HTTP error handling.
        """
        remote = request.remote_addr or ""
        if remote not in ("127.0.0.1", "::1", "localhost"):
            return jsonify({
                "status": "error",
                "message": "This endpoint is only reachable from localhost",
            }), 403

        payload = request.get_json(silent=True) or {}
        # Strip one or more trailing slashes; setup wizard sometimes posts
        # the host with "/" or "//".
        host = str(payload.get("host", "")).strip().rstrip("/")
        api_key = str(payload.get("api_key", "")).strip()

        if not host or not api_key:
            return jsonify({
                "status": "error",
                "message": "host and api_key are required",
            }), 400

        import httpx as _httpx  # noqa: PLC0415

        try:
            resp = _httpx.post(
                f"{host}/api/v1/ping",
                json={"apikey": api_key},
                timeout=5.0,
            )
        except (_httpx.ConnectError, _httpx.ConnectTimeout) as exc:
            return jsonify({
                "status": "error",
                "reachable": False,
                "message": f"Cannot reach OpenAlgo at {host}: {exc}",
            }), 200
        except _httpx.TimeoutException:
            return jsonify({
                "status": "error",
                "reachable": False,
                "message": f"OpenAlgo at {host} did not respond within 5s",
            }), 200
        except Exception as exc:  # noqa: BLE001
            return jsonify({
                "status": "error",
                "reachable": False,
                "message": f"Connection test failed ({type(exc).__name__}): {exc}",
            }), 200

        if resp.status_code == 200:
            broker = "unknown"
            try:
                data = resp.json()
                if isinstance(data, dict):
                    broker = data.get("data", {}).get("broker") or data.get("broker") or "unknown"
            except Exception:  # noqa: BLE001
                pass
            return jsonify({
                "status": "ok",
                "reachable": True,
                "authenticated": True,
                "broker": broker,
                "message": f"Connected — broker: {broker}",
            }), 200

        if resp.status_code in (401, 403):
            msg = "Invalid API key"
            try:
                body = resp.json()
                if isinstance(body, dict):
                    msg = body.get("message", msg)
            except Exception:  # noqa: BLE001
                pass
            return jsonify({
                "status": "error",
                "reachable": True,
                "authenticated": False,
                "http_status": resp.status_code,
                "message": f"Reachable but auth failed (HTTP {resp.status_code}): {msg}",
            }), 200

        return jsonify({
            "status": "error",
            "reachable": True,
            "authenticated": False,
            "http_status": resp.status_code,
            "message": f"OpenAlgo returned unexpected HTTP {resp.status_code}",
        }), 200

    # ------------------------------------------------------------------
    # SPA fallback — registered LAST so it only matches unclaimed routes.
    # Returns 404 for API paths (so unknown /api/ or /v1/ endpoints still
    # look like 404s to clients) and serves the React bundle for every
    # other path.  Matches at most one path segment so deep React-router
    # paths like `/trade/scalper` all fall through to index.html.
    # ------------------------------------------------------------------
    if _frontend_available:
        from flask import send_from_directory  # noqa: PLC0415

        _API_PREFIXES = ("/api/", "/ft-api/", "/v1/")

        @app.route("/", defaults={"path": ""}, endpoint="_spa_fallback")
        @app.route("/<path:path>", endpoint="_spa_fallback")
        def _spa_fallback(path: str) -> Any:
            """Serve the React SPA for any non-API path."""
            # API paths must never be intercepted — let Flask 404 them.
            req_path = request.path
            if any(req_path.startswith(p) for p in _API_PREFIXES):
                return jsonify({
                    "status": "error",
                    "message": "Not found",
                }), 404

            # If the exact file exists under dist/, serve it (favicon, assets/*).
            if path:
                candidate = _dist_path / path
                try:
                    # Guard against path traversal: resolved path must be
                    # inside _dist_path.
                    resolved = candidate.resolve()
                    if (
                        resolved.is_file()
                        and _dist_path.resolve() in resolved.parents
                    ):
                        return send_from_directory(
                            str(_dist_path), path
                        )
                except Exception:
                    pass

            # Otherwise serve index.html (SPA client-side routing).
            return send_from_directory(str(_dist_path), "index.html")

    return app


def _run_flask_server(app: Flask, port: int = 5100) -> None:
    """Run the Flask API server in a daemon thread.

    Uses Waitress — a pure-Python, cross-platform production WSGI server
    (works identically on Windows, macOS, Linux).  Replaces Flask's
    built-in Werkzeug dev server, which emits a loud "this is a
    development server" warning and is not production-safe.

    Args:
        app: Flask application instance.
        port: Port to bind (default 5100).
    """
    try:
        from waitress import serve as _waitress_serve  # noqa: PLC0415
    except ImportError:
        # Graceful fallback if waitress isn't installed — still works
        # for local dev, just prints the dev-server warning.
        logger.warning(
            "Waitress not installed; falling back to Werkzeug dev server. "
            "Install with: pip install waitress"
        )

        def _run() -> None:
            app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)
    else:
        # Quiet Waitress's per-request access log — our structlog middleware
        # already logs requests via the traffic logger at a structured level.
        logging.getLogger("waitress").setLevel(logging.WARNING)

        def _run() -> None:
            # ident="FlintTrade" sets the Server: header instead of "waitress".
            # threads=8 is enough for a single-user dev/desktop setup.
            _waitress_serve(
                app,
                host="127.0.0.1",
                port=port,
                ident="FlintTrade",
                threads=8,
            )

    thread = threading.Thread(target=_run, name="flinttrade-api", daemon=True)
    thread.start()
    logger.info("FlintTrade API server started on http://127.0.0.1:%d", port)


class FlintTradeApp:
    """Main application — creates and wires all FlintTrade subsystems.

    Startup is resilient: if OpenAlgo is unreachable or optional services
    (Telegram, AI) are not configured, the app starts with warnings
    instead of crashing.

    Usage::

        app = FlintTradeApp()
        app.run()  # blocking — runs until Ctrl+C or SIGTERM
    """

    def __init__(self) -> None:
        # Load environment
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass

        self.version = _read_version()

        # Audit logger first — must be available before anything else
        self.audit = AuditLogger()
        self.audit.log_event("APP_START", version=self.version)

        # Core — settings + API client
        self.settings = Settings.from_env()
        self.client = OpenAlgoClient(self.settings)

        # Engine — safety + router + scheduler (deferred to avoid circular import
        # between core↔engine at module level).
        from packages.engine.src.router import OrderRouter  # noqa: PLC0415
        from packages.engine.src.safety import SafetyConfig, SafetySystem  # noqa: PLC0415
        from packages.engine.src.scheduler import StrategyScheduler, TimeScheduler  # noqa: PLC0415

        self.safety = SafetySystem(SafetyConfig(check_market_hours=True))
        self.router = OrderRouter(
            client=self.client,
            safety=self.safety,
            audit_logger=self.audit,
        )
        self.time_scheduler = TimeScheduler(client=self.client)
        self.scheduler = StrategyScheduler(
            client=self.client,
            time_scheduler=self.time_scheduler,
        )

        # Automation — cron manager (lazy import avoids loading APScheduler at
        # module level, which accounts for ~0.3 s of the startup penalty).
        from packages.automation.src.cron_manager import CronManager  # noqa: PLC0415

        self.cron = CronManager(
            openalgo_client=self.client,
            audit_logger=self.audit,
        )

        # Automation — Telegram bot (optional — token may not be set).
        # Lazy import avoids pulling in the python-telegram-bot dependency
        # (and its event-loop initialisation) until it is actually needed.
        from packages.automation.src.telegram_bot import TelegramBot  # noqa: PLC0415

        self.telegram = TelegramBot(
            router=self.router,
            safety_system=self.safety,
            scheduler=self.scheduler,
            audit_logger=self.audit,
        )
        # Wire Telegram into cron so jobs can send alerts
        self.cron.telegram_bot = self.telegram

        # Gateway — broker registry + credential store + contract manager
        flinttrade_dir = _workspace_dir()
        master_password = _get_master_password()
        self.credential_store = CredentialStore(
            flinttrade_dir / "credentials.db", master_password
        )
        contracts_dir = flinttrade_dir / "contracts"
        contracts_dir.mkdir(exist_ok=True)
        self.contract_manager = ContractManager(contracts_dir)
        self.registry = BrokerRegistry()

        # RAG — knowledge base (persistent).
        # LLMClient and RAGEngine are imported lazily here to avoid loading
        # ChromaDB, sentence-transformers, and the LLM HTTP client at module
        # level, which would add 2-5 s to startup time even when the AI
        # features are not yet used.
        rag_dir = flinttrade_dir / "rag"
        rag_dir.mkdir(exist_ok=True)
        try:
            from packages.ai.src.llm_client import LLMClient, LLMConfig  # noqa: PLC0415
            from packages.ai.src.rag import RAGEngine  # noqa: PLC0415

            try:
                _cfg = LLMConfig.from_env()
                _llm_ok = bool(_cfg.provider)
            except Exception:
                _llm_ok = False
            llm_client = LLMClient() if _llm_ok else None
            self.rag = RAGEngine(llm_client=llm_client, persist_directory=str(rag_dir))
            if self.rag.document_count() == 0:
                logger.info("RAG database empty — indexing docs/ directory in background...")
                # Index documentation in background — do not block startup
                threading.Thread(
                    target=lambda: self.rag.index_directory("docs/"),
                    daemon=True,
                    name="rag-indexer",
                ).start()
        except Exception as exc:
            logger.warning("RAG initialisation failed: %s", exc)
            self.rag = None

        self._stop_event = asyncio.Event()

        logger.info("FlintTradeApp initialised — v%s", self.version)

    async def start(self) -> None:
        """Start all services and wait until stopped."""
        # Start FlintTrade API server (Flask, port 5100)
        flask_app = create_flask_app(
            safety=self.safety,
            scheduler=self.scheduler,
            cron=self.cron,
            audit=self.audit,
            client=self.client,
            registry=self.registry,
            credential_store=self.credential_store,
            contract_manager=self.contract_manager,
            rag=self.rag,
        )
        _run_flask_server(flask_app, port=5100)

        # Load market holidays (graceful — warns if OpenAlgo unreachable)
        try:
            await self.cron.load_holidays()
        except Exception as exc:
            logger.warning("Could not load holidays (OpenAlgo may be starting): %s", exc)

        # Register built-in cron jobs
        self.cron.register_builtin_jobs()

        # Verify OpenAlgo connectivity (non-fatal). Distinguish three
        # cases so the boot log is not misleading: REACHABLE_AUTHENTICATED,
        # REACHABLE_AUTH_FAILED, UNREACHABLE.
        try:
            import httpx  # noqa: PLC0415
            from .exceptions import AuthError  # noqa: PLC0415

            try:
                result = await self.client.ping()
                broker = (
                    result.get("data", {}).get("broker", "unknown")
                    if isinstance(result, dict)
                    else "unknown"
                )
                logger.info(
                    "FlintTrade v%s started — OpenAlgo %s REACHABLE, authenticated (broker: %s)",
                    self.version, self.settings.openalgo_host, broker,
                )
            except AuthError as exc:
                # Server responded but rejected the API key — reachable,
                # auth failed.  Don't confuse users with "UNREACHABLE".
                logger.warning(
                    "FlintTrade v%s started — OpenAlgo %s REACHABLE but AUTH FAILED "
                    "(status %d): %s. Configure the API key in /setup or ~/.flinttrade/workspace.json.",
                    self.version,
                    self.settings.openalgo_host,
                    exc.status_code,
                    exc.message,
                )
            except (httpx.ConnectError, httpx.TimeoutException, OSError) as exc:
                logger.warning(
                    "FlintTrade v%s started — OpenAlgo %s UNREACHABLE (%s: %s). "
                    "Start OpenAlgo on that host/port and FlintTrade will reconnect on next call.",
                    self.version,
                    self.settings.openalgo_host,
                    type(exc).__name__,
                    exc,
                )
        except Exception as exc:
            # Any other unexpected error — log full class + message so we
            # don't pretend we know what happened.
            logger.warning(
                "FlintTrade v%s started — OpenAlgo %s verification failed (%s: %s).",
                self.version,
                self.settings.openalgo_host,
                type(exc).__name__,
                exc,
            )

        # Wait for shutdown signal
        await self._stop_event.wait()

    async def stop(self) -> None:
        """Gracefully shut down all services."""
        logger.info("FlintTrade shutting down...")

        # Stop strategies
        await self.scheduler.stop_all()

        # Stop cron
        self.cron.stop()

        # Log shutdown to audit before closing
        self.audit.log_event("APP_STOP", version=self.version)

        # Close API client
        await self.client.close()

        # Close audit logger
        self.audit.close()

        logger.info("FlintTrade v%s stopped", self.version)

        self._stop_event.set()

    def run(self) -> None:
        """Run the application (blocking). Handles Ctrl+C gracefully."""
        # NOTE: stdlib logging is already configured by create_flask_app()
        # with a structlog-backed formatter. Calling basicConfig() here
        # would add a second root handler and re-introduce the dual-emit
        # bug. Don't do it.
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        # Handle signals
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, lambda: loop.create_task(self.stop()))
            except NotImplementedError:
                # Windows doesn't support add_signal_handler
                pass

        try:
            loop.run_until_complete(self.start())
        except KeyboardInterrupt:
            loop.run_until_complete(self.stop())
        finally:
            loop.close()


if __name__ == "__main__":
    FlintTradeApp().run()


# ---------------------------------------------------------------------------
# Module-level ``app`` for gunicorn / WSGI servers.
#   Usage: ``gunicorn 'packages.core.src.app:app'``
#
# The Flask app is created LAZILY the first time ``app`` is imported from
# this module.  We avoid eagerly building it at module import because
# running ``python -m packages.core.src.app`` would create one instance
# here and another inside ``FlintTradeApp.start()``, printing every
# startup log line twice and tripping the CPython "RuntimeWarning: ...
# found in sys.modules after import of package ..." warning.
#
# Python 3.7+ supports module-level ``__getattr__`` (PEP 562) which gives
# us lazy attribute access with no change to the consumer API — WSGI
# servers do ``from packages.core.src.app import app`` and still get a
# real Flask instance on first use.
# ---------------------------------------------------------------------------

_APP_CACHE: Flask | None = None


def _get_wsgi_app() -> Flask:
    """Lazily construct (and cache) the WSGI Flask app."""
    global _APP_CACHE
    if _APP_CACHE is None:
        _APP_CACHE = create_flask_app()
    return _APP_CACHE


def __getattr__(name: str) -> Any:
    """PEP 562 module __getattr__ — produce ``app`` on first access only."""
    if name == "app":
        return _get_wsgi_app()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
