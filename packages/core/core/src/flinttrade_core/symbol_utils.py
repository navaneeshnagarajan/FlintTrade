"""FlintTrade symbol spelling, derivative decomposition and expiry dates.

These utilities operate on exchange naming conventions; broker instrument
identity still comes from the native instrument catalogue.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

ExpiryFormat = Literal["DDMMMYY", "YYMMDD", "ISO"]
_MONTH_NUMBER = {calendar.month_abbr[number].upper(): number for number in range(1, 13)}
# Compact NSE and BSE index underlyings. Derivative admission uses this one
# list to tell an index contract from a stock contract. Quote boards and
# lot tables in the terminal use the same names.
INDEX_UNDERLYINGS = frozenset(
    {
        "BANKEX",
        "BANKNIFTY",
        "BSE100",
        "BSE150MIDCAPINDEX",
        "BSE200",
        "BSE250LARGEMIDCAPINDEX",
        "BSE400MIDSMALLCAPINDEX",
        "BSE500",
        "BSEAUTO",
        "BSECAPITALGOODS",
        "BSECARBONEX",
        "BSECONSUMERDURABLES",
        "BSECPSE",
        "BSEDOLLEX100",
        "BSEDOLLEX200",
        "BSEDOLLEX30",
        "BSEENERGY",
        "BSEFASTMOVINGCONSUMERGOODS",
        "BSEFINANCIALSERVICES",
        "BSEGREENEX",
        "BSEHEALTHCARE",
        "BSEINDIAINFRASTRUCTUREINDEX",
        "BSEINDUSTRIALS",
        "BSEINFORMATIONTECHNOLOGY",
        "BSEIPO",
        "BSELARGECAP",
        "BSEMETAL",
        "BSEMIDCAP",
        "BSEMIDCAPSELECTINDEX",
        "BSEOIL&GAS",
        "BSEPOWER",
        "BSEPSU",
        "BSEREALTY",
        "BSESENSEXNEXT50",
        "BSESMALLCAP",
        "BSESMALLCAPSELECTINDEX",
        "BSESMEIPO",
        "BSETECK",
        "BSETELECOM",
        "FINNIFTY",
        "HANGSENGBEESNAV",
        "INDIAVIX",
        "MIDCPNIFTY",
        "NIFTY",
        "NIFTY100",
        "NIFTY100EQLWGT",
        "NIFTY100LIQ15",
        "NIFTY100LOWVOL30",
        "NIFTY100QUALTY30",
        "NIFTY200",
        "NIFTY200QUALTY30",
        "NIFTY500",
        "NIFTY50DIVPOINT",
        "NIFTY50EQLWGT",
        "NIFTY50PR1XINV",
        "NIFTY50PR2XLEV",
        "NIFTY50TR1XINV",
        "NIFTY50TR2XLEV",
        "NIFTY50VALUE20",
        "NIFTYALPHA50",
        "NIFTYAUTO",
        "NIFTYCOMMODITIES",
        "NIFTYCONSUMPTION",
        "NIFTYCPSE",
        "NIFTYDIVOPPS50",
        "NIFTYENERGY",
        "NIFTYFMCG",
        "NIFTYFPI",
        "NIFTYGROWSECT15",
        "NIFTYGS10YR",
        "NIFTYGS10YRCLN",
        "NIFTYGS1115YR",
        "NIFTYGS15YRPLUS",
        "NIFTYGS48YR",
        "NIFTYGS813YR",
        "NIFTYGSCOMPSITE",
        "NIFTYINFRA",
        "NIFTYIT",
        "NIFTYMEDIA",
        "NIFTYMETAL",
        "NIFTYMIDCAP100",
        "NIFTYMIDCAP150",
        "NIFTYMIDCAP50",
        "NIFTYMIDLIQ15",
        "NIFTYMIDSML400",
        "NIFTYMNC",
        "NIFTYNXT50",
        "NIFTYPHARMA",
        "NIFTYPSE",
        "NIFTYPSUBANK",
        "NIFTYPVTBANK",
        "NIFTYREALTY",
        "NIFTYSERVSECTOR",
        "NIFTYSMLCAP100",
        "NIFTYSMLCAP250",
        "NIFTYSMLCAP50",
        "SENSEX",
        "SENSEX50",
    }
)
_INDEX_NAMES = INDEX_UNDERLYINGS
_CURRENCY_NAMES = frozenset(("USDINR", "EURINR", "GBPINR", "JPYINR", "USDCHF", "EURUSD"))
_COMMODITY_NAMES = frozenset(
    (
        "GOLD",
        "SILVER",
        "CRUDE",
        "CRUDEOIL",
        "COPPER",
        "ZINC",
        "LEAD",
        "ALUMINIUM",
        "NATURALGAS",
        "COTTON",
        "PEPPER",
    )
)


@dataclass(frozen=True)
class OptionParts:
    underlying: str
    expiry: str
    strike: float
    option_type: Literal["CE", "PE"]


@dataclass(frozen=True)
class FutureParts:
    underlying: str
    expiry: str


def normalize_symbol(symbol: str, exchange: str = "") -> str:
    """Resolve known index aliases while preserving punctuation in equities."""
    value = symbol.strip().upper()
    index_spelling = value.translate(str.maketrans("", "", "_-"))
    if index_spelling == "NIFTY50":
        return "NIFTY"
    return index_spelling if index_spelling in _INDEX_NAMES else value


def _named_index_day(prefix: str) -> tuple[str, str] | None:
    """Split a known index name from a following day, longest name first."""
    matched = ""
    for name in INDEX_UNDERLYINGS:
        if prefix.startswith(name) and len(name) > len(matched):
            matched = name
    if not matched:
        return None
    day = prefix[len(matched) :]
    if len(day) > 2 or (day and not day.isdigit()):
        return None
    return matched, day


def _split_month(value: str) -> tuple[str, str, str] | None:
    """Separate a derivative into underlying, day/month, and trailing fields.

    A month abbreviation inside an index name, such as SEP in BSEPOWER, is
    kept with that name. The known index match wins over an earlier generic one.
    """
    generic: tuple[str, str, str] | None = None
    for offset in range(1, len(value) - 2):
        month = value[offset : offset + 3]
        if month not in _MONTH_NUMBER:
            continue
        prefix = value[:offset]
        named = _named_index_day(prefix)
        if named is not None:
            name, day = named
            return name, day + month, value[offset + 3 :]
        if generic is not None:
            continue
        name_end = len(prefix)
        while name_end and prefix[name_end - 1].isdigit():
            name_end -= 1
        name, day = prefix[:name_end], prefix[name_end:]
        if not name or any(not (ch.isalpha() or ch == "&") for ch in name):
            continue
        if len(day) > 2:
            continue
        generic = (normalize_symbol(name), day + month, value[offset + 3 :])
    return generic


def parse_option_symbol(symbol: str) -> OptionParts | None:
    """Decompose ``underlying[day]month-year-strike-CE/PE`` spelling."""
    value = symbol.strip().upper()
    kind = value[-2:]
    if kind not in ("CE", "PE"):
        return None
    fields = _split_month(value[:-2])
    if fields is None:
        return None
    underlying, expiry, remainder = fields
    year, strike = remainder[:2], remainder[2:]
    if len(year) != 2 or not year.isdigit() or not strike:
        return None
    integer, dot, fraction = strike.partition(".")
    if not integer.isdigit() or (dot and not fraction.isdigit()):
        return None
    return OptionParts(underlying, expiry + year, float(strike), kind)


def parse_future_symbol(symbol: str) -> FutureParts | None:
    """Decompose a futures spelling with an optional two-digit year."""
    value = symbol.strip().upper()
    if not value.endswith("FUT"):
        return None
    fields = _split_month(value[:-3])
    if fields is None:
        return None
    underlying, expiry, year = fields
    if year and (len(year) != 2 or not year.isdigit()):
        return None
    return FutureParts(underlying, expiry + year)


def build_option_symbol(
    underlying: str,
    expiry: str,
    strike: float,
    option_type: Literal["CE", "PE"],
) -> str:
    """Render a decimal strike without trailing zeroes or exponent notation."""
    amount = format(Decimal(str(strike)), "f")
    if "." in amount:
        amount = amount.rstrip("0").rstrip(".")
    return "".join((underlying.upper(), expiry.upper(), amount, option_type.upper()))


def build_future_symbol(underlying: str, expiry: str) -> str:
    """Render the supplied contract components with the futures suffix."""
    return "".join((underlying.upper(), expiry.upper(), "FUT"))


def detect_instrument_type(
    symbol: str,
) -> Literal["equity", "option", "future", "index", "currency", "commodity"]:
    """Classify known spellings; native catalogue metadata is authoritative."""
    if parse_option_symbol(symbol):
        return "option"
    if parse_future_symbol(symbol):
        return "future"
    value = normalize_symbol(symbol)
    if value in _INDEX_NAMES:
        return "index"
    if value in _CURRENCY_NAMES:
        return "currency"
    if value in _COMMODITY_NAMES:
        return "commodity"
    return "equity"


def exchange_segment(exchange: str) -> Literal["EQ", "FO", "CD", "COM", "IDX"]:
    """Return an exchange's cash, derivative, currency, commodity or index segment."""
    value = exchange.strip().upper()
    for segment, exchanges in (
        ("EQ", ("NSE", "BSE")),
        ("FO", ("NFO", "BFO")),
        ("CD", ("CDS", "BCD")),
        ("COM", ("MCX", "NCDEX")),
        ("IDX", ("NSE_INDEX", "BSE_INDEX")),
    ):
        if value in exchanges:
            return segment
    raise ValueError(f"Unknown exchange: {exchange!r}")


def parse_expiry(
    value: str,
    *,
    formats: tuple[ExpiryFormat, ...] = ("DDMMMYY", "YYMMDD", "ISO"),
) -> date:
    """Parse only the explicitly allowed expiry date representations."""
    text = (value or "").strip().upper()
    for representation in formats:
        try:
            if representation == "ISO":
                return date.fromisoformat(text)
            if representation == "YYMMDD" and len(text) == 6 and text.isdigit():
                year = int(text[:2])
                return date(2000 + year if year <= 68 else 1900 + year, int(text[2:4]), int(text[4:]))
            if representation == "DDMMMYY" and len(text) in (6, 7):
                day, month, year = text[:-5], text[-5:-2], text[-2:]
                if day.isdigit() and year.isdigit() and month in _MONTH_NUMBER:
                    return date(2000 + int(year), _MONTH_NUMBER[month], int(day))
        except ValueError:
            continue
    raise ValueError(f"Invalid expiry date {value!r} (accepted formats: {', '.join(formats)})")
