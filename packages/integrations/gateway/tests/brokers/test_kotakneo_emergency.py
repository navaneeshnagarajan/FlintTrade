"""Contract tests for Kotak Neo's broker-authoritative emergency planner.

All broker data and credentials in this module are synthetic. The tests never
construct the live SDK facade or make a network request.
"""

from __future__ import annotations

import asyncio
import hashlib
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

import pytest

from flinttrade_core.exceptions import BrokerError
from flinttrade_engine.request_context import RequestContext
from flinttrade_engine.safety import (
    EMERGENCY_INTENT_SOURCE,
    EmergencyBrokerTarget,
    EmergencyWritePolicy,
    GatedEmergencyBrokerDispatcher,
    SafetyBypassError,
    SafetyContext,
    SafetyGate,
    set_safety_gate_secret,
)
from flinttrade_gateway.brokers._base import ROUTER_TOKEN as _ROUTER_TOKEN
from flinttrade_gateway.brokers._base import Session
from flinttrade_gateway.brokers.kotakneo import KotakNeoAdapter
from flinttrade_gateway.brokers.kotakneo_mapping import KotakNeoMappingError
from flinttrade_gateway.router import BrokerRouter

pytestmark = pytest.mark.unit

_CANCEL_POLICY = EmergencyWritePolicy(
    name="kotakneo_cancel_test",
    verbs=("cancel_all_orders",),
)
_EXIT_POLICY = EmergencyWritePolicy(
    name="kotakneo_exit_test",
    verbs=("exit_all_positions",),
)
_FLATTEN_POLICY = EmergencyWritePolicy(
    name="kotakneo_flatten_test",
    verbs=("cancel_all_orders", "exit_all_positions"),
)
_UNSET = object()


@pytest.fixture(autouse=True)
def _bind_safety_secret() -> None:
    set_safety_gate_secret(b"0123456789abcdef0123456789abcdef")


def _book(rows: list[Any], *, status: str = "Ok") -> dict[str, Any]:
    return {"stat": status, "stCode": 200, "data": deepcopy(rows)}


def _order_row(
    order_id: str = "OPEN-1",
    *,
    status: str = "open",
    symbol: str = "AXISBANK-EQ",
    exchange_segment: str = "nse_cm",
    product: str = "CNC",
    side: str = "B",
    quantity: int = 5,
    filled_quantity: int | None = 0,
    generation: str | None = "",
    tag: str = "",
    price_type: str = "L",
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "nOrdNo": order_id,
        "ordSt": status,
        "trdSym": symbol,
        "exSeg": exchange_segment,
        "prod": product,
        "trnsTp": side,
        "qty": str(quantity),
        "prcTp": price_type,
        "GuiOrdId": tag,
    }
    if filled_quantity is not None:
        row["fldQty"] = str(filled_quantity)
    if generation is not None:
        row["ordGenTp"] = generation
    return row


def _position_row(
    *,
    symbol: str = "AXISBANK-EQ",
    exchange_segment: str = "nse_cm",
    product: str = "CNC",
    quantity: int = 5,
    lot_size: int = 1,
    carry_buy: int = 0,
    carry_sell: int = 0,
    filled_buy: int | None = None,
    filled_sell: int | None = None,
    open_position: str = "true",
    square_off: str = "Y",
) -> dict[str, Any]:
    if filled_buy is None:
        filled_buy = max(quantity, 0)
    if filled_sell is None:
        filled_sell = max(-quantity, 0)
    return {
        "trdSym": symbol,
        "exSeg": exchange_segment,
        "prod": product,
        "qty": str(quantity),
        "lotSz": str(lot_size),
        "cfBuyQty": str(carry_buy),
        "cfSellQty": str(carry_sell),
        "flBuyQty": str(filled_buy),
        "flSellQty": str(filled_sell),
        "posFlg": open_position,
        "sqrFlg": square_off,
    }


