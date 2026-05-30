"""FlintTrade historical package — download, free data, DuckDB pipeline, expiry tracking."""

from flinttrade_core.version import APP_VERSION

__version__ = APP_VERSION

from .cache import CacheEntry, CacheResult, OHLCVCache
from .data_provider import (
    DataProvider,
    OpenAlgoProvider,
    OpenChartProvider,
    ProviderBar,
    ProviderRegistry,
    ProviderResult,
    YFinanceProvider,
    normalise_interval,
)
from .downloader import DownloadResult, HistoricalDownloader
from .expiry_collector import ExpiryDataCollector, ExpiryDataRecord, ExpiryDataResult
from .expiry_manager import ContinuousFuturesBar, ExpiryInfo, ExpiryManager
from .expiry_tracker import ExpiryTracker
from .free_data import FreeDataSource
from .normaliser import NormalisedBar, NormaliseResult, OHLCVNormaliser, normalise
from .nse_session import NSEBar, NSEDataResult, NSESession
from .pipeline import DataPipeline

__all__ = [
    # Downloader
    "HistoricalDownloader",
    "DownloadResult",
    # Free data
    "FreeDataSource",
    # Pipeline
    "DataPipeline",
    # Expiry management
    "ExpiryManager",
    "ExpiryInfo",
    "ContinuousFuturesBar",
    "ExpiryDataCollector",
    "ExpiryDataRecord",
    "ExpiryDataResult",
    "ExpiryTracker",
    # NSE session
    "NSESession",
    "NSEBar",
    "NSEDataResult",
    # Data provider abstraction (new)
    "DataProvider",
    "OpenAlgoProvider",
    "OpenChartProvider",
    "YFinanceProvider",
    "ProviderBar",
    "ProviderResult",
    "ProviderRegistry",
    "normalise_interval",
    # Normaliser (new)
    "OHLCVNormaliser",
    "NormalisedBar",
    "NormaliseResult",
    "normalise",
    # Cache (new)
    "OHLCVCache",
    "CacheEntry",
    "CacheResult",
]
