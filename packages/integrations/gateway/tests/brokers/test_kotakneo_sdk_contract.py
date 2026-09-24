"""Contracts against the installed, attested Kotak Neo v3 SDK."""

from __future__ import annotations

import os
import subprocess
import sys
from copy import deepcopy
from decimal import Decimal

import httpx
import pytest
from flinttrade_core.exceptions import (
    BrokerInternal, BrokerTimeout, CredentialsInvalid, MFARequired, NetworkError, OrderRejectedByBroker,
    RateLimitError, SessionExpired, UnsupportedCapabilityError,
)

pytestmark = pytest.mark.unit


_OUT_OF_BOUNDS_ORDER_NUMBERS = (
    pytest.param(
        "price",
        Decimal("12345678901234567890123456789012345678901234567890123456789012345"),
        id="65-significant-digits",
    ),
    pytest.param("quantity", Decimal("1e5000"), id="quantity-exponent-positive-5000"),
    pytest.param("price", Decimal("1e100000"), id="price-exponent-positive-100000"),
    pytest.param("price", Decimal("1e-5000"), id="price-scale-5000"),
)


def test_import_and_exact_sdk_contract_do_not_touch_network_or_cwd_logs(tmp_path):
    script = """
import inspect
import logging
import socket
import httpx

def denied(*_args, **_kwargs):
    raise AssertionError('network was opened')

socket.socket.connect = denied
socket.socket.connect_ex = denied
root_handlers = tuple(logging.getLogger().handlers)
from flinttrade_gateway.brokers.kotakneo_sdk import _sdk_class
NeoAPI = _sdk_class()
neo = NeoAPI(consumer_key='synthetic', environment='prod', access_token=None,
             transport=httpx.MockTransport(lambda request: denied()))
assert tuple(logging.getLogger().handlers) == root_handlers
neo.api_client.rest_client.close()

expected = {
    'totp_login': ('mobile_number', 'ucc', 'totp'),
    'totp_validate': ('mpin',),
    'place_order': ('exchange_segment', 'product', 'price', 'order_type', 'quantity', 'validity', 'trading_symbol', 'transaction_type', 'amo', 'disclosed_quantity', 'trigger_price', 'tag'),
    'modify_order': ('order_id', 'price', 'order_type', 'quantity', 'validity', 'trigger_price', 'disclosed_quantity', 'amo'),
    'cancel_order': ('order_id', 'amo', 'isVerify'),
    'margin_required': ('exchange_segment', 'price', 'order_type', 'product', 'quantity', 'instrument_token', 'transaction_type', 'trigger_price', 'broker_name', 'branch_id', 'stop_loss_type', 'stop_loss_value', 'square_off_type', 'square_off_value', 'trailing_stop_loss', 'trailing_sl_value'),
    'create_websocket': ('url', 'kwargs'),
    'create_order_feed': ('kwargs',),
    'whatsmyip': (),
    'order_report': ('order_id',),
    'order_history': ('order_id',),
    'trade_report': (),
    'positions': (),
    'holdings': (),
    'limits': (),
    'quotes': ('instrument_tokens', 'quote_type'),
    'scrip_master': ('exchange_segment',),
    'search_scrip': ('exchange_segment', 'symbol', 'expiry', 'option_type', 'strike_price', 'ignore_50multiple'),
    'expiries': ('exchange', 'underlying', 'instrument_type'),
    'option_chain': ('exchange', 'underlying', 'expiry', 'instrument_type', 'count'),
    'historical_data': ('neosymbol', 'interval', 'from_date', 'to_date'),
    'logout': (),
}
for name, params in expected.items():
    assert tuple(inspect.signature(getattr(NeoAPI, name)).parameters)[1:] == params, name
assert tuple(inspect.signature(NeoAPI).parameters) == (
    'consumer_key', 'environment', 'access_token', 'neo_fin_key', 'transport', 'limits', 'http2', 'timeout'
)
"""
    env = os.environ.copy()
    env.pop("NEO_LOG_FILE_ENABLED", None)
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=tmp_path, env=env,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "logs" / "neo-api-client.log").exists()


def test_facade_exposes_exact_v3_session_surface():
    from flinttrade_gateway.brokers.kotakneo_sdk import KotakNeoSdkSession

    assert callable(KotakNeoSdkSession.login)
    assert callable(KotakNeoSdkSession.liveness)
    assert callable(KotakNeoSdkSession.close)


