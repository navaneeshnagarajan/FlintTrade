"""Symbol normalisation and parsing utilities for FlintTrade.

Handles the canonical string representation of NSE/BSE/NFO/MCX instruments.
Ported and extended from OpenAlgo's ``utils/symbol_utils.py`` with additional
FlintTrade-specific helpers.

Canonical form rules
--------------------
* Equity index aliases are collapsed: ``NIFTY50`` → ``NIFTY``,
  ``BANKNIFTY`` stays ``BANKNIFTY``.
* Underscores and hyphens are stripped: ``NIFTY_50`` → ``NIFTY``.
* The symbol is upper-cased.

Option symbol format (NFO)
--------------------------
Compact NSE format: ``{UNDERLYING}{DD}{MON}{YY}{STRIKE}{CE|PE}``

Examples::

    NIFTY24APR25500CE
    BANKNIFTY24MAR2545000PE
    FINNIFTY24JUN2522000CE

Future symbol format (NFO)
--------------------------
``{UNDERLYING}{DD}{MON}{YY}FUT``  or  ``{UNDERLYING}{MON}{YY}FUT``

Examples::

    NIFTY24APRFUT
    NIFTY24APR25FUT  (some brokers use full date)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

# ---------------------------------------------------------------------------
# Normalisation aliases
# ---------------------------------------------------------------------------

# Maps common alias → canonical name
_INDEX_ALIASES: dict[str, str] = {
    "NIFTY50": "NIFTY",
    "NIFTY_50": "NIFTY",
    "NIFTY-50": "NIFTY",
    "SENSEX": "SENSEX",
    "BANKNIFTY": "BANKNIFTY",
    "BANK_NIFTY": "BANKNIFTY",
    "BANK-NIFTY": "BANKNIFTY",
    "FINNIFTY": "FINNIFTY",
    "FIN_NIFTY": "FINNIFTY",
    "MIDCPNIFTY": "MIDCPNIFTY",
    "MIDCP_NIFTY": "MIDCPNIFTY",
    "NIFTYIT": "NIFTYIT",
    "NIFTYMETAL": "NIFTYMETAL",
    "NIFTYPHARMA": "NIFTYPHARMA",
}

_MONTHS: tuple[str, ...] = (
    "JAN", "FEB", "MAR", "APR", "MAY", "JUN",
    "JUL", "AUG", "SEP", "OCT", "NOV", "DEC",
)
_MONTH_SET: frozenset[str] = frozenset(_MONTHS)

# Option symbol: underlying + optional day + month + 2-digit year + strike + CE/PE
_OPTION_RE = re.compile(
    r"^(?P<underlying>[A-Z&]+)"
    r"(?P<day>\d{1,2})?"
    r"(?P<month>JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)"
    r"(?P<year>\d{2})"
    r"(?P<strike>\d+(?:\.\d+)?)"
    r"(?P<option_type>CE|PE)$"
)

# Future symbol: underlying + optional day + month + optional 2-digit year + FUT
# e.g. NIFTY24APRFUT  (day=24, no year) or NIFTY24APR25FUT (day=24, year=25)
_FUTURE_RE = re.compile(
    r"^(?P<underlying>[A-Z&]+)"
    r"(?P<day>\d{1,2})?"
    r"(?P<month>JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)"
    r"(?P<year>\d{2})?"
    r"FUT$"
)


# ---------------------------------------------------------------------------
# Parsed result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OptionParts:
    """Parsed components of an option symbol.

    Args:
        underlying: Normalised underlying name (e.g. ``"NIFTY"``).
        expiry: Expiry string in ``DDMONYY`` or ``MONYY`` form as found in
            the original symbol (e.g. ``"24APR25"``).
        strike: Strike price as a float (e.g. ``22000.0``).
        option_type: ``"CE"`` or ``"PE"``.
    """

    underlying: str
    expiry: str
    strike: float
    option_type: Literal["CE", "PE"]


@dataclass(frozen=True)
class FutureParts:
    """Parsed components of a futures symbol.

    Args:
        underlying: Normalised underlying name.
        expiry: Expiry string as found in the original symbol.
    """

    underlying: str
    expiry: str


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def normalize_symbol(symbol: str, exchange: str = "") -> str:
    """Normalise *symbol* to FlintTrade canonical form.

    Converts to upper-case, resolves index aliases, and strips common
    separator characters.

    Args:
        symbol: Raw symbol string from any source.
        exchange: Optional exchange hint (currently unused; reserved for
            future MCX prefix handling).

    Returns:
        Canonical upper-case symbol string.

    Examples::

        normalize_symbol("nifty50")     # → "NIFTY"
        normalize_symbol("NIFTY_50")    # → "NIFTY"
        normalize_symbol("RELIANCE")    # → "RELIANCE"
        normalize_symbol("GOLD24APRFUT") # → "GOLD24APRFUT"
    """
    upper = symbol.strip().upper()
    # Check direct alias table first
    if upper in _INDEX_ALIASES:
        return _INDEX_ALIASES[upper]
    # Strip leading/trailing separators and internal underscores/hyphens
    # that appear *only* in index names (not futures/options)
    cleaned = upper.replace("_", "").replace("-", "")
    if cleaned in _INDEX_ALIASES:
        return _INDEX_ALIASES[cleaned]
    return upper


def parse_option_symbol(symbol: str) -> OptionParts | None:
    """Parse a compact NSE option symbol into its components.

    Accepts symbols in the form ``{UNDERLYING}[DD]{MON}{YY}{STRIKE}{CE|PE}``.

    Args:
        symbol: Raw option symbol string.

    Returns:
        :class:`OptionParts` on success, ``None`` when *symbol* does not
        match the expected pattern.

    Examples::

        parse_option_symbol("NIFTY24APR25500CE")
        # → OptionParts(underlying="NIFTY", expiry="24APR25", strike=500.0, option_type="CE")

        parse_option_symbol("BANKNIFTY24MAR2545000PE")
        # → OptionParts(underlying="BANKNIFTY", expiry="24MAR25", strike=45000.0, option_type="PE")
    """
    m = _OPTION_RE.match(symbol.strip().upper())
    if m is None:
        return None

    underlying = normalize_symbol(m.group("underlying"))
    day = m.group("day") or ""
    month = m.group("month")
    year = m.group("year")
    expiry = f"{day}{month}{year}"
    strike = float(m.group("strike"))
    option_type = m.group("option_type")  # type: ignore[assignment]

    return OptionParts(
        underlying=underlying,
        expiry=expiry,
        strike=strike,
        option_type=option_type,
    )


def parse_future_symbol(symbol: str) -> FutureParts | None:
    """Parse a compact NSE futures symbol into its components.

    Accepts symbols in the form ``{UNDERLYING}[DD]{MON}{YY}FUT``.

    Args:
        symbol: Raw futures symbol string.

    Returns:
        :class:`FutureParts` on success, ``None`` when *symbol* does not
        match.

    Examples::

        parse_future_symbol("NIFTY24APRFUT")
        # → FutureParts(underlying="NIFTY", expiry="24APR")

        parse_future_symbol("GOLD24APR25FUT")
        # → FutureParts(underlying="GOLD", expiry="24APR25")
    """
    m = _FUTURE_RE.match(symbol.strip().upper())
    if m is None:
        return None

    underlying = normalize_symbol(m.group("underlying"))
    day = m.group("day") or ""
    month = m.group("month")
    year = m.group("year")
    expiry = f"{day}{month}{year}"

    return FutureParts(underlying=underlying, expiry=expiry)


def build_option_symbol(
    underlying: str,
    expiry: str,
    strike: float,
    option_type: Literal["CE", "PE"],
) -> str:
    """Build a compact NSE option symbol from its components.

    Args:
        underlying: Underlying name (e.g. ``"NIFTY"``).
        expiry: Expiry string in ``DDMONYY`` or ``MONYY`` form
            (e.g. ``"24APR25"``).
        strike: Strike price.  Integer strikes are serialised without
            a decimal point.
        option_type: ``"CE"`` or ``"PE"``.

    Returns:
        Option symbol string (e.g. ``"NIFTY24APR25500CE"``).

    Examples::

        build_option_symbol("NIFTY", "24APR25", 22000.0, "CE")
        # → "NIFTY24APR2522000CE"
    """
    strike_str = str(int(strike)) if strike == int(strike) else str(strike)
    return f"{underlying.upper()}{expiry.upper()}{strike_str}{option_type.upper()}"


def build_future_symbol(underlying: str, expiry: str) -> str:
    """Build a compact NSE futures symbol.

    Args:
        underlying: Underlying name.
        expiry: Expiry string (e.g. ``"24APR25"``).

    Returns:
        Futures symbol string (e.g. ``"NIFTY24APR25FUT"``).
    """
    return f"{underlying.upper()}{expiry.upper()}FUT"


def detect_instrument_type(
    symbol: str,
) -> Literal["equity", "option", "future", "index", "currency", "commodity"]:
    """Classify an instrument by symbol pattern.

    Priority order: option → future → index → currency → commodity → equity.

    Args:
        symbol: Raw or normalised symbol string.

    Returns:
        One of ``"equity"``, ``"option"``, ``"future"``, ``"index"``,
        ``"currency"``, ``"commodity"``.

    Examples::

        detect_instrument_type("NIFTY24APR25500CE")  # → "option"
        detect_instrument_type("NIFTY24APRFUT")       # → "future"
        detect_instrument_type("NIFTY")               # → "index"
        detect_instrument_type("RELIANCE")             # → "equity"
    """
    upper = symbol.strip().upper()

    if parse_option_symbol(upper) is not None:
        return "option"

    if parse_future_symbol(upper) is not None:
        return "future"

    # Known index names
    _indices: frozenset[str] = frozenset(
        {
            "NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX",
            "NIFTYIT", "NIFTYMETAL", "NIFTYPHARMA", "NIFTYAUTO",
            "NIFTYENERGY", "NIFTYREALTY", "NIFTYFMCG", "NIFTYINFRA",
            "INDIA_VIX", "INDIAVIX",
        }
    )
    if normalize_symbol(upper) in _indices:
        return "index"

    # Currency pairs (e.g. USDINR, EURINR)
    _currencies = frozenset({"USDINR", "EURINR", "GBPINR", "JPYINR", "USDCHF", "EURUSD"})
    if upper in _currencies:
        return "currency"

    # MCX commodity base names
    _commodities = frozenset({"GOLD", "SILVER", "CRUDE", "CRUDEOIL", "COPPER", "ZINC", "LEAD", "ALUMINIUM", "NATURALGAS", "COTTON", "PEPPER"})
    if upper in _commodities:
        return "commodity"

    return "equity"


def exchange_segment(
    exchange: str,
) -> Literal["EQ", "FO", "CD", "COM", "IDX"]:
    """Map an OpenAlgo exchange code to its segment short code.

    Args:
        exchange: OpenAlgo exchange code (case-insensitive).

    Returns:
        One of ``"EQ"``, ``"FO"``, ``"CD"``, ``"COM"``, ``"IDX"``.

    Raises:
        ValueError: When *exchange* is not recognised.

    Examples::

        exchange_segment("NSE")        # → "EQ"
        exchange_segment("NFO")        # → "FO"
        exchange_segment("NSE_INDEX")  # → "IDX"
    """
    mapping: dict[str, Literal["EQ", "FO", "CD", "COM", "IDX"]] = {
        "NSE": "EQ",
        "BSE": "EQ",
        "NFO": "FO",
        "BFO": "FO",
        "CDS": "CD",
        "BCD": "CD",
        "MCX": "COM",
        "NCDEX": "COM",
        "NSE_INDEX": "IDX",
        "BSE_INDEX": "IDX",
    }
    key = exchange.strip().upper()
    if key not in mapping:
        raise ValueError(f"Unknown exchange: '{exchange}'")
    return mapping[key]
