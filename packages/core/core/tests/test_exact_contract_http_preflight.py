"""Exact-contract HTTP preflight with synthetic masters and inert SDK transport.

The normal factory, safety layers, one-shot gate and router remain real. These
fixtures prove ordering and refusal, not production eligibility or signed
contract-revision qualification. No master is fetched and no session logs in.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
from copy import deepcopy
from datetime import datetime, timezone
import json
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest

from flinttrade_core.auth_routes import _create_token
from flinttrade_core.exceptions import SafetyBypassError, UnsupportedCapabilityError
from flinttrade_engine.safety import SafetyGate
from flinttrade_gateway.brokers import dhan_mapping
from flinttrade_gateway.brokers._base import Session
from flinttrade_gateway.brokers.dhan import DhanAdapter
from flinttrade_gateway.brokers.kotakneo import KotakNeoAdapter
from flinttrade_gateway.brokers.kotakneo_contracts import KotakContractResolver
from flinttrade_gateway.brokers.kotakneo_sdk import KotakNeoSdkSession, _sdk_class
from flinttrade_gateway.router import BrokerRouter
from flinttrade_gateway.routing_config import RoutingConfig, RoutingHint
from packages.core.core.tests.test_ingress_safety_runtime import exact_egress_latch as exact_egress_latch
from packages.core.core.tests.test_order_route_evidence_runtime import route_stack as route_stack

pytestmark = pytest.mark.integration
ACCOUNT = "route-account"


def _resolver(broker, exchange, *, stale=False, expired=False, ambiguous=False):
    """Literal synthetic rows following each source-backed native master schema."""
    underlying = "NIFTY" if exchange == "NFO" else "SENSEX"
    symbol = underlying + "-JUN2099-22250-CE"
    if broker == "dhan":
        row = dict(EXCH_ID="NSE" if exchange == "NFO" else "BSE", SEGMENT="D",
            SECURITY_ID="synthetic-contract", INSTRUMENT="OPTIDX", TRADING_SYMBOL=symbol,
            UNDERLYING_SYMBOL=underlying, SYMBOL_NAME=underlying,
            SM_EXPIRY_DATE="2000-01-01" if expired else "2099-06-23",
            STRIKE_PRICE="22250", OPTION_TYPE="CE", LOT_SIZE="3", TICK_SIZE="5")
        rule = dict(tick_size="0.05", source_kind="exchange_rule", source_revision="synthetic-rule",
            source_url="https://example.invalid/synthetic-rule", contract_source_revision="synthetic-master",
            observed_at=100.0, valid_until=200.0)
        rows = [row, row | {"SECURITY_ID": "other-synthetic-contract"}] if ambiguous else [row]
        resolver = dhan_mapping.build_security_resolver(rows, source_revision="synthetic-master",
            observed_at=100.0, valid_until=200.0, clock=lambda: 201.0 if stale else 150.0,
            tick_rules={("synthetic-contract", exchange): rule})
    else:
        epoch = int(datetime(2000 if expired else 2099, 6, 23, 10, tzinfo=timezone.utc).timestamp())
        if exchange == "NFO":
            epoch -= 315511200  # Documented NSE master epoch offset, not expiry inference.
        row = dict(pSymbol="71472", pTrdSymbol=symbol, pExchSeg="nse_fo" if exchange == "NFO" else "bse_fo",
            pSymbolName=underlying, pOptionType="CE", pInstType="OPTIDX" if exchange == "NFO" else "IO",
            lExpiryDate=str(epoch), pExpiryDate=str(epoch), lLotSize="3", dTickSize="5", lPrecision="2")
        row["dStrikePrice;"] = "2225000"
        rows = [row, row | {"pSymbol": "71473"}] if ambiguous else [row]
        resolver = KotakContractResolver.from_records(rows, source="https://example.invalid/synthetic-master.csv",
            revision="synthetic-master", observed_at=datetime(1999, 1, 1, tzinfo=timezone.utc),
            valid_until=datetime(2000 if stale else 2099, 1, 1, tzinfo=timezone.utc))
    return resolver, symbol


@pytest.fixture
def exact_stack(
    route_stack: tuple[Any, Any, Any, BrokerRouter], monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Callable[..., SimpleNamespace]]:
    """Inject external reads/transport and explicitly synthetic account lookup.

    Args:
        route_stack: Existing normal-factory app, external read stub, SDK and router.
        monkeypatch: Scoped observers restored after the yielded fixture builder.

    Yields:
        Builder accepting broker, exchange and evidence condition. Its namespace
        exposes the real gate/router/adapters and detached phase/wire observations.
        The synthetic registry lookup is not production account qualification.

    Raises:
        AssertionError: If an inert transport receives an unexpected native request.
    """
    import flinttrade_engine.safety as safety_module

    app, source, _old_sdk, old_router = route_stack
    owned = []

    def build(broker="dhan", exchange="NFO", *, evidence="fresh"):
        stack = SimpleNamespace(app=app, source=source, safety=app.config["SAFETY"], broker=broker,
            events=[], reads=[], minted=[], consumed=[], invoked=[], wire=[], preflights=[], results=[], outcome="ack")
        resolver, symbol = _resolver(broker, exchange, stale=evidence == "stale", expired=evidence == "expired",
            ambiguous=evidence == "ambiguous")
        stack.symbol = symbol
        stack.body = dict(symbol=symbol, exchange=exchange, product="NRML", action="SELL",
            quantity="3", price="100", pricetype="LIMIT")
        if evidence == "missing":
            resolver = None
        if broker == "dhan":
            from dhanhq import DhanContext, dhanhq
            sdk = dhanhq(DhanContext(ACCOUNT, "synthetic"))

            def send(method, url, **kwargs):
                assert (method, url) == ("POST", "https://api.dhan.co/v2/orders")
                stack.wire.append(json.loads(kwargs["data"]))
                stack.events.append("wire")
                if stack.outcome == "unsupported":
                    raise UnsupportedCapabilityError("Synthetic failure after SDK invocation", broker_id=broker)
                return SimpleNamespace(status_code=200, content=b'{"orderId":"synthetic-ack"}')
            monkeypatch.setattr(sdk.dhan_http.session, "request", send)
            adapter = DhanAdapter(client_factory=lambda _: sdk, security_resolver=resolver)
            close = sdk.dhan_http.session.close
        else:
            def send(request):
                assert (request.method, request.url.host, request.url.path) == (
                    "POST", "example.invalid", "/quick/order/rule/ms/place")
                stack.wire.append(json.loads(parse_qs(request.content.decode())["jData"][0]))
                stack.events.append("wire")
                if stack.outcome == "unsupported":
                    raise UnsupportedCapabilityError("Synthetic failure after SDK invocation", broker_id=broker)
                return httpx.Response(200, json={"stat": "Ok", "stCode": 200, "nOrdNo": "synthetic-ack"})
            neo = _sdk_class()(consumer_key="synthetic", transport=httpx.MockTransport(send))
            neo.configuration.edit_token = "synthetic"
            neo.configuration.edit_sid = "synthetic"
            neo.configuration.base_url = "https://example.invalid"
            sdk = KotakNeoSdkSession.__new__(KotakNeoSdkSession)
            sdk._neo, sdk._closed = neo, False
            adapter = KotakNeoAdapter(client_factory=lambda _: sdk, contract_resolver=resolver,
                symbol_resolver=lambda symbol, _exchange: symbol)
            close = sdk.close
        session = Session("synthetic", 4102444800.0, ACCOUNT, broker)
        session.extra["client"] = sdk
        stack.adapter, stack.session, stack.resolver = adapter, session, resolver
        gate = SafetyGate()

        def session_for(context, broker_id, account):
            if (broker_id, account) != (broker, ACCOUNT) or context is not None and context.actor_id != "operator":
                raise SafetyBypassError("Synthetic account ACL denies this exact target")
            return session

        def consume(identifier):
            result = gate.consume(identifier)
            stack.consumed.append(result)
            stack.events.append("consume")
            return result

        config = RoutingConfig.from_workspace({"registered": [f"{broker}:{ACCOUNT}"],
            "execution": {"default": f"{broker}:{ACCOUNT}"},
            "data": {name: f"{broker}:{ACCOUNT}" for name in ("ticks", "historical", "option_chains", "quote")},
            "account_acls": {broker: {ACCOUNT: ["operator"]}}})
        router = BrokerRouter({broker: adapter}, session_for, consume_gate=consume, config=config,
            backend_lease_proof=old_router.backend_lease_proof)
        owned.append((router, close))
        stack.router = router
        app.config["BROKER_ROUTER"] = router
        app.config["NATIVE_ADAPTERS"] = {broker: source}
        app.config["REGISTRY"] = SimpleNamespace(get_session_for=lambda b, a: session_for(None, b, a))
        source.position_rows = [dict(symbol=symbol, exchange=exchange, product="NRML", quantity="3", net_qty=3,
            multiplier=1, cross_currency=False, delta=0.5, vega=0.1)]
        source.order_rows = []
        for name in ("positions", "order_book", "funds", "trade_book", "holdings", "quotes", "margin_calculator"):
            original = getattr(source, name)
            async def read(*args, _name=name, _original=original, **kwargs):
                stack.reads.append(_name)
                stack.events.append("read:" + _name)
                return await _original(*args, **kwargs)
            monkeypatch.setattr(source, name, read)
        async def portfolio_greeks(_session, positions):
            # Synthetic external observations, not a replacement for L3 or its
            # exact identity/coverage checks.
            stack.reads.append("portfolio_greeks")
            stack.events.append("read:portfolio_greeks")
            return [dict(symbol=p["symbol"], exchange=p["exchange"],
                instrument_id="synthetic-contract" if broker == "dhan" else "71472", delta=0.5, vega=0.1)
                for p in positions]
        monkeypatch.setattr(source, "portfolio_greeks", portfolio_greeks, raising=False)
        original_check = stack.safety.check_order
        stack.checked = []
        def check(order, **kwargs):
            result = original_check(order, **kwargs)
            stack.checked.append([dict(layer=r.layer, passed=r.passed, reason=r.reason) for r in result])
            return result
        monkeypatch.setattr(stack.safety, "check_order", check)
        original_mint = safety_module.gate_order
        def mint(*args, **kwargs):
            result = original_mint(*args, **kwargs)
            stack.minted.append((args[0], args[1], result))
            stack.events.append("mint")
            return result
        monkeypatch.setattr(safety_module, "gate_order", mint)
        original_preflight = adapter.preflight_order
        def preflight(order, **kwargs):
            stack.preflights.append(order.model_dump(mode="json"))
            stack.events.append("preflight")
            result = original_preflight(order, **kwargs)
            stack.results.append(deepcopy(result))
            return result
        monkeypatch.setattr(adapter, "preflight_order", preflight)
        original_place = adapter.place_order
        async def place(*args, **kwargs):
            stack.invoked.append(args[1].model_dump(mode="json"))
            stack.events.append("invoke")
            return await original_place(*args, **kwargs)
        monkeypatch.setattr(adapter, "place_order", place)
        return stack

    yield build
    for router, close in reversed(owned):
        router.revoke_and_drain(timeout=0)
        close()


def _snapshot(stack) -> dict[str, Any]:
    from flinttrade_engine.laya import process_laya
    from flinttrade_engine.reduce_only import contract_key, reserved_exit
    key = contract_key(mode="live", adapter=stack.broker, account=ACCOUNT, symbol=stack.body["symbol"],
        exchange=stack.body["exchange"], product=stack.body["product"])
    with stack.safety.order_admission(f"{stack.broker}:{ACCOUNT}") as lease:
        holds = [dict(quantity=r.order.quantity, broker_order_id=r.broker_order_id) for r in lease.reservations]
    return deepcopy(dict(events=stack.events, reads=stack.reads, minted=len(stack.minted), consumed=stack.consumed,
        invoked=stack.invoked, wire=stack.wire, preflights=stack.preflights,
        results=stack.results, checked=stack.checked,
        reducing=reserved_exit(key), exposure=holds, proofs=len(process_laya().decision_log())))


def _post(stack, changes=None, *, named=False, headers=None) -> tuple[Any, dict[str, Any]]:
    body = stack.body | (changes or {})
    path = f"/api/v1/orders/{stack.broker}/place" if named else "/api/v1/orders/place"
    if named:
        body.setdefault("account_id", ACCOUNT)
    if headers is None:
        headers = {"Authorization": "Bearer " + _create_token("operator", mode="live", live_mode_unlocked=True)}
    response = stack.app.test_client().post(path, json=body, headers=headers)
    captured: dict[str, Any] = dict(path=path, request=body, status=response.status_code,
        raw_body=response.get_data(as_text=True),
        phase=_snapshot(stack))
    print("EXACT_PREFLIGHT_HTTP " + json.dumps(captured, sort_keys=True), flush=True)
    return response, captured["phase"]


def _no_admission(phase):
    assert phase["reads"] == []
    assert phase["minted"] == 0 and phase["consumed"] == []
    assert phase["invoked"] == [] and phase["wire"] == []
    assert phase["reducing"] == 0 and phase["exposure"] == [] and phase["proofs"] == 0


def test_missing_dhan_exact_resolver_refuses_before_any_admission(
    exact_stack: Callable[..., SimpleNamespace],
) -> None:
    """Refuse missing Dhan contract evidence before provider or authority work.

    Args:
        exact_stack: Normal-factory fixture builder with inert SDK transports.

    Returns:
        None; assertions inspect the actual HTTP and detached phase observations.

    Raises:
        AssertionError: If the refusal, authority, custody or wire contract differs.
    """
    stack = exact_stack(evidence="missing")
    response, phase = _post(stack)
    _no_admission(phase)
    assert len(phase["preflights"]) == 1
    assert response.status_code == 400, response.get_json()


@pytest.mark.parametrize("field", ["target_price", "stop_loss_price", "trailing_jump"])
def test_dhan_unrepresented_protection_still_refuses_before_resolver(
    exact_stack: Callable[..., SimpleNamespace], field: str,
) -> None:
    """Preserve raw Dhan protection refusal before even consulting the resolver.

    Args:
        exact_stack: Normal-factory fixture builder with inert SDK transports.
        field: Raw request field whose presence is challenged.

    Returns:
        None; assertions inspect the actual HTTP and detached phase observations.

    Raises:
        AssertionError: If the refusal, authority, custody or wire contract differs.
    """
    stack = exact_stack("dhan")
    response, phase = _post(stack, {field: "5"})
    _no_admission(phase)
    assert phase["preflights"] == []
    assert response.status_code == 400, response.get_json()


def test_missing_kotak_exact_resolver_refuses_before_any_admission(
    exact_stack: Callable[..., SimpleNamespace],
) -> None:
    """Refuse missing Kotak listing evidence without selecting a fallback.

    Args:
        exact_stack: Normal-factory fixture builder with inert SDK transports.

    Returns:
        None; assertions inspect the actual HTTP and detached phase observations.

    Raises:
        AssertionError: If the refusal, authority, custody or wire contract differs.
    """
    stack = exact_stack("kotakneo", evidence="missing")
    response, phase = _post(stack, named=True)
    _no_admission(phase)
    assert len(phase["preflights"]) == 1
    assert response.status_code == 501, response.get_json()


@pytest.mark.parametrize("broker", ["dhan", "kotakneo"])
@pytest.mark.parametrize("field", [
    "instrument_id", "instrument_token", "security_id", "securityId", "pSymbol",
    "broker_account_id", "dhanClientId", "exchangeSegment", "exchange_segment", "pExchSeg",
    "trading_symbol", "tradingSymbol", "pTrdSymbol", "source_revision",
])
def test_native_identity_override_cannot_disappear_before_preflight(
    exact_stack: Callable[..., SimpleNamespace], broker: str, field: str,
) -> None:
    """Reject unrepresented native identity before canonical field selection.

    Args:
        exact_stack: Normal-factory fixture builder with inert SDK transports.
        broker: Exact broker selected by the configured or named route.
        field: Raw request field whose presence is challenged.

    Returns:
        None; assertions inspect the actual HTTP and detached phase observations.

    Raises:
        AssertionError: If the refusal, authority, custody or wire contract differs.
    """
    stack = exact_stack(broker)
    response, phase = _post(stack, {field: "different-exact-identity"}, named=True)
    _no_admission(phase)
    assert phase["preflights"] == []
    assert response.status_code == 400, response.get_json()


@pytest.mark.parametrize("broker", ["dhan", "kotakneo"])
@pytest.mark.parametrize("exchange", ["NFO", "BFO"])
@pytest.mark.parametrize("named", [False, True], ids=["default", "named"])
def test_non_lot_refusal_precedes_positive_followup_and_one_shot_replay(
    exact_stack: Callable[..., SimpleNamespace], broker: str, exchange: str, named: bool,
) -> None:
    """Retain lot refusal, a genuine one-shot positive and exact replay denial.

    Args:
        exact_stack: Normal-factory fixture builder with inert SDK transports.
        broker: Exact broker selected by the configured or named route.
        exchange: Canonical venue bound to the synthetic listed contract.
        named: Whether the request selects the named rather than configured target.

    Returns:
        None; assertions inspect the actual HTTP and detached phase observations.

    Raises:
        AssertionError: If the refusal, authority, custody or wire contract differs.
    """
    stack = exact_stack(broker, exchange)
    refused, refused_phase = _post(stack, {"quantity": "2"}, named=named)
    _no_admission(refused_phase)  # Measure BEFORE the legitimate later mint/consume.
    assert len(refused_phase["preflights"]) == 1
    assert refused.status_code == (400 if broker == "dhan" else 501)
    response, phase = _post(stack, named=named)
    assert response.status_code == 200, response.get_json()
    assert response.get_json() == {"status": "success", "orderid": "synthetic-ack", "data": "synthetic-ack"}
    assert phase["events"][0] == "preflight"
    assert phase["minted"] == 1 and phase["consumed"] == [True]
    assert len(phase["invoked"]) == len(phase["wire"]) == 1
    assert len(phase["checked"]) == 1 and len(phase["checked"][0]) == 5
    assert all(r["passed"] for r in phase["checked"][0])
    wire = phase["wire"][0]
    if broker == "dhan":
        assert wire["securityId"] == "synthetic-contract" and wire["quantity"] == 3
        assert wire["exchangeSegment"] == ("NSE_FNO" if exchange == "NFO" else "BSE_FNO")
    else:
        assert wire["ts"] == stack.symbol and wire["qt"] == "3"
        assert wire["es"] == ("nse_fo" if exchange == "NFO" else "bse_fo")
        assert phase["results"][0]["source_revision"] == "synthetic-master"
    order, context, gate = stack.minted[0]
    with pytest.raises(SafetyBypassError, match="already consumed"):
        asyncio.run(stack.router.place_order(context, order=order, safety_ctx=gate,
            hint=RoutingHint(adapter_id=broker, account_id=ACCOUNT)))
    replay = _snapshot(stack)
    assert replay["consumed"] == [True, False]
    assert replay["invoked"] == phase["invoked"] and replay["wire"] == phase["wire"]
    _no_admission(refused_phase)  # The detached earlier observation did not change.
    print("EXACT_PREFLIGHT_REPLAY " + json.dumps(replay, sort_keys=True), flush=True)


@pytest.mark.parametrize("broker", ["dhan", "kotakneo"])
@pytest.mark.parametrize("exchange", ["NFO", "BFO"])
@pytest.mark.parametrize("named", [False, True], ids=["default", "named"])
@pytest.mark.parametrize("evidence", ["missing", "stale", "expired"])
def test_unavailable_contract_refuses_before_books_and_authority(
    exact_stack: Callable[..., SimpleNamespace], broker: str, exchange: str, named: bool, evidence: str,
) -> None:
    """Keep unavailable or stale contract evidence outside admission.

    Args:
        exact_stack: Normal-factory fixture builder with inert SDK transports.
        broker: Exact broker selected by the configured or named route.
        exchange: Canonical venue bound to the synthetic listed contract.
        named: Whether the request selects the named rather than configured target.
        evidence: Synthetic missing, stale or expired contract condition.

    Returns:
        None; assertions inspect the actual HTTP and detached phase observations.

    Raises:
        AssertionError: If the refusal, authority, custody or wire contract differs.
    """
    stack = exact_stack(broker, exchange, evidence=evidence)
    response, phase = _post(stack, named=named)
    _no_admission(phase)
    assert len(phase["preflights"]) == 1
    assert response.status_code == (400 if broker == "dhan" else 501), response.get_json()


@pytest.mark.parametrize("broker", ["dhan", "kotakneo"])
@pytest.mark.parametrize("exchange", ["NFO", "BFO"])
@pytest.mark.parametrize("changes", [
    pytest.param({"product": "CNC"}, id="cash-product"),
    pytest.param({"product": "MTF"}, id="unqualified-mtf"),
    pytest.param({"pricetype": "SL-M", "trigger_price": "100"}, id="unsupported-stop-market"),
    pytest.param({"price": "0"}, id="zero-limit"),
    pytest.param({"price": "-1"}, id="negative-limit"),
    pytest.param({"price": "NaN"}, id="nonfinite-limit"),
    pytest.param({"price": "100.01"}, id="wrong-tick"),
    pytest.param({"pricetype": "SL", "trigger_price": "0"}, id="missing-stop-trigger"),
    pytest.param({"pricetype": "SL", "trigger_price": "99.95"}, id="wrong-side-trigger"),
    pytest.param({"quantity": "0"}, id="zero-units"),
])
def test_actual_adapter_terms_refuse_before_admission(
    exact_stack: Callable[..., SimpleNamespace], broker: str, exchange: str, changes: dict[str, Any],
) -> None:
    """Use the real adapter to reject incompatible contract terms before reads.

    Args:
        exact_stack: Normal-factory fixture builder with inert SDK transports.
        broker: Exact broker selected by the configured or named route.
        exchange: Canonical venue bound to the synthetic listed contract.
        changes: Literal request changes submitted without canonical pre-coercion.

    Returns:
        None; assertions inspect the actual HTTP and detached phase observations.

    Raises:
        AssertionError: If the refusal, authority, custody or wire contract differs.
    """
    stack = exact_stack(broker, exchange)
    response, phase = _post(stack, changes, named=True)
    _no_admission(phase)
    assert len(phase["preflights"]) == 1
    assert response.status_code == (400 if broker == "dhan" else 501), response.get_json()


@pytest.mark.parametrize("broker", ["dhan", "kotakneo"])
@pytest.mark.parametrize("changes", [
    {"quantity": "1.5"}, {"quantity": -3}, {"quantity": True},
    {"pricetype": "LIMIT", "order_type": "MARKET"}, {"trailingJump": 1},
    {"market_protection": 1}, {"isTSL": True},
])
def test_original_raw_intent_guards_run_before_preflight(
    exact_stack: Callable[..., SimpleNamespace], broker: str, changes: dict[str, Any],
) -> None:
    """Preserve established raw intent refusal before contract preflight.

    Args:
        exact_stack: Normal-factory fixture builder with inert SDK transports.
        broker: Exact broker selected by the configured or named route.
        changes: Literal request changes submitted without canonical pre-coercion.

    Returns:
        None; assertions inspect the actual HTTP and detached phase observations.

    Raises:
        AssertionError: If the refusal, authority, custody or wire contract differs.
    """
    stack = exact_stack(broker)
    response, phase = _post(stack, changes, named=True)
    _no_admission(phase)
    assert phase["preflights"] == []
    assert response.status_code == 400, response.get_json()


@pytest.mark.parametrize("broker", ["dhan", "kotakneo"])
@pytest.mark.parametrize("named", [False, True], ids=["default", "named"])
def test_real_sdk_exception_keeps_unknown_outcome_and_both_holds(
    exact_stack: Callable[..., SimpleNamespace], broker: str, named: bool,
) -> None:
    """Retain possible-write uncertainty and both holds after SDK failure.

    Args:
        exact_stack: Normal-factory fixture builder with inert SDK transports.
        broker: Exact broker selected by the configured or named route.
        named: Whether the request selects the named rather than configured target.

    Returns:
        None; assertions inspect the actual HTTP and detached phase observations.

    Raises:
        AssertionError: If the refusal, authority, custody or wire contract differs.
    """
    stack = exact_stack(broker)
    stack.outcome = "unsupported"
    response, phase = _post(stack, named=named)
    assert response.status_code == 500, response.get_json()
    assert response.get_json()["dispatch_outcome"] == "unknown_after_dispatch"
    assert response.get_json()["retry_safe"] is False
    assert phase["minted"] == 1 and phase["consumed"] == [True]
    assert len(phase["wire"]) == len(phase["invoked"]) == 1
    assert phase["reducing"] == 3 and phase["exposure"] == [{"quantity": "3", "broker_order_id": ""}]
    retry, after = _post(stack, named=named)
    assert retry.status_code == 409, retry.get_json()
    assert after["wire"] == phase["wire"] and after["invoked"] == phase["invoked"]
    assert after["minted"] == 1 and after["consumed"] == [True]


@pytest.mark.parametrize("broker", ["dhan", "kotakneo"])
@pytest.mark.parametrize("case,status", [("no-auth", 401), ("explore", 400), ("locked", 403), ("not-ready", 503)])
def test_auth_mode_and_safety_readiness_never_reach_preflight(
    exact_stack: Callable[..., SimpleNamespace], broker: str, case: str, status: int,
) -> None:
    """Keep authentication, unlock and readiness guards ahead of preflight.

    Args:
        exact_stack: Normal-factory fixture builder with inert SDK transports.
        broker: Exact broker selected by the configured or named route.
        case: Authentication, mode, unlock or readiness condition.
        status: Expected unchanged HTTP refusal status for that condition.

    Returns:
        None; assertions inspect the actual HTTP and detached phase observations.

    Raises:
        AssertionError: If the refusal, authority, custody or wire contract differs.
    """
    stack = exact_stack(broker)
    headers = {}
    if case != "no-auth":
        headers = {"Authorization": "Bearer " + _create_token("operator",
            mode="explore" if case == "explore" else "live", live_mode_unlocked=case != "locked")}
    if case == "not-ready":
        stack.app.config["SAFETY_CONFIG_READY"] = False
    response, phase = _post(stack, named=True, headers=headers)
    assert response.status_code == status, response.get_json()
    _no_admission(phase)
    assert phase["preflights"] == []


@pytest.mark.parametrize("broker", ["dhan", "kotakneo"])
def test_named_target_ignores_body_broker_and_never_falls_back(
    exact_stack: Callable[..., SimpleNamespace], broker: str,
) -> None:
    """Resolve the named target independently of an untrusted body selector.

    Args:
        exact_stack: Normal-factory fixture builder with inert SDK transports.
        broker: Exact broker selected by the configured or named route.

    Returns:
        None; assertions inspect the actual HTTP and detached phase observations.

    Raises:
        AssertionError: If the refusal, authority, custody or wire contract differs.
    """
    stack = exact_stack(broker, evidence="missing")
    response, phase = _post(stack, {"broker": "groww"}, named=True)
    assert response.status_code == (400 if broker == "dhan" else 501), response.get_json()
    assert len(phase["preflights"]) == 1
    _no_admission(phase)


@pytest.mark.parametrize("broker", ["dhan", "kotakneo"])
@pytest.mark.parametrize("fault", ["foreign-account", "foreign-actor", "read-only"])
def test_exact_preflight_does_not_replace_account_authority(
    exact_stack: Callable[..., SimpleNamespace], broker: str, fault: str,
) -> None:
    """Require account, operator and session authority after exact preflight.

    Args:
        exact_stack: Normal-factory fixture builder with inert SDK transports.
        broker: Exact broker selected by the configured or named route.
        fault: Exact account or target ownership fault to introduce.

    Returns:
        None; assertions inspect the actual HTTP and detached phase observations.

    Raises:
        AssertionError: If the refusal, authority, custody or wire contract differs.
    """
    stack = exact_stack(broker)
    headers = {"Authorization": "Bearer " + _create_token("foreign" if fault == "foreign-actor" else "operator",
        mode="live", live_mode_unlocked=True)}
    if fault == "read-only":
        stack.session.read_only_until_at = 4102444800.0
    response, phase = _post(stack, {"account_id": "another-account"} if fault == "foreign-account" else {},
        named=True, headers=headers)
    assert response.status_code in {403, 503}, response.get_json()
    assert phase["preflights"] and phase["wire"] == [] and phase["invoked"] == [] and phase["consumed"] == []
    assert phase["reducing"] == 0 and phase["exposure"] == []
    if fault == "foreign-account":
        assert phase["reads"] == [] and phase["minted"] == 0
    else:
        assert response.get_json()["dispatch_outcome"] == "refused_before_dispatch"
        assert phase["minted"] == 1


@pytest.mark.parametrize("broker", ["dhan", "kotakneo"])
@pytest.mark.parametrize("fault", ["missing-adapter", "wrong-adapter", "missing-hook"])
def test_router_preflight_refuses_missing_or_mismatched_target_without_fallback(
    exact_stack: Callable[..., SimpleNamespace], broker: str, fault: str,
) -> None:
    """Refuse unavailable or mismatched router targets without fallback.

    Args:
        exact_stack: Normal-factory fixture builder with inert SDK transports.
        broker: Exact broker selected by the configured or named route.
        fault: Exact account or target ownership fault to introduce.

    Returns:
        None; assertions inspect the actual HTTP and detached phase observations.

    Raises:
        AssertionError: If the refusal, authority, custody or wire contract differs.
    """
    stack = exact_stack(broker)
    if fault == "missing-adapter":
        stack.router._adapters.clear()
    elif fault == "wrong-adapter":
        stack.router._adapters[broker] = SimpleNamespace(
            broker_id="groww", preflight_order=stack.adapter.preflight_order)
    else:
        stack.router._adapters[broker] = SimpleNamespace(broker_id=broker)
    response, phase = _post(stack, named=True)
    assert response.status_code == (400 if broker == "dhan" else 501), response.get_json()
    _no_admission(phase)
    assert phase["preflights"] == []


def _ordinary_control(stack, kind):
    symbol, exchange, product = ("SYNTH-EQ", "NSE", "MIS") if kind == "cash" else (
        "SYNTH-JUN2099-FUT", "NFO", "NRML")
    stack.body.update(symbol=symbol, exchange=exchange, product=product)
    stack.source.position_rows[0].update(symbol=symbol, exchange=exchange, product=product)
    if stack.broker == "dhan":
        row = dict(EXCH_ID="NSE", SEGMENT="E" if kind == "cash" else "D", SECURITY_ID="synthetic-ordinary",
            TRADING_SYMBOL=symbol, INSTRUMENT="EQUITY" if kind == "cash" else "FUTIDX", LOT_SIZE="3", TICK_SIZE="5")
        if kind == "future":
            row.update(UNDERLYING_SYMBOL="SYNTH", SM_EXPIRY_DATE="2099-06-23")
        rule = dict(tick_size="0.05", source_kind="exchange_rule", source_revision="synthetic-rule",
            source_url="https://example.invalid/synthetic-rule", contract_source_revision="synthetic-ordinary",
            observed_at=100.0, valid_until=200.0)
        stack.adapter.install_security_resolver(dhan_mapping.build_security_resolver([row],
            source_revision="synthetic-ordinary", observed_at=100.0, valid_until=200.0, clock=lambda: 150.0,
            tick_rules={("synthetic-ordinary", exchange): rule}))


@pytest.mark.parametrize("broker", ["dhan", "kotakneo"])
@pytest.mark.parametrize("kind", ["cash", "future"])
@pytest.mark.parametrize("named", [False, True], ids=["default", "named"])
def test_supported_ordinary_cash_and_future_keep_real_safety_and_sdk(
    exact_stack: Callable[..., SimpleNamespace], broker: str, kind: str, named: bool,
) -> None:
    """Preserve existing cash and future execution through all safety layers.

    Args:
        exact_stack: Normal-factory fixture builder with inert SDK transports.
        broker: Exact broker selected by the configured or named route.
        kind: Ordinary cash or future positive control.
        named: Whether the request selects the named rather than configured target.

    Returns:
        None; assertions inspect the actual HTTP and detached phase observations.

    Raises:
        AssertionError: If the refusal, authority, custody or wire contract differs.
    """
    stack = exact_stack(broker)
    _ordinary_control(stack, kind)
    response, phase = _post(stack, named=named)
    assert response.status_code == 200, response.get_json()
    assert phase["events"][0] == "preflight"
    assert phase["minted"] == 1 and phase["consumed"] == [True]
    assert len(phase["wire"]) == len(phase["invoked"]) == 1
    assert len(phase["checked"][0]) == 5 and all(r["passed"] for r in phase["checked"][0])
    assert phase["wire"][0]["securityId" if broker == "dhan" else "ts"] == (
        "synthetic-ordinary" if broker == "dhan" else stack.body["symbol"])


@pytest.mark.parametrize("broker", ["dhan", "kotakneo"])
@pytest.mark.parametrize("exchange", ["NFO", "BFO"])
def test_same_symbol_cannot_borrow_other_venue_snapshot(
    exact_stack: Callable[..., SimpleNamespace], broker: str, exchange: str,
) -> None:
    """Keep identical symbols bound to their exact contract venue.

    Args:
        exact_stack: Normal-factory fixture builder with inert SDK transports.
        broker: Exact broker selected by the configured or named route.
        exchange: Canonical venue bound to the synthetic listed contract.

    Returns:
        None; assertions inspect the actual HTTP and detached phase observations.

    Raises:
        AssertionError: If the refusal, authority, custody or wire contract differs.
    """
    stack = exact_stack(broker, exchange)
    response, phase = _post(stack, {"exchange": "BFO" if exchange == "NFO" else "NFO"}, named=True)
    assert response.status_code == (400 if broker == "dhan" else 501), response.get_json()
    _no_admission(phase)
    assert len(phase["preflights"]) == 1


@pytest.mark.parametrize("exchange", ["NFO", "BFO"])
def test_dhan_ambiguous_symbol_snapshot_is_not_first_match_authority(
    exact_stack: Callable[..., SimpleNamespace], exchange: str,
) -> None:
    """Reject ambiguous Dhan contracts instead of selecting the first row.

    Args:
        exact_stack: Normal-factory fixture builder with inert SDK transports.
        exchange: Canonical venue bound to the synthetic listed contract.

    Returns:
        None; assertions inspect the actual HTTP and detached phase observations.

    Raises:
        AssertionError: If the refusal, authority, custody or wire contract differs.
    """
    stack = exact_stack("dhan", exchange, evidence="ambiguous")
    response, phase = _post(stack, named=True)
    assert response.status_code == 400, response.get_json()
    _no_admission(phase)
    assert len(phase["preflights"]) == 1


@pytest.mark.parametrize("exchange", ["NFO", "BFO"])
def test_kotak_conflicting_snapshot_cannot_be_installed_as_http_evidence(
    exact_stack: Callable[..., SimpleNamespace], exchange: str,
) -> None:
    """Preserve listing acquisition failure rather than manufacturing evidence.

    Args:
        exact_stack: Normal-factory fixture builder with inert SDK transports.
        exchange: Canonical venue bound to the synthetic listed contract.

    Returns:
        None; assertions inspect the actual HTTP and detached phase observations.

    Raises:
        AssertionError: If the refusal, authority, custody or wire contract differs.
    """
    from flinttrade_core.broker_read_port import BrokerReadResponseInvalid
    with pytest.raises(BrokerReadResponseInvalid):
        _resolver("kotakneo", exchange, ambiguous=True)
    # No prior good snapshot in this synthetic account. Acquisition failure is
    # not silently converted into a new valid resolver or a legacy search.
    stack = exact_stack("kotakneo", exchange, evidence="missing")
    response, phase = _post(stack, named=True)
    assert response.status_code == 501, response.get_json()
    _no_admission(phase)
    assert len(phase["preflights"]) == 1


@pytest.mark.parametrize("broker", ["dhan", "kotakneo"])
@pytest.mark.parametrize("named", [False, True], ids=["default", "named"])
@pytest.mark.parametrize("field,value", [
    ("token", "98765"), ("source_digest", "changed-source"), ("record_digest", "changed-contract"),
    ("triggerPrice", "100"), ("orderType", "MARKET"), ("transactionType", "BUY"), ("qty", "6"),
    ("ts", "OTHER-CONTRACT"), ("es", "bse_fo"), ("qt", "6"), ("tt", "B"), ("pt", "MKT"), ("tp", "100"),
])
def test_unrepresented_native_intent_refuses_before_canonical_selection(
    exact_stack: Callable[..., SimpleNamespace], broker: str, named: bool, field: str, value: str,
) -> None:
    """Refuse unsupported identity/economic aliases before any provider work.

    Args:
        exact_stack: Normal-factory fixture builder with inert SDK transports.
        broker: Exact configured broker, independent of any body override.
        named: Whether to select the explicit rather than configured route.
        field: Unsupported native spelling absent from the signed Order.
        value: Conflicting native identity or economic intent.

    Returns:
        None; assertions inspect the detached refusal-phase ledger.

    Raises:
        AssertionError: If an alias reaches preflight, admission or the SDK.
    """
    stack = exact_stack(broker)
    response, phase = _post(stack, {field: value}, named=named)
    _no_admission(phase)
    assert phase["preflights"] == []
    assert response.status_code == 400, response.get_json()


@pytest.mark.parametrize("broker", ["dhan", "kotakneo"])
@pytest.mark.parametrize("field", ["token", "triggerPrice", "qt"])
@pytest.mark.parametrize(
    "value", [None, False, 0, "", [], {}], ids=["null", "false", "zero", "blank", "list", "object"],
)
def test_unrepresented_native_intent_presence_is_not_omission(
    exact_stack: Callable[..., SimpleNamespace], broker: str, field: str, value: Any,
) -> None:
    """Unrepresented native fields have no nullable or inactive alias contract.

    Args:
        exact_stack: Normal-factory fixture builder with inert SDK transports.
        broker: Selected broker whose raw ingress contract is challenged.
        field: Unsupported native identity, trigger or quantity spelling.
        value: Present JSON value that must not disappear during selection.

    Returns:
        None; no broker read, reservation or one-shot authority may exist.

    Raises:
        AssertionError: If a present unsupported value is treated as omission.
    """
    stack = exact_stack(broker)
    response, phase = _post(stack, {field: value}, named=True)
    _no_admission(phase)
    assert phase["preflights"] == []
    assert response.status_code == 400, response.get_json()


@pytest.mark.parametrize("broker", ["dhan", "kotakneo"])
@pytest.mark.parametrize("kind", ["cash", "future"])
@pytest.mark.parametrize("named", [False, True], ids=["default", "named"])
def test_native_alias_refusal_preserves_ordinary_and_metadata_controls(
    exact_stack: Callable[..., SimpleNamespace], broker: str, kind: str, named: bool,
) -> None:
    """Retain ordinary positive intent without trusting unrelated JSON metadata.

    Args:
        exact_stack: Normal-factory fixture builder with inert SDK transports.
        broker: Exact broker selected through the real router.
        kind: Existing ordinary cash or future positive control.
        named: Whether to exercise named or configured placement.

    Returns:
        None; the refused phase remains empty beside the later genuine ACK.

    Raises:
        AssertionError: If refusal loses intent or metadata becomes authority.
    """
    stack = exact_stack(broker)
    _ordinary_control(stack, kind)
    refused, refused_phase = _post(stack, {"qty": "6"}, named=named)
    _no_admission(refused_phase)
    assert refused.status_code == 400
    response, phase = _post(stack, {
        "market_protection": None, "entry_trigger_type": None,
        "contract": {"token": "not-authority", "qualified": True}, "qualified": True,
        "actor_type": "service", "actor_id": "foreign", "source": "automate",
    }, named=named)
    assert response.status_code == 200, response.get_json()
    assert phase["minted"] == 1 and phase["consumed"] == [True]
    assert len(phase["wire"]) == len(phase["invoked"]) == 1
    order, context, _ticket = stack.minted[0]
    assert (context.actor_id, context.actor_type, context.selector) == ("operator", "human", f"{broker}:{ACCOUNT}")
    assert not {"contract", "qualified", "actor_id", "actor_type", "source"}.intersection(order.model_dump())
    assert not {"contract", "qualified", "source"}.intersection(phase["wire"][0])
    assert str(phase["wire"][0]["quantity" if broker == "dhan" else "qt"]) == "3"
    _no_admission(refused_phase)


@pytest.mark.parametrize("broker", ["dhan", "kotakneo"])
@pytest.mark.parametrize("shape", ["async-function", "returned-coroutine", "awaitable", "async-generator"])
def test_uncompleted_preflight_never_reaches_books_or_authority(
    exact_stack: Callable[..., SimpleNamespace], broker: str, shape: str,
) -> None:
    """Reject lazy validation without executing its body or arbitrary cleanup.

    Args:
        exact_stack: Real factory/gate/router with labelled inert transports.
        broker: Exact selected broker delegated by the faulty trusted hook.
        shape: Async callable or lazy object returned instead of validation.

    Returns:
        None; the same real adapter subsequently proves synchronous success.

    Raises:
        AssertionError: If validation is executed, ignored or treated as a grant.
    """
    stack = exact_stack(broker)
    entered: list[str] = []
    pending: list[Any] = []

    async def async_hook(order: Any) -> Any:
        entered.append("coroutine-body")
        return stack.adapter.preflight_order(order)

    async def async_generator(order: Any) -> Any:
        entered.append("generator-body")
        yield stack.adapter.preflight_order(order)

    class IncompleteValidation:
        def __await__(self) -> Any:
            entered.append("awaitable-body")
            yield None
            return None

        def close(self) -> None:
            entered.append("arbitrary-close")

    def hook(order: Any) -> Any:
        value = (IncompleteValidation() if shape == "awaitable" else
                 async_generator(order) if shape == "async-generator" else async_hook(order))
        pending.append(value)
        return value

    stack.router._adapters[broker] = SimpleNamespace(
        broker_id=broker, preflight_order=async_hook if shape == "async-function" else hook,
        place_order=stack.adapter.place_order,
    )
    try:
        refused, refused_phase = _post(stack, named=True)
        _no_admission(refused_phase)
        assert refused.status_code == (400 if broker == "dhan" else 501)
        assert entered == []
        assert refused_phase["preflights"] == []
        stack.router._adapters[broker] = stack.adapter
        response, phase = _post(stack, named=True)
        assert response.status_code == 200, response.get_json()
        assert len(phase["wire"]) == len(phase["invoked"]) == 1
        assert phase["minted"] == 1 and phase["consumed"] == [True]
        _no_admission(refused_phase)
    finally:
        for value in pending:
            if shape == "returned-coroutine":
                value.close()
            elif shape == "async-generator":
                asyncio.run(value.aclose())


@pytest.mark.parametrize("broker", ["dhan", "kotakneo"])
@pytest.mark.parametrize("kind", ["cash", "options"])
def test_completed_preflight_preserves_real_synchronous_result(
    exact_stack: Callable[..., SimpleNamespace], monkeypatch: pytest.MonkeyPatch, broker: str, kind: str,
) -> None:
    """Preserve the actual synchronous None/dict observation, without authority.

    Args:
        exact_stack: Normal-factory builder using the installed SDK adapters.
        monkeypatch: Test-owned observer restoring the exact adapter method.
        broker: Broker whose real preflight result is inspected.
        kind: Ordinary nonlisted cash or exact listed option.

    Returns:
        None; the router returns the actual object and creates no holds.

    Raises:
        AssertionError: If a completed result is replaced or treated as a grant.
    """
    from flinttrade_core.order_routes import _body_to_order

    stack = exact_stack(broker)
    if kind == "cash":
        _ordinary_control(stack, kind)
    observations: list[Any] = []
    original = stack.adapter.preflight_order

    def observe(order: Any) -> Any:
        result = original(order)
        observations.append(result)
        return result

    monkeypatch.setattr(stack.adapter, "preflight_order", observe)
    order = _body_to_order(stack.body, adapter_id=broker)
    result = stack.router.preflight_order(order, adapter_id=broker)
    assert len(observations) == 1 and result is observations[0]
    assert result is None if broker == "kotakneo" and kind == "cash" else type(result) is dict
    _no_admission(_snapshot(stack))
