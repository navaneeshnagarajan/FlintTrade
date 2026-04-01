"""FlintTrade application entry point — wires all packages together.

Includes a lightweight Flask API server (port 5001) for FlintTrade-specific
endpoints that are separate from the OpenAlgo API (port 5000).

Usage:
    python packages/core/src/app.py
    # or: make start
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
import threading
from pathlib import Path
from typing import Any

# Ensure repo root is on sys.path for cross-package imports
_REPO_ROOT = str(Path(__file__).resolve().parents[3])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import time  # noqa: E402

from flask import Flask, jsonify, request  # noqa: E402

from packages.core.src.config import Settings  # noqa: E402
from packages.core.src.openalgo_client import OpenAlgoClient  # noqa: E402
from packages.data.src.audit_logger import AuditLogger  # noqa: E402
from packages.engine.src.router import OrderRouter  # noqa: E402
from packages.engine.src.safety import SafetyConfig, SafetySystem  # noqa: E402
from packages.engine.src.scheduler import StrategyScheduler, TimeScheduler  # noqa: E402
from packages.automation.src.cron_manager import CronManager  # noqa: E402
from packages.automation.src.telegram_bot import TelegramBot  # noqa: E402
from packages.ai.src.llm_client import LLMClient, LLMConfig  # noqa: E402
from packages.ai.src.rag import RAGEngine  # noqa: E402

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
# Flask API server — FlintTrade-specific endpoints (port 5001)
# ---------------------------------------------------------------------------


def create_flask_app(
    safety: SafetySystem | None = None,
    scheduler: StrategyScheduler | None = None,
    cron: CronManager | None = None,
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
        import secrets as _secrets  # noqa: PLC0415

        flinttrade_dir = Path.home() / ".flinttrade"
        flinttrade_dir.mkdir(exist_ok=True)
        master_password = os.environ.get("MASTER_PASSWORD", "")
        if not master_password:
            if os.environ.get("FLINTTRADE_DEV") or app.debug or "pytest" in sys.modules:
                master_password = _secrets.token_urlsafe(32)
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

    # Register analysis blueprint (GEX, vol surface, IV smile, straddle P&L, OI profile, max pain)
    from packages.screener.src.analysis_routes import analysis_bp  # noqa: PLC0415
    app.register_blueprint(analysis_bp)

    # Register stock screener blueprint (/v1/stocks/*)
    from packages.screener.src.stock_routes import stock_bp  # noqa: PLC0415
    app.register_blueprint(stock_bp)

    # Register Action Center blueprint (/v1/action-center/*)
    from packages.engine.src.action_center import ActionCenter  # noqa: PLC0415
    from packages.engine.src.action_center_routes import action_center_bp  # noqa: PLC0415
    action_center = ActionCenter()
    app.config["ACTION_CENTER"] = action_center
    app.register_blueprint(action_center_bp)

    # Register Security blueprint and middleware (/v1/security/*)
    from packages.core.src.security import SecurityMonitor  # noqa: PLC0415
    from packages.core.src.security_routes import register_security_middleware, security_bp  # noqa: PLC0415
    security_monitor = SecurityMonitor()
    app.config["SECURITY_MONITOR"] = security_monitor
    app.register_blueprint(security_bp)
    register_security_middleware(app, security_monitor)

    # Register P&L tracker blueprint
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

    # Register monitoring blueprint (health, traffic, latency)
    from packages.core.src.monitoring_routes import monitoring_bp  # noqa: PLC0415
    app.register_blueprint(monitoring_bp)

    # Register Strategy Runner blueprint (/v1/strategies/*)
    from packages.engine.src.strategy_routes import strategy_bp  # noqa: PLC0415
    app.register_blueprint(strategy_bp)

    # Register Sandbox blueprint (/v1/sandbox/*)
    from packages.engine.src.sandbox_routes import sandbox_bp  # noqa: PLC0415
    app.register_blueprint(sandbox_bp)

    # Register admin blueprint (dev/debug only)
    if app.debug or os.environ.get("FLINTTRADE_DEV"):
        from packages.core.src.admin_routes import admin_bp  # noqa: PLC0415
        app.register_blueprint(admin_bp)
        logger.info("Admin endpoints registered (dev mode)")

    # Register extracted inline-route blueprints
    from packages.core.src.indicators_routes import indicators_bp  # noqa: PLC0415
    app.register_blueprint(indicators_bp)

    from packages.ai.src.advisor_routes import advisor_bp  # noqa: PLC0415
    app.register_blueprint(advisor_bp)

    from packages.ai.src.ai_routes import ai_bp  # noqa: PLC0415
    app.register_blueprint(ai_bp)

    from packages.core.src.backtest_routes import backtest_bp  # noqa: PLC0415
    app.register_blueprint(backtest_bp)

    from packages.core.src.operations_routes import operations_bp  # noqa: PLC0415
    app.register_blueprint(operations_bp)

    # Reconnect saved accounts (best-effort, don't block startup)
    try:
        _reconnect_saved_accounts(registry, credential_store, logger)
    except Exception as exc:
        logger.error("Account reconnection failed: %s", exc)

    # Specific /v1/ paths that are legitimately public (no API key needed):
    # - Health check endpoint
    # - Admin introspect (already gated by FLINTTRADE_DEV in admin_routes)
    # - OAuth callbacks (browser redirect — no API key in URL)
    _PUBLIC_V1_PREFIXES = (
        "/v1/admin/health",
        "/v1/admin/introspect",
        "/v1/auth/callback",
    )

    @app.before_request
    def require_auth() -> Any:
        """Require API key authentication on all endpoints.

        Only specific public paths are exempted:
        - Health check and admin introspect (dev-gated)
        - OAuth callback (browser redirect, no API key in URL)
        All other /v1/ endpoints require the same API key auth.
        """
        # Allow health check without auth
        if request.endpoint in ("health", "static"):
            return None
        # Allow OPTIONS for CORS preflight
        if request.method == "OPTIONS":
            return None
        # Allow specific public /v1/ paths only
        if any(request.path.startswith(prefix) for prefix in _PUBLIC_V1_PREFIXES):
            return None

        import hmac as _hmac  # noqa: PLC0415

        api_key = (
            request.headers.get("X-API-Key")
            or request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        )

        expected_key = os.environ.get("OPENALGO_API_KEY", "")
        if not expected_key:
            logger.warning("OPENALGO_API_KEY not set — all requests will be rejected")
            return jsonify({"status": "error", "message": "Server not configured"}), 503

        if not api_key or not _hmac.compare_digest(api_key, expected_key):
            # Record auth failure for brute-force detection
            try:
                sec = app.config.get("SECURITY_MONITOR")
                if sec:
                    sec.record_auth_failure(request.remote_addr or "unknown")
            except Exception:
                pass
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
        import flask  # noqa: PLC0415
        flask.g._request_start = time.monotonic()

    @app.after_request
    def _record_traffic(response: Any) -> Any:
        """Record method, path, status, and duration in TrafficCounter."""
        try:
            import flask  # noqa: PLC0415
            from packages.core.src.monitoring_routes import get_traffic_counter  # noqa: PLC0415

            start = getattr(flask.g, "_request_start", None)
            duration_ms = (time.monotonic() - start) * 1000 if start is not None else 0.0
            get_traffic_counter().record(
                method=request.method,
                path=request.path,
                status=response.status_code,
                duration_ms=duration_ms,
            )
        except Exception:
            pass  # Never let monitoring break the response
        return response

    # --- inline route handlers extracted to blueprints ---
    # indicators_bp  → packages/core/src/indicators_routes.py
    # advisor_bp     → packages/ai/src/advisor_routes.py
    # ai_bp          → packages/ai/src/ai_routes.py
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
            from packages.core.src.openalgo_client import OpenAlgoClient  # noqa: PLC0415
            client = OpenAlgoClient(Settings.from_env())
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(client.place_order(**params))
            finally:
                loop.run_until_complete(client.close())
                loop.close()

        def _mcp_get_positions(**params: Any) -> dict[str, Any]:
            """Route MCP get_positions through OpenAlgo (sync wrapper)."""
            from packages.core.src.openalgo_client import OpenAlgoClient  # noqa: PLC0415
            client = OpenAlgoClient(Settings.from_env())
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(client.positionbook())
            finally:
                loop.run_until_complete(client.close())
                loop.close()

        _mcp_bridge.register_handler("place_order", _mcp_place_order)
        _mcp_bridge.register_handler("get_positions", _mcp_get_positions)
        logger.info("MCP bridge initialized with place_order, get_positions handlers")
    except Exception:
        logger.debug("MCP bridge not available — skipping handler registration")

    return app


def _run_flask_server(app: Flask, port: int = 5001) -> None:
    """Run the Flask API server in a daemon thread.

    Args:
        app: Flask application instance.
        port: Port to bind (default 5001).
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

        # Engine — safety + router + scheduler
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

        # Automation — cron manager
        self.cron = CronManager(
            openalgo_client=self.client,
            audit_logger=self.audit,
        )

        # Automation — Telegram bot (optional — token may not be set)
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
        import secrets as _secrets  # noqa: PLC0415
        master_password = os.environ.get("MASTER_PASSWORD", "")
        if not master_password:
            if os.environ.get("FLINTTRADE_DEV") or "pytest" in sys.modules:
                master_password = _secrets.token_urlsafe(32)
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

        # RAG — knowledge base (persistent)
        rag_dir = flinttrade_dir / "rag"
        rag_dir.mkdir(exist_ok=True)
        try:
            try:
                _cfg = LLMConfig.from_env()
                _llm_ok = bool(_cfg.provider)
            except Exception:
                _llm_ok = False
            llm_client = LLMClient() if _llm_ok else None
            self.rag = RAGEngine(llm_client=llm_client, persist_directory=str(rag_dir))
            if self.rag.document_count() == 0:
                logger.info("RAG database empty — indexing docs/ directory...")
                self.rag.index_directory("docs/")
        except Exception as exc:
            logger.warning("RAG initialization failed: %s", exc)
            self.rag = None

        self._stop_event = asyncio.Event()

        logger.info("FlintTradeApp initialized — v%s", self.version)

    async def start(self) -> None:
        """Start all services and wait until stopped."""
        # Start FlintTrade API server (Flask, port 5001)
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
        _run_flask_server(flask_app, port=5001)

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
