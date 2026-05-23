"""Tests for packages/core/core/src/number_formatter.py.

Covers: format_indian, format_lakhs, format_currency, format_percentage,
        format_large_number.  12 tests total.
"""

from __future__ import annotations



from flinttrade_core.number_formatter import (
    format_currency,
    format_indian,
    format_lakhs,
    format_large_number,
    format_percentage,
)


# ---------------------------------------------------------------------------
# format_indian
# ---------------------------------------------------------------------------


def test_format_indian_crore_range() -> None:
    """12345678.5 formats with Indian grouping."""
    assert format_indian(12345678.5) == "1,23,45,678.50"


def test_format_indian_thousands() -> None:
    """1000 formats as 1,000.00."""
    assert format_indian(1000) == "1,000.00"


def test_format_indian_negative() -> None:
    """Negative values include a leading minus sign."""
    assert format_indian(-9876543.21, 2) == "-98,76,543.21"


def test_format_indian_zero_decimal_places() -> None:
    """decimal_places=0 omits the fractional part."""
    assert format_indian(12345678.0, 0) == "1,23,45,678"


def test_format_indian_small_value() -> None:
    """Values below 1000 format without commas."""
    assert format_indian(0.5, 2) == "0.50"


def test_format_indian_exact_lakh() -> None:
    """100000 → '1,00,000.00'."""
    assert format_indian(100000.0) == "1,00,000.00"


def test_format_indian_nan() -> None:
    """NaN passes through as 'nan'."""
    result = format_indian(float("nan"))
    assert result == "nan"


def test_format_indian_inf() -> None:
    """Infinity passes through."""
    result = format_indian(float("inf"))
    assert result == "inf"


# ---------------------------------------------------------------------------
# format_lakhs
# ---------------------------------------------------------------------------


def test_format_lakhs_crore() -> None:
    """Values >= 1 Cr show 'Cr' suffix."""
    assert format_lakhs(12345678) == "1.23 Cr"


def test_format_lakhs_lakh() -> None:
    """Values >= 1 L (< 1 Cr) show 'L' suffix."""
    assert format_lakhs(123456) == "1.23 L"


def test_format_lakhs_below_lakh() -> None:
    """Values < 1 L fall back to format_indian."""
    result = format_lakhs(9999)
    assert result == "9,999.00"


def test_format_lakhs_negative_crore() -> None:
    """Negative crore values include minus prefix."""
    assert format_lakhs(-50000000) == "-5.00 Cr"


# ---------------------------------------------------------------------------
# format_currency
# ---------------------------------------------------------------------------


def test_format_currency_inr() -> None:
    """INR uses ₹ prefix and Indian grouping."""
    result = format_currency(12345678.5)
    assert result.startswith("₹")
    assert "1,23,45,678.50" in result


def test_format_currency_usd() -> None:
    """USD uses $ prefix and standard grouping."""
    result = format_currency(12345.67, "USD")
    assert result.startswith("$")
    assert "12,345.67" in result


def test_format_currency_negative_eur() -> None:
    """Negative EUR value shows minus in amount."""
    result = format_currency(-1000.0, "EUR")
    assert "€" in result
    assert "-" in result


# ---------------------------------------------------------------------------
# format_percentage
# ---------------------------------------------------------------------------


def test_format_percentage_basic() -> None:
    """5.25 → '5.25%'."""
    assert format_percentage(5.25) == "5.25%"


def test_format_percentage_negative() -> None:
    """Negative percentages include minus sign."""
    assert format_percentage(-2.5, 1) == "-2.5%"


def test_format_percentage_zero_decimal() -> None:
    """decimal_places=0 omits fraction."""
    assert format_percentage(100.0, 0) == "100%"


# ---------------------------------------------------------------------------
# format_large_number
# ---------------------------------------------------------------------------


def test_format_large_number_million() -> None:
    """1234567 → '1.2M'."""
    assert format_large_number(1234567) == "1.2M"


def test_format_large_number_billion() -> None:
    """9876543210 → '9.9B'."""
    assert format_large_number(9876543210) == "9.9B"


def test_format_large_number_kilo() -> None:
    """12345 → '12.3K'."""
    assert format_large_number(12345) == "12.3K"


def test_format_large_number_below_1000() -> None:
    """Values < 1000 return plain integer string."""
    assert format_large_number(999) == "999"


def test_format_large_number_negative() -> None:
    """Negative millions include minus prefix."""
    assert format_large_number(-5000000) == "-5.0M"


def test_format_large_number_zero() -> None:
    """Zero returns '0'."""
    assert format_large_number(0) == "0"
