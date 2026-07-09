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

Restricted to the configured chat id — only the owner can send commands.

Native Bot API: FlintTrade talks to ``api.telegram.org`` directly over HTTPS
(:class:`TelegramClient`) — no ``python-telegram-bot`` dependency. Inbound
commands are received by a background long-polling loop (:meth:`TelegramBot.
start_background`) so the kill switch and all commands are reachable while the
app runs; outbound alerts use the same client.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

logger = logging.getLogger("flinttrade.automation.telegram")

IST = timezone(timedelta(hours=5, minutes=30))

# The command menu Telegram shows in the client UI (setMyCommands).
_BOT_COMMANDS: list[dict[str, str]] = [
    {"command": "status", "description": "Positions, funds, running strategies"},
    {"command": "positions", "description": "Detailed open positions with P&L"},
    {"command": "orders", "description": "Pending orders"},
    {"command": "pnl", "description": "Today's P&L breakdown"},
    {"command": "health", "description": "Backend, WebSocket, and disk health"},
    {"command": "pause", "description": "Pause a strategy: /pause <name>"},
    {"command": "resume", "description": "Resume a strategy: /resume <name>"},
    {"command": "kill", "description": "EMERGENCY: cancel all, close all, stop strategies"},
]


class TelegramApiError(RuntimeError):
    """A Telegram Bot API call returned ``ok: false`` or transport failed."""


