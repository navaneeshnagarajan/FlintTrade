"""Delta preflight at the public factory with real safety, gate and router.

NSE is an independent synthetic
tradeable admission envelope, not a Delta venue/eligibility assertion. The
separately labelled CRYPTO diagnostic projects only this instance's membership;
ordinary CRYPTO remains frozen. ACKs, books and the bound REST transport are
synthetic; these controls establish neither execution nor native readiness.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest

from flinttrade_core.auth_routes import _create_token
from flinttrade_core.exceptions import BrokerError, SafetyBypassError
from flinttrade_core.models import Exchange, Order
from flinttrade_engine.safety import SafetyGate, SafetySystem
from flinttrade_gateway.brokers import delta_mapping
from flinttrade_gateway.brokers._base import Session
from flinttrade_gateway.brokers.delta import DeltaAdapter
from flinttrade_gateway.router import BrokerRouter
from flinttrade_gateway.routing_config import RoutingConfig, RoutingHint
from packages.core.core.tests.test_ingress_safety_runtime import exact_egress_latch as exact_egress_latch
from packages.core.core.tests.test_order_route_evidence_runtime import route_stack as route_stack

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[4]
BASE = {
    "broker": "deltaexchange", "account_id": "route-account", "symbol": "BTCUSD", "exchange": "NSE",
    "product": "MIS", "action": "SELL", "quantity": "2", "price": "100", "pricetype": "LIMIT",
}
WIRE = {
    "product_symbol": "BTCUSD", "size": 2, "side": "sell", "time_in_force": "gtc",
    "order_type": "limit_order", "limit_price": "100",
}
PATHS = ["/api/v1/orders/place", "/api/v1/orders/deltaexchange/place"]


@pytest.fixture(autouse=True)
def delta_source_identity():
    paths = [str(Path(__file__).relative_to(ROOT)),
        "packages/core/core/src/flinttrade_core/order_routes.py",
        "packages/core/core/src/flinttrade_core/models.py",
        "packages/core/core/src/flinttrade_core/app.py",
        "packages/services/engine/src/flinttrade_engine/safety.py",
        "packages/services/engine/src/flinttrade_engine/reduce_only.py",
        "packages/integrations/gateway/src/flinttrade_gateway/router.py",
        "packages/integrations/gateway/src/flinttrade_gateway/brokers/delta.py",
        "packages/integrations/gateway/src/flinttrade_gateway/brokers/delta_mapping.py",
        "packages/integrations/gateway/src/flinttrade_gateway/brokers/delta_order_mapping.py",
    ]
    def identities():
        return {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in sorted(paths)}
    before = identities()
    print("DELTA_INGRESS_SOURCE " + json.dumps(before, sort_keys=True), flush=True)
    yield
    assert identities() == before, "Exercised source or untracked regression changed during the test"


@pytest.fixture
def delta_stack(route_stack, monkeypatch):
    import flinttrade_engine.safety as safety_module

    app, source, _sdk, old_router = route_stack
    safety = app.config["SAFETY"]
    assert type(safety) is SafetySystem
    gate = SafetyGate()
    stack = SimpleNamespace(
        app=app, source=source, safety=safety, gate=gate, wire=[], consumed=[], minted=[],
        checked=[], mapped=[], invoked=[], reads=[], violations=[], l1_projections=[],
    )
    # Observe every actual external read, including margin, without replacing
    # the safety/admission implementation or manufacturing execution evidence.
    for name in ("positions", "order_book", "funds", "trade_book", "holdings", "quotes", "margin_calculator"):
        original = getattr(source, name)
        async def read(*args, _original=original, _name=name, **kwargs):
            stack.reads.append(_name)
            return await _original(*args, **kwargs)
        monkeypatch.setattr(source, name, read)

    def transport(method, url, headers, body):
        try:
            assert (method, urlsplit(url).hostname, urlsplit(url).path) == ("POST", "fixture.invalid", "/v2/orders")
            assert headers["api-key"] == "synthetic-key" and headers["timestamp"] == "1700000000"
            assert headers["signature"] == delta_mapping.sign_request(
                "synthetic-secret", method, "1700000000", "/v2/orders", "", body,
            )
            stack.wire.append(json.loads(body))
            return 200, {"success": True, "result": {"id": 41, "product_id": 27}}
        except AssertionError as exc:
            stack.violations.append(str(exc))
            raise

    session = Session("synthetic-key", 4102444800.0, "route-account", "deltaexchange")
    session.extra.update({
        "api_secret": "synthetic-secret", "environment": "india_testnet",
        "rest_base": "https://fixture.invalid", "user_id": "42", "transport": transport,
    })
    stack.session = session

    def resolve(context, broker, account):
        assert (broker, account) == ("deltaexchange", "route-account")
        if context is not None:
            assert context.selector == "deltaexchange:route-account"
        return session

    def consume(identifier):
        result = gate.consume(identifier)
        stack.consumed.append(result)
        return result

    original_mint = safety_module.gate_order
    def mint(order, context, **kwargs):
        result = original_mint(order, context, **kwargs)
        stack.minted.append((order, context, result))
        return result
    monkeypatch.setattr(safety_module, "gate_order", mint)

    original_check = safety.check_order
    def check(order, **kwargs):
        results = original_check(order, **kwargs)
        stack.checked.append([{"layer": row.layer, "passed": row.passed, "reason": row.reason} for row in results])
        return results
    monkeypatch.setattr(safety, "check_order", check)

    original_map = delta_mapping.to_place_payload
    stack.legacy_builder = original_map
    def mapping(order, **kwargs):
        stack.mapped.append(order.model_dump(mode="json"))
        return original_map(order, **kwargs)
    monkeypatch.setattr(delta_mapping, "to_place_payload", mapping)

    adapter = DeltaAdapter(transport_factory=lambda: transport, clock=lambda: 1700000000)
    original_place = adapter.place_order
    stack.direct_place = original_place
    async def place(session, order, **kwargs):
        stack.invoked.append(order.model_dump(mode="json"))
        return await original_place(session, order, **kwargs)
    monkeypatch.setattr(adapter, "place_order", place)
    stack.adapter = adapter
    selector = "deltaexchange:route-account"
    config = RoutingConfig.from_workspace({
        "registered": [selector], "execution": {"default": selector},
        "data": {name: selector for name in ("ticks", "historical", "option_chains", "quote")},
        "account_acls": {"deltaexchange": {"route-account": ["operator"]}},
    })
    router = BrokerRouter({"deltaexchange": adapter}, resolve, consume_gate=consume, config=config,
                          backend_lease_proof=old_router.backend_lease_proof)
    stack.router = router
    app.config["BROKER_ROUTER"] = router
    app.config["NATIVE_ADAPTERS"] = {"deltaexchange": source}
    app.config["REGISTRY"] = SimpleNamespace(get_session_for=lambda b, a: resolve(None, b, a))
    source.position_rows = [{
        "symbol": "BTCUSD", "exchange": "NSE", "product": "MIS", "quantity": "10",
        "multiplier": 1, "cross_currency": True, "fx_rate": 1,
    }]
    source.order_rows = []
    tradeable = frozenset(safety_module._TRADEABLE_EXCHANGES)
    assert "CRYPTO" not in tradeable
    try:
        yield stack
    finally:
        router.revoke_and_drain(timeout=0)
        assert stack.violations == []
        assert frozenset(safety_module._TRADEABLE_EXCHANGES) == tradeable


def _request(stack, fields, path=PATHS[0], *, configured_default=False):
    body = {**BASE, **deepcopy(fields)}
    if configured_default:
        del body["broker"], body["account_id"]
    stack.source.position_rows[0]["exchange"] = body["exchange"]
    response = stack.app.test_client().post(path, json=body, headers={
        "Authorization": "Bearer " + _create_token("operator", mode="live", live_mode_unlocked=True),
    })
    observed = {
        "request": body, "path": path, "status": response.status_code, "response": response.get_json(),
        "minted": [order.model_dump(mode="json") for order, _ctx, _gate in stack.minted],
        "consumed": stack.consumed, "wire": stack.wire, "checked": stack.checked,
        "mapped": stack.mapped, "invoked": stack.invoked, "reads": stack.reads,
        "l1_projections": stack.l1_projections, "session_transport_bound": callable(stack.session.extra["transport"]),
    }
    print("DELTA_INGRESS_OBSERVED " + json.dumps(observed, sort_keys=True), flush=True)
    return response


def _no_admission(stack):
    from flinttrade_engine.laya import process_laya
    from flinttrade_engine.reduce_only import contract_key, reserved_exit

    assert stack.minted == [] and stack.consumed == [] and stack.invoked == [] and stack.wire == []
    assert stack.checked == [] and stack.reads == [] and stack.source.reads == []
    assert process_laya().decision_log() == ()
    key = contract_key(mode="live", adapter="deltaexchange", account="route-account",
                       symbol="BTCUSD", exchange=stack.source.position_rows[0]["exchange"], product="MIS")
    assert reserved_exit(key) == 0
    with stack.safety.order_admission("deltaexchange:route-account") as lease:
        assert lease.reservations == ()


def test_raw_post_only_cannot_disappear_before_canonical_selection(delta_stack):
    response = _request(delta_stack, {"post_only": True})
    assert response.status_code == 400, response.get_json()
    _no_admission(delta_stack)


def test_regular_trailing_is_purely_refused_before_books_margin_and_authority(delta_stack):
    response = _request(delta_stack, {"trailing_jump": "5"})
    assert response.status_code == 400, response.get_json()
    _no_admission(delta_stack)
    assert delta_stack.mapped[0]["trailing_jump"] == "5"


# The exact neighbouring unsigned-attribute set in the actual legacy builder.
# None alone is absent there: do not reinterpret False, 0, empty text/container
# or malformed values as authorised inactive intent at this raw HTTP seam.
NATIVE_FIELDS = (
    "native", "post_only", "client_order_id", "stop_order_type", "stop_price", "trail_amount",
    "stop_trigger_method", "bracket_stop_loss_limit_price", "bracket_take_profit_limit_price",
    "bracket_stop_trigger_method", "reduce_only",
)


@pytest.mark.parametrize("path", PATHS, ids=["ordinary", "named"])
@pytest.mark.parametrize("field", NATIVE_FIELDS)
@pytest.mark.parametrize("value", [True, False, 0, "", [], {}],
                         ids=["active", "false", "zero", "empty-text", "empty-list", "empty-object"])
def test_unrepresented_raw_neighbours_retain_exact_legacy_refusal(delta_stack, field, value, path):
    fields = {field: value}
    with pytest.raises(BrokerError, match="explicit native intent"):
        delta_stack.legacy_builder(SimpleNamespace(**{**BASE, **fields}))
    response = _request(delta_stack, fields, path)
    assert response.status_code == 400, response.get_json()
    _no_admission(delta_stack)
    assert delta_stack.mapped == []


@pytest.mark.parametrize("fields", [
    pytest.param({}, id="absent"),
    *(pytest.param({field: None}, id="null-" + field) for field in NATIVE_FIELDS),
    pytest.param({"target_price": "0", "trailing_jump": "0", "stop_loss_price": "0", "iceberg_legs": 0,
                  "is_tsl": False, "tsl_step_size": "0e0", "market_protection": False}, id="canonical-inactive"),
])
@pytest.mark.parametrize("path", PATHS, ids=["ordinary", "named"])
def test_absent_null_and_canonical_inactive_controls_keep_exact_ordinary_wire(delta_stack, fields, path):
    response = _request(delta_stack, fields, path)
    assert response.status_code == 200, response.get_json()
    assert response.get_json() == {"status": "success", "orderid": "41", "data": "41"}
    assert delta_stack.wire == [WIRE]
    assert len(delta_stack.minted) == 1 and delta_stack.consumed == [True] and len(delta_stack.invoked) == 1
    assert len(delta_stack.mapped) == 2, "The same pure builder must run in preflight and the guarded adapter"
    assert delta_stack.mapped[0] == delta_stack.mapped[1]
    assert len(delta_stack.checked) == 1 and len(delta_stack.checked[0]) == 5
    assert all(row["passed"] for row in delta_stack.checked[0])
    assert "margin_calculator" in delta_stack.reads
    order, context, gate = delta_stack.minted[0]
    with pytest.raises(SafetyBypassError, match="already consumed"):
        asyncio.run(delta_stack.router.place_order(context, order=order, safety_ctx=gate,
                    hint=RoutingHint(adapter_id="deltaexchange", account_id="route-account")))
    assert delta_stack.consumed == [True, False] and delta_stack.wire == [WIRE]
    assert len(delta_stack.invoked) == 1


@pytest.mark.parametrize("fields", [
    pytest.param({"trailing_jump": "5"}, id="regular-trailing"),
    pytest.param({"target_price": "110"}, id="regular-target"),
    pytest.param({"variety": "iceberg"}, id="iceberg"),
    pytest.param({"variety": "super"}, id="super"),
    pytest.param({"variety": "cover"}, id="cover"),
    pytest.param({"variety": "amo"}, id="amo"),
    pytest.param({"variety": "bracket"}, id="bracket-missing-protection"),
    pytest.param({"price": "0"}, id="limit-missing-price"),
    pytest.param({"price": "NaN"}, id="limit-nan"),
    pytest.param({"price": True}, id="limit-boolean"),
    pytest.param({"pricetype": "SL"}, id="stop-limit-missing-stop"),
    pytest.param({"pricetype": "SL-M"}, id="stop-market-missing-stop"),
    pytest.param({"trigger_price": "90", "stop_loss_price": "91"}, id="conflicting-stop-aliases"),
    pytest.param({"validity": "invalid"}, id="invalid-time-in-force"),
    pytest.param({"quantity": "0"}, id="zero-size"),
    pytest.param({"quantity": "2.5"}, id="fractional-size"),
    pytest.param({"trailing_jump": None}, id="null-canonical-trailing"),
    pytest.param({"trailing_jump": True}, id="boolean-canonical-trailing"),
    pytest.param({"target_price": "Infinity"}, id="nonfinite-target"),
])
@pytest.mark.parametrize("path", PATHS, ids=["ordinary", "named"])
def test_existing_placement_validation_is_pure_and_precedes_all_admission(delta_stack, fields, path):
    response = _request(delta_stack, fields, path)
    assert response.status_code == 400, response.get_json()
    _no_admission(delta_stack)
    assert len(delta_stack.mapped) <= 1


ORIGINAL_INTENTS = [
    pytest.param({"post_only": True}, id="post-only"),
    pytest.param({"trailing_jump": "5"}, id="trailing-jump"),
    pytest.param({"native": {"reduce_only": True}}, id="native-reduce-only"),
]


@pytest.mark.parametrize("fields", ORIGINAL_INTENTS)
@pytest.mark.parametrize("path", PATHS, ids=["ordinary", "named"])
def test_original_crypto_inputs_now_refuse_at_preflight_without_exchange_unfreeze(delta_stack, fields, path):
    response = _request(delta_stack, {"exchange": "CRYPTO", **fields}, path)
    assert response.status_code == 400, response.get_json()
    _no_admission(delta_stack)


@pytest.mark.parametrize("fields", [*ORIGINAL_INTENTS, pytest.param({}, id="ordinary-positive")])
def test_configured_default_uses_resolved_delta_id_before_field_selection(delta_stack, fields):
    response = _request(delta_stack, fields, configured_default=True)
    assert response.status_code == (400 if fields else 200), response.get_json()
    if fields:
        _no_admission(delta_stack)
    else:
        assert delta_stack.wire == [WIRE] and delta_stack.consumed == [True]


@pytest.mark.parametrize("fields", ORIGINAL_INTENTS)
def test_named_target_not_untrusted_body_broker_controls_raw_preflight(delta_stack, fields):
    response = _request(delta_stack, {"broker": "dhan", **fields}, PATHS[1])
    assert response.status_code == 400, response.get_json()
    _no_admission(delta_stack)


@pytest.mark.parametrize("path", PATHS, ids=["ordinary", "named"])
def test_ordinary_crypto_stays_frozen_by_real_l1_before_mint_or_consume(delta_stack, path):
    response = _request(delta_stack, {"exchange": "CRYPTO"}, path)
    assert response.status_code == 403, response.get_json()
    assert response.get_json() == {
        "status": "error", "message": "Order blocked by safety system [L1_ORDER]: Exchange CRYPTO is not tradeable",
    }
    assert delta_stack.minted == [] and delta_stack.consumed == [] and delta_stack.invoked == []
    assert delta_stack.wire == [] and delta_stack.l1_projections == []
    assert len(delta_stack.mapped) == 1, "Pure validation neither dispatches nor grants exchange authority"


def _diagnostic_crypto_membership(stack, monkeypatch):
    """Explicit instance-only L1 diagnostic, not production/native eligibility."""
    original = stack.safety.l1_order.validate
    def validate(order, ltp=None, at=None):
        if order.symbol == "BTCUSD" and order.exchange is Exchange.CRYPTO:
            result = original(order.model_copy(update={"exchange": Exchange.NSE}), ltp, at=at)
            stack.l1_projections.append({"synthetic_only": True, "passed": result.passed, "reason": result.reason})
            return result
        return original(order, ltp, at=at)
    monkeypatch.setattr(stack.safety.l1_order, "validate", validate)


@pytest.mark.parametrize("path", PATHS, ids=["ordinary", "named"])
def test_labelled_crypto_membership_diagnostic_keeps_real_signed_order_and_one_shot(delta_stack, monkeypatch, path):
    _diagnostic_crypto_membership(delta_stack, monkeypatch)
    response = _request(delta_stack, {"exchange": "CRYPTO"}, path)
    assert response.status_code == 200, response.get_json()
    assert delta_stack.wire == [WIRE] and delta_stack.consumed == [True]
    assert len(delta_stack.l1_projections) == 1 and delta_stack.l1_projections[0]["passed"]
    assert all(row["passed"] for row in delta_stack.checked[0]) and len(delta_stack.checked[0]) == 5
    order, context, gate = delta_stack.minted[0]
    assert order.exchange is Exchange.CRYPTO and delta_stack.invoked[0]["exchange"] == "CRYPTO"
    with pytest.raises(SafetyBypassError, match="already consumed"):
        asyncio.run(delta_stack.router.place_order(context, order=order, safety_ctx=gate,
                    hint=RoutingHint(adapter_id="deltaexchange", account_id="route-account")))
    assert delta_stack.consumed == [True, False] and delta_stack.wire == [WIRE]


@pytest.mark.parametrize("fields", ORIGINAL_INTENTS)
@pytest.mark.parametrize("path", PATHS, ids=["ordinary", "named"])
def test_labelled_crypto_diagnostic_intent_refusal_is_still_pre_admission(delta_stack, monkeypatch, fields, path):
    _diagnostic_crypto_membership(delta_stack, monkeypatch)
    response = _request(delta_stack, {"exchange": "CRYPTO", **fields}, path)
    assert response.status_code == 400, response.get_json()
    _no_admission(delta_stack)
    assert delta_stack.l1_projections == []


def test_labelled_membership_diagnostic_preserves_real_l1_price_refusal(delta_stack, monkeypatch):
    _diagnostic_crypto_membership(delta_stack, monkeypatch)
    response = _request(delta_stack, {"exchange": "CRYPTO", "price": "160"})
    assert response.status_code == 403 and "[L1_ORDER]" in response.get_json()["message"]
    assert len(delta_stack.l1_projections) == 1 and not delta_stack.l1_projections[0]["passed"]
    assert delta_stack.minted == [] and delta_stack.consumed == [] and delta_stack.wire == []


def test_direct_adapter_token_refusal_stays_ahead_of_mapping_and_transport(delta_stack):
    order = Order(symbol="BTCUSD", exchange=Exchange.NSE, action="SELL", quantity="2", pricetype="LIMIT", price="100")
    with pytest.raises(SafetyBypassError):
        asyncio.run(delta_stack.direct_place(delta_stack.session, order))
    assert delta_stack.mapped == [] and delta_stack.wire == [] and delta_stack.consumed == []


def test_read_only_session_stays_refused_by_router_before_consume_or_adapter(delta_stack):
    delta_stack.session.read_only_until_at = 4102444800.0
    response = _request(delta_stack, {})
    assert response.status_code == 403, response.get_json()
    assert response.get_json()["dispatch_outcome"] == "refused_before_dispatch"
    assert len(delta_stack.minted) == 1 and delta_stack.consumed == []
    assert delta_stack.invoked == [] and delta_stack.wire == []


def test_possible_delta_transport_invocation_stays_unknown_with_held_capacity(delta_stack):
    from flinttrade_engine.reduce_only import contract_key, reserved_exit

    original = delta_stack.session.extra["transport"]
    def accepted_then_timeout(*args):
        original(*args)
        raise TimeoutError("synthetic timeout after accepting the inert request")
    delta_stack.session.extra["transport"] = accepted_then_timeout
    first = _request(delta_stack, {})
    assert first.status_code == 500, first.get_json()
    assert first.get_json()["dispatch_outcome"] == "unknown_after_dispatch"
    assert first.get_json()["retry_safe"] is False
    key = contract_key(mode="live", adapter="deltaexchange", account="route-account",
                       symbol="BTCUSD", exchange="NSE", product="MIS")
    assert reserved_exit(key) == 2
    with delta_stack.safety.order_admission("deltaexchange:route-account") as lease:
        assert len(lease.reservations) == 1 and lease.reservations[0].broker_order_id == ""
    second = _request(delta_stack, {})
    assert second.status_code == 409, second.get_json()
    assert delta_stack.wire == [WIRE] and delta_stack.consumed == [True]
