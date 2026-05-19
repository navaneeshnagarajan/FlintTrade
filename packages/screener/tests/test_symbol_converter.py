"""Tests for the OpenAlgo symbol converter.

All tests use synthetic data — no API calls or broker connections required.
"""

from __future__ import annotations

from datetime import date

import pytest

from packages.screener.src.symbol_converter import (
    InstrumentType,
    Segment,
    build_openalgo_symbol,
    detect_segment,
    format_expiry_date,
    normalise_base,
    parse_expiry_date,
    parse_openalgo_symbol,
)


# ---------------------------------------------------------------------------
# format_expiry_date
# ---------------------------------------------------------------------------

class TestFormatExpiryDate:
    """Tests for format_expiry_date."""

    def test_standard_date(self) -> None:
        assert format_expiry_date(date(2024, 3, 28)) == "28MAR24"

    def test_single_digit_day(self) -> None:
        assert format_expiry_date(date(2025, 1, 3)) == "03JAN25"

    def test_december(self) -> None:
        assert format_expiry_date(date(2026, 12, 25)) == "25DEC26"

    def test_february(self) -> None:
        assert format_expiry_date(date(2024, 2, 29)) == "29FEB24"


# ---------------------------------------------------------------------------
# parse_expiry_date
# ---------------------------------------------------------------------------

class TestParseExpiryDate:
    """Tests for parse_expiry_date."""

    def test_roundtrip(self) -> None:
        d = date(2024, 3, 28)
        assert parse_expiry_date(format_expiry_date(d)) == d

    def test_single_digit_day(self) -> None:
        assert parse_expiry_date("3APR25") == date(2025, 4, 3)

    def test_double_digit_day(self) -> None:
        assert parse_expiry_date("28MAR24") == date(2024, 3, 28)

    def test_invalid_format(self) -> None:
        with pytest.raises(ValueError, match="Invalid expiry date"):
            parse_expiry_date("2024-03-28")

    def test_invalid_month(self) -> None:
        with pytest.raises(ValueError, match="Unknown month"):
            parse_expiry_date("28XXX24")


# ---------------------------------------------------------------------------
# normalise_base
# ---------------------------------------------------------------------------

class TestNormaliseBase:
    """Tests for normalise_base."""

    def test_nifty_50_alias(self) -> None:
        assert normalise_base("NIFTY 50") == "NIFTY"

    def test_bank_nifty_alias(self) -> None:
        assert normalise_base("NIFTY BANK") == "BANKNIFTY"

    def test_finnifty_alias(self) -> None:
        assert normalise_base("NIFTY FINANCIAL SERVICES") == "FINNIFTY"

    def test_passthrough(self) -> None:
        assert normalise_base("RELIANCE") == "RELIANCE"

    def test_strip_whitespace(self) -> None:
        assert normalise_base("  TCS  ") == "TCS"

    def test_lowercase_converted(self) -> None:
        assert normalise_base("infy") == "INFY"


# ---------------------------------------------------------------------------
# build_openalgo_symbol
# ---------------------------------------------------------------------------

class TestBuildSymbol:
    """Tests for build_openalgo_symbol."""

    def test_equity(self) -> None:
        assert build_openalgo_symbol("RELIANCE") == "RELIANCE"

    def test_future(self) -> None:
        assert build_openalgo_symbol("NIFTY", date(2024, 3, 28)) == "NIFTY28MAR24FUT"

    def test_call_option(self) -> None:
        result = build_openalgo_symbol("NIFTY", date(2024, 3, 28), 20800, "CE")
        assert result == "NIFTY28MAR2420800CE"

    def test_put_option(self) -> None:
        result = build_openalgo_symbol("BANKNIFTY", date(2024, 3, 28), 48000, "PE")
        assert result == "BANKNIFTY28MAR2448000PE"

    def test_decimal_strike_cds(self) -> None:
        result = build_openalgo_symbol("USDINR", date(2024, 3, 28), 85.50, "CE")
        assert result == "USDINR28MAR2485.5CE"

    def test_mcx_commodity(self) -> None:
        result = build_openalgo_symbol("CRUDEOIL", date(2024, 3, 28), 9000, "CE")
        assert result == "CRUDEOIL28MAR249000CE"

    def test_stock_option(self) -> None:
        result = build_openalgo_symbol("RELIANCE", date(2025, 4, 24), 2800, "CE")
        assert result == "RELIANCE24APR252800CE"

    def test_alias_resolution(self) -> None:
        result = build_openalgo_symbol("NIFTY 50", date(2024, 3, 28))
        assert result == "NIFTY28MAR24FUT"

    def test_strike_without_expiry_raises(self) -> None:
        with pytest.raises(ValueError, match="Cannot specify strike"):
            build_openalgo_symbol("NIFTY", strike=20800)

    def test_option_type_without_strike_raises(self) -> None:
        with pytest.raises(ValueError, match="Both strike and option_type"):
            build_openalgo_symbol("NIFTY", date(2024, 3, 28), option_type="CE")

    def test_invalid_option_type_raises(self) -> None:
        with pytest.raises(ValueError, match="option_type must be CE or PE"):
            build_openalgo_symbol("NIFTY", date(2024, 3, 28), 20800, "XX")


# ---------------------------------------------------------------------------
# parse_openalgo_symbol
# ---------------------------------------------------------------------------

