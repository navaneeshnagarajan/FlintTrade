"""FlintTrade screener package — OI analysis, Greeks, futures quadrant, IV analysis, RRG, scanner, fundamentals, ETF screener, shareholding."""

__version__ = "0.1.0-alpha"

from .options_payoff import (
    OptionLeg,
    OptionsPayoffEngine,
    PayoffAnalysis,
    PayoffPoint,
)
from .regime_detector import RegimeDetector, RegimeSignal, RegimeType
from .correlation import CorrelationEngine, CorrelationMatrix, make_sample_returns

from .scanner import ScannerDef, ScannerEngine, ScanResult
from .market_scanner import (
    PREBUILT_SCANS,
    MarketScanner,
    ScanCondition,
    ScanConfig,
    ScanResult as MarketScanResult,
)
from .oi_analytics import (
    OIAnalytics,
    OISnapshot,
    OIHeatmapData,
    OIHeatmapEntry,
    OIChangeAnalysis,
    OIChangeSignal,
    OITrendEntry,
    SupportResistanceLevels,
    UnusualOIEntry,
)
from .stock_cache import StockCache, StockFundamentals
from .fundamental_screener import FundamentalData, FundamentalScreener, SearchResult

from .futures_quadrant import FuturesQuadrant, FuturesSnapshot, Quadrant, QuadrantResult
from .greeks import OptionPosition, PortfolioGreeks, PortfolioGreeksResult, PositionGreeks
from .iv_analysis import IVAnalysis, IVPercentileResult, IVSkewResult, IVTermStructure
from .oi_analysis import (
    MaxPainResult,
    OIAnalysis,
    OIChangeEntry,
    OISpurtEntry,
    PCRResult,
    SupportResistance,
)
from .option_chain import (
    LOT_SIZES,
    OptionChainAnalyzer,
    OptionChainSnapshot,
    StrikeData,
)
from .fii_dii import FiiDiiSnapshot, FiiDiiTracker, FiiDiiTrend
from .earnings_calendar import EarningsCalendar, EarningsEvent
from .pivot_calculator import PivotCalculator, PivotLevels, PivotMethod
from .economic_calendar import EconomicCalendarProvider, EconomicEvent
from .orderflow_inference import FlowBucket, OrderFlowInference, PriceLevel
from .market_breadth import BreadthData, MarketBreadthCalculator
from .volatility_cone import VolatilityCone, VolatilityConePoint
from .pair_correlation import PairCorrelationEngine, PairSignal, make_sample_pair_data
from .multi_timeframe import (
    MTFAnalysis,
    MultiTimeframeAnalyser,
    TimeframeSignal,
    make_sample_mtf_data,
)
from .rrg import (
    NIFTY_SECTORS,
    RRGPoint,
    SectorRRG,
    build_sector_rrg,
    classify_quadrant,
    compute_rrg,
)
from .etf_screener import (
    ETF_CATALOGUE,
    ETFRecord,
    ETFScreenResult,
    calculate_momentum_score,
    calculate_asset_quilt,
    get_52w_high_low,
    get_sparkline,
    screen_etfs,
)
from .shareholding import (
    Announcement,
    AnnualFinancial,
    FinancialSummary,
    QuarterlyHolding,
    ShareholdingData,
    fetch_shareholding,
    fetch_financial_summary,
    fetch_corporate_announcements,
)
from .lot_sizes import (
    FALLBACK_LOT_SIZES,
    LotSizeResolver,
    get_lot_size_sync,
)
from .gex_analytics import (
    compute_gex_by_strike,
    find_gamma_walls,
    total_gex,
    zero_gamma_level,
)
from .iv_analytics import (
    compute_iv_smile,
    compute_iv_skew,
    compute_atm_iv,
    compute_iv_term_structure,
)
from .vol_surface_analytics import (
    build_vol_surface,
    surface_to_grid,
)
from .oi_profile_analytics import (
    oi_profile_by_strike,
    put_call_oi_ratio,
    max_pain,
    oi_change_top_movers,
)
from .straddle_simulator import (
    simulate_short_straddle,
    simulate_iron_condor,
    simulate_iron_butterfly,
    straddle_pnl_curve,
)

