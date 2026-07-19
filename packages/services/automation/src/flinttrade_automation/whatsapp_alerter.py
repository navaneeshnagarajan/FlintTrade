"""WhatsApp alert delivery via wabridge sidecar.

Connects to a local wabridge HTTP sidecar (https://github.com/navaneeshnagarajan/wabridge)
to send WhatsApp messages to individuals, self, and groups.

Also provides :class:`AlertRouter` which routes alerts to Telegram AND/OR
WhatsApp based on workspace.json ``notifications`` configuration.

Usage::

    alerter = WhatsAppAlerter(bridge_url="http://localhost:3000")
    alerter.send_text("919876543210", "NIFTY broke 24000!")
    alerter.send_to_self("Strategy straddle triggered — check terminal")
    alerter.send_to_group("120363012345@g.us", "Alert: max pain shift detected")

    router = AlertRouter()
    router.route_alert("signal", "RELIANCE BUY signal", {"confidence": 0.9})
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

from .rate_window import SlidingWindowRateLimit

logger = logging.getLogger("flinttrade.automation.whatsapp_alerter")

# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

_MAX_MESSAGES_PER_MINUTE = 30
_RATE_WINDOW_SECONDS = 60.0


# ---------------------------------------------------------------------------
# WhatsAppAlerter
# ---------------------------------------------------------------------------


class WhatsAppAlerter:
    """Send WhatsApp messages via a wabridge sidecar.

    The sidecar is a lightweight HTTP bridge that exposes a REST API for
    sending messages without requiring a direct WhatsApp Business API account.

    Configuration:
        bridge_url: Full URL of the wabridge sidecar, e.g.
            ``http://localhost:3000``.  Read from ``WABRIDGE_URL`` env var
            or ``notifications.wabridge_url`` in workspace.json when not
            supplied explicitly.

    Args:
        bridge_url: Base URL of the wabridge HTTP sidecar.  Pass ``""`` to
            auto-detect from environment / workspace.json.
    """

    def __init__(self, bridge_url: str = "") -> None:
        self.bridge_url = bridge_url or self._resolve_bridge_url()
        self._rate_limit = SlidingWindowRateLimit(
            max_events=_MAX_MESSAGES_PER_MINUTE, window_seconds=_RATE_WINDOW_SECONDS
        )

    # ------------------------------------------------------------------
    # Config helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_bridge_url() -> str:
        """Resolve bridge URL from env or workspace.json.

        Returns:
            Configured bridge URL, or empty string if not set.
        """
        url = os.getenv("WABRIDGE_URL", "")
        if url:
            return url
        try:
            from flinttrade_core.workspace import Workspace  # noqa: PLC0415

            ws = Workspace()
            return ws.get("notifications.wabridge_url", "")
        except Exception:
            return ""

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------

    def _check_rate_limit(self) -> bool:
        """Return ``True`` if sending is within the 30/min rate limit.

        Uses a sliding-window over the last 60 seconds.

        Returns:
            ``True`` if the send is allowed, ``False`` if the limit is exceeded.
        """
        return self._rate_limit.allow()

    def _record_send(self) -> None:
        """Record a sent message timestamp for rate limiting."""
        self._rate_limit.record()

    # ------------------------------------------------------------------
    # Internal HTTP helper
    # ------------------------------------------------------------------

    def _post(self, path: str, payload: dict[str, Any]) -> bool:
        """POST JSON payload to the wabridge sidecar.

        Args:
            path: Endpoint path, e.g. ``/send`` or ``/send/self``.
            payload: JSON body to send.

        Returns:
            ``True`` on HTTP 200, ``False`` on any error.
        """
        if not self.bridge_url:
            logger.warning("WhatsApp bridge URL not configured — message not sent")
            return False

        if not self._check_rate_limit():
            logger.warning(
                "WhatsApp rate limit exceeded (max %d/min) — message dropped",
                _MAX_MESSAGES_PER_MINUTE,
            )
            return False

        try:
            import httpx  # optional dep

            url = self.bridge_url.rstrip("/") + path
            resp = httpx.post(url, json=payload, timeout=10)
            if resp.status_code == 200:
                self._record_send()
                logger.debug("WhatsApp message sent via %s", path)
                return True
            logger.error("wabridge returned HTTP %d for %s", resp.status_code, path)
            return False
        except Exception as exc:
            logger.error("WhatsApp send failed (%s): %s", path, exc)
            return False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def send_text(self, phone: str, message: str) -> bool:
        """Send a text message to a phone number.

        Args:
            phone: Recipient phone number in international format, e.g.
                ``"919876543210"`` (country code + number, no ``+`` or spaces).
            message: Plain-text message body.

        Returns:
            ``True`` if the message was delivered to the sidecar successfully.
        """
        return self._post("/send", {"phone": phone, "message": message})

    def send_to_self(self, message: str) -> bool:
        """Send a quick self-notification to the linked WhatsApp number.

        Useful for instant personal alerts (e.g. strategy triggered, kill
        switch activated, end-of-day P&L summary).

        Args:
            message: Plain-text message body.

        Returns:
            ``True`` if the message was delivered to the sidecar successfully.
        """
        return self._post("/send/self", {"message": message})

    def send_to_group(self, group_id: str, message: str) -> bool:
        """Send a text message to a WhatsApp group.

        Args:
            group_id: Group JID, e.g. ``"120363012345@g.us"``.  Use the
                wabridge ``/groups`` endpoint to list available group IDs.
            message: Plain-text message body.

        Returns:
            ``True`` if the message was delivered to the sidecar successfully.
        """
        return self._post("/send/group", {"groupId": group_id, "message": message})

    @property
    def is_configured(self) -> bool:
        """Return ``True`` when the bridge URL is set.

        Returns:
            Whether a non-empty bridge URL is configured.
        """
        return bool(self.bridge_url)


# ---------------------------------------------------------------------------
# AlertRouter
# ---------------------------------------------------------------------------

# Alert type → which channels it should always reach by default.
_DEFAULT_CHANNEL_MAP: dict[str, list[str]] = {
    "signal": ["telegram", "whatsapp"],
    "order": ["telegram", "whatsapp"],
    "kill_switch": ["telegram", "whatsapp"],
    "pnl": ["telegram"],
    "health": ["telegram"],
    "info": ["telegram"],
}


@dataclass
class AlertRouterConfig:
    """Configuration for :class:`AlertRouter`.

    Attributes:
        telegram_enabled: Send alerts to Telegram.
        whatsapp_enabled: Send alerts to WhatsApp.
        whatsapp_self_phone: Phone number to use for WhatsApp self-alerts.
            If empty, ``send_to_self`` is used instead of ``send_text``.
        whatsapp_group_id: Default group JID for group-type alerts.
        alert_channels: Mapping of ``alert_type`` → list of enabled channels.
            Overrides the built-in defaults for specific alert types.
    """

    telegram_enabled: bool = True
    whatsapp_enabled: bool = False
    whatsapp_self_phone: str = ""
    whatsapp_group_id: str = ""
    alert_channels: dict[str, list[str]] = field(default_factory=dict)

    @classmethod
    def from_workspace(cls) -> AlertRouterConfig:
        """Load configuration from workspace.json ``notifications`` section.

        Returns:
            Populated :class:`AlertRouterConfig`, using safe defaults when
            workspace.json cannot be read.
        """
        try:
            from flinttrade_core.workspace import Workspace  # noqa: PLC0415

            ws = Workspace()
            tg_enabled = bool(ws.get("notifications.telegram_enabled", True))
            wa_enabled = bool(ws.get("notifications.whatsapp_enabled", False))
            wa_phone = str(ws.get("notifications.whatsapp_self_phone", ""))
            wa_group = str(ws.get("notifications.whatsapp_group_id", ""))
            channels: dict[str, list[str]] = ws.get("notifications.alert_channels", {})
        except Exception:
            tg_enabled = True
            wa_enabled = False
            wa_phone = ""
            wa_group = ""
            channels = {}

        return cls(
            telegram_enabled=tg_enabled,
            whatsapp_enabled=wa_enabled,
            whatsapp_self_phone=wa_phone,
            whatsapp_group_id=wa_group,
            alert_channels=channels,
        )


class AlertRouter:
    """Route trading alerts to Telegram and/or WhatsApp.

    Reads enabled channels from workspace.json ``notifications`` config and
    dispatches each alert to the correct sinks.  Both channels are optional
    — if neither is configured, alerts are logged and silently dropped.

    Args:
        telegram_bot: A :class:`~flinttrade_automation.telegram_bot.TelegramBot`
            instance.  Created lazily from env if not supplied.
        whatsapp_alerter: A :class:`WhatsAppAlerter` instance.  Created
            lazily from env if not supplied.
        config: Pre-built :class:`AlertRouterConfig`.  Loaded from
            workspace.json if not supplied.
    """

    def __init__(
        self,
        telegram_bot: Any = None,
        whatsapp_alerter: WhatsAppAlerter | None = None,
        config: AlertRouterConfig | None = None,
    ) -> None:
        self._telegram = telegram_bot
        self._whatsapp = whatsapp_alerter
        self.config = config or AlertRouterConfig.from_workspace()

    # ------------------------------------------------------------------
    # Lazy accessors
    # ------------------------------------------------------------------

    def _get_telegram(self) -> Any:
        """Return the Telegram bot, creating one lazily if not injected.

        Returns:
            A :class:`~flinttrade_automation.telegram_bot.TelegramBot`
            instance, or ``None`` if Telegram is disabled.
        """
        if not self.config.telegram_enabled:
            return None
        if self._telegram is None:
            try:
                from .telegram_bot import TelegramBot  # noqa: PLC0415

                self._telegram = TelegramBot()
            except Exception as exc:
                logger.warning("Could not create TelegramBot: %s", exc)
        return self._telegram

    def _get_whatsapp(self) -> WhatsAppAlerter | None:
        """Return the WhatsApp alerter, creating one lazily if not injected.

        Returns:
            A :class:`WhatsAppAlerter` instance, or ``None`` if WhatsApp is
            disabled.
        """
        if not self.config.whatsapp_enabled:
            return None
        if self._whatsapp is None:
            self._whatsapp = WhatsAppAlerter()
        return self._whatsapp

    # ------------------------------------------------------------------
    # Channel resolution
    # ------------------------------------------------------------------

    def _channels_for(self, alert_type: str) -> list[str]:
        """Return the list of enabled channels for a given alert type.

        Merges the workspace ``alert_channels`` override with the built-in
        defaults.  A channel is only included when its global enable flag
        is also ``True``.

        Args:
            alert_type: Alert category, e.g. ``"signal"``, ``"order"``,
                ``"kill_switch"``, ``"pnl"``.

        Returns:
            List of channel names to deliver this alert to.
        """
        overrides = self.config.alert_channels
        raw = overrides.get(alert_type, _DEFAULT_CHANNEL_MAP.get(alert_type, ["telegram"]))
        channels: list[str] = []
        if "telegram" in raw and self.config.telegram_enabled:
            channels.append("telegram")
        if "whatsapp" in raw and self.config.whatsapp_enabled:
            channels.append("whatsapp")
        return channels

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def route_alert(self, alert_type: str, message: str, context: dict[str, Any]) -> None:
        """Dispatch an alert to all configured channels.

        Checks workspace.json config to decide which channels are enabled for
        this ``alert_type``, then sends the message to each.  Failures on
        individual channels are logged but do not raise exceptions so that
        other channels are always attempted.

        Args:
            alert_type: Category of the alert — used to look up which
                channels should receive it.  Built-in types: ``"signal"``,
                ``"order"``, ``"kill_switch"``, ``"pnl"``, ``"health"``,
                ``"info"``.
            message: Human-readable alert text.
            context: Additional key/value pairs for structured logging or
                future enrichment (e.g. symbol, strategy name, confidence).
        """
        channels = self._channels_for(alert_type)

        if not channels:
            logger.info(
                "Alert [%s] has no enabled channels — dropping: %s", alert_type, message
            )
            return

        logger.debug(
            "Routing alert type=%s channels=%s context_keys=%s",
            alert_type,
            channels,
            list(context.keys()),
        )

        if "telegram" in channels:
            try:
                bot = self._get_telegram()
                if bot is not None:
                    formatted = f"[{alert_type.upper()}] {message}"
                    bot.send_message(formatted)
                    logger.debug("Alert sent to Telegram: %s", formatted[:80])
            except Exception as exc:
                logger.error("Telegram delivery failed for alert [%s]: %s", alert_type, exc)

        if "whatsapp" in channels:
            try:
                wa = self._get_whatsapp()
                if wa is not None and wa.is_configured:
                    formatted = f"[{alert_type.upper()}] {message}"
                    if self.config.whatsapp_self_phone:
                        wa.send_text(self.config.whatsapp_self_phone, formatted)
                    else:
                        wa.send_to_self(formatted)
                    logger.debug("Alert sent to WhatsApp: %s", formatted[:80])
            except Exception as exc:
                logger.error("WhatsApp delivery failed for alert [%s]: %s", alert_type, exc)
