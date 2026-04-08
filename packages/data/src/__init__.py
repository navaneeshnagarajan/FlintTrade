"""FlintTrade data package — tick capture, audit logs, trade logging, DuckDB storage."""

__version__ = "0.1.0-alpha"

from .activity_log import ActivityEntry, ActivityLog
from .audit_logger import AuditLogger
from .orderflow import FootprintBucket, FootprintCell, OrderFlowAggregator
from .storage import StorageManager
from .tick_recorder import TickRecorder
from .trade_logger import TradeLogger, TradeSummary

__all__ = [
    "StorageManager",
    "TickRecorder",
    "AuditLogger",
    "TradeLogger",
    "TradeSummary",
    "OrderFlowAggregator",
    "FootprintBucket",
    "FootprintCell",
    "ActivityLog",
    "ActivityEntry",
]