class ExactNeo:
    instances = []

    def __init__(self, *, consumer_key=None, environment="prod", access_token=None, neo_fin_key=None):
        self.constructor = (consumer_key, environment, access_token, neo_fin_key)
        self.calls = []
        self.view = {
            "data": {"status": "success", "token": "view", "sid": "view-sid", "ucc": "SYNTHETIC", "kType": "View"}
        }
        self.trade = {
            "data": {"status": "success", "token": "trade", "sid": "trade-sid", "baseUrl": "https://example.invalid", "kType": "Trade"}
        }
        self.liveness_response = {"data": [{"ip": "synthetic", "time": "now"}], "stCode": 1000, "status": "success"}
        self.configuration = type("Configuration", (), {"edit_token": "trade", "edit_sid": "trade-sid"})()
        self.api_client = type("ApiClient", (), {"rest_client": type("RestClient", (), {"close": lambda self: None})()})()
        self.__class__.instances.append(self)

    def totp_login(self, mobile_number=None, ucc=None, totp=None):
        self.calls.append(("totp_login", mobile_number, ucc, totp))
        return self.view

    def totp_validate(self, mpin=None):
        self.calls.append(("totp_validate", mpin))
        return self.trade

    def whatsmyip(self):
        self.calls.append(("whatsmyip",))
        return self.liveness_response

    def place_order(
        self,
        exchange_segment,
        product,
        price,
        order_type,
        quantity,
        validity,
        trading_symbol,
        transaction_type,
        amo="NO",
        disclosed_quantity="0",
        trigger_price="0",
        tag=None,
    ):
        self.calls.append(
            (
                "place_order",
                exchange_segment,
                product,
                price,
                order_type,
                quantity,
                validity,
                trading_symbol,
                transaction_type,
                amo,
                disclosed_quantity,
                trigger_price,
                tag,
            )
        )
        return {"stat": "Ok", "stCode": 200, "nOrdNo": "OID-PLACE"}

    def modify_order(
        self,
        order_id,
        price,
        order_type,
        quantity,
        validity,
        trigger_price="0",
        disclosed_quantity="0",
        amo="NO",
    ):
        self.calls.append(
            (
                "modify_order",
                order_id,
                price,
                order_type,
                quantity,
                validity,
                trigger_price,
                disclosed_quantity,
                amo,
            )
        )
        return {"stat": "Ok", "stCode": 200, "nOrdNo": order_id}

    def cancel_order(self, order_id, amo="NO", isVerify=False):
        self.calls.append(("cancel_order", order_id, amo, isVerify))
        return {"stat": "Ok", "stCode": 200, "nOrdNo": order_id}

    def trade_report(self):
        self.calls.append(("trade_report",))
        return {"stat": "Ok", "stCode": 200, "data": []}

    def limits(self):
        self.calls.append(("limits",))
        return {"stat": "Ok", "stCode": 200, "Net": "1", "MarginUsed": "0"}

    def margin_required(
        self,
        exchange_segment,
        price,
        order_type,
        product,
        quantity,
        instrument_token,
        transaction_type,
        trigger_price=None,
    ):
        self.calls.append(
            (
                "margin_required",
                exchange_segment,
                price,
                order_type,
                product,
                quantity,
                instrument_token,
                transaction_type,
                trigger_price,
            )
        )
        return {
            "data": {
                "status": "success",
                "stat": "Ok",
                "stCode": 200,
                "ordMrgn": "1",
                "reqdMrgn": "0",
                "avlCash": "10",
                "insufFund": "0",
                "rmsVldtd": "OK",
            }
        }

    def logout(self):
        self.calls.append(("logout",))
        return {"status": "success"}


@pytest.fixture
def fake_sdk(monkeypatch):
    import neo_api_client

    ExactNeo.instances.clear()
    monkeypatch.setattr(neo_api_client, "NeoAPI", ExactNeo)
    return ExactNeo


def _credentials():
    return {"access_token": "alias", "mobile_number": "synthetic", "ucc": "SYNTHETIC", "totp": "000000", "mpin": "123456"}


def test_legacy_alias_is_consumer_key_and_totp_never_uses_sdk_access_token(fake_sdk):
    from flinttrade_gateway.brokers.kotakneo_sdk import KotakNeoSdkSession

    session = KotakNeoSdkSession.login(_credentials())
    neo = fake_sdk.instances[-1]
    assert neo.constructor == ("alias", "prod", None, None)
    assert neo.calls == [("totp_login", "synthetic", "SYNTHETIC", "000000"), ("totp_validate", "123456")]
    session.close()


def test_facade_invokes_exact_v3_order_report_limits_and_margin_signatures(fake_sdk):
    from flinttrade_gateway.brokers.kotakneo_sdk import KotakNeoSdkSession

    session = KotakNeoSdkSession.login(_credentials())
    neo = fake_sdk.instances[-1]
    neo.calls.clear()
    session.place_order(
        {
            "exchange_segment": "nse_cm",
            "product": "MIS",
            "price": "1",
            "order_type": "L",
            "quantity": "2",
            "validity": "DAY",
            "trading_symbol": "SYNTHETIC-EQ",
            "transaction_type": "B",
            "amo": "NO",
            "disclosed_quantity": "0",
            "trigger_price": "0",
            "tag": "TAG-1",
        }
    )
    session.modify_order(
        {
            "order_id": "OID-1",
            "price": "2",
            "order_type": "SL",
            "quantity": "3",
            "validity": "IOC",
            "trigger_price": "1.5",
            "disclosed_quantity": "1",
            "amo": "YES",
        }
    )
    session.cancel_order("OID-1", amo="YES", is_verify=True)
    session.trade_book()
    session.limits()
    session.margin(
        {
            "exchange_segment": "nse_cm",
            "price": "1",
            "order_type": "L",
            "product": "MIS",
            "quantity": "2",
            "instrument_token": "123",
            "transaction_type": "B",
            "trigger_price": "0",
        }
    )

    assert neo.calls == [
        ("place_order", "nse_cm", "MIS", "1", "L", "2", "DAY", "SYNTHETIC-EQ", "B", "NO", "0", "0", "TAG-1"),
        ("modify_order", "OID-1", "2", "SL", "3", "IOC", "1.5", "1", "YES"),
        ("cancel_order", "OID-1", "YES", True),
        ("trade_report",),
        ("limits",),
        ("margin_required", "nse_cm", "1", "L", "MIS", "2", "123", "B", "0"),
    ]
    session.close()


def test_facade_preserves_provider_write_rejection_as_order_rejected(fake_sdk, monkeypatch):
    import neo_api_client

    from flinttrade_gateway.brokers.kotakneo_sdk import KotakNeoSdkSession

    class RejectedNeo(ExactNeo):
        def modify_order(self, *args, **kwargs):
            return {"stat": "Not_Ok", "stCode": 400, "errMsg": "synthetic rejection"}

    monkeypatch.setattr(neo_api_client, "NeoAPI", RejectedNeo)
    session = KotakNeoSdkSession.login(_credentials())
    with pytest.raises(OrderRejectedByBroker):
        session.modify_order(
            {
                "order_id": "OID-1",
                "price": "0",
                "order_type": "MKT",
                "quantity": "1",
                "validity": "DAY",
                "trigger_price": "0",
                "disclosed_quantity": "0",
            }
        )
    session.close()


