"""One Practice market pricing rule for every place path.

Desk Order Pad and Settings → Practice Mode both reach
``POST /api/v1/orders/place``. A typed number is not a second rule. The fill
price is:

1. the live price, when the request marks ``price_basis`` as ``ltp``;
2. otherwise the last stored close, labelled with its age and tagged
   ``price_source=last_close``;
3. otherwise a plain refusal.

An F&O option outside the existing market-hours session is refused before
either of those prices is used. No Practice path fills at a sample or fixed
reference price.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

logger = logging.getLogger("flinttrade.data.practice_price")

_STORAGE_UNSET = object()

_IST = ZoneInfo("Asia/Kolkata")

PRICE_SOURCE_LTP = "ltp"
PRICE_SOURCE_LAST_CLOSE = "last_close"

OPTION_PRICE_STALE = "Option prices go stale outside market hours. Try again when the market opens."


def practice_price_unavailable(symbol: str) -> str:
    """Plain refusal when a Practice market order has nothing to fill against."""
    name = str(symbol).strip().upper() or "this symbol"
    return f"No price for {name} right now. Practice needs a live price or a recent close."


def format_price_age(age_s: int) -> str:
    """Render a stored-close age as days, else hours, else minutes."""
    seconds = max(0, int(age_s))
    if seconds >= 86_400:
        days = seconds // 86_400
        unit = "day" if days == 1 else "days"
        return f"{days} {unit} old"
    if seconds >= 3_600:
        hours = seconds // 3_600
        unit = "hour" if hours == 1 else "hours"
        return f"{hours} {unit} old"
    minutes = seconds // 60
    return f"{minutes} min old"


def last_close_fill_label(price: float, age_s: int) -> str:
    """Operator sentence for a Practice fill taken from the last stored close."""
    return f"Simulated at last close ₹{price:.2f} ({format_price_age(age_s)})"


@dataclass(frozen=True)
class StoredClose:
    """One usable stored close and how old its tick is, in seconds."""

    price: float
    age_s: int


@dataclass(frozen=True)
class PracticeMarketPrice:
    """Resolved Practice MARKET fill.

    ``label`` is set only for a last-close fill. A live LTP leaves it empty.
    ``price_source`` is ``ltp`` or ``last_close`` so storage can exclude a
    stale fill from research.
    """

    price: float
    price_source: str | None
    price_age_s: int | None
    label: str | None


def practice_market_is_open(exchange: str, symbol: str) -> bool:
    """Whether the running scheduler says this instrument's session is open.

    Session times, exchange holidays, and broker special sessions stay on
    the scheduler already loaded into ``app.config["TIME_SCHEDULER"]``.
    A fresh clock has none of that calendar, so this does not build one.
    With no running scheduler the session is closed and an option is refused.
    """
    scheduler = _runtime_scheduler()
    if scheduler is None:
        return False
    try:
        return bool(scheduler.is_market_open(exchange, symbol=symbol or None))
    except Exception:
        logger.debug(
            "Practice market-hours check failed for %s %s",
            exchange,
            symbol,
            exc_info=True,
        )
        return False


def _runtime_scheduler() -> Any | None:
    """Return the app's populated scheduler, or nothing when it is missing."""
    try:
        from flask import current_app, has_app_context
    except Exception:
        return None
    if not has_app_context():
        return None
    scheduler = current_app.config.get("TIME_SCHEDULER")
    if not callable(getattr(scheduler, "is_market_open", None)):
        return None
    return scheduler


def resolve_practice_market_price(
    *,
    symbol: str,
    exchange: str = "",
    request_price: float,
    price_basis: str | None,
    stored_close: StoredClose | None = None,
    market_open: Callable[[str, str], bool] | None = None,
) -> PracticeMarketPrice | str:
    """Resolve one Practice MARKET price, or return the plain refusal sentence.

    A positive request price counts only when ``price_basis`` is ``ltp``.
    Any other number on the request (including a price typed in Settings) is
    ignored so both place paths share this rule. Options outside market hours
    are refused even when a live price or a stored close exists.
    """
    name = str(symbol).strip().upper()
    venue = str(exchange).strip().upper()
    if _is_option(name) and not _session_open(venue, name, market_open):
        return OPTION_PRICE_STALE

    basis = str(price_basis or "").strip().lower()
    try:
        quoted = float(request_price)
    except (TypeError, ValueError, OverflowError):
        quoted = 0.0
    if basis == "ltp" and math.isfinite(quoted) and quoted > 0:
        return PracticeMarketPrice(
            price=quoted,
            price_source=PRICE_SOURCE_LTP,
            price_age_s=None,
            label=None,
        )

    if stored_close is not None and stored_close.age_s >= 0:
        price = _positive_price(stored_close.price)
        if price is not None:
            age_s = int(stored_close.age_s)
            return PracticeMarketPrice(
                price=price,
                price_source=PRICE_SOURCE_LAST_CLOSE,
                price_age_s=age_s,
                label=last_close_fill_label(price, age_s),
            )

    return practice_price_unavailable(name)


