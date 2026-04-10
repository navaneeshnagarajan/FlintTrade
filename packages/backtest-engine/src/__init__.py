"""FlintTrade backtest-engine package — simulation, metrics, optimization, strategies."""

__version__ = "0.1.0-alpha"


def _try_import(relative_name: str, bare_name: str, names: list[str]) -> dict:
    """Try relative import first, then bare import."""
    result = {}
    try:
        mod = __import__(relative_name, globals(), locals(), names, 1)
        for n in names:
            result[n] = getattr(mod, n)
    except (ImportError, SystemError, ValueError):
        try:
            mod = __import__(bare_name, globals(), locals(), names, 0)
            for n in names:
                result[n] = getattr(mod, n)
        except (ImportError, ModuleNotFoundError):
            pass
    return result


# --- Event-driven engine ---
globals().update(_try_import(".engine", "engine", [
    "BacktestEngine", "EngineConfig", "EngineOrder", "EnginePosition",
    "EngineTrade", "EngineResult", "EngineEquityPoint",
    "OrderSide", "OrderType", "OrderStatus", "FillMode",
]))

# --- Tax calculator ---
globals().update(_try_import(".tax_calculator", "tax_calculator", [
    "IndianTaxCalculator", "TradeType", "Exchange",
    "TaxBreakdown", "TaxSummary",
    "make_equity_calculator", "make_intraday_calculator", "make_fo_calculator",
]))

# --- Base strategy ---
globals().update(_try_import(".base_strategy", "base_strategy", [
    "BaseBacktestStrategy", "Signal", "OrderIntent", "indicators",
]))

# --- Simulator ---
globals().update(_try_import(".simulator", "simulator", [
    "BacktestConfig", "BacktestResult", "BacktestSimulator",
    "EquityPoint", "SimOrder", "SimTrade",
]))

# --- Metrics ---
globals().update(_try_import(".metrics", "metrics", [
    "DrawdownInfo", "MonthlyReturn", "PerformanceMetrics",
    "PerformanceReport", "RiskMetrics", "TradeStats",
]))

# --- Optimizer ---
globals().update(_try_import(".optimizer", "optimizer", [
    "MonteCarloResult", "ParamGrid", "WalkForwardOptimizer", "WalkForwardResult",
]))

# --- Data connectors ---
globals().update(_try_import(".data_connector", "data_connector", [
    "CSVConnector", "DataConnector", "DataResult",
    "DuckDBConnector", "JSONConnector", "YFinanceConnector",
]))

# --- Built-in strategies ---
globals().update(_try_import(".strategies", "strategies", [
    "BUILTIN_STRATEGIES", "BearCallSpread", "BollingerMeanReversion",
    "BullPutSpread", "EMACrossover", "IronCondor", "MACDRSIStrategy",
    "MomentumBreakout", "OpeningRangeBreakout", "StraddleSell",
    "StrangleSell", "SupertrendStrategy", "VWAPDeviation",
]))

# --- RL environment ---
globals().update(_try_import(".rl_environment", "rl_environment", [
    "EnvironmentConfig", "TradingEnvironment",
]))
globals().update(_try_import(".rl_features", "rl_features", [
    "DEFAULT_FEATURES", "MINIMAL_FEATURES", "RewardState", "RewardType",
    "compute_features", "compute_reward", "normalise_features",
]))
globals().update(_try_import(".rl_trainer", "rl_trainer", [
    "DEFAULT_PARAMS", "RLAlgorithm", "RLTrainer",
    "TrainingJob", "TrainingResult", "register_rl_endpoints",
]))

# --- Portfolio optimiser ---
globals().update(_try_import(".portfolio_optimiser", "portfolio_optimiser", [
    "OptimiserConfig", "PortfolioOptimiser", "PortfolioResult",
]))
globals().update(_try_import(".optimiser_routes", "optimiser_routes", ["optimiser_bp"]))

# --- Permutation testing ---
globals().update(_try_import(".permutation_test", "permutation_test", [
    "PermutationConfig", "PermutationResult", "PermutationTester",
]))
_ns = _try_import(".walk_forward", "walk_forward", [
    "WalkForwardConfig", "WalkForwardResult", "WalkForwardAnalyser", "SplitDetail",
])
if "WalkForwardConfig" in _ns:
    _ns["WFConfig"] = _ns["WalkForwardConfig"]
if "WalkForwardResult" in _ns:
    _ns["WFResult"] = _ns["WalkForwardResult"]
globals().update(_ns)
globals().update(_try_import(".permutation_routes", "permutation_routes", ["permutation_bp"]))

# --- Strategy comparison ---
globals().update(_try_import(".strategy_comparison", "strategy_comparison", [
    "StrategyComparator", "StrategyComparisonResult",
]))

# --- Simulation ---
globals().update(_try_import(".simulation", "simulation", [
    "SimulationEngine", "SimulationScenario", "SimulationPhase",
    "MarketEvent", "SimulationResult", "StressTestRunner",
]))

# Cleanup
del _ns, _try_import

__all__ = [
    "BacktestEngine", "EngineConfig", "EngineOrder", "EnginePosition",
    "EngineTrade", "EngineResult", "EngineEquityPoint",
    "OrderSide", "OrderType", "OrderStatus", "FillMode",
    "IndianTaxCalculator", "TradeType", "Exchange",
    "TaxBreakdown", "TaxSummary",
    "make_equity_calculator", "make_intraday_calculator", "make_fo_calculator",
    "BaseBacktestStrategy", "Signal", "OrderIntent", "indicators",
    "BacktestSimulator", "BacktestConfig", "BacktestResult",
    "SimOrder", "SimTrade", "EquityPoint",
    "PerformanceMetrics", "PerformanceReport", "TradeStats",
    "DrawdownInfo", "RiskMetrics", "MonthlyReturn",
    "WalkForwardOptimizer", "WalkForwardResult", "MonteCarloResult", "ParamGrid",
    "DataConnector", "DataResult", "DuckDBConnector", "CSVConnector",
    "JSONConnector", "YFinanceConnector",
    "BUILTIN_STRATEGIES", "EMACrossover", "SupertrendStrategy",
    "MACDRSIStrategy", "BollingerMeanReversion", "VWAPDeviation",
    "StraddleSell", "StrangleSell", "IronCondor",
    "BullPutSpread", "BearCallSpread", "MomentumBreakout", "OpeningRangeBreakout",
    "TradingEnvironment", "EnvironmentConfig",
    "DEFAULT_FEATURES", "MINIMAL_FEATURES", "RewardType", "RewardState",
    "compute_features", "compute_reward", "normalise_features",
    "RLTrainer", "RLAlgorithm", "TrainingResult", "TrainingJob",
    "DEFAULT_PARAMS", "register_rl_endpoints",
    "OptimiserConfig", "PortfolioOptimiser", "PortfolioResult", "optimiser_bp",
    "PermutationConfig", "PermutationResult", "PermutationTester",
    "WFConfig", "WFResult", "WalkForwardAnalyser", "SplitDetail",
    "permutation_bp",
    "StrategyComparator", "StrategyComparisonResult",
    "SimulationEngine", "SimulationScenario", "SimulationPhase",
    "MarketEvent", "SimulationResult", "StressTestRunner",
]