@pytest.mark.asyncio
async def test_adapter_strict_numeric_validation_stops_installed_sdk_mock_transport():
    import time

    import neo_api_client

    from flinttrade_core.models import Order
    from flinttrade_gateway.brokers._base import ROUTER_TOKEN, Session
    from flinttrade_gateway.brokers.kotakneo import KotakNeoAdapter
    from flinttrade_gateway.brokers.kotakneo_sdk import KotakNeoSdkSession

    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"stat": "Ok", "stCode": 200, "nOrdNo": "OID-1"})

    neo = neo_api_client.NeoAPI(
        consumer_key="synthetic",
        access_token=None,
        transport=httpx.MockTransport(respond),
    )
    neo.configuration.edit_token = "synthetic"
    neo.configuration.edit_sid = "synthetic"
    neo.configuration.base_url = "https://example.invalid"
    facade = KotakNeoSdkSession.__new__(KotakNeoSdkSession)
    facade._neo = neo
    facade._closed = False
    adapter = KotakNeoAdapter(
        client_factory=lambda _session: facade,
        symbol_resolver=lambda _symbol, _exchange: "SYNTHETIC-EQ",
        token_resolver=lambda _symbol, _exchange: "123",
    )
    session = Session(
        access_token="synthetic",
        expires_at=time.time() + 60,
        account_id="synthetic",
        adapter_id="kotakneo",
    )
    bad_price = Order(
        symbol="SYNTHETIC", action="BUY", exchange="NSE", pricetype="MARKET", product="MIS"
    ).model_copy(update={"price": "NaN"})
    bad_quantity = Order(
        symbol="SYNTHETIC", action="BUY", exchange="NSE", pricetype="MARKET", product="MIS"
    ).model_copy(update={"quantity": "1.5"})

    try:
        with pytest.raises(UnsupportedCapabilityError):
            await adapter.place_order(session, bad_price, _router_token=ROUTER_TOKEN)
        with pytest.raises(UnsupportedCapabilityError):
            await adapter.modify_order(
                session,
                "OID-1",
                {"pricetype": "MARKET", "price": "Infinity", "quantity": "1"},
                _router_token=ROUTER_TOKEN,
            )
        with pytest.raises(UnsupportedCapabilityError):
            await adapter.margin_calculator(session, bad_quantity)
        assert requests == []
    finally:
        facade.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", _OUT_OF_BOUNDS_ORDER_NUMBERS)
@pytest.mark.parametrize("operation", ["place", "modify", "margin"])
async def test_adapter_numeric_bounds_stop_installed_sdk_transport_with_canonical_error(operation, field, value):
    import time

    import neo_api_client

    from flinttrade_core.models import Order
    from flinttrade_gateway.brokers._base import ROUTER_TOKEN, Session
    from flinttrade_gateway.brokers.kotakneo import KotakNeoAdapter
    from flinttrade_gateway.brokers.kotakneo_sdk import KotakNeoSdkSession

    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "stat": "Ok",
                "stCode": 200,
                "nOrdNo": "OID-1",
                "data": {
                    "stat": "Ok",
                    "stCode": 200,
                    "ordMrgn": "1",
                    "reqdMrgn": "0",
                    "avlCash": "10",
                    "insufFund": "0",
                    "rmsVldtd": "OK",
                },
            },
        )

    neo = neo_api_client.NeoAPI(
        consumer_key="synthetic",
        access_token=None,
        transport=httpx.MockTransport(respond),
    )
    neo.configuration.edit_token = "synthetic"
    neo.configuration.edit_sid = "synthetic"
    neo.configuration.base_url = "https://example.invalid"
    facade = KotakNeoSdkSession.__new__(KotakNeoSdkSession)
    facade._neo = neo
    facade._closed = False
    adapter = KotakNeoAdapter(
        client_factory=lambda _session: facade,
        symbol_resolver=lambda _symbol, _exchange: "SYNTHETIC-EQ",
        token_resolver=lambda _symbol, _exchange: "123",
    )
    session = Session(
        access_token="synthetic",
        expires_at=time.time() + 60,
        account_id="synthetic",
        adapter_id="kotakneo",
    )
    order = Order(
        symbol="SYNTHETIC",
        action="BUY",
        exchange="NSE",
        pricetype="MARKET",
        product="MIS",
        quantity="1",
    ).model_copy(update={field: value})

    try:
        with pytest.raises(UnsupportedCapabilityError, match=field.replace("_", " ")):
            if operation == "place":
                await adapter.place_order(session, order, _router_token=ROUTER_TOKEN)
            elif operation == "modify":
                await adapter.modify_order(
                    session,
                    "OID-1",
                    {"pricetype": "MARKET", "quantity": "1", "price": "0", field: value},
                    _router_token=ROUTER_TOKEN,
                )
            else:
                await adapter.margin_calculator(session, order)
        assert requests == []
    finally:
        facade.close()


