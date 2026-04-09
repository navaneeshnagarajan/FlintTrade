"""FlintTrade screener package — OI analysis, Greeks, futures quadrant, IV analysis, RRG, scanner, fundamentals."""

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
from .rrg import (
    NIFTY_SECTORS,
    RRGPoint,
    SectorRRG,
    build_sector_rrg,
    classify_quadrant,
    compute_rrg,
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
]
