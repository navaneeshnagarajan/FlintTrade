"""Contracts against the installed, attested Kotak Neo v3 SDK."""

from __future__ import annotations

import os
import subprocess
import sys
from copy import deepcopy

import httpx
import pytest
from flinttrade_core.exceptions import (
    BrokerInternal, BrokerTimeout, CredentialsInvalid, MFARequired, NetworkError, RateLimitError, SessionExpired,
)

pytestmark = pytest.mark.unit


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
    from flinttrade_gateway.brokers.kotakneo_sdk import validate_read_envelope

    with pytest.raises(error):
        validate_read_envelope(response, operation="order_report")


def test_read_envelope_allows_main_track_rate_limit_metadata():
    from flinttrade_gateway.brokers.kotakneo_sdk import validate_read_envelope

    response = {"stat": "Ok", "stCode": 200, "data": [], "rateLimit": {"remaining": 2}}
    assert validate_read_envelope(response, operation="order_report") is response


def test_read_envelope_accepts_nested_successful_margin_response():
    from flinttrade_gateway.brokers.kotakneo_sdk import validate_read_envelope

    response = {"data": {"stat": "Ok", "reqdMrgn": "15.50", "avlCash": "38.19"}}
    assert validate_read_envelope(response, operation="margin_required") is response


def test_read_envelope_rejects_nested_margin_auth_error():
    from flinttrade_gateway.brokers.kotakneo_sdk import validate_read_envelope

    with pytest.raises(SessionExpired):
        validate_read_envelope({"data": {"stat": "Not_Ok", "errMsg": "session expired"}}, operation="margin_required")


def test_successful_limits_without_balance_values_is_not_zero_funds():
    from flinttrade_gateway.brokers.kotakneo_sdk import validate_read_envelope

    with pytest.raises(BrokerInternal):
        validate_read_envelope({"stat": "Ok", "stCode": 200, "data": {}}, operation="limits")


def test_scrip_master_accepts_documented_paths_without_oms_status():
    from flinttrade_gateway.brokers.kotakneo_sdk import validate_read_envelope

    response = {"filesPaths": ["https://example.invalid/nse_cm.csv"], "baseFolder": "https://example.invalid"}
    assert validate_read_envelope(response, operation="scrip_master") is response


def test_data_only_holdings_shape_is_accepted_without_weakening_error_checks():
    from flinttrade_gateway.brokers.kotakneo_sdk import validate_read_envelope

    response = {"data": [{"displaySymbol": "SYNTHETIC", "quantity": 1}]}
    assert validate_read_envelope(response, operation="holdings") is response
    with pytest.raises(SessionExpired):
        validate_read_envelope({"data": [], "error": [{"code": "401", "message": "session expired"}]}, operation="holdings")
    with pytest.raises(BrokerInternal):
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
    from flinttrade_gateway.brokers.kotakneo_sdk import validate_read_envelope

    with pytest.raises(BrokerInternal):
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