@pytest.mark.parametrize("step,invalid,error", [
    ("view", {"data": {"status": "failure", "message": "Invalid credential"}}, CredentialsInvalid),
    ("view", {"error": [{"code": "401", "message": "Invalid credential"}]}, CredentialsInvalid),
    ("view", {"data": {"status": "success", "token": "view", "sid": "sid", "ucc": "OTHER", "kType": "View"}}, CredentialsInvalid),
    ("view", {"data": {"status": "success", "token": "", "sid": "sid", "ucc": "SYNTHETIC", "kType": "View"}}, CredentialsInvalid),
    ("view", {"data": {"status": "success", "token": "view", "sid": "sid", "ucc": "SYNTHETIC", "kType": "Trade"}}, CredentialsInvalid),
    ("trade", {"data": {"status": "success", "token": "trade", "sid": "sid", "kType": "Trade"}}, CredentialsInvalid),
    ("trade", {"data": {"status": "success", "token": "trade", "sid": "sid", "baseUrl": "https://example.invalid", "kType": "View"}}, CredentialsInvalid),
    ("trade", {"error": [{"code": "403", "message": "Invalid MPIN"}]}, CredentialsInvalid),
    ("trade", {"error": [{"code": "401", "message": "session expired"}]}, SessionExpired),
])
def test_login_rejects_false_success_and_bad_identity(fake_sdk, step, invalid, error):
    from flinttrade_gateway.brokers.kotakneo_sdk import KotakNeoSdkSession

    class InvalidNeo(ExactNeo):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            setattr(self, step, invalid)

    import neo_api_client
    neo_api_client.NeoAPI = InvalidNeo
    with pytest.raises(error):
        KotakNeoSdkSession.login(_credentials())
    assert ("totp_validate", "123456") not in ExactNeo.instances[-1].calls if step == "view" else True


@pytest.mark.parametrize("status_code,nested_code", [(401, "500"), (403, "429"), (401, "429"), (403, "500")])
def test_login_outer_auth_status_outweighs_nested_failure(fake_sdk, monkeypatch, status_code, nested_code):
    import neo_api_client

    from flinttrade_gateway.brokers.kotakneo_sdk import KotakNeoSdkSession

    class RejectedNeo(ExactNeo):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.view = {
                "status": "error",
                "stCode": status_code,
                "data": {
                    "status": "failure",
                    "error": [{"code": nested_code, "message": "synthetic nested provider detail"}],
                },
            }

    monkeypatch.setattr(neo_api_client, "NeoAPI", RejectedNeo)
    with pytest.raises(CredentialsInvalid) as raised:
        KotakNeoSdkSession.login(_credentials())
    assert raised.value.broker_code == str(status_code)
    assert "synthetic nested provider detail" not in str(raised.value)


def test_missing_mfa_requires_fresh_auth(fake_sdk):
    from flinttrade_gateway.brokers.kotakneo_sdk import KotakNeoSdkSession

    credentials = _credentials()
    credentials.pop("totp")
    with pytest.raises(MFARequired):
        KotakNeoSdkSession.login(credentials)
    assert fake_sdk.instances == []


def test_liveness_discards_ip_and_rejects_expired_response(fake_sdk):
    from flinttrade_gateway.brokers.kotakneo_sdk import KotakNeoSdkSession

    session = KotakNeoSdkSession.login(_credentials())
    assert session.liveness() is None
    fake_sdk.instances[-1].liveness_response = {"Error Message": "session expired"}
    with pytest.raises(SessionExpired):
        session.liveness()


@pytest.mark.parametrize("response,error", [
    ({"stat": "Not_Ok", "errMsg": "session expired"}, SessionExpired),
    ({"stat": "Not_Ok", "stCode": 401}, SessionExpired),
    ({"error": [{"code": "401", "message": "Invalid token"}]}, SessionExpired),
    ({"status": "error", "message": "Too many requests", "rateLimit": {"retryAfter": 7}}, RateLimitError),
    ({"stat": "Ok", "stCode": 500, "data": []}, BrokerInternal),
    ({"stat": "Ok", "stCode": 200, "data": [None]}, BrokerInternal),
])
def test_read_envelope_rejects_provider_failure_and_malformed_rows(response, error):
    from flinttrade_core.broker_read_port import BrokerReadResponseInvalid
    from flinttrade_gateway.brokers.kotakneo_sdk import validate_read_envelope

    expected = BrokerReadResponseInvalid if response.get("data") == [None] else error
    with pytest.raises(expected):
        validate_read_envelope(response, operation="order_report")


def test_read_envelope_allows_main_track_rate_limit_metadata():
    from flinttrade_gateway.brokers.kotakneo_sdk import validate_read_envelope

    response = {"stat": "Ok", "stCode": 200, "data": [], "rateLimit": {"remaining": 2}}
    assert validate_read_envelope(response, operation="order_report") is response


def _official_option_envelope() -> dict:
    return {
        "data": {
            "common_data": {
                "mktLot": "65",
                "multiplier": "1",
                "unlSymbol": "NIFTY",
                "exSeg": "nse_fo",
                "expiryDt": "2026-06-23",
            },
            "call": [{"instrument": {"neoSymbol": "nse_fo|71472"}}],
            "put": [],
        }
    }


def test_read_envelope_accepts_v307_data_only_option_chain_shape():
    from flinttrade_gateway.brokers.kotakneo_sdk import validate_read_envelope

    response = _official_option_envelope()
    assert validate_read_envelope(response, operation="option_chain") is response


def test_read_envelope_accepts_main_option_chain_rate_limit_metadata():
    from flinttrade_gateway.brokers.kotakneo_sdk import validate_read_envelope

    response = _official_option_envelope()
    response["rateLimit"] = {
        "Retry-After": "60",
        "X-RateLimit-Limit": "100",
        "X-RateLimit-Remaining": "99",
        "X-RateLimit-Reset": "1720000000",
    }
    assert validate_read_envelope(response, operation="option_chain") is response


