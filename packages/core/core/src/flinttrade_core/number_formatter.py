"""Indian locale number formatting utilities for FlintTrade.

Implements the Indian numbering system (lakhs and crores) used throughout
the FlintTrade UI for fund balances, P&L, market cap, and open interest.

Indian numbering recap
----------------------
* 1,000          — one thousand
* 1,00,000       — one lakh  (10^5)
* 1,00,00,000    — one crore (10^7)
* Grouping: last three digits, then groups of two from the right.

All functions accept ``float`` (or anything coercible to it) and return
``str``.  None values are returned as ``"—"`` (em-dash, standard in Indian
financial displays).
"""

from __future__ import annotations

import math


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _indian_int_part(n: int) -> str:
    """Format a non-negative integer using Indian grouping.

    Args:
        n: Non-negative integer.

    Returns:
        Comma-separated string with Indian grouping.

    Examples::

        _indian_int_part(12345678)   # → "1,23,45,678"
        _indian_int_part(1000)       # → "1,000"
        _indian_int_part(0)          # → "0"
    """
    s = str(n)
    if len(s) <= 3:
        return s
    # Last 3 digits form the first group
    result = s[-3:]
    s = s[:-3]
    # Remaining digits in groups of 2 from the right
    while len(s) > 2:
        result = s[-2:] + "," + result
        s = s[:-2]
    result = s + "," + result
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def format_indian(value: float, decimal_places: int = 2) -> str:
    """Format *value* using the Indian numbering system.

    Args:
        value: Numeric value to format.
        decimal_places: Number of decimal places (default 2).

    Returns:
        Formatted string with Indian grouping, e.g. ``"1,23,45,678.50"``.

    Examples::

        format_indian(12345678.5)      # → "1,23,45,678.50"
        format_indian(1000)            # → "1,000.00"
        format_indian(-9876543.21, 2)  # → "-98,76,543.21"
        format_indian(0.5, 2)          # → "0.50"
    """
    if math.isnan(value) or math.isinf(value):
        return str(value)

    negative = value < 0
    abs_value = abs(value)

    int_part = int(abs_value)
    frac = abs_value - int_part

    formatted_int = _indian_int_part(int_part)

    if decimal_places > 0:
        # Round fraction to avoid floating-point drift
        frac_rounded = round(frac, decimal_places)
        # Edge case: rounding pushed frac to 1.0
        if frac_rounded >= 1.0:
            int_part += 1
            formatted_int = _indian_int_part(int_part)
            frac_rounded = 0.0
        frac_str = f"{frac_rounded:.{decimal_places}f}"[1:]  # strip leading "0"
        result = formatted_int + frac_str
    else:
        result = formatted_int

    return f"-{result}" if negative else result


def format_lakhs(value: float) -> str:
    """Format *value* as lakhs or crores with a compact suffix.

    Thresholds:

    * |value| >= 1 crore (1e7)  → ``"X.XX Cr"``
    * |value| >= 1 lakh  (1e5)  → ``"X.XX L"``
    * Otherwise                 → :func:`format_indian` with 2 decimal places

    Args:
        value: Numeric value in INR (or any unit).

    Returns:
        Compact formatted string.

    Examples::

        format_lakhs(12345678)    # → "1.23 Cr"
        format_lakhs(123456)      # → "1.23 L"
        format_lakhs(9999)        # → "9,999.00"
        format_lakhs(-50000000)   # → "-5.00 Cr"
    """
    if math.isnan(value) or math.isinf(value):
        return str(value)

    negative = value < 0
    abs_value = abs(value)

    if abs_value >= 1e7:
        compact = f"{abs_value / 1e7:.2f} Cr"
    elif abs_value >= 1e5:
        compact = f"{abs_value / 1e5:.2f} L"
    else:
        return format_indian(value, decimal_places=2)

    return f"-{compact}" if negative else compact


def format_currency(value: float, currency: str = "INR") -> str:
    """Format *value* as a currency amount with symbol prefix.

    Uses :func:`format_indian` for INR; uses standard grouping (``f"{value:,.2f}"``)
    for other currencies.

    Args:
        value: Numeric amount.
        currency: ISO 4217 currency code (default ``"INR"``).

    Returns:
        Currency-prefixed string, e.g. ``"₹ 1,23,45,678.50"`` or
        ``"$ 12,345.67"``.

    Examples::

        format_currency(12345678.5)           # → "₹ 1,23,45,678.50"
        format_currency(12345.67, "USD")      # → "$ 12,345.67"
        format_currency(-1000.0, "EUR")       # → "€ -1,000.00"
    """
    symbols: dict[str, str] = {
        "INR": "₹",
        "USD": "$",
        "EUR": "€",
        "GBP": "£",
        "JPY": "¥",
    }
    prefix = symbols.get(currency.upper(), currency.upper() + " ")

    if currency.upper() == "INR":
        formatted = format_indian(value, decimal_places=2)
    else:
        negative = value < 0
        formatted = f"{abs(value):,.2f}"
        if negative:
            formatted = f"-{formatted}"

    return f"{prefix} {formatted}"


def format_percentage(value: float, decimal_places: int = 2) -> str:
    """Format *value* as a percentage string.

    Args:
        value: Percentage value (e.g. ``5.25`` for 5.25%).
        decimal_places: Number of decimal places (default 2).

    Returns:
        Formatted percentage string with ``%`` suffix.

    Examples::

        format_percentage(5.25)      # → "5.25%"
        format_percentage(-2.5, 1)   # → "-2.5%"
        format_percentage(100.0, 0)  # → "100%"
    """
    if math.isnan(value) or math.isinf(value):
        return str(value)
    return f"{value:.{decimal_places}f}%"


def format_large_number(value: int) -> str:
    """Format a large integer with compact SI-style suffix.

    Intended for OI, volume, market cap, and similar large counts.

    Thresholds:

    * |value| >= 1,000,000,000 (1B) → ``"X.XB"``
    * |value| >= 1,000,000     (1M) → ``"X.XM"``
    * |value| >= 1,000         (1K) → ``"X.XK"``
    * Otherwise                     → plain integer string

    Args:
        value: Integer value (float accepted and truncated).

    Returns:
        Compact formatted string.

    Examples::

        format_large_number(1234567)   # → "1.2M"
        format_large_number(9876543210) # → "9.9B"
        format_large_number(12345)     # → "12.3K"
        format_large_number(999)       # → "999"
        format_large_number(-5000000)  # → "-5.0M"
    """
    n = int(value)
    negative = n < 0
    abs_n = abs(n)

    if abs_n >= 1_000_000_000:
        compact = f"{abs_n / 1_000_000_000:.1f}B"
    elif abs_n >= 1_000_000:
        compact = f"{abs_n / 1_000_000:.1f}M"
    elif abs_n >= 1_000:
        compact = f"{abs_n / 1_000:.1f}K"
    else:
        return f"-{abs_n}" if negative else str(abs_n)

    return f"-{compact}" if negative else compact
