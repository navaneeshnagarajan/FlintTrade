"""FlintTrade engine package — strategy execution, safety, routing, scheduling."""

from flinttrade_core.version import APP_VERSION

__version__ = APP_VERSION

from .safety import (
    DailyPnLLimits,
    IntradayAllowList,
    KillSwitch,
    MTMCircuitBreaker,
    MTMCircuitBreakerConfig,
    OrderValidation,
    OvertradingConfig,
    OvertradingGuard,
    PortfolioRisk,
    PositionLimits,
    SafetyConfig,
    SafetyResult,
    SafetySystem,
    SafetyVerdict,
)
from .scheduler import (
    EXCHANGE_SCHEDULES,
    CronScheduleConfig,
    CronStrategyScheduler,
    ExchangeSchedule,
    StrategyRunner,
    StrategyScheduler,
    StrategyStartTimeoutError,
    TimeScheduler,
)
from .bracket_order import BracketOrder, BracketOrderError, BracketOrderService, BracketResult
from .position_sizer import PositionSizer
from .strategy import BaseStrategy, StrategyRegistry, StrategyState
from .strategy_execution import (
    GatedStrategyDispatcher,
    StrategyExecutionContract,
    StrategyExecutionMode,
)

# NOTE: UserStrategyRunner is intentionally
# NOT imported here to prevent triggering the pre-existing circular import
# between flinttrade_core.__init__ (which imports app.py) and the engine
# submodules.  Import these directly from their submodules:
#
#   from flinttrade_engine.strategy_runner import UserStrategyRunner
#   from flinttrade_engine.strategy_routes import strategy_bp
#   from flinttrade_engine.bracket_routes import bracket_bp

__all__ = [
    # Safety
    "SafetySystem",
    "SafetyConfig",
    "SafetyResult",
    "SafetyVerdict",
    "OrderValidation",
    "PositionLimits",
    "PortfolioRisk",
    "DailyPnLLimits",
    "KillSwitch",
    "OvertradingGuard",
    "OvertradingConfig",
    "MTMCircuitBreaker",
    "MTMCircuitBreakerConfig",
    "IntradayAllowList",
    # Scheduler
    "TimeScheduler",
    "ExchangeSchedule",
    "EXCHANGE_SCHEDULES",
    "StrategyRunner",
    "StrategyScheduler",
    "StrategyStartTimeoutError",
    "CronStrategyScheduler",
    "CronScheduleConfig",
    # Strategy
    "BaseStrategy",
    "StrategyState",
    "StrategyRegistry",
    "StrategyExecutionMode",
    "StrategyExecutionContract",
    "GatedStrategyDispatcher",
    # Bracket orders
    "BracketOrder",
    "BracketOrderService",
    "BracketOrderError",
    "BracketResult",
    # Position sizer
    "PositionSizer",
]