def lookup_stored_last_close(
    symbol: str,
    exchange: str,
    storage: Any = _STORAGE_UNSET,
    *,
    now: datetime | None = None,
) -> StoredClose | None:
    """Return the newest stored close, else last trade, and its age.

    A row without a timestamp is not usable: the age must be real. Missing
    storage or a failed read means "no stored price", not an error. The
    window is the last seven IST sessions so a closed market can still see
    the last print. Omit ``storage`` to read the app's tick store.
    """
    name = str(symbol).strip().upper()
    venue = str(exchange).strip().upper()
    if not name or not venue:
        return None
    if storage is _STORAGE_UNSET:
        return _lookup_configured_last_close(name, venue, now)
    return _read_last_close(storage, name, venue, now)


def _lookup_configured_last_close(
    name: str,
    venue: str,
    now: datetime | None,
) -> StoredClose | None:
    """Read the app tick store under its lock, then re-check the handle.

    The recorder flushes on the same DuckDB connection. ``TICK_STORAGE_LOCK``
    is the lock the tick query route uses. After the lock is taken, a store
    that was replaced or unpublished is not read.
    """
    try:
        from flask import current_app, has_app_context
    except Exception:
        return None
    if not has_app_context():
        return None
    store = current_app.config.get("TICK_STORAGE")
    if store is None:
        return None
    lock = current_app.config.get("TICK_STORAGE_LOCK")
    try:
        if lock is None:
            if current_app.config.get("TICK_STORAGE") is not store:
                return None
            return _read_last_close(store, name, venue, now)
        with lock:
            if current_app.config.get("TICK_STORAGE") is not store:
                return None
            return _read_last_close(store, name, venue, now)
    except Exception:
        logger.debug("Practice last-close lookup failed for %s %s", venue, name, exc_info=True)
        return None


def _read_last_close(
    store: Any,
    name: str,
    venue: str,
    now: datetime | None,
) -> StoredClose | None:
    """Return the newest stored close from one store, or nothing."""
    window_clock = now if now is not None else datetime.now(_IST)
    if window_clock.tzinfo is None:
        window_clock = window_clock.replace(tzinfo=_IST)
    try:
        today = window_clock.astimezone(_IST).date()
        start = (today - timedelta(days=7)).isoformat()
        rows = store.get_ticks(name, venue, start, today.isoformat(), limit=1)
    except Exception:
        logger.debug("Practice last-close lookup failed for %s %s", venue, name, exc_info=True)
        return None
    if not rows:
        return None
    row = rows[-1]
    if not isinstance(row, dict):
        return None
    age_clock = window_clock if now is not None else datetime.now(_IST)
    if age_clock.tzinfo is None:
        age_clock = age_clock.replace(tzinfo=_IST)
    age_s = _age_seconds(row.get("ts"), age_clock)
    if age_s is None:
        return None
    for key in ("prev_close", "close", "ltp"):
        price = _positive_price(row.get(key))
        if price is not None:
            return StoredClose(price=price, age_s=age_s)
    return None


def _session_open(
    exchange: str,
    symbol: str,
    market_open: Callable[[str, str], bool] | None,
) -> bool:
    is_open = market_open or practice_market_is_open
    try:
        return bool(is_open(exchange, symbol))
    except Exception:
        logger.debug("Practice market-hours check failed for %s %s", exchange, symbol, exc_info=True)
        return False


def _is_option(symbol: str) -> bool:
    from flinttrade_core.symbol_utils import parse_option_symbol

    return parse_option_symbol(symbol) is not None


def _age_seconds(ts: Any, now: datetime) -> int | None:
    moment = _as_datetime(ts)
    if moment is None:
        return None
    delta = (now - moment).total_seconds()
    if not math.isfinite(delta):
        return None
    if delta < 0:
        return 0 if delta > -5 else None
    return int(delta)


def _as_datetime(ts: Any) -> datetime | None:
    """Read a tick time. Zone-less storage values are UTC, not IST.

    Epoch numbers are absolute instants. Aware values are converted to UTC.
    """
    if isinstance(ts, bool):
        return None
    if isinstance(ts, (int, float)) and math.isfinite(float(ts)) and float(ts) > 1_000_000_000:
        return datetime.fromtimestamp(float(ts), tz=UTC)
    from flinttrade_data.storage import read_stored_timestamp  # noqa: PLC0415

    return read_stored_timestamp(ts)


def _positive_price(value: Any) -> float | None:
    try:
        price = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if math.isfinite(price) and price > 0:
        return price
    return None
