"""Adapter-only Dhan observations using synthetic data and the installed SDK.

These controls establish no provider acceptance, account eligibility, paid-fee
allocation, canonical persistence or options execution authority.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, Callable

import pytest

from flinttrade_core.broker_read_port import BrokerReadResponseInvalid
from flinttrade_gateway.brokers import dhan_mapping as M
from flinttrade_gateway.brokers._base import Session
from flinttrade_gateway.brokers.dhan import DhanAdapter

pytestmark = pytest.mark.unit


def session() -> Session:
    """Construct a disposable synthetic Dhan session."""
    return Session(access_token="synthetic-token", expires_at=9e9,
                   account_id="synthetic-account", adapter_id="dhan")


def request(**overrides: Any) -> SimpleNamespace:
    """Construct explicit synthetic order terms with requested overrides.

    Args:
        overrides: Test-specific replacements for the fixed synthetic cash terms.

    Returns:
        Attribute-based terms consumed by the existing mapper and adapter seams.
    """
    fields = dict(symbol="SYNTH", exchange="NSE", action="BUY", quantity="3",
                  product="CNC", pricetype="LIMIT", price="7.25", trigger_price="0")
    return SimpleNamespace(**(fields | overrides))


def sdk_adapter(
    monkeypatch: pytest.MonkeyPatch,
    response: Any,
) -> tuple[DhanAdapter, list[tuple[str, str, dict]]]:
    """Bind the genuine pinned SDK to an inert recording transport.

    Args:
        monkeypatch: Pytest fixture restoring the SDK transport after the case.
        response: Synthetic native JSON response returned by that transport.

    Returns:
        Adapter and the exact method, URL and kwargs request ledger.
    """
    from dhanhq import DhanContext, dhanhq
    client = dhanhq(DhanContext("synthetic-account", "synthetic-token"))
    calls = []

    def transport(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return SimpleNamespace(status_code=200, content=json.dumps(response).encode())

    monkeypatch.setattr(client.dhan_http.session, "request", transport)
    adapter = DhanAdapter(client_factory=lambda _: client, security_resolver=lambda *_: "SYNTH-ID")
    return adapter, calls


async def test_single_margin_preserves_variable_raw_and_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Retain independent single-margin observations without filling absent fields."""
    native = {"totalMargin": "21.7500", "variableMargin": "2.00", "availableBalance": "8.00"}
    adapter, calls = sdk_adapter(monkeypatch, native)
    result = await adapter.margin_calculator(session(), request())
    assert result["required_margin"] == "21.7500"
    assert result["variable_margin"] == "2.00"
    assert result["available_balance"] == "8.00"
    assert "brokerage" not in result and "span_margin" not in result
    assert result["broker_fields"] == native
    assert result["observation_kind"] == "estimate"
    assert len(calls) == 1
    assert json.loads(calls[0][2]["data"]) == {
        "securityId": "SYNTH-ID", "exchangeSegment": "NSE_EQ", "transactionType": "BUY",
        "quantity": 3, "productType": "CNC", "price": 7.25, "triggerPrice": 0.0,
        "dhanClientId": "synthetic-account",
    }


@pytest.mark.parametrize("native", [None, [], {}, {"totalMargin": None}, {"totalMargin": True},
    {"totalMargin": "NaN"}, {"totalMargin": "-1"}, {"totalMargin": "1", "variableMargin": "bad"},
    {"totalMargin": "1", "total_margin": "2"}])
def test_single_margin_refuses_unavailable_or_malformed(native: Any) -> None:
    """Refuse unavailable, malformed and contradictory margin observations."""
    with pytest.raises(BrokerReadResponseInvalid):
        M.from_dhan_margin({"status": "success", "data": native})


def test_single_margin_retains_observed_zero_without_making_paid_fees() -> None:
    """Preserve observed zero while keeping estimated brokerage distinct from payment."""
    result = M.from_dhan_margin({"totalMargin": 0, "brokerage": "0", "insufficientBalance": "-2"})
    assert result["required_margin"] == "0"
    assert result["insufficient_balance"] == "-2"
    assert "paid" not in result


