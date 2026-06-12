"""Reconciliation-wave tests (contract §14): the pure diff model in
``flinttrade_gateway.reconciliation`` plus every native adapter's ``reconcile()``
happy path (fakes via the established client_factory/transport injections).
"""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timezone
from typing import Any

import pytest

from flinttrade_core.exceptions import BrokerError
from flinttrade_gateway.brokers import indmoney_mapping
from flinttrade_gateway.brokers._base import Session
from flinttrade_gateway.brokers.dhan import DhanAdapter
from flinttrade_gateway.brokers.indmoney import IndMoneyAdapter
from flinttrade_gateway.brokers.kotakneo import KotakNeoAdapter
from flinttrade_gateway.brokers.upstox import UpstoxAdapter
from flinttrade_gateway.reconciliation import (
    DISCREPANCY_ONLY_IN_FLINTTRADE,
    DISCREPANCY_ONLY_ON_BROKER,
    DISCREPANCY_QTY_MISMATCH,
    DISCREPANCY_STATUS_MISMATCH,
    EMPTY_LOCAL_STATE,
    SEVERITY_CRITICAL,
    SEVERITY_WARNING,
    LocalStateSnapshot,
    ReconciliationReport,
    build_report,
)

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 6, 12, 9, 30, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Row helpers (the adapters' normalised read shapes)
# ---------------------------------------------------------------------------


def _order(oid: str = "O1", status: str = "open", symbol: str = "TCS",
           qty: str = "5", filled: str = "0", **extra: Any) -> dict[str, Any]:
    row = {"orderid": oid, "status": status, "symbol": symbol, "exchange": "NSE",
           "product": "CNC", "quantity": qty, "filled_quantity": filled}
    row.update(extra)
    return row


def _pos(symbol: str = "TCS", qty: str = "5", exchange: str = "NSE", product: str = "CNC") -> dict[str, Any]:
    return {"symbol": symbol, "exchange": exchange, "product": product, "quantity": qty}


def _hold(symbol: str = "INFY", qty: str = "10", exchange: str = "NSE") -> dict[str, Any]:
    return {"symbol": symbol, "exchange": exchange, "quantity": qty}


def _report(**kw: Any) -> ReconciliationReport:
    base: dict[str, Any] = {"adapter_id": "dhan", "account_id": "A1", "generated_at": _NOW}
    base.update(kw)
    return build_report(**base)


# ---------------------------------------------------------------------------
# Pure diff model
# ---------------------------------------------------------------------------


def test_identical_state_is_clean() -> None:
    local = LocalStateSnapshot(orders=(_order(),), positions=(_pos(),), holdings=(_hold(),))
    report = _report(broker_orders=[_order()], broker_positions=[_pos()],
                     broker_holdings=[_hold()], local_state=local)
    assert report.clean
    assert report.severity == ""
    assert report.severity_counts == {"info": 0, "warning": 0, "critical": 0}
    assert report.adapter_id == "dhan" and report.account_id == "A1"
    assert report.generated_at is _NOW


def test_broker_only_order_is_warning() -> None:
    report = _report(broker_orders=[_order(oid="O9", status="complete")])
    (diff,) = report.orders_diff
    assert diff.order_id == "O9"
    assert diff.discrepancy == DISCREPANCY_ONLY_ON_BROKER
    assert diff.severity == SEVERITY_WARNING
    assert diff.broker_status == "complete" and diff.flinttrade_status == ""
    assert not report.clean


def test_local_only_order_is_critical() -> None:
    local = LocalStateSnapshot(orders=(_order(oid="GHOST", status="open"),))
    report = _report(local_state=local)
    (diff,) = report.orders_diff
    assert diff.discrepancy == DISCREPANCY_ONLY_IN_FLINTTRADE
    assert diff.severity == SEVERITY_CRITICAL
    assert diff.flinttrade_status == "open"


def test_order_status_comparison_is_case_insensitive() -> None:
    local = LocalStateSnapshot(orders=(_order(status="OPEN"),))
    report = _report(broker_orders=[_order(status="open")], local_state=local)
    assert report.clean


def test_order_status_mismatch_is_warning() -> None:
    local = LocalStateSnapshot(orders=(_order(status="open"),))
    report = _report(broker_orders=[_order(status="complete")], local_state=local)
    (diff,) = report.orders_diff
    assert diff.discrepancy == DISCREPANCY_STATUS_MISMATCH
    assert diff.severity == SEVERITY_WARNING
    assert diff.flinttrade_status == "open" and diff.broker_status == "complete"


def test_order_qty_mismatch_detail_names_both_fields() -> None:
    local = LocalStateSnapshot(orders=(_order(qty="5", filled="0"),))
    report = _report(broker_orders=[_order(qty="10", filled="10")], local_state=local)
    (diff,) = report.orders_diff
    assert diff.discrepancy == DISCREPANCY_QTY_MISMATCH
    assert "quantity: flinttrade=5 broker=10" in diff.detail
    assert "filled_quantity: flinttrade=0 broker=10" in diff.detail


def test_order_status_and_qty_mismatch_coexist() -> None:
    local = LocalStateSnapshot(orders=(_order(status="open", filled="0"),))
    report = _report(broker_orders=[_order(status="complete", filled="5")], local_state=local)
    assert {d.discrepancy for d in report.orders_diff} == {
        DISCREPANCY_STATUS_MISMATCH, DISCREPANCY_QTY_MISMATCH,
    }


def test_position_qty_mismatch_is_critical() -> None:
    local = LocalStateSnapshot(positions=(_pos(qty="5"),))
    report = _report(broker_positions=[_pos(qty="3")], local_state=local)
    (diff,) = report.positions_diff
    assert diff.discrepancy == DISCREPANCY_QTY_MISMATCH
    assert diff.severity == SEVERITY_CRITICAL
    assert diff.flinttrade_qty == 5.0 and diff.broker_qty == 3.0


def test_position_missing_either_side_is_critical() -> None:
    local = LocalStateSnapshot(positions=(_pos(symbol="GHOST"),))
    report = _report(broker_positions=[_pos(symbol="REAL")], local_state=local)
    by_symbol = {d.symbol: d for d in report.positions_diff}
    assert by_symbol["REAL"].discrepancy == DISCREPANCY_ONLY_ON_BROKER
    assert by_symbol["GHOST"].discrepancy == DISCREPANCY_ONLY_IN_FLINTTRADE
    assert all(d.severity == SEVERITY_CRITICAL for d in report.positions_diff)


def test_flat_positions_are_not_discrepancies() -> None:
    # A closed (qty 0) row broker-side and no local row both mean "flat".
    report = _report(broker_positions=[_pos(qty="0")])
    assert report.clean


def test_position_key_includes_product() -> None:
    # Same scrip under MIS vs CNC are different positions, not a qty mismatch.
    local = LocalStateSnapshot(positions=(_pos(product="MIS"),))
    report = _report(broker_positions=[_pos(product="CNC")], local_state=local)
    assert {d.discrepancy for d in report.positions_diff} == {
        DISCREPANCY_ONLY_ON_BROKER, DISCREPANCY_ONLY_IN_FLINTTRADE,
    }


def test_holdings_discrepancies_are_warnings() -> None:
    local = LocalStateSnapshot(holdings=(_hold(qty="10"),))
    report = _report(broker_holdings=[_hold(qty="8")], local_state=local)
    (diff,) = report.holdings_diff
    assert diff.discrepancy == DISCREPANCY_QTY_MISMATCH
    assert diff.severity == SEVERITY_WARNING


def test_severity_is_worst_across_surfaces_and_counts_add_up() -> None:
    report = _report(
        broker_orders=[_order(oid="O9")],            # warning
        broker_positions=[_pos(symbol="REAL")],      # critical
        broker_holdings=[_hold(symbol="HODL")],      # warning
    )
    assert report.severity == SEVERITY_CRITICAL
    assert report.severity_counts == {"info": 0, "warning": 2, "critical": 1}


def test_error_short_circuits_diffs() -> None:
    report = _report(broker_orders=[_order()], error="broker fetch failed: boom")
    assert report.error == "broker fetch failed: boom"
    assert report.orders_diff == () and report.positions_diff == () and report.holdings_diff == ()
    assert not report.clean
    assert report.severity == SEVERITY_CRITICAL


def test_report_is_frozen() -> None:
    report = _report()
    with pytest.raises(dataclasses.FrozenInstanceError):
        report.error = "mutated"  # type: ignore[misc]


def test_as_dict_is_json_serialisable() -> None:
    local = LocalStateSnapshot(orders=(_order(status="open"),))
    report = _report(broker_orders=[_order(status="complete")], local_state=local)
    payload = json.loads(json.dumps(report.as_dict()))
    assert payload["adapter_id"] == "dhan"
    assert payload["generated_at"] == _NOW.isoformat()
    assert payload["clean"] is False
    assert payload["orders_diff"][0]["discrepancy"] == DISCREPANCY_STATUS_MISMATCH


def test_diffs_are_deterministic_and_sorted() -> None:
    broker = [_order(oid="B"), _order(oid="A"), _order(oid="C")]
    first = _report(broker_orders=broker)
    second = _report(broker_orders=list(reversed(broker)))
    assert first == second
    assert [d.order_id for d in first.orders_diff] == ["A", "B", "C"]


def test_rows_without_order_id_are_ignored() -> None:
    report = _report(broker_orders=[{"status": "open", "symbol": "TCS"}])
    assert report.clean


def test_default_local_state_is_empty() -> None:
    report = _report(broker_orders=[_order()], local_state=None)
    (diff,) = report.orders_diff
    assert diff.discrepancy == DISCREPANCY_ONLY_ON_BROKER
    assert EMPTY_LOCAL_STATE.orders == () and EMPTY_LOCAL_STATE.positions == ()


# ---------------------------------------------------------------------------
# Adapter fakes
# ---------------------------------------------------------------------------

_DHAN_ORDER = {"orderId": "OID1", "orderStatus": "PENDING", "tradingSymbol": "TCS",
               "exchangeSegment": "NSE_EQ", "transactionType": "BUY", "orderType": "LIMIT",
               "productType": "CNC", "quantity": 5, "price": 3500}
_DHAN_POSITION = {"tradingSymbol": "TCS", "exchangeSegment": "NSE_EQ", "productType": "CNC",
                  "netQty": 5, "costPrice": 3450.0, "buyQty": 5, "buyAvg": 3450.0}
_DHAN_HOLDING = {"tradingSymbol": "INFY", "exchange": "NSE", "totalQty": 10, "avgCostPrice": 1500}


class _DhanClient:
    """Read-surface stand-in for the dhanhq client (reconcile inputs only)."""

    def __init__(self, *, fail_orders: bool = False) -> None:
        self._fail_orders = fail_orders

    def get_order_list(self):
        if self._fail_orders:
            raise BrokerError("boom")
        return {"status": "success", "data": [_DHAN_ORDER]}

    def get_positions(self):
        return {"status": "success", "data": [_DHAN_POSITION]}

    def get_holdings(self):
        return {"status": "success", "data": [_DHAN_HOLDING]}


class _UpstoxClient:
    """Read-surface stand-in for the UpstoxClient facade."""

    def order_book(self):
        return {"status": "success", "data": [
            {"order_id": "U1", "status": "open", "trading_symbol": "RELIANCE", "exchange": "NSE",
             "transaction_type": "BUY", "order_type": "LIMIT", "product": "D",
             "quantity": 10, "price": 2900, "filled_quantity": 0},
        ]}

    def positions(self):
        return {"status": "success", "data": [
            {"trading_symbol": "RELIANCE", "exchange": "NSE", "product": "D",
             "quantity": 10, "average_price": 2900.0, "last_price": 2950.0, "pnl": 500.0},
        ]}

    def holdings(self):
        return {"status": "success", "data": [
            {"trading_symbol": "TCS", "exchange": "NSE", "quantity": 5, "average_price": 3450.0},
        ]}


class _KotakClient:
    """Read-surface stand-in for the KotakNeoClient facade."""

    def order_book(self):
        return {"data": [
            {"nOrdNo": "K1", "ordSt": "open", "trdSym": "IDEA-EQ", "exSeg": "nse_cm",
             "trnsTp": "B", "prcTp": "L", "prod": "CNC", "qty": 10, "prc": "9.5", "fldQty": 0},
        ]}

    def positions(self):
        return {"data": [
            {"trdSym": "IDEA-EQ", "exSeg": "nse_cm", "prod": "CNC", "flBuyQty": 10, "buyAmt": 95.0,
             "cfBuyQty": 0, "cfSellQty": 0, "flSellQty": 0, "genNum": 1, "genDen": 1,
             "prcNum": 1, "prcDen": 1, "precision": 2},
        ]}

    def holdings(self):
        return {"data": [
            {"displaySymbol": "IDEA", "exchangeSegment": "nse_cm", "quantity": 10, "averagePrice": 9.5},
        ]}


_IND_ORDER = {"id": "DRV-1", "status": "SUCCESS", "name": "NIFTY 3 JUL 25700 CE",
              "exchange": "NSE", "segment": "DERIVATIVE", "product": "MARGIN",
              "txn_type": "BUY", "order_type": "MARKET", "requested_qty": 75, "traded_qty": 75,
              "requested_price": "43.55", "traded_price": "43.55", "security_id": "56998"}
_IND_POSITION = {"trading_symbol": "NIFTY 3 JUL 25700 CE", "exchange_segment": "NSE_FNO",
                 "net_quantity": 75, "average_price": 43.55, "last_traded_price": 44.0,
                 "pnl_absolute": 33.75}
_IND_HOLDING = {"trading_symbol": "TCS", "exchange_segment": "NSE_EQ", "quantity": 5,
                "average_price": 3450}


def _ind_transport(method, url, *, headers, params=None, json_body=None):
    """Params-aware fake httpx transport for the IndMoney adapter.

    Positions are returned for the derivative/margin combo ONLY, so the
    adapter's four-combo aggregation yields exactly one position row.
    """
    path = url.replace(indmoney_mapping.BASE_URL, "")
    if path == "/order-book":
        return 200, {"status": "success", "data": [_IND_ORDER]}
    if path == "/portfolio/positions":
        if params == {"segment": "derivative", "product": "margin"}:
            return 200, {"status": "success", "data": {"net_positions": [_IND_POSITION],
                                                       "day_positions": []}}
        return 200, {"status": "success", "data": {"net_positions": [], "day_positions": []}}
    if path == "/portfolio/holdings":
        return 200, {"status": "success", "data": [_IND_HOLDING]}
    return 200, {"status": "success", "data": {}}


def _session(adapter_id: str, account_id: str) -> Session:
    return Session(access_token="TOK", expires_at=4_000_000_000.0,
                   account_id=account_id, adapter_id=adapter_id)


async def _own_reads_snapshot(adapter, session: Session) -> LocalStateSnapshot:
    """A flinttrade-side mirror that matches the broker exactly (clean case)."""
    return LocalStateSnapshot(
        orders=tuple(await adapter.order_book(session)),
        positions=tuple(await adapter.positions(session)),
        holdings=tuple(await adapter.holdings(session)),
    )


# ---------------------------------------------------------------------------
# Per-adapter reconcile()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dhan_reconcile_clean_round_trip() -> None:
    holder: dict[str, LocalStateSnapshot] = {}
    adapter = DhanAdapter(client_factory=lambda _s: _DhanClient(),
                          local_state_provider=lambda _s: holder["snap"])
    session = _session("dhan", "ACC-D")
    holder["snap"] = await _own_reads_snapshot(adapter, session)
    report = await adapter.reconcile(session)
    assert report.adapter_id == "dhan" and report.account_id == "ACC-D"
    assert report.clean and report.error == ""


@pytest.mark.asyncio
async def test_dhan_reconcile_default_empty_local_flags_broker_rows() -> None:
    adapter = DhanAdapter(client_factory=lambda _s: _DhanClient())
    report = await adapter.reconcile(_session("dhan", "ACC-D"))
    assert not report.clean
    assert [d.discrepancy for d in report.orders_diff] == [DISCREPANCY_ONLY_ON_BROKER]
    assert [d.discrepancy for d in report.positions_diff] == [DISCREPANCY_ONLY_ON_BROKER]
    assert [d.discrepancy for d in report.holdings_diff] == [DISCREPANCY_ONLY_ON_BROKER]
    assert report.severity == SEVERITY_CRITICAL  # the untracked position dominates


@pytest.mark.asyncio
async def test_dhan_reconcile_fetch_error_is_captured_not_raised() -> None:
    adapter = DhanAdapter(client_factory=lambda _s: _DhanClient(fail_orders=True))
    report = await adapter.reconcile(_session("dhan", "ACC-D"))
    assert "boom" in report.error and report.error.startswith("broker fetch failed")
    assert not report.clean and report.severity == SEVERITY_CRITICAL
    assert report.orders_diff == () and report.positions_diff == () and report.holdings_diff == ()


@pytest.mark.asyncio
async def test_upstox_reconcile_clean_then_flags_local_qty_drift() -> None:
    holder: dict[str, LocalStateSnapshot] = {}
    adapter = UpstoxAdapter(client_factory=lambda _s: _UpstoxClient(),
                            local_state_provider=lambda _s: holder["snap"])
    session = _session("upstox", "ACC-U")
    snap = await _own_reads_snapshot(adapter, session)
    holder["snap"] = snap
    assert (await adapter.reconcile(session)).clean

    # Drift the local mirror's position quantity → one critical qty mismatch.
    drifted = tuple({**row, "quantity": "7"} for row in snap.positions)
    holder["snap"] = LocalStateSnapshot(orders=snap.orders, positions=drifted, holdings=snap.holdings)
    report = await adapter.reconcile(session)
    (diff,) = report.positions_diff
    assert diff.discrepancy == DISCREPANCY_QTY_MISMATCH and diff.severity == SEVERITY_CRITICAL
    assert diff.flinttrade_qty == 7.0 and diff.broker_qty == 10.0
    assert report.orders_diff == () and report.holdings_diff == ()


@pytest.mark.asyncio
async def test_kotakneo_reconcile_clean_round_trip() -> None:
    holder: dict[str, LocalStateSnapshot] = {}
    adapter = KotakNeoAdapter(client_factory=lambda _s: _KotakClient(),
                              local_state_provider=lambda _s: holder["snap"])
    session = _session("kotakneo", "ACC-K")
    holder["snap"] = await _own_reads_snapshot(adapter, session)
    report = await adapter.reconcile(session)
    assert report.adapter_id == "kotakneo" and report.account_id == "ACC-K"
    assert report.clean and report.error == ""


@pytest.mark.asyncio
async def test_indmoney_reconcile_clean_round_trip() -> None:
    holder: dict[str, LocalStateSnapshot] = {}
    adapter = IndMoneyAdapter(http_factory=lambda: _ind_transport,
                              local_state_provider=lambda _s: holder["snap"])
    session = _session("indmoney", "ACC-I")
    holder["snap"] = await _own_reads_snapshot(adapter, session)
    report = await adapter.reconcile(session)
    assert report.adapter_id == "indmoney" and report.account_id == "ACC-I"
    assert report.clean and report.error == ""
    # The fake serves exactly one of everything — prove the snapshot was real.
    assert len(holder["snap"].orders) == 1
    assert len(holder["snap"].positions) == 1
    assert len(holder["snap"].holdings) == 1
