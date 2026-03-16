"""FlintTrade engine package — strategy execution, safety, routing, scheduling."""

__version__ = "0.1.0-alpha"

from .router import OrderRouter, RoutingDecision, StrategyRouteConfig
from .safety import (
    DailyPnLLimits,
    KillSwitch,
    OrderValidation,
    PortfolioRisk,
    PositionLimits,
    SafetyConfig,
    SafetyResult,
    SafetySystem,
    SafetyVerdict,
)
from .scheduler import (
    EXCHANGE_SCHEDULES,
    ExchangeSchedule,
    StrategyRunner,
    StrategyScheduler,
    TimeScheduler,
)
from .strategy import BaseStrategy, StrategyRegistry, StrategyState

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
    # Router
    "OrderRouter",
    "RoutingDecision",
    "StrategyRouteConfig",
    # Scheduler
    "TimeScheduler",
    "ExchangeSchedule",
    "EXCHANGE_SCHEDULES",
    "StrategyRunner",
    "StrategyScheduler",
    # Strategy
    "BaseStrategy",
    "StrategyState",
    "StrategyRegistry",
]
