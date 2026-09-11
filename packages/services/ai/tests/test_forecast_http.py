"""The private forecast HTTP seam performs only bounded admitted attempts."""

import asyncio
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from flinttrade_ai.forecast_http import ForecastHttpTransport, ForecastTransportError
from flinttrade_ai.forecasting import ForecastCapabilities, ForecastRequest, ForecastSeries, MissingDataPolicy
from flinttrade_core.service_providers import ModelIdentity

MODEL = ModelIdentity("forecast:external-json", "fixture", "v1", "b" * 64)
CAPS = ForecastCapabilities(128, 4, 16, True, True, (MissingDataPolicy.REJECT,), ())
TOKEN = "synthetic-forecast-endpoint-secret"


def request():
    now = datetime.now(UTC)
    return ForecastRequest(
        "forecast-attempt", (now - timedelta(minutes=1), now), (now + timedelta(minutes=1),),
        (ForecastSeries("NSE:TEST", "close", (100, 101)),), (), (), now,
        now + timedelta(seconds=10), "1m", "Asia/Kolkata", "NSE:fixture", MissingDataPolicy.REJECT, (), ("a" * 64,),
    )


def handshake():
    return {"protocol_version": 1, "model": MODEL.to_public_dict(), "capabilities": {
        "max_context": 128, "max_variates": 4, "max_horizon": 16,
        "supports_observed_covariates": True, "supports_known_future_covariates": True,
        "missing_data_policies": ["reject"], "quantiles": [],
    }}


def output(item):
    return {
        "protocol_version": 1, "request_id": item.request_id, "input_digest": item.input_digest,
        "schema_digest": item.schema_digest, "model": MODEL.to_public_dict(),
        "targets": [{"instrument": "NSE:TEST", "feature": "close"}],
        "timestamps": [t.isoformat() for t in item.future_timestamps], "point": [[102]], "quantiles": [],
        "started_at": item.data_as_of.isoformat(), "completed_at": datetime.now(UTC).isoformat(),
        "device": "cpu", "warnings": [],
    }


async def admitted(_invocation):
    return None


def transport(handler, **kwargs):
    return ForecastHttpTransport(
        "http://127.0.0.1:9876/worker", TOKEN, MODEL, CAPS,
        before_invoke=kwargs.pop("before_invoke", admitted), transport=httpx.MockTransport(handler), **kwargs,
    )


async def test_handshake_and_forecast_are_distinct_admitted_authenticated_operations():
    item = request()
    admissions, calls = [], []

    async def admit(invocation):
        admissions.append(invocation)

    def handle(http):
        assert len(admissions) == len(calls) + 1
        assert http.headers["authorization"] == f"Bearer {TOKEN}"
        calls.append(http)
        return httpx.Response(200, json=handshake() if http.method == "GET" else output(item))

    worker = transport(handle, before_invoke=admit)
    try:
        await worker.handshake("probe-attempt", item.deadline)
        result = await worker.forecast(item)
        assert result.output.point == ((102.0,),)
        assert json.loads(result.body)["request_id"] == item.request_id
        assert [a.attempt_id for a in admissions] == ["probe-attempt", item.request_id]
        assert [a.kind for a in admissions] == ["handshake", "forecast"]
        assert [str(c.url.path) for c in calls] == ["/worker/capabilities", "/worker/forecast"]
    finally:
        await worker.close(1)


async def test_failed_admission_and_absent_handshake_never_send():
    calls = []

    async def refuse(_invocation):
        raise RuntimeError("budget unavailable")

    worker = transport(lambda r: calls.append(r), before_invoke=refuse)
    try:
        with pytest.raises(ForecastTransportError, match="handshake"):
            await worker.forecast(request())
        with pytest.raises(RuntimeError, match="budget"):
            await worker.handshake("probe", request().deadline)
        assert calls == []
    finally:
        await worker.close(1)


@pytest.mark.parametrize("endpoint", ["http://worker.invalid", "http://localhost:9876", "https://u:p@worker.invalid",
                                     "https://worker.invalid?token=x", "https://worker.invalid/#fragment"])
def test_endpoint_refuses_credential_leaks_and_plaintext_nonliteral_targets(endpoint):
    with pytest.raises(ValueError):
        ForecastHttpTransport(endpoint, TOKEN, MODEL, CAPS, before_invoke=admitted)


@pytest.mark.parametrize("response", [
    httpx.Response(302, headers={"Location": "https://foreign.invalid"}),
    httpx.Response(503, text="private internal detail"),
    httpx.Response(200, headers={"Content-Length": "999999999"}, content=b"{}"),
    httpx.Response(200, headers={"Content-Encoding": "gzip"}, content=b""),
])
async def test_bad_http_envelopes_are_refused_without_following_or_exposing_body(response):
    calls = []

    def handle(http):
        calls.append(http)
        return response

    worker = transport(handle)
    try:
        with pytest.raises(ForecastTransportError) as caught:
            await worker.handshake("probe", request().deadline)
        assert "private internal" not in str(caught.value)
        assert len(calls) == 1
    finally:
        await worker.close(1)


async def test_deadline_busy_cancellation_and_close_are_bounded():
    entered = asyncio.Event()
    blocked = asyncio.Event()

    async def handle(_http):
        entered.set()
        await blocked.wait()
        return httpx.Response(200, json=handshake())

    worker = transport(handle)
    first = asyncio.create_task(worker.handshake("probe-1", request().deadline))
    await asyncio.wait_for(entered.wait(), 1)
    try:
        with pytest.raises(ForecastTransportError, match="busy"):
            await worker.handshake("probe-2", request().deadline)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        with pytest.raises(ForecastTransportError, match="deadline"):
            await worker.handshake("expired", datetime.now(UTC) - timedelta(seconds=1))
    finally:
        await worker.close(1)
    with pytest.raises(ForecastTransportError, match="closed"):
        await worker.handshake("after-close", request().deadline)
