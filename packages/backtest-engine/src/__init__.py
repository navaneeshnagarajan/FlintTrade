"""FlintTrade backtest-engine package — simulation, metrics, optimization, strategies."""

__version__ = "0.1.0-dev"

from .data_connector import (
    CSVConnector,
    DataConnector,
    DataResult,
    DuckDBConnector,
    JSONConnector,
    YFinanceConnector,
)
from .metrics import (
    DrawdownInfo,
    MonthlyReturn,
    PerformanceMetrics,
    PerformanceReport,
    RiskMetrics,
    TradeStats,
)
from .optimizer import (
    MonteCarloResult,
    ParamGrid,
    WalkForwardOptimizer,
    WalkForwardResult,
)
from .simulator import (
    BacktestConfig,
    BacktestResult,
    BacktestSimulator,
    EquityPoint,
    SimOrder,
    SimTrade,
)
from .strategies import (
    BUILTIN_STRATEGIES,
    BearCallSpread,
    BollingerMeanReversion,
    BullPutSpread,
    EMACrossover,
    IronCondor,
    MACDRSIStrategy,
    MomentumBreakout,
    OpeningRangeBreakout,
    StraddleSell,
    StrangleSell,
    SupertrendStrategy,
    VWAPDeviation,
)

__all__ = [
    # Simulator
    "BacktestSimulator",
    "BacktestConfig",
    "BacktestResult",
    "SimOrder",
    "SimTrade",
    "EquityPoint",
    # Metrics
    "PerformanceMetrics",
    "PerformanceReport",
    "TradeStats",
    "DrawdownInfo",
    "RiskMetrics",
    "MonthlyReturn",
    # Optimizer
    "WalkForwardOptimizer",
    "WalkForwardResult",
    "MonteCarloResult",
    "ParamGrid",
    # Data
    "DataConnector",
    "DataResult",
    "DuckDBConnector",
    "CSVConnector",
    "JSONConnector",
    "YFinanceConnector",
    # Strategies
    "BUILTIN_STRATEGIES",
    "EMACrossover",
    "SupertrendStrategy",
    "MACDRSIStrategy",
    "BollingerMeanReversion",
    "VWAPDeviation",
    "StraddleSell",
    "StrangleSell",
    "IronCondor",
    "BullPutSpread",
    "BearCallSpread",
    "MomentumBreakout",
    "OpeningRangeBreakout",
]
