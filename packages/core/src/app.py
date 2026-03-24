"""FlintTrade application entry point — wires all packages together.

Includes a lightweight Flask API server (port 5001) for FlintTrade-specific
endpoints that are separate from the OpenAlgo API (port 5000).

Usage:
    python packages/core/src/app.py
    # or: make start
"""

from __future__ import annotations

import asyncio
import json as _json
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

import math  # noqa: E402
import time  # noqa: E402

import numpy as np  # noqa: E402
from flask import Flask, Response, jsonify, request  # noqa: E402

from packages.core.src.config import Settings  # noqa: E402
from packages.core.src.openalgo_client import OpenAlgoClient  # noqa: E402
from packages.data.src.audit_logger import AuditLogger  # noqa: E402
from packages.engine.src.router import OrderRouter  # noqa: E402
from packages.engine.src.safety import SafetyConfig, SafetySystem  # noqa: E402
from packages.engine.src.scheduler import StrategyScheduler, TimeScheduler  # noqa: E402
from packages.automation.src.cron_manager import CronManager  # noqa: E402
from packages.automation.src.telegram_bot import TelegramBot  # noqa: E402
from packages.ai.src.llm_client import LLMClient, LLMConfig, LLMMessage  # noqa: E402

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

_SYSTEM_PROMPT = (
    "You are FlintTrade AI Advisor, a knowledgeable trading assistant for "
    "Indian markets (NSE, BSE, NFO, MCX). You help with market analysis, "
    "options strategies, technical indicators, and portfolio management. "
    "Be concise, accurate, and always remind users that your responses are "
    "informational — not financial advice. Never recommend specific trades "
    "without proper risk disclaimers."
)


def _is_llm_configured() -> bool:
    """Check whether the LLM provider is configured."""
    try:
        cfg = LLMConfig.from_env()
        return bool(cfg.provider)
    except Exception:
        return False


