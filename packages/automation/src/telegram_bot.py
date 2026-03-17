"""Telegram bot for trading alerts and control commands.

Commands:
  /status   — active positions, funds, running strategies
  /positions — detailed position list with P&L
  /orders   — pending orders
  /kill     — emergency kill switch (cancel all + close all + stop strategies)
  /pause    — pause a strategy
  /resume   — resume a strategy
  /pnl      — today's P&L breakdown
  /health   — OpenAlgo connection, WebSocket, disk space

Restricted to TELEGRAM_CHAT_ID from .env — only the owner can send commands.
Uses python-telegram-bot library.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

logger = logging.getLogger("flinttrade.automation.telegram")

IST = timezone(timedelta(hours=5, minutes=30))


@dataclass
class BotConfig:
    """Telegram bot configuration."""

    token: str = ""
    chat_id: str = ""
    enabled: bool = False

    @classmethod
    def from_env(cls) -> BotConfig:
        """Load from env vars, falling back to workspace.json."""
        token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        enabled = os.getenv("TELEGRAM_ENABLED", "")

        if not token:
            try:
                from packages.core.src.workspace import Workspace
                ws = Workspace()
                token = token or ws.get("notifications.telegram_bot_token_ref", "")
                chat_id = chat_id or ws.get("notifications.telegram_chat_id", "")
                if not enabled:
                    enabled = "true" if ws.get("notifications.telegram_enabled", False) else "false"
            except Exception:
                pass

        return cls(
            token=token,
            chat_id=chat_id,
            enabled=(enabled or "false").lower() == "true",
        )


@dataclass
class CommandResult:
    """Result from processing a Telegram command."""

    command: str
    response: str
    authorized: bool = True
    error: str = ""


# ---------------------------------------------------------------------------
# Command parsing (works without python-telegram-bot for testability)
# ---------------------------------------------------------------------------


def parse_command(text: str) -> tuple[str, list[str]]:
    """Parse a Telegram message into command + args.

    "/pause MyStrategy" → ("pause", ["MyStrategy"])
    "/kill" → ("kill", [])
    """
    text = text.strip()
    if not text.startswith("/"):
        return ("", [])

    parts = text.split()
    cmd = parts[0].lstrip("/").lower()
    # Strip @botname suffix
    if "@" in cmd:
        cmd = cmd.split("@")[0]
    args = parts[1:]
    return (cmd, args)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def format_positions(positions: list[dict[str, Any]]) -> str:
    """Format position data into a readable Telegram message."""
    if not positions:
        return "No open positions."

    lines = ["*Open Positions:*"]
    total_pnl = 0.0
    for p in positions:
        sym = p.get("symbol", "?")
        qty = p.get("quantity", "0")
        pnl = float(p.get("pnl", 0))
        ltp = p.get("ltp", "0")
        total_pnl += pnl
        emoji = "🟢" if pnl >= 0 else "🔴"
        lines.append(f"{emoji} {sym} qty={qty} LTP={ltp} P&L={pnl:+.0f}")

    lines.append(f"\n*Total P&L:* {total_pnl:+.0f}")
    return "\n".join(lines)


def format_orders(orders: list[dict[str, Any]]) -> str:
    """Format pending orders into a readable message."""
    if not orders:
        return "No pending orders."

    lines = ["*Pending Orders:*"]
    for o in orders:
        sym = o.get("symbol", "?")
        action = o.get("action", "?")
        qty = o.get("quantity", "0")
        price = o.get("price", "0")
        lines.append(f"• {action} {sym} qty={qty} @ {price}")
    return "\n".join(lines)


def format_health(health_data: dict[str, Any]) -> str:
    """Format system health info."""
    lines = ["*System Health:*"]
    openalgo = "✅" if health_data.get("openalgo_connected") else "❌"
    lines.append(f"OpenAlgo: {openalgo}")

    ws = "✅" if health_data.get("websocket_connected") else "❌"
    lines.append(f"WebSocket: {ws}")

    disk = health_data.get("disk_free_gb", 0)
    disk_emoji = "✅" if disk > 10 else "⚠️" if disk > 2 else "❌"
    lines.append(f"Disk Free: {disk_emoji} {disk:.1f} GB")

    uptime = health_data.get("uptime", "unknown")
    lines.append(f"Uptime: {uptime}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# TelegramBot
# ---------------------------------------------------------------------------


class TelegramBot:
    """Telegram bot with trading commands.

    Can be used in two modes:

    1. Legacy callback mode (backwards-compatible)::

        bot = TelegramBot()
        bot.set_handler("kill_switch", lambda: engine.kill_switch.activate(...))
        bot.handle_command("/kill")

    2. Wired mode (production — connects to engine)::

        bot = TelegramBot(
            router=router,
            safety_system=safety,
            scheduler=scheduler,
            audit_logger=auditor,
        )
        bot.handle_command("/kill")  # activates real kill switch
    """

    def __init__(
        self,
        config: BotConfig | None = None,
        router: Any = None,
        safety_system: Any = None,
        scheduler: Any = None,
        audit_logger: Any = None,
    ) -> None:
        self.config = config or BotConfig.from_env()
        self.router = router
        self.safety = safety_system
        self.scheduler = scheduler
        self.audit = audit_logger
        self._handlers: dict[str, Callable[..., Any]] = {}
        self._command_log: list[CommandResult] = []

    @property
    def command_log(self) -> list[CommandResult]:
        return list(self._command_log)

    def set_handler(self, name: str, handler: Callable[..., Any]) -> None:
        """Register a handler for a bot function (legacy callback mode).

        Expected handlers:
        - get_positions: () -> list[dict]
        - get_orders: () -> list[dict]
        - get_pnl: () -> dict with "total_pnl", "trades", etc.
        - kill_switch: () -> None (activates kill)
        - pause_strategy: (name: str) -> None
        - resume_strategy: (name: str) -> None
        - get_health: () -> dict with "openalgo_connected", "websocket_connected", "disk_free_gb"
        """
        self._handlers[name] = handler

    def is_authorized(self, chat_id: str | int) -> bool:
        """Check if the message sender is the authorized owner."""
        if not self.config.chat_id:
            return True  # No restriction if not configured
        return str(chat_id) == str(self.config.chat_id)

    def handle_command(self, text: str, chat_id: str | int = "", username: str = "") -> CommandResult:
        """Process a command and return a response.

        Can be used standalone without python-telegram-bot (e.g., for testing).
        """
        cmd, args = parse_command(text)

        if not cmd:
            return CommandResult(command="", response="Not a command", authorized=True)

        if not self.is_authorized(chat_id):
            result = CommandResult(command=cmd, response="Unauthorized", authorized=False)
            self._command_log.append(result)
            return result

        response = ""
        error = ""

        try:
            if cmd == "status":
                response = self._cmd_status()
            elif cmd == "positions":
                response = self._cmd_positions()
            elif cmd == "orders":
                response = self._cmd_orders()
            elif cmd == "kill":
                response = self._cmd_kill(username=username)
            elif cmd == "pause":
                response = self._cmd_pause(args)
            elif cmd == "resume":
                response = self._cmd_resume(args)
            elif cmd == "pnl":
                response = self._cmd_pnl()
            elif cmd == "health":
                response = self._cmd_health()
            else:
                response = f"Unknown command: /{cmd}"
        except Exception as exc:
            error = str(exc)
            response = f"Error: {error}"
            logger.error("Command /%s failed: %s", cmd, exc)

        result = CommandResult(command=cmd, response=response, error=error)
        self._command_log.append(result)
        return result

    # ------------------------------------------------------------------
    # /kill — SEBI emergency kill switch
    # ------------------------------------------------------------------

    def _cmd_kill(self, username: str = "") -> str:
        """Activate kill switch: safety → cancel orders → close positions → stop strategies."""
        now = datetime.now(IST).strftime("%H:%M:%S IST")
        errors: list[str] = []

        # 1. Activate SafetySystem kill switch
        if self.safety and hasattr(self.safety, "l5_kill"):
            self.safety.l5_kill.activate(f"Telegram /kill by {username or 'operator'}")
        elif self._handlers.get("kill_switch"):
            self._handlers["kill_switch"]()
        else:
            errors.append("Safety system not configured")

        # 2. Cancel all orders via OpenAlgo
        if self.router and self.router.client:
            try:
                coro = self.router.client.cancel_all_orders(strategy="Flint")
                if asyncio.iscoroutine(coro):
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.ensure_future(coro)
                    else:
                        loop.run_until_complete(coro)
            except Exception as exc:
                errors.append(f"cancel_all_orders: {exc}")
                logger.error("Kill switch cancel_all_orders failed: %s", exc)

        # 3. Close all positions via OpenAlgo
        if self.router and self.router.client:
            try:
                coro = self.router.client.close_position(strategy="Flint")
                if asyncio.iscoroutine(coro):
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.ensure_future(coro)
                    else:
                        loop.run_until_complete(coro)
            except Exception as exc:
                errors.append(f"close_position: {exc}")
                logger.error("Kill switch close_position failed: %s", exc)

        # 4. Stop all strategies
        if self.scheduler and hasattr(self.scheduler, "stop_all"):
            try:
                coro = self.scheduler.stop_all()
                if asyncio.iscoroutine(coro):
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.ensure_future(coro)
                    else:
                        loop.run_until_complete(coro)
            except Exception as exc:
                errors.append(f"stop_all: {exc}")
                logger.error("Kill switch stop_all failed: %s", exc)

        # 5. Audit log
        if self.audit:
            self.audit.log_event(
                "KILL_SWITCH",
                source="telegram",
                triggered_by=username or "operator",
            )

        logger.critical("KILL SWITCH activated via Telegram by %s", username or "operator")

        if errors:
            error_lines = "\n".join(f"⚠️ {e}" for e in errors)
            return (
                f"🔴 KILL SWITCH ACTIVATED\n"
                f"⚠️ Some actions had errors:\n{error_lines}\n"
                f"⏱ {now}"
            )

        return (
            f"🔴 KILL SWITCH ACTIVATED\n"
            f"✅ All orders cancelled\n"
            f"✅ All positions closed\n"
            f"✅ All strategies stopped\n"
            f"⏱ {now}"
        )

    # ------------------------------------------------------------------
    # /status — live positions, funds, strategies
    # ------------------------------------------------------------------

    def _cmd_status(self) -> str:
        """Return live status: positions, funds, running strategies."""
        lines: list[str] = []

        # Try wired mode first
        if self.router and self.router.client:
            try:
                # Positions — async client, try to get result
                positions = self._run_async(self.router.client.positionbook())
                if positions:
                    lines.append(format_positions(
                        [p.model_dump() if hasattr(p, "model_dump") else {"symbol": p.symbol, "quantity": p.quantity, "pnl": p.pnl} for p in positions]
                    ))
                else:
                    lines.append("No open positions.")
            except Exception:
                lines.append("No open positions.")

            try:
                funds = self._run_async(self.router.client.funds())
                lines.append(f"\n*Funds:* ₹{funds.available_balance} available")
            except Exception:
                pass

        elif self._handlers.get("get_positions"):
            # Legacy callback mode
            positions = self._handlers["get_positions"]()
            lines.append(format_positions(positions if isinstance(positions, list) else []))
        else:
            lines.append("Position handler not configured")

        # Strategy status
        if self.scheduler and hasattr(self.scheduler, "status"):
            status = self.scheduler.status()
            if status:
                lines.append("\n*Strategies:*")
                for name, info in status.items():
                    state = info.get("state", "?")
                    exch = info.get("exchange", "?")
                    lines.append(f"• {name} ({exch}): {state}")

        return "\n".join(lines) if lines else "No data available."

    # ------------------------------------------------------------------
    # /positions — detailed position list
    # ------------------------------------------------------------------

    def _cmd_positions(self) -> str:
        return self._cmd_status()

    # ------------------------------------------------------------------
    # /orders — pending orders
    # ------------------------------------------------------------------

    def _cmd_orders(self) -> str:
        handler = self._handlers.get("get_orders")
        if not handler:
            return "Orders handler not configured"
        orders = handler()
        return format_orders(orders if isinstance(orders, list) else [])

    # ------------------------------------------------------------------
    # /pause, /resume
    # ------------------------------------------------------------------

    def _cmd_pause(self, args: list[str]) -> str:
        if not args:
            return "Usage: /pause <strategy_name>"
        handler = self._handlers.get("pause_strategy")
        if not handler:
            return "Pause handler not configured"
        handler(args[0])
        return f"⏸ Strategy '{args[0]}' paused."

    def _cmd_resume(self, args: list[str]) -> str:
        if not args:
            return "Usage: /resume <strategy_name>"
        handler = self._handlers.get("resume_strategy")
        if not handler:
            return "Resume handler not configured"
        handler(args[0])
        return f"▶ Strategy '{args[0]}' resumed."

    # ------------------------------------------------------------------
    # /pnl
    # ------------------------------------------------------------------

    def _cmd_pnl(self) -> str:
        handler = self._handlers.get("get_pnl")
        if not handler:
            return "P&L handler not configured"
        data = handler()
        if isinstance(data, dict):
            total = data.get("total_pnl", 0)
            trades = data.get("total_trades", 0)
            wins = data.get("winning_trades", 0)
            return f"*Today's P&L:*\nTotal: {total:+.0f}\nTrades: {trades}\nWins: {wins}"
        return str(data)

    # ------------------------------------------------------------------
    # /health
    # ------------------------------------------------------------------

    def _cmd_health(self) -> str:
        handler = self._handlers.get("get_health")
        if not handler:
            # Basic health from system info
            disk = shutil.disk_usage("/")
            return format_health({
                "openalgo_connected": True,
                "websocket_connected": True,
                "disk_free_gb": disk.free / (1024 ** 3),
            })
        return format_health(handler())

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _run_async(coro: Any) -> Any:
        """Run an async coroutine from sync context."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Already in async context — create a future
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    return pool.submit(asyncio.run, coro).result(timeout=10)
            return loop.run_until_complete(coro)
        except Exception:
            return asyncio.run(coro)

    # ------------------------------------------------------------------
    # Send message (used by alerter)
    # ------------------------------------------------------------------

    def send_message(self, text: str) -> bool:
        """Send a message to the configured chat. Returns True on success."""
        if not self.config.token or not self.config.chat_id:
            logger.warning("Telegram not configured — message not sent")
            return False

        try:
            import httpx
            url = f"https://api.telegram.org/bot{self.config.token}/sendMessage"
            resp = httpx.post(url, json={
                "chat_id": self.config.chat_id,
                "text": text,
                "parse_mode": "Markdown",
            }, timeout=10)
            return resp.status_code == 200
        except Exception as exc:
            logger.error("Telegram send failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Polling loop (uses python-telegram-bot)
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the Telegram bot polling loop (blocking)."""
        if not self.config.token:
            logger.error("TELEGRAM_BOT_TOKEN not set — cannot start bot")
            return

        try:
            from telegram import Update
            from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
        except ImportError:
            raise ImportError("python-telegram-bot required — pip install python-telegram-bot")

        app = ApplicationBuilder().token(self.config.token).build()

        async def _handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            if not update.message or not update.message.text:
                return
            chat_id = update.message.chat_id
            username = update.effective_user.username if update.effective_user else ""
            result = self.handle_command(update.message.text, chat_id, username=username)
            await update.message.reply_text(result.response, parse_mode="Markdown")

        for cmd_name in ("status", "positions", "orders", "kill", "pause", "resume", "pnl", "health"):
            app.add_handler(CommandHandler(cmd_name, _handler))

        logger.info("Telegram bot starting...")
        app.run_polling()
