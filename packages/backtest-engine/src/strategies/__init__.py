"""Backtest strategy sub-package.

This package shadows the parent ``strategies.py`` module when Python resolves
``import strategies`` with ``src/`` on sys.path. To keep backward compatibility,
we re-export everything from that module here so that existing test imports like
``from strategies import EMACrossover`` continue to work.

Sub-modules (38 additional strategies across 6 categories):

    Trend (7):
        trend_ema_crossover    — TrendEMACrossover (EMA crossover + confirmation)
        trend_sma_crossover    — SMACrossover
        trend_macd_signal      — MACDSignal
        trend_supertrend       — DoubleSupertrend
        trend_parabolic_sar    — ParabolicSAR
        trend_ichimoku         — IchimokuCloud
        trend_hull_ma          — HullMA

    Momentum (7):
        momentum_rsi           — RSIMomentum, RSIDivergence
        momentum_stochastic    — StochasticCrossover
        momentum_cci           — CCIStrategy
        momentum_williams_r    — WilliamsR
        momentum_roc           — ROCMomentum
        momentum_laguerre_rsi  — LaguerreRSI
        momentum_elder_impulse — ElderImpulse

    Mean Reversion (7):
        mean_reversion_vwap        — VWAPReversion
        mean_reversion_rsi         — RSIMeanRevert
        mean_reversion_keltner     — KeltnerChannelReversion
        mean_reversion_ma_envelope — MAEnvelope
        mean_reversion_zscore      — ZScoreMeanReversion
        mean_reversion_pivot_point — PivotPointReversion
        [BollingerMeanReversion already in strategies.py]

    Volatility (7):
        volatility_atr_breakout      — ATRBreakout
        volatility_bollinger_squeeze — BollingerSqueeze
        volatility_donchian_breakout — DonchianBreakout
        volatility_vix_based         — VIXRegime
        volatility_range_expansion   — RangeExpansion
        volatility_vcp               — VCPBreakout
        volatility_india_vix         — IndiaVIXRegime

    Volume (4):
        volume_obv_divergence — OBVDivergence
        volume_vwap_cross     — VWAPCross
        volume_breakout       — VolumeBreakout
        volume_vwma           — VWMACrossover

    Pattern (2):
        pattern_engulfing — EngulfingPattern
        pattern_hammer    — HammerShootingStar

    Trend + (1 new):
        trend_triple_ma   — TripleMA

    Options (3):
        options_straddle_strangle — ATMStraddleSell, OTMStrangleSell
        options_iron_condor       — IronCondorStrategy
        options_wheel             — WheelStrategy
"""

from __future__ import annotations

# Re-export the entire public API of the parent strategies.py module.
# The parent file is not a package so we must import it by loading the .py
# file directly via importlib to avoid a circular reference.
import importlib.util
import os as _os

_parent_strategies_path = _os.path.join(_os.path.dirname(__file__), "..", "strategies.py")
_parent_strategies_path = _os.path.normpath(_parent_strategies_path)

_spec = importlib.util.spec_from_file_location("_backtest_strategies_parent", _parent_strategies_path)
if _spec is not None and _spec.loader is not None:
    _parent = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_parent)  # type: ignore[union-attr]

    # Re-export all public names
    from typing import Any as _Any

    def _re_export(name: str) -> _Any:
        return getattr(_parent, name)

    # Indicator helpers
    ema = _re_export("ema")
    sma = _re_export("sma")
    rsi = _re_export("rsi")
    bollinger_bands = _re_export("bollinger_bands")
    macd = _re_export("macd")
    supertrend = _re_export("supertrend")

    # Strategy classes from parent strategies.py
    _BacktestStrategyMixin = _re_export("_BacktestStrategyMixin")
    EMACrossover = _re_export("EMACrossover")
    SupertrendStrategy = _re_export("SupertrendStrategy")
    MACDRSIStrategy = _re_export("MACDRSIStrategy")
    BollingerMeanReversion = _re_export("BollingerMeanReversion")
    VWAPDeviation = _re_export("VWAPDeviation")
    StraddleSell = _re_export("StraddleSell")
    StrangleSell = _re_export("StrangleSell")
    IronCondor = _re_export("IronCondor")
    BullPutSpread = _re_export("BullPutSpread")
    BearCallSpread = _re_export("BearCallSpread")
    MomentumBreakout = _re_export("MomentumBreakout")
    OpeningRangeBreakout = _re_export("OpeningRangeBreakout")
    BUILTIN_STRATEGIES = _re_export("BUILTIN_STRATEGIES")

# ---------------------------------------------------------------------------
# New strategy sub-modules — imported lazily to keep startup fast.
# All are available via:
#   from packages.backtest_engine.src.strategies.<module> import <Class>
# or via the ALL_STRATEGIES registry below.
# ---------------------------------------------------------------------------

# Trend
from .trend_ema_crossover import TrendEMACrossover  # noqa: E402
from .trend_hull_ma import HullMA  # noqa: E402
from .trend_ichimoku import IchimokuCloud  # noqa: E402
from .trend_macd_signal import MACDSignal  # noqa: E402
from .trend_parabolic_sar import ParabolicSAR  # noqa: E402
from .trend_sma_crossover import SMACrossover  # noqa: E402
from .trend_supertrend import DoubleSupertrend  # noqa: E402

# Momentum
from .momentum_cci import CCIStrategy  # noqa: E402
from .momentum_roc import ROCMomentum  # noqa: E402
from .momentum_rsi import RSIDivergence, RSIMomentum  # noqa: E402
from .momentum_stochastic import StochasticCrossover  # noqa: E402
from .momentum_williams_r import WilliamsR  # noqa: E402

