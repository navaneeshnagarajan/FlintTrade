"""Lot sizes from a broker scrip master, one row per listed contract.

The exchange revises a lot size for new expiries only. Contracts already
listed keep the previous size until they expire, so two sizes can be live
for one underlying. Dhan (``SEM_LOT_UNITS``) and Kotak Neo (``lLotSize``)
both publish that size on the contract, not on the underlying.

Look up a size by instrument token or security id. Two expiries of the same
underlying may differ. The only rejected row is a real conflict: the same
contract (same underlying, expiry month, and kind) carrying different sizes
in the Dhan and Neo masters.

There is no built-in NIFTY / BANKNIFTY / SENSEX table. A missing contract
returns ``None``. A live session reads the disk cache written from the
public masters; otherwise the shipped excerpt is used. Contracts whose
expiry is before today (IST) are dropped.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

_FIXTURE_PATH = Path(__file__).parent / "data" / "instrument_lot_fixture.json"

_LOT_KEYS = ("SEM_LOT_UNITS", "LOT_UNITS", "LOT_SIZE", "lLotSize", "lot_size")
_NAME_KEYS = (
    "SEM_CUSTOM_SYMBOL",
    "UNDERLYING_SYMBOL",
    "SM_SYMBOL_NAME",
    "SYMBOL_NAME",
    "pSymbolName",
)
_ID_KEYS = (
    "SEM_SMST_SECURITY_ID",
    "SECURITY_ID",
    "instrument_token",
    "security_id",
    "pSymbol",
)
_EXPIRY_KEYS = (
    "SEM_EXPIRY_DATE",
    "SM_EXPIRY_DATE",
    "pExpiryDate",
    "lExpiryDate",
    "expiry",
)
_SYMBOL_KEYS = ("SEM_TRADING_SYMBOL", "TRADING_SYMBOL", "pTrdSymbol", "trading_symbol")
_INSTRUMENT_KEYS = ("SEM_INSTRUMENT_NAME", "pInstType", "instrument_type", "instrument")

_MONTHS: dict[str, int] = {
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
_MONTH_LABELS: dict[int, str] = {
    1: "Jan",
    2: "Feb",
    3: "Mar",
    4: "Apr",
    5: "May",
    6: "Jun",
    7: "Jul",
    8: "Aug",
    9: "Sep",
    10: "Oct",
    11: "Nov",
    12: "Dec",
}
_MONTH_NAME = re.compile(
    r"(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*[\s-]*(\d{4})",
    re.IGNORECASE,
)
_YY_MONTH = re.compile(
    r"(\d{2})(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)",
    re.IGNORECASE,
)
_ISO_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
# Desk label: underlying, strike, CE/PE. No thousands separator.
_DESK_OPTION = re.compile(r"^(?P<underlying>[A-Z][A-Z0-9&]*)\s+(?P<strike>\d+(?:\.\d+)?)\s+(?P<option_type>CE|PE)$")


@dataclass(frozen=True)
class ContractLot:
    """One listed contract after the two masters have been reconciled."""

    security_ids: tuple[str, ...]
    underlying: str
    expiry: date | None
    lot_size: int
    kind: str

    @property
    def month_label(self) -> str | None:
        """Three-letter expiry month, or ``None`` when the row has no expiry."""
        if self.expiry is None:
            return None
        return _MONTH_LABELS[self.expiry.month]


def fixture_path() -> Path:
    """Absolute path of the shipped scrip-master excerpt."""
    return _FIXTURE_PATH


def cache_path() -> Path:
    """Disk cache of the last successful master download for this workspace."""
    from flinttrade_core.workspace import workspace_dir  # noqa: PLC0415

    return workspace_dir(ensure_exists=False) / "instrument_lot_cache.json"


def today_ist() -> date:
    """Current calendar day in India Standard Time."""
    return datetime.now(ZoneInfo("Asia/Kolkata")).date()


def _resolve_as_of(as_of: date | None) -> date:
    return today_ist() if as_of is None else as_of


def _unexpired(contracts: tuple[ContractLot, ...], as_of: date) -> tuple[ContractLot, ...]:
    """Drop contracts whose expiry date is before ``as_of``."""
    return tuple(contract for contract in contracts if contract.expiry is None or contract.expiry >= as_of)


def _cell(row: Mapping[str, object], *names: str) -> str:
    folded = {str(key).strip().lower(): value for key, value in row.items()}
    for name in names:
        value = folded.get(name.lower())
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _lot_units(row: Mapping[str, object]) -> int | None:
    raw = _cell(row, *_LOT_KEYS)
    if not raw:
        return None
    try:
        number = Decimal(raw)
    except InvalidOperation:
        return None
    if not number.is_finite() or number != number.to_integral_value() or number <= 0:
        return None
    return int(number)


def _underlying(row: Mapping[str, object]) -> str:
    return _cell(row, *_NAME_KEYS).upper().replace(" ", "")


def _parse_date(raw: str) -> date | None:
    iso = _ISO_DATE.search(raw)
    if iso:
        year, month, day = (int(part) for part in iso.groups())
        try:
            return date(year, month, day)
        except ValueError:
            return None
    named = _MONTH_NAME.search(raw)
    if named:
        month = _MONTHS[named.group(1).upper()]
        return date(int(named.group(2)), month, 1)
    short = _YY_MONTH.search(raw.upper())
    if short:
        year = 2000 + int(short.group(1))
        month = _MONTHS[short.group(2).upper()]
        return date(year, month, 1)
    return None


def _expiry(row: Mapping[str, object]) -> date | None:
    explicit = _parse_date(_cell(row, *_EXPIRY_KEYS))
    if explicit is not None:
        return explicit
    return _parse_date(_cell(row, *_SYMBOL_KEYS))


def _kind(row: Mapping[str, object]) -> str:
    instrument = _cell(row, *_INSTRUMENT_KEYS).upper()
    symbol = _cell(row, *_SYMBOL_KEYS).upper()
    if "FUT" in instrument or symbol.endswith("FUT"):
        return "FUT"
    if instrument.startswith("OPT") or symbol.endswith(("CE", "PE")):
        return "OPT"
    return instrument or "INST"


def _contract_key(underlying: str, expiry: date | None, kind: str) -> str:
    when = expiry.strftime("%Y-%m") if expiry is not None else "undated"
    return f"{underlying}|{when}|{kind}"


def _security_id(row: Mapping[str, object], fallback: str) -> str:
    found = _cell(row, *_ID_KEYS)
    return found or fallback


def contracts_from_rows(
    rows: list[Mapping[str, object]] | tuple[Mapping[str, object], ...],
) -> tuple[ContractLot, ...]:
    """Reconcile master rows into one record per listed contract.

    Raises:
        ValueError: The same contract has two lot sizes. A later expiry of
            the same underlying is a different contract and is kept.
    """
    grouped: dict[str, list[tuple[str, str, date | None, int, str]]] = {}
    for row in rows:
        underlying = _underlying(row)
        lot = _lot_units(row)
        if not underlying or lot is None:
            continue
        expiry = _expiry(row)
        kind = _kind(row)
        key = _contract_key(underlying, expiry, kind)
        security_id = _security_id(row, key)
        grouped.setdefault(key, []).append((security_id, underlying, expiry, lot, kind))

    contracts: list[ContractLot] = []
    seen_ids: dict[str, int] = {}
    for items in grouped.values():
        sizes = {item[3] for item in items}
        underlying, expiry = items[0][1], items[0][2]
        when = expiry.isoformat() if expiry is not None else "undated"
        if len(sizes) > 1:
            raise ValueError(f"Scrip master disagrees on the lot size for {underlying} {when}")
        ids: list[str] = []
        for security_id, _name, _when, lot, _series in items:
            previous = seen_ids.get(security_id)
            if previous is not None and previous != lot:
                raise ValueError(f"Scrip master disagrees on the lot size for {underlying} {when}")
            seen_ids[security_id] = lot
            if security_id not in ids:
                ids.append(security_id)
        _, underlying, expiry, lot, kind = items[0]
        contracts.append(
            ContractLot(
                security_ids=tuple(ids),
                underlying=underlying,
                expiry=expiry,
                lot_size=lot,
                kind=kind,
            )
        )
    return tuple(contracts)


def lot_sizes_from_rows(
    rows: list[Mapping[str, object]] | tuple[Mapping[str, object], ...],
) -> dict[str, int]:
    """Map each instrument token or security id to its contract lot size.

    Raises:
        ValueError: The same contract disagrees across the masters.
    """
    found: dict[str, int] = {}
    for contract in contracts_from_rows(rows):
        for security_id in contract.security_ids:
            found[security_id] = contract.lot_size
    return found


def _rows_from_payload(payload: object) -> tuple[dict[str, object], ...]:
    if not isinstance(payload, dict):
        return ()
    raw_rows = payload.get("rows", [])
    if not isinstance(raw_rows, list):
        return ()
    return tuple(row for row in raw_rows if isinstance(row, dict))


def read_master_payload(path: Path) -> dict[str, object] | None:
    """Load a master excerpt. ``None`` when the file is missing or unreadable."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