class FakeKotakNeoEmergencyClient:
    """Stateful, synchronous facade matching the adapter's injected client."""

    def __init__(
        self,
        *,
        orders: list[dict[str, Any]] | None = None,
        positions: list[dict[str, Any]] | None = None,
    ) -> None:
        self.order_rows = deepcopy(orders or [])
        self.position_rows = deepcopy(positions or [])
        self.order_response: Any = _UNSET
        self.trade_response: Any = _UNSET
        self.position_response: Any = _UNSET
        self.cancel_response: Any = _UNSET
        self.place_response: Any = _UNSET
        self.mutate_on_cancel = True
        self.calls: list[tuple[Any, ...]] = []

    def order_book(self) -> Any:
        self.calls.append(("order_book",))
        if self.order_response is not _UNSET:
            return deepcopy(self.order_response)
        return _book(self.order_rows)

    def positions(self) -> Any:
        self.calls.append(("positions",))
        if self.position_response is not _UNSET:
            return deepcopy(self.position_response)
        return _book(self.position_rows)

    def trade_book(self) -> Any:
        self.calls.append(("trade_book",))
        if self.trade_response is not _UNSET:
            return deepcopy(self.trade_response)
        rows = []
        for row in self.order_rows:
            filled = int(str(row.get("fldQty") or "0"))
            if filled:
                rows.append(
                    {
                        "nOrdNo": str(row["nOrdNo"]),
                        "flId": f"FILL-{row['nOrdNo']}",
                        "fldQty": str(filled),
                        "rptTp": "fill",
                    }
                )
        return _book(rows)

    def _cancel(
        self,
        family: str,
        order_id: str,
        amo: str,
        is_verify: bool,
        trading_symbol: str | None,
    ) -> Any:
        self.calls.append((family, order_id, amo, is_verify, trading_symbol))
        if self.mutate_on_cancel:
            self.order_rows = [row for row in self.order_rows if row.get("nOrdNo") != order_id]
        if self.cancel_response is not _UNSET:
            return deepcopy(self.cancel_response)
        return {"stat": "Ok", "stCode": 200, "nOrdNo": order_id}

    def cancel_order(
        self,
        order_id: str,
        amo: str = "NO",
        is_verify: bool = False,
        trading_symbol: str | None = None,
    ) -> Any:
        return self._cancel("cancel_order", order_id, amo, is_verify, trading_symbol)

    def cancel_bracket_order(
        self,
        order_id: str,
        amo: str = "NO",
        is_verify: bool = False,
        trading_symbol: str | None = None,
    ) -> Any:
        return self._cancel("cancel_bracket_order", order_id, amo, is_verify, trading_symbol)

    def cancel_cover_order(
        self,
        order_id: str,
        amo: str = "NO",
        is_verify: bool = False,
        trading_symbol: str | None = None,
    ) -> Any:
        return self._cancel("cancel_cover_order", order_id, amo, is_verify, trading_symbol)

    def place_order(self, params: dict[str, Any]) -> Any:
        self.calls.append(("place_order", deepcopy(params)))
        if self.place_response is not _UNSET:
            return deepcopy(self.place_response)
        return {"stat": "Ok", "stCode": 200, "nOrdNo": "EXIT-NEW-1"}


def _adapter(client: FakeKotakNeoEmergencyClient) -> KotakNeoAdapter:
    return KotakNeoAdapter(client_factory=lambda _session: client)


def _session() -> Session:
    return Session(
        access_token="FAKE-KOTAK-TOKEN",
        expires_at=datetime.now(tz=timezone.utc).timestamp() + 3600,
        account_id="fake-account",
        adapter_id="kotakneo",
    )


async def _plan(
    adapter: KotakNeoAdapter,
    session: Session,
    *,
    policy: EmergencyWritePolicy = _FLATTEN_POLICY,
    protected_order_ids: frozenset[str] = frozenset(),
    protected_exit_order_ids: frozenset[str] = frozenset(),
    protected_exit_tags: frozenset[str] = frozenset(),
    unidentified_exit_inflight: bool = False,
):
    return await adapter.plan_emergency_reduction(
        session,
        policy=policy,
        protected_order_ids=protected_order_ids,
        protected_exit_order_ids=protected_exit_order_ids,
        protected_exit_tags=protected_exit_tags,
        unidentified_exit_inflight=unidentified_exit_inflight,
    )


@pytest.mark.asyncio
async def test_explicit_success_empty_books_produce_a_quiet_plan() -> None:
    client = FakeKotakNeoEmergencyClient()
    adapter = _adapter(client)

    plan = await _plan(adapter, _session())

    assert plan.writes == ()
    assert plan.pending_verbs == frozenset()
    assert client.calls == [("order_book",), ("trade_book",), ("positions",)]


@pytest.mark.asyncio
async def test_pinned_lowercase_trade_and_position_success_envelopes_are_accepted() -> None:
    position = _position_row(quantity=5)
    client = FakeKotakNeoEmergencyClient()
    client.trade_response = _book([], status="ok")
    client.position_response = _book([position], status="ok")

    plan = await _plan(_adapter(client), _session(), policy=_EXIT_POLICY)

    assert len(plan.writes) == 1
    assert plan.writes[0].verb == "place_reducing_order"


@pytest.mark.asyncio
@pytest.mark.parametrize("book_name", ["order", "trade", "position"])
@pytest.mark.parametrize(
    "bad_envelope",
    [
        {"stCode": 200, "data": []},
        {"stat": "Not_Ok", "stCode": 200, "data": []},
        {"stat": "Ok", "data": []},
        {"stat": "Ok", "stCode": True, "data": []},
        {"stat": "Ok", "stCode": 200, "data": {}},
        {"stat": "Ok", "stCode": 200, "data": ["not-an-object"]},
    ],
    ids=[
        "missing-stat",
        "negative-stat",
        "missing-code",
        "boolean-code",
        "non-list-data",
        "non-object-row",
    ],
)
async def test_emergency_books_require_explicit_success_and_object_rows(
    book_name: str,
    bad_envelope: dict[str, Any],
) -> None:
    client = FakeKotakNeoEmergencyClient()
    policy = _CANCEL_POLICY
    if book_name == "order":
        client.order_response = bad_envelope
    elif book_name == "trade":
        client.trade_response = bad_envelope
        policy = _EXIT_POLICY
    else:
        client.position_response = bad_envelope
        policy = _EXIT_POLICY
    adapter = _adapter(client)

    with pytest.raises(BrokerError):
        await _plan(adapter, _session(), policy=policy)

    assert not any(call[0].startswith("cancel") or call[0] == "place_order" for call in client.calls)


