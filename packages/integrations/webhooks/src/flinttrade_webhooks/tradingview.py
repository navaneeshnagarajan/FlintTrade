"""TradingView webhook receiver.

Parses incoming TradingView alert payloads (both simple text and structured
JSON) and maps them to FlintTrade Order objects for routing through the engine.

Webhook URL format: /webhook/tradingview/{strategy_id}

Supported payload formats:

1. Structured JSON::

    {
        "action": "BUY",
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "quantity": "10",
        "price": "0",
        "pricetype": "MARKET",
        "product": "MIS",
        "strategy": "Flint"
    }

2. Simple text::

    "BUY NIFTY NFO 75"
    "SELL RELIANCE"
    "BUY BANKNIFTY NFO 30 LIMIT 51000"
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from flinttrade_core.models import Order

from .webhook_hmac import verify_hmac_sha256_signature

logger = logging.getLogger("flinttrade.integration.tradingview")

# Valid actions
_VALID_ACTIONS = {"BUY", "SELL"}
_VALID_EXCHANGES = {
    "NSE", "BSE", "NFO", "BFO", "CDS", "BCD", "MCX", "NCDEX", "NCO", "DELTA",
}
_VALID_PRICETYPES = {"MARKET", "LIMIT", "SL", "SL-M"}
_VALID_PRODUCTS = {"MIS", "CNC", "NRML"}


@dataclass
class TradingViewAlert:
    """Parsed TradingView alert."""

    action: str = ""
    symbol: str = ""
    exchange: str = "NSE"
    quantity: str = "1"
    price: str = "0"
    trigger_price: str = "0"
    pricetype: str = "MARKET"
    product: str = "MIS"
    strategy: str = "Flint"
    raw_payload: str = ""
    is_valid: bool = False
    error: str = ""


def parse_tradingview_payload(
    body: str | bytes,
    default_strategy: str = "Flint",
) -> TradingViewAlert:
    """Parse a TradingView webhook payload into a TradingViewAlert.

    Handles both JSON and simple text formats.
    """
    raw = body.decode("utf-8") if isinstance(body, bytes) else body
    raw = raw.strip()

    if not raw:
        return TradingViewAlert(raw_payload=raw, error="Empty payload")

    # Try JSON first
    if raw.startswith("{"):
        return _parse_json_alert(raw, default_strategy)

    # Fall back to simple text
    return _parse_text_alert(raw, default_strategy)


def _parse_json_alert(raw: str, default_strategy: str) -> TradingViewAlert:
    """Parse a JSON-structured TradingView alert."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return TradingViewAlert(raw_payload=raw, error=f"Invalid JSON: {exc}")

    if not isinstance(data, dict):
        return TradingViewAlert(raw_payload=raw, error="Payload must be a JSON object")

    action = str(data.get("action", "")).upper()
    if action not in _VALID_ACTIONS:
        return TradingViewAlert(
            raw_payload=raw,
            error=f"Invalid action: '{action}'. Must be BUY or SELL",
        )

    symbol = str(data.get("symbol", "")).upper()
    if not symbol:
        return TradingViewAlert(raw_payload=raw, error="Missing symbol")

    exchange = str(data.get("exchange", "NSE")).upper()
    pricetype = str(data.get("pricetype", "MARKET")).upper()
    product = str(data.get("product", "MIS")).upper()

    return TradingViewAlert(
        action=action,
        symbol=symbol,
        exchange=exchange,
        quantity=str(data.get("quantity", "1")),
        price=str(data.get("price", "0")),
        trigger_price=str(data.get("trigger_price", "0")),
        pricetype=pricetype if pricetype in _VALID_PRICETYPES else "MARKET",
        product=product if product in _VALID_PRODUCTS else "MIS",
        strategy=str(data.get("strategy", default_strategy)),
        raw_payload=raw,
        is_valid=True,
    )


