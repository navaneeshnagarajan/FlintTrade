"""Default INDmoney/Groww REST paths, with HTTP replaced at the network boundary."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from flinttrade_core.exceptions import RateLimitError
from flinttrade_gateway.brokers import groww, indmoney

pytestmark = pytest.mark.unit


@pytest.fixture(params=[indmoney, groww], ids=["indmoney", "groww"])
def broker_module(request):
    return request.param


def _adapter(module):
    return indmoney.IndMoneyAdapter() if module is indmoney else groww.GrowwAdapter()


def _envelope(module, data):
    return {"status": "success", "data": data} if module is indmoney else {"status": "SUCCESS", "payload": data}


@pytest.mark.asyncio
async def test_default_login_profile_transport_preserves_headers_and_timeout(broker_module, monkeypatch):
    calls = []
    profile = {"user_id": "synthetic-account"}

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return httpx.Response(200, json=_envelope(broker_module, profile))

    monkeypatch.setattr(httpx, "request", request)
    adapter = _adapter(broker_module)
    session = await adapter.login({"access_token": "synthetic-token", "user_id": "synthetic-account"})
    assert calls == []  # Constructing the default transport is not a broker request.

    assert await adapter.profile(session) == profile

    (method, url, kwargs), = calls
    expected_url = (
        "https://api.indstocks.com/user/profile" if broker_module is indmoney else "https://api.groww.in/v1/user/detail"
    )
    expected_auth = "synthetic-token" if broker_module is indmoney else "Bearer synthetic-token"
    assert (method, url) == ("GET", expected_url)
    assert kwargs["headers"]["Authorization"] == expected_auth
    assert kwargs["headers"]["Content-Type"] == "application/json"
    assert kwargs["timeout"] == 10.0
    assert kwargs["params"] is None and kwargs["json"] is None
    assert (session.account_id, session.adapter_id) == ("synthetic-account", adapter.broker_id)


@pytest.mark.parametrize("timeout", [None, 2.5])
@pytest.mark.parametrize("json_response", [True, False], ids=["json", "text"])
def test_transport_keeps_request_arguments_status_and_payload(broker_module, monkeypatch, timeout, json_response):
    calls = []
    payload = {"synthetic": [0, None]} if json_response else "synthetic,raw\nCSV,text\n"

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return httpx.Response(207, **({"json": payload} if json_response else {"text": payload}))

    monkeypatch.setattr(httpx, "request", request)
    factory = broker_module._build_httpx_transport
    transport = factory() if timeout is None else factory(timeout=timeout)
    headers = {"X-Synthetic": "test"}
    params = {"segment": "synthetic"}
    body = {"synthetic": [1, 2]}

    assert transport("POST", "https://example.invalid/read", headers=headers, params=params, json_body=body) == (
        207, payload,
    )

    (method, url, kwargs), = calls
    assert (method, url) == ("POST", "https://example.invalid/read")
    assert kwargs == {"headers": headers, "params": params, "json": body, "timeout": 10.0 if timeout is None else timeout}
    assert kwargs["headers"] is headers and kwargs["params"] is params and kwargs["json"] is body


@pytest.mark.asyncio
@pytest.mark.parametrize("json_response", [True, False], ids=["json", "text"])
async def test_default_profile_transport_preserves_http_error_without_retry(broker_module, monkeypatch, json_response):
    calls = []
    message = "synthetic refusal"

    def request(*args, **kwargs):
        calls.append((args, kwargs))
        return httpx.Response(429, **({"json": {"message": message}} if json_response else {"text": message}))

    monkeypatch.setattr(httpx, "request", request)
    adapter = _adapter(broker_module)
    session = await adapter.login({"access_token": "synthetic-token"})

    with pytest.raises(RateLimitError, match=message) as caught:
        await adapter.profile(session)

    assert caught.value.broker_code == "429"
    assert caught.value.broker_id == adapter.broker_id
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [httpx.ConnectError, httpx.ReadTimeout, RuntimeError])
async def test_default_profile_transport_propagates_network_failure_without_retry(broker_module, monkeypatch, error_type):
    calls = []
    error = error_type("synthetic transport failure")

    def request(*args, **kwargs):
        calls.append((args, kwargs))
        raise error

    monkeypatch.setattr(httpx, "request", request)
    adapter = _adapter(broker_module)
    session = await adapter.login({"access_token": "synthetic-token"})

    with pytest.raises(error_type) as caught:
        await adapter.profile(session)

    assert caught.value is error
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_default_profile_transport_only_falls_back_on_json_value_error(broker_module, monkeypatch):
    error = RuntimeError("synthetic decoder failure")
    calls = []

    def decode():
        calls.append("json")
        raise error

    def request(*_args, **_kwargs):
        calls.append("request")
        return SimpleNamespace(status_code=200, json=decode, text="must not hide the decoder failure")

    monkeypatch.setattr(httpx, "request", request)
    adapter = _adapter(broker_module)
    session = await adapter.login({"access_token": "synthetic-token"})

    with pytest.raises(RuntimeError) as caught:
        await adapter.profile(session)

    assert caught.value is error
    assert calls == ["request", "json"]


@pytest.mark.asyncio
async def test_login_keeps_broker_module_default_factory_override(broker_module, monkeypatch):
    calls = []

    def transport(*_args, **_kwargs):
        calls.append("request")
        return 200, _envelope(broker_module, {"user_id": "synthetic-account"})

    def factory():
        calls.append("factory")
        return transport

    monkeypatch.setattr(broker_module, "_build_httpx_transport", factory)
    adapter = _adapter(broker_module)
    session = await adapter.login({"access_token": "synthetic-token"})

    assert session.extra["transport"] is transport
    assert await adapter.profile(session) == {"user_id": "synthetic-account"}
    assert calls == ["factory", "request"]