@pytest.mark.asyncio
async def test_planner_emits_exact_regular_amo_bracket_and_cover_cancellations() -> None:
    orders = [
        _order_row("01-REG", product="MIS", generation="NA"),
        _order_row(
            "02-AMO",
            status="after market order req received",
            product="CNC",
            generation="AMO",
            symbol="ITC-EQ",
        ),
        _order_row("03-BO", product="BO", generation="--"),
        _order_row("04-CO", product="CO", generation=""),
        _order_row("05-MTF", product="MTF", generation="NA", symbol="SBIN-EQ"),
    ]
    client = FakeKotakNeoEmergencyClient(orders=orders)
    adapter = _adapter(client)
    session = _session()

    plan = await _plan(adapter, session, policy=_CANCEL_POLICY)

    assert plan.pending_verbs == frozenset({"cancel_all_orders"})
    assert [(write.parent_verb, write.verb, dict(write.payload)) for write in plan.writes] == [
        (
            "cancel_all_orders",
            "cancel_order",
            {"_op": "cancel_order", "order_id": "01-REG", "variety": "regular", "amo": False},
        ),
        (
            "cancel_all_orders",
            "cancel_order",
            {
                "_op": "cancel_order",
                "order_id": "02-AMO",
                "variety": "amo",
                "amo": True,
            },
        ),
        (
            "cancel_all_orders",
            "cancel_order",
            {"_op": "cancel_order", "order_id": "03-BO", "variety": "bracket", "amo": False},
        ),
        (
            "cancel_all_orders",
            "cancel_order",
            {"_op": "cancel_order", "order_id": "04-CO", "variety": "cover", "amo": False},
        ),
        (
            "cancel_all_orders",
            "cancel_order",
            {"_op": "cancel_order", "order_id": "05-MTF", "variety": "regular", "amo": False},
        ),
    ]

    for write in plan.writes:
        extras = {key: write.payload[key] for key in ("variety", "amo", "trading_symbol") if key in write.payload}
        await adapter.cancel_order(
            session,
            str(write.payload["order_id"]),
            **extras,
            _router_token=_ROUTER_TOKEN,
        )

    assert [call for call in client.calls if call[0].startswith("cancel")] == [
        ("cancel_order", "01-REG", "NO", False, None),
        ("cancel_order", "02-AMO", "YES", False, None),
        ("cancel_bracket_order", "03-BO", "NO", False, None),
        ("cancel_cover_order", "04-CO", "NO", False, None),
        ("cancel_order", "05-MTF", "NO", False, None),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        {"stat": "Ok", "nOrdNo": "OPEN-1"},
        {"stat": "Not_Ok", "stCode": 200, "nOrdNo": "OPEN-1"},
        {"stat": "Ok", "stCode": 200, "nOrdNo": "OTHER-ORDER"},
    ],
    ids=["missing-code", "negative-status", "different-order"],
)
async def test_concrete_cancellation_requires_matching_explicit_success(response: dict[str, Any]) -> None:
    client = FakeKotakNeoEmergencyClient(orders=[_order_row()])
    client.cancel_response = response
    client.mutate_on_cancel = False
    adapter = _adapter(client)

    with pytest.raises(KotakNeoMappingError):
        await adapter.cancel_order(_session(), "OPEN-1", _router_token=_ROUTER_TOKEN)

    assert [call[0] for call in client.calls] == ["cancel_order"]


@pytest.mark.asyncio
async def test_protected_cancellation_stays_pending_without_replay() -> None:
    client = FakeKotakNeoEmergencyClient(orders=[_order_row("ACK-CANCEL-1")])

    plan = await _plan(
        _adapter(client),
        _session(),
        policy=_CANCEL_POLICY,
        protected_order_ids=frozenset({"ACK-CANCEL-1"}),
    )

    assert plan.pending_verbs == frozenset({"cancel_all_orders"})
    assert plan.writes == ()
    assert client.calls == [("order_book",)]


def _expected_exit_tag(position: dict[str, Any]) -> str:
    identity = "|".join(
        (
            str(position["trdSym"]),
            str(position["exSeg"]),
            str(position["prod"]),
            str(int(position["qty"])),
            str(int(position["lotSz"])),
            str(int(position["cfBuyQty"])),
            str(int(position["cfSellQty"])),
            str(int(position["flBuyQty"])),
            str(int(position["flSellQty"])),
        )
    )
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    return f"FTE-KN-{digest}"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "filled_quantity", "price_type", "expected_pending"),
    [
        ("open", 0, "MKT", frozenset({"cancel_all_orders", "exit_all_positions"})),
        ("open", 0, "L", frozenset({"cancel_all_orders", "exit_all_positions"})),
        ("complete", 5, "MKT", frozenset({"exit_all_positions"})),
        ("complete", 5, "L", frozenset({"exit_all_positions"})),
    ],
    ids=["active-market", "active-protected-limit", "completed-market", "completed-protected-limit"],
)
async def test_protected_exit_is_reconciled_without_replay(
    status: str,
    filled_quantity: int,
    price_type: str,
    expected_pending: frozenset[str],
) -> None:
    position = _position_row(quantity=5)
    tag = _expected_exit_tag(position)
    protected_id = "ACK-EXIT-1"
    client = FakeKotakNeoEmergencyClient(
        orders=[
            _order_row(
                protected_id,
                status=status,
                product="CNC",
                side="S",
                quantity=5,
                filled_quantity=filled_quantity,
                generation="",
                tag=tag,
                price_type=price_type,
            )
        ],
        positions=[position],
    )

    plan = await _plan(
        _adapter(client),
        _session(),
        policy=_FLATTEN_POLICY,
        protected_exit_order_ids=frozenset({protected_id}),
        protected_exit_tags=frozenset({tag}),
    )

    assert plan.pending_verbs == expected_pending
    assert plan.writes == ()
    assert not any(call[0].startswith("cancel") or call[0] == "place_order" for call in client.calls)


