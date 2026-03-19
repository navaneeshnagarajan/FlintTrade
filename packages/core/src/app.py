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