@pytest.mark.parametrize(
    "mutate",
    [
        lambda response: response.update({"unexpected": "field"}),
        lambda response: response.update({"status": "success"}),
        lambda response: response.update({"stat": "Ok"}),
        lambda response: response.update({"status": "success", "token": "secret"}),
        lambda response: response.update({"rateLimit": {"Retry-After": 60}}),
        lambda response: response.update({"rateLimit": {"Retry-After": "\ud800"}}),
        lambda response: response["data"].update({"common_data": []}),
        lambda response: response["data"]["common_data"].update({"unlSymbol": ""}),
        lambda response: response["data"]["common_data"].update({"exSeg": True}),
        lambda response: response["data"]["common_data"].update({"expiryDt": ""}),
        lambda response: response["data"].update({"call": {}}),
        lambda response: response["data"].update({"put": [None]}),
        lambda response: response["data"].update({"fut": []}),
    ],
)
def test_read_envelope_rejects_malformed_data_only_option_chain_shape(mutate):
    from flinttrade_core.broker_read_port import BrokerReadResponseInvalid
    from flinttrade_gateway.brokers.kotakneo_sdk import validate_read_envelope

    response = _official_option_envelope()
    mutate(response)
    with pytest.raises(BrokerReadResponseInvalid):
        validate_read_envelope(response, operation="option_chain")


@pytest.mark.parametrize(
    "evidence",
    [
        {"status": "error", "message": "synthetic failure"},
        {"stat": "Not_Ok", "emsg": "synthetic failure"},
        {"error": [{"code": "500", "message": "synthetic failure"}]},
    ],
)
def test_read_envelope_never_accepts_plausible_option_data_with_failure_evidence(evidence):
    from flinttrade_core.exceptions import BrokerInternal
    from flinttrade_gateway.brokers.kotakneo_sdk import validate_read_envelope

    response = _official_option_envelope()
    response.update(evidence)
    with pytest.raises(BrokerInternal):
        validate_read_envelope(response, operation="option_chain")


@pytest.mark.parametrize(("retry_key", "retry_value"), [("Retry-After", "60"), ("retryAfter", 7)])
def test_main_shaped_top_level_429_uses_official_and_compatibility_retry_metadata(retry_key, retry_value):
    from flinttrade_gateway.brokers.kotakneo_sdk import validate_read_envelope

    response = {
        "status": "error",
        "code": 429,
        "message": "Too many requests",
        "rateLimit": {retry_key: retry_value},
    }
    with pytest.raises(RateLimitError) as raised:
        validate_read_envelope(response, operation="option_chain")
    assert raised.value.broker_code == "429"
    assert raised.value.retry_after == float(retry_value)


def test_rate_limit_retry_after_official_spelling_takes_precedence():
    from flinttrade_gateway.brokers.kotakneo_sdk import validate_read_envelope

    response = {
        "status": "error",
        "code": 429,
        "message": "Too many requests",
        "rateLimit": {"Retry-After": "60", "retryAfter": 7},
    }
    with pytest.raises(RateLimitError) as raised:
        validate_read_envelope(response, operation="option_chain")
    assert raised.value.retry_after == 60.0


def test_rate_limit_metadata_dict_subclass_cannot_execute_get_hooks():
    from flinttrade_gateway.brokers.kotakneo_sdk import validate_read_envelope

    class HostileMetadata(dict):
        def get(self, *_args, **_kwargs):
            raise RuntimeError("provider metadata hook executed")

    response = {
        "status": "error",
        "code": 429,
        "message": "Too many requests",
        "rateLimit": HostileMetadata({"Retry-After": "60"}),
    }
    with pytest.raises(RateLimitError) as raised:
        validate_read_envelope(response, operation="option_chain")
    assert raised.value.retry_after == 0


@pytest.mark.parametrize(
    ("top_level_code", "expected_error"),
    [(429, RateLimitError), (403, SessionExpired)],
)
def test_top_level_error_code_is_authoritative_over_conflicting_embedded_code(top_level_code, expected_error):
    from flinttrade_gateway.brokers.kotakneo_sdk import validate_read_envelope

    response = {
        "code": top_level_code,
        "error": {"code": 500, "message": "conflicting nested detail"},
        "rateLimit": {"Retry-After": "3"},
    }
    with pytest.raises(expected_error) as raised:
        validate_read_envelope(response, operation="option_chain")
    assert raised.value.broker_code == str(top_level_code)
    if top_level_code == 429:
        assert raised.value.retry_after == 3.0


def test_success_transport_stcode_does_not_hide_nested_provider_error_code():
    from flinttrade_gateway.brokers.kotakneo_sdk import validate_read_envelope

    response = {
        "stCode": 200,
        "error": {"code": 401, "message": "session expired"},
    }
    with pytest.raises(SessionExpired) as raised:
        validate_read_envelope(response, operation="positions")
    assert raised.value.broker_code == "401"


@pytest.mark.parametrize(
    ("nested_code", "expected_error"),
    [(401, SessionExpired), (500, BrokerInternal)],
)
def test_benign_top_level_code_does_not_hide_nested_provider_error_code(nested_code, expected_error):
    from flinttrade_gateway.brokers.kotakneo_sdk import validate_read_envelope

    response = {
        "code": 200,
        "error": {"code": nested_code, "message": "nested provider failure"},
    }
    with pytest.raises(expected_error) as raised:
        validate_read_envelope(response, operation="positions")
    assert raised.value.broker_code == str(nested_code)


def test_stcode_int_subclass_cannot_execute_comparison_hooks():
    from flinttrade_core.broker_read_port import BrokerReadResponseInvalid
    from flinttrade_gateway.brokers.kotakneo_sdk import validate_read_envelope

    class HostileStatusCode(int):
        def __ge__(self, _other):
            raise RuntimeError("provider status comparison hook executed")

    response = {"status": "error", "stCode": HostileStatusCode(500), "message": "synthetic"}
    with pytest.raises(BrokerReadResponseInvalid):
        validate_read_envelope(response, operation="positions")