@pytest.mark.asyncio
async def test_partially_filled_protected_exit_reconstructs_the_original_episode() -> None:
    original = _position_row(quantity=10)
    current = _position_row(quantity=6, filled_buy=10, filled_sell=4)
    tag = _expected_exit_tag(original)
    client = FakeKotakNeoEmergencyClient(
        orders=[
            _order_row(
                "PARTIAL-EXIT",
                side="S",
                quantity=10,
                filled_quantity=4,
                tag=tag,
                price_type="MKT",
            )
        ],
        positions=[current],
    )
    client.trade_response = _book(
        [
            {"nOrdNo": "PARTIAL-EXIT", "flId": "FILL-PARTIAL-1", "fldQty": "1", "rptTp": "fill"},
            {"nOrdNo": "PARTIAL-EXIT", "flId": "FILL-PARTIAL-2", "fldQty": "3", "rptTp": "fill"},
        ]
    )

    plan = await _plan(
        _adapter(client),
        _session(),
        policy=_EXIT_POLICY,
        protected_exit_order_ids=frozenset({"PARTIAL-EXIT"}),
        protected_exit_tags=frozenset({tag}),
    )

    assert plan.pending_verbs == frozenset({"exit_all_positions"})
    assert plan.writes == ()


@pytest.mark.asyncio
async def test_completed_flat_exit_does_not_block_the_next_position_batch() -> None:
    completed_position = _position_row(quantity=5)
    completed_tag = _expected_exit_tag(completed_position)
    remaining_position = _position_row(symbol="ITC-EQ", quantity=3)
    client = FakeKotakNeoEmergencyClient(
        orders=[
            _order_row(
                "COMPLETED-EXIT",
                status="complete",
                side="S",
                quantity=5,
                filled_quantity=5,
                tag=completed_tag,
                price_type="MKT",
            )
        ],
        positions=[remaining_position],
    )

    plan = await _plan(
        _adapter(client),
        _session(),
        policy=_EXIT_POLICY,
        protected_exit_order_ids=frozenset({"COMPLETED-EXIT"}),
        protected_exit_tags=frozenset({completed_tag}),
    )

    assert len(plan.writes) == 1
    assert plan.writes[0].payload["symbol"] == "ITC-EQ"


@pytest.mark.asyncio
async def test_old_completed_emergency_tag_does_not_mask_a_reopened_position() -> None:
    prior = _position_row(quantity=5)
    current = _position_row(quantity=5, carry_buy=5, filled_buy=0)
    prior_tag = _expected_exit_tag(prior)
    current_tag = _expected_exit_tag(current)
    client = FakeKotakNeoEmergencyClient(
        orders=[
            _order_row(
                "OLD-EXIT",
                status="complete",
                side="S",
                quantity=5,
                filled_quantity=5,
                tag=prior_tag,
                price_type="MKT",
            )
        ],
        positions=[current],
    )

    plan = await _plan(_adapter(client), _session(), policy=_EXIT_POLICY)

    assert prior_tag != current_tag
    assert len(plan.writes) == 1
    assert plan.writes[0].payload["emergency_tag"] == current_tag


@pytest.mark.asyncio
async def test_missing_protected_exit_fill_evidence_fails_closed() -> None:
    position = _position_row(quantity=5)
    tag = _expected_exit_tag(position)
    client = FakeKotakNeoEmergencyClient(
        orders=[
            _order_row(
                "UNSETTLED-EXIT",
                product="CNC",
                side="S",
                quantity=5,
                filled_quantity=None,
                tag=tag,
                price_type="MKT",
            )
        ],
        positions=[position],
    )

    with pytest.raises(BrokerError, match="filled quantity"):
        await _plan(
            _adapter(client),
            _session(),
            protected_exit_order_ids=frozenset({"UNSETTLED-EXIT"}),
            protected_exit_tags=frozenset({tag}),
        )

    assert not any(call[0].startswith("cancel") or call[0] == "place_order" for call in client.calls)


@pytest.mark.asyncio
async def test_missing_protected_exit_evidence_keeps_exit_pending_without_replay() -> None:
    position = _position_row(quantity=5)
    client = FakeKotakNeoEmergencyClient(positions=[position])

    plan = await _plan(
        _adapter(client),
        _session(),
        policy=_EXIT_POLICY,
        protected_exit_order_ids=frozenset({"MISSING-EXIT"}),
        protected_exit_tags=frozenset({_expected_exit_tag(position)}),
    )

    assert plan.pending_verbs == frozenset({"exit_all_positions"})
    assert plan.writes == ()
    assert not any(call[0] == "place_order" for call in client.calls)