__all__ = [
    # Options payoff engine
    "OptionLeg",
    "OptionsPayoffEngine",
    "PayoffAnalysis",
    "PayoffPoint",
    # Regime detector
    "RegimeDetector",
    "RegimeSignal",
    "RegimeType",
    # Correlation engine
    "CorrelationEngine",
    "CorrelationMatrix",
    "make_sample_returns",
    # Stock cache
    "StockCache",
    "StockFundamentals",
    # Option chain
    "OptionChainAnalyzer",
    "OptionChainSnapshot",
    "StrikeData",
    "LOT_SIZES",
    # OI analysis
    "OIAnalysis",
    "PCRResult",
    "MaxPainResult",
    "OIChangeEntry",
    "OISpurtEntry",
    "SupportResistance",
    # Futures quadrant
    "FuturesQuadrant",
    "FuturesSnapshot",
    "Quadrant",
    "QuadrantResult",
    # Portfolio Greeks
    "PortfolioGreeks",
    "PortfolioGreeksResult",
    "PositionGreeks",
    "OptionPosition",
    # IV analysis
    "IVAnalysis",
    "IVSkewResult",
    "IVPercentileResult",
    "IVTermStructure",
    # RRG
    "RRGPoint",
    "SectorRRG",
    "NIFTY_SECTORS",
    "compute_rrg",
    "classify_quadrant",
    "build_sector_rrg",
    # Code-execution scanner (fluxscan pattern)
    "ScannerDef",
    "ScannerEngine",
    "ScanResult",
    # Declarative market scanner
    "MarketScanner",
    "ScanCondition",
    "ScanConfig",
    "MarketScanResult",
    "PREBUILT_SCANS",
    # Enhanced OI analytics
    "OIAnalytics",
    "OISnapshot",
    "OIHeatmapData",
    "OIHeatmapEntry",
    "OIChangeAnalysis",
    "OIChangeSignal",
    "OITrendEntry",
    "SupportResistanceLevels",
    "UnusualOIEntry",
    # Fundamental screener
    "FundamentalScreener",
    "FundamentalData",
    "SearchResult",
    # FII/DII flows
    "FiiDiiTracker",
    "FiiDiiSnapshot",
    "FiiDiiTrend",
    # Earnings calendar
    "EarningsCalendar",
    "EarningsEvent",
    # Pivot calculator
    "PivotCalculator",
    "PivotLevels",
    "PivotMethod",
    # Economic calendar
    "EconomicCalendarProvider",
    "EconomicEvent",
    # Order flow inference
    "OrderFlowInference",
    "FlowBucket",
    "PriceLevel",
    # Market breadth
    "BreadthData",
    "MarketBreadthCalculator",
    # Volatility cone
    "VolatilityCone",
    "VolatilityConePoint",
    # Pair correlation
    "PairCorrelationEngine",
    "PairSignal",
    "make_sample_pair_data",
    # Multi-timeframe analyser
    "MultiTimeframeAnalyser",
    "MTFAnalysis",
    "TimeframeSignal",
    "make_sample_mtf_data",
    # ETF screener
    "ETF_CATALOGUE",
    "ETFRecord",
    "ETFScreenResult",
    "calculate_momentum_score",
    "calculate_asset_quilt",
    "get_52w_high_low",
    "get_sparkline",
    "screen_etfs",
    # Shareholding + fundamentals
    "Announcement",
    "AnnualFinancial",
    "FinancialSummary",
    "QuarterlyHolding",
    "ShareholdingData",
    "fetch_shareholding",
    "fetch_financial_summary",
    "fetch_corporate_announcements",
    # Lot sizes
    "FALLBACK_LOT_SIZES",
    "LotSizeResolver",
    "get_lot_size_sync",
    # GEX analytics (P1)
    "compute_gex_by_strike",
    "find_gamma_walls",
    "total_gex",
    "zero_gamma_level",
    # IV analytics (P1)
    "compute_iv_smile",
    "compute_iv_skew",
    "compute_atm_iv",
    "compute_iv_term_structure",
    # Vol surface analytics (P1)
    "build_vol_surface",
    "surface_to_grid",
    # OI profile analytics (P1)
    "oi_profile_by_strike",
    "put_call_oi_ratio",
    "max_pain",
    "oi_change_top_movers",
    # Straddle simulator (P1)
    "simulate_short_straddle",
    "simulate_iron_condor",
    "simulate_iron_butterfly",
    "straddle_pnl_curve",
]
