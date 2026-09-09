"""Untrusted worker responses must match the complete requested forecast."""

import json
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

import pytest

from flinttrade_ai import forecast_protocol as protocol
from flinttrade_ai.forecasting import ForecastRequest, ForecastSeries, MissingDataPolicy
from flinttrade_core.service_providers import ModelIdentity


@pytest.fixture
def forecast_request():
    start = datetime(2026, 9, 1, 4, tzinfo=UTC)
    return ForecastRequest(
        request_id="run-1:attempt-1", timestamps=(start, start + timedelta(minutes=1)),
        future_timestamps=(start + timedelta(minutes=2), start + timedelta(minutes=3)),
        targets=(ForecastSeries("NSE:TEST", "close", (100, 101)),),
        observed_covariates=(), known_future_covariates=(), data_as_of=start + timedelta(minutes=1),
        deadline=start + timedelta(minutes=4), frequency="1m", timezone="Asia/Kolkata",
        market_calendar="NSE:v1", missing_data_policy=MissingDataPolicy.REJECT,
        quantiles=(0.1, 0.9), lineage_digests=("a" * 64,),
    )


@pytest.fixture
def model():
    return ModelIdentity("forecast:external-json", "fixture", "v1", "b" * 64)


def response(request, model):
    return {
        "protocol_version": 1, "request_id": request.request_id,
        "input_digest": request.input_digest, "schema_digest": request.schema_digest,
        "model": model.to_public_dict(),
        "targets": [{"instrument": "NSE:TEST", "feature": "close"}],
        "timestamps": [t.isoformat() for t in request.future_timestamps],
        "point": [[102, 103]],
        "quantiles": [{"quantile": 0.1, "values": [[101, 102]]}, {"quantile": 0.9, "values": [[103, 104]]}],
        "started_at": request.data_as_of.isoformat(),
        "completed_at": (request.data_as_of + timedelta(seconds=1)).isoformat(),
        "device": "cpu", "warnings": [],
    }


def decode(payload, request, model):
    return protocol.decode_forecast_response(json.dumps(payload).encode(), request=request, expected_model=model)


def test_wire_request_contains_every_channel_and_exact_snapshot(forecast_request):
    wire = protocol.encode_forecast_request(forecast_request)
    payload = json.loads(wire)
    assert payload["protocol_version"] == 1
    assert payload["input_digest"] == forecast_request.input_digest
    assert payload["targets"][0]["values"] == [100, 101]
    assert payload["future_timestamps"] == [t.isoformat() for t in forecast_request.future_timestamps]
    assert "rights" not in payload


def test_response_is_detached_and_digest_binds_output(forecast_request, model):
    payload = response(forecast_request, model)
    output = decode(payload, forecast_request, model)
    payload["point"][0][0] = 999
    assert output.point == ((102.0, 103.0),)
    with pytest.raises(FrozenInstanceError):
        output.device = "cuda"
    changed = response(forecast_request, model)
    changed["point"][0][0] = 102.5
    assert decode(changed, forecast_request, model).output_digest != output.output_digest


@pytest.mark.parametrize("field,value", [
    ("protocol_version", True), ("protocol_version", 2), ("request_id", "other-attempt"),
    ("input_digest", "c" * 64), ("schema_digest", "d" * 64),
    ("targets", [{"instrument": "NSE:OTHER", "feature": "close"}]),
    ("point", [[102]]), ("point", [[102, True]]), ("point", [[102, float("nan")]]),
    ("point", [[102, 103], [104, 105]]), ("quantiles", []),
    ("timestamps", ["2026-09-01T00:00:00+00:00"]), ("warnings", "warning"),
    ("device", ""), ("completed_at", "2026-09-01T00:00:00+00:00"),
])
def test_rejects_mismatched_or_incomplete_worker_result(forecast_request, model, field, value):
    payload = response(forecast_request, model)
    payload[field] = value
    with pytest.raises(protocol.ForecastProtocolError):
        decode(payload, forecast_request, model)


def test_rejects_different_checkpoint_and_worker_asserted_rights(forecast_request, model):
    payload = response(forecast_request, model)
    payload["model"]["revision"] = "unpinned"
    with pytest.raises(protocol.ForecastProtocolError):
        decode(payload, forecast_request, model)
    payload = response(forecast_request, model)
    payload["rights"] = {"max_evidence_use_scope": "live_decision"}
    with pytest.raises(protocol.ForecastProtocolError):
        decode(payload, forecast_request, model)


def test_rejects_crossing_quantiles(forecast_request, model):
    payload = response(forecast_request, model)
    payload["quantiles"][0]["values"] = [[105, 106]]
    with pytest.raises(protocol.ForecastProtocolError, match="quantile"):
        decode(payload, forecast_request, model)


@pytest.mark.parametrize("wire", [b'{"protocol_version":1,"protocol_version":1}', b'[]', b'\xff', b'{' * 5000])
def test_rejects_duplicate_fields_non_objects_and_malformed_json(forecast_request, model, wire):
    with pytest.raises(protocol.ForecastProtocolError):
        protocol.decode_forecast_response(wire, request=forecast_request, expected_model=model)


def test_rejects_oversized_response_before_parsing(forecast_request, model):
    with pytest.raises(protocol.ForecastProtocolError, match="size"):
        protocol.decode_forecast_response(
            b" " * (protocol.MAX_FORECAST_BODY_BYTES + 1), request=forecast_request, expected_model=model,
        )