@pytest.mark.asyncio
async def test_missing_protected_tag_blocks_only_its_matching_position() -> None:
    blocked = _position_row(quantity=5)
    independent = _position_row(symbol="ITC-EQ", quantity=3)
    client = FakeKotakNeoEmergencyClient(positions=[blocked, independent])

    plan = await _plan(
        _adapter(client),
        _session(),
        policy=_EXIT_POLICY,
        protected_exit_tags=frozenset({_expected_exit_tag(blocked)}),
    )

    assert len(plan.writes) == 1
    assert plan.writes[0].payload["symbol"] == "ITC-EQ"
    assert plan.pending_verbs == frozenset({"exit_all_positions"})


@pytest.mark.asyncio
@pytest.mark.parametrize("duplicate_book", ["order", "position"])
async def test_duplicate_broker_identities_fail_closed(duplicate_book: str) -> None:
    client = FakeKotakNeoEmergencyClient()
    policy = _CANCEL_POLICY
    if duplicate_book == "order":
        client.order_rows = [_order_row("DUPLICATE"), _order_row("DUPLICATE")]
    else:
        row = _position_row(quantity=5)
        client.position_rows = [row, deepcopy(row)]
        policy = _EXIT_POLICY

    with pytest.raises(BrokerError, match="duplicate"):
        await _plan(_adapter(client), _session(), policy=policy)

    assert not any(call[0].startswith("cancel") or call[0] == "place_order" for call in client.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "row",
    [
        _order_row(generation=None),
        _order_row(status="complete", filled_quantity=5, generation=None),
        _order_row(status="traded", filled_quantity=5, generation=None),
        _order_row(generation="UNKNOWN"),
        _order_row(exchange_segment="unknown_segment"),
        _order_row(status="broker-private-state"),
        _order_row(status="after market order req received", generation="NA"),
        _order_row(status="after market order req received", generation="--"),
        _order_row(status="after market order req received", generation=""),
        {**_order_row(), "nOrdNo": 123},
        {key: value for key, value in _order_row().items() if key != "prcTp"},
    ],
    ids=[
        "missing-amo-discriminator",
        "completed-missing-amo-discriminator",
        "traded-missing-amo-discriminator",
        "unsupported-generation",
        "unsupported-exchange",
        "unknown-status",
        "contradictory-amo-status-na",
        "contradictory-amo-status-dashes",
        "contradictory-amo-status-blank",
        "non-string-order-id",
        "missing-order-type",
    ],
)
async def test_malformed_or_ambiguous_active_order_rows_fail_closed(row: dict[str, Any]) -> None:
    client = FakeKotakNeoEmergencyClient(orders=[row])

    with pytest.raises(BrokerError):
        await _plan(_adapter(client), _session(), policy=_CANCEL_POLICY)

    assert not any(call[0].startswith("cancel") for call in client.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "position",
    [
        _position_row(quantity=5, lot_size=2),
        _position_row(quantity=5, product="MTF"),
        _position_row(quantity=5, product="INTRADAY"),
        _position_row(quantity=5, product="BO"),
        _position_row(quantity=5, product="CO"),
        {key: value for key, value in _position_row(quantity=5).items() if key != "flBuyQty"},
    ],
    ids=[
        "fractional-lot",
        "unsupported-mtf-position",
        "unsupported-intraday-position",
        "unsupported-bracket-position",
        "unsupported-cover-position",
        "incomplete-accounting",
    ],
)
async def test_malformed_position_rows_fail_closed(position: dict[str, Any]) -> None:
    client = FakeKotakNeoEmergencyClient(positions=[position])

    with pytest.raises(BrokerError):
        await _plan(_adapter(client), _session(), policy=_EXIT_POLICY)

    assert not any(call[0] == "place_order" for call in client.calls)


@pytest.mark.asyncio
async def test_cumulative_position_accounting_overrides_zero_raw_quantity_and_blank_flags() -> None:
    position = _position_row(quantity=0, filled_buy=5, filled_sell=0, open_position="")
    position.pop("sqrFlg")
    client = FakeKotakNeoEmergencyClient(positions=[position])

    plan = await _plan(_adapter(client), _session(), policy=_EXIT_POLICY)

    assert len(plan.writes) == 1
    assert plan.writes[0].payload["expected_position_quantity"] == "5"
    assert plan.writes[0].payload["quantity"] == "5"


@pytest.mark.asyncio
async def test_order_and_trade_fill_disagreement_fails_closed() -> None:
    position = _position_row(quantity=4, filled_buy=5, filled_sell=1)
    client = FakeKotakNeoEmergencyClient(
        orders=[_order_row("PARTIAL", side="S", quantity=5, filled_quantity=1)],
        positions=[position],
    )
    client.trade_response = _book([])

    with pytest.raises(BrokerError, match="disagree on fills"):
        await _plan(_adapter(client), _session(), policy=_EXIT_POLICY)


