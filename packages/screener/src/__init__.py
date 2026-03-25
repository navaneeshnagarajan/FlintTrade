"""FlintTrade screener package — OI analysis, Greeks, futures quadrant, IV analysis, RRG."""

__version__ = "0.1.0-alpha"

from .stock_cache import StockCache, StockFundamentals

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
from .rrg import (
    NIFTY_SECTORS,
    RRGPoint,
    SectorRRG,
    build_sector_rrg,
    classify_quadrant,
    compute_rrg,
)

__all__ = [
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
]