def test_top_level_string_http_error_code_is_a_declared_provider_failure():
    from flinttrade_gateway.brokers.kotakneo_sdk import validate_read_envelope

    with pytest.raises(BrokerInternal) as raised:
        validate_read_envelope({"code": "503", "message": "synthetic"}, operation="positions")
    assert raised.value.broker_code == "503"


def test_real_sdk_session_preserves_malformed_read_taxonomy():
    from flinttrade_core.broker_read_port import BrokerReadResponseInvalid
    from flinttrade_gateway.brokers.kotakneo_sdk import KotakNeoSdkSession

    class MalformedNeo:
        @staticmethod
        def positions():
            return {"stat": "Ok", "stCode": 200, "data": [None]}

    session = KotakNeoSdkSession.__new__(KotakNeoSdkSession)
    session._closed = False
    session._neo = MalformedNeo()

    with pytest.raises(BrokerReadResponseInvalid):
        session.positions()


def test_real_sdk_session_canonicalises_malformed_write_response():
    from flinttrade_gateway.brokers.kotakneo_sdk import KotakNeoSdkSession

    class MalformedNeo:
        @staticmethod
        def place_order(**_params):
            return {"status": "error", "errorCode": 10**5000, "message": "synthetic"}

    session = KotakNeoSdkSession.__new__(KotakNeoSdkSession)
    session._closed = False
    session._neo = MalformedNeo()

    with pytest.raises(BrokerInternal):
        session.place_order({})


@pytest.mark.parametrize("attribute", ["reason", "status"])
@pytest.mark.parametrize("surface", ["read", "write", "login"])
def test_sdk_exception_metadata_cannot_escape_as_raw_conversion_errors(
    monkeypatch,
    attribute,
    surface,
):
    import neo_api_client

    from flinttrade_gateway.brokers.kotakneo_sdk import KotakNeoSdkSession

    class HostileSdkError(Exception):
        pass

    failure = HostileSdkError("synthetic")
    setattr(failure, attribute, 10**5000)

    class HostileNeo(ExactNeo):
        def totp_login(self, mobile_number=None, ucc=None, totp=None):
            if surface == "login":
                raise failure
            return super().totp_login(mobile_number=mobile_number, ucc=ucc, totp=totp)

        def positions(self):
            raise failure

        def place_order(self, **_params):
            raise failure

    monkeypatch.setattr(neo_api_client, "NeoAPI", HostileNeo)
    if surface == "login":
        with pytest.raises(BrokerInternal):
            KotakNeoSdkSession.login(_credentials())
        return

    session = KotakNeoSdkSession.login(_credentials())
    with pytest.raises(BrokerInternal):
        session.positions() if surface == "read" else session.place_order({})


@pytest.mark.parametrize("wrapped", [False, True])
def test_login_http_auth_errors_remain_credentials_failures(monkeypatch, wrapped):
    import neo_api_client

    from flinttrade_gateway.brokers.kotakneo_sdk import KotakNeoSdkSession

    response = httpx.Response(401, request=httpx.Request("POST", "https://example.invalid/login"))
    failure = httpx.HTTPStatusError("synthetic", request=response.request, response=response)

    class UnauthorisedNeo(ExactNeo):
        def totp_login(self, mobile_number=None, ucc=None, totp=None):
            if wrapped:
                payload = deepcopy(self.view)
                payload["Error"] = failure
                return payload
            raise failure

    monkeypatch.setattr(neo_api_client, "NeoAPI", UnauthorisedNeo)
    with pytest.raises(CredentialsInvalid) as raised:
        KotakNeoSdkSession.login(_credentials())
    assert raised.value.broker_code == "401"


@pytest.mark.parametrize(
    "response",
    [
        {"status": "error", "errorCode": 10**5000, "message": "synthetic"},
        {"status": "error", "error": [{"code": 10**5000, "message": "synthetic"}]},
    ],
)
def test_read_envelope_rejects_oversized_error_integers_canonically(response):
    from flinttrade_core.broker_read_port import BrokerReadResponseInvalid
    from flinttrade_gateway.brokers.kotakneo_sdk import validate_read_envelope

    with pytest.raises(BrokerReadResponseInvalid):
        validate_read_envelope(response, operation="positions")


@pytest.mark.parametrize(
    "retry_after",
    [pytest.param(10**5000, id="huge-integer"), pytest.param("1e100000", id="infinite-float")],
)
def test_rate_limit_retry_metadata_is_bounded_and_finite(retry_after):
    from flinttrade_gateway.brokers.kotakneo_sdk import validate_read_envelope

    response = {
        "status": "error",
        "message": "Too many requests",
        "rateLimit": {"retryAfter": retry_after},
    }
    with pytest.raises(RateLimitError) as raised:
        validate_read_envelope(response, operation="positions")
    assert raised.value.retry_after == 0


def test_read_envelope_accepts_nested_successful_margin_response():
    from flinttrade_gateway.brokers.kotakneo_sdk import validate_read_envelope

    response = {
        "data": {
            "stat": "Ok",
            "stCode": 200,
            "ordMrgn": "15.50",
            "reqdMrgn": "0",
            "avlCash": "38.19",
            "insufFund": "0",
            "rmsVldtd": "OK",
        }
    }
    assert validate_read_envelope(response, operation="margin_required") is response


def test_read_envelope_rejects_nested_margin_auth_error():
    from flinttrade_gateway.brokers.kotakneo_sdk import validate_read_envelope

    with pytest.raises(SessionExpired):
        validate_read_envelope({"data": {"stat": "Not_Ok", "errMsg": "session expired"}}, operation="margin_required")


