"""
OpenAlgo Symbol Converter — Bidirectional converter between broker-specific
instrument keys and the OpenAlgo canonical symbol format.

Supports all segments: EQ, FO (futures + options), CDS, MCX, IDX.

OpenAlgo symbol formats:
  - Equity:   RELIANCE
  - Future:   NIFTY28MAR24FUT
  - Option:   NIFTY28MAR2420800CE
  - CDS:      USDINR28MAR2485.50CE  (decimal strikes)
  - MCX:      CRUDEOIL28MAR249000CE
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

class Segment(str, Enum):
    """Exchange segment codes used by OpenAlgo."""
    EQ = "EQ"
    FO = "FO"       # NSE F&O
    CDS = "CDS"     # Currency derivatives
    MCX = "MCX"     # Commodities
    IDX = "IDX"     # Index (no trading, data only)
    BFO = "BFO"     # BSE F&O
    BCD = "BCD"     # BSE Currency


class InstrumentType(str, Enum):
    """Instrument types within a segment."""
    EQ = "EQ"
    FUT = "FUT"
    CE = "CE"
    PE = "PE"


@dataclass(frozen=True)
class SymbolParts:
    """Parsed components of an OpenAlgo symbol string.

    Attributes:
        base: Underlying name (e.g. ``NIFTY``, ``RELIANCE``, ``USDINR``).
        instrument_type: One of EQ, FUT, CE, PE.
        expiry_date: Expiry date (``None`` for equities).
        strike: Strike price (``None`` for equities / futures).
        option_type: ``CE`` or ``PE`` (``None`` for equities / futures).
        original: The raw symbol string that was parsed.
    """
    base: str
    instrument_type: InstrumentType
    expiry_date: Optional[date] = None
    strike: Optional[float] = None
    option_type: Optional[str] = None
    original: str = ""


# ---------------------------------------------------------------------------
# Well-known base-symbol mappings (broker → OpenAlgo)
# ---------------------------------------------------------------------------

SYMBOL_ALIASES: dict[str, str] = {
    "NIFTY 50": "NIFTY",
    "NIFTY50": "NIFTY",
    "NIFTY BANK": "BANKNIFTY",
    "BANK NIFTY": "BANKNIFTY",
    "NIFTY FINANCIAL SERVICES": "FINNIFTY",
    "NIFTY FIN SERVICE": "FINNIFTY",
    "NIFTY NEXT 50": "NIFTYNXT50",
    "NIFTY MIDCAP SELECT": "MIDCPNIFTY",
    "INDIA VIX": "INDIAVIX",
    "SENSEX": "SENSEX",
    "BANKEX": "BANKEX",
    "SENSEX50": "SENSEX50",
}

# Month abbreviations for parsing DDMMMYY
_MONTH_ABBR = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}

# Regex: DDMMMYY e.g. 28MAR24, 3APR25
_DDMMMYY_RE = re.compile(r"(\d{1,2})([A-Z]{3})(\d{2})")

# Regex: trailing number (possibly decimal) before CE/PE
_STRIKE_RE = re.compile(r"(\d+(?:\.\d+)?)$")

# Regex: full option symbol — base + DDMMMYY + strike + CE/PE
_OPTION_RE = re.compile(
    r"^(?P<base>[A-Z&]+?)(?P<dd>\d{1,2})(?P<mmm>[A-Z]{3})(?P<yy>\d{2})"
    r"(?P<strike>\d+(?:\.\d+)?)(?P<ot>CE|PE)$"
)

# Regex: full futures symbol — base + DDMMMYY + FUT
_FUTURE_RE = re.compile(
    r"^(?P<base>[A-Z&]+?)(?P<dd>\d{1,2})(?P<mmm>[A-Z]{3})(?P<yy>\d{2})FUT$"
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def format_expiry_date(dt: date) -> str:
    """Format a ``date`` object into OpenAlgo's ``DDMMMYY`` string.

    Args:
        dt: The expiry date.

    Returns:
        Upper-case string like ``28MAR24``.

    Examples:
        >>> from datetime import date
        >>> format_expiry_date(date(2024, 3, 28))
        '28MAR24'
        >>> format_expiry_date(date(2025, 1, 3))
        '03JAN25'
    """
    return dt.strftime("%d%b%y").upper()


def parse_expiry_date(s: str) -> date:
    """Parse a ``DDMMMYY`` string into a ``date`` object.

    Args:
        s: Expiry string like ``28MAR24``.

    Returns:
        A ``datetime.date``.

    Raises:
        ValueError: If the string does not match DDMMMYY format.
    """
    m = _DDMMMYY_RE.fullmatch(s)
    if not m:
        raise ValueError(f"Invalid expiry date format: {s!r} (expected DDMMMYY)")
    day = int(m.group(1))
    month = _MONTH_ABBR.get(m.group(2))
    if month is None:
        raise ValueError(f"Unknown month abbreviation: {m.group(2)!r}")
    year = 2000 + int(m.group(3))
    return date(year, month, day)


def normalise_base(raw: str) -> str:
    """Normalise a broker-specific base symbol to the OpenAlgo canonical form.

    Args:
        raw: Raw base symbol from the broker (e.g. ``NIFTY 50``).

    Returns:
        Canonical OpenAlgo base symbol (e.g. ``NIFTY``).
    """
    upper = raw.strip().upper()
    if upper in SYMBOL_ALIASES:
        return SYMBOL_ALIASES[upper]
    # Strip spaces, hyphens, underscores
    return upper.replace(" ", "").replace("-", "").replace("_", "")


def build_openalgo_symbol(
    base: str,
    expiry: Optional[date] = None,
    strike: Optional[float] = None,
    option_type: Optional[str] = None,
) -> str:
    """Build an OpenAlgo symbol string from its components.

    Args:
        base: The underlying name (e.g. ``NIFTY``, ``RELIANCE``).
        expiry: Expiry date (omit for equities).
        strike: Strike price (omit for equities / futures).
        option_type: ``CE`` or ``PE`` (omit for equities / futures).

    Returns:
        OpenAlgo-formatted symbol string.

    Raises:
        ValueError: If option_type is given without a strike/expiry, or
                    if option_type is not CE/PE.

    Examples:
        >>> build_openalgo_symbol("NIFTY")
        'NIFTY'
        >>> from datetime import date
        >>> build_openalgo_symbol("NIFTY", date(2024, 3, 28))
        'NIFTY28MAR24FUT'
        >>> build_openalgo_symbol("NIFTY", date(2024, 3, 28), 20800, "CE")
        'NIFTY28MAR2420800CE'
        >>> build_openalgo_symbol("USDINR", date(2024, 3, 28), 85.50, "CE")
        'USDINR28MAR2485.5CE'
    """
    canonical = normalise_base(base)

    # Equity — no expiry
    if expiry is None:
        if strike is not None or option_type is not None:
            raise ValueError("Cannot specify strike/option_type without an expiry")
        return canonical

    exp_str = format_expiry_date(expiry)

    # Future — expiry but no strike
    if strike is None and option_type is None:
        return f"{canonical}{exp_str}FUT"

    # Option — expiry + strike + option_type
    if option_type is None or strike is None:
        raise ValueError("Both strike and option_type are required for options")
    ot = option_type.upper()
    if ot not in ("CE", "PE"):
        raise ValueError(f"option_type must be CE or PE, got {ot!r}")

    # Format strike: integer if whole, decimal otherwise
    if strike == int(strike):
        strike_str = str(int(strike))
    else:
        strike_str = str(strike)

    return f"{canonical}{exp_str}{strike_str}{ot}"


def parse_openalgo_symbol(symbol: str) -> SymbolParts:
    """Parse an OpenAlgo symbol string into its constituent parts.

    Handles equity, futures, and options (including decimal strikes for CDS).

    Args:
        symbol: An OpenAlgo-format symbol (e.g. ``NIFTY28MAR2420800CE``).

    Returns:
        A ``SymbolParts`` dataclass with parsed fields.

    Raises:
        ValueError: If the symbol cannot be parsed.

    Examples:
        >>> parts = parse_openalgo_symbol("NIFTY28MAR2420800CE")
        >>> parts.base
        'NIFTY'
        >>> parts.strike
        20800.0
        >>> parts.option_type
        'CE'
    """
    sym = symbol.strip().upper()

    # --- Futures: ...FUT ---
    m = _FUTURE_RE.match(sym)
    if m:
        exp = _build_date(m.group("dd"), m.group("mmm"), m.group("yy"))
        return SymbolParts(
            base=m.group("base"),
            instrument_type=InstrumentType.FUT,
            expiry_date=exp,
            original=symbol,
        )

    # --- Options: ...CE or ...PE ---
    m = _OPTION_RE.match(sym)
    if m:
        exp = _build_date(m.group("dd"), m.group("mmm"), m.group("yy"))
        strike = float(m.group("strike"))
        ot = m.group("ot")
        return SymbolParts(
            base=m.group("base"),
            instrument_type=InstrumentType.CE if ot == "CE" else InstrumentType.PE,
            expiry_date=exp,
            strike=strike,
            option_type=ot,
            original=symbol,
        )

    # --- Equity / Index (plain name, no date pattern) ---
    if re.fullmatch(r"[A-Z&]+", sym):
        return SymbolParts(
            base=sym,
            instrument_type=InstrumentType.EQ,
            original=symbol,
        )

    raise ValueError(f"Cannot parse OpenAlgo symbol: {symbol!r}")


def detect_segment(symbol: str, exchange: str = "") -> Segment:
    """Infer the exchange segment from symbol + exchange hint.

    Args:
        symbol: OpenAlgo-format symbol string.
        exchange: Optional exchange code (e.g. ``NSE``, ``MCX``, ``CDS``).

    Returns:
        The most likely ``Segment`` enum value.
    """
    exch = exchange.strip().upper()
    if exch in ("MCX", "NCDEX"):
        return Segment.MCX
    if exch in ("CDS", "BCD"):
        return Segment.CDS
    if exch == "BFO":
        return Segment.BFO
    if exch in ("NSE_INDEX", "BSE_INDEX"):
        return Segment.IDX

    # Infer from the symbol itself
    try:
        parts = parse_openalgo_symbol(symbol)
    except ValueError:
        return Segment.EQ

    if parts.instrument_type == InstrumentType.EQ:
        return Segment.EQ
    if exch in ("NFO", "NSE"):
        return Segment.FO
    if exch in ("BSE", "BFO"):
        return Segment.BFO

    # Default: FO for derivatives, EQ for plain symbols
    return Segment.FO if parts.instrument_type != InstrumentType.EQ else Segment.EQ


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _build_date(dd: str, mmm: str, yy: str) -> date:
    """Construct a ``date`` from DDMMMYY components."""
    month = _MONTH_ABBR.get(mmm)
    if month is None:
        raise ValueError(f"Unknown month: {mmm!r}")
    return date(2000 + int(yy), month, int(dd))