def create_flask_app(
    safety: SafetySystem | None = None,
    scheduler: StrategyScheduler | None = None,
    cron: CronManager | None = None,
    audit: AuditLogger | None = None,
    client: OpenAlgoClient | None = None,
    registry: BrokerRegistry | None = None,
    credential_store: CredentialStore | None = None,
    contract_manager: ContractManager | None = None,
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
        flinttrade_dir = Path.home() / ".flinttrade"
        flinttrade_dir.mkdir(exist_ok=True)
        master_password = os.environ.get("MASTER_PASSWORD", "")
        if not master_password:
            master_password = "flinttrade-dev-default"
            logger.warning(
                "MASTER_PASSWORD not set — using development default. Set it for production."
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

    # Register gateway blueprint (mounts at /ft-api/v1/)
    app.register_blueprint(gateway_bp)

    # Register analysis blueprint (GEX, vol surface, IV smile, straddle P&L, OI profile, max pain)
    from packages.screener.src.analysis_routes import analysis_bp  # noqa: PLC0415
    app.register_blueprint(analysis_bp)

    # Register Action Center blueprint (/ft-api/v1/action-center/*)
    from packages.engine.src.action_center import ActionCenter  # noqa: PLC0415
    from packages.engine.src.action_center_routes import action_center_bp  # noqa: PLC0415
    action_center = ActionCenter()
    app.config["ACTION_CENTER"] = action_center
    app.register_blueprint(action_center_bp)

    # Register Security blueprint and middleware (/ft-api/v1/security/*)
    from packages.core.src.security import SecurityMonitor  # noqa: PLC0415
    from packages.core.src.security_routes import register_security_middleware, security_bp  # noqa: PLC0415
    security_monitor = SecurityMonitor()
    app.config["SECURITY_MONITOR"] = security_monitor
    app.register_blueprint(security_bp)
    register_security_middleware(app, security_monitor)

    # Register P&L tracker blueprint
    from packages.data.src.pnl_routes import pnl_bp  # noqa: PLC0415
    app.register_blueprint(pnl_bp)

    # Register Historify watchlist blueprint
    from packages.historical.src.watchlist_routes import historify_bp  # noqa: PLC0415
    app.register_blueprint(historify_bp)

    # Register monitoring blueprint (health, traffic, latency)
    from packages.core.src.monitoring_routes import monitoring_bp  # noqa: PLC0415
    app.register_blueprint(monitoring_bp)

    # Register admin blueprint (dev/debug only)
    if app.debug or os.environ.get("FLINTTRADE_DEV"):
        from packages.core.src.admin_routes import admin_bp  # noqa: PLC0415
        app.register_blueprint(admin_bp)
        logger.info("Admin endpoints registered (dev mode)")

    # Reconnect saved accounts (best-effort, don't block startup)
    try:
        _reconnect_saved_accounts(registry, credential_store, logger)
    except Exception as exc:
        logger.error("Account reconnection failed: %s", exc)

    @app.before_request
    def require_auth() -> Any:
        """Require API key authentication on all endpoints.

        Gateway endpoints under /ft-api/v1/brokers and /ft-api/v1/auth/
        are public (broker catalog listing, OAuth callback) or manage their
        own account-level credentials — they do not use the FlintTrade API key.
        All other /ft-api/v1/ endpoints (accounts, reconnect, set-primary) are
        also exempted here because account management uses the gateway's own
        credential/session model rather than the server-level API key.
        """
        # Allow health check without auth
        if request.endpoint in ("health", "static"):
            return None
        # Allow OPTIONS for CORS preflight
        if request.method == "OPTIONS":
            return None
        # Gateway endpoints handle their own auth — exempt the entire /ft-api/ namespace
        if request.path.startswith("/ft-api/"):
            return None

        api_key = (
            request.headers.get("X-API-Key")
            or request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        )
        if not api_key:
            body = request.get_json(silent=True) or {}
            api_key = body.get("apikey", "")

        expected_key = os.environ.get("OPENALGO_API_KEY", "")
        if not expected_key:
            logger.warning("OPENALGO_API_KEY not set — all requests will be rejected")
            return jsonify({"status": "error", "message": "Server not configured"}), 503

        if api_key != expected_key:
            return jsonify({"status": "error", "message": "Unauthorized"}), 401

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

    @app.route("/api/v1/indicators/compute", methods=["POST"])
    def indicators_compute() -> tuple[Any, int]:
        """Compute one or more technical indicators over a OHLCV bar series.

        Request JSON:
            bars (list[dict]): OHLCV bars, each with keys
                ``time`` (int, Unix seconds), ``open``, ``high``, ``low``,
                ``close`` (float), ``volume`` (float, optional).
            indicators (list[str]): Indicator names such as ``"ema_20"``,
                ``"macd"``, ``"bollinger_bands_20"``, ``"atr_14"``.

        Returns:
            JSON with ``status`` and ``data`` mapping each indicator name to
            its computed values on success, or ``status`` and ``message``
            on error.  Arrays contain ``null`` for bars with insufficient
            history.  Multi-line indicators (MACD, Bollinger Bands, Keltner
            Channels) return a dict of named sub-arrays.
        """
        from packages.indicators.src import (  # noqa: PLC0415
            atr,
            bollinger_bands,
            cci,
            dema,
            ema,
            hull,
            keltner_channels,
            macd,
            obv,
            parabolic_sar,
            rsi,
            sma,
            supertrend,
            vwap,
            vwma,
            williams_r,
            wma,
        )

        body = request.get_json(silent=True) or {}
        raw_bars = body.get("bars")
        raw_indicators = body.get("indicators")

        if not isinstance(raw_bars, list) or len(raw_bars) == 0:
            return jsonify({
                "status": "error",
                "message": "bars must be a non-empty list.",
            }), 400

        if not isinstance(raw_indicators, list) or len(raw_indicators) == 0:
            return jsonify({
                "status": "error",
                "message": "indicators must be a non-empty list of strings.",
            }), 400

        if len(raw_bars) > 2000:
            return jsonify({
                "status": "error",
                "message": "Maximum 2000 bars per request.",
            }), 400

        # Validate and unpack bars
        try:
            # opens is validated for presence but not needed for indicator calcs
            _ = [float(b["open"]) for b in raw_bars]
            highs   = np.array([float(b["high"])   for b in raw_bars], dtype=np.float64)
            lows    = np.array([float(b["low"])    for b in raw_bars], dtype=np.float64)
            closes  = np.array([float(b["close"])  for b in raw_bars], dtype=np.float64)
            volumes = np.array(
                [float(b.get("volume", 0) or 0) for b in raw_bars], dtype=np.float64
            )
            _ = [int(b["time"]) for b in raw_bars]  # validate time field exists
        except (KeyError, TypeError, ValueError) as exc:
            return jsonify({
                "status": "error",
                "message": f"Invalid bar data: {exc}",
            }), 400

        def _to_list(arr: "np.ndarray") -> list:
            """Convert numpy array to JSON-serialisable list (NaN -> None)."""
            return [None if math.isnan(v) else float(v) for v in arr]

        def _parse_period(name: str, default: int) -> int:
            parts = name.rsplit("_", 1)
            if len(parts) == 2:
                try:
                    return int(parts[1])
                except ValueError:
                    pass
            return default

        result: dict[str, object] = {}

        for ind_name in raw_indicators:
            if not isinstance(ind_name, str):
                result[str(ind_name)] = {"error": "indicator name must be a string"}
                continue

            key = ind_name.lower().strip()
            try:
                # --- trend ---
                if key.startswith("ema"):
                    period = _parse_period(key, 20)
                    result[ind_name] = _to_list(ema(closes, period))

                elif key.startswith("sma"):
                    period = _parse_period(key, 20)
                    result[ind_name] = _to_list(sma(closes, period))

                elif key.startswith("dema"):
                    period = _parse_period(key, 20)
                    result[ind_name] = _to_list(dema(closes, period))

                elif key.startswith("wma"):
                    period = _parse_period(key, 20)
                    result[ind_name] = _to_list(wma(closes, period))

                elif key.startswith("hull"):
                    period = _parse_period(key, 20)
                    result[ind_name] = _to_list(hull(closes, period))

                elif key.startswith("vwap"):
                    result[ind_name] = _to_list(
                        vwap(highs, lows, closes, volumes)
                    )

                elif key.startswith("supertrend"):
                    st_vals, st_dir = supertrend(highs, lows, closes)
                    # Split into up (uptrend values) and down (downtrend values)
                    up_arr = np.where(st_dir, st_vals, np.nan)
                    down_arr = np.where(~st_dir, st_vals, np.nan)
                    result[ind_name] = {
                        "up": _to_list(up_arr),
                        "down": _to_list(down_arr),
                    }

                elif key.startswith("parabolic_sar"):
                    result[ind_name] = _to_list(parabolic_sar(highs, lows))

                # --- momentum ---
                elif key.startswith("rsi"):
                    period = _parse_period(key, 14)
                    result[ind_name] = _to_list(rsi(closes, period))

                elif key == "macd":
                    m_line, m_signal, m_hist = macd(closes)
                    result[ind_name] = {
                        "line": _to_list(m_line),
                        "signal": _to_list(m_signal),
                        "histogram": _to_list(m_hist),
                    }

                elif key.startswith("williams_r"):
                    period = _parse_period(key, 14)
                    result[ind_name] = _to_list(williams_r(highs, lows, closes, period))

                elif key.startswith("cci"):
                    period = _parse_period(key, 20)
                    result[ind_name] = _to_list(cci(highs, lows, closes, period))

                # --- volatility ---
                elif key.startswith("bollinger_bands"):
                    period = _parse_period(key, 20)
                    upper, middle, lower = bollinger_bands(closes, period)
                    result[ind_name] = {
                        "upper": _to_list(upper),
                        "middle": _to_list(middle),
                        "lower": _to_list(lower),
                    }

                elif key.startswith("atr"):
                    period = _parse_period(key, 14)
                    result[ind_name] = _to_list(atr(highs, lows, closes, period))

                elif key.startswith("keltner_channels"):
                    period = _parse_period(key, 20)
                    upper, middle, lower = keltner_channels(
                        highs, lows, closes, ema_period=period
                    )
                    result[ind_name] = {
                        "upper": _to_list(upper),
                        "middle": _to_list(middle),
                        "lower": _to_list(lower),
                    }

                # --- volume ---
                elif key == "obv":
                    result[ind_name] = _to_list(obv(closes, volumes))

                elif key.startswith("vwma"):
                    period = _parse_period(key, 20)
                    result[ind_name] = _to_list(vwma(closes, volumes, period))

                else:
                    result[ind_name] = {"error": f"unknown indicator: {ind_name!r}"}

            except Exception as exc:  # noqa: BLE001
                logger.warning("Indicator %r error: %s", ind_name, exc)
                result[ind_name] = {"error": str(exc)}

        return jsonify({"status": "success", "data": result}), 200

    @app.route("/api/v1/advisor", methods=["POST"])
    def advisor_chat() -> tuple[Any, int]:
        """Chat with the AI advisor via the configured LLM backend.

        Request JSON (conversation history — preferred):
            messages (list[dict]): Array of ``{role, content}`` dicts.
            context (str, optional): Additional context (e.g. current positions).

        Request JSON (legacy single-message):
            message (str): User's message text.
            context (str, optional): Additional context.

        Returns:
            JSON with ``status`` and ``data.response`` on success, or
            ``status`` and ``message`` on error.
        """
        if not _is_llm_configured():
            return jsonify({
                "status": "error",
                "message": (
                    "LLM not configured. Set provider in Settings \u2192 AI."
                ),
            }), 200

        body = request.get_json(silent=True) or {}
        context: str = body.get("context", "").strip()

        # Accept messages[] array (new) or message string (legacy)
        raw_messages = body.get("messages")
        if isinstance(raw_messages, list) and raw_messages:
            # Conversation history supplied by the frontend
            conversation: list[LLMMessage] = [
                LLMMessage(role="system", content=_SYSTEM_PROMPT),
            ]
            if context:
                conversation.append(LLMMessage(
                    role="system",
                    content=f"Current trading context:\n{context}",
                ))
            for msg in raw_messages:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role and content:
                    conversation.append(LLMMessage(role=role, content=content))
        else:
            # Legacy: single message string
            user_message: str = body.get("message", "").strip()
            if not user_message:
                return jsonify({
                    "status": "error",
                    "message": "message or messages field is required.",
                }), 400
            conversation = [
                LLMMessage(role="system", content=_SYSTEM_PROMPT),
            ]
            if context:
                conversation.append(LLMMessage(
                    role="system",
                    content=f"Current trading context:\n{context}",
                ))
            conversation.append(LLMMessage(role="user", content=user_message))

        try:
            client = LLMClient()
            response = client.chat(conversation)
            client.close()

            if response.success:
                return jsonify({
                    "status": "success",
                    "data": {"response": response.content},
                }), 200

            return jsonify({
                "status": "error",
                "message": f"LLM error: {response.error}",
            }), 200
        except Exception:
            logger.exception("Advisor endpoint error")
            return jsonify({
                "status": "error",
                "message": "Internal server error",
            }), 500

    @app.route("/api/v1/advisor/stream", methods=["POST"])
    def advisor_stream() -> Response | tuple[Any, int]:
        """SSE streaming variant of the advisor endpoint.

        Accepts the same request body as ``/api/v1/advisor`` (messages[]
        array or legacy message string).  Returns a ``text/event-stream``
        response where each event carries a ``token`` field and the final
        event carries ``done: true``.
        """
        if not _is_llm_configured():
            return jsonify({
                "status": "error",
                "message": "LLM not configured. Set provider in Settings \u2192 AI.",
            }), 200

        body = request.get_json(silent=True) or {}
        context: str = body.get("context", "").strip()

        # Build conversation (same logic as /advisor)
        raw_messages = body.get("messages")
        if isinstance(raw_messages, list) and raw_messages:
            conversation: list[LLMMessage] = [
                LLMMessage(role="system", content=_SYSTEM_PROMPT),
            ]
            if context:
                conversation.append(LLMMessage(
                    role="system",
                    content=f"Current trading context:\n{context}",
                ))
            for msg in raw_messages:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role and content:
                    conversation.append(LLMMessage(role=role, content=content))
        else:
            user_message = body.get("message", "").strip()
            if not user_message:
                return jsonify({
                    "status": "error",
                    "message": "message or messages field is required.",
                }), 400
            conversation = [
                LLMMessage(role="system", content=_SYSTEM_PROMPT),
            ]
            if context:
                conversation.append(LLMMessage(
                    role="system",
                    content=f"Current trading context:\n{context}",
                ))
            conversation.append(LLMMessage(role="user", content=user_message))

        def _generate():  # type: ignore[no-untyped-def]
            try:
                client = LLMClient()
                for token in client.chat_stream(conversation):
                    yield f"data: {_json.dumps({'token': token})}\n\n"
                yield f"data: {_json.dumps({'done': True})}\n\n"
                client.close()
            except Exception:
                logger.exception("Advisor stream error")
                yield f"data: {_json.dumps({'error': 'Internal server error'})}\n\n"

        return Response(_generate(), content_type="text/event-stream")

    @app.route("/api/v1/advisor/status", methods=["GET"])
    def advisor_status() -> tuple[Any, int]:
        """Check whether the AI advisor LLM backend is configured."""
        configured = _is_llm_configured()
        cfg = LLMConfig.from_env() if configured else None
        return jsonify({
            "status": "success",
            "data": {
                "configured": configured,
                "provider": cfg.provider if cfg else "",
                "model": cfg.model if cfg else "",
            },
        }), 200

    @app.route("/api/v1/signals", methods=["GET"])
    def get_signals() -> tuple[Any, int]:
        """Return current signal state (stub — populated by signal pipeline)."""
        return jsonify({
            "status": "success",
            "data": {"signals": []},
        }), 200

    # ------------------------------------------------------------------
    # Backtest
    # ------------------------------------------------------------------

    @app.route("/api/v1/backtest/run", methods=["POST"])
    def backtest_run() -> tuple[Any, int]:
        """Run a backtest for a given symbol and strategy.

        Request JSON:
            symbol (str): Trading symbol (e.g. ``"RELIANCE"``).
            exchange (str): Exchange code (e.g. ``"NSE"``).
            interval (str): Bar interval such as ``"5m"``, ``"1d"``.
            start_date (str): Start date in ``YYYY-MM-DD`` format.
            end_date (str): End date in ``YYYY-MM-DD`` format.
            strategy (str): Strategy name — must be a key in BUILTIN_STRATEGIES.
            initial_capital (float, optional): Starting capital (default 1 000 000).
            position_size_pct (float, optional): Position size as % of capital (default 10).

        Returns:
            JSON with ``status`` and ``data`` containing ``trades``,
            ``equity_curve``, and ``metrics`` on success, or ``status``
            and ``message`` on error.
        """
        # backtest-engine has a hyphen in its directory name which prevents
        # regular Python imports.  Inject its src dir onto sys.path temporarily
        # so direct imports resolve, then remove it to avoid polluting the path.
        import importlib  # noqa: PLC0415
        _be_src = str(Path(_REPO_ROOT) / "packages" / "backtest-engine" / "src")
        _be_src_added = _be_src not in sys.path
        if _be_src_added:
            sys.path.insert(0, _be_src)
        try:
            _sim_mod = importlib.import_module("simulator")
            _strat_mod = importlib.import_module("strategies")
            _dc_mod = importlib.import_module("data_connector")
            _met_mod = importlib.import_module("metrics")
            BacktestConfig = _sim_mod.BacktestConfig
            BacktestSimulator = _sim_mod.BacktestSimulator
            BUILTIN_STRATEGIES = _strat_mod.BUILTIN_STRATEGIES
            DataConnector = _dc_mod.DataConnector
            PerformanceMetrics = _met_mod.PerformanceMetrics
        finally:
            if _be_src_added and _be_src in sys.path:
                sys.path.remove(_be_src)

        body = request.get_json(silent=True) or {}
        symbol: str = body.get("symbol", "").strip()
        exchange: str = body.get("exchange", "NSE").strip()
        interval: str = body.get("interval", "5m").strip()
        start_date: str = body.get("start_date", "").strip()
        end_date: str = body.get("end_date", "").strip()
        strategy_name: str = body.get("strategy", "").strip()
        initial_capital: float = float(body.get("initial_capital", 1_000_000))
        position_size_pct: float = float(body.get("position_size_pct", 10.0))

        if not symbol:
            return jsonify({"status": "error", "message": "symbol is required"}), 400
        if not strategy_name:
            return jsonify({"status": "error", "message": "strategy is required"}), 400

        strategy_cls = BUILTIN_STRATEGIES.get(strategy_name)
        if strategy_cls is None:
            available = list(BUILTIN_STRATEGIES.keys())
            return jsonify({
                "status": "error",
                "message": f"Unknown strategy '{strategy_name}'. Available: {available}",
            }), 400

        try:
            dc = DataConnector()
            data_result = dc.load(symbol, exchange, interval, start_date, end_date)
        except Exception:
            logger.exception("Backtest data load error")
            return jsonify({"status": "error", "message": "Internal server error"}), 500

        if not data_result.success:
            return jsonify({
                "status": "error",
                "message": f"No data available: {data_result.error or 'unknown error'}",
            }), 400

        try:
            config = BacktestConfig(
                symbol=symbol,
                exchange=exchange,
                interval=interval,
                start_date=start_date,
                end_date=end_date,
                initial_capital=initial_capital,
                position_size_pct=position_size_pct,
            )
            sim = BacktestSimulator(config)
            strategy_instance = strategy_cls(
                name=strategy_name,
                exchange=exchange,
                symbol=symbol,
            )
            result = sim.run(strategy_instance, data_result.bars)
        except Exception:
            logger.exception("Backtest simulation error")
            return jsonify({"status": "error", "message": "Internal server error"}), 500

        try:
            report = PerformanceMetrics.compute(result)
            metrics = {
                "total_return": report.total_return_pct,
                "cagr": report.cagr,
                "sharpe": report.sharpe_ratio,
                "sortino": report.sortino_ratio,
                "max_drawdown": report.drawdown.max_drawdown_pct,
                "win_rate": report.trade_stats.win_rate,
                "profit_factor": report.trade_stats.profit_factor,
                "total_trades": report.trade_stats.total_trades,
            }
        except Exception as exc:
            logger.warning("Metrics computation error: %s", exc)
            metrics = {"total_return": result.total_return_pct}

        trades = [
            {
                "entry_timestamp": t.entry_timestamp,
                "exit_timestamp": t.exit_timestamp,
                "symbol": t.symbol,
                "side": t.side,
                "quantity": t.quantity,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "pnl": t.pnl,
                "net_pnl": t.net_pnl,
                "commission": t.commission,
                "bars_held": t.bars_held,
            }
            for t in result.trades
        ]
        equity_curve = [
            {
                "timestamp": pt.timestamp,
                "equity": pt.equity,
                "cash": pt.cash,
                "drawdown": pt.drawdown,
            }
            for pt in result.equity_curve
        ]

        return jsonify({
            "status": "success",
            "data": {
                "trades": trades,
                "equity_curve": equity_curve,
                "metrics": metrics,
                "total_bars": result.total_bars,
                "final_equity": result.final_equity,
            },
        }), 200

    # ------------------------------------------------------------------
    # Strategies
    # ------------------------------------------------------------------

    @app.route("/api/v1/strategies", methods=["GET"])
    def list_strategies() -> tuple[Any, int]:
        """Return available backtest strategy names and descriptions.

        Returns:
            JSON with ``status`` and ``data.strategies`` — a list of objects
            with ``name`` and ``description`` fields.
        """
        try:
            import importlib  # noqa: PLC0415
            _be_src = str(Path(_REPO_ROOT) / "packages" / "backtest-engine" / "src")
            _be_src_added = _be_src not in sys.path
            if _be_src_added:
                sys.path.insert(0, _be_src)
            try:
                _strat_mod = importlib.import_module("strategies")
                _bi: dict = _strat_mod.BUILTIN_STRATEGIES
            finally:
                if _be_src_added and _be_src in sys.path:
                    sys.path.remove(_be_src)

            strategies = [
                {"name": name, "description": cls.__doc__.split("\n")[0].strip() if cls.__doc__ else name}
                for name, cls in _bi.items()
            ]
        except Exception as exc:
            logger.warning("Could not load BUILTIN_STRATEGIES: %s", exc)
            # Hardcoded fallback list matching the known 12 strategies
            strategies = [
                {"name": "EMACrossover",       "description": "EMA crossover strategy: buy when fast EMA > slow EMA"},
                {"name": "Supertrend",          "description": "Supertrend indicator strategy"},
                {"name": "MACD_RSI",            "description": "MACD + RSI combined momentum strategy"},
                {"name": "BollingerMR",         "description": "Bollinger Bands mean-reversion strategy"},
                {"name": "VWAPDev",             "description": "VWAP deviation mean-reversion strategy"},
                {"name": "StraddleSell",        "description": "Short straddle options-selling strategy"},
                {"name": "StrangleSell",        "description": "Short strangle options-selling strategy"},
                {"name": "IronCondor",          "description": "Iron condor multi-leg options strategy"},
                {"name": "BullPutSpread",       "description": "Bull put spread credit strategy"},
                {"name": "BearCallSpread",      "description": "Bear call spread credit strategy"},
                {"name": "MomentumBreakout",    "description": "Momentum breakout strategy on volume surge"},
                {"name": "ORB",                 "description": "Opening Range Breakout intraday strategy"},
            ]
        return jsonify({"status": "success", "data": {"strategies": strategies}}), 200

    @app.route("/api/v1/strategies/running", methods=["GET"])
    def strategies_running() -> tuple[Any, int]:
        """Return status of all currently registered and running strategies.

        Returns:
            JSON with ``status`` and ``data.strategies`` — a list of objects
            with ``name``, ``state``, ``is_running``, ``exchange``, and
            ``tick_count`` fields.
        """
        _scheduler: StrategyScheduler | None = app.config.get("SCHEDULER")
        if _scheduler is None:
            return jsonify({"status": "success", "data": {"strategies": []}}), 200

        try:
            status_map = _scheduler.status()
            strategies_list = [
                {"name": name, **info}
                for name, info in status_map.items()
            ]
            return jsonify({"status": "success", "data": {"strategies": strategies_list}}), 200
        except Exception:
            logger.exception("strategies_running error")
            return jsonify({"status": "error", "message": "Internal server error"}), 500

    @app.route("/api/v1/strategies/<name>/start", methods=["POST"])
    def strategy_start(name: str) -> tuple[Any, int]:
        """Start a registered strategy by name.

        Args:
            name: Strategy name as registered in the scheduler.

        Returns:
            JSON with ``status`` and confirmation message.
        """
        _scheduler: StrategyScheduler | None = app.config.get("SCHEDULER")
        if _scheduler is None:
            return jsonify({"status": "error", "message": "Scheduler not available"}), 503

        runner = _scheduler.get_runner(name)
        if runner is None:
            return jsonify({"status": "error", "message": f"Strategy '{name}' not registered"}), 404

        try:
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(runner.start())
            finally:
                loop.close()
            return jsonify({"status": "success", "data": {"message": f"Strategy '{name}' started"}}), 200
        except Exception:
            logger.exception("strategy_start error for %s", name)
            return jsonify({"status": "error", "message": "Internal server error"}), 500

    @app.route("/api/v1/strategies/<name>/stop", methods=["POST"])
    def strategy_stop(name: str) -> tuple[Any, int]:
        """Stop a running strategy by name.

        Args:
            name: Strategy name as registered in the scheduler.

        Returns:
            JSON with ``status`` and confirmation message.
        """
        _scheduler: StrategyScheduler | None = app.config.get("SCHEDULER")
        if _scheduler is None:
            return jsonify({"status": "error", "message": "Scheduler not available"}), 503

        try:
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(_scheduler.stop_one(name))
            finally:
                loop.close()
            return jsonify({"status": "success", "data": {"message": f"Strategy '{name}' stopped"}}), 200
        except KeyError:
            return jsonify({"status": "error", "message": f"Strategy '{name}' not registered"}), 404
        except Exception:
            logger.exception("strategy_stop error for %s", name)
            return jsonify({"status": "error", "message": "Internal server error"}), 500

    # ------------------------------------------------------------------
    # Active signals (replaces stub)
    # ------------------------------------------------------------------

    @app.route("/api/v1/signals/active", methods=["GET"])
    def signals_active() -> tuple[Any, int]:
        """Return currently active trading signals from the signal pipeline.

        Returns:
            JSON with ``status`` and ``data.signals`` — a list of signal
            objects with ``symbol``, ``exchange``, ``signal_type``,
            ``confidence``, ``timestamp``, and ``indicators`` fields.
            Returns an empty list if the pipeline has not yet produced signals.
        """
        try:
            from packages.ai.src.pipeline import SignalPipeline  # noqa: PLC0415
            # Use a module-level singleton if already running, otherwise return empty
            pipeline: SignalPipeline | None = getattr(app, "_signal_pipeline", None)
            if pipeline is None:
                return jsonify({"status": "success", "data": {"signals": []}}), 200

            raw_signals = pipeline.latest_signals
            signals = [
                {
                    "symbol": info.get("symbol", key.split(":")[-1]),
                    "exchange": info.get("exchange", key.split(":")[0]),
                    "signal_type": info.get("signal", "NEUTRAL"),
                    "confidence": info.get("confidence", 0.0),
                    "timestamp": info.get("timestamp", ""),
                    "indicators": {k: v for k, v in info.items()
                                   if k not in ("symbol", "exchange", "signal", "confidence", "timestamp")},
                }
                for key, info in raw_signals.items()
            ]
            return jsonify({"status": "success", "data": {"signals": signals}}), 200
        except Exception:
            logger.exception("signals_active error")
            return jsonify({"status": "error", "message": "Internal server error"}), 500

    # ------------------------------------------------------------------
    # Sentiment
    # ------------------------------------------------------------------

    @app.route("/api/v1/sentiment/analyze", methods=["POST"])
    def sentiment_analyze() -> tuple[Any, int]:
        """Analyze sentiment for a text snippet or symbol.

        Request JSON:
            text (str, optional): Raw text to analyze (headline, news).
            symbol (str, optional): Symbol to look up recent sentiment for.
            At least one of ``text`` or ``symbol`` must be provided.

        Returns:
            JSON with ``status`` and ``data`` containing ``score`` (-1 to 1),
            ``label`` (``"bullish"``, ``"bearish"``, or ``"neutral"``), and
            ``confidence`` (0 to 1).
        """
        if not _is_llm_configured():
            return jsonify({
                "status": "error",
                "message": "LLM not configured. Sentiment analysis requires an LLM provider.",
            }), 200

        body = request.get_json(silent=True) or {}
        text: str = body.get("text", "").strip()
        symbol: str = body.get("symbol", "").strip()

        if not text and not symbol:
            return jsonify({"status": "error", "message": "text or symbol is required"}), 400

        analyze_text = text or f"{symbol} stock market performance"

        try:
            from packages.ai.src.sentiment import (  # noqa: PLC0415
                NewsArticle,
                score_article_rule_based,
                score_article_with_llm,
            )
            from packages.ai.src.llm_client import LLMClient  # noqa: PLC0415

            article = NewsArticle(title=analyze_text, summary="")
            try:
                llm_client = LLMClient()
                scored = score_article_with_llm(article, llm_client)
                llm_client.close()
            except Exception as llm_exc:
                logger.warning("LLM sentiment failed, using rule-based: %s", llm_exc)
                scored = score_article_rule_based(article)

            label_map = {"BULLISH": "bullish", "BEARISH": "bearish", "NEUTRAL": "neutral"}
            label = label_map.get(scored.sentiment.upper(), "neutral")

            # Convert sentiment to numeric score: bullish=+confidence, bearish=-confidence
            if label == "bullish":
                score = scored.confidence
            elif label == "bearish":
                score = -scored.confidence
            else:
                score = 0.0

            return jsonify({
                "status": "success",
                "data": {
                    "score": round(score, 4),
                    "label": label,
                    "confidence": round(scored.confidence, 4),
                    "reasoning": scored.reasoning,
                },
            }), 200
        except Exception:
            logger.exception("sentiment_analyze error")
            return jsonify({"status": "error", "message": "Internal server error"}), 500

    # ------------------------------------------------------------------
    # RAG
    # ------------------------------------------------------------------

    @app.route("/api/v1/rag/query", methods=["POST"])
    def rag_query() -> tuple[Any, int]:
        """Query the RAG knowledge base.

        Request JSON:
            query (str): Natural language query.
            top_k (int, optional): Number of results to return (default 5).

        Returns:
            JSON with ``status`` and ``data.results`` — a list of
            ``{content, source, score}`` objects.
        """
        body = request.get_json(silent=True) or {}
        query: str = body.get("query", "").strip()
        top_k: int = int(body.get("top_k", 5))

        if not query:
            return jsonify({"status": "error", "message": "query is required"}), 400

        try:
            from packages.ai.src.rag import RAGEngine  # noqa: PLC0415
            from packages.ai.src.llm_client import LLMClient  # noqa: PLC0415

            try:
                llm_client = LLMClient() if _is_llm_configured() else None
                rag = RAGEngine(llm_client=llm_client)
                response = rag.query(query, n_results=top_k)
                if llm_client:
                    llm_client.close()
            except ImportError:
                return jsonify({
                    "status": "error",
                    "message": "RAG not configured — chromadb not installed. pip install chromadb",
                }), 200

            if response.error:
                return jsonify({"status": "error", "message": response.error}), 200

            results = [
                {
                    "content": chunk.content,
                    "source": chunk.source,
                    "score": round(chunk.score, 4),
                }
                for chunk in response.chunks_used
            ]
            return jsonify({"status": "success", "data": {"results": results}}), 200
        except Exception:
            logger.exception("rag_query error")
            return jsonify({"status": "error", "message": "Internal server error"}), 500

    # ------------------------------------------------------------------
    # Cron jobs
    # ------------------------------------------------------------------

    @app.route("/api/v1/cron/jobs", methods=["GET"])
    def cron_jobs_list() -> tuple[Any, int]:
        """Return all registered cron jobs with their current status.

        Returns:
            JSON with ``status`` and ``data.jobs`` — a list of job objects
            with ``name``, ``description``, ``trigger_type``, ``status``,
            ``last_run``, ``run_count``, and ``error_count``.
        """
        _cron: CronManager | None = app.config.get("CRON")
        if _cron is None:
            return jsonify({"status": "success", "data": {"jobs": []}}), 200

        try:
            jobs = [
                {
                    "name": job.name,
                    "description": job.description,
                    "trigger_type": job.trigger_type,
                    "status": job.status,
                    "last_run": job.last_run,
                    "run_count": job.run_count,
                    "error_count": job.error_count,
                }
                for job in _cron._jobs.values()
            ]
            return jsonify({"status": "success", "data": {"jobs": jobs}}), 200
        except Exception:
            logger.exception("cron_jobs_list error")
            return jsonify({"status": "error", "message": "Internal server error"}), 500

    @app.route("/api/v1/cron/jobs/<name>/pause", methods=["POST"])
    def cron_job_pause(name: str) -> tuple[Any, int]:
        """Pause a cron job by name.

        Args:
            name: Job name as registered in CronManager.

        Returns:
            JSON with ``status`` and confirmation message.
        """
        _cron: CronManager | None = app.config.get("CRON")
        if _cron is None:
            return jsonify({"status": "error", "message": "CronManager not available"}), 503

        try:
            if name not in _cron._jobs:
                return jsonify({"status": "error", "message": f"Job '{name}' not found"}), 404
            _cron.pause(name)
            return jsonify({"status": "success", "data": {"message": f"Job '{name}' paused"}}), 200
        except Exception:
            logger.exception("cron_job_pause error for %s", name)
            return jsonify({"status": "error", "message": "Internal server error"}), 500

    @app.route("/api/v1/cron/jobs/<name>/resume", methods=["POST"])
    def cron_job_resume(name: str) -> tuple[Any, int]:
        """Resume a paused cron job by name.

        Args:
            name: Job name as registered in CronManager.

        Returns:
            JSON with ``status`` and confirmation message.
        """
        _cron: CronManager | None = app.config.get("CRON")
        if _cron is None:
            return jsonify({"status": "error", "message": "CronManager not available"}), 503

        try:
            if name not in _cron._jobs:
                return jsonify({"status": "error", "message": f"Job '{name}' not found"}), 404
            _cron.resume(name)
            return jsonify({"status": "success", "data": {"message": f"Job '{name}' resumed"}}), 200
        except Exception:
            logger.exception("cron_job_resume error for %s", name)
            return jsonify({"status": "error", "message": "Internal server error"}), 500

    # ------------------------------------------------------------------
    # Audit logs
    # ------------------------------------------------------------------

    @app.route("/api/v1/audit/logs", methods=["GET"])
    def audit_logs() -> tuple[Any, int]:
        """Read SEBI-compliant audit logs for a given date.

        Query parameters:
            date (str): Date in ``YYYY-MM-DD`` format (default: today).
            limit (int): Maximum entries to return (default 100, max 1000).
            offset (int): Skip this many entries before returning (default 0).

        Returns:
            JSON with ``status`` and ``data`` containing ``logs`` (list)
            and ``total`` (total entries before pagination).
        """
        _audit: AuditLogger | None = app.config.get("AUDIT")
        if _audit is None:
            return jsonify({"status": "error", "message": "AuditLogger not available"}), 503

        from datetime import datetime as _dt  # noqa: PLC0415
        from datetime import timedelta as _td, timezone as _tz  # noqa: PLC0415
        _IST = _tz(_td(hours=5, minutes=30))

        date_str: str = request.args.get("date", _dt.now(_IST).strftime("%Y-%m-%d"))
        limit: int = min(int(request.args.get("limit", 100)), 1000)
        offset: int = max(0, int(request.args.get("offset", 0)))

        try:
            all_logs = _audit.read_day(date_str)
            total = len(all_logs)
            page = all_logs[offset: offset + limit]
            return jsonify({
                "status": "success",
                "data": {"logs": page, "total": total, "date": date_str},
            }), 200
        except Exception:
            logger.exception("audit_logs error")
            return jsonify({"status": "error", "message": "Internal server error"}), 500

    # ------------------------------------------------------------------
    # Trade journal
    # ------------------------------------------------------------------

    @app.route("/api/v1/trades/journal", methods=["GET"])
    def trades_journal() -> tuple[Any, int]:
        """Query the trade journal from DuckDB storage.

        Query parameters:
            start_date (str): Filter trades from this date (``YYYY-MM-DD``).
            end_date (str): Filter trades up to this date (``YYYY-MM-DD``).
            strategy (str): Filter by strategy name.
            limit (int): Maximum rows to return (default 100, max 1000).

        Returns:
            JSON with ``status`` and ``data`` containing ``trades`` (list)
            and ``total`` (total rows before pagination).
        """
        try:
            from packages.data.src.storage import StorageManager  # noqa: PLC0415
            from datetime import datetime as _dt  # noqa: PLC0415
            from datetime import timedelta as _td, timezone as _tz  # noqa: PLC0415
            _IST = _tz(_td(hours=5, minutes=30))

            start_date: str = request.args.get("start_date", "")
            end_date: str = request.args.get("end_date", "")
            strategy_filter: str = request.args.get("strategy", "")
            limit: int = min(int(request.args.get("limit", 100)), 1000)

            storage = StorageManager()
            storage.initialize()

            # Use available query methods on StorageManager
            if strategy_filter and start_date and end_date:
                trades = storage.get_trades_by_strategy(strategy_filter, start_date, end_date)
            elif start_date:
                trades = storage.get_trades_by_date(start_date)
            else:
                today = _dt.now(_IST).strftime("%Y-%m-%d")
                trades = storage.get_trades_by_date(today)

            # Apply limit
            trades = trades[:limit]
            # Convert datetime objects to strings for JSON serialisation
            for t in trades:
                for k, v in t.items():
                    if isinstance(v, _dt):
                        t[k] = v.isoformat()
            storage.close()

            return jsonify({
                "status": "success",
                "data": {"trades": trades, "total": len(trades)},
            }), 200
        except ImportError:
            return jsonify({
                "status": "error",
                "message": "Trade storage not available (DuckDB not configured)",
            }), 200
        except Exception:
            logger.exception("trades_journal error")
            return jsonify({"status": "error", "message": "Internal server error"}), 500

    # ------------------------------------------------------------------
    # Safety config
    # ------------------------------------------------------------------

    @app.route("/api/v1/safety/config", methods=["GET"])
    def safety_config_get() -> tuple[Any, int]:
        """Return the current safety system configuration.

        Returns:
            JSON with ``status`` and ``data`` containing all 5-layer
            safety parameters and current kill-switch / pause state.
        """
        _safety: SafetySystem | None = app.config.get("SAFETY")
        if _safety is None:
            return jsonify({"status": "error", "message": "SafetySystem not available"}), 503

        try:
            data = {
                "l1_order": {
                    "price_deviation_pct": _safety.l1_order.price_deviation_pct,
                    "check_market_hours": _safety.l1_order.check_market_hours,
                    "qty_limits": _safety.l1_order.qty_limits,
                },
                "l2_position": {
                    "max_positions": _safety.l2_position.max_positions,
                    "max_margin_pct": _safety.l2_position.max_margin_pct,
                },
                "l3_portfolio": {
                    "max_net_delta": _safety.l3_portfolio.max_net_delta,
                    "max_net_vega": _safety.l3_portfolio.max_net_vega,
                },
                "l4_pnl": {
                    "pause_pct": _safety.l4_pnl.pause_pct,
                    "kill_pct": _safety.l4_pnl.kill_pct,
                    "is_paused": _safety.l4_pnl.is_paused,
                    "is_killed": _safety.l4_pnl.is_killed,
                },
                "l5_kill": {
                    "is_active": _safety.l5_kill.is_active,
                    "reason": _safety.l5_kill.reason,
                },
            }
            return jsonify({"status": "success", "data": data}), 200
        except Exception:
            logger.exception("safety_config_get error")
            return jsonify({"status": "error", "message": "Internal server error"}), 500

    @app.route("/api/v1/safety/config", methods=["POST"])
    def safety_config_update() -> tuple[Any, int]:
        """Update safety system parameters.

        Request JSON (all fields optional):
            price_deviation_pct (float): L1 price deviation tolerance.
            check_market_hours (bool): L1 market-hours enforcement flag.
            max_positions (int): L2 maximum simultaneous positions.
            max_margin_pct (float): L2 maximum margin utilisation %.
            max_net_delta (float): L3 maximum net options delta.
            max_net_vega (float): L3 maximum net options vega.
            pnl_pause_pct (float): L4 daily-loss % that triggers a pause.
            pnl_kill_pct (float): L4 daily-loss % that activates kill switch.

        Returns:
            JSON with ``status`` and confirmation.
        """
        _safety: SafetySystem | None = app.config.get("SAFETY")
        if _safety is None:
            return jsonify({"status": "error", "message": "SafetySystem not available"}), 503

        body = request.get_json(silent=True) or {}
        try:
            if "price_deviation_pct" in body:
                _safety.l1_order.price_deviation_pct = float(body["price_deviation_pct"])
            if "check_market_hours" in body:
                _safety.l1_order.check_market_hours = bool(body["check_market_hours"])
            if "max_positions" in body:
                _safety.l2_position.max_positions = int(body["max_positions"])
            if "max_margin_pct" in body:
                _safety.l2_position.max_margin_pct = float(body["max_margin_pct"])
            if "max_net_delta" in body:
                _safety.l3_portfolio.max_net_delta = float(body["max_net_delta"])
            if "max_net_vega" in body:
                _safety.l3_portfolio.max_net_vega = float(body["max_net_vega"])
            if "pnl_pause_pct" in body:
                _safety.l4_pnl.pause_pct = float(body["pnl_pause_pct"])
            if "pnl_kill_pct" in body:
                _safety.l4_pnl.kill_pct = float(body["pnl_kill_pct"])

            return jsonify({"status": "success", "data": {"message": "Safety config updated"}}), 200
        except (ValueError, TypeError) as exc:
            return jsonify({"status": "error", "message": f"Invalid value: {exc}"}), 400
        except Exception:
            logger.exception("safety_config_update error")
            return jsonify({"status": "error", "message": "Internal server error"}), 500

    # ------------------------------------------------------------------
    # Kill switch
    # ------------------------------------------------------------------

    @app.route("/api/v1/safety/kill-switch", methods=["POST"])
    def kill_switch_activate() -> tuple[Any, int]:
        """Activate the emergency kill switch to halt all trading.

        Request JSON:
            reason (str, optional): Human-readable reason for activation.

        Returns:
            JSON with ``status`` and confirmation.
        """
        _safety: SafetySystem | None = app.config.get("SAFETY")
        _client: OpenAlgoClient | None = app.config.get("CLIENT")
        _audit: AuditLogger | None = app.config.get("AUDIT")
        if _safety is None:
            return jsonify({"status": "error", "message": "SafetySystem not available"}), 503

        body = request.get_json(silent=True) or {}
        reason: str = body.get("reason", "Manual kill switch via API").strip()

        try:
            _safety.l5_kill.activate(reason, client=_client)
            if _audit:
                _audit.log_kill_switch(activated=True, reason=reason)
            return jsonify({
                "status": "success",
                "data": {"message": "Kill switch activated", "reason": reason},
            }), 200
        except Exception:
            logger.exception("kill_switch_activate error")
            return jsonify({"status": "error", "message": "Internal server error"}), 500

    @app.route("/api/v1/safety/kill-switch", methods=["DELETE"])
    def kill_switch_reset() -> tuple[Any, int]:
        """Reset the kill switch to allow trading to resume.

        Returns:
            JSON with ``status`` and confirmation.
        """
        _safety: SafetySystem | None = app.config.get("SAFETY")
        _audit: AuditLogger | None = app.config.get("AUDIT")
        if _safety is None:
            return jsonify({"status": "error", "message": "SafetySystem not available"}), 503

        try:
            _safety.l5_kill.reset()
            if _audit:
                _audit.log_kill_switch(activated=False, reason="Manual reset via API")
            return jsonify({
                "status": "success",
                "data": {"message": "Kill switch reset — trading may resume"},
            }), 200
        except Exception:
            logger.exception("kill_switch_reset error")
            return jsonify({"status": "error", "message": "Internal server error"}), 500

    # ------------------------------------------------------------------
    # Webhooks
    # ------------------------------------------------------------------

    @app.route("/api/v1/webhooks", methods=["GET"])
    def webhooks_list() -> tuple[Any, int]:
        """Return all registered webhook endpoints and their status.

        Returns:
            JSON with ``status`` and ``data.webhooks`` — a list of objects
            with ``path``, ``name``, and ``enabled`` fields.
        """
        try:
            from packages.integration.src.webhook_server import (  # noqa: PLC0415
                WebhookServer,
            )
            server: WebhookServer | None = getattr(app, "_webhook_server", None)
            if server is None:
                return jsonify({"status": "success", "data": {"webhooks": [], "info": "Webhook server not started"}}), 200

            webhooks = [
                {"path": ep.path, "name": ep.name, "enabled": ep.enabled}
                for ep in server._endpoints.values()
            ]
            return jsonify({"status": "success", "data": {"webhooks": webhooks}}), 200
        except Exception:
            logger.exception("webhooks_list error")
            return jsonify({"status": "error", "message": "Internal server error"}), 500

    @app.route("/api/v1/webhooks", methods=["POST"])
    def webhooks_create() -> tuple[Any, int]:
        """Register a new webhook endpoint.

        Request JSON:
            path (str): URL path for the webhook (e.g. ``"/webhook/custom/my_signal"``).
            name (str): Human-readable name.
            secret (str, optional): HMAC secret for request validation.

        Returns:
            JSON with ``status`` and the registered webhook details.
        """
        try:
            from packages.integration.src.webhook_server import (  # noqa: PLC0415
                WebhookServer,
            )
            server: WebhookServer | None = getattr(app, "_webhook_server", None)
            if server is None:
                return jsonify({
                    "status": "error",
                    "message": "Webhook server not started — initialize WebhookServer first",
                }), 503

            body = request.get_json(silent=True) or {}
            path: str = body.get("path", "").strip()
            name: str = body.get("name", "").strip()
            secret: str = body.get("secret", "").strip()

            if not path or not name:
                return jsonify({"status": "error", "message": "path and name are required"}), 400

            def _noop_handler(raw_body: bytes, headers: dict[str, str]) -> dict[str, Any]:
                return {"status": "received"}

            server.register(path, name, _noop_handler, secret=secret)
            return jsonify({
                "status": "success",
                "data": {"path": path, "name": name, "enabled": True},
            }), 201
        except Exception:
            logger.exception("webhooks_create error")
            return jsonify({"status": "error", "message": "Internal server error"}), 500

    @app.route("/api/v1/webhooks/<webhook_id>", methods=["DELETE"])
    def webhooks_delete(webhook_id: str) -> tuple[Any, int]:
        """Remove a registered webhook endpoint.

        Args:
            webhook_id: The URL-encoded path or name identifying the webhook.

        Returns:
            JSON with ``status`` and confirmation message.
        """
        try:
            from packages.integration.src.webhook_server import (  # noqa: PLC0415
                WebhookServer,
            )
            server: WebhookServer | None = getattr(app, "_webhook_server", None)
            if server is None:
                return jsonify({"status": "error", "message": "Webhook server not started"}), 503

            # webhook_id may be the path (URL-decoded) or name
            path_key = f"/{webhook_id}" if not webhook_id.startswith("/") else webhook_id
            if path_key in server._endpoints:
                del server._endpoints[path_key]
                return jsonify({"status": "success", "data": {"message": f"Webhook '{path_key}' removed"}}), 200

            # Try matching by name
            for ep_path, ep in list(server._endpoints.items()):
                if ep.name == webhook_id:
                    del server._endpoints[ep_path]
                    return jsonify({"status": "success", "data": {"message": f"Webhook '{ep.name}' removed"}}), 200

            return jsonify({"status": "error", "message": f"Webhook '{webhook_id}' not found"}), 404
        except Exception:
            logger.exception("webhooks_delete error")
            return jsonify({"status": "error", "message": "Internal server error"}), 500

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

    # ------------------------------------------------------------------
    # RAG initialization (optional — requires chromadb)
    # ------------------------------------------------------------------
    # TODO: Initialize RAGEngine on startup once chromadb is a hard dependency.
    #   from packages.ai.src.rag import RAGEngine
    #   rag = RAGEngine()
    #   if rag.document_count() == 0:
    #       rag.index_directory("docs/")

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
        master_password = os.environ.get("MASTER_PASSWORD", "")
        if not master_password:
            master_password = "flinttrade-dev-default"
            logger.warning(
                "MASTER_PASSWORD not set — using development default. Set it for production."
            )
        self.credential_store = CredentialStore(
            flinttrade_dir / "credentials.db", master_password
        )
        contracts_dir = flinttrade_dir / "contracts"
        contracts_dir.mkdir(exist_ok=True)
        self.contract_manager = ContractManager(contracts_dir)
        self.registry = BrokerRegistry()

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