@pytest.mark.parametrize("nested,error,code", [
    ({"status": "failure", "message": "session expired"}, SessionExpired, ""),
    ({"message": "session expired"}, SessionExpired, ""),
    ({"status": "failure", "error": [{"code": "401", "message": "synthetic private detail"}]}, SessionExpired, "401"),
    ({"status": "failure", "error": [{"code": "403", "message": "synthetic private detail"}]}, SessionExpired, "403"),
    ({"status": "failure", "error": [{"code": "429", "message": "synthetic private detail"}]}, RateLimitError, "429"),
    ({"status": "failure", "error": [{"code": "500", "message": "synthetic private detail"}]}, BrokerInternal, "500"),
])
def test_rejected_outer_envelope_preserves_nested_error_classification(nested, error, code):
    from flinttrade_gateway.brokers.kotakneo_sdk import validate_read_envelope

    with pytest.raises(error) as raised:
        validate_read_envelope({"status": "error", "data": nested}, operation="limits")
    assert raised.value.broker_code == code
    assert "synthetic private detail" not in str(raised.value)


@pytest.mark.parametrize("response,error,code", [
    (
        {"status": "error", "stCode": 401, "data": {"status": "failure", "error": [{"code": "500", "message": "synthetic backend failure"}]}},
        SessionExpired,
        "401",
    ),
    (
        {"status": "error", "stCode": 403, "data": {"status": "failure", "error": [{"code": "500", "message": "synthetic backend failure"}]}},
        SessionExpired,
        "403",
    ),
    (
        {"status": "error", "message": "session expired", "data": {"status": "failure", "message": "synthetic backend failure"}},
        SessionExpired,
        "",
    ),
    (
        {"status": "error", "stCode": 429, "data": {"status": "failure", "error": [{"code": "500", "message": "synthetic backend failure"}]}},
        RateLimitError,
        "429",
    ),
    (
        {"status": "error", "stCode": 500, "data": {"status": "failure", "error": [{"code": "400", "message": "synthetic backend failure"}]}},
        BrokerInternal,
        "500",
    ),
])
def test_rejected_outer_envelope_uses_highest_precedence_evidence(response, error, code):
    from flinttrade_gateway.brokers.kotakneo_sdk import validate_read_envelope

    with pytest.raises(error) as raised:
        validate_read_envelope(response, operation="limits")
    assert raised.value.broker_code == code
    assert "synthetic backend failure" not in str(raised.value)


def test_successful_limits_without_balance_values_is_not_zero_funds():
    from flinttrade_core.broker_read_port import BrokerReadResponseInvalid
    from flinttrade_gateway.brokers.kotakneo_sdk import validate_read_envelope

    with pytest.raises(BrokerReadResponseInvalid):
        validate_read_envelope({"stat": "Ok", "stCode": 200, "data": {}}, operation="limits")


def test_scrip_master_accepts_documented_paths_without_oms_status():
    from flinttrade_gateway.brokers.kotakneo_sdk import validate_read_envelope

    response = {"filesPaths": ["https://example.invalid/nse_cm.csv"], "baseFolder": "https://example.invalid"}
    assert validate_read_envelope(response, operation="scrip_master") is response


def test_data_only_holdings_shape_is_accepted_without_weakening_error_checks():
    from flinttrade_core.broker_read_port import BrokerReadResponseInvalid
    from flinttrade_gateway.brokers.kotakneo_sdk import validate_read_envelope

    response = {"data": [{"displaySymbol": "SYNTHETIC", "quantity": 1}]}
    assert validate_read_envelope(response, operation="holdings") is response
    with pytest.raises(SessionExpired):
        validate_read_envelope({"data": [], "error": [{"code": "401", "message": "session expired"}]}, operation="holdings")
    with pytest.raises(BrokerReadResponseInvalid):
        validate_read_envelope({"data": [None]}, operation="holdings")


@pytest.mark.parametrize("failure,error", [
    ("timeout", BrokerTimeout),
    (401, SessionExpired),
    (429, RateLimitError),
    (500, BrokerInternal),
])
def test_transport_failures_cross_facade_as_canonical_errors(fake_sdk, monkeypatch, failure, error):
    from flinttrade_gateway.brokers.kotakneo_sdk import KotakNeoSdkSession

    session = KotakNeoSdkSession.login(_credentials())
    if failure == "timeout":
        exc = httpx.ReadTimeout("synthetic")
    else:
        response = httpx.Response(failure, request=httpx.Request("GET", "https://example.invalid"))
        exc = httpx.HTTPStatusError("synthetic", request=response.request, response=response)

    def fail():
        raise exc

    monkeypatch.setattr(fake_sdk, "whatsmyip", lambda self: fail(), raising=True)
    with pytest.raises(error):
        session.liveness()


@pytest.mark.parametrize("step,mutations", [
    ("view", {"stat": "Not_Ok", "errMsg": "Invalid credential"}),
    ("view", {"error": [{"code": "401", "message": "Invalid credential"}]}),
    ("view", {"status": "success", "error": [{"code": "401", "message": "Invalid credential"}]}),
    ("trade", {"stat": "Not_Ok", "errMsg": "Invalid MPIN"}),
    ("trade", {"error": [{"code": "401", "message": "Invalid MPIN"}]}),
])
def test_nested_auth_rejection_overrides_valid_identity(fake_sdk, monkeypatch, step, mutations):
    import neo_api_client

    from flinttrade_gateway.brokers.kotakneo_sdk import KotakNeoSdkSession

    class InvalidNeo(ExactNeo):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            payload = deepcopy(getattr(self, step))
            payload["data"].update(mutations)
            setattr(self, step, payload)

    monkeypatch.setattr(neo_api_client, "NeoAPI", InvalidNeo)
    with pytest.raises(CredentialsInvalid):
        KotakNeoSdkSession.login(_credentials())


