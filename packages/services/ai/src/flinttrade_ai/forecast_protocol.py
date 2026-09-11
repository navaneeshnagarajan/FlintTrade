"""Bounded JSON codec for a separately installed forecast worker.

This module parses untrusted output, never provider rights or usage authority.
The runtime supplies a pinned model identity after an authenticated handshake.
It must record the attempt and resolve rights before using decoded evidence.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from flinttrade_core.service_providers import ModelIdentity

from .forecasting import ForecastRequest

MAX_FORECAST_BODY_BYTES = 8 * 1024 * 1024
_RESPONSE_FIELDS = frozenset({
    "protocol_version", "request_id", "input_digest", "schema_digest", "model",
    "targets", "timestamps", "point", "quantiles", "started_at", "completed_at", "device", "warnings",
})


class ForecastProtocolError(ValueError):
    """A worker body cannot be accepted as the requested forecast."""


def _encode(payload: object) -> bytes:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    if len(body) > MAX_FORECAST_BODY_BYTES:
        raise ForecastProtocolError("forecast body size exceeds the protocol limit")
    return body


def encode_forecast_request(request: ForecastRequest) -> bytes:
    """Encode the complete snapshot; never clip history, channels or horizon."""
    if type(request) is not ForecastRequest:
        raise ForecastProtocolError("an exact forecast request is required")
    return _encode({
        "protocol_version": 1,
        "request_id": request.request_id,
        "input_digest": request.input_digest,
        "schema_digest": request.schema_digest,
        "timestamps": [t.isoformat() for t in request.timestamps],
        "future_timestamps": [t.isoformat() for t in request.future_timestamps],
        "data_as_of": request.data_as_of.isoformat(),
        "deadline": request.deadline.isoformat(),
        "frequency": request.frequency,
        "timezone": request.timezone,
        "market_calendar": request.market_calendar,
        "missing_data_policy": request.missing_data_policy.value,
        "quantiles": request.quantiles,
        "lineage_digests": request.lineage_digests,
        **{name: [{"instrument": s.instrument, "feature": s.feature, "values": s.values}
                  for s in getattr(request, name)]
           for name in ("targets", "observed_covariates", "known_future_covariates")},
    })


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ForecastProtocolError("duplicate JSON field")
        result[key] = value
    return result


def _constant(value: str) -> None:
    raise ForecastProtocolError("non-finite JSON number")


def _instant(value: object) -> datetime:
    if type(value) is not str:
        raise ForecastProtocolError("worker timestamp must be UTC text")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ForecastProtocolError("worker timestamp must be UTC text")
    return parsed.replace(tzinfo=UTC)


def _matrix(value: object, rows: int, columns: int) -> tuple[tuple[float, ...], ...]:
    if type(value) is not list or len(value) != rows:
        raise ForecastProtocolError("forecast target count mismatch")
    result = []
    for row in value:
        if type(row) is not list or len(row) != columns:
            raise ForecastProtocolError("forecast horizon mismatch")
        if any(type(v) not in (float, int) or not math.isfinite(v) for v in row):
            raise ForecastProtocolError("forecast values must be finite numbers")
        result.append(tuple(float(v) for v in row))
    return tuple(result)


def _label(value: object, *, maximum: int = 256) -> str:
    if type(value) is not str or not value.strip() or len(value) > maximum or any(ord(c) < 32 for c in value):
        raise ForecastProtocolError("worker label must be bounded non-blank text")
    return value


@dataclass(frozen=True, slots=True)
class ForecastOutput:
    """Decoded observations, not centrally authorised evidence or a trade signal."""

    model: ModelIdentity
    request_id: str
    input_digest: str
    schema_digest: str
    point: tuple[tuple[float, ...], ...]
    quantiles: tuple[tuple[float, tuple[tuple[float, ...], ...]], ...]
    started_at: datetime
    completed_at: datetime
    device: str
    warnings: tuple[str, ...]
    output_digest: str


def decode_forecast_response(body: bytes, *, request: ForecastRequest, expected_model: ModelIdentity) -> ForecastOutput:
    """Strictly validate identity, dimensions and quantiles of an untrusted body.

    Only the documented fields are accepted. Workers cannot return a rights
    grant, change a checkpoint, reorder targets or drop requested quantiles.
    Transport deadline, authentication and body-stream limits are additional
    runtime obligations; this decoder performs no network or other I/O.
    """
    if type(body) is not bytes or not 0 < len(body) <= MAX_FORECAST_BODY_BYTES:
        raise ForecastProtocolError("invalid forecast body size")
    if type(request) is not ForecastRequest or type(expected_model) is not ModelIdentity:
        raise ForecastProtocolError("exact request and pinned model identity are required")
    try:
        value = json.loads(body, object_pairs_hook=_object, parse_constant=_constant)
        if type(value) is not dict or set(value) != _RESPONSE_FIELDS:
            raise ForecastProtocolError("unknown or missing forecast response fields")
        if type(value["protocol_version"]) is not int or value["protocol_version"] != 1:
            raise ForecastProtocolError("unsupported forecast protocol version")
        if (value["request_id"], value["input_digest"], value["schema_digest"]) != (
            request.request_id, request.input_digest, request.schema_digest,
        ):
            raise ForecastProtocolError("forecast request identity mismatch")
        if value["model"] != expected_model.to_public_dict():
            raise ForecastProtocolError("forecast model identity mismatch")
        if value["targets"] != [{"instrument": s.instrument, "feature": s.feature} for s in request.targets]:
            raise ForecastProtocolError("forecast target identity mismatch")
        if type(value["timestamps"]) is not list or tuple(_instant(t) for t in value["timestamps"]) != request.future_timestamps:
            raise ForecastProtocolError("forecast future timestamps mismatch")
        rows, columns = len(request.targets), request.horizon
        point = _matrix(value["point"], rows, columns)
        wire_quantiles = value["quantiles"]
        if type(wire_quantiles) is not list or len(wire_quantiles) != len(request.quantiles):
            raise ForecastProtocolError("forecast quantiles mismatch")
        quantiles = []
        for expected, entry in zip(request.quantiles, wire_quantiles, strict=True):
            if type(entry) is not dict or set(entry) != {"quantile", "values"}:
                raise ForecastProtocolError("invalid forecast quantile fields")
            if type(entry["quantile"]) not in (int, float) or entry["quantile"] != expected:
                raise ForecastProtocolError("forecast quantiles mismatch")
            matrix = _matrix(entry["values"], rows, columns)
            if quantiles and any(matrix[r][c] < quantiles[-1][1][r][c] for r in range(rows) for c in range(columns)):
                raise ForecastProtocolError("crossing forecast quantiles")
            quantiles.append((expected, matrix))
        started, completed = _instant(value["started_at"]), _instant(value["completed_at"])
        if not request.data_as_of <= started <= completed <= request.deadline:
            raise ForecastProtocolError("worker timing outside the request window")
        device = _label(value["device"])
        if type(value["warnings"]) is not list or len(value["warnings"]) > 64:
            raise ForecastProtocolError("invalid worker warnings")
        warnings = tuple(_label(w, maximum=1024) for w in value["warnings"])
        return ForecastOutput(
            model=expected_model, request_id=request.request_id,
            input_digest=request.input_digest, schema_digest=request.schema_digest,
            point=point, quantiles=tuple(quantiles), started_at=started, completed_at=completed,
            device=device, warnings=warnings, output_digest=hashlib.sha256(_encode(value)).hexdigest(),
        )
    except ForecastProtocolError:
        raise
    except (ValueError, TypeError, OverflowError, RecursionError) as exc:
        raise ForecastProtocolError("malformed forecast response") from exc
