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

# Trend
from packages.indicators.src.trend import (
    adx,
    dema,
    dmi,
    ema,
    hull,
    ichimoku,
    kama,
    linreg,
    parabolic_sar,
    sma,
    supertrend,
    tema,
    vwap,
    wma,
)

# Momentum
from packages.indicators.src.momentum import (
    awesome_oscillator,
    bop,
    cci,
    cmo,
    dpo,
    macd,
    mom,
    roc,
    rsi,
    squeeze_momentum,
    stoch_rsi,
    stochastic,
    trix,
    williams_r,
)

# Volatility
from packages.indicators.src.volatility import (
    atr,
    bollinger_bands,
    chaikin_volatility,
    donchian_channels,
    historical_volatility,
    keltner_channels,
    natr,
    williams_vix_fix,
)

# Volume
from packages.indicators.src.volume import (
    ad,
    cmf,
    cumulative_delta,
    efi,
    mfi,
    obv,
    pvt,
    volume_profile,
    vwma,
)

# Signals
from packages.indicators.src.signals import (
    crossover,
    crossunder,
    exrem,
    flip,
    pivothigh,
    pivotlow,
    valuewhen,
)

# Streaming
from packages.indicators.src.streaming import (
    StreamingATR,
    StreamingBollingerBands,
    StreamingCumulativeDelta,
    StreamingEMA,
    StreamingMACD,
    StreamingRSI,
    StreamingSMA,
    StreamingSupertrend,
    StreamingVWAP,
)

# Pipeline
from packages.indicators.src.pipeline import IndicatorPipeline

__all__ = [
    # trend
    "ema",
    "sma",
    "dema",
    "tema",
    "wma",
    "hull",
    "ichimoku",
    "parabolic_sar",
    "supertrend",
    "vwap",
    "kama",
    "adx",
    "dmi",
    "linreg",
    # momentum
    "rsi",
    "macd",
    "stochastic",
    "williams_r",
    "cci",
    "roc",
    "cmo",
    "trix",
    "stoch_rsi",
    "bop",
    "mom",
    "awesome_oscillator",
    "squeeze_momentum",
    "dpo",
    # volatility
    "atr",
    "bollinger_bands",
    "keltner_channels",
    "donchian_channels",
    "natr",
    "historical_volatility",
    "williams_vix_fix",
    "chaikin_volatility",
    # volume
    "obv",
    "ad",
    "cmf",
    "mfi",
    "vwma",
    "efi",
    "pvt",
    "cumulative_delta",
    "volume_profile",
    # signals
    "crossover",
    "crossunder",
    "exrem",
    "flip",
    "pivothigh",
    "pivotlow",
    "valuewhen",
    # streaming
    "StreamingEMA",
    "StreamingSMA",
    "StreamingRSI",
    "StreamingATR",
    "StreamingMACD",
    "StreamingBollingerBands",
    "StreamingSupertrend",
    "StreamingVWAP",
    "StreamingCumulativeDelta",
    # pipeline
    "IndicatorPipeline",
]
