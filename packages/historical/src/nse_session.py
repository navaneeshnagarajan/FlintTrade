"""NSE charting API session with cookie pre-warming.

Absorbed from openchart-js audit: NSE's charting.nseindia.com requires a valid
browser session (cookies) before it will serve OHLCV or search data. The
standard approach is to hit the NSE homepage first so the CDN sets the
required session cookies, then use those cookies in subsequent data requests.

This module provides ``NSESession`` — an async-capable wrapper around httpx
that handles:
  - Pre-warming the NSE session (homepage hit to obtain cookies)
  - Browser-like request headers (User-Agent, Referer, Sec-Fetch-* family)
  - Persistent cookie-jar management across requests
  - Historical OHLCV data from charting.nseindia.com
  - Symbol search against the NSE symbol master
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any

logger = logging.getLogger("flinttrade.historical.nse_session")

# ---------------------------------------------------------------------------
# Browser-like headers — mimic Chrome 124 on Linux to pass NSE bot checks
# ---------------------------------------------------------------------------

_BROWSER_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-IN,en-GB;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Linux"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "Referer": "https://www.nseindia.com/",
    "Origin": "https://www.nseindia.com",
    "DNT": "1",
}

# NSE endpoint constants
_NSE_HOME = "https://www.nseindia.com/"
_NSE_CHART_API = "https://charting.nseindia.com/Charts/GetHistoricalData"
_NSE_SEARCH_API = "https://www.nseindia.com/api/search/autocomplete"

# Map FlintTrade interval strings to NSE chart API interval codes
_INTERVAL_MAP: dict[str, str] = {
    "1m": "1",
    "3m": "3",
    "5m": "5",
    "10m": "10",
    "15m": "15",
    "30m": "30",
    "1h": "60",
    "1d": "1D",
    "1w": "1W",
    "1M": "1M",
}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class NSEBar:
    """A single OHLCV bar from NSE charting API."""

    timestamp: str = ""
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: int = 0


@dataclass
class NSEDataResult:
    """Result from an NSE historical data or search request."""

    symbol: str
    bars: list[NSEBar] = field(default_factory=list)
    matches: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""

    @property
    def success(self) -> bool:
        """True if data was retrieved without error."""
        return not self.error

    @property
    def total_bars(self) -> int:
        """Number of OHLCV bars returned."""
        return len(self.bars)


# ---------------------------------------------------------------------------
# NSESession
# ---------------------------------------------------------------------------


class NSESession:
    """HTTP session for NSE charting API with browser-like cookie pre-warming.

    NSE's charting endpoints block requests without valid session cookies. This
    class pre-warms the session by visiting the NSE homepage first (the same
    behaviour a browser exhibits), then uses the resulting cookie jar for all
    subsequent data requests.

    The session is lazy-initialised: the first call to ``get_nse_data`` or
    ``search_symbol`` triggers the pre-warm automatically. Call ``close()``
    when done, or use it as an async context manager::

        async with NSESession() as sess:
            result = await sess.get_nse_data("NIFTY 50", "NSE_INDEX", "1d",
                                             date(2025, 1, 1), date(2025, 12, 31))

    Args:
        timeout: HTTP timeout in seconds (default 30).
        max_retries: Number of retry attempts on transient errors (default 2).
        pre_warm: Whether to hit the NSE homepage to seed cookies. Set to
            ``False`` in tests where cookies are mocked (default True).
    """

    def __init__(
        self,
        timeout: float = 30.0,
        max_retries: int = 2,
        pre_warm: bool = True,
    ) -> None:
        self._timeout = timeout
        self._max_retries = max_retries
        self._pre_warm = pre_warm
        self._client: Any = None  # httpx.AsyncClient
        self._warmed = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def _ensure_client(self) -> Any:
        """Lazy-create the httpx client and pre-warm the NSE session."""
        if self._client is not None:
            return self._client

        try:
            import httpx
        except ImportError:
            raise ImportError("httpx required — pip install httpx")

        self._client = httpx.AsyncClient(
            headers=_BROWSER_HEADERS,
            timeout=self._timeout,
            follow_redirects=True,
        )

        if self._pre_warm and not self._warmed:
            await self._warm_session()

        return self._client

    async def _warm_session(self) -> None:
        """Hit the NSE homepage to obtain session cookies.

        NSE sets several mandatory cookies (nsit, nsiappid, etc.) on the
        homepage response. Without these the charting API returns 401/403.
        """
        try:
            response = await self._client.get(_NSE_HOME)
            response.raise_for_status()
            self._warmed = True
            logger.info(
                "NSE session pre-warmed — %d cookies received",
                len(self._client.cookies),
            )
        except Exception as exc:
            logger.warning("NSE pre-warm failed (will retry on first request): %s", exc)

    async def close(self) -> None:
        """Close the underlying httpx client and release connections."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            self._warmed = False

    async def __aenter__(self) -> "NSESession":
        await self._ensure_client()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_nse_data(
        self,
        symbol: str,
        interval: str,
        start: date,
        end: date,
    ) -> NSEDataResult:
        """Fetch historical OHLCV data from the NSE charting API.

        Args:
            symbol: NSE symbol string, e.g. ``"NIFTY 50"`` or ``"RELIANCE"``.
            interval: Interval string — one of ``"1m"``, ``"5m"``, ``"15m"``,
                ``"30m"``, ``"1h"``, ``"1d"``, ``"1w"``, ``"1M"``.
            start: Inclusive start date for the range.
            end: Inclusive end date for the range.

        Returns:
            :class:`NSEDataResult` with ``.bars`` populated on success.
        """
        client = await self._ensure_client()

        nse_interval = _INTERVAL_MAP.get(interval)
        if not nse_interval:
            return NSEDataResult(
                symbol=symbol,
                error=f"Unsupported interval '{interval}'. "
                      f"Supported: {sorted(_INTERVAL_MAP)}",
            )

        params = {
            "symbol": symbol,
            "time": nse_interval,
            "start": start.strftime("%Y-%m-%d"),
            "end": end.strftime("%Y-%m-%d"),
        }

        for attempt in range(self._max_retries + 1):
            try:
                response = await client.get(_NSE_CHART_API, params=params)
                if response.status_code in (401, 403) and not self._warmed:
                    # Session may have expired — re-warm and retry once
                    logger.info("NSE session expired, re-warming (attempt %d)", attempt + 1)
                    await self._warm_session()
                    continue
                response.raise_for_status()
                payload = response.json()
                bars = self._parse_chart_response(payload)
                logger.info(
                    "NSE chart: %s %s %s→%s — %d bars",
                    symbol, interval, start, end, len(bars),
                )
                return NSEDataResult(symbol=symbol, bars=bars)

            except Exception as exc:
                if attempt == self._max_retries:
                    logger.error("NSE chart request failed after %d attempts: %s", attempt + 1, exc)
                    return NSEDataResult(symbol=symbol, error=str(exc))
                logger.warning("NSE chart attempt %d failed: %s — retrying", attempt + 1, exc)

        return NSEDataResult(symbol=symbol, error="Max retries exceeded")

    async def search_symbol(self, query: str) -> NSEDataResult:
        """Search NSE symbols by name or ticker fragment.

        Args:
            query: Partial symbol name or description, e.g. ``"NIFTY"`` or
                ``"Reliance"``.

        Returns:
            :class:`NSEDataResult` with ``.matches`` as a list of dicts, each
            containing at least ``"symbol"`` and ``"name"`` keys.
        """
        if not query or not query.strip():
            return NSEDataResult(symbol=query, error="Empty search query")

        client = await self._ensure_client()

        try:
            response = await client.get(
                _NSE_SEARCH_API,
                params={"q": query.strip(), "type": "equity,index,futures,options"},
            )
            response.raise_for_status()
            payload = response.json()
            matches = self._parse_search_response(payload)
            logger.info("NSE search '%s' — %d matches", query, len(matches))
            return NSEDataResult(symbol=query, matches=matches)

        except Exception as exc:
            logger.error("NSE search failed for '%s': %s", query, exc)
            return NSEDataResult(symbol=query, error=str(exc))

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_chart_response(payload: Any) -> list[NSEBar]:
        """Parse NSE charting API JSON into NSEBar list.

        NSE returns a list of candles, each as a list:
        ``[timestamp_ms, open, high, low, close, volume]``
        or as a dict with those keys. Both formats are handled.
        """
        if not payload:
            return []

        # Handle wrapped response: {"data": [...]} or bare list
        candles = payload if isinstance(payload, list) else payload.get("data", [])
        bars: list[NSEBar] = []

        for candle in candles:
            try:
                if isinstance(candle, (list, tuple)) and len(candle) >= 5:
                    ts_raw, o, h, lo, c = candle[0], candle[1], candle[2], candle[3], candle[4]
                    vol = int(candle[5]) if len(candle) > 5 else 0
                    bars.append(NSEBar(
                        timestamp=str(ts_raw),
                        open=float(o),
                        high=float(h),
                        low=float(lo),
                        close=float(c),
                        volume=vol,
                    ))
                elif isinstance(candle, dict):
                    bars.append(NSEBar(
                        timestamp=str(candle.get("t") or candle.get("timestamp", "")),
                        open=float(candle.get("o") or candle.get("open", 0)),
                        high=float(candle.get("h") or candle.get("high", 0)),
                        low=float(candle.get("l") or candle.get("low", 0)),
                        close=float(candle.get("c") or candle.get("close", 0)),
                        volume=int(candle.get("v") or candle.get("volume", 0)),
                    ))
            except (TypeError, ValueError, IndexError) as exc:
                logger.debug("Skipping malformed candle: %s — %s", candle, exc)

        return bars

    @staticmethod
    def _parse_search_response(payload: Any) -> list[dict[str, Any]]:
        """Parse NSE search autocomplete response into a flat list of matches."""
        if not payload:
            return []

        # NSE search returns {"symbols": [...], ...}
        items = payload if isinstance(payload, list) else payload.get("symbols", [])
        matches: list[dict[str, Any]] = []

        for item in items:
            if isinstance(item, dict):
                matches.append({
                    "symbol": item.get("symbol") or item.get("id", ""),
                    "name": item.get("symbolName") or item.get("name", ""),
                    "type": item.get("identifier") or item.get("type", ""),
                })

        return matches
