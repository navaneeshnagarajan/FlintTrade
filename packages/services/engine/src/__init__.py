"""FlintTrade engine package — strategy execution, safety, routing, scheduling."""

__version__ = "0.1.0-alpha"

from .router import OrderRouter, RoutingDecision, SandboxAccountConfig, StrategyRouteConfig
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
    TimeScheduler,
)
from .bracket_order import BracketOrder, BracketOrderError, BracketOrderService, BracketResult
from .position_sizer import PositionSizer
from .strategy import BaseStrategy, StrategyRegistry, StrategyState

# NOTE: SandboxEngine, SandboxConfig, and UserStrategyRunner are intentionally
# NOT imported here to prevent triggering the pre-existing circular import
# between flinttrade_core.__init__ (which imports app.py) and
# flinttrade_engine.router.  Import these directly from their submodules:
#
#   from flinttrade_engine.sandbox import SandboxEngine, SandboxConfig
#   from flinttrade_engine.strategy_runner import UserStrategyRunner
#   from flinttrade_engine.sandbox_routes import sandbox_bp
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
    # Router
    "OrderRouter",
    "RoutingDecision",
    "StrategyRouteConfig",
    "SandboxAccountConfig",
    # Scheduler
    "TimeScheduler",
    "ExchangeSchedule",
    "EXCHANGE_SCHEDULES",
    "StrategyRunner",
    "StrategyScheduler",
    "CronStrategyScheduler",
    "CronScheduleConfig",
    # Strategy
    "BaseStrategy",
    "StrategyState",
    "StrategyRegistry",
    # Bracket orders
    "BracketOrder",
    "BracketOrderService",
    "BracketOrderError",
    "BracketResult",
    # Position sizer
    "PositionSizer",
]