def _parse_text_alert(raw: str, default_strategy: str) -> TradingViewAlert:
    """Parse a simple text TradingView alert.

    Format: "ACTION SYMBOL [EXCHANGE] [QUANTITY] [PRICETYPE] [PRICE]"
    Examples: "BUY NIFTY NFO 75", "SELL RELIANCE", "BUY BANKNIFTY NFO 30 LIMIT 51000"
    """
    parts = raw.upper().split()
    if len(parts) < 2:
        return TradingViewAlert(
            raw_payload=raw,
            error="Text alert needs at least: ACTION SYMBOL",
        )

    action = parts[0]
    if action not in _VALID_ACTIONS:
        return TradingViewAlert(
            raw_payload=raw,
            error=f"Invalid action: '{action}'. Must be BUY or SELL",
        )

    symbol = parts[1]
    exchange = "NSE"
    quantity = "1"
    pricetype = "MARKET"
    price = "0"

    idx = 2
    # Optional exchange
    if idx < len(parts) and parts[idx] in _VALID_EXCHANGES:
        exchange = parts[idx]
        idx += 1

    # Optional quantity (numeric)
    if idx < len(parts) and parts[idx].isdigit():
        quantity = parts[idx]
        idx += 1

    # Optional pricetype
    if idx < len(parts) and parts[idx] in _VALID_PRICETYPES:
        pricetype = parts[idx]
        idx += 1

    # Optional price (numeric with possible decimal)
    if idx < len(parts):
        try:
            float(parts[idx])
            price = parts[idx]
        except ValueError:
            pass

    return TradingViewAlert(
        action=action,
        symbol=symbol,
        exchange=exchange,
        quantity=quantity,
        price=price,
        pricetype=pricetype,
        strategy=default_strategy,
        raw_payload=raw,
        is_valid=True,
    )


def alert_to_order(alert: TradingViewAlert) -> Order | None:
    """Convert a valid TradingViewAlert into an Order model."""
    if not alert.is_valid:
        return None

    return Order(
        symbol=alert.symbol,
        action=alert.action,
        exchange=alert.exchange,
        pricetype=alert.pricetype,
        product=alert.product,
        quantity=alert.quantity,
        price=alert.price,
        trigger_price=alert.trigger_price,
        strategy=alert.strategy,
    )


def verify_webhook_signature(
    body: bytes,
    signature: str,
    secret: str,
    *,
    skip_verification: bool = False,
) -> bool:
    """Verify TradingView webhook signature (HMAC-SHA256).

    Empty secrets fail closed unless ``skip_verification=True`` is passed
    explicitly. This mirrors :class:`WebhookReceiver` so all webhook entry
    points share one HMAC policy.
    """
    return verify_hmac_sha256_signature(
        body,
        signature,
        secret,
        skip_verification=skip_verification,
    )


class TradingViewWebhook:
    """TradingView webhook handler.

    Usage::

        tv = TradingViewWebhook(default_strategy="MyStrat", secret="my_secret")
        alert = tv.handle(request_body, signature=sig_header)
        if alert.is_valid:
            order = tv.to_order(alert)
    """

    def __init__(
        self,
        default_strategy: str = "Flint",
        secret: str = "",
        skip_verification: bool = False,
    ) -> None:
        self.default_strategy = default_strategy
        self.secret = secret
        self.skip_verification = skip_verification

    def handle(
        self,
        body: str | bytes,
        signature: str = "",
    ) -> TradingViewAlert:
        """Parse and validate a TradingView webhook request."""
        raw_bytes = body.encode("utf-8") if isinstance(body, str) else body

        if not verify_webhook_signature(
            raw_bytes,
            signature,
            self.secret,
            skip_verification=self.skip_verification,
        ):
            return TradingViewAlert(
                raw_payload=raw_bytes.decode("utf-8", errors="replace"),
                error="Invalid webhook signature",
            )

        alert = parse_tradingview_payload(raw_bytes, self.default_strategy)
        if alert.is_valid:
            logger.info(
                "TradingView alert: %s %s %s qty=%s strategy=%s",
                alert.action, alert.symbol, alert.exchange,
                alert.quantity, alert.strategy,
            )
        else:
            logger.warning("Invalid TradingView alert: %s", alert.error)

        return alert

    @staticmethod
    def to_order(alert: TradingViewAlert) -> Order | None:
        """Convert alert to Order."""
        return alert_to_order(alert)
