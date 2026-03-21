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

import numpy as np  # noqa: E402
from flask import Flask, jsonify, request  # noqa: E402

from packages.core.src.config import Settings  # noqa: E402
from packages.core.src.openalgo_client import OpenAlgoClient  # noqa: E402
from packages.data.src.audit_logger import AuditLogger  # noqa: E402
from packages.engine.src.router import OrderRouter  # noqa: E402
from packages.engine.src.safety import SafetyConfig, SafetySystem  # noqa: E402
from packages.engine.src.scheduler import StrategyScheduler, TimeScheduler  # noqa: E402
from packages.automation.src.cron_manager import CronManager  # noqa: E402
from packages.automation.src.telegram_bot import TelegramBot  # noqa: E402
from packages.ai.src.llm_client import LLMClient, LLMConfig, LLMMessage  # noqa: E402

logger = logging.getLogger("flinttrade")


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


def create_flask_app() -> Flask:
    """Create the Flask app with FlintTrade API routes.

    Returns:
        Flask application with ``/api/v1/advisor`` and ``/api/v1/advisor/status``
        endpoints registered.
    """
    app = Flask(__name__)

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

        Request JSON:
            message (str): User's message text.
            context (str, optional): Additional context (e.g. current positions).

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
        user_message: str = body.get("message", "").strip()
        context: str = body.get("context", "").strip()

        if not user_message:
            return jsonify({
                "status": "error",
                "message": "message field is required.",
            }), 400

        # Build conversation messages
        messages: list[LLMMessage] = [
            LLMMessage(role="system", content=_SYSTEM_PROMPT),
        ]
        if context:
            messages.append(LLMMessage(
                role="system",
                content=f"Current trading context:\n{context}",
            ))
        messages.append(LLMMessage(role="user", content=user_message))

        try:
            client = LLMClient()
            response = client.chat(messages)
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
        except Exception as exc:
            logger.exception("Advisor endpoint error")
            return jsonify({
                "status": "error",
                "message": f"Internal error: {exc}",
            }), 500

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

        self._stop_event = asyncio.Event()

        logger.info("FlintTradeApp initialized — v%s", self.version)

    async def start(self) -> None:
        """Start all services and wait until stopped."""
        # Start FlintTrade API server (Flask, port 5001)
        flask_app = create_flask_app()
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