@pytest.mark.asyncio
async def test_duplicate_trade_fill_identity_fails_closed() -> None:
    fill = {"nOrdNo": "PARTIAL", "flId": "FILL-1", "fldQty": "1", "rptTp": "fill"}
    client = FakeKotakNeoEmergencyClient(
        orders=[_order_row("PARTIAL", side="S", quantity=5, filled_quantity=2)],
        positions=[_position_row(quantity=3, filled_buy=5, filled_sell=2)],
    )
    client.trade_response = _book([fill, deepcopy(fill)])

    with pytest.raises(BrokerError, match="duplicate fill id"):
        await _plan(_adapter(client), _session(), policy=_EXIT_POLICY)


@pytest.mark.asyncio
async def test_non_string_trade_fill_identifier_fails_closed() -> None:
    client = FakeKotakNeoEmergencyClient(
        orders=[_order_row("PARTIAL", side="S", quantity=5, filled_quantity=1)],
        positions=[_position_row(quantity=4, filled_buy=5, filled_sell=1)],
    )
    client.trade_response = _book(
        [{"nOrdNo": "PARTIAL", "flId": 1, "fldQty": "1", "rptTp": "fill"}]
    )

    with pytest.raises(BrokerError, match="trade fill id is not canonical"):
        await _plan(_adapter(client), _session(), policy=_EXIT_POLICY)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("price_type", "generation", "product"),
    [
        ("SL", "", "CNC"),
        ("SL-M", "", "CNC"),
        ("MKT", "AMO", "CNC"),
        ("MKT", "", "BO"),
        ("MKT", "", "CO"),
    ],
    ids=["stop-limit", "stop-market", "amo", "bracket", "cover"],
)
async def test_noncanonical_protected_exit_shape_is_cancelled_instead_of_trusted(
    price_type: str,
    generation: str,
    product: str,
) -> None:
    position = _position_row(quantity=5)
    tag = _expected_exit_tag(position)
    client = FakeKotakNeoEmergencyClient(
        orders=[
            _order_row(
                "STOP-EXIT",
                side="S",
                quantity=5,
                filled_quantity=0,
                tag=tag,
                price_type=price_type,
                generation=generation,
                product=product,
            )
        ],
        positions=[position],
    )

    plan = await _plan(
        _adapter(client),
        _session(),
        policy=_EXIT_POLICY,
        protected_exit_order_ids=frozenset({"STOP-EXIT"}),
        protected_exit_tags=frozenset({tag}),
    )

    assert [(write.parent_verb, write.verb, write.payload["order_id"]) for write in plan.writes] == [
        ("exit_all_positions", "cancel_order", "STOP-EXIT")
    ]

    protected_plan = await _plan(
        _adapter(client),
        _session(),
        policy=_EXIT_POLICY,
        protected_order_ids=frozenset({"STOP-EXIT"}),
        protected_exit_order_ids=frozenset({"STOP-EXIT"}),
        protected_exit_tags=frozenset({tag}),
    )

    assert protected_plan.writes == ()
    assert protected_plan.pending_verbs == frozenset({"exit_all_positions"})


@pytest.mark.asyncio
async def test_unidentified_exit_intent_blocks_new_reducing_writes() -> None:
    client = FakeKotakNeoEmergencyClient(positions=[_position_row(quantity=5)])

    plan = await _plan(
        _adapter(client),
        _session(),
        policy=_EXIT_POLICY,
        unidentified_exit_inflight=True,
    )

    assert plan.pending_verbs == frozenset({"exit_all_positions"})
    assert plan.writes == ()


@pytest.mark.asyncio
async def test_reducing_plan_is_bounded_to_ten_positions() -> None:
    positions = [_position_row(symbol=f"SYNTH-{index}-EQ", quantity=1) for index in range(11)]
    client = FakeKotakNeoEmergencyClient(positions=positions)

    plan = await _plan(_adapter(client), _session(), policy=_EXIT_POLICY)

    assert len(plan.writes) == 10
    assert plan.pending_verbs == frozenset({"exit_all_positions"})


@pytest.mark.asyncio
async def test_reducing_plan_binds_exact_position_and_uses_a_deterministic_tag() -> None:
    symbol = "NIFTY31JUL2625000PE"
    position = _position_row(
        symbol=symbol,
        exchange_segment="nse_fo",
        product="NRML",
        quantity=-50,
        lot_size=25,
    )
    expected_tag = _expected_exit_tag(position)
    expected_payload = {
        "_op": "place_reducing_order",
        "symbol": symbol,
        "exchange": "NFO",
        "exchange_segment": "nse_fo",
        "product": "NRML",
        "broker_product": "NRML",
        "lot_size": "25",
        "carry_buy_quantity": "0",
        "carry_sell_quantity": "0",
        "filled_buy_quantity": "0",
        "filled_sell_quantity": "50",
        "quantity": "50",
        "expected_position_quantity": "-50",
        "action": "BUY",
        "pricetype": "MARKET",
        "price": "0",
        "trigger_price": "0",
        "variety": "regular",
        "emergency_tag": expected_tag,
    }
    client = FakeKotakNeoEmergencyClient(positions=[position])
    adapter = _adapter(client)
    session = _session()

    first = await _plan(adapter, session, policy=_EXIT_POLICY)
    second = await _plan(adapter, session, policy=_EXIT_POLICY)

    assert first.pending_verbs == frozenset({"exit_all_positions"})
    assert len(first.writes) == 1
    assert first.writes[0].parent_verb == "exit_all_positions"
    assert first.writes[0].verb == "place_reducing_order"
    assert dict(first.writes[0].payload) == expected_payload
    assert dict(second.writes[0].payload) == expected_payload

    order_id = await adapter.place_reducing_order(
        session,
        dict(first.writes[0].payload),
        _router_token=_ROUTER_TOKEN,
    )

    assert order_id == "EXIT-NEW-1"
    assert [call for call in client.calls if call[0] == "place_order"] == [
        (
            "place_order",
            {
                "exchange_segment": "nse_fo",
                "product": "NRML",
                "price": "0.0",
                "order_type": "MKT",
                "quantity": "50",
                "validity": "DAY",
                "trading_symbol": symbol,
                "transaction_type": "B",
                "trigger_price": "0.0",
                "disclosed_quantity": "0",
                "amo": "NO",
                "tag": expected_tag,
            },
        )
    ]


