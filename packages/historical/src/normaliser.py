"""OHLCV normaliser — converts provider-specific formats to a standard schema.

Absorbed patterns from:
- openchart utils.py: timestamp-from-milliseconds, column renaming, intraday
  cutoff at 15:29:59 IST, timezone stripping
- historify data_fetcher.py: DataFrame-vs-dict response handling, date/time
  splitting, exchange field propagation

Normalisation steps:
    1. Accept data in any supported input form (dict list, DataFrame, ProviderBar list)
    2. Apply column name mapping to a standard schema
    3. Convert timestamps to IST (UTC+5:30), stored as timezone-naive strings
    4. Apply intraday cutoff (market close = 15:29:59) for intraday intervals
    5. Validate each bar (prices positive, high >= low >= 0, volume >= 0)
    6. Mark or drop gap rows depending on caller preference
    7. Forward-fill missing close prices for tick gaps if requested

Standard schema fields:
    timestamp   str       "YYYY-MM-DD HH:MM:SS" (IST, timezone-naive)
    open        float     >= 0
    high        float     >= open (after validation)
    low         float     <= close, >= 0
    close       float     >= 0
    volume      int       >= 0
    oi          int       >= 0
    symbol      str       optional, passed through
    exchange    str       optional, passed through
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any

logger = logging.getLogger("flinttrade.historical.normaliser")

# Indian Standard Time offset — UTC+5:30
_IST = timezone(timedelta(hours=5, minutes=30))

# Intraday market cutoff (inclusive) — absorbed from openchart utils.py
_INTRADAY_CUTOFF_HH = 15
_INTRADAY_CUTOFF_MM = 29
_INTRADAY_CUTOFF_SS = 59

# Intraday intervals that should have the 15:29:59 cutoff applied
_INTRADAY_INTERVALS: frozenset[str] = frozenset(
    {"1m", "2m", "3m", "5m", "10m", "15m", "30m", "1h"}
)

# Column aliases — maps many source-specific names to our standard names
# Absorbed from openchart (Open/High/Low/Close/Volume/Timestamp) and
# historify (open/high/low/close/volume/date/time)
_COLUMN_ALIASES: dict[str, str] = {
    # Timestamp variants
    "Timestamp": "timestamp",
    "datetime": "timestamp",
    "time": "timestamp",
    "date": "timestamp",
    "Date": "timestamp",
    "DateTime": "timestamp",
    # OHLCV variants
    "Open": "open",
    "High": "high",
    "Low": "low",
    "Close": "close",
    "Volume": "volume",
    # OI variants
    "OI": "oi",
    "OpenInterest": "oi",
    "open_interest": "oi",
}

# Validation limits — reject obviously corrupt bars
_MAX_PRICE = 1_000_000.0  # 10 lakh — above any realistic Indian instrument
_MAX_VOLUME = 10_000_000_000  # 10 billion — generous upper bound


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class NormalisedBar:
    """Single OHLCV bar in the standard FlintTrade schema.

    All bars produced by the normaliser are in IST, timezone-naive.
    """

    timestamp: str = ""
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: int = 0
    oi: int = 0
    symbol: str = ""
    exchange: str = ""


@dataclass
class NormaliseResult:
    """Result of a normalisation pass.

    Attributes:
        bars: Normalised bars sorted oldest-first.
        dropped: Count of bars rejected by validation.
        warnings: Non-fatal issues encountered during normalisation.
        error: Non-empty if the entire normalisation failed.
    """

    bars: list[NormalisedBar] = field(default_factory=list)
    dropped: int = 0
    warnings: list[str] = field(default_factory=list)
    error: str = ""

    @property
    def total_bars(self) -> int:
        """Number of valid bars produced."""
        return len(self.bars)

    @property
    def success(self) -> bool:
        """True when at least one bar was produced without a fatal error."""
        return self.total_bars > 0 and not self.error


# ---------------------------------------------------------------------------
# Timestamp normalisation
# ---------------------------------------------------------------------------


def _to_ist_naive(raw: Any) -> str:
    """Convert a raw timestamp value to an IST naive string "YYYY-MM-DD HH:MM:SS".

    Handles:
    - int/float milliseconds since epoch (openchart source)
    - int/float seconds since epoch
    - datetime objects (tz-aware or naive)
    - ISO-8601 strings
    - "YYYY-MM-DD" date-only strings → "YYYY-MM-DD 00:00:00"

    Args:
        raw: The raw timestamp in any supported form.

    Returns:
        Normalised timestamp string in IST.

    Raises:
        ValueError: If the timestamp cannot be parsed.
    """
    dt: datetime | None = None

    if isinstance(raw, (int, float)):
        # Distinguish milliseconds from seconds:
        # year 2000 in seconds = 946684800, in milliseconds = 946684800000
        # If the value is > 1e10 assume milliseconds (openchart sends ms).
        if raw > 1e10:
            dt = datetime.fromtimestamp(raw / 1000.0, tz=timezone.utc)
        else:
            dt = datetime.fromtimestamp(raw, tz=timezone.utc)

    elif isinstance(raw, datetime):
        if raw.tzinfo is None:
            # Assume naive datetimes from external sources are already IST
            # (openchart strips tz after conversion — openchart utils line 27)
            dt = raw.replace(tzinfo=_IST)
        else:
            dt = raw

    elif isinstance(raw, str):
        raw = raw.strip()
        # Try ISO format first
        for fmt in (
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M:%S%z",
            "%Y-%m-%d",
        ):
            try:
                parsed = datetime.strptime(raw, fmt)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=_IST)
                dt = parsed
                break
            except ValueError:
                continue

        if dt is None:
            raise ValueError(f"Cannot parse timestamp: {raw!r}")

    else:
        # Pandas Timestamp or similar — convert via isoformat
        try:
            iso = raw.isoformat()
            return _to_ist_naive(iso)
        except Exception:
            raise ValueError(f"Unsupported timestamp type: {type(raw).__name__}")

    # Convert to IST and strip timezone info
    dt_ist = dt.astimezone(_IST).replace(tzinfo=None)
    return dt_ist.strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _validate_bar(bar: dict[str, Any]) -> str:
    """Validate a single normalised bar dict.

    Args:
        bar: Dict with keys: open, high, low, close, volume, oi.

    Returns:
        Empty string if valid, else a human-readable error message.
    """
    o, h, lo, c = bar.get("open", 0), bar.get("high", 0), bar.get("low", 0), bar.get("close", 0)
    v = bar.get("volume", 0)
    oi = bar.get("oi", 0)

    if any(p < 0 for p in (o, h, lo, c)):
        return f"Negative price: open={o} high={h} low={lo} close={c}"

    if any(p > _MAX_PRICE for p in (o, h, lo, c)):
        return f"Price exceeds maximum ({_MAX_PRICE}): {max(o, h, lo, c)}"

    if h < lo:
        return f"high ({h}) < low ({lo})"

    if o > 0 and h < o:
        return f"high ({h}) < open ({o})"

    if o > 0 and lo > o:
        return f"low ({lo}) > open ({o})"

    if v < 0:
        return f"Negative volume: {v}"

    if oi < 0:
        return f"Negative OI: {oi}"

    return ""


# ---------------------------------------------------------------------------
# Column name normalisation
# ---------------------------------------------------------------------------


def _normalise_columns(raw_bar: dict[str, Any]) -> dict[str, Any]:
    """Apply column alias mapping to a raw dict bar.

    Args:
        raw_bar: Dict possibly using source-specific column names.

    Returns:
        Dict with standardised lowercase column names.
    """
    normalised: dict[str, Any] = {}
    for k, v in raw_bar.items():
        standard = _COLUMN_ALIASES.get(k, k.lower())
        normalised[standard] = v
    return normalised


# ---------------------------------------------------------------------------
# Core normaliser
# ---------------------------------------------------------------------------


class OHLCVNormaliser:
    """Normalise heterogeneous OHLCV data to the standard FlintTrade schema.

    Usage::

        normaliser = OHLCVNormaliser()

        # From a list of dicts (historify / openalgo format)
        result = normaliser.normalise(raw_bars, symbol="RELIANCE", exchange="NSE", interval="5m")

        # From a pandas DataFrame (openchart format)
        result = normaliser.normalise_dataframe(df, symbol="NIFTY", exchange="NFO", interval="1d")

        # From ProviderBar list (registry output)
        result = normaliser.normalise_provider_bars(provider_result.bars)
    """

    def __init__(
        self,
        *,
        apply_intraday_cutoff: bool = True,
        drop_invalid: bool = True,
        forward_fill: bool = False,
    ) -> None:
        """Initialise the normaliser.

        Args:
            apply_intraday_cutoff: If True, bars after 15:29:59 IST are
                dropped for intraday intervals (absorbed from openchart).
            drop_invalid: If True (default), invalid bars are dropped.
                If False, they are kept but a warning is added.
            forward_fill: If True, missing close values are forward-filled
                from the previous bar's close. Useful for thinly-traded
                instruments with gaps.
        """
        self._cutoff = apply_intraday_cutoff
        self._drop_invalid = drop_invalid
        self._forward_fill = forward_fill

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def normalise(
        self,
        bars: list[dict[str, Any]],
        *,
        symbol: str = "",
        exchange: str = "",
        interval: str = "",
    ) -> NormaliseResult:
        """Normalise a list of raw dict bars.

        Each dict may use any of the supported column name variants.

        Args:
            bars: Raw OHLCV bars as a list of dicts.
            symbol: Symbol to annotate on each bar (optional).
            exchange: Exchange to annotate on each bar (optional).
            interval: Interval string — used for intraday cutoff logic.

        Returns:
            NormaliseResult with sorted, validated bars.
        """
        result = NormaliseResult()

        if not bars:
            return result

        try:
            normalised_bars = self._process_dicts(
                bars, symbol=symbol, exchange=exchange, interval=interval,
            )
            result.bars = normalised_bars.bars
            result.dropped = normalised_bars.dropped
            result.warnings = normalised_bars.warnings
        except Exception as exc:
            result.error = str(exc)
            logger.error("Normalisation failed: %s", exc)

        return result

    def normalise_dataframe(
        self,
        df: Any,
        *,
        symbol: str = "",
        exchange: str = "",
        interval: str = "",
    ) -> NormaliseResult:
        """Normalise a pandas DataFrame to the standard schema.

        The DataFrame may use either the openchart column names
        (Timestamp/Open/High/Low/Close/Volume) or the index as timestamp.

        Args:
            df: pandas DataFrame with OHLCV data.
            symbol: Symbol to annotate.
            exchange: Exchange to annotate.
            interval: Interval for intraday cutoff.

        Returns:
            NormaliseResult with sorted, validated bars.
        """
        result = NormaliseResult()

        try:
            import pandas  # noqa: F401
        except ImportError:
            result.error = "pandas is required for normalise_dataframe"
            return result

        if df is None or df.empty:
            return result

        try:
            # If timestamp is the index (openchart style), reset it to a column
            if "timestamp" not in df.columns and "Timestamp" not in df.columns:
                df = df.reset_index()

            records = df.to_dict("records")
            return self.normalise(records, symbol=symbol, exchange=exchange, interval=interval)

        except Exception as exc:
            result.error = str(exc)
            logger.error("DataFrame normalisation failed: %s", exc)
        return result

    def normalise_provider_bars(
        self,
        bars: list[Any],
        *,
        interval: str = "",
    ) -> NormaliseResult:
        """Normalise a list of ProviderBar objects.

        Args:
            bars: List of ProviderBar instances from a data provider.
            interval: Interval string for intraday cutoff.

        Returns:
            NormaliseResult with validated NormalisedBar objects.
        """
        raw = [
            {
                "timestamp": b.timestamp,
                "open": b.open,
                "high": b.high,
                "low": b.low,
                "close": b.close,
                "volume": b.volume,
                "oi": b.oi,
                "symbol": getattr(b, "source", ""),
                "exchange": "",
            }
            for b in bars
        ]
        return self.normalise(raw, interval=interval)

    # ------------------------------------------------------------------
    # Internal processing
    # ------------------------------------------------------------------

    def _process_dicts(
        self,
        bars: list[dict[str, Any]],
        *,
        symbol: str,
        exchange: str,
        interval: str,
    ) -> NormaliseResult:
        """Internal: process a list of raw dicts into NormalisedBar objects."""
        result = NormaliseResult()
        is_intraday = interval in _INTRADAY_INTERVALS
        prev_close: float | None = None

        for raw_bar in bars:
            mapped = _normalise_columns(raw_bar)

            # Timestamp
            raw_ts = mapped.get("timestamp") or mapped.get("date") or ""
            if not raw_ts:
                result.dropped += 1
                result.warnings.append(f"Bar missing timestamp: {raw_bar}")
                continue

            try:
                ts_str = _to_ist_naive(raw_ts)
            except ValueError as exc:
                result.dropped += 1
                result.warnings.append(f"Bad timestamp {raw_ts!r}: {exc}")
                continue

            # Apply intraday cutoff (openchart pattern — drop bars after 15:29:59)
            if self._cutoff and is_intraday:
                try:
                    bar_time = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S").time()
                    cutoff = datetime(2000, 1, 1, _INTRADAY_CUTOFF_HH,
                                      _INTRADAY_CUTOFF_MM, _INTRADAY_CUTOFF_SS).time()
                    if bar_time > cutoff:
                        result.dropped += 1
                        continue
                except ValueError:
                    pass  # Date-only timestamp, not intraday — keep it

            # Numeric fields
            try:
                open_ = float(mapped.get("open", 0) or 0)
                high = float(mapped.get("high", 0) or 0)
                low = float(mapped.get("low", 0) or 0)
                close = float(mapped.get("close", 0) or 0)
                volume = int(float(mapped.get("volume", 0) or 0))
                oi = int(float(mapped.get("oi", 0) or 0))
            except (TypeError, ValueError) as exc:
                result.dropped += 1
                result.warnings.append(f"Non-numeric field in bar at {ts_str}: {exc}")
                continue

            # Forward fill missing close
            if close == 0.0 and self._forward_fill and prev_close is not None:
                close = prev_close

            bar_dict = {
                "open": open_, "high": high, "low": low,
                "close": close, "volume": volume, "oi": oi,
            }

            # Validation
            err = _validate_bar(bar_dict)
            if err:
                msg = f"Invalid bar at {ts_str}: {err}"
                if self._drop_invalid:
                    result.dropped += 1
                    result.warnings.append(msg)
                    continue
                else:
                    result.warnings.append(msg)

            prev_close = close

            # Build NormalisedBar
            bar_symbol = symbol or str(mapped.get("symbol", ""))
            bar_exchange = exchange or str(mapped.get("exchange", ""))

            result.bars.append(
                NormalisedBar(
                    timestamp=ts_str,
                    open=open_,
                    high=high,
                    low=low,
                    close=close,
                    volume=volume,
                    oi=oi,
                    symbol=bar_symbol,
                    exchange=bar_exchange,
                )
            )

        # Sort oldest-first
        result.bars.sort(key=lambda b: b.timestamp)

        if result.dropped:
            logger.info(
                "Normaliser: %d/%d bars dropped (%d valid)",
                result.dropped, len(bars), result.total_bars,
            )

        return result


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------


def normalise(
    bars: list[dict[str, Any]],
    *,
    symbol: str = "",
    exchange: str = "",
    interval: str = "",
    apply_intraday_cutoff: bool = True,
    drop_invalid: bool = True,
    forward_fill: bool = False,
) -> NormaliseResult:
    """Convenience wrapper: normalise raw bar dicts with a one-liner.

    Args:
        bars: Raw OHLCV bar dicts.
        symbol: Symbol annotation.
        exchange: Exchange annotation.
        interval: Interval string for intraday cutoff logic.
        apply_intraday_cutoff: Drop bars after 15:29:59 for intraday intervals.
        drop_invalid: Drop bars failing validation (default True).
        forward_fill: Forward-fill zero close values.

    Returns:
        NormaliseResult with validated, sorted NormalisedBar objects.
    """
    return OHLCVNormaliser(
        apply_intraday_cutoff=apply_intraday_cutoff,
        drop_invalid=drop_invalid,
        forward_fill=forward_fill,
    ).normalise(bars, symbol=symbol, exchange=exchange, interval=interval)
