"""FlintTrade indicators — technical analysis library.

Uses TA-Lib when available (C speed), falls back to pure Python/NumPy.
Designed for both batch processing and streaming calculations.

All functions:
- Accept numpy arrays as input
- Return numpy arrays as output
- Use NaN for insufficient data (no forward-fill)
- Are fully type-annotated
"""

from __future__ import annotations

from packages.indicators.src.momentum import macd, rsi, stochastic, williams_r
from packages.indicators.src.trend import dema, ema, sma, supertrend, vwap
from packages.indicators.src.volatility import atr, bollinger_bands, keltner_channels

__all__ = [
    # trend
    "ema",
    "sma",
    "dema",
    "supertrend",
    "vwap",
    # momentum
    "rsi",
    "macd",
    "stochastic",
    "williams_r",
    # volatility
    "atr",
    "bollinger_bands",
    "keltner_channels",
]
