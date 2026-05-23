"""ChartInk scanner webhook receiver.

ChartInk sends scan results as a list of triggered symbols. This module parses
them, maps to OpenAlgo symbol format, and generates batch orders.

Webhook URL format: /webhook/chartink/{strategy_id}

ChartInk payload format (typical)::

    {
        "scan_name": "OI Spurt Bullish",
        "scan_url": "https://chartink.com/screener/...",
        "alert_list": "RELIANCE,TCS,INFY,HDFCBANK",
        "triggered_at": "2026-03-16 10:30:00",
        "stocks": "RELIANCE,TCS,INFY,HDFCBANK"
    }

Also supports the simpler comma-separated format: "RELIANCE,TCS,INFY"
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from flinttrade_core.models import Order

logger = logging.getLogger("flinttrade.integration.chartink")


@dataclass
class ChartInkScanResult:
    """Parsed ChartInk scan result."""

    scan_name: str = ""
    symbols: list[str] = field(default_factory=list)
    triggered_at: str = ""
    raw_payload: str = ""
    is_valid: bool = False
    error: str = ""

    @property
    def symbol_count(self) -> int:
        return len(self.symbols)


@dataclass
class ChartInkConfig:
    """Configuration for ChartInk webhook handling."""

    action: str = "BUY"            # Default action for triggered symbols
    exit_action: str = "SELL"      # Action when symbols exit the scan
    exchange: str = "NSE"
    product: str = "MIS"
    pricetype: str = "MARKET"
    quantity_per_symbol: str = "1"
    strategy: str = "Flint"
    max_symbols: int = 10          # Max symbols to act on per scan


# Common ChartInk symbol suffixes to strip
_CHARTINK_SUFFIXES = ["-EQ", "-BE", "-SM", "-ST", "-BZ"]


def normalize_chartink_symbol(raw_symbol: str) -> str:
    """Normalise a ChartInk symbol to OpenAlgo format.

    ChartInk may add suffixes like -EQ, -BE. OpenAlgo uses plain symbols.
    """
    symbol = raw_symbol.strip().upper()
    for suffix in _CHARTINK_SUFFIXES:
        if symbol.endswith(suffix):
            symbol = symbol[: -len(suffix)]
            break
    # Remove any NSE: or BSE: prefix
    if ":" in symbol:
        symbol = symbol.split(":")[-1]
    return symbol


def parse_chartink_payload(body: str | bytes) -> ChartInkScanResult:
    """Parse a ChartInk webhook payload."""
    raw = body.decode("utf-8") if isinstance(body, bytes) else body
    raw = raw.strip()

    if not raw:
        return ChartInkScanResult(raw_payload=raw, error="Empty payload")

    # Try JSON
    if raw.startswith("{"):
        return _parse_json_payload(raw)

    # Try comma-separated symbols
    return _parse_csv_payload(raw)


def _parse_json_payload(raw: str) -> ChartInkScanResult:
    """Parse JSON payload from ChartInk."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return ChartInkScanResult(raw_payload=raw, error=f"Invalid JSON: {exc}")

    if not isinstance(data, dict):
        return ChartInkScanResult(raw_payload=raw, error="Payload must be a JSON object")

    # Extract symbols from various fields ChartInk may use
    symbols_raw = (
        data.get("stocks", "")
        or data.get("alert_list", "")
        or data.get("symbols", "")
    )

    if isinstance(symbols_raw, list):
        symbols = [normalize_chartink_symbol(s) for s in symbols_raw if s]
    elif isinstance(symbols_raw, str):
        symbols = [
            normalize_chartink_symbol(s)
            for s in symbols_raw.split(",")
            if s.strip()
        ]
    else:
        symbols = []

    if not symbols:
        return ChartInkScanResult(raw_payload=raw, error="No symbols found in payload")

    return ChartInkScanResult(
        scan_name=str(data.get("scan_name", "")),
        symbols=symbols,
        triggered_at=str(data.get("triggered_at", "")),
        raw_payload=raw,
        is_valid=True,
    )


def _parse_csv_payload(raw: str) -> ChartInkScanResult:
    """Parse comma-separated symbol list."""
    symbols = [
        normalize_chartink_symbol(s) for s in raw.split(",") if s.strip()
    ]
    if not symbols:
        return ChartInkScanResult(raw_payload=raw, error="No symbols found")

    return ChartInkScanResult(
        symbols=symbols,
        raw_payload=raw,
        is_valid=True,
    )


def scan_result_to_orders(
    result: ChartInkScanResult,
    config: ChartInkConfig | None = None,
) -> list[Order]:
    """Convert a ChartInk scan result into a list of Orders."""
    if not result.is_valid:
        return []

    cfg = config or ChartInkConfig()
    symbols = result.symbols[: cfg.max_symbols]

    orders: list[Order] = []
    for sym in symbols:
        orders.append(Order(
            symbol=sym,
            action=cfg.action,
            exchange=cfg.exchange,
            pricetype=cfg.pricetype,
            product=cfg.product,
            quantity=cfg.quantity_per_symbol,
            strategy=cfg.strategy,
        ))

    return orders


class ChartInkWebhook:
    """ChartInk webhook handler.

    Usage::

        ci = ChartInkWebhook(config=ChartInkConfig(action="BUY", quantity_per_symbol="10"))
        result = ci.handle(request_body)
        if result.is_valid:
            orders = ci.to_orders(result)
    """

    def __init__(self, config: ChartInkConfig | None = None) -> None:
        self.config = config or ChartInkConfig()

    def handle(self, body: str | bytes) -> ChartInkScanResult:
        """Parse a ChartInk webhook payload."""
        result = parse_chartink_payload(body)
        if result.is_valid:
            logger.info(
                "ChartInk scan '%s': %d symbols — %s",
                result.scan_name, result.symbol_count,
                ", ".join(result.symbols[:5]),
            )
        else:
            logger.warning("Invalid ChartInk payload: %s", result.error)
        return result

    def to_orders(self, result: ChartInkScanResult) -> list[Order]:
        """Convert scan result to orders using this handler's config."""
        return scan_result_to_orders(result, self.config)