class TestParseSymbol:
    """Tests for parse_openalgo_symbol."""

    def test_equity(self) -> None:
        parts = parse_openalgo_symbol("RELIANCE")
        assert parts.base == "RELIANCE"
        assert parts.instrument_type == InstrumentType.EQ
        assert parts.expiry_date is None
        assert parts.strike is None

    def test_future(self) -> None:
        parts = parse_openalgo_symbol("NIFTY28MAR24FUT")
        assert parts.base == "NIFTY"
        assert parts.instrument_type == InstrumentType.FUT
        assert parts.expiry_date == date(2024, 3, 28)
        assert parts.strike is None

    def test_call_option(self) -> None:
        parts = parse_openalgo_symbol("NIFTY28MAR2420800CE")
        assert parts.base == "NIFTY"
        assert parts.instrument_type == InstrumentType.CE
        assert parts.expiry_date == date(2024, 3, 28)
        assert parts.strike == 20800.0
        assert parts.option_type == "CE"

    def test_put_option(self) -> None:
        parts = parse_openalgo_symbol("BANKNIFTY28MAR2448000PE")
        assert parts.base == "BANKNIFTY"
        assert parts.instrument_type == InstrumentType.PE
        assert parts.expiry_date == date(2024, 3, 28)
        assert parts.strike == 48000.0
        assert parts.option_type == "PE"

    def test_cds_decimal_strike(self) -> None:
        parts = parse_openalgo_symbol("USDINR28MAR2485.5CE")
        assert parts.base == "USDINR"
        assert parts.strike == 85.5
        assert parts.option_type == "CE"

    def test_mcx_option(self) -> None:
        parts = parse_openalgo_symbol("CRUDEOIL28MAR249000CE")
        assert parts.base == "CRUDEOIL"
        assert parts.strike == 9000.0
        assert parts.expiry_date == date(2024, 3, 28)

    def test_single_digit_day(self) -> None:
        parts = parse_openalgo_symbol("NIFTY3APR2520800CE")
        assert parts.base == "NIFTY"
        assert parts.expiry_date == date(2025, 4, 3)
        assert parts.strike == 20800.0

    def test_stock_future(self) -> None:
        parts = parse_openalgo_symbol("RELIANCE28MAR24FUT")
        assert parts.base == "RELIANCE"
        assert parts.instrument_type == InstrumentType.FUT

    def test_invalid_symbol_raises(self) -> None:
        with pytest.raises(ValueError, match="Cannot parse"):
            parse_openalgo_symbol("12345INVALID")

    def test_original_preserved(self) -> None:
        parts = parse_openalgo_symbol("NIFTY28MAR2420800CE")
        assert parts.original == "NIFTY28MAR2420800CE"


# ---------------------------------------------------------------------------
# Roundtrip: build → parse → build
# ---------------------------------------------------------------------------

class TestRoundtrip:
    """Verify that build → parse → build produces the same symbol."""

    @pytest.mark.parametrize(
        "base, expiry, strike, option_type",
        [
            ("NIFTY", date(2024, 3, 28), 20800, "CE"),
            ("BANKNIFTY", date(2025, 6, 26), 55000, "PE"),
            ("USDINR", date(2024, 3, 28), 85.5, "CE"),
            ("CRUDEOIL", date(2024, 9, 19), 7500, "PE"),
            ("RELIANCE", date(2025, 4, 24), 2800, "CE"),
        ],
    )
    def test_option_roundtrip(
        self,
        base: str,
        expiry: date,
        strike: float,
        option_type: str,
    ) -> None:
        sym = build_openalgo_symbol(base, expiry, strike, option_type)
        parts = parse_openalgo_symbol(sym)
        rebuilt = build_openalgo_symbol(parts.base, parts.expiry_date, parts.strike, parts.option_type)
        assert rebuilt == sym

    @pytest.mark.parametrize(
        "base, expiry",
        [
            ("NIFTY", date(2024, 3, 28)),
            ("RELIANCE", date(2025, 1, 30)),
        ],
    )
    def test_future_roundtrip(self, base: str, expiry: date) -> None:
        sym = build_openalgo_symbol(base, expiry)
        parts = parse_openalgo_symbol(sym)
        rebuilt = build_openalgo_symbol(parts.base, parts.expiry_date)
        assert rebuilt == sym

    def test_equity_roundtrip(self) -> None:
        sym = build_openalgo_symbol("TCS")
        parts = parse_openalgo_symbol(sym)
        rebuilt = build_openalgo_symbol(parts.base)
        assert rebuilt == sym


# ---------------------------------------------------------------------------
# detect_segment
# ---------------------------------------------------------------------------

class TestDetectSegment:
    """Tests for detect_segment."""

    def test_mcx_exchange(self) -> None:
        assert detect_segment("CRUDEOIL28MAR249000CE", "MCX") == Segment.MCX

    def test_cds_exchange(self) -> None:
        assert detect_segment("USDINR28MAR2485.5CE", "CDS") == Segment.CDS

    def test_nfo_exchange(self) -> None:
        assert detect_segment("NIFTY28MAR2420800CE", "NFO") == Segment.FO

    def test_index_exchange(self) -> None:
        assert detect_segment("NIFTY", "NSE_INDEX") == Segment.IDX

    def test_plain_equity(self) -> None:
        assert detect_segment("RELIANCE", "NSE") == Segment.EQ

    def test_bfo_exchange(self) -> None:
        assert detect_segment("SENSEX28MAR2475000CE", "BFO") == Segment.BFO
