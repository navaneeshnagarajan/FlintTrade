"""Immutable units, prices and budget evidence for provider admission.

Money and provider credits use millionths of the named unit. Time uses integer
milliseconds; bytes and tokens are exact integers. No price discovery or I/O.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, fields
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any

from .service_connections import INT64_MAX, ServiceConnectionRef

USAGE_DIMENSIONS = (
    "requests",
    "input_tokens",
    "output_tokens",
    "currency_micros",
    "credits_micros",
    "compute_milliseconds",
    "bytes",
    "concurrency",
    "storage_bytes",
)
_PRICE_DIMENSIONS = frozenset(USAGE_DIMENSIONS) - {"currency_micros", "credits_micros", "concurrency"}


def integer(value: object, name: str, *, minimum: int = 0) -> int:
    """Reject coercion and non-finite or out-of-range quantities."""
    if type(value) is not int or not minimum <= value <= INT64_MAX:
        raise ValueError(f"{name} must be an integer in {minimum}..INT64_MAX")
    return value


def text(value: object, name: str) -> str:
    """Validate bounded identifiers and evidence labels, never credential bodies."""
    if type(value) is not str or not value.strip() or len(value) > 1024 or any(ord(c) < 32 for c in value):
        raise ValueError(f"{name} must be bounded non-blank text")
    return value


def utc(value: object) -> datetime:
    """Require an unambiguous UTC instant."""
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("timestamps must be UTC datetimes")
    return value.replace(tzinfo=UTC)


def canonical(value: object) -> str:
    """Stable encoding for digests and durable equality checks."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _currency(value: object) -> None:
    if type(value) is not str or not re.fullmatch(r"[A-Z][A-Z0-9_-]{1,31}", value):
        raise ValueError("currency must be an explicit uppercase currency or provider-credit unit")


@dataclass(frozen=True, slots=True)
class UsageAmounts:
    """All supported accounting dimensions; omitted dimensions are exactly zero."""

    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    currency_micros: int = 0
    credits_micros: int = 0
    compute_milliseconds: int = 0
    bytes: int = 0
    concurrency: int = 0
    storage_bytes: int = 0

    def __post_init__(self) -> None:
        for item in fields(self):
            integer(getattr(self, item.name), item.name)

    def to_dict(self) -> dict[str, int]:
        """Return a detached JSON-ready unit vector."""
        return {name: getattr(self, name) for name in USAGE_DIMENSIONS}


@dataclass(frozen=True, slots=True)
class UnitPrice:
    """Integer micro-units payable per ``units`` of one billable dimension."""

    micros: int
    units: int = 1

    def __post_init__(self) -> None:
        integer(self.micros, "micros")
        integer(self.units, "units", minimum=1)


