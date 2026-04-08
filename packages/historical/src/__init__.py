"""FlintTrade historical package — download, free data, DuckDB pipeline, expiry tracking."""

__version__ = "0.1.0-alpha"

from .downloader import DownloadResult, HistoricalDownloader
from .expiry_collector import ExpiryDataCollector, ExpiryDataRecord, ExpiryDataResult
from .expiry_manager import ContinuousFuturesBar, ExpiryInfo, ExpiryManager
from .expiry_tracker import ExpiryTracker
from .free_data import FreeDataSource
from .pipeline import DataPipeline

__all__ = [
    "HistoricalDownloader",
    "DownloadResult",
    "FreeDataSource",
    "DataPipeline",
    "ExpiryManager",
    "ExpiryInfo",
    "ContinuousFuturesBar",
    "ExpiryDataCollector",
    "ExpiryDataRecord",
    "ExpiryDataResult",
    "ExpiryTracker",
]