class TelegramClient:
    """Minimal native Telegram Bot API client (no python-telegram-bot).

    Wraps the handful of Bot API methods FlintTrade needs over plain HTTPS, so
    the bot has no heavyweight third-party runtime dependency.
    """

    def __init__(self, token: str, *, base_url: str = "https://api.telegram.org") -> None:
        self._base = f"{base_url}/bot{token}"

    def _call(self, method: str, params: dict[str, Any] | None = None, *, timeout: float = 35.0) -> Any:
        import httpx  # noqa: PLC0415 — keep httpx import lazy/local like send_message

        resp = httpx.post(f"{self._base}/{method}", json=params or {}, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise TelegramApiError(str(data.get("description", "unknown error")))
        return data.get("result")

    def get_updates(self, offset: int | None = None, *, timeout: int = 30) -> list[dict[str, Any]]:
        """Long-poll for new updates (messages only). Blocks up to ``timeout`` s."""
        params: dict[str, Any] = {"timeout": timeout, "allowed_updates": ["message"]}
        if offset is not None:
            params["offset"] = offset
        result = self._call("getUpdates", params, timeout=timeout + 10)
        return result if isinstance(result, list) else []

    def send_message(self, chat_id: str | int, text: str, *, parse_mode: str = "Markdown") -> Any:
        return self._call("sendMessage", {"chat_id": chat_id, "text": text, "parse_mode": parse_mode})

    def set_my_commands(self, commands: list[dict[str, str]]) -> Any:
        return self._call("setMyCommands", {"commands": commands})

    def delete_webhook(self) -> Any:
        """Remove any webhook — long-polling and webhooks are mutually exclusive."""
        return self._call("deleteWebhook", {"drop_pending_updates": False})


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
                from flinttrade_core.workspace import Workspace
                ws = Workspace()
                token = token or ws.get("notifications.telegram_bot_token_ref", "")
                chat_id = chat_id or ws.get("notifications.telegram_chat_id", "")
                if not enabled:
                    enabled = "true" if ws.get("notifications.telegram_enabled", False) else "false"
            except Exception as exc:
                logger.exception("suppressed: %s", exc)

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


def _row_from(obj: Any, *fields: str) -> dict[str, Any]:
    """Coerce a broker model (pydantic or plain object) to a flat dict.

    Prefers ``model_dump()``; else reads the named attributes — so the Telegram
    formatters stay decoupled from the client's concrete model classes.
    """
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if isinstance(obj, dict):
        return obj
    return {f: getattr(obj, f, None) for f in fields}


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
            client=client,
            safety_system=safety,
            scheduler=scheduler,
            audit_logger=auditor,
        )
        bot.handle_command("/kill")  # activates real kill switch
    """

    def __init__(
        self,
        config: BotConfig | None = None,
        client: Any = None,
        safety_system: Any = None,
        scheduler: Any = None,
        audit_logger: Any = None,
    ) -> None:
        self.config = config or BotConfig.from_env()
        self.client = client
        self.safety = safety_system
        self.scheduler = scheduler
        self.audit = audit_logger
        self._handlers: dict[str, Callable[..., Any]] = {}
        self._command_log: list[CommandResult] = []
        self._chat_id: str = self.config.chat_id
        # Native long-polling state (see run_polling / start_background / stop).
        self._running: bool = False
        self._poll_thread: threading.Thread | None = None
        self._poll_timeout: int = 30

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
            logger.warning("TELEGRAM_CHAT_ID not set — rejecting all commands for safety")
            return False
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

        # 2. Cancel all orders via OpenAlgo — run to completion so the
        #    confirmation reflects the actual outcome, not a fire-and-forget.
        orders_cancelled = False
        if self.client:
            try:
                coro = self.client.cancel_all_orders(strategy="Flint")
                if asyncio.iscoroutine(coro):
                    self._client_sync(coro)
                orders_cancelled = True
            except Exception as exc:
                errors.append(f"cancel_all_orders: {exc}")
                logger.error("Kill switch cancel_all_orders failed: %s", exc)

        # 3. Close all positions via OpenAlgo
        positions_closed = False
        if self.client:
            try:
                coro = self.client.close_position(strategy="Flint")
                if asyncio.iscoroutine(coro):
                    self._client_sync(coro)
                positions_closed = True
            except Exception as exc:
                errors.append(f"close_position: {exc}")
                logger.error("Kill switch close_position failed: %s", exc)

        # 4. Stop all strategies
        strategies_stopped = False
        if self.scheduler and hasattr(self.scheduler, "stop_all"):
            try:
                coro = self.scheduler.stop_all()
                if asyncio.iscoroutine(coro):
                    self._run_async(coro)
                strategies_stopped = True
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

        status_lines = [
            f"{'✅' if orders_cancelled else '❌'} "
            f"{'All orders cancelled' if orders_cancelled else 'Orders not cancelled'}",
            f"{'✅' if positions_closed else '❌'} "
            f"{'All positions closed' if positions_closed else 'Positions not closed'}",
            f"{'✅' if strategies_stopped else '❌'} "
            f"{'All strategies stopped' if strategies_stopped else 'Strategies not stopped'}",
        ]

        if errors:
            error_lines = "\n".join(f"⚠️ {e}" for e in errors)
            return (
                "🔴 KILL SWITCH ACTIVATED\n"
                + "\n".join(status_lines)
                + f"\n⚠️ Some actions had errors:\n{error_lines}\n"
                f"⏱ {now}"
            )

        return (
            "🔴 KILL SWITCH ACTIVATED\n"
            + "\n".join(status_lines)
            + f"\n⏱ {now}"
        )

    # ------------------------------------------------------------------
    # /status — live positions, funds, strategies
    # ------------------------------------------------------------------

    def _cmd_status(self) -> str:
        """Return live status: positions, funds, running strategies."""
        lines: list[str] = []

        # Try wired mode first
        if self.client:
            try:
                # Positions — async client, try to get result
                positions = self._client_sync(self.client.positionbook())
                if positions:
                    lines.append(format_positions(
                        [p.model_dump() if hasattr(p, "model_dump") else {"symbol": p.symbol, "quantity": p.quantity, "pnl": p.pnl} for p in positions]
                    ))
                else:
                    lines.append("No open positions.")
            except Exception:
                lines.append("No open positions.")

            try:
                funds = self._client_sync(self.client.funds())
                lines.append(f"\n*Funds:* ₹{funds.available_balance} available")
            except Exception as exc:
                logger.exception("suppressed: %s", exc)

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
        """Detailed open-position list with per-position P&L.

        Distinct from /status (which also shows funds + strategies): this is the
        focused position book. Previously it aliased /status, so /positions and
        /status returned the same blob.
        """
        if self.client:
            try:
                positions = self._client_sync(self.client.positionbook())
                return format_positions([_row_from(p, "symbol", "quantity", "pnl", "ltp") for p in (positions or [])])
            except Exception as exc:
                logger.error("Telegram /positions failed: %s", exc)
                return "Could not fetch positions."
        if self._handlers.get("get_positions"):
            positions = self._handlers["get_positions"]()
            return format_positions(positions if isinstance(positions, list) else [])
        return "Position handler not configured"

    # ------------------------------------------------------------------
    # /orders — pending orders
    # ------------------------------------------------------------------

    def _cmd_orders(self) -> str:
        """Pending orders — from the broker order book in wired mode."""
        if self.client:
            try:
                orders = self._client_sync(self.client.orderbook())
                return format_orders([_row_from(o, "symbol", "action", "quantity", "price") for o in (orders or [])])
            except Exception as exc:
                logger.error("Telegram /orders failed: %s", exc)
                return "Could not fetch orders."
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
        """Run an async coroutine from sync context (ad-hoc loop).

        Only for coroutines that own no loop-affine state. Broker-client calls
        MUST go through :meth:`_client_sync` — the OpenAlgo client pools httpx
        connections affine to one loop, which this closes between calls.
        """
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

    def _client_sync(self, coro: Any) -> Any:
        """Run a broker-client coroutine on the client's OWN persistent loop.

        :class:`~flinttrade_core.openalgo_client.OpenAlgoClient` pools httpx
        connections affine to a single event loop and exposes ``run_sync`` for
        exactly this. Driving it through :meth:`_run_async`'s ad-hoc
        ``asyncio.run`` loops closes the loop between calls, so the *second*
        broker call in a command (e.g. ``/kill``'s ``close_position`` after
        ``cancel_all_orders``, or ``/status``'s ``funds`` after ``positionbook``)
        would fail with "Event loop is closed" — a safety-critical false
        negative on the kill switch. Falls back to :meth:`_run_async` for a plain
        client without ``run_sync`` (e.g. test doubles).
        """
        client = self.client
        run_sync = getattr(client, "run_sync", None)
        if callable(run_sync):
            return run_sync(coro)
        return self._run_async(coro)

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
    # Proactive alert dispatcher
    # ------------------------------------------------------------------

    async def send_alert(self, message: str, severity: str = "INFO") -> None:
        """Send a proactive alert to the configured chat ID.

        Args:
            message: Alert body text (plain string; Markdown is handled here).
            severity: One of ``"P0"`` (critical), ``"P1"`` (warning),
                ``"P2"`` (info), or any string (defaults to megaphone prefix).
                ``"INFO"`` maps to the megaphone prefix for backwards
                compatibility.
        """
        prefix = {"P0": "\U0001f6a8", "P1": "\u26a0\ufe0f", "P2": "\u2139\ufe0f"}.get(severity, "\U0001f4e2")
        text = f"{prefix} *FlintTrade Alert*\n{message}"
        # Native send (no python-telegram-bot). send_message guards the token /
        # chat id and swallows transport errors, returning False on failure \u2014 so
        # a P0 kill-switch alert is at least logged rather than silently lost.
        if not self.send_message(text):
            logger.warning("Telegram alert not delivered: %s", message)

    async def alert_broker_disconnect(self, broker_name: str = "broker") -> None:
        """Send a P1 alert when a broker connection is lost.

        Args:
            broker_name: Human-readable broker label for the alert body.
        """
        await self.send_alert(
            f"Broker disconnected: {broker_name}. Reconnecting...",
            "P1",
        )

    async def alert_position_mismatch(self, details: str) -> None:
        """Send a P1 alert when position reconciliation detects a mismatch.

        Args:
            details: Human-readable description of the discrepancy.
        """
        await self.send_alert(
            f"Position reconciliation mismatch:\n{details}",
            "P1",
        )

    async def alert_kill_switch(self, reason: str) -> None:
        """Send a P0 critical alert when the kill switch is activated.

        Args:
            reason: Free-text reason explaining why the kill switch fired.
        """
        await self.send_alert(f"KILL SWITCH ACTIVATED: {reason}", "P0")

    async def alert_error_rate(self, rate: float, window: str) -> None:
        """Send a P2 informational alert about elevated error rates.

        Args:
            rate: Error rate as a fraction (e.g. ``0.15`` for 15 %).
            window: Human-readable time window (e.g. ``"5 min"``).
        """
        await self.send_alert(f"Error rate {rate:.1%} over {window}", "P2")

    # ------------------------------------------------------------------
    # Native long-polling loop (no python-telegram-bot)
    # ------------------------------------------------------------------

    def start_background(self) -> bool:
        """Start the long-polling loop in a daemon thread.

        No-op (returns ``False``) unless the bot is enabled AND has both a token
        and an authorised chat id — an unconfigured or open bot must never poll.
        Idempotent: a second call while already running returns ``True``.
        """
        if not (self.config.enabled and self.config.token and self.config.chat_id):
            logger.info("Telegram bot not started (disabled or unconfigured)")
            return False
        if self._poll_thread is not None and self._poll_thread.is_alive():
            return True
        self._running = True
        self._poll_thread = threading.Thread(
            target=self.run_polling, name="telegram-poll", daemon=True
        )
        self._poll_thread.start()
        logger.info("Telegram bot polling started (kill switch reachable)")
        return True

    def stop(self) -> None:
        """Signal the polling loop to exit after its current long-poll returns."""
        self._running = False

    def run_polling(self, client: TelegramClient | None = None) -> None:
        """Long-poll ``getUpdates`` and dispatch commands until :meth:`stop`.

        Blocking — :meth:`start_background` runs this in a thread. Every update is
        authorised inside :meth:`handle_command`; an unauthorised chat triggers
        no action AND gets no reply (so the bot is not a spammable reflector).
        Pending updates queued while the app was down are drained on startup, so
        a stale ``/kill`` from hours ago never replays. Transient API/network
        errors back off and retry rather than killing the loop.

        Never log the raw exception here: httpx errors embed the request URL,
        which contains the bot token — log only the exception type.
        """
        if not self.config.token:
            logger.error("Telegram token not set — cannot start polling")
            return
        client = client or TelegramClient(self.config.token)
        # A webhook would starve getUpdates; register the command menu best-effort.
        for setup, label in ((client.delete_webhook, "delete_webhook"),
                             (lambda: client.set_my_commands(_BOT_COMMANDS), "set_my_commands")):
            try:
                setup()
            except Exception as exc:  # noqa: BLE001 — best-effort; never leak the token in the message
                logger.warning("Telegram %s failed: %s", label, type(exc).__name__)

        # Drain updates queued while the app was down so only commands sent AFTER
        # the bot comes online are acted on (no stale /kill or /pause replay).
        offset: int | None = None
        try:
            pending = client.get_updates(offset=None, timeout=0)
            if pending:
                offset = int(pending[-1].get("update_id", 0)) + 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("Telegram initial drain failed: %s", type(exc).__name__)

        while self._running:
            try:
                updates = client.get_updates(offset=offset, timeout=self._poll_timeout)
            except Exception as exc:  # noqa: BLE001 — a transient failure must not kill the loop
                logger.warning("Telegram getUpdates failed: %s", type(exc).__name__)
                time.sleep(3)
                continue
            for update in updates:
                offset = int(update.get("update_id", 0)) + 1
                message = update.get("message") or {}
                text = message.get("text")
                if not isinstance(text, str) or not text:
                    continue
                chat_id = (message.get("chat") or {}).get("id", "")
                username = (message.get("from") or {}).get("username", "")
                result = self.handle_command(text, chat_id, username=username)
                if not result.authorized:
                    continue  # never reply to an unauthorised chat (no reflector)
                self._reply(client, chat_id, result.response)
        logger.info("Telegram polling loop stopped")

    @staticmethod
    def _reply(client: TelegramClient, chat_id: str | int, text: str) -> None:
        """Send a reply, falling back to plain text if Markdown fails to parse.

        An unbalanced ``_`` / ``*`` / ``[`` (e.g. a strategy named ``iron_condor``)
        makes Telegram reject Markdown; retry without formatting so the operator
        still gets the message rather than silence.
        """
        try:
            client.send_message(chat_id, text)
        except Exception as exc:  # noqa: BLE001
            try:
                client.send_message(chat_id, text, parse_mode="")
            except Exception:  # noqa: BLE001 — a send failure must not kill the loop
                logger.warning("Telegram reply failed: %s", type(exc).__name__)