@pytest.mark.parametrize("response,error", [
    ({"stat": "Ok", "data": {"stat": "Not_Ok", "errMsg": "session expired", "Net": "0", "MarginUsed": "0"}}, SessionExpired),
    ({"stat": "Ok", "data": {"status": "success", "error": [{"code": "401", "message": "session expired"}], "Net": "0", "MarginUsed": "0"}}, SessionExpired),
    ({"stat": "Ok", "data": {"status": "success", "error": [{"code": "500", "message": "failed"}], "Net": "0", "MarginUsed": "0"}}, BrokerInternal),
])
def test_nested_limits_rejection_never_maps_to_zero_funds(response, error):
    from flinttrade_gateway.brokers.kotakneo_mapping import from_kotak_funds

    with pytest.raises(error):
        from_kotak_funds(response)


@pytest.mark.parametrize("response", [
    {"stat": "Ok"},
    {"stat": "Ok", "data": [None]},
    {"status": 401, "stat": "Ok", "data": []},
    {"status": None, "stat": "Ok", "data": []},
    {"stat": None, "status": "success", "data": []},
    {"status": "success", "stat": "Not_Ok", "data": []},
    {"stat": "Ok", "data": {"stat": "Ok"}},
    {"data": {"stat": "Ok", "data": [None]}},
])
def test_order_history_requires_consistent_status_and_real_rows(response):
    from flinttrade_core.broker_read_port import BrokerReadResponseInvalid
    from flinttrade_gateway.brokers.kotakneo_sdk import validate_read_envelope

    with pytest.raises(BrokerReadResponseInvalid):
        validate_read_envelope(response, operation="order_history")


@pytest.mark.parametrize("response", [
    {"stat": "Ok", "stCode": 200, "data": []},
    {"data": {"stat": "Ok", "stCode": 200, "data": []}},
])
def test_order_history_accepts_both_official_success_envelopes(response):
    from flinttrade_gateway.brokers.kotakneo_sdk import validate_read_envelope

    assert validate_read_envelope(response, operation="order_history") is response


@pytest.mark.parametrize("status,error", [
    (401, SessionExpired), (403, SessionExpired), (429, RateLimitError), (500, BrokerInternal),
    ("timeout", BrokerTimeout), ("connection", NetworkError),
])
def test_installed_sdk_embedded_exceptions_translate_with_offline_transport(status, error):
    import neo_api_client

    from flinttrade_gateway.brokers.kotakneo_sdk import KotakNeoSdkSession

    def respond(request):
        if status == "timeout":
            raise httpx.ReadTimeout("synthetic", request=request)
        if status == "connection":
            raise httpx.ConnectError("synthetic", request=request)
        return httpx.Response(status, json={"error": "synthetic"})

    neo = neo_api_client.NeoAPI(
        consumer_key="synthetic", access_token=None, transport=httpx.MockTransport(respond),
    )
    neo.api_client.rest_client.raise_on_error = True
    neo.configuration.edit_token = "synthetic"
    neo.configuration.edit_sid = "synthetic"
    session = KotakNeoSdkSession.__new__(KotakNeoSdkSession)
    session._neo = neo
    session._closed = False
    try:
        with pytest.raises(error) as raised:
            session.liveness()
        if isinstance(status, int):
            assert raised.value.broker_code == str(status)
        assert "synthetic" not in str(raised.value).lower()
    finally:
        session.close()


def test_two_factor_required_sdk_reply_is_session_expiry():
    from flinttrade_gateway.brokers.kotakneo_sdk import validate_read_envelope

    with pytest.raises(SessionExpired):
        validate_read_envelope(
            {"Error Message": "Complete the 2fa process before accessing this application"},
            operation="whatsmyip",
        )


def test_liveness_sdk_info_logging_does_not_emit_ip(tmp_path):
    script = """
import logging
import os
import httpx
from flinttrade_gateway.brokers.kotakneo_sdk import KotakNeoSdkSession, _sdk_class

root_handlers = tuple(logging.getLogger().handlers)
NeoAPI = _sdk_class()
assert os.environ['NEO_LOG_LEVEL'] == 'INFO'
assert os.environ['NEO_LOG_FILE_ENABLED'] == 'true'

def respond(request):
    return httpx.Response(200, json={
        'data': [{'ip': 'SYNTHETIC_IP_SENTINEL', 'time': 'synthetic'}],
        'stCode': 1000, 'status': 'success',
    })

neo = NeoAPI(consumer_key='synthetic', access_token=None,
             transport=httpx.MockTransport(respond))
neo.configuration.edit_token = 'synthetic'
neo.configuration.edit_sid = 'synthetic'
session = KotakNeoSdkSession.__new__(KotakNeoSdkSession)
session._neo = neo
session._closed = False
assert session.liveness() is None
assert tuple(logging.getLogger().handlers) == root_handlers
session.close()
"""
    env = os.environ.copy()
    env.update({
        "NEO_LOG_LEVEL": "INFO", "NEO_LOG_FILE_ENABLED": "true",
        "NEO_LOG_FILE_LEVEL": "INFO", "NEO_LOG_FILE_PATH": str(tmp_path / "sdk.log"),
    })
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=tmp_path, env=env,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    log = (tmp_path / "sdk.log").read_text()
    assert "api_request_success" in result.stdout + log
    assert "SYNTHETIC_IP_SENTINEL" not in result.stdout + result.stderr + log
