"""Strict balance primitives shared by native broker response converters."""

from __future__ import annotations

import math

from flinttrade_core.broker_read_port import BrokerBalanceResponseInvalid


def _balance_number(value: object) -> float:
    if isinstance(value, bool) or type(value) not in (int, float, str) or (type(value) is str and not value.strip()):
        raise BrokerBalanceResponseInvalid
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        raise BrokerBalanceResponseInvalid from None
    if not math.isfinite(number):
        raise BrokerBalanceResponseInvalid
    return number


def _balance_record(value: object) -> dict[str, object]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise BrokerBalanceResponseInvalid
    return value
