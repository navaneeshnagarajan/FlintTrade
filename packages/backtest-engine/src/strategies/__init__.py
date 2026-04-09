"""Backtest strategy sub-package.

This package shadows the parent ``strategies.py`` module when Python resolves
``import strategies`` with ``src/`` on sys.path. To keep backward compatibility,
we re-export everything from that module here so that existing test imports like
``from strategies import EMACrossover`` continue to work.

Sub-modules (~100 strategies + 29 BaseBacktestStrategy classes — 12 legacy + 88 BaseStrategy + 29 new):

Sub-modules (43 NEW strategies added in this batch):

    Multi-Timeframe (5):
        mtf_rsi_trend              — MTFRSITrend
        mtf_ema_breakout           — MTFEMABreakout
        mtf_vwap_scalp             — MTFVWAPScalp
        mtf_supertrend_confluence  — MTFSupertrendConfluence
        mtf_macd_momentum          — MTFMACDMomentum

    Pairs/Statistical (4):
        pairs_ratio_reversion  — PairsRatioReversion
        pairs_cointegration    — PairsCointegration
        stat_regime_hmm        — StatRegimeHMM
        stat_kalman_filter     — StatKalmanFilter

    Intraday India-specific (6):
        intraday_orb_atr        — IntradayORBATR
        intraday_gap_fill       — IntradayGapFill
        intraday_first_candle   — IntradayFirstCandle
        intraday_vwap_bounce    — IntradayVWAPBounce
        intraday_expiry_day     — IntradayExpiryDay
        intraday_pre_market     — IntradayPreMarket

    Options Advanced (5):
        options_jade_lizard     — OptionsJadeLizard
        options_ratio_spread    — OptionsRatioSpread
        options_calendar_spread — OptionsCalendarSpread
        options_butterfly       — OptionsButterfly, OptionsIronButterfly
        options_collar          — OptionsCollar

    Event-Driven (4):
        event_earnings    — EventEarnings
        event_rbi_policy  — EventRBIPolicy
        event_expiry_oi   — EventExpiryOI
        event_fii_flow    — EventFIIFlow

    Crypto (4):
        crypto_funding_arb     — CryptoFundingArb
        crypto_grid            — CryptoGrid
        crypto_dca_momentum    — CryptoDCAMomentum
        crypto_breakout_volume — CryptoBreakoutVolume

    Commodity (3):
        commodity_seasonal  — CommoditySeasonal
        commodity_spread    — CommoditySpread
        commodity_inventory — CommodityInventory

    Machine Learning (4):
        ml_feature_signal      — MLFeatureSignal
        ml_regime_classifier   — MLRegimeClassifier
        ml_ensemble_voter      — MLEnsembleVoter
        ml_adaptive_params     — MLAdaptiveParams

    Portfolio/Risk (4):
        portfolio_equal_weight        — PortfolioEqualWeight
        portfolio_risk_parity         — PortfolioRiskParity
        portfolio_momentum_rotation   — PortfolioMomentumRotation
        portfolio_min_variance        — PortfolioMinVariance

    Scalping (4):
        scalp_tape_reading      — ScalpTapeReading
        scalp_level2_squeeze    — ScalpLevel2Squeeze
        scalp_tick_momentum     — ScalpTickMomentum
        scalp_spread_capture    — ScalpSpreadCapture

Sub-modules (38 original strategies across 6 categories):

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

    Pattern (7):
        pattern_engulfing        — EngulfingPattern
        pattern_hammer           — HammerShootingStar
        pattern_doji             — DojiReversal
        pattern_morning_star     — MorningStar
        pattern_evening_star     — EveningStar
        pattern_three_soldiers   — ThreeWhiteSoldiers

    Momentum + (1 new):
        momentum_macd_divergence — MACDDivergence

    Trend + (1 new):
        trend_triple_ma   — TripleMA

    Options (3):
        options_straddle_strangle — ATMStraddleSell, OTMStrangleSell
        options_iron_condor       — IronCondorStrategy
        options_wheel             — WheelStrategy

Sub-modules (AlgoTrading absorption batch — 29 BaseBacktestStrategy classes):

    Trend-Following (9 — trend_following.py):
        SupertrendStrategy, EMACrossoverStrategy, MACDStrategy,
        ADXStrategy, ADXDIStrategy, ParabolicSARStrategy,
        DonchianBreakoutStrategy, KeltnerBreakoutStrategy, HeikinAshiStrategy

    Mean Reversion (6 — mean_reversion.py):
        RSIStrategy, BollingerBandStrategy, StochasticStrategy,
        CCIStrategy, WilliamsRStrategy, KeltnerChannelStrategy

    Momentum (6 — momentum.py):
        MomentumStrategy, DualMomentumStrategy, VolumeBreakoutStrategy,
        VWAPStrategy, OBVStrategy, VWMAStrategy

    Volatility (4 — volatility.py):
        ATRBreakoutStrategy, ATRRangeStrategy,
        ChoppinessBreakoutStrategy, VolatilityContractionStrategy

    Composite (4 — composite.py):
        RSI_MACD_Strategy, SupertrendEMAStrategy,
        TripleScreenStrategy, IchimokuStrategy

    Registry: STRATEGY_REGISTRY (dict) + get_strategy(name) lookup function.
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
from .pattern_doji import DojiReversal  # noqa: E402
from .pattern_morning_star import MorningStar  # noqa: E402
from .pattern_evening_star import EveningStar  # noqa: E402
from .pattern_three_soldiers import ThreeWhiteSoldiers  # noqa: E402

# Momentum (new — divergence)
from .momentum_macd_divergence import MACDDivergence  # noqa: E402

# Trend (new)
from .trend_triple_ma import TripleMA  # noqa: E402

# ---------------------------------------------------------------------------
# NEW BATCH — 43 additional strategies
# ---------------------------------------------------------------------------

# Multi-Timeframe (5)
from .mtf_rsi_trend import MTFRSITrend  # noqa: E402
from .mtf_ema_breakout import MTFEMABreakout  # noqa: E402
from .mtf_vwap_scalp import MTFVWAPScalp  # noqa: E402
from .mtf_supertrend_confluence import MTFSupertrendConfluence  # noqa: E402
from .mtf_macd_momentum import MTFMACDMomentum  # noqa: E402

# Pairs / Statistical (4)
from .pairs_ratio_reversion import PairsRatioReversion  # noqa: E402
from .pairs_cointegration import PairsCointegration  # noqa: E402
from .stat_regime_hmm import StatRegimeHMM  # noqa: E402
from .stat_kalman_filter import StatKalmanFilter  # noqa: E402

# Intraday India-specific (6)
from .intraday_orb_atr import IntradayORBATR  # noqa: E402
from .intraday_gap_fill import IntradayGapFill  # noqa: E402
from .intraday_first_candle import IntradayFirstCandle  # noqa: E402
from .intraday_vwap_bounce import IntradayVWAPBounce  # noqa: E402
from .intraday_expiry_day import IntradayExpiryDay  # noqa: E402
from .intraday_pre_market import IntradayPreMarket  # noqa: E402

# Options Advanced (5 files → 6 classes)
from .options_jade_lizard import OptionsJadeLizard  # noqa: E402
from .options_ratio_spread import OptionsRatioSpread  # noqa: E402
from .options_calendar_spread import OptionsCalendarSpread  # noqa: E402
from .options_butterfly import OptionsButterfly, OptionsIronButterfly  # noqa: E402
from .options_collar import OptionsCollar  # noqa: E402

# Event-Driven (4)
from .event_earnings import EventEarnings  # noqa: E402
from .event_rbi_policy import EventRBIPolicy  # noqa: E402
from .event_expiry_oi import EventExpiryOI  # noqa: E402
from .event_fii_flow import EventFIIFlow  # noqa: E402

# Crypto (4)
from .crypto_funding_arb import CryptoFundingArb  # noqa: E402
from .crypto_grid import CryptoGrid  # noqa: E402
from .crypto_dca_momentum import CryptoDCAMomentum  # noqa: E402
from .crypto_breakout_volume import CryptoBreakoutVolume  # noqa: E402

# Commodity (3)
from .commodity_seasonal import CommoditySeasonal  # noqa: E402
from .commodity_spread import CommoditySpread  # noqa: E402
from .commodity_inventory import CommodityInventory  # noqa: E402

# Machine Learning (4)
from .ml_feature_signal import MLFeatureSignal  # noqa: E402
from .ml_regime_classifier import MLRegimeClassifier  # noqa: E402
from .ml_ensemble_voter import MLEnsembleVoter  # noqa: E402
from .ml_adaptive_params import MLAdaptiveParams  # noqa: E402

# Portfolio / Risk (4)
from .portfolio_equal_weight import PortfolioEqualWeight  # noqa: E402
from .portfolio_risk_parity import PortfolioRiskParity  # noqa: E402
from .portfolio_momentum_rotation import PortfolioMomentumRotation  # noqa: E402
from .portfolio_min_variance import PortfolioMinVariance  # noqa: E402

# Scalping (4)
from .scalp_tape_reading import ScalpTapeReading  # noqa: E402
from .scalp_level2_squeeze import ScalpLevel2Squeeze  # noqa: E402
from .scalp_tick_momentum import ScalpTickMomentum  # noqa: E402
from .scalp_spread_capture import ScalpSpreadCapture  # noqa: E402

# ---------------------------------------------------------------------------
# Unified strategy registry — all new classes + 12 legacy (~100 total)
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
    # Pattern — absorbed batch (2 legacy + 4 new candlestick)
    "EngulfingPattern": EngulfingPattern,
    "HammerShootingStar": HammerShootingStar,
    "DojiReversal": DojiReversal,
    "MorningStar": MorningStar,
    "EveningStar": EveningStar,
    "ThreeWhiteSoldiers": ThreeWhiteSoldiers,
    # Momentum — MACD divergence
    "MACDDivergence": MACDDivergence,
    # Trend — absorbed batch (1 new)
    "TripleMA": TripleMA,
    # -----------------------------------------------------------------------
    # NEW BATCH — 43 additional strategies (~100 total)
    # -----------------------------------------------------------------------
    # Multi-Timeframe (5)
    "MTFRSITrend": MTFRSITrend,
    "MTFEMABreakout": MTFEMABreakout,
    "MTFVWAPScalp": MTFVWAPScalp,
    "MTFSupertrendConfluence": MTFSupertrendConfluence,
    "MTFMACDMomentum": MTFMACDMomentum,
    # Pairs / Statistical (4)
    "PairsRatioReversion": PairsRatioReversion,
    "PairsCointegration": PairsCointegration,
    "StatRegimeHMM": StatRegimeHMM,
    "StatKalmanFilter": StatKalmanFilter,
    # Intraday India-specific (6)
    "IntradayORBATR": IntradayORBATR,
    "IntradayGapFill": IntradayGapFill,
    "IntradayFirstCandle": IntradayFirstCandle,
    "IntradayVWAPBounce": IntradayVWAPBounce,
    "IntradayExpiryDay": IntradayExpiryDay,
    "IntradayPreMarket": IntradayPreMarket,
    # Options Advanced (6 classes from 5 files)
    "OptionsJadeLizard": OptionsJadeLizard,
    "OptionsRatioSpread": OptionsRatioSpread,
    "OptionsCalendarSpread": OptionsCalendarSpread,
    "OptionsButterfly": OptionsButterfly,
    "OptionsIronButterfly": OptionsIronButterfly,
    "OptionsCollar": OptionsCollar,
    # Event-Driven (4)
    "EventEarnings": EventEarnings,
    "EventRBIPolicy": EventRBIPolicy,
    "EventExpiryOI": EventExpiryOI,
    "EventFIIFlow": EventFIIFlow,
    # Crypto (4)
    "CryptoFundingArb": CryptoFundingArb,
    "CryptoGrid": CryptoGrid,
    "CryptoDCAMomentum": CryptoDCAMomentum,
    "CryptoBreakoutVolume": CryptoBreakoutVolume,
    # Commodity (3)
    "CommoditySeasonal": CommoditySeasonal,
    "CommoditySpread": CommoditySpread,
    "CommodityInventory": CommodityInventory,
    # Machine Learning (4)
    "MLFeatureSignal": MLFeatureSignal,
    "MLRegimeClassifier": MLRegimeClassifier,
    "MLEnsembleVoter": MLEnsembleVoter,
    "MLAdaptiveParams": MLAdaptiveParams,
    # Portfolio / Risk (4)
    "PortfolioEqualWeight": PortfolioEqualWeight,
    "PortfolioRiskParity": PortfolioRiskParity,
    "PortfolioMomentumRotation": PortfolioMomentumRotation,
    "PortfolioMinVariance": PortfolioMinVariance,
    # Scalping (4)
    "ScalpTapeReading": ScalpTapeReading,
    "ScalpLevel2Squeeze": ScalpLevel2Squeeze,
    "ScalpTickMomentum": ScalpTickMomentum,
    "ScalpSpreadCapture": ScalpSpreadCapture,
}

# ---------------------------------------------------------------------------
# AlgoTrading absorption batch — 5 category files (26 strategy classes)
# ---------------------------------------------------------------------------

# Trend-following (9)
from .trend_following import (  # noqa: E402
    SupertrendStrategy,
    EMACrossoverStrategy,
    MACDStrategy,
    ADXStrategy,
    ADXDIStrategy,
    ParabolicSARStrategy,
    DonchianBreakoutStrategy,
    KeltnerBreakoutStrategy,
    HeikinAshiStrategy,
)

# Mean reversion (6)
from .mean_reversion import (  # noqa: E402
    RSIStrategy,
    BollingerBandStrategy,
    StochasticStrategy,
    CCIStrategy,
    WilliamsRStrategy,
    KeltnerChannelStrategy,
)

# Momentum (6)
from .momentum import (  # noqa: E402
    MomentumStrategy,
    DualMomentumStrategy,
    VolumeBreakoutStrategy,
    VWAPStrategy,
    OBVStrategy,
    VWMAStrategy,
)

# Volatility (4)
from .volatility import (  # noqa: E402
    ATRBreakoutStrategy,
    ATRRangeStrategy,
    ChoppinessBreakoutStrategy,
    VolatilityContractionStrategy,
)

# Composite (4)
from .composite import (  # noqa: E402
    RSI_MACD_Strategy,
    SupertrendEMAStrategy,
    TripleScreenStrategy,
    IchimokuStrategy,
)

# NOTE: The new BaseBacktestStrategy-based classes are NOT added to ALL_STRATEGIES
# because ALL_STRATEGIES requires BaseStrategy (packages.engine) in the MRO.
# They live exclusively in STRATEGY_REGISTRY below.

# ---------------------------------------------------------------------------
# STRATEGY_REGISTRY and get_strategy() — for the BaseBacktestStrategy-based classes
# ---------------------------------------------------------------------------
try:
    from ..base_strategy import BaseBacktestStrategy as _BaseBacktestStrategy  # noqa: E402
except ImportError:
    from base_strategy import BaseBacktestStrategy as _BaseBacktestStrategy  # type: ignore[no-redef]  # noqa: E402

STRATEGY_REGISTRY: dict[str, type[_BaseBacktestStrategy]] = {
    # Trend-following
    "SupertrendStrategy": SupertrendStrategy,
    "EMACrossoverStrategy": EMACrossoverStrategy,
    "MACDStrategy": MACDStrategy,
    "ADXStrategy": ADXStrategy,
    "ADXDIStrategy": ADXDIStrategy,
    "ParabolicSARStrategy": ParabolicSARStrategy,
    "DonchianBreakoutStrategy": DonchianBreakoutStrategy,
    "KeltnerBreakoutStrategy": KeltnerBreakoutStrategy,
    "HeikinAshiStrategy": HeikinAshiStrategy,
    # Mean reversion
    "RSIStrategy": RSIStrategy,
    "BollingerBandStrategy": BollingerBandStrategy,
    "StochasticStrategy": StochasticStrategy,
    "CCIStrategy": CCIStrategy,
    "WilliamsRStrategy": WilliamsRStrategy,
    "KeltnerChannelStrategy": KeltnerChannelStrategy,
    # Momentum
    "MomentumStrategy": MomentumStrategy,
    "DualMomentumStrategy": DualMomentumStrategy,
    "VolumeBreakoutStrategy": VolumeBreakoutStrategy,
    "VWAPStrategy": VWAPStrategy,
    "OBVStrategy": OBVStrategy,
    "VWMAStrategy": VWMAStrategy,
    # Volatility
    "ATRBreakoutStrategy": ATRBreakoutStrategy,
    "ATRRangeStrategy": ATRRangeStrategy,
    "ChoppinessBreakoutStrategy": ChoppinessBreakoutStrategy,
    "VolatilityContractionStrategy": VolatilityContractionStrategy,
    # Composite
    "RSI_MACD_Strategy": RSI_MACD_Strategy,
    "SupertrendEMAStrategy": SupertrendEMAStrategy,
    "TripleScreenStrategy": TripleScreenStrategy,
    "IchimokuStrategy": IchimokuStrategy,
}


def get_strategy(name: str) -> type[_BaseBacktestStrategy]:
    """Look up a BaseBacktestStrategy subclass by registry name.

    Args:
        name: Strategy registry key (e.g. ``"SupertrendStrategy"``).

    Returns:
        Strategy class.

    Raises:
        KeyError: If ``name`` is not found in STRATEGY_REGISTRY.
    """
    try:
        return STRATEGY_REGISTRY[name]
    except KeyError:
        available = ", ".join(sorted(STRATEGY_REGISTRY))
        raise KeyError(
            f"Strategy {name!r} not found. Available: {available}"
        ) from None

