"""Data provider abstraction for historical OHLCV data.

Defines a Protocol for data providers and a registry with fallback chain:
    1. OpenAlgo (primary — broker API via OpenAlgoClient)
    2. NSEData / OpenChart (free NSE/NFO data, no API key required)
    3. CommodityData / yfinance (free MCX commodity data)

Adapted patterns from:
- historify: OpenAlgo integration, rate limiting, interval normalisation
- openchart: NSE charting API, segment/exchange mapping
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger("flinttrade.historical.data_provider")

# ---------------------------------------------------------------------------
# Canonical interval map — normalise user-supplied strings to OpenAlgo format
# Adapted from historify convert_interval_format() and openchart interval_map
# ---------------------------------------------------------------------------

INTERVAL_MAP: dict[str, str] = {
    "1m": "1m",
    "2m": "2m",
    "3m": "3m",
    "5m": "5m",
    "10m": "10m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1h",
    "1d": "D",
    "D": "D",
    "1W": "1W",
    "1M": "1M",
}

INTRADAY_INTERVALS: frozenset[str] = frozenset(
    {"1m", "2m", "3m", "5m", "10m", "15m", "30m", "1h"}
)

# Exchanges supported natively via OpenAlgo
OPENALGO_EXCHANGES: frozenset[str] = frozenset(
    {"NSE", "BSE", "NFO", "BFO", "CDS", "BCD", "MCX", "NCDEX"}
)

# Exchanges supported via free NSE/NFO data (openchart)
FREE_NSE_EXCHANGES: frozenset[str] = frozenset({"NSE", "NFO"})


def normalise_interval(interval: str) -> str:
    """Return the canonical OpenAlgo interval string.

    Args:
        interval: User-supplied interval string (e.g. "1d", "D", "1h").

    Returns:
        Canonical interval string (e.g. "D", "1h").

    Raises:
        ValueError: If the interval is not recognised.
    """
    canonical = INTERVAL_MAP.get(interval)
    if canonical is None:
        raise ValueError(
            f"Unrecognised interval: {interval!r}. "
            f"Supported: {sorted(INTERVAL_MAP)}"
        )
    return canonical


# ---------------------------------------------------------------------------
# Common result type
# ---------------------------------------------------------------------------


@dataclass
class ProviderBar:
    """Normalised OHLCV bar from any provider.

    All providers normalise their output to this type before returning it,
    so consumers never need to care which provider supplied the data.
    """

    timestamp: str = ""
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: int = 0
    oi: int = 0
    source: str = ""


@dataclass
class ProviderResult:
    """Result from a data provider fetch.

    Attributes:
        symbol: Trading symbol.
        exchange: Exchange code.
        interval: Canonical interval string.
        provider: Name of the provider that supplied the data.
        bars: Ordered list of OHLCV bars (oldest first).
        error: Non-empty if the fetch failed.
    """

    symbol: str
    exchange: str
    interval: str
    provider: str = ""
    bars: list[ProviderBar] = field(default_factory=list)
    error: str = ""

    @property
    def total_bars(self) -> int:
        """Number of bars returned."""
        return len(self.bars)

    @property
    def success(self) -> bool:
        """True when at least one bar was returned and no error occurred."""
        return self.total_bars > 0 and not self.error


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class DataProvider(Protocol):
    """Protocol that all historical data providers must satisfy.

    A provider accepts a symbol, exchange, interval, and date range and
    returns a ``ProviderResult``. Providers are synchronous at the protocol
    boundary — the OpenAlgo async client is wrapped internally.
    """

    @property
    def name(self) -> str:
        """Short identifier for this provider (e.g. "openalgo", "openchart")."""
        ...

    def supports(self, exchange: str) -> bool:
        """Return True if this provider can supply data for the given exchange.

        Args:
            exchange: Exchange code (e.g. "NSE", "MCX").
        """
        ...

    def fetch(
        self,
        symbol: str,
        exchange: str,
        interval: str,
        start_date: str,
        end_date: str,
    ) -> ProviderResult:
        """Fetch historical OHLCV data.

        Args:
            symbol: e.g. "RELIANCE", "NIFTY26MARFUT"
            exchange: e.g. "NSE", "NFO", "MCX"
            interval: e.g. "5m", "1h", "D" (canonical or user-friendly)
            start_date: "YYYY-MM-DD"
            end_date: "YYYY-MM-DD"

        Returns:
            ProviderResult with bars sorted oldest-first.
        """
        ...


# ---------------------------------------------------------------------------
# OpenAlgo provider
# ---------------------------------------------------------------------------


class OpenAlgoProvider:
    """Primary data provider — wraps OpenAlgoClient async history endpoint.

    Uses the existing HistoricalDownloader for automatic date chunking so
    brokers' 30-day intraday limits are transparently handled.

    Args:
        client: An ``OpenAlgoClient`` instance.
        chunk_days_intraday: Max days per API call for intraday intervals.
        chunk_days_daily: Max days per API call for daily/weekly intervals.
    """

    def __init__(
        self,
        client: Any,
        chunk_days_intraday: int = 30,
        chunk_days_daily: int = 365,
    ) -> None:
        self._client = client
        self._chunk_intraday = chunk_days_intraday
        self._chunk_daily = chunk_days_daily

    @property
    def name(self) -> str:
        """Provider identifier."""
        return "openalgo"

    def supports(self, exchange: str) -> bool:
        """OpenAlgo supports all standard Indian exchanges.

        Args:
            exchange: Exchange code.

        Returns:
            True for NSE, BSE, NFO, BFO, CDS, BCD, MCX, NCDEX.
        """
        return exchange.upper() in OPENALGO_EXCHANGES

    def fetch(
        self,
        symbol: str,
        exchange: str,
        interval: str,
        start_date: str,
        end_date: str,
    ) -> ProviderResult:
        """Fetch via OpenAlgo history API with automatic chunking.

        Args:
            symbol: Trading symbol.
            exchange: Exchange code.
            interval: Data interval (canonical or user-friendly).
            start_date: Start date "YYYY-MM-DD".
            end_date: End date "YYYY-MM-DD".

        Returns:
            ProviderResult with OpenAlgo bars.
        """
        canonical = normalise_interval(interval)
        result = ProviderResult(
            symbol=symbol,
            exchange=exchange,
            interval=canonical,
            provider=self.name,
        )

        try:
            from .downloader import HistoricalDownloader

            dl = HistoricalDownloader(
                self._client,
                chunk_days_intraday=self._chunk_intraday,
                chunk_days_daily=self._chunk_daily,
            )

            # HistoricalDownloader.download is synchronous — it calls the
            # async client via asyncio.run() internally. When already inside
            # an event loop (e.g. FastAPI), callers should use the async
            # variant in downloader.py directly.
            download = dl.download(symbol, exchange, canonical, start_date, end_date)

            if download.errors:
                for err in download.errors:
                    logger.warning("OpenAlgo provider partial error: %s", err)

            result.bars = [
                ProviderBar(
                    timestamp=b.timestamp,
                    open=b.open,
                    high=b.high,
                    low=b.low,
                    close=b.close,
                    volume=b.volume,
                    oi=0,
                    source=self.name,
                )
                for b in download.bars
            ]

            if download.errors and not result.bars:
                result.error = "; ".join(download.errors)

        except Exception as exc:
            result.error = str(exc)
            logger.error(
                "OpenAlgo provider error for %s %s %s: %s",
                symbol, exchange, canonical, exc,
            )

        return result


# ---------------------------------------------------------------------------
# OpenChart (free NSE/NFO) provider
# ---------------------------------------------------------------------------


class OpenChartProvider:
    """Free NSE/NFO data provider via the openchart library.

    No API key required. Covers NSE equities, indices, futures, and options.
    MCX and other exchanges are not supported — the registry falls back to
    OpenAlgo for those.

    Adapted from openchart core.py patterns: lazy cookie initialisation,
    segment-based symbol resolution, intraday cutoff at 15:29:59.
    """

    @property
    def name(self) -> str:
        """Provider identifier."""
        return "openchart"

    def supports(self, exchange: str) -> bool:
        """OpenChart only covers NSE and NFO.

        Args:
            exchange: Exchange code.

        Returns:
            True for NSE and NFO only.
        """
        return exchange.upper() in FREE_NSE_EXCHANGES

    def fetch(
        self,
        symbol: str,
        exchange: str,
        interval: str,
        start_date: str,
        end_date: str,
    ) -> ProviderResult:
        """Fetch via the free openchart library.

        Args:
            symbol: NSE trading symbol.
            exchange: "NSE" or "NFO".
            interval: Data interval.
            start_date: Start date "YYYY-MM-DD".
            end_date: End date "YYYY-MM-DD".

        Returns:
            ProviderResult with openchart bars.
        """
        canonical = normalise_interval(interval)
        result = ProviderResult(
            symbol=symbol,
            exchange=exchange,
            interval=canonical,
            provider=self.name,
        )

        try:
            from .free_data import NSEData

            nse = NSEData()
            free_result = nse.historical(symbol, exchange, start_date, end_date, interval)

            if not free_result.success:
                result.error = free_result.error or "No data from openchart"
                return result

            result.bars = [
                ProviderBar(
                    timestamp=b.timestamp,
                    open=b.open,
                    high=b.high,
                    low=b.low,
                    close=b.close,
                    volume=b.volume,
                    oi=b.oi,
                    source=self.name,
                )
                for b in free_result.bars
            ]

        except ImportError:
            result.error = "openchart not installed — pip install openchart"
        except Exception as exc:
            result.error = str(exc)
            logger.error(
                "OpenChart provider error for %s %s: %s", symbol, exchange, exc,
            )

        return result


# ---------------------------------------------------------------------------
# yfinance commodity provider
# ---------------------------------------------------------------------------


class YFinanceProvider:
    """Free commodity data provider via yfinance.

    Covers MCX commodities (GOLD, SILVER, CRUDEOIL, NATURALGAS, COPPER, ZINC)
    with optional INR conversion.

    Adapted from historify patterns: approximate INR conversion via USDINR=X
    with fallback rate, and the yfinance ticker mapping table.
    """

    @property
    def name(self) -> str:
        """Provider identifier."""
        return "yfinance"

    def supports(self, exchange: str) -> bool:
        """yfinance supports MCX commodity symbols only.

        Args:
            exchange: Exchange code.

        Returns:
            True for MCX only.
        """
        return exchange.upper() == "MCX"

    def fetch(
        self,
        symbol: str,
        exchange: str,
        interval: str,
        start_date: str,
        end_date: str,
    ) -> ProviderResult:
        """Fetch MCX commodity data via yfinance.

        Args:
            symbol: Commodity code e.g. "GOLD", "CRUDEOIL".
            exchange: Must be "MCX".
            interval: Data interval.
            start_date: Start date "YYYY-MM-DD".
            end_date: End date "YYYY-MM-DD".

        Returns:
            ProviderResult with INR-converted commodity bars.
        """
        canonical = normalise_interval(interval)
        result = ProviderResult(
            symbol=symbol,
            exchange=exchange,
            interval=canonical,
            provider=self.name,
        )

        try:
            from .free_data import CommodityData

            mcx = CommodityData()
            free_result = mcx.historical(symbol, start_date, end_date, interval)

            if not free_result.success:
                result.error = free_result.error or "No data from yfinance"
                return result

            result.bars = [
                ProviderBar(
                    timestamp=b.timestamp,
                    open=b.open,
                    high=b.high,
                    low=b.low,
                    close=b.close,
                    volume=b.volume,
                    oi=0,
                    source=self.name,
                )
                for b in free_result.bars
            ]

        except Exception as exc:
            result.error = str(exc)
            logger.error(
                "yfinance provider error for %s %s: %s", symbol, exchange, exc,
            )

        return result


# ---------------------------------------------------------------------------
# Provider registry with fallback chain
# ---------------------------------------------------------------------------


class ProviderRegistry:
    """Registry that routes fetch requests to the correct provider with fallback.

    Default chain (ordered by priority):
        1. OpenAlgoProvider — primary, all exchanges, requires API key
        2. OpenChartProvider — free fallback for NSE/NFO
        3. YFinanceProvider — free fallback for MCX commodities

    Usage::

        registry = ProviderRegistry(openalgo_client)
        result = registry.fetch("RELIANCE", "NSE", "5m", "2026-01-01", "2026-03-31")

        # With fallback disabled (strict mode):
        result = registry.fetch(..., fallback=False)

    Args:
        openalgo_client: Initialised ``OpenAlgoClient``. Pass None to skip the
            primary provider (useful when only free data sources are needed).
        extra_providers: Additional providers inserted before the built-in
            free providers. Useful for testing or custom data sources.
    """

    def __init__(
        self,
        openalgo_client: Any | None = None,
        extra_providers: list[DataProvider] | None = None,
    ) -> None:
        self._providers: list[DataProvider] = []

        if openalgo_client is not None:
            self._providers.append(OpenAlgoProvider(openalgo_client))

        if extra_providers:
            self._providers.extend(extra_providers)

        # Free providers are always available as fallback
        self._providers.append(OpenChartProvider())
        self._providers.append(YFinanceProvider())

    @property
    def providers(self) -> list[DataProvider]:
        """Ordered list of registered providers."""
        return list(self._providers)

    def register(self, provider: DataProvider, *, position: int = -1) -> None:
        """Add a provider to the registry.

        Args:
            provider: Provider instance implementing the DataProvider protocol.
            position: Insert position. -1 appends to end (lowest priority).
        """
        if position == -1:
            self._providers.append(provider)
        else:
            self._providers.insert(position, provider)

    def fetch(
        self,
        symbol: str,
        exchange: str,
        interval: str,
        start_date: str,
        end_date: str,
        *,
        fallback: bool = True,
    ) -> ProviderResult:
        """Fetch historical data using the first suitable provider.

        Tries each registered provider in order. If ``fallback=True``,
        moves to the next provider when the current one fails or returns no
        data. Returns the first successful result.

        Args:
            symbol: Trading symbol.
            exchange: Exchange code.
            interval: Data interval.
            start_date: Start date "YYYY-MM-DD".
            end_date: End date "YYYY-MM-DD".
            fallback: When True (default), try the next provider on failure.

        Returns:
            ProviderResult from the first successful provider. If all providers
            fail, returns the last error result.
        """
        canonical = normalise_interval(interval)
        last_result = ProviderResult(
            symbol=symbol,
            exchange=exchange,
            interval=canonical,
            error="No providers available for this exchange",
        )

        suitable = [p for p in self._providers if p.supports(exchange)]
        if not suitable:
            logger.warning(
                "No provider supports exchange %s for %s", exchange, symbol,
            )
            return last_result

        for provider in suitable:
            logger.info(
                "Trying provider %r for %s %s %s (%s → %s)",
                provider.name, symbol, exchange, canonical, start_date, end_date,
            )
            result = provider.fetch(symbol, exchange, interval, start_date, end_date)

            if result.success:
                logger.info(
                    "Provider %r returned %d bars for %s %s",
                    provider.name, result.total_bars, symbol, exchange,
                )
                return result

            logger.warning(
                "Provider %r failed for %s %s: %s",
                provider.name, symbol, exchange, result.error,
            )
            last_result = result

            if not fallback:
                break

        return last_result

    def fetch_batch(
        self,
        requests: list[dict[str, str]],
        interval: str,
        start_date: str,
        end_date: str,
        *,
        fallback: bool = True,
    ) -> list[ProviderResult]:
        """Fetch historical data for multiple symbols.

        Each entry in ``requests`` must have "symbol" and "exchange" keys.

        Args:
            requests: List of dicts with "symbol" and "exchange".
            interval: Data interval applied to all symbols.
            start_date: Start date "YYYY-MM-DD".
            end_date: End date "YYYY-MM-DD".
            fallback: Passed through to each fetch() call.

        Returns:
            List of ProviderResult in the same order as ``requests``.
        """
        return [
            self.fetch(
                req["symbol"],
                req.get("exchange", "NSE"),
                interval,
                start_date,
                end_date,
                fallback=fallback,
            )
            for req in requests
        ]
