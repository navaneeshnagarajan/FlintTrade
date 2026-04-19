"""FlintTrade application entry point — wires all packages together.

Includes a lightweight Flask API server (port 5100) for FlintTrade-specific
endpoints that are separate from the OpenAlgo API (port 5000).

Usage:
    python packages/core/src/app.py
    # or: make start
"""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import signal
import sys
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
    app = Flask(__name__)

    # ------------------------------------------------------------------
    # Structured logging — structlog with JSON output in production,
    # coloured console output in debug/dev mode.
    # ------------------------------------------------------------------
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer()
            if not app.debug
            else structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # ------------------------------------------------------------------
    # Bridge stdlib logging through structlog so that ALL 250+ modules
    # using logging.getLogger() emit structured output via the same
    # pipeline as structlog calls.  We attach a ProcessorFormatter to
    # the root logger exactly once (guarded by a sentinel attribute on
    # the handler to prevent duplicate handlers across test reruns or
    # multiple create_flask_app() calls in the same process).
    # ------------------------------------------------------------------
    _sentinel_attr = "_flinttrade_structlog_bridge"
    _root_logger = logging.getLogger()
    if not any(getattr(h, _sentinel_attr, False) for h in _root_logger.handlers):
        _bridge_formatter = structlog.stdlib.ProcessorFormatter(
            processors=[
                structlog.stdlib.add_log_level,
                structlog.stdlib.add_logger_name,
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.JSONRenderer()
                if not app.debug
                else structlog.dev.ConsoleRenderer(),
            ],
        )
        _bridge_handler = logging.StreamHandler()
        _bridge_handler.setFormatter(_bridge_formatter)
        setattr(_bridge_handler, _sentinel_attr, True)
        _root_logger.addHandler(_bridge_handler)
        _root_logger.setLevel(logging.INFO)

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
        flinttrade_dir = Path.home() / ".flinttrade"
        flinttrade_dir.mkdir(exist_ok=True)
        master_password = os.environ.get("MASTER_PASSWORD", "")
        if not master_password:
            if os.environ.get("FLINTTRADE_DEV") or app.debug or "pytest" in sys.modules:
                master_password = secrets.token_urlsafe(32)
                logger.warning(
                    "MASTER_PASSWORD not set — generated random password for this session. "
                    "Set MASTER_PASSWORD env var for persistent credential storage across restarts."
                )
            else:
                raise ValueError(
                    "MASTER_PASSWORD environment variable must be set. "
                    "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(32))\""
                )
        credential_store = CredentialStore(flinttrade_dir / "credentials.db", master_password)

    if contract_manager is None:
        flinttrade_dir = Path.home() / ".flinttrade"
        flinttrade_dir.mkdir(exist_ok=True)
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

    # Register market scanner blueprint (/ft-api/v1/scanner/*)
    from packages.screener.src.scanner_routes import scanner_bp  # noqa: PLC0415
    app.register_blueprint(scanner_bp)

    # Register OI analytics blueprint (/ft-api/v1/oi/*)
    from packages.screener.src.oi_analytics_routes import oi_analytics_bp  # noqa: PLC0415
    app.register_blueprint(oi_analytics_bp)

    # Register Mutual Fund NAV blueprint (/api/v1/mf/search, /mf/nav, /mf/categories)
    from packages.screener.src.mf_routes import mf_bp  # noqa: PLC0415
    app.register_blueprint(mf_bp)

    # Register breadth + volatility cone blueprints (/ft-api/v1/breadth/*, /ft-api/v1/analytics/volcone)
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
    _security_db = Path.home() / ".flinttrade" / "security.db"
    app.config["SECURITY_TRACKER"] = _SecurityTracker(str(_security_db))

    # Register LoginActivity + SessionTracker (DuckDB-backed)
    from packages.data.src.activity_log import LoginActivity as _LoginActivity  # noqa: PLC0415
    from packages.data.src.activity_log import SessionTracker as _SessionTracker  # noqa: PLC0415
    _login_db = Path.home() / ".flinttrade" / "activity.db"
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

    # Register frontend error ingestion + changelog reader (/ft-api/v1/errors,
    # /ft-api/v1/changelog). Previously referenced by the terminal but not
    # wired, causing 404s on fire-and-forget error reports.
    from .error_log import ErrorLog as _ErrorLog  # noqa: PLC0415
    from .frontend_error_routes import frontend_errors_bp  # noqa: PLC0415
    _error_db = Path.home() / ".flinttrade" / "error_log.duckdb"
    try:
        app.config["ERROR_LOG"] = _ErrorLog(db_path=str(_error_db))
    except Exception as exc:
        logger.warning("ErrorLog initialisation failed (%s); /ft-api/v1/errors will log warnings only", exc)
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

    _error_log_path = Path.home() / ".flinttrade" / "error_log.duckdb"
    _error_log = ErrorLog(_error_log_path)
    app.config["ERROR_LOG"] = _error_log

    # ------------------------------------------------------------------
    # Global unhandled-exception handler — persists errors to DuckDB
    # before re-raising so Flask's default 500 handler takes over.
    # ------------------------------------------------------------------
    @app.errorhandler(Exception)
    def _log_unhandled_exception(exc: Exception) -> Any:
        """Persist every unhandled exception to the structured error log.

        The error is logged first (preserving the active exception context
        so traceback.format_exc() captures a full stack trace), then
        re-raised as a plain HTTP 500 JSON response to avoid leaking
        internal tracebacks to clients.
        """
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

    _traffic_log_path = Path.home() / ".flinttrade" / "traffic_log.duckdb"
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

    _latency_log_path = Path.home() / ".flinttrade" / "latency_log.duckdb"
    _latency_monitor = _LatencyMonitor(_latency_log_path)
    app.config["LATENCY_MONITOR"] = _latency_monitor

    # Initialise APIAnalyzer (DuckDB-backed, opt-in via ENABLE_ANALYZER=true).
    _analyzer_enabled = os.environ.get("ENABLE_ANALYZER", "").lower() in ("1", "true", "yes")
    if _analyzer_enabled:
        from .api_analyzer import APIAnalyzer as _APIAnalyzer  # noqa: PLC0415

        _analyzer_path = Path.home() / ".flinttrade" / "api_analyzer.duckdb"
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
    _activity_db = Path.home() / ".flinttrade" / "activity.db"
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

    # Register Earnings Calendar blueprint (/ft-api/v1/earnings/*)
    from packages.screener.src.earnings_routes import earnings_bp  # noqa: PLC0415
    app.register_blueprint(earnings_bp)

    # Register Pivot Calculator blueprint (/ft-api/v1/pivots/*)
    from packages.screener.src.pivot_routes import pivot_bp  # noqa: PLC0415
    app.register_blueprint(pivot_bp)

    # Register Economic Calendar blueprint (/ft-api/v1/economic/*)
    from packages.screener.src.economic_routes import economic_bp  # noqa: PLC0415
    app.register_blueprint(economic_bp)

    # Register Audit Trail blueprint (/ft-api/v1/audit/*)
    from packages.data.src.audit_routes import audit_bp  # noqa: PLC0415
    app.register_blueprint(audit_bp)

    # Register Analytics extensions blueprint (/ft-api/v1/indicators/vwap,
    # /ft-api/v1/analytics/pairs, /ft-api/v1/analytics/mtf)
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

    # Register Workspace Preset blueprint (/ft-api/v1/presets/*)
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
    _auth_db = Path.home() / ".flinttrade" / "auth.db"
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
        "/api/v1/errors",     # Frontend error reporting — public, rate-limited
        "/api/v1/ping",       # Liveness probe — no auth required
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
        All other /v1/ endpoints require the same API key auth.
        """
        # Allow health check without auth
        if request.endpoint in ("monitoring.health", "static"):
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

    return app


def _run_flask_server(app: Flask, port: int = 5100) -> None:
    """Run the Flask API server in a daemon thread.

    Args:
        app: Flask application instance.
        port: Port to bind (default 5100).
    """
    thread = threading.Thread(
        target=lambda: app.run(
            host="127.0.0.1",
            port=port,
            debug=False,
            use_reloader=False,
        ),
        name="flinttrade-api",
        daemon=True,
    )
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
        flinttrade_dir = Path.home() / ".flinttrade"
        flinttrade_dir.mkdir(exist_ok=True)
        master_password = os.environ.get("MASTER_PASSWORD", "")
        if not master_password:
            if os.environ.get("FLINTTRADE_DEV") or "pytest" in sys.modules:
                master_password = secrets.token_urlsafe(32)
                logger.warning(
                    "MASTER_PASSWORD not set — generated random password for this session. "
                    "Set MASTER_PASSWORD env var for persistent credential storage across restarts."
                )
            else:
                raise ValueError(
                    "MASTER_PASSWORD environment variable must be set. "
                    "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(32))\""
                )
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

        # Verify OpenAlgo connectivity (non-fatal)
        try:
            result = await self.client.ping()
            broker = result.get("data", {}).get("broker", "unknown") if isinstance(result, dict) else "unknown"
            logger.info(
                "FlintTrade v%s started — OpenAlgo: %s (broker: %s)",
                self.version, self.settings.openalgo_host, broker,
            )
        except Exception as exc:
            logger.warning(
                "FlintTrade v%s started — OpenAlgo at %s is UNREACHABLE: %s. "
                "Will retry when orders are placed.",
                self.version, self.settings.openalgo_host, exc,
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
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

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

# Module-level app instance for gunicorn/WSGI servers.
# Usage: gunicorn 'packages.core.src.app:app'
app = create_flask_app()