@lru_cache(maxsize=1)
def load_fixture_rows() -> tuple[dict[str, object], ...]:
    """Rows in the shipped excerpt. Not a substitute for a fresh download."""
    payload = read_master_payload(_FIXTURE_PATH)
    if payload is None:
        return ()
    return _rows_from_payload(payload)


def load_cache_rows() -> tuple[dict[str, object], ...]:
    """Rows from today's downloaded cache, or empty when the cache is absent."""
    payload = read_master_payload(cache_path())
    if payload is None:
        return ()
    return _rows_from_payload(payload)


def active_rows() -> tuple[dict[str, object], ...]:
    """Live cache when the session has downloaded rows, otherwise the shipped excerpt."""
    cached = load_cache_rows()
    if cached:
        return cached
    return load_fixture_rows()


def _source(
    rows: list[Mapping[str, object]] | tuple[Mapping[str, object], ...] | None,
    *,
    as_of: date | None = None,
) -> tuple[ContractLot, ...]:
    loaded = active_rows() if rows is None else rows
    return _unexpired(contracts_from_rows(tuple(loaded)), _resolve_as_of(as_of))


def lot_size_for_contract(
    security_id: str,
    rows: list[Mapping[str, object]] | tuple[Mapping[str, object], ...] | None = None,
    *,
    as_of: date | None = None,
) -> int | None:
    """Lot size of one contract, addressed by instrument token or security id."""
    token = security_id.strip()
    if not token:
        return None
    for contract in _source(rows, as_of=as_of):
        if token in contract.security_ids:
            return contract.lot_size
    return None