async def test_multi_margin_executes_pinned_resource_with_explicit_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify exact multi-margin request flags and unqualified raw estimates."""
    native = {"total_margin": "19.00", "hedge_benefit": "2.75", "fo_margin": "19.00"}
    adapter, calls = sdk_adapter(monkeypatch, native)
    result = await adapter.margin_calculator_multi(
        session(), [request(), request(action="SELL")], include_position=True, include_order=False,
    )
    assert result["required_margin"] == "19.00" and result["hedge_benefit"] == "2.75"
    assert result["broker_fields"] == native
    assert "available_balance" not in result
    assert result["include_position"] is True and result["include_order"] is False
    assert result["provider_acceptance"] == "unverified_request_name_conflict"
    assert result["observation_kind"] == "estimate"
    assert len(calls) == 1
    assert calls[0][0:2] == ("POST", "https://api.dhan.co/v2/margincalculator/multi")
    leg = {"exchangeSegment": "NSE_EQ", "transactionType": "BUY", "quantity": 3,
           "productType": "CNC", "securityId": "SYNTH-ID", "price": 7.25, "triggerPrice": 0.0}
    assert json.loads(calls[0][2]["data"]) == {
        "includePosition": True, "includeOrder": False, "scripList": [leg, leg | {"transactionType": "SELL"}],
        "dhanClientId": "synthetic-account",
    }


@pytest.mark.parametrize("flags", [{}, {"include_position": False},
    {"include_position": 1, "include_order": False}, {"include_position": False, "include_order": "false"}])
async def test_multi_margin_never_defaults_inclusion_flags(
    monkeypatch: pytest.MonkeyPatch,
    flags: dict[str, Any],
) -> None:
    """Refuse missing or non-boolean inclusion flags before invoking the SDK."""
    adapter, calls = sdk_adapter(monkeypatch, {"total_margin": 1})
    with pytest.raises((TypeError, M.DhanMappingError)):
        await adapter.margin_calculator_multi(session(), [request()], **flags)
    assert calls == []


@pytest.mark.parametrize("native", [None, {}, {"total_margin": None}, {"total_margin": "NaN"},
    {"total_margin": -1}, {"total_margin": 1, "hedge_benefit": True}])
async def test_multi_margin_malformed_response_never_retries(monkeypatch: pytest.MonkeyPatch, native: Any) -> None:
    """Refuse an invalid estimate after exactly one native request, without retry."""
    adapter, calls = sdk_adapter(monkeypatch, native)
    with pytest.raises(BrokerReadResponseInvalid):
        await adapter.margin_calculator_multi(session(), [request()], include_position=False, include_order=True)
    assert len(calls) == 1


def fill(**overrides: Any) -> dict[str, Any]:
    """Build a synthetic fill with independent identity, quantity and time evidence."""
    return dict(orderId="order-A", exchangeTradeId="fill-A", exchangeOrderId="exchange-A",
                dhanClientId="synthetic-account", securityId="contract-A", tradingSymbol="SYNTH-CE",
                exchangeSegment="NSE_FNO", productType="MARGIN", transactionType="BUY",
                tradedQuantity="6", tradedPrice="7.250", createTime="2026-01-02 09:15:01",
                updateTime="2026-01-02 09:15:03", exchangeTime="2026-01-02 09:15:02",
                drvExpiryDate="2026-01-29", drvOptionType="CALL", drvStrikePrice="101.00") | overrides


async def test_trade_book_preserves_exact_native_fill_observations(monkeypatch: pytest.MonkeyPatch) -> None:
    """Retain detached native fill observations through the actual adapter read."""
    native = fill()
    adapter, calls = sdk_adapter(monkeypatch, [native])
    result, = await adapter.trade_book(session())
    assert result["fill_id"] == "fill-A"
    assert result["exchange_order_id"] == "exchange-A"
    assert result["broker_account_id"] == "synthetic-account"
    assert result["broker_exchange_segment"] == "NSE_FNO"
    assert result["broker_product_type"] == "MARGIN"
    assert result["created_at"] == native["createTime"]
    assert result["updated_at"] == native["updateTime"]
    assert result["exchange_time"] == native["exchangeTime"]
    assert result["option_type"] == "CE" and result["strike_price"] == "101.00"
    assert result["expiry"] == "2026-01-29"
    assert result["broker_fields"] == native
    native["exchangeTradeId"] = "mutated"
    assert result["broker_fields"]["exchangeTradeId"] == "fill-A"
    assert len(calls) == 1


@pytest.mark.parametrize("changes", [dict(quantity="7"), dict(price="8"), dict(quantity=None),
    dict(price=True), dict(drvStrikePrice="NaN"), dict(exchangeTradeId={}), dict(drvOptionType="unknown"),
    dict(brokerageCharges="bad"), dict(tradedQuantity="1.5"), dict(tradedQuantity=-1)])
def test_fill_conflicts_and_malformed_secondary_observations_refuse(changes: dict[str, Any]) -> None:
    """Refuse conflicting or malformed supplied secondary fill observations."""
    with pytest.raises(BrokerReadResponseInvalid):
        M.from_dhan_trade(fill(**changes))


def test_fill_missing_id_is_not_synthesised_and_charges_are_not_paid() -> None:
    """Do not manufacture fill identity or payment evidence from observed charges."""
    native = fill(quantity=6, price=7.25, brokerageCharges="1.00", serviceTax="0.18")
    del native["exchangeTradeId"]
    result = M.from_dhan_trade(native)
    assert "fill_id" not in result
    assert result["quantity"] == "6" and result["price"] == "7.250"
    assert result["broker_fields"]["brokerageCharges"] == "1.00"
    assert "paid" not in result and "paid_fees" not in result


@pytest.mark.parametrize("account", [None, "", " "])
async def test_trade_book_refuses_present_but_unavailable_account(
    monkeypatch: pytest.MonkeyPatch,
    account: str | None,
) -> None:
    """Reject a supplied null or blank provider account rather than drop it."""
    adapter, calls = sdk_adapter(monkeypatch, [fill(dhanClientId=account)])
    with pytest.raises(BrokerReadResponseInvalid):
        await adapter.trade_book(session())
    assert len(calls) == 1


async def test_trade_book_refuses_foreign_native_account(monkeypatch: pytest.MonkeyPatch) -> None:
    """Refuse fill observations naming an account other than the bound session."""
    adapter, calls = sdk_adapter(monkeypatch, [fill(dhanClientId="foreign")])
    with pytest.raises(BrokerReadResponseInvalid):
        await adapter.trade_book(session())
    assert len(calls) == 1


@pytest.mark.parametrize("native", [None, {}, "", [fill(), None], {"data": None}])
async def test_history_never_manufactures_empty_or_filters_invalid_rows(
    monkeypatch: pytest.MonkeyPatch,
    native: Any,
) -> None:
    """Distinguish unavailable history from an empty page and retain invalid-row refusal."""
    adapter, calls = sdk_adapter(monkeypatch, native)
    with pytest.raises(BrokerReadResponseInvalid):
        await adapter.trade_history(session(), "2026-01-01", "2026-01-02")
    assert len(calls) == 1


@pytest.mark.parametrize("native", [[], [fill(brokerageCharges="1.00")]])
async def test_history_page_retains_window_and_unknown_terminal(monkeypatch: pytest.MonkeyPatch, native: Any) -> None:
    """Retain the exact requested page/window without claiming terminal completeness."""
    adapter, calls = sdk_adapter(monkeypatch, native)
    rows = await adapter.trade_history(session(), "2026-01-01", "2026-01-02", 3)
    assert rows == native
    assert rows.coverage == {"resource": "trade_history", "from_date": "2026-01-01", "to_date": "2026-01-02",
        "page": 3, "complete": False, "terminal": "undocumented", "broker_account_id": "synthetic-account"}
    assert len(calls) == 1 and calls[0][1].endswith("/trades/2026-01-01/2026-01-02/3")


async def test_ledger_preserves_documented_single_object(monkeypatch: pytest.MonkeyPatch) -> None:
    """Preserve the ledger resource's documented single-object result."""
    native = {"dhanClientId": "synthetic-account", "vouchernumber": "voucher-A", "debit": "2.50", "credit": 0}
    adapter, calls = sdk_adapter(monkeypatch, native)
    rows = await adapter.ledger(session(), "2026-01-01", "2026-01-02")
    assert rows == [native]
    assert rows.coverage["complete"] is False
    assert len(calls) == 1


