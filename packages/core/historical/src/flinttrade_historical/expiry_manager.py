"""Derivative expiry tracking and continuous futures construction.

Tracks expiry dates for all derivative segments:
- NFO: NIFTY, BANKNIFTY weekly; monthly stock options
- BFO: SENSEX, BANKEX weekly
- CDS: USDINR, EURINR monthly
- MCX: commodity-specific expiries

Uses OpenAlgo /api/v1/expiry to fetch available expiry dates.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from flinttrade_core.openalgo_client import OpenAlgoClient

from .downloader import resolve_maybe_awaitable

logger = logging.getLogger("flinttrade.historical.expiry")


@dataclass
class ExpiryInfo:
    """Expiry dates for a derivative symbol."""

    symbol: str
    exchange: str
    expiry_dates: list[str] = field(default_factory=list)  # YYMMDD format from OpenAlgo

    @property
    def count(self) -> int:
        return len(self.expiry_dates)

    def nearest(self, reference_date: date | None = None) -> str | None:
        """Get the nearest future expiry from a reference date."""
        ref = reference_date or date.today()
        for exp_date, exp_str in _dated_expiries(self.expiry_dates):
            if exp_date >= ref:
                return exp_str
        return None

    def weekly(self) -> list[str]:
        """Filter to weekly expiries (within 7 days of each other)."""
        dated = _dated_expiries(self.expiry_dates)
        if len(dated) < 2:
            return [exp_str for _, exp_str in dated]
        weekly = [dated[0][1]]
        for (previous, _), (current, exp_str) in zip(dated, dated[1:], strict=True):
            if (current - previous).days <= 8:
                weekly.append(exp_str)
        return weekly

    def monthly(self) -> list[str]:
        """Filter to monthly expiries (last Thursday of each month typically)."""
        dated = _dated_expiries(self.expiry_dates)
        monthly: list[tuple[date, str]] = []
        seen_months: set[tuple[int, int]] = set()
        # Walk backwards — the last expiry each month is the monthly.
        for expiry_date, exp_str in reversed(dated):
            month_key = (expiry_date.year, expiry_date.month)
            if month_key not in seen_months:
                seen_months.add(month_key)
                monthly.append((expiry_date, exp_str))
        return [exp_str for _, exp_str in reversed(monthly)]


def _parse_expiry_date(exp_str: str) -> date:
    """Parse historical and official OpenAlgo expiry strings to a date."""
    from flinttrade_core.symbol_utils import parse_expiry

    text = str(exp_str or "").strip()
    try:
        return parse_expiry(text, formats=("YYMMDD", "ISO"))
    except ValueError:
        try:
            return datetime.strptime(text.upper(), "%d-%b-%y").date()
        except ValueError as exc:
            raise ValueError(f"Invalid expiry date: {exp_str!r}") from exc


def _dated_expiries(expiry_dates: list[str]) -> list[tuple[date, str]]:
    """Return valid expiry strings sorted by their parsed calendar date."""
    dated: list[tuple[date, str]] = []
    for exp_str in expiry_dates:
        try:
            dated.append((_parse_expiry_date(exp_str), exp_str))
        except ValueError:
            continue
    return sorted(dated, key=lambda item: item[0])


@dataclass
class ContinuousFuturesBar:
    """A single bar in a continuous futures series with roll info."""

    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: int = 0
    oi: int = 0
    contract: str = ""  # The specific contract symbol, e.g. "NIFTY26MARFUT"
    is_roll: bool = False  # True on the bar where we rolled to next contract


class ExpiryManager:
    """Track derivative expiries and construct continuous futures.

    Usage::

        mgr = ExpiryManager(client)
        info = mgr.get_expiries("NIFTY", "NFO", instrumenttype="options")
        nearest = info.nearest()
        monthly = info.monthly()

        # Continuous futures (rolls on expiry day)
        bars = mgr.build_continuous_futures("NIFTY", "NFO", "1d", "2025-01-01", "2025-12-31")
    """

    def __init__(self, client: OpenAlgoClient) -> None:
        self._client = client
        self._cache: dict[str, ExpiryInfo] = {}

    def get_expiries(
        self,
        symbol: str,
        exchange: str = "NFO",
        *,
        instrumenttype: str,
    ) -> ExpiryInfo:
        """Fetch expiry dates from OpenAlgo /api/v1/expiry.

        Results are cached per (symbol, exchange, instrumenttype).
        """
        cache_key = f"{exchange}:{symbol}:{instrumenttype}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        info = ExpiryInfo(symbol=symbol, exchange=exchange)

        try:
            data = resolve_maybe_awaitable(
                self._client.expiry(symbol, exchange, instrumenttype=instrumenttype),
                caller="ExpiryManager.get_expiries",
            )
            # OpenAlgo returns expiries in various formats depending on broker
            if isinstance(data, dict):
                nested = data.get("data")
                if isinstance(nested, list):
                    expiry_list = nested
                elif isinstance(nested, dict):
                    expiry_list = nested.get("expiry", nested.get("expiries", []))
                else:
                    expiry_list = data.get("expiry", data.get("expiries", []))
            elif isinstance(data, list):
                expiry_list = data
            else:
                expiry_list = []

            info.expiry_dates = [str(e) for e in expiry_list]
            logger.info(
                "Loaded %d expiries for %s:%s", info.count, exchange, symbol,
            )
        except Exception as exc:
            logger.error("Failed to fetch expiries for %s:%s: %s", exchange, symbol, exc)

        self._cache[cache_key] = info
        return info

    def clear_cache(self) -> None:
        """Clear the expiry cache (e.g. after market hours to refresh)."""
        self._cache.clear()

    def nearest_expiry(
        self,
        symbol: str,
        exchange: str = "NFO",
        reference_date: date | None = None,
        *,
        instrumenttype: str,
    ) -> str | None:
        """Get the nearest expiry date for a symbol."""
        info = self.get_expiries(symbol, exchange, instrumenttype=instrumenttype)
        return info.nearest(reference_date)

    def build_continuous_futures(
        self,
        underlying: str,
        exchange: str,
        interval: str,
        start_date: str,
        end_date: str,
    ) -> list[ContinuousFuturesBar]:
        """Build a continuous futures series by rolling on expiry day.

        Algorithm:
        1. Get all expiry dates for the underlying
        2. For each contract period (from one expiry to the next):
           - Download OHLCV for that specific FUT contract
        3. Stitch together with roll markers

        The contract symbol format follows OpenAlgo conventions:
        e.g. "NIFTY26MARFUT", "BANKNIFTY26MARFUT"
        """
        info = self.get_expiries(underlying, exchange, instrumenttype="futures")
        if not info.expiry_dates:
            logger.warning("No expiries found for %s:%s", exchange, underlying)
            return []

        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)

        # Filter to expiries within our range (plus one before for overlap).
        # Official dashed values such as 26-MAR-26 / 02-APR-26 sort April
        # first when compared as strings, so use parsed calendar order.
        relevant: list[str] = []
        for exp_date, exp_str in _dated_expiries(info.expiry_dates):
            if exp_date >= start - timedelta(days=60):
                relevant.append(exp_str)
            if exp_date > end:
                break

        if not relevant:
            return []

        continuous: list[ContinuousFuturesBar] = []
        prev_expiry_date = start

        for i, exp_str in enumerate(relevant):
            try:
                exp_date = _parse_expiry_date(exp_str)
            except ValueError:
                continue

            # Build contract symbol — convention: {UNDERLYING}{YY}{MON}FUT
            contract_symbol = self._build_futures_symbol(underlying, exp_str)

            # Date range for this contract: from prev expiry+1 to this expiry
            c_start = prev_expiry_date if i == 0 else prev_expiry_date + timedelta(days=1)
            c_end = min(exp_date, end)

            if c_start > end or c_start > c_end:
                break

            try:
                bars = resolve_maybe_awaitable(
                    self._client.history(
                        symbol=contract_symbol,
                        exchange=exchange,
                        interval=interval,
                        start_date=c_start.isoformat(),
                        end_date=c_end.isoformat(),
                    ),
                    caller="ExpiryManager.build_continuous_futures",
                )

                contract_bars = list(bars or [])
                is_first = True
                for bar in contract_bars:
                    continuous.append(ContinuousFuturesBar(
                        timestamp=bar.timestamp,
                        open=bar.open,
                        high=bar.high,
                        low=bar.low,
                        close=bar.close,
                        volume=bar.volume,
                        contract=contract_symbol,
                        is_roll=(i > 0 and is_first),
                    ))
                    is_first = False

                logger.info(
                    "Continuous futures: %s %s to %s — %d bars",
                    contract_symbol, c_start, c_end, len(contract_bars),
                )
            except Exception as exc:
                logger.warning(
                    "Failed to fetch %s: %s", contract_symbol, exc,
                )

            prev_expiry_date = exp_date

        return continuous

    @staticmethod
    def _build_futures_symbol(underlying: str, expiry_str: str) -> str:
        """Build futures symbol from underlying and expiry string.

        Input expiry: "260326" (YYMMDD)
        Output: "NIFTY26MARFUT"
        """
        _MONTH_MAP = {
            1: "JAN", 2: "FEB", 3: "MAR", 4: "APR", 5: "MAY", 6: "JUN",
            7: "JUL", 8: "AUG", 9: "SEP", 10: "OCT", 11: "NOV", 12: "DEC",
        }
        try:
            d = _parse_expiry_date(expiry_str)
            yy = f"{d.year % 100:02d}"
            mon = _MONTH_MAP[d.month]
            return f"{underlying}{yy}{mon}FUT"
        except (ValueError, KeyError):
            # Fallback: just append FUT
            return f"{underlying}FUT"
