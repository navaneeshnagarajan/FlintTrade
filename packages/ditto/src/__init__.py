"""FlintTrade ditto package — multi-broker, multi-account orchestration."""

__version__ = "0.1.0-alpha"

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
from .algomirror_bridge import AlgoMirrorBridge, AlgoMirrorStatus
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
    # AlgoMirror bridge
    "AlgoMirrorBridge",
    "AlgoMirrorStatus",
]
