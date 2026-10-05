"""Download the public Dhan and Kotak Neo masters and keep a small excerpt.

The excerpt covers NIFTY, BANKNIFTY and SENSEX futures for the near month
and the next month. Security ids, expiries and lot sizes are copied from
those files. When a download fails the excerpt keeps an empty ``rows`` list
and the source metadata; nothing is invented.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
import threading
import time
import urllib.request
from collections.abc import Callable
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

from flinttrade_core.instrument_lots import (
    cache_path,
    contracts_from_rows,
    fixture_path,
    read_master_payload,
    today_ist,
)

logger = logging.getLogger("flinttrade.instrument_lots")

DHAN_SCRIP_MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"
NEO_MASTER_URL = (
    "https://lapi.kotaksecurities.com/wso2-scripmaster/v1/prod/{day}/transformed/{name}.csv"
)
_NEO_FILES = ("nse_fo", "bse_fo")
_UNDERLYINGS = ("NIFTY", "BANKNIFTY", "SENSEX")
_LISTED = re.compile(
    r"^(NIFTY|BANKNIFTY|SENSEX)(?:-|\d{2}(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC))"
)
_YY_MONTH = re.compile(r"(\d{2})(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)")
_MONTHS = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}
_IST = ZoneInfo("Asia/Kolkata")
_USER_AGENT = "FlintTrade/0.0.1 instrument-lot-excerpt"
Downloader = Callable[[str], str]


def _download_text(url: str) -> str:
    if not url.startswith("https://"):
        raise ValueError(f"Refusing non-HTTPS instrument master URL: {url}")
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - scheme pinned above
        return response.read().decode("utf-8", errors="replace")


def _whole_lot(raw: str) -> str | None:
    try:
        number = Decimal(raw.strip())
    except InvalidOperation:
        return None
    if not number.is_finite() or number != number.to_integral_value() or number <= 0:
        return None
    return str(int(number))


def _iso_day(raw: str) -> date | None:
    text = raw.strip()
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None
    return None


def _listed_underlying(symbol: str) -> str | None:
    match = _LISTED.match(symbol.upper())
    if match is None:
        return None
    return match.group(1)


def _is_future(instrument: str, symbol: str) -> bool:
    inst = instrument.upper()
    sym = symbol.upper()
    if sym.endswith(("CE", "PE")):
        return False
    return "FUT" in inst or inst == "IF" or sym.endswith("FUT")


def _neo_expiry(raw: str, trading_symbol: str) -> date | None:
    """Return the listed expiry.

    Kotak's NSE file stores some expiries ten years early. The trading
    symbol carries the listed year, and the timestamp still has the right
    month and day.
    """
    text = raw.strip()
    if text.isdigit():
        parsed = datetime.fromtimestamp(int(text), ZoneInfo("UTC")).date()
        named = _YY_MONTH.search(trading_symbol.upper())
        if named is not None:
            year = 2000 + int(named.group(1))
            if parsed.year != year:
                try:
                    parsed = date(year, parsed.month, parsed.day)
                except ValueError:
                    return None
        return parsed
    iso = _iso_day(text)
    if iso is not None:
        return iso
    named = _YY_MONTH.search(text.upper()) or _YY_MONTH.search(trading_symbol.upper())
    if named is None:
        return None
    return date(2000 + int(named.group(1)), _MONTHS[named.group(2)], 1)


def _dhan_rows(text: str) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    for row in csv.DictReader(io.StringIO(text)):
        symbol = (row.get("SEM_TRADING_SYMBOL") or "").strip()
        underlying = _listed_underlying(symbol)
        instrument = (row.get("SEM_INSTRUMENT_NAME") or "").strip()
        if underlying is None or not _is_future(instrument, symbol):
            continue
        expiry = _iso_day(row.get("SEM_EXPIRY_DATE") or "")
        lot = _whole_lot(row.get("SEM_LOT_UNITS") or "")
        security_id = (row.get("SEM_SMST_SECURITY_ID") or "").strip()
        if expiry is None or lot is None or not security_id:
            continue
        found.append(
            {
                "SEM_EXM_EXCH_ID": (row.get("SEM_EXM_EXCH_ID") or "").strip(),
                "SEM_SEGMENT": (row.get("SEM_SEGMENT") or "D").strip() or "D",
                "SEM_SMST_SECURITY_ID": security_id,
                "SEM_INSTRUMENT_NAME": instrument,
                "SEM_TRADING_SYMBOL": symbol,
                "SEM_CUSTOM_SYMBOL": underlying,
                "SEM_EXPIRY_DATE": expiry.isoformat(),
                "SEM_LOT_UNITS": lot,
            }
        )
    return found


def _neo_rows(text: str) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    for row in csv.DictReader(io.StringIO(text)):
        symbol = (row.get("pTrdSymbol") or "").strip()
        name = (row.get("pSymbolName") or "").strip().upper().replace(" ", "")
        underlying = name if name in _UNDERLYINGS else _listed_underlying(symbol)
        instrument = (row.get("pInstType") or "").strip()
        if underlying is None or underlying not in _UNDERLYINGS or not _is_future(instrument, symbol):
            continue
        if _listed_underlying(symbol) not in {None, underlying}:
            continue
        expiry = _neo_expiry(row.get("pExpiryDate") or "", symbol)
        lot = _whole_lot(row.get("lLotSize") or "")
        security_id = (row.get("pSymbol") or "").strip()
        if expiry is None or lot is None or not security_id:
            continue
        found.append(
            {
                "pExchSeg": (row.get("pExchSeg") or "").strip(),
                "pSymbol": security_id,
                "pSymbolName": underlying,
                "pTrdSymbol": symbol,
                "pInstType": instrument or "FUTIDX",
                "pExpiryDate": expiry.isoformat(),
                "lLotSize": lot,
            }
        )
    return found


def _row_underlying(row: dict[str, str]) -> str:
    return (row.get("SEM_CUSTOM_SYMBOL") or row.get("pSymbolName") or "").upper()


def _row_expiry(row: dict[str, str]) -> date | None:
    return _iso_day(row.get("SEM_EXPIRY_DATE") or row.get("pExpiryDate") or "")


def _near_and_next(rows: list[dict[str, str]], *, as_of: date) -> list[dict[str, str]]:
    """Keep the first two unexpired expiries of each underlying."""
    by_underlying: dict[str, dict[date, list[dict[str, str]]]] = {}
    for row in rows:
        underlying = _row_underlying(row)
        expiry = _row_expiry(row)
        if underlying not in _UNDERLYINGS or expiry is None or expiry < as_of:
            continue
        by_underlying.setdefault(underlying, {}).setdefault(expiry, []).append(row)
    chosen: list[dict[str, str]] = []
    for underlying in _UNDERLYINGS:
        expiries = sorted(by_underlying.get(underlying, {}))
        for expiry in expiries[:2]:
            chosen.extend(by_underlying[underlying][expiry])
    return chosen


def _payload(rows: list[dict[str, str]], sources: list[str], *, fetched_at: str, note: str) -> dict[str, object]:
    try:
        contracts_from_rows(rows)
    except ValueError:
        logger.warning("Instrument masters disagree; the excerpt is left empty")
        rows = []
        note = f"{note} The masters disagreed on a lot size, so no rows were written."
    return {
        "source": sources,
        "fetched_at": fetched_at,
        "note": note,
        "rows": rows,
    }


def build_excerpt(
    *,
    downloader: Downloader | None = None,
    as_of: date | None = None,
) -> dict[str, object]:
    """Download both masters and return the near/next-month excerpt.

    A master that cannot be fetched contributes no rows. The returned
    document still names the source URLs and the fetch time.
    """
    fetch = downloader or _download_text
    day = as_of or today_ist()
    fetched_at = datetime.now(_IST).isoformat(timespec="seconds")
    sources: list[str] = [DHAN_SCRIP_MASTER_URL]
    rows: list[dict[str, str]] = []
    downloaded = 0

    try:
        rows.extend(_dhan_rows(fetch(DHAN_SCRIP_MASTER_URL)))
        downloaded += 1
    except Exception as exc:  # noqa: BLE001 - a failed master must not invent rows
        logger.warning("Dhan scrip master was not downloaded (%s)", type(exc).__name__)

    neo_day = day
    neo_texts: list[str] = []
    for offset in range(7):
        candidate = (day - timedelta(days=offset)).isoformat()
        urls = [NEO_MASTER_URL.format(day=candidate, name=name) for name in _NEO_FILES]
        try:
            neo_texts = [fetch(url) for url in urls]
        except Exception as exc:  # noqa: BLE001 - try the previous published day
            logger.warning("Kotak Neo F&O master %s was not downloaded (%s)", candidate, type(exc).__name__)
            continue
        neo_day = date.fromisoformat(candidate)
        sources.extend(urls)
        downloaded += 1
        break
    else:
        sources.extend(NEO_MASTER_URL.format(day=day.isoformat(), name=name) for name in _NEO_FILES)

    for text in neo_texts:
        rows.extend(_neo_rows(text))

    chosen = _near_and_next(rows, as_of=day)
    if downloaded == 0:
        note = (
            "Near and next month NIFTY, BANKNIFTY and SENSEX futures. "
            "The public masters could not be downloaded, so rows are empty."
        )
    elif neo_texts:
        note = (
            "Near and next month NIFTY, BANKNIFTY and SENSEX futures from the "
            f"public Dhan scrip master and the Kotak Neo F&O master dated {neo_day.isoformat()}. "
            "A contract is omitted once its expiry is before the current day in IST."
        )
    else:
        note = (
            "Near and next month NIFTY, BANKNIFTY and SENSEX futures from the public "
            "Dhan scrip master. The Kotak Neo F&O master could not be downloaded. "
            "A contract is omitted once its expiry is before the current day in IST."
        )
    return _payload(chosen, sources, fetched_at=fetched_at, note=note)


def write_excerpt(path: Path, payload: dict[str, object]) -> None:
    """Atomically replace ``path`` with ``payload``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def write_shipped_excerpt(*, downloader: Downloader | None = None, as_of: date | None = None) -> dict[str, object]:
    """Refresh the excerpt bundled with the backend and the terminal."""
    payload = build_excerpt(downloader=downloader, as_of=as_of)
    write_excerpt(fixture_path(), payload)
    return payload


