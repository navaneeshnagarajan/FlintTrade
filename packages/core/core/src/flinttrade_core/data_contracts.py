"""Canonical data identity shared by historical and streaming readers.

These values describe observations, never trading authority. No provider,
calendar, currency or execution account is inferred from a ticker.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any


class DataIntegrityError(ValueError):
    """Input cannot establish the declared identity or observation."""


def canonical_json(value: Any) -> str:
    """Detach exact JSON values and prohibit nonfinite evidence."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def digest(value: Any) -> str:
    """Content identity of a canonical JSON observation."""
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def timestamp(value: Any) -> datetime:
    """Read an offset-aware observation time; naive timestamps are ambiguous."""
    if type(value) is not str:
        raise DataIntegrityError("timestamp must be an offset-aware ISO string")
    try:
        result = datetime.fromisoformat(value)
    except ValueError as exc:
        raise DataIntegrityError("invalid timestamp") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise DataIntegrityError("naive timestamp")
    return result.astimezone(UTC)


def text(value: Any, field: str) -> str:
    """Require explicit nonempty identity without repairing a supplied token."""
    if type(value) is not str or not value or value != value.strip() or len(value) > 256:
        raise DataIntegrityError(f"invalid {field}")
    return value


def generation(value: Any) -> int:
    """Generations are non-negative integers, not booleans or truncations."""
    if type(value) is not int or value < 0:
        raise DataIntegrityError("invalid generation")
    return value


def validate_identity(value: dict[str, Any]) -> dict[str, Any]:
    """Validate a fully qualified market series, including calendar and units."""
    fields = ("instrument_id", "venue", "asset_class", "currency", "quantity_unit", "price_unit",
              "adjustment", "calendar_id", "calendar_revision")
    result: dict[str, Any] = {key: text(value.get(key), key) for key in fields}
    interval = value.get("interval_seconds")
    if type(interval) is not int or interval <= 0:
        raise DataIntegrityError("invalid interval_seconds")
    try:
        multiplier = Decimal(text(value.get("multiplier"), "multiplier"))
    except InvalidOperation as exc:
        raise DataIntegrityError("invalid multiplier") from exc
    if not multiplier.is_finite() or multiplier <= 0:
        raise DataIntegrityError("invalid multiplier")
    result.update(interval_seconds=interval, multiplier=value["multiplier"])
    # Contract-specific identity (expiry, strike, right, native crosswalk, etc.)
    # is retained rather than lost when additional canonical fields are supplied.
    return json.loads(canonical_json({**value, **result}))


def validate_scope(value: dict[str, Any]) -> dict[str, Any]:
    """Bind data to the exact principal/environment/account/run generation."""
    result: dict[str, Any] = {key: text(value.get(key), key) for key in ("principal_id", "environment")}
    for key in ("account_id", "run_id"):
        if key not in value:
            raise DataIntegrityError(f"missing {key}")
        result[key] = None if value[key] is None else text(value[key], key)
    result["generation"] = generation(value.get("generation"))
    return result


def validate_source(value: dict[str, Any]) -> dict[str, Any]:
    """Identify one configured source and its non-secret authority versions."""
    result: dict[str, Any] = {key: text(value.get(key), key) for key in ("connection_id", "provider", "environment")}
    if "account_id" not in value:
        raise DataIntegrityError("missing source account_id")
    result["account_id"] = None if value["account_id"] is None else text(value["account_id"], "account_id")
    for key in ("auth_generation", "configuration_generation"):
        result[key] = generation(value.get(key))
    return result


def finite_number(value: Any, field: str, *, positive: bool = False) -> float:
    """Accept finite explicit numeric observations, preserving fractional units."""
    if type(value) not in (int, float) or not math.isfinite(value) or (positive and value <= 0):
        raise DataIntegrityError(f"invalid {field}")
    return float(value)


def validate_ohlcv(value: dict[str, Any]) -> dict[str, Any]:
    """Validate one whole bar, never invent absent volume or open interest."""
    result: dict[str, Any] = {"timestamp": timestamp(value.get("timestamp")).isoformat()}
    for key in ("open", "high", "low", "close"):
        result[key] = finite_number(value.get(key), key, positive=True)
    if not result["low"] <= min(result["open"], result["close"]) <= max(result["open"], result["close"]) <= result["high"]:
        raise DataIntegrityError("incoherent OHLC range")
    for key in ("volume", "oi"):
        number = value.get(key)
        if number is not None:
            number = finite_number(number, key)
            if number < 0:
                raise DataIntegrityError(f"negative {key}")
        result[key] = number
    published = value.get("published_at")
    result["published_at"] = None if published is None else timestamp(published).isoformat()
    return result
