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
from .trend import (
    adx,
    alma,
    alligator,
    dema,
    dmi,
    ema,
    frama,
    hull,
    ichimoku,
    kama,
    linreg,
    mcginley_dynamic,
    moving_average_envelopes,
    parabolic_sar,
    sma,
    supertrend,
    t3,
    tema,
    trima,
    vidya,
    vwap,
    wma,
)

# Momentum
from .momentum import (
    awesome_oscillator,
    bop,
    cci,
    cmo,
    crsi,
    dpo,
    elder_ray,
    fisher_transform,
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
from .volatility import (
    atr,
    bb_percent,
    bb_width,
    bollinger_bands,
    chandelier_exit,
    chaikin_volatility,
    donchian_channels,
    historical_volatility,
    keltner_channels,
    natr,
    starc_bands,
    ulcer_index,
    williams_vix_fix,
)

# Volume
from .volume import (
    ad,
    cmf,
    cumulative_delta,
    efi,
    emv,
    fi,
    klinger_volume_oscillator,
    mfi,
    nvi,
    obv,
    obv_smoothed,
    pvt,
    rvol,
    volume_profile,
    vroc,
    vwma,
)

# Oscillators
from .oscillators import (
    ac,
    cho,
    chop,
    coppock_curve,
    gator_oscillator,
    kst,
    stc,
    tsi,
    vortex,
)

# Statistics
from .statistics import (
    beta,
    correl,
    lrslope,
    median,
    median_bands,
    mode,
    tsf,
    var,
)

# Signals
from .signals import (
    crossover,
    crossunder,
    exrem,
    flip,
    pivothigh,
    pivotlow,
    valuewhen,
)

# Streaming
from .streaming import (
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
from .pipeline import IndicatorPipeline

# VWAP bands
from .vwap_bands import VWAPResult, calculate_vwap_bands

# Seasonality
from .seasonality import (
    MonthlyStats,
    WeekdayStats,
    build_seasonality_matrix,
    compute_day_of_month_seasonality,
    compute_monthly_seasonality,
    compute_weekday_seasonality,
)

__all__ = [
    # trend
    "adx",
    "alma",
    "alligator",
    "dema",
    "dmi",
    "ema",
    "frama",
    "hull",
    "ichimoku",
    "kama",
    "linreg",
    "mcginley_dynamic",
    "moving_average_envelopes",
    "parabolic_sar",
    "sma",
    "supertrend",
    "t3",
    "tema",
    "trima",
    "vidya",
    "vwap",
    "wma",
    # momentum
    "awesome_oscillator",
    "bop",
    "cci",
    "cmo",
    "crsi",
    "dpo",
    "elder_ray",
    "fisher_transform",
    "macd",
    "mom",
    "roc",
    "rsi",
    "squeeze_momentum",
    "stoch_rsi",
    "stochastic",
    "trix",
    "williams_r",
    # volatility
    "atr",
    "bb_percent",
    "bb_width",
    "bollinger_bands",
    "chandelier_exit",
    "chaikin_volatility",
    "donchian_channels",
    "historical_volatility",
    "keltner_channels",
    "natr",
    "starc_bands",
    "ulcer_index",
    "williams_vix_fix",
    # volume
    "ad",
    "cmf",
    "cumulative_delta",
    "efi",
    "emv",
    "fi",
    "klinger_volume_oscillator",
    "mfi",
    "nvi",
    "obv",
    "obv_smoothed",
    "pvt",
    "rvol",
    "volume_profile",
    "vroc",
    "vwma",
    # oscillators
    "ac",
    "cho",
    "chop",
    "coppock_curve",
    "gator_oscillator",
    "kst",
    "stc",
    "tsi",
    "vortex",
    # statistics
    "beta",
    "correl",
    "lrslope",
    "median",
    "median_bands",
    "mode",
    "tsf",
    "var",
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
    # vwap bands
    "VWAPResult",
    "calculate_vwap_bands",
    # seasonality
    "MonthlyStats",
    "WeekdayStats",
    "compute_monthly_seasonality",
    "compute_weekday_seasonality",
    "compute_day_of_month_seasonality",
    "build_seasonality_matrix",
]