def _fetched_on(payload: dict[str, object]) -> date | None:
    raw = payload.get("fetched_at")
    if not isinstance(raw, str) or len(raw) < 10:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def refresh_master_cache_if_due(
    *,
    downloader: Downloader | None = None,
    as_of: date | None = None,
) -> bool:
    """Download when the workspace cache is missing or from an earlier IST day.

    A failed download leaves a previous non-empty cache in place. Returns
    ``True`` when a new cache file was written.
    """
    day = as_of or today_ist()
    path = cache_path()
    existing = read_master_payload(path)
    if (
        existing is not None
        and isinstance(existing.get("rows"), list)
        and existing["rows"]
        and _fetched_on(existing) == day
    ):
        return False
    payload = build_excerpt(downloader=downloader, as_of=day)
    rows = payload.get("rows")
    if (not isinstance(rows, list) or not rows) and existing is not None and existing.get("rows"):
        logger.warning("Instrument master refresh returned no rows; the previous cache is unchanged")
        return False
    write_excerpt(path, payload)
    return True


def _seconds_until_next_ist_midnight() -> float:
    now = datetime.now(_IST)
    tomorrow = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), tzinfo=_IST)
    return max(60.0, (tomorrow - now).total_seconds())


def _refresh_loop() -> None:
    while True:
        try:
            refresh_master_cache_if_due()
        except Exception:  # noqa: BLE001 - the shipped excerpt remains the fallback
            logger.warning("Instrument master refresh failed", exc_info=True)
        time.sleep(_seconds_until_next_ist_midnight())


_REFRESH_STARTED = False


def start_instrument_master_refresh() -> None:
    """Refresh the master cache on startup and again at each IST midnight.

    Tests skip the thread. A second call does not start another one.
    """
    global _REFRESH_STARTED
    if _REFRESH_STARTED or os.environ.get("PYTEST_CURRENT_TEST"):
        return
    _REFRESH_STARTED = True
    threading.Thread(target=_refresh_loop, name="instrument-master-refresh", daemon=True).start()