@pytest.mark.parametrize("native", [None, {}, [{"orderId": "order-A"}, {"orderId": "order-B"}],
    {"orderId": "foreign"}])
async def test_order_specific_read_refuses_wrong_cardinality_or_identity(
    monkeypatch: pytest.MonkeyPatch,
    native: Any,
) -> None:
    """Reject wrong identity or cardinality at the order-specific read seam."""
    adapter, calls = sdk_adapter(monkeypatch, native)
    with pytest.raises(BrokerReadResponseInvalid):
        await adapter.get_order_by_id(session(), "order-A")
    assert len(calls) == 1


async def test_order_specific_empty_is_explicit_absence(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep a genuinely empty order-specific result as explicit absence."""
    adapter, calls = sdk_adapter(monkeypatch, [])
    assert await adapter.get_order_by_id(session(), "order-A") is None
    assert len(calls) == 1


@pytest.mark.parametrize("native", [fill(), [fill(), fill(exchangeTradeId="fill-B")], []])
async def test_order_specific_trades_keep_all_fills(monkeypatch: pytest.MonkeyPatch, native: Any) -> None:
    """Preserve all fills returned by the exact order-specific resource."""
    adapter, calls = sdk_adapter(monkeypatch, native)
    rows = await adapter.trade_book(session(), order_id="order-A")
    expected = native if type(native) is list else [native]
    assert [row["fill_id"] for row in rows] == [row["exchangeTradeId"] for row in expected]
    assert len(calls) == 1 and calls[0][1].endswith("/trades/order-A")


def master_row(**overrides: Any) -> dict[str, Any]:
    """Construct a synthetic listing, not current exchange contract evidence."""
    # Deliberately synthetic lot/tick/contract; not a current exchange listing.
    return dict(EXCH_ID="NSE", SEGMENT="D", SECURITY_ID="contract-A", INSTRUMENT="OPTIDX",
                TRADING_SYMBOL="SYNTH-JAN2099-101-CE", DISPLAY_NAME="SYNTH 29 JAN 101 CALL",
                SYMBOL_NAME="SYNTH", UNDERLYING_SYMBOL="SYNTH", UNDERLYING_SECURITY_ID="underlying-A",
                SM_EXPIRY_DATE="2099-01-29", STRIKE_PRICE="101.000", OPTION_TYPE="CE",
                LOT_SIZE="3", TICK_SIZE="5") | overrides


def versioned_resolver(
    rows: list[dict[str, Any]] | None = None,
    **overrides: Any,
) -> M._ScripMasterSecurityResolver:
    """Build a dated synthetic resolver; omitted rows select the single test listing.

    Args:
        rows: Synthetic master rows; None retains the original fixture listing.
        overrides: Explicit source, validity, clock or independent tick-rule inputs.

    Returns:
        Existing versioned resolver, without downloading a master or guessing ticks.
    """
    return M.build_security_resolver(rows or [master_row()], **(dict(
        source_revision="synthetic-sha256-revision-A", observed_at=100.0, valid_until=200.0,
        clock=lambda: 150.0,
    ) | overrides))


@pytest.mark.parametrize("symbol,exchange", [("NIFTY", "NFO"), ("SENSEX", "BFO")])
def test_bare_underlying_never_resolves_as_derivative(symbol: str, exchange: str) -> None:
    """Refuse underlying shortcuts where an exact derivative contract is required."""
    adapter = DhanAdapter(security_resolver=lambda *_: "fallback-is-forbidden")
    with pytest.raises(M.DhanMappingError, match="contract|underlying"):
        adapter._resolve_security(symbol, exchange)


def test_versioned_contract_keeps_exact_identity_lot_raw_tick_and_freshness() -> None:
    """Preserve exact listing identity and raw tick scale without guessing units."""
    resolver = versioned_resolver()
    contract = resolver.contract("SYNTH-JAN2099-101-CE", "NFO")
    assert contract == {
        "broker_id": "dhan", "security_id": "contract-A", "symbol": "SYNTH-JAN2099-101-CE",
        "exchange": "NFO", "exchange_segment": "NSE_FNO", "instrument": "OPTIDX",
        "expiry": "2099-01-29", "strike_price": "101.000", "option_type": "CE",
        "underlying": "SYNTH", "underlying_security_id": "underlying-A", "lot_size": 3,
        "raw_tick_size": "5", "tick_size": None, "tick_scale": "unavailable",
        "source_revision": "synthetic-sha256-revision-A", "observed_at": 100.0, "valid_until": 200.0,
    }
    with pytest.raises(M.DhanMappingError):
        resolver("SYNTH", "NFO")
    with pytest.raises(M.DhanMappingError):
        resolver.contract("SYNTH-JAN2099-101-CE", "BFO")


@pytest.mark.parametrize("changes", [dict(LOT_SIZE="0"), dict(LOT_SIZE="1.5"), dict(LOT_SIZE=""),
    dict(OPTION_TYPE="garbage"), dict(STRIKE_PRICE="NaN"), dict(UNDERLYING_SYMBOL=""),
    dict(SM_EXPIRY_DATE="bad")])
def test_contract_refuses_missing_or_malformed_exact_evidence(changes: dict[str, Any]) -> None:
    """Refuse missing or malformed listing facts instead of substituting defaults."""
    with pytest.raises(M.DhanMappingError):
        versioned_resolver([master_row(**changes)]).contract("SYNTH-JAN2099-101-CE", "NFO")


async def test_existing_lot_interface_rejects_stale_and_accepts_refreshed_snapshot() -> None:
    """Require fresh exact lot evidence and admit an explicitly refreshed snapshot."""
    from flinttrade_core.broker_read_port import LotSizeRequest
    now = [150.0]
    resolver = versioned_resolver(clock=lambda: now[0])
    adapter = DhanAdapter(security_resolver=resolver)
    query = LotSizeRequest(exchange="NFO", symbols=("SYNTH-JAN2099-101-CE",))
    rows = await adapter.instrument_lot_sizes(session(), query)
    assert rows[0]["symbol"] == query.symbols[0] and rows[0]["lot_size"] == 3
    assert rows[0]["instrument_id"] == "contract-A"
    assert rows[0]["source_revision"] == "synthetic-sha256-revision-A"
    now[0] = 200.0
    with pytest.raises(M.DhanMappingError):
        await adapter.instrument_lot_sizes(session(), query)
    adapter.install_security_resolver(versioned_resolver([master_row(LOT_SIZE="6")],
        source_revision="synthetic-revision-B", observed_at=200.0, valid_until=300.0, clock=lambda: now[0]))
    assert (await adapter.instrument_lot_sizes(session(), query))[0]["lot_size"] == 6


def auth_adapter(
    monkeypatch: pytest.MonkeyPatch,
    profile: dict[str, Any],
) -> tuple[DhanAdapter, Any, list[tuple[str, dict]]]:
    """Bind the pinned profile resource to inert authentication-only responses.

    Args:
        monkeypatch: Pytest fixture restoring profile and financial transports.
        profile: Synthetic provider profile, including deliberately invalid cases.

    Returns:
        Adapter, actual pinned client and exact profile-request ledger. Financial
        transport always raises; no account or broker activity is performed.
    """
    from dhanhq import DhanContext, DhanLogin, dhanhq
    import dhanhq.auth as auth
    client = dhanhq(DhanContext("synthetic-account", "synthetic-token"))
    calls = []
    def get(url, **kwargs):
        calls.append((url, kwargs))
        return SimpleNamespace(status_code=200, json=lambda: profile)
    monkeypatch.setattr(auth.requests, "get", get)
    def unexpected(*args, **kwargs):
        raise AssertionError("No funds/market/order transport is part of profile verification")
    monkeypatch.setattr(client.dhan_http.session, "request", unexpected)
    return DhanAdapter(client_factory=lambda _: client, login_factory=DhanLogin), client, calls


async def test_reconnect_expiry_requires_provider_profile_without_local_extension(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Require provider verification before assigning expiry, without a local extension."""
    from datetime import datetime, timezone, timedelta
    profile = {"dhanClientId": "synthetic-account", "tokenValidity": "02/01/2099 10:00"}
    adapter, client, calls = auth_adapter(monkeypatch, profile)
    candidate = await adapter.login({
        "client_id": "synthetic-account", "access_token": "synthetic-token"})
    assert candidate.expires_at == 0  # unavailable before provider proof, not now+24h
    assert candidate.extra["client"] is client
    assert calls == []  # owner can take custody before the first fallible profile read
    await adapter.liveness(candidate)
    expected = datetime(2099, 1, 2, 10, tzinfo=timezone(timedelta(hours=5, minutes=30))).timestamp()
    assert candidate.expires_at == expected
    await adapter.liveness(candidate)
    assert candidate.expires_at == expected
    assert len(calls) == 2 and all(call[0].endswith("/profile") for call in calls)
    adapter.dispose_session(candidate)
    assert candidate.extra.get("client") is None and len(calls) == 2


@pytest.mark.parametrize("profile", [{}, {"dhanClientId": "foreign", "tokenValidity": "02/01/2099 10:00"},
    {"dhanClientId": "synthetic-account", "tokenValidity": "02/01/2000 10:00"},
    {"dhanClientId": "synthetic-account", "tokenValidity": "bad"},
    {"status": "failure", "data": {"dhanClientId": "synthetic-account", "tokenValidity": "02/01/2099 10:00"}}])
async def test_profile_failure_retains_actual_session_in_existing_cleanup_custody(
    monkeypatch: pytest.MonkeyPatch,
    profile: dict[str, Any],
) -> None:
    """Keep the actual created client in candidate custody through profile refusal."""
    from flinttrade_gateway.native_login import prepare_native_session
    from flinttrade_core.exceptions import BrokerError
    adapter, client, calls = auth_adapter(monkeypatch, profile)
    owned = []
    with pytest.raises(BrokerError):
        await prepare_native_session(adapter, {"client_id": "synthetic-account", "access_token": "synthetic-token"},
            verify=True, strict_probe=True, mutation_admission=lambda: None, accept_candidate=owned.append)
    assert len(owned) == 1 and owned[0].session.extra["client"] is client
    assert owned[0].session.expires_at == 0
    adapter.dispose_session(owned[0].session)
    assert len(calls) == 1


async def test_unverified_jwt_claims_never_supply_provider_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never use unverified token claims to replace provider identity or expiry."""
    from flinttrade_core.exceptions import BrokerError
    adapter, client, calls = auth_adapter(monkeypatch, {})
    candidate = await adapter.login({
        "client_id": "synthetic-account", "access_token": "e30.eyJleHAiOjk5OTk5OTk5OTl9.unsigned"})
    with pytest.raises(BrokerError):
        await adapter.liveness(candidate)
    assert candidate.expires_at == 0 and candidate.extra["client"] is client
    adapter.dispose_session(candidate)


@pytest.mark.parametrize("changes", [dict(product="CNC"), dict(pricetype="SL-M", trigger_price="7"),
    dict(quantity="4"), dict(price="7.1")])
async def test_existing_placement_refuses_unqualified_derivative_intent(
    monkeypatch: pytest.MonkeyPatch,
    changes: dict[str, Any],
) -> None:
    """Refuse unqualified derivative terms before the actual placement transport."""
    from flinttrade_gateway.brokers.dhan import _ROUTER_TOKEN
    adapter, calls = sdk_adapter(monkeypatch, {"orderId": "unsafe-synthetic-ack"})
    adapter.install_security_resolver(versioned_resolver())
    order = request(**(dict(symbol="SYNTH-JAN2099-101-CE", exchange="NFO", product="NRML") | changes))
    with pytest.raises(M.DhanMappingError):
        await adapter.place_order(session(), order, _router_token=_ROUTER_TOKEN)
    assert calls == []


def test_historical_fill_preserves_independent_display_and_instrument_fields() -> None:
    """Keep display, instrument and timestamp observations independent of contract authority."""
    native = fill(tradingSymbol=None, customSymbol="Synthetic Company", isin="SYNTHETIC-ISIN", instrument="EQUITY",
                  exchangeSegment="NSE_EQ", productType="CNC",
                  drvExpiryDate="NA", drvOptionType="NA", drvStrikePrice=0, createTime="NA", updateTime="NA")
    result = M.from_dhan_trade(native)
    assert result["symbol"] == ""  # display name does not replace exchange trading symbol
    assert result["broker_fields"] == native
    assert result["created_at"] == "NA" and result["updated_at"] == "NA"
    assert "trade_date" not in result and "fill_time" not in result


def tick_rule(**overrides: Any) -> dict[str, Any]:
    """Construct independent synthetic tick evidence with explicit source validity.

    Args:
        overrides: Test-specific rule fields; no raw-master scale is inferred.

    Returns:
        Detached synthetic exchange-rule observations bound to a master revision.
    """
    return dict(tick_size="0.25", source_kind="exchange_rule", source_revision="synthetic-rule-A",
        source_url="https://example.invalid/synthetic-tick-rule",
        contract_source_revision="synthetic-sha256-revision-A",
        observed_at=100.0, valid_until=200.0) | overrides


@pytest.mark.parametrize("exchange,native", [("NFO", "NSE"), ("BFO", "BSE")])
@pytest.mark.parametrize("product", ["MIS", "NRML"])
async def test_option_preflight_and_real_pinned_placement_share_exact_contract(
    monkeypatch: pytest.MonkeyPatch,
    exchange: str,
    native: str,
    product: str,
) -> None:
    """Bind pure option preflight to the same exact contract sent by the pinned SDK."""
    from flinttrade_gateway.brokers.dhan import _ROUTER_TOKEN
    adapter, calls = sdk_adapter(monkeypatch, {"orderId": "synthetic-ack"})
    adapter.install_security_resolver(versioned_resolver([master_row(EXCH_ID=native)],
        tick_rules={("contract-A", exchange): tick_rule()}))
    order = request(symbol="SYNTH-JAN2099-101-CE", exchange=exchange, product=product, quantity="6")
    prepared = adapter.preflight_order(order)
    assert prepared["quantity"] == 6 and prepared["security_id"] == "contract-A"
    assert calls == []
    result = await adapter.place_order(session(), order, _router_token=_ROUTER_TOKEN)
    assert result == "synthetic-ack"  # ACK, not fill, protection or authority
    assert len(calls) == 1
    body = json.loads(calls[0][2]["data"])
    assert body["quantity"] == 6 and body["securityId"] == "contract-A"
    assert body["productType"] == M.PRODUCT_MAP[product]


@pytest.mark.parametrize("changes", [dict(product="CNC"), dict(product="MTF"), dict(quantity="4"),
    dict(quantity="1.5"), dict(pricetype="SL-M", trigger_price="7"), dict(price="7.1"),
    dict(price="NaN"), dict(pricetype="SL", trigger_price="7.5"), dict(pricetype="SL", trigger_price="0")])
async def test_option_preflight_refuses_before_actual_transport(
    monkeypatch: pytest.MonkeyPatch,
    changes: dict[str, Any],
) -> None:
    """Reject invalid lot, product, price and trigger intent before native transport."""
    from flinttrade_gateway.brokers.dhan import _ROUTER_TOKEN
    adapter, calls = sdk_adapter(monkeypatch, {"orderId": "should-not-send"})
    adapter.install_security_resolver(versioned_resolver(tick_rules={("contract-A", "NFO"): tick_rule()}))
    order = request(**(dict(symbol="SYNTH-JAN2099-101-CE", exchange="NFO", product="NRML", quantity="6") | changes))
    with pytest.raises(M.DhanMappingError):
        adapter.preflight_order(order)
    with pytest.raises(M.DhanMappingError):
        await adapter.place_order(session(), order, _router_token=_ROUTER_TOKEN)
    assert calls == []


@pytest.mark.parametrize("row,rule", [(master_row(), None), (master_row(SM_EXPIRY_DATE="2000-01-01"), tick_rule()),
    (master_row(), tick_rule(valid_until=150.0)), (master_row(), tick_rule(contract_source_revision="foreign"))])
def test_option_preflight_refuses_unavailable_tick_or_expiry(
    row: dict[str, Any],
    rule: dict[str, Any] | None,
) -> None:
    """Require independent fresh tick and expiry evidence rather than raw-scale guesses."""
    rules = {} if rule is None else {("contract-A", "NFO"): rule}
    adapter = DhanAdapter(security_resolver=versioned_resolver([row], tick_rules=rules))
    with pytest.raises(M.DhanMappingError):
        adapter.preflight_order(request(symbol="SYNTH-JAN2099-101-CE", exchange="NFO", product="NRML"))


def test_nse_future_slm_remains_supported_with_exact_evidence() -> None:
    """Retain the independently evidenced NSE future SL-M positive control."""
    row = master_row(INSTRUMENT="FUTIDX", TRADING_SYMBOL="SYNTH-JAN2099-FUT")
    adapter = DhanAdapter(security_resolver=versioned_resolver([row], tick_rules={("contract-A", "NFO"): tick_rule()}))
    result = adapter.preflight_order(request(symbol="SYNTH-JAN2099-FUT", exchange="NFO", product="NRML",
        pricetype="SL-M", price="0", trigger_price="7"))
    assert result["order_type"] == "STOP_LOSS_MARKET"


@pytest.mark.parametrize("change", [dict(OPTION_TYPE="PE"), dict(STRIKE_PRICE="102"),
    dict(EXCH_ID="BSE", SEM_EXM_EXCH_ID="NSE"), dict(SEGMENT="D-junk")])
def test_versioned_master_rejects_conflicting_contract_columns(change: dict[str, Any]) -> None:
    """Refuse contradictory venue, right and strike observations in a versioned row."""
    with pytest.raises(M.DhanMappingError):
        versioned_resolver([master_row(**change)]).contract("SYNTH-JAN2099-101-CE", "NFO")


@pytest.mark.parametrize("mapper", [M.from_dhan_margin, M.from_dhan_multi_margin, M.from_dhan_statement_list])
def test_observation_mappers_refuse_unsuccessful_status(mapper: Callable[[Any], Any]) -> None:
    """Do not treat an unknown or invalid envelope status as a successful observation."""
    for status in ("unknown", None, True):
        with pytest.raises((M.DhanMappingError, BrokerReadResponseInvalid)):
            mapper({"status": status, "data": {"totalMargin": 1, "total_margin": 1}})


@pytest.mark.parametrize("start,end,page", [("bad", "2026-01-02", 0), ("2026-01-02", "2026-01-01", 0),
    ("2026-01-01", "2026-01-02", True), ("2026-01-01", "2026-01-02", -1)])
async def test_history_invalid_window_or_page_never_calls_sdk(
    monkeypatch: pytest.MonkeyPatch,
    start: str,
    end: str,
    page: int,
) -> None:
    """Reject invalid history windows and page values without invoking the SDK."""
    adapter, calls = sdk_adapter(monkeypatch, [])
    with pytest.raises(M.DhanMappingError):
        await adapter.trade_history(session(), start, end, page)
    assert calls == []


async def test_local_disposal_failure_keeps_same_client_for_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Retain exact local-client custody until its retryable close actually succeeds."""
    adapter, client, calls = auth_adapter(monkeypatch, {})
    candidate = await adapter.login({
        "client_id": "synthetic-account", "access_token": "synthetic-token"})
    attempts = []
    def close():
        attempts.append(client)
        if len(attempts) == 1:
            raise OSError("synthetic local close failure")
    monkeypatch.setattr(client.dhan_http.session, "close", close)
    with pytest.raises(OSError):
        adapter.dispose_session(candidate)
    assert candidate.extra["client"] is client
    adapter.dispose_session(candidate)
    adapter.dispose_session(candidate)
    assert attempts == [client, client] and calls == []


async def test_profile_reobservation_cannot_extend_same_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the original token expiry when later profile observations claim a longer TTL."""
    profile = {"dhanClientId": "synthetic-account", "tokenValidity": "02/01/2099 10:00"}
    adapter, client, calls = auth_adapter(monkeypatch, profile)
    candidate = await adapter.login({
        "client_id": "synthetic-account", "access_token": "synthetic-token"})
    await adapter.liveness(candidate)
    expiry = candidate.expires_at
    profile["tokenValidity"] = "03/01/2099 10:00"
    await adapter.liveness(candidate)
    assert candidate.expires_at == expiry
    adapter.dispose_session(candidate)


@pytest.mark.parametrize("mapper,data", [(M.from_dhan_margin, {"totalMargin": 1}),
    (M.from_dhan_multi_margin, {"total_margin": 1}), (M.from_dhan_statement_list, [])])
def test_observation_envelope_rejects_foreign_dictionary_hooks(mapper: Callable[[Any], Any], data: Any) -> None:
    """Reject foreign envelope containers without executing their getter hooks."""
    calls = []
    class ForeignDict(dict):
        def get(self, *args):
            calls.append("get")
            return super().get(*args)
    with pytest.raises(BrokerReadResponseInvalid):
        mapper(ForeignDict(status="success", data=data))
    assert calls == []


@pytest.mark.parametrize("surface", ["fill", "margin", "contract", "contract-id"])
def test_observation_primitives_never_invoke_foreign_conversion_hooks(surface: str) -> None:
    """Reject hostile primitive/metaclass hooks at each native observation surface."""
    calls = []
    class ForeignMeta(type):
        def __eq__(cls, other):
            calls.append("type-equality")
            return True
        __hash__ = type.__hash__
    class Foreign(metaclass=ForeignMeta):
        def __str__(self):
            calls.append("conversion")
            return "3"
    with pytest.raises((M.DhanMappingError, BrokerReadResponseInvalid)):
        if surface == "fill":
            M.from_dhan_trade(fill(tradedQuantity=Foreign()))
        elif surface == "margin":
            M.from_dhan_margin({"totalMargin": Foreign()})
        elif surface == "contract-id":
            versioned_resolver([master_row(SECURITY_ID=Foreign())])
        else:
            versioned_resolver([master_row(LOT_SIZE=Foreign())]).contract("SYNTH-JAN2099-101-CE", "NFO")
    assert calls == []


@pytest.mark.parametrize("facts", [dict(dhanClientId="foreign", expiryTime="2099-01-02T10:00:00"),
    dict(dhanClientId="synthetic-account", expiryTime="bad"),
    dict(dhanClientId="synthetic-account", expiryTime="2000-01-02T10:00:00")])
async def test_minted_token_facts_cannot_be_discarded_by_successful_profile(
    monkeypatch: pytest.MonkeyPatch,
    facts: dict[str, Any],
) -> None:
    """Retain minted-token identity and expiry constraints beside a valid profile."""
    import dhanhq.auth as auth
    from flinttrade_core.exceptions import BrokerError
    adapter, client, calls = auth_adapter(monkeypatch, {
        "dhanClientId": "synthetic-account", "tokenValidity": "02/01/2099 10:00"})
    def post(url, **kwargs):
        assert url.endswith("/app/generateAccessToken")
        return SimpleNamespace(status_code=200, json=lambda: facts | {"accessToken": "synthetic-token"})
    monkeypatch.setattr(auth.requests, "post", post)
    candidate = await adapter.login({
        "client_id": "synthetic-account", "pin": "synthetic", "totp": "synthetic"})
    assert candidate.extra["client"] is client
    with pytest.raises(BrokerError):
        await adapter.liveness(candidate)
    assert candidate.expires_at == 0
    adapter.dispose_session(candidate)