def _plain_strike(strike: str | float) -> str:
    """Strike as the desk prints it: ``24500``, or ``83.5`` when it is not whole."""
    number = Decimal(str(strike))
    if number == number.to_integral_value():
        return str(int(number))
    return format(number.normalize(), "f")


def desk_contract_name(symbol: str) -> str:
    """Contract label the desk already shows, for example ``NIFTY 24500 CE``.

    A spaced option is kept. A compact option such as ``NIFTY24APR2524500CE``
    is expanded to that same label. Any other symbol is the order's own name.
    """
    text = " ".join(symbol.strip().upper().split())
    if not text:
        return ""
    spaced = _DESK_OPTION.fullmatch(text)
    if spaced is not None:
        return f"{spaced.group('underlying')} {_plain_strike(spaced.group('strike'))} {spaced.group('option_type')}"
    from flinttrade_core.symbol_utils import parse_option_symbol  # noqa: PLC0415

    option = parse_option_symbol(text.replace(" ", ""))
    if option is not None:
        return f"{option.underlying} {_plain_strike(option.strike)} {option.option_type}"
    return text


def _listed_symbol(
    security_id: str,
    rows: list[Mapping[str, object]] | tuple[Mapping[str, object], ...] | None,
) -> str:
    """Trading symbol for a security id, including a contract that has expired."""
    token = security_id.strip()
    if not token or rows is None:
        return ""
    for row in rows:
        if _security_id(row, "") == token:
            return _cell(row, *_SYMBOL_KEYS)
    return ""


def missing_lot_refusal(contract: str) -> str:
    """Refusal when the instrument master has no lot for this contract."""
    return f"Not placed. The lot size for {contract} isn't in the instrument master, so this order can't be sized."


def contract_quantity_message(
    security_id: str,
    quantity: int,
    rows: list[Mapping[str, object]] | tuple[Mapping[str, object], ...] | None = None,
    *,
    as_of: date | None = None,
    contract: str = "",
) -> str | None:
    """Refuse a quantity that is not a positive multiple of that contract's lot.

    Returns ``None`` when the quantity is valid. ``contract`` is the order's
    display name, for example ``NIFTY 24500 CE``.
    """
    lot = lot_size_for_contract(security_id, rows, as_of=as_of)
    if lot is None:
        name = desk_contract_name(contract) or desk_contract_name(_listed_symbol(security_id, rows))
        if not name:
            name = security_id.strip()
        return missing_lot_refusal(name)
    if quantity <= 0 or quantity % lot != 0:
        return f"Quantity must be a positive multiple of the lot size ({lot})"
    return None


