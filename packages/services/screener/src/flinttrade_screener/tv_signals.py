"""TradingView technical analysis signals via tradingview-ta.

Fetches buy/sell/neutral recommendations and indicator values for any
symbol across NSE, BSE, and global exchanges — no API key required.

Uses the ``tradingview-ta`` package which reads TradingView's public
technical analysis data (oscillators, moving averages, summary).

Usage::

    signals = TVSignals()
    result = signals.get_analysis("RELIANCE", "NSE")
    print(result.summary)       # {"BUY": 15, "SELL": 2, "NEUTRAL": 9}
    print(result.recommendation) # "BUY"
    print(result.oscillators)   # {"RSI": 58.2, "MACD": 0.45, ...}
    print(result.moving_averages) # {"EMA10": 2850.5, "SMA20": 2830.1, ...}

    # Bulk analysis for watchlist
    results = signals.get_bulk_analysis([
        ("NIFTY", "NSE"),
        ("BANKNIFTY", "NSE"),
        ("RELIANCE", "NSE"),
    ])
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("flinttrade.screener.tv_signals")

# Exchange mapping: FlintTrade exchange codes → TradingView screener/exchange
_EXCHANGE_MAP: dict[str, tuple[str, str]] = {
    "NSE": ("india", "NSE"),
    "BSE": ("india", "BSE"),
    "NFO": ("india", "NSE"),       # F&O uses NSE exchange on TV
    "MCX": ("india", "MCX"),
    "NSE_INDEX": ("india", "NSE"),
    "BSE_INDEX": ("india", "BSE"),
}

# Standard intervals supported by tradingview-ta
INTERVALS: dict[str, Any] = {}

try:
    from tradingview_ta import Interval

    INTERVALS = {
        "1m": Interval.INTERVAL_1_MINUTE,
        "5m": Interval.INTERVAL_5_MINUTES,
        "15m": Interval.INTERVAL_15_MINUTES,
        "30m": Interval.INTERVAL_30_MINUTES,
        "1h": Interval.INTERVAL_1_HOUR,
        "2h": Interval.INTERVAL_2_HOURS,
        "4h": Interval.INTERVAL_4_HOURS,
        "1d": Interval.INTERVAL_1_DAY,
        "1w": Interval.INTERVAL_1_WEEK,
        "1M": Interval.INTERVAL_1_MONTH,
    }
except ImportError:
    logger.debug("tradingview-ta not installed — TVSignals unavailable")


@dataclass
class TVAnalysisResult:
    """Result from TradingView technical analysis."""

    symbol: str
    exchange: str
    interval: str
    recommendation: str = ""  # STRONG_BUY, BUY, NEUTRAL, SELL, STRONG_SELL
    summary: dict[str, int] = field(default_factory=dict)  # {BUY: n, SELL: n, NEUTRAL: n}
    oscillators: dict[str, float | None] = field(default_factory=dict)
    oscillators_recommendation: str = ""
    moving_averages: dict[str, float | None] = field(default_factory=dict)
    moving_averages_recommendation: str = ""
    indicators: dict[str, float | None] = field(default_factory=dict)
    error: str = ""


class TVSignals:
    """TradingView technical analysis signal fetcher.

    Wraps ``tradingview-ta`` to provide buy/sell/neutral signals and
    indicator values for any symbol. No API key required.
    """

    def get_analysis(
        self,
        symbol: str,
        exchange: str = "NSE",
        interval: str = "1d",
    ) -> TVAnalysisResult:
        """Get technical analysis for a single symbol.

        Args:
            symbol: Trading symbol (e.g. "RELIANCE", "NIFTY").
            exchange: FlintTrade exchange code (NSE, BSE, MCX, etc.).
            interval: Timeframe — 1m, 5m, 15m, 30m, 1h, 2h, 4h, 1d, 1w, 1M.

        Returns:
            TVAnalysisResult with recommendation, summary counts, and indicator values.
        """
        try:
            from tradingview_ta import TA_Handler  # noqa: PLC0415
        except ImportError:
            return TVAnalysisResult(
                symbol=symbol, exchange=exchange, interval=interval,
                error="tradingview-ta not installed. Run: pip install tradingview-ta",
            )

        tv_interval = INTERVALS.get(interval)
        if tv_interval is None:
            return TVAnalysisResult(
                symbol=symbol, exchange=exchange, interval=interval,
                error=f"Unknown interval: {interval}. Valid: {list(INTERVALS.keys())}",
            )

        screener, tv_exchange = _EXCHANGE_MAP.get(exchange, ("india", "NSE"))

        try:
            handler = TA_Handler(
                symbol=symbol,
                screener=screener,
                exchange=tv_exchange,
                interval=tv_interval,
            )
            analysis = handler.get_analysis()
        except Exception as exc:
            logger.warning("TVSignals error for %s:%s: %s", exchange, symbol, exc)
            return TVAnalysisResult(
                symbol=symbol, exchange=exchange, interval=interval,
                error=str(exc),
            )

        summary = analysis.summary or {}
        osc = analysis.oscillators or {}
        ma = analysis.moving_averages or {}

        return TVAnalysisResult(
            symbol=symbol,
            exchange=exchange,
            interval=interval,
            recommendation=summary.get("RECOMMENDATION", ""),
            summary={
                "BUY": summary.get("BUY", 0),
                "SELL": summary.get("SELL", 0),
                "NEUTRAL": summary.get("NEUTRAL", 0),
            },
            oscillators=osc.get("COMPUTE", {}),
            oscillators_recommendation=osc.get("RECOMMENDATION", ""),
            moving_averages=ma.get("COMPUTE", {}),
            moving_averages_recommendation=ma.get("RECOMMENDATION", ""),
            indicators=analysis.indicators or {},
        )

    def get_bulk_analysis(
        self,
        symbols: list[tuple[str, str]],
        interval: str = "1d",
    ) -> list[TVAnalysisResult]:
        """Get analysis for multiple symbols.

        Args:
            symbols: List of (symbol, exchange) tuples.
            interval: Timeframe for all symbols.

        Returns:
            List of TVAnalysisResult, one per symbol.
        """
        return [
            self.get_analysis(symbol, exchange, interval)
            for symbol, exchange in symbols
        ]

    def get_recommendation_summary(
        self,
        symbol: str,
        exchange: str = "NSE",
    ) -> dict[str, str]:
        """Get quick recommendation across multiple timeframes.

        Returns dict like:
        {"1h": "BUY", "4h": "STRONG_BUY", "1d": "BUY", "1w": "NEUTRAL"}
        """
        timeframes = ["1h", "4h", "1d", "1w"]
        result: dict[str, str] = {}
        for tf in timeframes:
            analysis = self.get_analysis(symbol, exchange, tf)
            result[tf] = analysis.recommendation if not analysis.error else "ERROR"
        return result
