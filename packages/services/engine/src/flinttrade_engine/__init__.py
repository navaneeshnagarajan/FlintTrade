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
    TimeScheduler,
)
from .bracket_order import BracketOrder, BracketOrderError, BracketOrderService, BracketResult
from .position_sizer import PositionSizer
from .strategy import BaseStrategy, StrategyRegistry, StrategyState

# NOTE: SandboxEngine, SandboxConfig, and UserStrategyRunner are intentionally
# NOT imported here to prevent triggering the pre-existing circular import
# between flinttrade_core.__init__ (which imports app.py) and the engine
# submodules.  Import these directly from their submodules:
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
