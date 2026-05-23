"""Tests for packages/core/core/src/symbol_utils.py.

Covers: normalize_symbol, parse_option_symbol, parse_future_symbol,
        build_option_symbol, build_future_symbol, detect_instrument_type,
        exchange_segment.  25 tests total.
"""

from __future__ import annotations

import pytest

from flinttrade_core.symbol_utils import (
    FutureParts,
    OptionParts,
    build_future_symbol,
    build_option_symbol,
    detect_instrument_type,
    exchange_segment,
    normalize_symbol,
    parse_future_symbol,
    parse_option_symbol,
)


# ---------------------------------------------------------------------------
# normalize_symbol
# ---------------------------------------------------------------------------


def test_normalize_upper_case() -> None:
    """normalize_symbol upper-cases the symbol."""
    assert normalize_symbol("reliance") == "RELIANCE"


def test_normalize_nifty50_alias() -> None:
    """NIFTY50 → NIFTY."""
    assert normalize_symbol("NIFTY50") == "NIFTY"


def test_normalize_nifty_underscore() -> None:
    """NIFTY_50 → NIFTY."""
    assert normalize_symbol("NIFTY_50") == "NIFTY"


def test_normalize_nifty_hyphen() -> None:
    """NIFTY-50 → NIFTY."""
    assert normalize_symbol("NIFTY-50") == "NIFTY"


def test_normalize_banknifty_with_underscore() -> None:
    """BANK_NIFTY → BANKNIFTY."""
    assert normalize_symbol("BANK_NIFTY") == "BANKNIFTY"


def test_normalize_equity_unchanged() -> None:
    """Plain equity symbols pass through unchanged."""
    assert normalize_symbol("TCS") == "TCS"


def test_normalize_strips_whitespace() -> None:
    """Leading/trailing whitespace is stripped."""
    assert normalize_symbol("  NIFTY  ") == "NIFTY"


# ---------------------------------------------------------------------------
# parse_option_symbol
# ---------------------------------------------------------------------------


def test_parse_option_ce() -> None:
    """Parse a NIFTY CE option."""
    result = parse_option_symbol("NIFTY24APR25500CE")
    assert result is not None
    assert result.underlying == "NIFTY"
    assert "APR" in result.expiry
    assert result.strike == 500.0
    assert result.option_type == "CE"


def test_parse_option_pe() -> None:
    """Parse a BANKNIFTY PE option."""
    result = parse_option_symbol("BANKNIFTY24MAR2545000PE")
    assert result is not None
    assert result.underlying == "BANKNIFTY"
    assert result.strike == 45000.0
    assert result.option_type == "PE"


def test_parse_option_lower_case() -> None:
    """parse_option_symbol normalises to upper case."""
    result = parse_option_symbol("nifty24apr25500ce")
    assert result is not None
    assert result.option_type == "CE"


def test_parse_option_invalid_returns_none() -> None:
    """parse_option_symbol returns None for a non-option symbol."""
    assert parse_option_symbol("RELIANCE") is None


def test_parse_option_future_returns_none() -> None:
    """parse_option_symbol returns None for a futures symbol."""
    assert parse_option_symbol("NIFTY24APRFUT") is None


def test_parse_option_decimal_strike() -> None:
    """parse_option_symbol handles decimal strikes."""
    result = parse_option_symbol("USDINR24APR2583.5CE")
    assert result is not None
    assert result.strike == 83.5


def test_parse_option_returns_option_parts_type() -> None:
    """parse_option_symbol returns an OptionParts instance."""
    result = parse_option_symbol("NIFTY24APR25500CE")
    assert isinstance(result, OptionParts)


# ---------------------------------------------------------------------------
# parse_future_symbol
# ---------------------------------------------------------------------------


def test_parse_future_basic() -> None:
    """Parse a standard NIFTY futures symbol."""
    result = parse_future_symbol("NIFTY24APRFUT")
    assert result is not None
    assert result.underlying == "NIFTY"
    assert "APR" in result.expiry


def test_parse_future_with_full_date() -> None:
    """Parse a futures symbol with a day prefix."""
    result = parse_future_symbol("GOLD24APR25FUT")
    assert result is not None
    assert result.underlying == "GOLD"


def test_parse_future_invalid_returns_none() -> None:
    """parse_future_symbol returns None for a non-futures symbol."""
    assert parse_future_symbol("RELIANCE") is None


def test_parse_future_option_returns_none() -> None:
    """parse_future_symbol returns None for an option symbol."""
    assert parse_future_symbol("NIFTY24APR25500CE") is None


def test_parse_future_returns_future_parts_type() -> None:
    """parse_future_symbol returns a FutureParts instance."""
    result = parse_future_symbol("NIFTY24APRFUT")
    assert isinstance(result, FutureParts)


# ---------------------------------------------------------------------------
# build_option_symbol
# ---------------------------------------------------------------------------


def test_build_option_symbol_integer_strike() -> None:
    """build_option_symbol serialises integer strikes without .0."""
    sym = build_option_symbol("NIFTY", "24APR25", 22000.0, "CE")
    assert sym == "NIFTY24APR2522000CE"


def test_build_option_symbol_decimal_strike() -> None:
    """build_option_symbol keeps decimal strikes."""
    sym = build_option_symbol("USDINR", "24APR25", 83.5, "PE")
    assert sym == "USDINR24APR2583.5PE"


def test_build_option_symbol_upper_case() -> None:
    """build_option_symbol forces upper-case."""
    sym = build_option_symbol("nifty", "24apr25", 500.0, "ce")
    assert sym == "NIFTY24APR25500CE"


# ---------------------------------------------------------------------------
# build_future_symbol
# ---------------------------------------------------------------------------


def test_build_future_symbol() -> None:
    """build_future_symbol appends FUT suffix."""
    assert build_future_symbol("NIFTY", "24APR25") == "NIFTY24APR25FUT"


def test_build_future_symbol_upper_case() -> None:
    """build_future_symbol forces upper-case."""
    assert build_future_symbol("gold", "24apr25") == "GOLD24APR25FUT"


# ---------------------------------------------------------------------------
# detect_instrument_type
# ---------------------------------------------------------------------------


def test_detect_option() -> None:
    assert detect_instrument_type("NIFTY24APR25500CE") == "option"


def test_detect_future() -> None:
    assert detect_instrument_type("NIFTY24APRFUT") == "future"


def test_detect_index() -> None:
    assert detect_instrument_type("NIFTY") == "index"


def test_detect_equity() -> None:
    assert detect_instrument_type("RELIANCE") == "equity"


def test_detect_currency() -> None:
    assert detect_instrument_type("USDINR") == "currency"


# ---------------------------------------------------------------------------
# exchange_segment
# ---------------------------------------------------------------------------


def test_exchange_segment_nse() -> None:
    assert exchange_segment("NSE") == "EQ"


def test_exchange_segment_nfo() -> None:
    assert exchange_segment("NFO") == "FO"


def test_exchange_segment_nse_index() -> None:
    assert exchange_segment("NSE_INDEX") == "IDX"


def test_exchange_segment_mcx() -> None:
    assert exchange_segment("MCX") == "COM"


def test_exchange_segment_cds() -> None:
    assert exchange_segment("CDS") == "CD"


def test_exchange_segment_unknown_raises() -> None:
    """exchange_segment raises ValueError for an unknown exchange."""
    with pytest.raises(ValueError, match="Unknown exchange"):
        exchange_segment("UNKNOWN")


def test_exchange_segment_case_insensitive() -> None:
    """exchange_segment accepts lower-case input."""
    assert exchange_segment("nse") == "EQ"
