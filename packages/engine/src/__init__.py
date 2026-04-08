"""FlintTrade engine package — strategy execution, safety, routing, scheduling."""

__version__ = "0.1.0-alpha"

from .router import OrderRouter, RoutingDecision, SandboxAccountConfig, StrategyRouteConfig
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
from .bracket_order import BracketOrder, BracketOrderError, BracketOrderService, BracketResult
from .strategy import BaseStrategy, StrategyRegistry, StrategyState

# NOTE: SandboxEngine, SandboxConfig, and UserStrategyRunner are intentionally
# NOT imported here to prevent triggering the pre-existing circular import
# between packages.core.src.__init__ (which imports app.py) and
# packages.engine.src.router.  Import these directly from their submodules:
#
#   from packages.engine.src.sandbox import SandboxEngine, SandboxConfig
#   from packages.engine.src.strategy_runner import UserStrategyRunner
#   from packages.engine.src.sandbox_routes import sandbox_bp
#   from packages.engine.src.strategy_routes import strategy_bp
#   from packages.engine.src.bracket_routes import bracket_bp

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
    "SandboxAccountConfig",
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
    # Bracket orders
    "BracketOrder",
    "BracketOrderService",
    "BracketOrderError",
    "BracketResult",
]