def _underlying_contracts(underlying: str, contracts: tuple[ContractLot, ...]) -> list[ContractLot]:
    key = underlying.strip().upper().replace(" ", "")
    mine = [contract for contract in contracts if contract.underlying == key and contract.expiry is not None]
    futures = [contract for contract in mine if contract.kind == "FUT"]
    chosen = futures or mine
    chosen.sort(key=lambda contract: contract.expiry or date.min)
    return chosen


def lot_size_from_master(
    underlying: str,
    rows: list[Mapping[str, object]] | tuple[Mapping[str, object], ...] | None = None,
    *,
    as_of: date | None = None,
) -> int | None:
    """Near-month lot size for an underlying, or ``None`` when it is not listed.

    This is the front contract only. A later expiry can carry a different
    size; callers that price or validate one contract use
    :func:`lot_size_for_contract`.
    """
    contracts = _source(rows, as_of=as_of)
    dated = _underlying_contracts(underlying, contracts)
    if dated:
        return dated[0].lot_size
    key = underlying.strip().upper().replace(" ", "")
    undated = [contract for contract in contracts if contract.underlying == key and contract.expiry is None]
    if not undated:
        return None
    return undated[0].lot_size


def scalper_lot_label(
    underlying: str,
    rows: list[Mapping[str, object]] | tuple[Mapping[str, object], ...] | None = None,
    *,
    as_of: date | None = None,
) -> str | None:
    """Near-month lot, labelled with its expiry.

    When the next month uses a different size, both are named. ``None`` when
    the master has no dated contract for the underlying.
    """
    chosen = _underlying_contracts(underlying, _source(rows, as_of=as_of))
    if not chosen:
        return None
    shown = [chosen[0]]
    if len(chosen) > 1 and chosen[1].lot_size != chosen[0].lot_size:
        shown.append(chosen[1])
    parts: list[str] = []
    for contract in shown:
        month = contract.month_label
        if month is None or contract.expiry is None:
            continue
        parts.append(f"{contract.lot_size} · {month} expiry")
    if not parts:
        return None
    return ", ".join(parts)


_INDEX_UNDERLYINGS = ("NIFTY", "BANKNIFTY", "SENSEX")
_MISSING_LOT = "\u2014"


def index_lot_line(
    rows: list[Mapping[str, object]] | tuple[Mapping[str, object], ...] | None = None,
    *,
    as_of: date | None = None,
    underlyings: tuple[str, ...] = _INDEX_UNDERLYINGS,
) -> str:
    """Near-month index lots in the Scalper's form.

    ``NIFTY 65 · BANKNIFTY 30 · SENSEX 20 (Sep/Oct expiry)``. Each name keeps
    its lot, so the line is never a bare list of numbers. An underlying with
    no dated master row is ``—``. When the Scalper names a second month
    because the size changes, that underlying keeps the Scalper's own
    wording. The parenthetical lists the expiry months of the rows that
    supplied a lot, in calendar order.
    """
    parts: list[str] = []
    months: list[str] = []
    seen: set[str] = set()
    for underlying in underlyings:
        label = scalper_lot_label(underlying, rows, as_of=as_of)
        if label is None:
            parts.append(f"{underlying} {_MISSING_LOT}")
            continue
        segments = [segment.strip() for segment in label.split(",") if segment.strip()]
        lots: list[str] = []
        for segment in segments:
            lot_text, _, rest = segment.partition(" · ")
            month = rest.removesuffix(" expiry").strip()
            if lot_text:
                lots.append(lot_text)
            if month and month not in seen:
                seen.add(month)
                months.append(month)
        if len(segments) == 1 and lots:
            parts.append(f"{underlying} {lots[0]}")
        else:
            parts.append(f"{underlying} {label}")
    months.sort(key=lambda name: next(number for number, label in _MONTH_LABELS.items() if label == name))
    line = " · ".join(parts)
    if months:
        line = f"{line} ({'/'.join(months)} expiry)"
    return line