# Mean Reversion
from .mean_reversion_keltner import KeltnerChannelReversion  # noqa: E402
from .mean_reversion_ma_envelope import MAEnvelope  # noqa: E402
from .mean_reversion_rsi import RSIMeanRevert  # noqa: E402
from .mean_reversion_vwap import VWAPReversion  # noqa: E402

# Volatility
from .volatility_atr_breakout import ATRBreakout  # noqa: E402
from .volatility_bollinger_squeeze import BollingerSqueeze  # noqa: E402
from .volatility_donchian_breakout import DonchianBreakout  # noqa: E402
from .volatility_range_expansion import RangeExpansion  # noqa: E402
from .volatility_vix_based import VIXRegime  # noqa: E402

# Volume
from .volume_breakout import VolumeBreakout  # noqa: E402
from .volume_obv_divergence import OBVDivergence  # noqa: E402
from .volume_vwap_cross import VWAPCross  # noqa: E402

# Options
from .options_iron_condor import IronCondorStrategy  # noqa: E402
from .options_short_straddle_indian import IndianShortStraddle  # noqa: E402
from .options_straddle_strangle import ATMStraddleSell, OTMStrangleSell  # noqa: E402
from .options_wheel import WheelStrategy  # noqa: E402

# Momentum (new)
from .momentum_laguerre_rsi import LaguerreRSI  # noqa: E402
from .momentum_elder_impulse import ElderImpulse  # noqa: E402

# Mean Reversion (new)
from .mean_reversion_zscore import ZScoreMeanReversion  # noqa: E402
from .mean_reversion_pivot_point import PivotPointReversion  # noqa: E402

# Volatility (new)
from .volatility_vcp import VCPBreakout  # noqa: E402
from .volatility_india_vix import IndiaVIXRegime  # noqa: E402

# Volume (new)
from .volume_vwma import VWMACrossover  # noqa: E402

# Pattern (new)
from .pattern_engulfing import EngulfingPattern  # noqa: E402
from .pattern_hammer import HammerShootingStar  # noqa: E402

# Trend (new)
from .trend_triple_ma import TripleMA  # noqa: E402

# ---------------------------------------------------------------------------
# Unified strategy registry — all 28 new classes + 12 legacy
# ---------------------------------------------------------------------------
from packages.engine.src.strategy import BaseStrategy as _BaseStrategy  # noqa: E402

ALL_STRATEGIES: dict[str, type[_BaseStrategy]] = {
    # Legacy (12 from strategies.py)
    "EMACrossover": EMACrossover,
    "Supertrend": SupertrendStrategy,
    "MACD_RSI": MACDRSIStrategy,
    "BollingerMR": BollingerMeanReversion,
    "VWAPDev": VWAPDeviation,
    "StraddleSell": StraddleSell,
    "StrangleSell": StrangleSell,
    "IronCondor": IronCondor,
    "BullPutSpread": BullPutSpread,
    "BearCallSpread": BearCallSpread,
    "MomentumBreakout": MomentumBreakout,
    "ORB": OpeningRangeBreakout,
    # Trend (7 new)
    "TrendEMACrossover": TrendEMACrossover,
    "SMACrossover": SMACrossover,
    "MACDSignal": MACDSignal,
    "DoubleSupertrend": DoubleSupertrend,
    "ParabolicSAR": ParabolicSAR,
    "IchimokuCloud": IchimokuCloud,
    "HullMA": HullMA,
    # Momentum (6 new)
    "RSIMomentum": RSIMomentum,
    "RSIDivergence": RSIDivergence,
    "StochasticCrossover": StochasticCrossover,
    "CCI": CCIStrategy,
    "WilliamsR": WilliamsR,
    "ROCMomentum": ROCMomentum,
    # Mean Reversion (4 new; BollingerMR already in legacy)
    "VWAPReversion": VWAPReversion,
    "RSIMeanRevert": RSIMeanRevert,
    "KeltnerReversion": KeltnerChannelReversion,
    "MAEnvelope": MAEnvelope,
    # Volatility (5 new)
    "ATRBreakout": ATRBreakout,
    "BollingerSqueeze": BollingerSqueeze,
    "DonchianBreakout": DonchianBreakout,
    "VIXRegime": VIXRegime,
    "RangeExpansion": RangeExpansion,
    # Volume (3 new)
    "OBVDivergence": OBVDivergence,
    "VWAPCross": VWAPCross,
    "VolumeBreakout": VolumeBreakout,
    # Options (4 new)
    "ATMStraddleSell": ATMStraddleSell,
    "OTMStrangleSell": OTMStrangleSell,
    "IronCondorStrategy": IronCondorStrategy,
    "WheelStrategy": WheelStrategy,
    "IndianShortStraddle": IndianShortStraddle,
    # User's personal strategy (in ema_supertrend_dema.py)
    # Momentum — absorbed batch (2 new)
    "LaguerreRSI": LaguerreRSI,
    "ElderImpulse": ElderImpulse,
    # Mean Reversion — absorbed batch (2 new)
    "ZScoreMeanReversion": ZScoreMeanReversion,
    "PivotPointReversion": PivotPointReversion,
    # Volatility — absorbed batch (2 new)
    "VCPBreakout": VCPBreakout,
    "IndiaVIXRegime": IndiaVIXRegime,
    # Volume — absorbed batch (1 new)
    "VWMACrossover": VWMACrossover,
    # Pattern — absorbed batch (2 new)
    "EngulfingPattern": EngulfingPattern,
    "HammerShootingStar": HammerShootingStar,
    # Trend — absorbed batch (1 new)
    "TripleMA": TripleMA,
}

