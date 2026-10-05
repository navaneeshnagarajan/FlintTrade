"""Validate exchange closures and special sessions from calendar provider data."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, time
from math import isfinite
from typing import Any

_COLLECTION = (list, tuple, set)


def _date(value: Any) -> str | None:
    try:
        return date.fromisoformat(str(value).strip()[:10]).isoformat()
    except ValueError:
        return None


def _time_value(value: Any) -> tuple[bool, float] | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
        return (False, number) if isfinite(number) else None
    except (ValueError, TypeError):
        try:
            clock = time.fromisoformat(str(value))
        except ValueError:
            return None
        return True, clock.hour * 3600 + clock.minute * 60 + clock.second + clock.microsecond / 1e6


def _session(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    exchange = str(value.get("exchange") or "").strip().upper()
    start, end = _time_value(value.get("start_time")), _time_value(value.get("end_time"))
    if not exchange or start is None or end is None or start[0] != end[0]:
        return None
    if (start[0] and start[1] == end[1]) or (not start[0] and end[1] <= start[1]):
        return None
    record = {"exchange": exchange, "start_time": value["start_time"], "end_time": value["end_time"]}
    if value.get("symbol"):
        record["symbol"] = str(value["symbol"]).strip().upper()
    if isinstance(value.get("symbols"), _COLLECTION):
        symbols = sorted({str(symbol).strip().upper() for symbol in value["symbols"] if str(symbol).strip()})
        if symbols:
            record["symbols"] = symbols
    return record


def _entries(payload: Any, year: int | None = None) -> list[tuple[Any, str]] | None:
    seen = set()
    while isinstance(payload, Mapping) and ("data" in payload or "holidays" in payload):
        if id(payload) in seen:
            return None
        seen.add(id(payload))
        if str(payload.get("status", "success")).lower() not in ("success", "ok"):
            return None
        if year is not None and "year" in payload:
            try:
                if int(payload["year"]) != year:
                    return None
            except (ValueError, TypeError):
                return None
        payload = payload["data"] if "data" in payload else payload["holidays"]
    if isinstance(payload, _COLLECTION):
        return [(entry, "*") for entry in payload]
    if isinstance(payload, Mapping):
        if any(not isinstance(values, _COLLECTION) for values in payload.values()):
            return None
        return [(entry, str(exchange).strip().upper()) for exchange, values in payload.items() for entry in values]
    return None


def _entry_date(entry: Any) -> str | None:
    value = (
        next((entry[key] for key in ("date", "holiday_date", "trading_date") if entry.get(key)), None)
        if isinstance(entry, Mapping)
        else entry
    )
    return _date(value)


def is_authoritative_market_calendar(payload: Any, *, expected_year: int | None = None) -> bool:
    """Require nonempty, wholly valid calendar evidence before replacing live state."""
    entries = _entries(payload, expected_year)
    if not entries:
        return False
    for entry, exchange in entries:
        day = _entry_date(entry)
        if day is None or (expected_year is not None and int(day[:4]) != expected_year):
            return False
        if isinstance(entry, Mapping):
            for key in ("closed_exchanges", "open_exchanges"):
                if key in entry and not isinstance(entry[key], _COLLECTION):
                    return False
            if any(_session(value) is None for value in entry.get("open_exchanges", ())):
                return False
    return True


def normalise_market_calendar(payload: Any) -> list[dict[str, Any]]:
    """Merge closures by date; malformed declared openings remain closed."""
    dates: dict[str, dict[str, Any]] = {}
    for entry, exchange in _entries(payload) or ():
        day = _entry_date(entry)
        if day is None:
            continue
        data = entry if isinstance(entry, Mapping) else {}
        kind = str(data.get("holiday_type") or "TRADING_HOLIDAY").strip().upper()
        structured = any(key in data for key in ("closed_exchanges", "open_exchanges", "holiday_type"))
        closed = set()
        if structured:
            if isinstance(data.get("closed_exchanges", ()), _COLLECTION):
                closed.update(
                    str(value).strip().upper() for value in data.get("closed_exchanges", ()) if str(value).strip()
                )
        else:
            closed.add(exchange)
        openings = []
        if isinstance(data.get("open_exchanges", ()), _COLLECTION):
            for candidate in data.get("open_exchanges", ()):
                session = _session(candidate)
                if session:
                    openings.append(session)
                elif isinstance(candidate, Mapping) and candidate.get("exchange"):
                    closed.add(str(candidate["exchange"]).strip().upper())
        if structured and not closed and kind != "SETTLEMENT_HOLIDAY":
            closed.add("*")
        row = dates.setdefault(
            day,
            {
                "date": day,
                "description": "",
                "holiday_type": kind,
                "closed_exchanges": set(),
                "open_exchanges": [],
            },
        )
        row["description"] = row["description"] or str(data.get("description") or "")
        if kind == "SPECIAL_SESSION" or row["holiday_type"] == "SETTLEMENT_HOLIDAY":
            row["holiday_type"] = kind
        row["closed_exchanges"].update(closed)
        row["open_exchanges"].extend(session for session in openings if session not in row["open_exchanges"])
    return [{**dates[day], "closed_exchanges": sorted(dates[day]["closed_exchanges"])} for day in sorted(dates)]


def normalise_holiday_dates(payload: Any, exchange: str = "NSE") -> list[str]:
    """List full trading closures for the chosen exchange, respecting special sessions."""
    name = str(exchange or "NSE").strip().upper()
    name = {"NSE_INDEX": "NSE", "BSE_INDEX": "BSE", "MCX_INDEX": "MCX"}.get(name, name)
    return [
        row["date"]
        for row in normalise_market_calendar(payload)
        if ("*" in row["closed_exchanges"] or name in row["closed_exchanges"])
        and not any(session["exchange"] == name for session in row["open_exchanges"])
    ]
