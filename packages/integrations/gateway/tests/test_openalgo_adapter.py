"""OpenAlgo bridge adapter — forwards the gated router to OpenAlgo (contract §5).

Verifies the §8 router-token guard on writes, faithful forwarding to the
OpenAlgo client, order-id extraction + rejection, reconciliation, honest
UnsupportedCapability for streaming, and broker-error-taxonomy mapping.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from flinttrade_core.exceptions import (
    BrokerError,
    OpenAlgoRateLimitError,
    OrderRejectedByBroker,
    RateLimitError,
    SafetyBypassError,
    UnsupportedCapabilityError,
)
from flinttrade_core.models import Holding, OrderStatus, Position
from flinttrade_engine.safety import L5_EMERGENCY_POLICY, MTM_EMERGENCY_POLICY
from flinttrade_gateway.brokers._base import Session
from flinttrade_gateway.brokers.dhan import _ROUTER_TOKEN
from flinttrade_gateway.brokers.openalgo import OpenAlgoAdapter
from flinttrade_gateway.reconciliation import LocalStateSnapshot, SEVERITY_CRITICAL

pytestmark = pytest.mark.unit


class _FakeClient:
    """Minimal async stand-in for OpenAlgoClient."""

    def __init__(
        self,
        *,
        place_status: str = "success",
        raise_exc: Exception | None = None,
        orders: list[object] | None = None,
        positions: list[object] | None = None,
        holdings: list[object] | None = None,
    ) -> None:
        self.calls: list[tuple] = []
        self._place_status = place_status
        self._raise = raise_exc
        self.order_rows = list(orders or [])
        self.position_rows = (
            [{"symbol": "RELIANCE", "qty": 10}]
            if positions is None
            else list(positions)
        )
        self.holding_rows = list(holdings or [])

    async def place_order(self, order):
        self.calls.append(("place_order", order))
        if self._raise:
            raise self._raise
        return SimpleNamespace(status=self._place_status, orderid="OID-1")

    async def modify_order(self, modify):
        self.calls.append(("modify_order", modify))
        return SimpleNamespace(status="success", orderid=modify.orderid)

    async def cancel_order(self, order_id, strategy="Flint"):
        self.calls.append(("cancel_order", order_id, strategy))
        return SimpleNamespace(status="success", orderid=order_id)

    async def cancel_all_orders(self, strategy="Flint"):
        self.calls.append(("cancel_all_orders", strategy))
        return SimpleNamespace(status=self._place_status, orderid="", message="cancelled")

    async def close_position(self, strategy="Flint"):
        self.calls.append(("close_position", strategy))
        return SimpleNamespace(status=self._place_status, orderid="", message="closed")

    async def orderbook(self):
        self.calls.append(("orderbook",))
        return list(self.order_rows)

    async def positionbook(self):
        self.calls.append(("positionbook",))
        return list(self.position_rows)

    async def holdings(self):
        self.calls.append(("holdings",))
        return list(self.holding_rows)

    async def funds(self):
        return {"available": 50000.0}

    async def multi_quotes(self, payload):
        self.calls.append(("multi_quotes", payload))
        return [{"symbol": p["symbol"], "ltp": 100.0} for p in payload]


def _adapter(client: _FakeClient) -> OpenAlgoAdapter:
    return OpenAlgoAdapter(default_client=client)


def _session() -> Session:
    return Session(access_token="api-key-1", expires_at=4_102_444_800.0, account_id="dhan", adapter_id="openalgo")


def _order() -> object:
    return SimpleNamespace(symbol="RELIANCE", exchange="NSE", action="BUY", quantity=10, pricetype="MARKET")


def test_identity_and_capabilities() -> None:
    a = _adapter(_FakeClient())
    assert a.broker_id == "openalgo"
    assert a.capabilities.streaming_supported is False  # the REST bridge does not stream
    assert a.capabilities.algo_tag_required is False


async def test_login_builds_session_from_api_key() -> None:
    s = await _adapter(_FakeClient()).login({"api_key": "K", "account_id": "dhan", "host": "http://x"})
    assert s.access_token == "K"
    assert s.account_id == "dhan"
    assert s.adapter_id == "openalgo"
    assert s.extra["host"] == "http://x"


async def test_place_order_requires_router_token() -> None:
    a = _adapter(_FakeClient())
    with pytest.raises(SafetyBypassError, match="outside BrokerRouter"):
        await a.place_order(_session(), _order())  # no token


async def test_modify_order_requires_router_token() -> None:
    # The §8 guard must reject a tokenless modify before any OpenAlgo request,
    # so the FakeClient records nothing (mirrors place_order's rejection arm).
    client = _FakeClient()
    a = _adapter(client)
    with pytest.raises(SafetyBypassError, match="outside BrokerRouter"):
        await a.modify_order(_session(), "OID-1", {"price": 1.0})  # no token
    assert client.calls == []  # the guard short-circuits ahead of the client


async def test_cancel_order_requires_router_token() -> None:
    # As above for cancel: a tokenless cancel must raise before the client runs.
    client = _FakeClient()
    a = _adapter(client)
    with pytest.raises(SafetyBypassError, match="outside BrokerRouter"):
        await a.cancel_order(_session(), "OID-9")  # no token
    assert client.calls == []  # the guard short-circuits ahead of the client


async def test_place_order_forwards_and_returns_id() -> None:
    client = _FakeClient()
    a = _adapter(client)
    oid = await a.place_order(_session(), _order(), _router_token=_ROUTER_TOKEN)
    assert oid == "OID-1"
    assert client.calls[0][0] == "place_order"


async def test_place_order_rejection_raises() -> None:
    a = _adapter(_FakeClient(place_status="error"))
    with pytest.raises(OrderRejectedByBroker):
        await a.place_order(_session(), _order(), _router_token=_ROUTER_TOKEN)


async def test_cancel_order_forwards_with_strategy() -> None:
    client = _FakeClient()
    a = _adapter(client)
    await a.cancel_order(_session(), "OID-9", _router_token=_ROUTER_TOKEN)
    assert ("cancel_order", "OID-9", "Flint") in client.calls


@pytest.mark.parametrize("verb", ["cancel_all_orders", "exit_all_positions"])
async def test_emergency_sweep_requires_router_token(verb: str) -> None:
    client = _FakeClient()
    adapter = _adapter(client)

    with pytest.raises(SafetyBypassError, match="outside BrokerRouter"):
        await getattr(adapter, verb)(_session())

    assert client.calls == []


async def test_emergency_sweeps_forward_with_session_strategy() -> None:
    client = _FakeClient()
    adapter = _adapter(client)
    session = _session()
    session.extra["strategy"] = "Emergency"

    await adapter.cancel_all_orders(session, _router_token=_ROUTER_TOKEN)
    await adapter.exit_all_positions(session, _router_token=_ROUTER_TOKEN)

    assert client.calls == [
        ("cancel_all_orders", "Emergency"),
        ("close_position", "Emergency"),
    ]


@pytest.mark.parametrize("verb", ["cancel_all_orders", "exit_all_positions"])
async def test_emergency_sweep_rejection_is_not_reported_as_success(verb: str) -> None:
    adapter = _adapter(_FakeClient(place_status="error"))

    with pytest.raises(OrderRejectedByBroker):
        await getattr(adapter, verb)(_session(), _router_token=_ROUTER_TOKEN)


@pytest.mark.parametrize("verb", ["cancel_all_orders", "exit_all_positions"])
async def test_emergency_sweep_refuses_unsupported_scope_narrowing(verb: str) -> None:
    client = _FakeClient()
    adapter = _adapter(client)

    with pytest.raises(UnsupportedCapabilityError, match="scope"):
        await getattr(adapter, verb)(
            _session(),
            segment="NSE",
            _router_token=_ROUTER_TOKEN,
        )

    assert client.calls == []


async def test_reads_forward() -> None:
    a = _adapter(_FakeClient())
    pos = await a.positions(_session())
    assert pos == [{"symbol": "RELIANCE", "qty": 10}]
    assert await a.funds(_session()) == {"available": 50000.0}


async def test_quotes_split_symbols() -> None:
    client = _FakeClient()
    a = _adapter(client)
    await a.quotes(_session(), ["NFO:NIFTY", "RELIANCE"])
    _, payload = client.calls[-1]
    assert payload == [{"symbol": "NIFTY", "exchange": "NFO"}, {"symbol": "RELIANCE", "exchange": "NSE"}]


async def test_streaming_unsupported() -> None:
    a = _adapter(_FakeClient())
    with pytest.raises(UnsupportedCapabilityError):
        a.stream(_session())
    with pytest.raises(UnsupportedCapabilityError):
        await a.subscribe(_session(), ["X"])


_ORDER_NUMERIC_FIELDS = ("quantity", "filled_quantity", "price", "trigger_price", "average_price")


@pytest.mark.parametrize("blank", [None, "", "  "])
def test_order_reconciliation_mapping_omits_absent_and_blank_numeric_evidence(blank: object) -> None:
    mapped = OpenAlgoAdapter._reconciliation_rows(  # noqa: SLF001 - focused adapter normaliser contract
        [{field: blank for field in _ORDER_NUMERIC_FIELDS}],
        book="order-book",
    )[0]

    assert set(_ORDER_NUMERIC_FIELDS).isdisjoint(mapped)


def test_order_reconciliation_mapping_preserves_explicit_zero_and_malformed_numeric_evidence() -> None:
    zero = OpenAlgoAdapter._reconciliation_rows(  # noqa: SLF001 - focused adapter normaliser contract
        [{field: 0 for field in _ORDER_NUMERIC_FIELDS}],
        book="order-book",
    )[0]
    malformed = OpenAlgoAdapter._reconciliation_rows(  # noqa: SLF001 - focused adapter normaliser contract
        [{field: "not-a-number" for field in _ORDER_NUMERIC_FIELDS}],
        book="order-book",
    )[0]

    assert all(field in zero and zero[field] == 0 for field in _ORDER_NUMERIC_FIELDS)
    assert all(malformed[field] == "not-a-number" for field in _ORDER_NUMERIC_FIELDS)


async def test_reconcile_uses_canonical_reads_and_injected_local_state() -> None:
    orders = [
        {
            "orderid": "OID-1",
            "status": "open",
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "product": "CNC",
            "action": "BUY",
            "quantity": "2",
            "filled_quantity": "0",
            "price": "2500",
            "trigger_price": "0",
            "pricetype": "LIMIT",
            "average_price": "0",
        }
    ]
    positions = [Position(symbol="NIFTY", exchange="NFO", product="NRML", quantity="3")]
    holdings = [Holding(symbol="RELIANCE", exchange="NSE", product="CNC", quantity="2")]
    local_state = LocalStateSnapshot(
        orders=(dict(orders[0]),),
        positions=(positions[0].model_dump(),),
        holdings=(holdings[0].model_dump(),),
    )
    provider_sessions: list[Session] = []

    def local_state_provider(session: Session) -> LocalStateSnapshot:
        provider_sessions.append(session)
        return local_state

    client = _FakeClient(orders=orders, positions=positions, holdings=holdings)
    adapter = OpenAlgoAdapter(default_client=client, local_state_provider=local_state_provider)

    report = await adapter.reconcile(_session())

    assert report.clean
    assert report.adapter_id == "openalgo"
    assert report.account_id == "dhan"
    expected_order = dict(orders[0])
    expected_order["price_type"] = expected_order.pop("pricetype")
    expected_order.update(
        variety="UNKNOWN",
        validity="UNKNOWN",
        strategy="UNKNOWN",
    )
    assert report.broker_orders == (expected_order,)
    assert report.broker_positions == (positions[0].model_dump(),)
    assert report.broker_holdings == (holdings[0].model_dump(),)
    assert provider_sessions == [_session()]
    assert client.calls == [("orderbook",), ("positionbook",), ("holdings",)]


async def test_reconcile_rejects_order_status_with_omitted_trigger_without_retaining_evidence() -> None:
    order = OrderStatus(
        orderid="OID-1",
        status="open",
        symbol="RELIANCE",
        exchange="NSE",
        product="CNC",
        action="BUY",
        quantity="2",
        filled_quantity="0",
        price="2500",
        pricetype="LIMIT",
        average_price="0",
    )

    report = await _adapter(_FakeClient(orders=[order], positions=[], holdings=[])).reconcile(_session())

    assert report.severity == SEVERITY_CRITICAL
    assert "missing trigger_price" in report.error
    assert report.broker_orders == report.broker_positions == report.broker_holdings == ()
    assert report._evidence_sha256 == ""  # noqa: SLF001 - error reports retain no private evidence


async def test_reconcile_returns_critical_report_on_read_failure() -> None:
    class ReadFailureClient(_FakeClient):
        async def positionbook(self):
            self.calls.append(("positionbook",))
            raise RuntimeError("position snapshot unavailable")

    client = ReadFailureClient(orders=[], positions=[], holdings=[])

    report = await _adapter(client).reconcile(_session())

    assert not report.clean
    assert report.severity == SEVERITY_CRITICAL
    assert report.error == "reconciliation failed (RuntimeError)"
    assert report.orders_diff == report.positions_diff == report.holdings_diff == ()
    assert client.calls == [("orderbook",), ("positionbook",)]


async def test_reconcile_returns_critical_report_on_malformed_broker_row() -> None:
    client = _FakeClient(orders=[object()], positions=[], holdings=[])

    report = await _adapter(client).reconcile(_session())

    assert not report.clean
    assert report.severity == SEVERITY_CRITICAL
    assert report.error == "reconciliation failed (BrokerError)"
    assert report.orders_diff == report.positions_diff == report.holdings_diff == ()


async def test_reconcile_preserves_critical_report_on_broker_row_validation_failure() -> None:
    client = _FakeClient(
        orders=[{"status": "open", "quantity": "1", "filled_quantity": "0"}],
        positions=[],
        holdings=[],
    )

    report = await _adapter(client).reconcile(_session())

    assert not report.clean
    assert report.severity == SEVERITY_CRITICAL
    assert "missing order id" in report.error
    assert report.orders_diff == report.positions_diff == report.holdings_diff == ()


async def test_reconcile_returns_critical_report_when_local_state_read_fails() -> None:
    def failing_local_state_provider(_session: Session) -> LocalStateSnapshot:
        raise ValueError("local snapshot unavailable")

    client = _FakeClient(orders=[], positions=[], holdings=[])
    adapter = OpenAlgoAdapter(default_client=client, local_state_provider=failing_local_state_provider)

    report = await adapter.reconcile(_session())

    assert not report.clean
    assert report.severity == SEVERITY_CRITICAL
    assert report.error == "reconciliation failed (ValueError)"
    assert report.orders_diff == report.positions_diff == report.holdings_diff == ()
    assert client.calls == []


async def test_rate_limit_error_mapped() -> None:
    a = _adapter(_FakeClient(raise_exc=OpenAlgoRateLimitError("429")))
    with pytest.raises(RateLimitError):
        await a.place_order(_session(), _order(), _router_token=_ROUTER_TOKEN)


@pytest.mark.parametrize("variety", ["gtt", "bracket", "cover", "iceberg", "conditional"])
async def test_place_order_non_regular_variety_refused(variety: str) -> None:
    """Audit HIGH: a forever/GTT (or bracket/cover/iceberg/conditional) place
    against the bridge must raise UnsupportedCapabilityError, NOT silently
    downgrade to an immediate regular order. The OpenAlgo client is never
    called — nothing is placed."""
    client = _FakeClient()
    a = _adapter(client)
    order = SimpleNamespace(
        symbol="RELIANCE", exchange="NSE", action="BUY", quantity=10,
        pricetype="LIMIT", variety=variety, trigger_price="2890",
    )
    with pytest.raises(UnsupportedCapabilityError, match=variety):
        await a.place_order(_session(), order, _router_token=_ROUTER_TOKEN)
    assert client.calls == []  # the honesty guard short-circuits ahead of OpenAlgo


@pytest.mark.parametrize("variety", ["", "regular", "REGULAR"])
async def test_place_order_regular_variety_still_forwards(variety: str) -> None:
    """A regular (or unset) variety keeps the legacy forward — no regression."""
    client = _FakeClient()
    a = _adapter(client)
    order = SimpleNamespace(
        symbol="RELIANCE", exchange="NSE", action="BUY", quantity=10,
        pricetype="MARKET", variety=variety,
    )
    oid = await a.place_order(_session(), order, _router_token=_ROUTER_TOKEN)
    assert oid == "OID-1"
    assert client.calls[0][0] == "place_order"


async def test_emergency_planner_reports_quiet_only_after_reading_both_books() -> None:
    client = _FakeClient(orders=[], positions=[])

    plan = await _adapter(client).plan_emergency_reduction(
        _session(),
        policy=L5_EMERGENCY_POLICY,
        protected_order_ids=frozenset(),
        protected_exit_order_ids=frozenset(),
        protected_exit_tags=frozenset(),
    )

    assert plan.writes == ()
    assert plan.pending_verbs == frozenset()
    assert client.calls == [("orderbook",), ("positionbook",)]


async def test_emergency_planner_bounds_concrete_cancellations_before_position_exits() -> None:
    orders = [
        {"orderid": f"OID-{index:02d}", "order_status": "open"}
        for index in range(12)
    ]
    positions = [
        {
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "product": "MIS",
            "quantity": "5",
        }
    ]

    plan = await _adapter(_FakeClient(orders=orders, positions=positions)).plan_emergency_reduction(
        _session(),
        policy=L5_EMERGENCY_POLICY,
        protected_order_ids=frozenset(),
        protected_exit_order_ids=frozenset(),
        protected_exit_tags=frozenset(),
    )

    assert plan.pending_verbs == frozenset({"cancel_all_orders", "exit_all_positions"})
    assert len(plan.writes) == 10
    assert all(write.parent_verb == "cancel_all_orders" for write in plan.writes)
    assert all(write.verb == "cancel_order" for write in plan.writes)
    assert [write.payload["order_id"] for write in plan.writes] == [
        f"OID-{index:02d}" for index in range(10)
    ]


async def test_emergency_planner_builds_exact_reducing_write_from_signed_position() -> None:
    client = _FakeClient(
        orders=[],
        positions=[
            {
                "symbol": "NIFTY26JUL25000CE",
                "exchange": "NFO",
                "product": "NRML",
                "quantity": "-7",
            }
        ],
    )

    plan = await _adapter(client).plan_emergency_reduction(
        _session(),
        policy=MTM_EMERGENCY_POLICY,
        protected_order_ids=frozenset(),
        protected_exit_order_ids=frozenset(),
        protected_exit_tags=frozenset(),
    )

    assert plan.pending_verbs == frozenset({"exit_all_positions"})
    assert len(plan.writes) == 1
    write = plan.writes[0]
    assert write.parent_verb == "exit_all_positions"
    assert write.verb == "place_reducing_order"
    assert write.payload == {
        "_op": "place_reducing_order",
        "symbol": "NIFTY26JUL25000CE",
        "exchange": "NFO",
        "product": "NRML",
        "quantity": "7",
        "expected_position_quantity": "-7",
        "action": "BUY",
        "pricetype": "MARKET",
        "price": "0",
        "trigger_price": "0",
        "variety": "regular",
        "emergency_tag": write.payload["emergency_tag"],
    }
    assert str(write.payload["emergency_tag"]).startswith("FTE-OA-")


@pytest.mark.parametrize(
    "row",
    [
        {"orderid": "", "order_status": "open"},
        {"orderid": " PADDED ", "order_status": "open"},
        {"orderid": "OID-1", "order_status": ""},
        object(),
    ],
)
async def test_emergency_planner_fails_closed_on_malformed_active_order_row(row: object) -> None:
    client = _FakeClient(orders=[row], positions=[])

    with pytest.raises(BrokerError, match="order-book row|order id|status"):
        await _adapter(client).plan_emergency_reduction(
            _session(),
            policy=L5_EMERGENCY_POLICY,
            protected_order_ids=frozenset(),
            protected_exit_order_ids=frozenset(),
            protected_exit_tags=frozenset(),
        )

    assert all(call[0] not in {"cancel_order", "cancel_all_orders", "close_position", "place_order"} for call in client.calls)


@pytest.mark.parametrize("quantity", [None, "", "unknown", "1.5", float("inf")])
async def test_emergency_planner_fails_closed_on_unknown_position_quantity(quantity: object) -> None:
    client = _FakeClient(
        orders=[],
        positions=[
            {
                "symbol": "RELIANCE",
                "exchange": "NSE",
                "product": "MIS",
                "quantity": quantity,
            }
        ],
    )

    with pytest.raises(BrokerError, match="position quantity"):
        await _adapter(client).plan_emergency_reduction(
            _session(),
            policy=MTM_EMERGENCY_POLICY,
            protected_order_ids=frozenset(),
            protected_exit_order_ids=frozenset(),
            protected_exit_tags=frozenset(),
        )


async def test_emergency_planner_does_not_repeat_protected_cancellation() -> None:
    client = _FakeClient(
        orders=[{"orderid": "OID-PROTECTED", "order_status": "open"}],
        positions=[],
    )

    plan = await _adapter(client).plan_emergency_reduction(
        _session(),
        policy=L5_EMERGENCY_POLICY,
        protected_order_ids=frozenset({"OID-PROTECTED"}),
        protected_exit_order_ids=frozenset(),
        protected_exit_tags=frozenset(),
    )

    assert plan.pending_verbs == frozenset({"cancel_all_orders"})
    assert plan.writes == ()


async def test_emergency_planner_does_not_repeat_protected_exit_by_id_or_tag() -> None:
    position = {
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "product": "MIS",
        "quantity": "5",
    }
    seed = await _adapter(_FakeClient(orders=[], positions=[position])).plan_emergency_reduction(
        _session(),
        policy=MTM_EMERGENCY_POLICY,
        protected_order_ids=frozenset(),
        protected_exit_order_ids=frozenset(),
        protected_exit_tags=frozenset(),
    )
    tag = str(seed.writes[0].payload["emergency_tag"])
    protected_exit = {
        "orderid": "EXIT-1",
        "order_status": "open",
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "product": "MIS",
        "action": "SELL",
        "quantity": "5",
        "strategy": tag,
    }

    by_id = await _adapter(_FakeClient(orders=[protected_exit], positions=[position])).plan_emergency_reduction(
        _session(),
        policy=MTM_EMERGENCY_POLICY,
        protected_order_ids=frozenset(),
        protected_exit_order_ids=frozenset({"EXIT-1"}),
        protected_exit_tags=frozenset(),
    )
    by_tag = await _adapter(_FakeClient(orders=[], positions=[position])).plan_emergency_reduction(
        _session(),
        policy=MTM_EMERGENCY_POLICY,
        protected_order_ids=frozenset(),
        protected_exit_order_ids=frozenset(),
        protected_exit_tags=frozenset({tag}),
    )

    assert by_id.pending_verbs == by_tag.pending_verbs == frozenset({"exit_all_positions"})
    assert by_id.writes == by_tag.writes == ()


@pytest.mark.parametrize(
    "remaining_fields",
    [
        {},
        {"remaining_quantity": "3"},
        {"pending_quantity": "3"},
        {"unfilled_quantity": "3"},
    ],
)
async def test_emergency_planner_preserves_protected_partially_filled_residual_exit(
    remaining_fields: dict[str, str],
) -> None:
    position = {
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "product": "MIS",
        "quantity": "3",
    }
    protected_exit = {
        "orderid": "EXIT-PARTIAL",
        "order_status": "open",
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "product": "MIS",
        "action": "SELL",
        "quantity": "5",
        "filled_quantity": "2",
        **remaining_fields,
    }

    plan = await _adapter(
        _FakeClient(orders=[protected_exit], positions=[position])
    ).plan_emergency_reduction(
        _session(),
        policy=MTM_EMERGENCY_POLICY,
        protected_order_ids=frozenset(),
        protected_exit_order_ids=frozenset({"EXIT-PARTIAL"}),
        protected_exit_tags=frozenset(),
    )

    assert plan.pending_verbs == frozenset({"exit_all_positions"})
    assert plan.writes == ()


async def test_emergency_planner_never_cancels_a_conflicting_protected_exit_id() -> None:
    position = {
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "product": "MIS",
        "quantity": "3",
    }
    conflicting_exit = {
        "orderid": "EXIT-PROTECTED-CONFLICT",
        "order_status": "open",
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "product": "MIS",
        "action": "SELL",
        "quantity": "5",
        "filled_quantity": "0",
    }

    plan = await _adapter(
        _FakeClient(orders=[conflicting_exit], positions=[position])
    ).plan_emergency_reduction(
        _session(),
        policy=MTM_EMERGENCY_POLICY,
        protected_order_ids=frozenset(),
        protected_exit_order_ids=frozenset({"EXIT-PROTECTED-CONFLICT"}),
        protected_exit_tags=frozenset(),
    )

    assert plan.pending_verbs == frozenset({"exit_all_positions"})
    assert plan.writes == ()


async def test_emergency_planner_does_not_cancel_an_unidentifiable_response_lost_exit() -> None:
    position = {
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "product": "MIS",
        "quantity": "5",
    }
    seed = await _adapter(_FakeClient(orders=[], positions=[position])).plan_emergency_reduction(
        _session(),
        policy=MTM_EMERGENCY_POLICY,
        protected_order_ids=frozenset(),
        protected_exit_order_ids=frozenset(),
        protected_exit_tags=frozenset(),
    )
    tag = str(seed.writes[0].payload["emergency_tag"])
    active_order_without_strategy = {
        "orderid": "UNKNOWN-EXIT",
        "order_status": "open",
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "product": "MIS",
        "action": "SELL",
        "quantity": "5",
    }

    plan = await _adapter(
        _FakeClient(orders=[active_order_without_strategy], positions=[position])
    ).plan_emergency_reduction(
        _session(),
        policy=MTM_EMERGENCY_POLICY,
        protected_order_ids=frozenset(),
        protected_exit_order_ids=frozenset(),
        protected_exit_tags=frozenset({tag}),
    )

    assert plan.pending_verbs == frozenset({"cancel_all_orders", "exit_all_positions"})
    assert plan.writes == ()


async def test_missing_protected_exit_id_settles_when_both_books_are_quiet() -> None:
    plan = await _adapter(_FakeClient(orders=[], positions=[])).plan_emergency_reduction(
        _session(),
        policy=MTM_EMERGENCY_POLICY,
        protected_order_ids=frozenset(),
        protected_exit_order_ids=frozenset({"EXIT-FILLED"}),
        protected_exit_tags=frozenset(),
    )

    assert plan.pending_verbs == frozenset()
    assert plan.writes == ()


async def test_emergency_planner_does_not_repeat_terminal_protected_exit_with_open_position() -> None:
    position = {
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "product": "MIS",
        "quantity": "5",
    }
    client = _FakeClient(
        orders=[{"orderid": "EXIT-TERMINAL", "order_status": "complete"}],
        positions=[position],
    )

    plan = await _adapter(client).plan_emergency_reduction(
        _session(),
        policy=MTM_EMERGENCY_POLICY,
        protected_order_ids=frozenset(),
        protected_exit_order_ids=frozenset({"EXIT-TERMINAL"}),
        protected_exit_tags=frozenset(),
    )

    assert plan.pending_verbs == frozenset({"exit_all_positions"})
    assert plan.writes == ()


async def test_place_reducing_order_revalidates_position_and_requires_router_token() -> None:
    position = {
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "product": "MIS",
        "quantity": "5",
    }
    client = _FakeClient(orders=[], positions=[position])
    adapter = _adapter(client)
    plan = await adapter.plan_emergency_reduction(
        _session(),
        policy=MTM_EMERGENCY_POLICY,
        protected_order_ids=frozenset(),
        protected_exit_order_ids=frozenset(),
        protected_exit_tags=frozenset(),
    )
    payload = dict(plan.writes[0].payload)
    client.calls.clear()

    with pytest.raises(SafetyBypassError, match="outside BrokerRouter"):
        await adapter.place_reducing_order(_session(), payload)
    assert client.calls == []

    order_id = await adapter.place_reducing_order(
        _session(),
        payload,
        _router_token=_ROUTER_TOKEN,
    )

    assert order_id == "OID-1"
    assert client.calls[0] == ("positionbook",)
    placed = client.calls[1][1]
    assert placed.action.value == "SELL"
    assert placed.quantity == "5"
    assert placed.strategy == payload["emergency_tag"]


def test_emergency_dispatcher_uses_openalgo_planned_readback_not_bulk_sweeps() -> None:
    import asyncio

    from flinttrade_engine.request_context import RequestContext
    from flinttrade_engine.safety import (
        EmergencyBrokerTarget,
        GatedEmergencyBrokerDispatcher,
        SafetyGate,
        set_safety_gate_secret,
    )
    from flinttrade_gateway.router import BrokerRouter

    class ReadbackClient(_FakeClient):
        def __init__(self) -> None:
            super().__init__(
                orders=[{"orderid": "OPEN-1", "order_status": "open"}],
                positions=[
                    {
                        "symbol": "RELIANCE",
                        "exchange": "NSE",
                        "product": "MIS",
                        "quantity": "3",
                    }
                ],
            )

        async def cancel_order(self, order_id, strategy="Flint"):
            response = await super().cancel_order(order_id, strategy)
            self.order_rows = []
            return response

        async def place_order(self, order):
            response = await super().place_order(order)
            self.position_rows = []
            self.order_rows = [
                {
                    "orderid": response.orderid,
                    "order_status": "complete",
                    "symbol": order.symbol,
                    "exchange": order.exchange.value,
                    "product": order.product.value,
                    "action": order.action.value,
                    "quantity": order.quantity,
                    "strategy": order.strategy,
                }
            ]
            return response

    client = ReadbackClient()
    adapter = _adapter(client)
    safety_gate = SafetyGate()
    set_safety_gate_secret(b"openalgo-planned-emergency-secret-0123456789")
    router = BrokerRouter(
        {"openalgo": adapter},
        lambda _request_ctx, _adapter_id, _account_id: _session(),
        consume_gate=safety_gate.consume,
    )
    request_ctx = RequestContext(
        jti="openalgo-planned-emergency",
        actor_type="human",
        actor_id="operator",
        mode="live",
        selector="openalgo:dhan",
    )
    dispatcher = GatedEmergencyBrokerDispatcher(
        router_provider=lambda: router,
        target_provider=lambda: EmergencyBrokerTarget(
            request_ctx=request_ctx,
            adapter_id="openalgo",
            account_id="dhan",
        ),
        run_awaitable=asyncio.run,
        planned_readback_attempts=6,
        planned_quiet_reads=2,
        planned_readback_delay_seconds=0,
    )

    result = dispatcher.dispatch(L5_EMERGENCY_POLICY, reason="OpenAlgo emergency")

    assert result.complete
    assert [call[0] for call in client.calls].count("cancel_order") == 1
    assert [call[0] for call in client.calls].count("place_order") == 1
    assert not {"cancel_all_orders", "close_position"}.intersection(call[0] for call in client.calls)
