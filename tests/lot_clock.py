"""Index futures generated from the test clock, not the shipped excerpt.

Set ``FLINTTRADE_CLOCK_OFFSET_MONTHS`` to prove a lookup still resolves after
the shipped expiry dates. ``1`` and ``6`` are the proof offsets.
"""

from __future__ import annotations

import calendar
import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date

import pytest
from flinttrade_core.instrument_lots import future_index_rows, lot_size_from_master, today_ist

_NAMES = ("NIFTY", "BANKNIFTY", "SENSEX")


def clock_day() -> date:
    """Today in India, plus ``FLINTTRADE_CLOCK_OFFSET_MONTHS`` when set."""
    raw = os.environ.get("FLINTTRADE_CLOCK_OFFSET_MONTHS", "0") or "0"
    months = int(raw)
    day = today_ist()
    if months == 0:
        return day
    month_index = day.month - 1 + months
    year = day.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


@contextmanager
def open_clocked_master(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[dict[str, object], ...]]:
    """Point master lookup and the fallback table at clock-relative futures.

    Restores the fallback table afterwards. Attribute writes are undone when
    the test ends.
    """
    from flinttrade_core import instrument_lots
    from flinttrade_screener.lot_sizes import FALLBACK_LOT_SIZES

    day = clock_day()
    rows = future_index_rows(day)
    monkeypatch.setattr(instrument_lots, "today_ist", lambda: day)
    monkeypatch.setattr(instrument_lots, "active_rows", lambda: rows)
    previous = {name: FALLBACK_LOT_SIZES.get(name) for name in _NAMES}
    missing = {name for name in _NAMES if name not in FALLBACK_LOT_SIZES}
    for name in _NAMES:
        lot = lot_size_from_master(name, rows, as_of=day)
        if lot is None:
            raise AssertionError(f"{name} has no lot on {day.isoformat()}")
        FALLBACK_LOT_SIZES[name] = lot
    try:
        yield rows
    finally:
        for name in _NAMES:
            if name in missing:
                FALLBACK_LOT_SIZES.pop(name, None)
            elif previous[name] is not None:
                FALLBACK_LOT_SIZES[name] = previous[name]