def test_full_emergency_dispatch_reduces_kotak_position_through_router_token() -> None:
    class FlatteningClient(FakeKotakNeoEmergencyClient):
        def __init__(self, position: dict[str, Any]) -> None:
            super().__init__()
            self._position_snapshots = [[deepcopy(position)], [deepcopy(position)], []]

        def positions(self) -> Any:
            self.calls.append(("positions",))
            rows = self._position_snapshots.pop(0) if self._position_snapshots else []
            return _book(rows)

    class RecordingAdapter(KotakNeoAdapter):
        def __init__(self, client: FlatteningClient) -> None:
            super().__init__(client_factory=lambda _session: client)
            self.router_tokens: list[object | None] = []

        async def place_reducing_order(
            self,
            session: Session,
            payload: dict[str, Any],
            *,
            _router_token: object | None = None,
        ) -> str:
            self.router_tokens.append(_router_token)
            return await super().place_reducing_order(
                session,
                payload,
                _router_token=_router_token,
            )

    client = FlatteningClient(_position_row(quantity=5))
    adapter = RecordingAdapter(client)
    session = _session()
    gate = SafetyGate()
    request_ctx = RequestContext(
        jti="fake-kotak-exit-jti",
        actor_type="human",
        actor_id="fake-operator",
        mode="live",
        selector="kotakneo:fake-account",
    )
    target = EmergencyBrokerTarget(
        request_ctx=request_ctx,
        adapter_id="kotakneo",
        account_id="fake-account",
    )
    router = BrokerRouter(
        {"kotakneo": adapter},
        lambda _ctx, _adapter_id, _account_id: session,
        consume_gate=gate.consume,
    )
    dispatcher = GatedEmergencyBrokerDispatcher(
        router_provider=lambda: router,
        target_provider=lambda: target,
        run_awaitable=asyncio.run,
        planned_readback_attempts=4,
        planned_quiet_reads=1,
        planned_readback_delay_seconds=0,
    )

    result = dispatcher.dispatch(_EXIT_POLICY, reason="synthetic Kotak reduction proof")

    assert result.complete
    assert result.succeeded("exit_all_positions")
    assert adapter.router_tokens == [_ROUTER_TOKEN]
    assert len([call for call in client.calls if call[0] == "place_order"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        {"stat": "Ok", "nOrdNo": "EXIT-NEW-1"},
        {"stat": "Not_Ok", "stCode": 200, "nOrdNo": "EXIT-NEW-1"},
        {"stat": "Ok", "stCode": 200, "nOrdNo": " BAD-ID "},
    ],
    ids=["missing-code", "negative-status", "noncanonical-order-id"],
)
async def test_reducing_write_requires_explicit_success(response: dict[str, Any]) -> None:
    position = _position_row(quantity=5)
    client = FakeKotakNeoEmergencyClient(positions=[position])
    adapter = _adapter(client)
    session = _session()
    plan = await _plan(adapter, session, policy=_EXIT_POLICY)
    client.place_response = response

    with pytest.raises(KotakNeoMappingError):
        await adapter.place_reducing_order(
            session,
            dict(plan.writes[0].payload),
            _router_token=_ROUTER_TOKEN,
        )

    assert len([call for call in client.calls if call[0] == "place_order"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["net-quantity", "lot-size", "accounting"])
async def test_reducing_write_refuses_a_changed_position_fingerprint(change: str) -> None:
    original = _position_row(quantity=10)
    client = FakeKotakNeoEmergencyClient(positions=[original])
    adapter = _adapter(client)
    session = _session()
    plan = await _plan(adapter, session, policy=_EXIT_POLICY)
    payload = dict(plan.writes[0].payload)

    if change == "net-quantity":
        client.position_rows = [_position_row(quantity=9)]
    elif change == "lot-size":
        client.position_rows = [_position_row(quantity=10, lot_size=2)]
    else:
        client.position_rows = [_position_row(quantity=10, filled_buy=11, filled_sell=1)]

    with pytest.raises(BrokerError, match="changed"):
        await adapter.place_reducing_order(session, payload, _router_token=_ROUTER_TOKEN)

    assert not any(call[0] == "place_order" for call in client.calls)


@pytest.mark.asyncio
async def test_reducing_write_refuses_a_concurrent_reducing_order() -> None:
    position = _position_row(quantity=10)
    client = FakeKotakNeoEmergencyClient(positions=[position])
    adapter = _adapter(client)
    session = _session()
    plan = await _plan(adapter, session, policy=_EXIT_POLICY)
    client.order_rows = [
        _order_row(
            "CONCURRENT-SELL",
            product="CNC",
            side="S",
            quantity=10,
            filled_quantity=0,
            generation="",
            price_type="MKT",
        )
    ]

    with pytest.raises(BrokerError, match="concurrent reducing order"):
        await adapter.place_reducing_order(
            session,
            dict(plan.writes[0].payload),
            _router_token=_ROUTER_TOKEN,
        )

    assert not any(call[0] == "place_order" for call in client.calls)


@pytest.mark.asyncio
async def test_concrete_emergency_writes_require_the_router_token() -> None:
    position = _position_row(quantity=5)
    client = FakeKotakNeoEmergencyClient(
        orders=[_order_row("TOKEN-CANCEL")],
        positions=[position],
    )
    adapter = _adapter(client)
    session = _session()
    exit_plan = await _plan(adapter, session, policy=_EXIT_POLICY)

    with pytest.raises(SafetyBypassError, match="outside BrokerRouter"):
        await adapter.cancel_order(session, "TOKEN-CANCEL")
    with pytest.raises(SafetyBypassError, match="outside BrokerRouter"):
        await adapter.place_reducing_order(session, dict(exit_plan.writes[0].payload))

    assert not any(call[0].startswith("cancel") or call[0] == "place_order" for call in client.calls)


def test_real_dispatcher_path_mints_one_shot_context_and_crosses_router_token_boundary() -> None:
    class RecordingAdapter(KotakNeoAdapter):
        def __init__(self, client: FakeKotakNeoEmergencyClient) -> None:
            super().__init__(client_factory=lambda _session: client)
            self.router_tokens: list[object | None] = []

        async def cancel_order(
            self,
            session: Session,
            order_id: str,
            *,
            variety: str = "regular",
            amo: bool = False,
            trading_symbol: str | None = None,
            _router_token: object | None = None,
        ) -> None:
            self.router_tokens.append(_router_token)
            await super().cancel_order(
                session,
                order_id,
                variety=variety,
                amo=amo,
                trading_symbol=trading_symbol,
                _router_token=_router_token,
            )

    class RecordingRouter(BrokerRouter):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self.cancel_dispatches: list[tuple[RequestContext, dict[str, Any]]] = []

        async def cancel_order(self, request_ctx: RequestContext, **kwargs: Any) -> Any:
            self.cancel_dispatches.append((request_ctx, dict(kwargs)))
            return await super().cancel_order(request_ctx, **kwargs)

    client = FakeKotakNeoEmergencyClient(orders=[_order_row("ROUTED-CANCEL")])
    adapter = RecordingAdapter(client)
    session = _session()
    gate = SafetyGate()

    def provide_session(
        request_ctx: RequestContext,
        adapter_id: str,
        account_id: str,
    ) -> Session:
        assert request_ctx.selector == "kotakneo:fake-account"
        assert adapter_id == "kotakneo"
        assert account_id == "fake-account"
        return session

    router = RecordingRouter(
        {"kotakneo": adapter},
        provide_session,
        consume_gate=gate.consume,
    )
    target_context = RequestContext(
        jti="fake-emergency-jti",
        actor_type="human",
        actor_id="fake-operator",
        mode="live",
        selector="kotakneo:fake-account",
    )
    dispatcher = GatedEmergencyBrokerDispatcher(
        router_provider=lambda: router,
        target_provider=lambda: EmergencyBrokerTarget(
            request_ctx=target_context,
            adapter_id="kotakneo",
            account_id="fake-account",
        ),
        run_awaitable=asyncio.run,
        planned_readback_attempts=4,
        planned_quiet_reads=1,
        planned_readback_delay_seconds=0,
    )

    result = dispatcher.dispatch(_CANCEL_POLICY, reason="synthetic Kotak emergency")

    assert result.complete
    assert adapter.router_tokens == [_ROUTER_TOKEN]
    assert [call for call in client.calls if call[0].startswith("cancel")] == [
        ("cancel_order", "ROUTED-CANCEL", "NO", False, None)
    ]
    assert len(router.cancel_dispatches) == 1
    emergency_context, dispatch = router.cancel_dispatches[0]
    safety_context = dispatch["safety_ctx"]
    assert isinstance(safety_context, SafetyContext)
    assert safety_context.adapter_id == "kotakneo"
    assert safety_context.account_id == "fake-account"
    assert safety_context.intent_source == EMERGENCY_INTENT_SOURCE
    assert safety_context.order_hash == SafetyContext.order_hash_for(dispatch["order"])
    assert emergency_context.intent_source == EMERGENCY_INTENT_SOURCE

    with pytest.raises(SafetyBypassError):
        asyncio.run(router.cancel_order(emergency_context, **dispatch))
    assert len([call for call in client.calls if call[0].startswith("cancel")]) == 1
