"""FlintTrade data package — tick capture, audit logs, storage, QuestDB, and sandbox state."""

from importlib import import_module

from flinttrade_core.version import APP_VERSION

__version__ = APP_VERSION

from .activity_log import ActivityEntry, ActivityLog, LoginActivity, SessionTracker
from .audit_logger import AuditLogger
from .security_tracker import SecurityTracker
from .orderflow import FootprintBucket, FootprintCell, OrderFlowAggregator
from .orderflow_aggregator import (
    FootprintBucket as FootprintBucketV2,
    OrderFlowAggregator as OrderFlowAggregatorV2,
)
from .questdb_bridge import QuestDBBridge, QuestDBBridgeError
from .questdb_client import OHLCV, MarketStats, QuestDBClient, QuestDBClientError
from .storage import StorageManager
from .tick_recorder import TickRecorder

_JOURNAL_EXPORTS = {
    "JournalEntry",
    "JournalFilters",
    "JournalStats",
    "TradeJournal",
    "TradeLogger",
    "TradeSummary",
}


def __getattr__(name: str):
    if name in _JOURNAL_EXPORTS:
        value = getattr(import_module("flinttrade_journal"), name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

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
    "LoginActivity",
    "SessionTracker",
    "SecurityTracker",
    # Trade Journal
    "TradeJournal",
    "JournalEntry",
    "JournalFilters",
    "JournalStats",
    # QuestDB — ILP bridge (existing)
    "QuestDBBridge",
    "QuestDBBridgeError",
    # QuestDB — PostgreSQL wire client (new)
    "QuestDBClient",
    "QuestDBClientError",
    "OHLCV",
    "MarketStats",
    # OrderFlow — per-symbol aggregator with IST bins (new)
    "OrderFlowAggregatorV2",
    "FootprintBucketV2",
]
