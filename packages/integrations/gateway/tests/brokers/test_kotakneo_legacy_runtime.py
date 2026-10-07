"""Legacy mapper/adapter correspondence through the real pinned SDK transport.

Only synthetic sessions and httpx.MockTransport are used; no broker login runs.
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
from importlib.metadata import distribution
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest

from flinttrade_core.broker_read_port import BrokerReadResponseInvalid
from flinttrade_core.exceptions import BrokerInternal, BrokerTimeout, OrderRejectedByBroker, UnsupportedCapabilityError
from flinttrade_core.models import Order
from flinttrade_gateway.brokers import kotakneo_mapping as M
from flinttrade_gateway.brokers._base import ROUTER_TOKEN, Session
from flinttrade_gateway.brokers.kotakneo import KotakNeoAdapter
from flinttrade_gateway.brokers.kotakneo_sdk import KotakNeoSdkSession, _sdk_class

pytestmark = pytest.mark.unit


@pytest.fixture(scope="session", autouse=True)
def owned_source_integrity():
    """Bind tracked and new closure files despite concurrent unrelated repairs."""
    root = Path(__file__).resolve().parents[5]
    names = (
        "packages/core/core/src/flinttrade_core/models.py",
        "packages/integrations/gateway/src/flinttrade_gateway/brokers/kotakneo.py",
        "packages/integrations/gateway/src/flinttrade_gateway/brokers/kotakneo_mapping.py",
        "packages/integrations/gateway/src/flinttrade_gateway/brokers/kotakneo_sdk.py",
        "packages/integrations/gateway/tests/brokers/test_kotakneo_mapping.py",
        "packages/integrations/gateway/tests/brokers/test_kotakneo_legacy_repairs.py",
        "packages/integrations/gateway/tests/brokers/test_kotakneo_legacy_runtime.py",
    )

    def fingerprint():
        return {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in names}

    before = fingerprint()
    yield before
    assert fingerprint() == before, "Owned Kotak closure files changed during verification"


@pytest.fixture
def runtime():
    facades = []

    def build(response, *, http_status=200):
        requests = []

        def respond(request):
            requests.append(request)
            if isinstance(response, BaseException):
                raise response
            return httpx.Response(http_status, json=response)

        neo = _sdk_class()(
            consumer_key="synthetic", access_token=None, transport=httpx.MockTransport(respond),
        )
        neo.configuration.edit_token = "synthetic"
        neo.configuration.edit_sid = "synthetic"
        neo.configuration.base_url = "https://example.invalid"
        facade = KotakNeoSdkSession.__new__(KotakNeoSdkSession)
        facade._neo = neo
        facade._closed = False
        facades.append(facade)
        resolver_calls = []

        def resolve(symbol, exchange):
            resolver_calls.append((symbol, exchange))
            return "SYNTHETIC-EQ"

        adapter = KotakNeoAdapter(client_factory=lambda _session: facade, symbol_resolver=resolve)
        session = Session(
            access_token="synthetic", expires_at=time.time() + 60, account_id="synthetic", adapter_id="kotakneo",
        )
        return adapter, session, facade, requests, resolver_calls

    yield build
    for facade in facades:
        facade.close()


@pytest.mark.parametrize(
    "response,code",
    [
        ({"stat": "Ok", "stCode": 200, "status_code": 400, "nOrdNo": "OID-1", "errMsg": "Order is completed"}, "400"),
        ({"stat": "Not_Ok", "stCode": 1021, "nOrdNo": "OID-1", "errMsg": "Order is completed"}, "1021"),
    ],
)
def test_pinned_facade_rejects_supplied_http_failure_and_retains_broker_reason(runtime, response, code):
    _, _, facade, requests, _ = runtime(response)
    with pytest.raises(OrderRejectedByBroker) as raised:
        facade.modify_order({
            "order_id": "OID-1", "order_type": "L", "price": "9.40", "quantity": "10", "validity": "DAY",
            "trigger_price": "0", "disclosed_quantity": "0",
        })
    assert raised.value.broker_code == code
    assert raised.value.broker_message == "Order is completed"
    assert len(requests) == 1


@pytest.mark.parametrize("status", [502, 503, 504])
def test_pinned_write_unknown_http_outcome_cannot_be_hidden_by_generic_provider_rejection(runtime, status):
    _, _, facade, requests, _ = runtime({
        "stat": "Ok", "stCode": 200, "code": 400, "status_code": status, "nOrdNo": "OID-1",
        "message": "Uncertain provider response",
    })
    with pytest.raises(BrokerInternal) as raised:
        facade.modify_order({
            "order_id": "OID-1", "order_type": "L", "price": "9.40", "quantity": "10", "validity": "DAY",
        })
    assert raised.value.broker_code == str(status)
    assert not isinstance(raised.value, OrderRejectedByBroker)
    assert len(requests) == 1


def test_pinned_write_timeout_stays_unknown_with_one_dispatch_and_no_replay(runtime):
    _, _, facade, requests, _ = runtime(httpx.ReadTimeout("synthetic timeout"))
    with pytest.raises(BrokerTimeout):
        facade.modify_order({
            "order_id": "OID-1", "order_type": "L", "price": "9.40", "quantity": "10", "validity": "DAY",
        })
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("exchange", ["NSE", "BSE", "NFO", "BFO", "MCX"])
@pytest.mark.parametrize("operation", ["place", "margin"])
async def test_canonical_mtf_cannot_dispatch_or_resolve_without_verified_local_eligibility(runtime, exchange, operation):
    adapter, session, _, requests, resolver_calls = runtime({"stat": "Ok", "stCode": 200, "nOrdNo": "OID-1"})
    order = Order(
        symbol="SYNTHETIC", action="BUY", exchange=exchange, product="MTF", pricetype="LIMIT",
        quantity="10", price="9.40",
    )
    with pytest.raises(UnsupportedCapabilityError, match="MTF.*eligibility"):
        if operation == "place":
            await adapter.place_order(session, order, _router_token=ROUTER_TOKEN)
        else:
            await adapter.margin_calculator(session, order)
    assert requests == []
    assert resolver_calls == []


def test_installed_kotak_pin_and_request_chain_match_distribution_record(record_property, owned_source_integrity):
    import neo_api_client
    from neo_api_client import settings

    dist = distribution("kotakneoapi")
    metadata = dist.read_text("direct_url.json")
    assert isinstance(metadata, str)
    source = json.loads(metadata)
    assert dist.version == "3.0.8"
    assert source["vcs_info"]["commit_id"] == "9a37488d77dc96442ee2a90ef78462e688cf4856"
    assert source["vcs_info"]["requested_revision"] == "9a37488d77dc96442ee2a90ef78462e688cf4856"
    module_path = neo_api_client.__file__
    assert isinstance(module_path, str)
    assert Path(module_path).parent.samefile(str(dist.locate_file("neo_api_client")))
    assert settings.place_order_product_allowed_values == ["CNC", "NRML", "MIS", "MTF"]
    chain = (
        "neo_api_client/settings.py", "neo_api_client/req_data_validation.py", "neo_api_client/neo_api.py",
        "neo_api_client/services/order.py", "neo_api_client/services/modify_order.py", "neo_api_client/rest.py",
        "neo_api_client/services/order_history.py",
    )
    files = dist.files
    assert files is not None
    records = {str(item): item for item in files}
    evidence = {}
    for name in chain:
        entry = records[name]
        digest = hashlib.sha256(Path(entry.locate()).read_bytes()).digest()
        entry_hash = entry.hash
        assert entry_hash is not None
        assert entry_hash.mode == "sha256"
        assert base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii") == entry_hash.value
        evidence[name] = digest.hex()
    record_property("kotakneo_sdk_pin", source["vcs_info"]["commit_id"])
    record_property("kotakneo_sdk_request_chain_sha256", json.dumps(evidence, sort_keys=True))
    record_property("kotak_legacy_source_sha256", json.dumps(owned_source_integrity, sort_keys=True))
    print("KOTAK_PINNED_REQUEST_CHAIN " + json.dumps(evidence, sort_keys=True))


def _body(request):
    assert request.headers["content-type"] == "application/x-www-form-urlencoded"
    form = parse_qs(request.content.decode("utf-8"))
    assert set(form) == {"jData"}
    return json.loads(form["jData"][0])


def test_canonical_mtf_maps_through_real_pinned_placement_serializer_but_not_adapter_eligibility(runtime):
    _, _, facade, requests, _ = runtime({"stat": "Ok", "stCode": 200, "nOrdNo": "OID-1"})
    order = Order(
        symbol="SYNTHETIC", action="BUY", exchange="NSE", product="MTF", pricetype="LIMIT",
        quantity="10", price="9.40", disclosed_quantity="2",
    )
    response = facade.place_order(M.to_place_order_params(order, "SYNTHETIC-EQ", tag="TAG-1"))
    assert response == {"stat": "Ok", "stCode": 200, "nOrdNo": "OID-1"}
    assert len(requests) == 1
    assert requests[0].method == "POST"
    assert requests[0].url.path == "/quick/order/rule/ms/place"
    assert _body(requests[0]) == {
        "am": "NO", "dq": "2", "es": "nse_cm", "mp": "0", "pc": "MTF", "pr": "9.40", "pt": "L",
        "qt": "10", "rt": "DAY", "tp": "0", "ts": "SYNTHETIC-EQ", "tt": "B", "ig": "TAG-1",
        "os": "NEOTRADEAPI",
    }


@pytest.mark.asyncio
async def test_real_legacy_adapter_preserves_exact_place_modify_wire_and_ack_only(runtime):
    adapter, session, _, requests, _ = runtime({"stat": "Ok", "stCode": 200, "nOrdNo": "OID-1"})
    session.algo_id = "TAG-1"
    order = Order(
        symbol="SYNTHETIC", action="SELL", exchange="NSE", product="MIS", pricetype="SL",
        price="9.40", trigger_price="9.45", quantity="10", disclosed_quantity="2", validity="IOC", variety="amo",
    )
    assert await adapter.place_order(session, order, _router_token=ROUTER_TOKEN) == "OID-1"
    assert _body(requests[0]) == {
        "am": "YES", "dq": "2", "es": "nse_cm", "mp": "0", "pc": "MIS", "pr": "9.40", "pt": "SL",
        "qt": "10", "rt": "IOC", "tp": "9.45", "ts": "SYNTHETIC-EQ", "tt": "S", "ig": "TAG-1",
        "os": "NEOTRADEAPI",
    }
    assert await adapter.modify_order(
        session, "OID-1",
        {
            "pricetype": "LIMIT", "order_type": "L", "price": "9.50", "quantity": "10", "validity": "DAY",
            "disclosed_quantity": "10", "amo": "YES", "variety": "amo",
            "symbol": "SYNTHETIC", "exchange": "NSE", "action": "SELL", "product": "MIS", "broker_product": "MIS",
        },
        _router_token=ROUTER_TOKEN,
    ) is None
    assert requests[1].url.path == "/quick/order/vr/modify"
    assert _body(requests[1]) == {
        "mp": "0", "dq": "10", "vd": "DAY", "pr": "9.50", "pt": "L", "am": "YES", "tp": "0",
        "qt": "10", "no": "OID-1", "os": "NEOTRADEAPI",
    }
    assert len(requests) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,changes",
    [
        ("place", {"quantity": "2", "disclosed_quantity": "3"}),
        ("modify", {"quantity": "2", "disclosed_quantity": "3"}),
        ("modify", {"pricetype": "LIMIT", "order_type": "MKT"}),
    ],
)
async def test_real_adapter_refuses_quantity_or_alias_contradictions_before_pinned_transport(runtime, operation, changes):
    adapter, session, _, requests, resolver_calls = runtime({"stat": "Ok", "stCode": 200, "nOrdNo": "OID-1"})
    order = Order(symbol="SYNTHETIC", action="BUY", pricetype="LIMIT", price="9.40", quantity="10")
    with pytest.raises(UnsupportedCapabilityError):
        if operation == "place":
            await adapter.place_order(session, order.model_copy(update=changes), _router_token=ROUTER_TOKEN)
        else:
            await adapter.modify_order(
                session, "OID-1", {"price": "9.40", "quantity": "10", **changes}, _router_token=ROUTER_TOKEN,
            )
    assert requests == []
    assert resolver_calls == []


def _read_order_row(**observations):
    row = {
        "nOrdNo": "OID-1", "ordSt": "cancelled", "trdSym": "SYNTHETIC-EQ", "sym": "SYNTHETIC",
        "exSeg": "nse_cm", "trnsTp": "B", "prcTp": "L", "prod": "NRML", "qty": "100", "fldQty": "40",
        "prc": "9.40", "trgPrc": "0", "avgPrc": "9.35", "exOrdId": "EX-1", "vldt": "DAY",
    }
    row.update(observations)
    return row


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["book", "history"])
@pytest.mark.parametrize(
    "observations",
    [
        {"qty": "1", "fldQty": "2"}, {"qty": "9007199254740992", "fldQty": "9007199254740993"},
        {"qty": "-1"}, {"qty": "1.5"}, {"fldQty": "-1"}, {"fldQty": "1.5"},
        {"nOrdNo": " OID-1"}, {"exchOrdId": "EX-2"}, {"ordDur": "IOC"},
    ],
)
async def test_pinned_order_reads_reach_strict_legacy_row_validation(runtime, operation, observations):
    # OrderHistoryAPI adds the outer data wrapper; inject the HTTP body, not
    # an already SDK-wrapped response (which would test the wrong boundary).
    response = {"stat": "Ok", "stCode": 200, "data": [_read_order_row(**observations)]}
    adapter, session, _, requests, _ = runtime(response)
    with pytest.raises(BrokerReadResponseInvalid):
        if operation == "history":
            await adapter.order_history(session, "OID-1")
        else:
            await adapter.order_book(session)
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_pinned_history_preserves_all_partial_cancel_transitions_and_raw_status(runtime):
    response = {"stat": "Ok", "stCode": 200, "data": [
        _read_order_row(), _read_order_row(ordSt="open", fldQty="0"), _read_order_row(),
    ]}
    adapter, session, _, requests, _ = runtime(response)
    rows = await adapter.order_history(session, "OID-1")
    assert [row["status"] for row in rows] == ["cancelled", "open", "cancelled"]
    assert [row["attempt_state"] for row in rows] == ["CANCELLED", "WORKING", "CANCELLED"]
    assert [row["filled_quantity"] for row in rows] == ["40", "0", "40"]
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_pinned_history_guard_distinguishes_empty_from_malformed_before_legacy_helper(runtime):
    inner = {"stat": "Ok", "stCode": 200, "data": []}
    adapter, session, _, requests, _ = runtime(inner)
    assert await adapter.order_history(session, "OID-1") == []
    assert len(requests) == 1
    malformed = {"stat": "Ok", "stCode": 200, "data": [None]}
    adapter, session, _, requests, _ = runtime(malformed)
    with pytest.raises(BrokerReadResponseInvalid):
        await adapter.order_history(session, "OID-1")
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_pinned_trade_report_keeps_independent_qty_fields_and_every_same_order_fill(runtime):
    row = {
        "nOrdNo": "OID-1", "trdSym": "SYNTHETIC-EQ", "sym": "SYNTHETIC", "exSeg": "nse_cm",
        "trnsTp": "B", "prod": "NRML", "qty": "0", "fldQty": "1", "avgPrc": "9.39", "flPrc": "9.40",
        "flDtTm": "22-Jan-2025 14:32:53",
    }
    adapter, session, _, requests, _ = runtime({"stat": "Ok", "stCode": 200, "data": [row, row]})
    fills = await adapter.order_trades(session, "OID-1")
    assert [(fill["orderid"], fill["quantity"], fill["price"]) for fill in fills] == [
        ("OID-1", "1", "9.39"), ("OID-1", "1", "9.39"),
    ]
    assert len(requests) == 1
    assert requests[0].url.path == "/quick/user/trades"


@pytest.mark.parametrize(
    "response",
    [
        {"stat": "Ok", "stCode": 200, "nOrdNo": "OID-1", "Error": "Validation reason"},
        {"stat": "Ok", "stCode": 200, "nOrdNo": "OID-1", "Error Message": "Validation reason"},
        {"stat": "Ok", "stCode": 200, "nOrdNo": "OID-1", "error": [{"code": "41", "message": "Validation reason"}]},
        {"stat": "Not_Ok", "stCode": 410, "nOrdNo": "OID-1", "emsg": "Validation reason"},
        {"stat": "Ok", "stCode": 200, "data": {"stat": "Not_Ok", "stCode": 410, "errMsg": "Validation reason"}},
    ],
)
def test_pinned_write_failure_reason_survives_error_or_nested_envelopes_without_execution_claim(runtime, response):
    _, _, facade, requests, _ = runtime(response)
    with pytest.raises(OrderRejectedByBroker) as raised:
        facade.modify_order({
            "order_id": "OID-1", "order_type": "L", "price": "9.40", "quantity": "10", "validity": "DAY",
        })
    assert raised.value.broker_message == "Validation reason"
    assert "Validation reason" not in str(raised.value)
    assert len(requests) == 1


@pytest.mark.parametrize("http_status", [502, 503, 504])
@pytest.mark.parametrize("operation", ["place", "modify", "cancel"])
def test_pinned_actual_http_failure_cannot_be_hidden_by_a_positive_native_ack(runtime, http_status, operation):
    _, _, facade, requests, _ = runtime(
        {"stat": "Ok", "stCode": 200, "nOrdNo": "OID-1"}, http_status=http_status,
    )
    with pytest.raises(BrokerInternal) as raised:
        if operation == "place":
            facade.place_order({
                "exchange_segment": "nse_cm", "product": "MIS", "price": "9.40", "order_type": "L",
                "quantity": "10", "validity": "DAY", "trading_symbol": "SYNTHETIC-EQ", "transaction_type": "B",
            })
        elif operation == "modify":
            facade.modify_order({
                "order_id": "OID-1", "order_type": "L", "price": "9.40", "quantity": "10", "validity": "DAY",
            })
        else:
            facade.cancel_order("OID-1")
    assert raised.value.broker_code == str(http_status)
    assert not isinstance(raised.value, OrderRejectedByBroker)
    assert len(requests) == 1
