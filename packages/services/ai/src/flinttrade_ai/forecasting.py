"""Model-neutral forecast inputs and explicit provider shape admission.

These immutable contracts contain no model loader, credentials or execution
capability. Lineage digests reference separately verified evidence; their
presence alone grants no right to use a forecast for qualification or trading.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class MissingDataPolicy(StrEnum):
    """Missing values are rejected or passed explicitly to a capable model."""

    REJECT = "reject"
    MASK = "mask"


class UnsupportedForecastShape(ValueError):
    """A provider cannot consume the complete requested schema."""


def _text(value: object, name: str) -> None:
    if type(value) is not str or not value.strip() or len(value) > 256 or any(ord(c) < 32 for c in value):
        raise ValueError(f"{name} must be non-blank text of at most 256 characters")


def _utc(value: object) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("forecast timestamps must be timezone-aware UTC datetimes")
    return value.replace(tzinfo=UTC)


def _quantiles(values: tuple[float, ...]) -> tuple[float, ...]:
    result = tuple(values)
    if any(type(v) not in (int, float) or not math.isfinite(v) or not 0 < v < 1 for v in result):
        raise ValueError("quantiles must be finite numbers strictly between zero and one")
    if any(a >= b for a, b in zip(result, result[1:])):
        raise ValueError("quantiles must be unique and increasing")
    return tuple(float(v) for v in result)


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class ForecastSeries:
    """One named channel, with its exact instrument identity and values."""

    instrument: str
    feature: str
    values: tuple[float | None, ...]

    def __post_init__(self) -> None:
        _text(self.instrument, "instrument")
        _text(self.feature, "feature")
        values = tuple(self.values)
        if not values or any(v is not None and (type(v) not in (int, float) or not math.isfinite(v)) for v in values):
            raise ValueError("series must contain finite numeric values or explicit missing values")
        object.__setattr__(self, "values", tuple(None if v is None else float(v) for v in values))

    @property
    def key(self) -> tuple[str, str]:
        return self.instrument, self.feature


@dataclass(frozen=True, slots=True)
class ForecastRequest:
    """An immutable snapshot; known-future channels include history + horizon.

    Future timestamps are supplied by the market calendar owner, never inferred
    by adding wall-clock intervals across holidays or exchange session breaks.
    The runtime also checks ``deadline`` against its current clock on admission.
    """

    request_id: str
    timestamps: tuple[datetime, ...]
    future_timestamps: tuple[datetime, ...]
    targets: tuple[ForecastSeries, ...]
    observed_covariates: tuple[ForecastSeries, ...]
    known_future_covariates: tuple[ForecastSeries, ...]
    data_as_of: datetime
    deadline: datetime
    frequency: str
    timezone: str
    market_calendar: str
    missing_data_policy: MissingDataPolicy
    quantiles: tuple[float, ...]
    lineage_digests: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ("request_id", "frequency", "timezone", "market_calendar"):
            _text(getattr(self, name), name)
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("timezone must be an IANA timezone") from exc
        for name in ("timestamps", "future_timestamps"):
            values = tuple(_utc(v) for v in getattr(self, name))
            if not values or any(a >= b for a, b in zip(values, values[1:])):
                raise ValueError("timestamps must be non-empty and strictly increasing")
            object.__setattr__(self, name, values)
        object.__setattr__(self, "data_as_of", _utc(self.data_as_of))
        object.__setattr__(self, "deadline", _utc(self.deadline))
        if self.timestamps[-1] > self.data_as_of:
            raise ValueError("observations must not exceed data-as-of")
        if self.future_timestamps[0] <= self.data_as_of:
            raise ValueError("future timestamps must be after data-as-of")
        if self.deadline <= self.data_as_of:
            raise ValueError("deadline must be after data-as-of")
        if type(self.missing_data_policy) is not MissingDataPolicy:
            raise ValueError("missing data policy must be explicit")
        channels = []
        for name in ("targets", "observed_covariates", "known_future_covariates"):
            series = tuple(getattr(self, name))
            expected = len(self.timestamps) + (self.horizon if name == "known_future_covariates" else 0)
            for channel in series:
                if type(channel) is not ForecastSeries or len(channel.values) != expected:
                    raise ValueError("channel length must match its history/horizon schema")
                if self.missing_data_policy is MissingDataPolicy.REJECT and None in channel.values:
                    raise ValueError("missing values require an explicit supported missing data policy")
            channels.extend(series)
            object.__setattr__(self, name, series)
        if not self.targets:
            raise ValueError("at least one target is required")
        if len({channel.key for channel in channels}) != len(channels):
            raise ValueError("instrument/feature channels must be unique across roles")
        object.__setattr__(self, "quantiles", _quantiles(self.quantiles))
        digests = tuple(self.lineage_digests)
        if not digests or any(type(v) is not str or len(v) != 64 or any(c not in "0123456789abcdef" for c in v) for v in digests):
            raise ValueError("lineage must contain SHA-256 digests")
        if len(digests) != len(set(digests)):
            raise ValueError("lineage digests must be unique")
        object.__setattr__(self, "lineage_digests", tuple(sorted(digests)))

    @property
    def horizon(self) -> int:
        return len(self.future_timestamps)

    def _schema(self) -> dict[str, object]:
        return {
            "version": 1,
            "frequency": self.frequency,
            "timezone": self.timezone,
            "market_calendar": self.market_calendar,
            "missing_data_policy": self.missing_data_policy.value,
            "quantiles": self.quantiles,
            "context": len(self.timestamps),
            "horizon": self.horizon,
            **{name: [s.key for s in getattr(self, name)] for name in (
                "targets", "observed_covariates", "known_future_covariates",
            )},
        }

    @property
    def schema_digest(self) -> str:
        return _digest(self._schema())

    @property
    def input_digest(self) -> str:
        """Digest content and provenance, excluding invocation ID/deadline."""
        return _digest({
            "schema": self._schema(),
            "timestamps": [v.isoformat() for v in self.timestamps],
            "future_timestamps": [v.isoformat() for v in self.future_timestamps],
            "data_as_of": self.data_as_of.isoformat(),
            "lineage": self.lineage_digests,
            **{name: [s.values for s in getattr(self, name)] for name in (
                "targets", "observed_covariates", "known_future_covariates",
            )},
        })


@dataclass(frozen=True, slots=True)
class ForecastCapabilities:
    """A provider's declared shape ceilings, checked before worker invocation."""

    max_context: int
    max_variates: int
    max_horizon: int
    supports_observed_covariates: bool
    supports_known_future_covariates: bool
    missing_data_policies: tuple[MissingDataPolicy, ...]
    quantiles: tuple[float, ...]

    def __post_init__(self) -> None:
        for name in ("max_context", "max_variates", "max_horizon"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        for name in ("supports_observed_covariates", "supports_known_future_covariates"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be a boolean")
        policies = tuple(self.missing_data_policies)
        if not policies or any(type(v) is not MissingDataPolicy for v in policies) or len(set(policies)) != len(policies):
            raise ValueError("missing data policies must be unique declared policies")
        object.__setattr__(self, "missing_data_policies", policies)
        object.__setattr__(self, "quantiles", _quantiles(self.quantiles))

    def validate(self, request: ForecastRequest) -> None:
        """Reject rather than truncating any unsupported input or output axis."""
        checks = (
            (len(request.timestamps) <= self.max_context, "context"),
            (request.horizon <= self.max_horizon, "horizon"),
            (len(request.targets) + len(request.observed_covariates) + len(request.known_future_covariates)
             <= self.max_variates, "variates"),
            (not request.observed_covariates or self.supports_observed_covariates, "observed covariates"),
            (not request.known_future_covariates or self.supports_known_future_covariates, "known future covariates"),
            (request.missing_data_policy in self.missing_data_policies, "missing data policy"),
            (set(request.quantiles) <= set(self.quantiles), "quantiles"),
        )
        for supported, label in checks:
            if not supported:
                raise UnsupportedForecastShape(f"unsupported forecast {label}")