@dataclass(frozen=True, slots=True)
class ExchangeRate:
    """Exact target/source ratio and evidence for an optional display projection."""

    target_currency: str
    numerator: int
    denominator: int
    source: str
    observed_at: datetime

    def __post_init__(self) -> None:
        _currency(self.target_currency)
        integer(self.numerator, "numerator", minimum=1)
        integer(self.denominator, "denominator", minimum=1)
        text(self.source, "FX source")
        object.__setattr__(self, "observed_at", utc(self.observed_at))

    def to_dict(self) -> dict[str, Any]:
        """Detach immutable FX evidence."""
        return {
            "target_currency": self.target_currency,
            "numerator": self.numerator,
            "denominator": self.denominator,
            "source": self.source,
            "observed_at": self.observed_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class TariffSnapshot:
    """Exact billed route and immutable pricing evidence.

    ``prices=None`` means unknown; ``{}`` is an explicitly evidenced free
    tariff. Unlisted dimensions are not billable under a known tariff. Rounding
    is ceiling per dimension, then one ceiling after multiplicative markup/tax.
    FX is retained for display only: accounting stays in the source currency.
    """

    provider_id: str
    model: str
    model_revision: str
    source_kind: str
    source: str
    currency: str
    effective_from: datetime
    effective_until: datetime
    prices: Mapping[str, UnitPrice] | None
    price_dimension: str = "currency_micros"
    rounding: str = "ceil_per_dimension_then_total"
    markup_basis_points: int = 0
    tax_basis_points: int = 0
    exchange_rate: ExchangeRate | None = None

    def __post_init__(self) -> None:
        for name in ("provider_id", "model", "model_revision", "source"):
            text(getattr(self, name), name)
        if self.source_kind not in {"operator", "authoritative"}:
            raise ValueError("unsupported tariff source kind")
        _currency(self.currency)
        object.__setattr__(self, "effective_from", utc(self.effective_from))
        object.__setattr__(self, "effective_until", utc(self.effective_until))
        if self.effective_until <= self.effective_from:
            raise ValueError("empty tariff interval")
        if self.rounding != "ceil_per_dimension_then_total":
            raise ValueError("unsupported rounding policy")
        if self.price_dimension not in {"currency_micros", "credits_micros"}:
            raise ValueError("unsupported tariff price dimension")
        integer(self.markup_basis_points, "markup_basis_points")
        integer(self.tax_basis_points, "tax_basis_points")
        if self.exchange_rate is not None and type(self.exchange_rate) is not ExchangeRate:
            raise ValueError("invalid exchange-rate evidence")
        if self.prices is not None:
            if not isinstance(self.prices, Mapping):
                raise ValueError("prices must be a mapping or unknown")
            prices = dict(self.prices)
            if any(
                type(k) is not str or k not in _PRICE_DIMENSIONS or type(v) is not UnitPrice for k, v in prices.items()
            ):
                raise ValueError("unsupported price dimension or unit price")
            object.__setattr__(self, "prices", MappingProxyType(prices))

    def quote(self, usage: UsageAmounts) -> int:
        """Compute conservative micro-unit cost without binary floating point."""
        if type(usage) is not UsageAmounts or self.prices is None:
            raise ValueError("known prices and exact usage units are required")
        subtotal = sum(
            (getattr(usage, key) * price.micros + price.units - 1) // price.units for key, price in self.prices.items()
        )
        numerator = subtotal * (10000 + self.markup_basis_points) * (10000 + self.tax_basis_points)
        return integer((numerator + 100_000_000 - 1) // 100_000_000, "quoted cost")

    def to_dict(self) -> dict[str, Any]:
        """Return exact digest material as a detached value."""
        return {
            "provider_id": self.provider_id,
            "model": self.model,
            "model_revision": self.model_revision,
            "source_kind": self.source_kind,
            "source": self.source,
            "currency": self.currency,
            "effective_from": self.effective_from.isoformat(),
            "effective_until": self.effective_until.isoformat(),
            "prices": None
            if self.prices is None
            else {key: {"micros": price.micros, "units": price.units} for key, price in self.prices.items()},
            "price_dimension": self.price_dimension,
            "rounding": self.rounding,
            "markup_basis_points": self.markup_basis_points,
            "tax_basis_points": self.tax_basis_points,
            "exchange_rate": self.exchange_rate.to_dict() if self.exchange_rate else None,
        }

    @property
    def digest(self) -> str:
        """SHA-256 identity, independent of mapping insertion order."""
        return hashlib.sha256(canonical(self.to_dict()).encode()).hexdigest()

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> TariffSnapshot:
        """Validate and reconstruct stored tariff evidence."""
        values = dict(value)
        for name in ("effective_from", "effective_until"):
            values[name] = datetime.fromisoformat(values[name])
        if values["prices"] is not None:
            values["prices"] = {key: UnitPrice(**price) for key, price in values["prices"].items()}
        if values["exchange_rate"] is not None:
            fx = dict(values["exchange_rate"])
            fx["observed_at"] = datetime.fromisoformat(fx["observed_at"])
            values["exchange_rate"] = ExchangeRate(**fx)
        return cls(**values)


@dataclass(frozen=True, slots=True)
class BudgetPolicy:
    """Connection-wide ceilings for one explicit half-open UTC interval.

    Missing limits are unrestricted; supplied unsupported dimensions are errors.
    Concurrency counts outstanding attempts across all periods. Storage remains
    conservatively charged across periods; this authority has no implicit file
    deletion refund. Other dimensions count the current period plus unresolved
    reservations from earlier periods. A current period cannot be shortened.
    """

    connection: ServiceConnectionRef
    currency: str
    window_start: datetime
    window_end: datetime
    limits: Mapping[str, int]

    def __post_init__(self) -> None:
        if type(self.connection) is not ServiceConnectionRef:
            raise ValueError("exact canonical connection required")
        _currency(self.currency)
        object.__setattr__(self, "window_start", utc(self.window_start))
        object.__setattr__(self, "window_end", utc(self.window_end))
        if self.window_end <= self.window_start:
            raise ValueError("empty budget interval")
        if not isinstance(self.limits, Mapping) or not self.limits:
            raise ValueError("at least one explicit budget ceiling is required")
        limits = dict(self.limits)
        for name, amount in limits.items():
            if type(name) is not str or name not in USAGE_DIMENSIONS:
                raise ValueError("unsupported budget dimension")
            integer(amount, name)
        object.__setattr__(self, "limits", MappingProxyType(limits))

    def to_dict(self) -> dict[str, Any]:
        """Detach operator budget policy."""
        return {
            "connection": self.connection.to_dict(),
            "currency": self.currency,
            "window_start": self.window_start.isoformat(),
            "window_end": self.window_end.isoformat(),
            "limits": dict(self.limits),
        }
