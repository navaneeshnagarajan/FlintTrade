"""FlintTrade historical package — download, free data, DuckDB pipeline, expiry tracking."""

__version__ = "0.1.0-dev"

from .downloader import DownloadResult, HistoricalDownloader
from .expiry_manager import ContinuousFuturesBar, ExpiryInfo, ExpiryManager
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
]
