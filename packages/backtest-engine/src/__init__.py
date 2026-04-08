"""FlintTrade backtest-engine package — simulation, metrics, optimization, strategies."""

__version__ = "0.1.0-alpha"

try:
    from .data_connector import (
        CSVConnector, DataConnector, DataResult,
        DuckDBConnector, JSONConnector, YFinanceConnector,
    )
    from .metrics import (
        DrawdownInfo, MonthlyReturn, PerformanceMetrics,
        PerformanceReport, RiskMetrics, TradeStats,
    )
    from .optimizer import (
        MonteCarloResult, ParamGrid, WalkForwardOptimizer, WalkForwardResult,
    )
    from .simulator import (
        BacktestConfig, BacktestResult, BacktestSimulator,
        EquityPoint, SimOrder, SimTrade,
    )
    from .strategies import (
        BUILTIN_STRATEGIES, BearCallSpread, BollingerMeanReversion,
        BullPutSpread, EMACrossover, IronCondor, MACDRSIStrategy,
        MomentumBreakout, OpeningRangeBreakout, StraddleSell,
        StrangleSell, SupertrendStrategy, VWAPDeviation,
    )
    from .rl_environment import EnvironmentConfig, TradingEnvironment
    from .rl_features import (
        DEFAULT_FEATURES, MINIMAL_FEATURES, RewardState, RewardType,
        compute_features, compute_reward, normalise_features,
    )
    from .rl_trainer import (
        DEFAULT_PARAMS, RLAlgorithm, RLTrainer,
        TrainingJob, TrainingResult, register_rl_endpoints,
    )
except ImportError:
    from data_connector import (
        CSVConnector, DataConnector, DataResult,
        DuckDBConnector, JSONConnector, YFinanceConnector,
    )
    from metrics import (
        DrawdownInfo, MonthlyReturn, PerformanceMetrics,
        PerformanceReport, RiskMetrics, TradeStats,
    )
    from optimizer import (
        MonteCarloResult, ParamGrid, WalkForwardOptimizer, WalkForwardResult,
    )
    from simulator import (
        BacktestConfig, BacktestResult, BacktestSimulator,
        EquityPoint, SimOrder, SimTrade,
    )
    from strategies import (
        BUILTIN_STRATEGIES, BearCallSpread, BollingerMeanReversion,
        BullPutSpread, EMACrossover, IronCondor, MACDRSIStrategy,
        MomentumBreakout, OpeningRangeBreakout, StraddleSell,
        StrangleSell, SupertrendStrategy, VWAPDeviation,
    )
    from rl_environment import EnvironmentConfig, TradingEnvironment
    from rl_features import (
        DEFAULT_FEATURES, MINIMAL_FEATURES, RewardState, RewardType,
        compute_features, compute_reward, normalise_features,
    )
    from rl_trainer import (
        DEFAULT_PARAMS, RLAlgorithm, RLTrainer,
        TrainingJob, TrainingResult, register_rl_endpoints,
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
    # RL Environment
    "TradingEnvironment",
    "EnvironmentConfig",
    # RL Features
    "DEFAULT_FEATURES",
    "MINIMAL_FEATURES",
    "RewardType",
    "RewardState",
    "compute_features",
    "compute_reward",
    "normalise_features",
    # RL Trainer
    "RLTrainer",
    "RLAlgorithm",
    "TrainingResult",
    "TrainingJob",
    "DEFAULT_PARAMS",
    "register_rl_endpoints",
]
