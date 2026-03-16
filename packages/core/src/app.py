"""FlintTrade application entry point — wires all packages together.

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
from pathlib import Path
from typing import Any

# Ensure repo root is on sys.path for cross-package imports
_REPO_ROOT = str(Path(__file__).resolve().parents[3])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from packages.core.src.config import Settings
from packages.core.src.openalgo_client import OpenAlgoClient
from packages.data.src.audit_logger import AuditLogger
from packages.engine.src.router import OrderRouter
from packages.engine.src.safety import SafetyConfig, SafetySystem
from packages.engine.src.scheduler import StrategyScheduler, TimeScheduler
from packages.automation.src.cron_manager import CronManager
from packages.automation.src.telegram_bot import TelegramBot
from packages.automation.src.totp_login import TOTPLogin

logger = logging.getLogger("flinttrade")


def _read_version() -> str:
    """Read version from VERSION file at repo root."""
    version_file = Path(_REPO_ROOT) / "VERSION"
    if version_file.exists():
        return version_file.read_text().strip()
    return "0.0.0-dev"


class FlintTradeApp:
    """Main application — creates and wires all FlintTrade subsystems.

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

        # Core — settings + API client
        self.settings = Settings.from_env()
        self.client = OpenAlgoClient(self.settings)

        # Data — audit logger
        self.audit = AuditLogger()

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

        # Automation — TOTP login + cron + Telegram
        self.totp = TOTPLogin(
            openalgo_host=self.settings.openalgo_host,
        )
        self.cron = CronManager(
            openalgo_client=self.client,
            audit_logger=self.audit,
            totp_login=self.totp,
        )
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
        # Log startup to audit
        self.audit.log_event(
            "APP_START",
            version=self.version,
            host=self.settings.openalgo_host,
        )

        # Load market holidays
        self.cron.load_holidays()

        # Register built-in cron jobs
        self.cron.register_builtin_jobs()

        logger.info(
            "FlintTrade v%s started — OpenAlgo: %s",
            self.version, self.settings.openalgo_host,
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

        # Close API client
        await self.client.close()

        # Close audit logger
        self.audit.close()

        # Log shutdown
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
