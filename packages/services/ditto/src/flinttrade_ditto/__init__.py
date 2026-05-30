"""FlintTrade ditto package — multi-broker, multi-account orchestration."""

from flinttrade_core.version import APP_VERSION

__version__ = APP_VERSION

from .account_manager import AccountHealth, AccountManager, BrokerAccount
from .margin_calculator import (
    MarginCalculator,
    MarginInfo,
    MultiLegMarginResult,
    OrderMarginEstimate,
)
from .mirror import AllocationMode, MirrorResult, PositionMirror
from .risk_manager import (
    AccountRiskState,
    RiskCheckResult,
    RiskConfig,
    RiskManager,
    RiskStatus,
    TradeGrade,
    TradeQuality,
)
from .trailing_sl import (
    SLAdjustment,
    SLTracker,
    TrailingMode,
    TrailingSLManager,
)

__all__ = [
    # Accounts
    "AccountManager",
    "BrokerAccount",
    "AccountHealth",
    # Mirror
    "PositionMirror",
    "AllocationMode",
    "MirrorResult",
    # Margin
    "MarginCalculator",
    "MarginInfo",
    "OrderMarginEstimate",
    "MultiLegMarginResult",
    # Trailing SL
    "TrailingSLManager",
    "SLTracker",
    "SLAdjustment",
    "TrailingMode",
    # Risk
    "RiskManager",
    "RiskConfig",
    "RiskStatus",
    "RiskCheckResult",
    "AccountRiskState",
    "TradeGrade",
    "TradeQuality",
]
