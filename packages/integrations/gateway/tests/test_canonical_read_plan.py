"""Finite canonical captures with real managed owners and synthetic transports."""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import pytest

from flinttrade_core.broker_read_port import BatchQuoteRequest, InstrumentRef, LedgerRequest
from flinttrade_core.native_autonomy_contracts_v2 import ReadPlanV2
from flinttrade_engine.local_state_provider import OrderLifecycleLedger
from packages.integrations.gateway.tests.test_canonical_broker_observations import (
    SyntheticAdapter,
    bound as bound,
    richer_trade,
)

pytestmark = pytest.mark.unit


class FullSource(SyntheticAdapter):
    """Explicit inert source; empty resources are real supplied observations."""

    async def order_book(self, session: Any) -> list:
        """Record an exact-account orders read and return the fixture's empty collection.

        Args:
            session: Broker session supplied by the real adapter call.

        Returns:
            An explicitly empty synthetic collection; the read call remains in the fixture ledger.
        """
        self.calls.append(("orders", session.account_id))
        return []

    async def positions(self, session: Any) -> list:
        """Record an exact-account positions read and return the fixture's empty collection.

        Args:
            session: Broker session supplied by the real adapter call.

        Returns:
            An explicitly empty synthetic collection; the read call remains in the fixture ledger.
        """
        self.calls.append(("positions", session.account_id))
        return []

    async def holdings(self, session: Any) -> list:
        """Record an exact-account holdings read and return the fixture's empty collection.

        Args:
            session: Broker session supplied by the real adapter call.

        Returns:
            An explicitly empty synthetic collection; the read call remains in the fixture ledger.
        """
        self.calls.append(("holdings", session.account_id))
        return []

    async def ledger(self, session: Any, start: str, end: str) -> list:
        """Record an exact-account dated fees read and return the fixture's empty collection.

        Args:
            session: Broker session supplied by the real adapter call.
            start: Requested ledger start date supplied by the canonical read plan.
            end: Requested ledger end date supplied by the canonical read plan.

        Returns:
            An explicitly empty synthetic collection; the read call remains in the fixture ledger.
        """
        self.calls.append(("fees", session.account_id))
        return []

    async def forever_orders(self, session: Any) -> list:
        """Record an exact-account Forever orders read and return the fixture's empty collection.

        Args:
            session: Broker session supplied by the real adapter call.

        Returns:
            An explicitly empty synthetic collection; the read call remains in the fixture ledger.
        """
        self.calls.append(("forever", session.account_id))
        return []

    async def super_orders(self, session: Any) -> list:
        """Record an exact-account Super orders read and return the fixture's empty collection.

        Args:
            session: Broker session supplied by the real adapter call.

        Returns:
            An explicitly empty synthetic collection; the read call remains in the fixture ledger.
        """
        self.calls.append(("super", session.account_id))
        return []

    async def quotes(self, session: Any, instruments: list[str]) -> list:
        """Record the exact-account quote read and return the configured synthetic option quote.

        Args:
            session: Broker session supplied by the real adapter call.
            instruments: Requested canonical instrument names recorded by the quote read.

        Returns:
            The fixture's single option quote observation, without qualification or execution authority.
        """
        self.calls.append(("quotes", session.account_id))
        return [{"symbol": "SYNTHETIC-OPTION", "exchange": "NFO", "ltp": 12.5}]


def plan(surfaces: list[str], *, reads: int = 16, pages: int = 4) -> ReadPlanV2:
    """Return explicit finite synthetic selection, not read authority."""
    return ReadPlanV2(surfaces=surfaces, max_reads=reads, max_pages=pages,
                      deadline_ms=int(time.time() * 1000) + 30000)


def test_full_plan_retains_actual_surfaces_through_restart(bound: Any, tmp_path: Path) -> None:
    """Every selected surface reaches the existing durable capture owner."""
    source = FullSource([richer_trade()])
    handle = bound(source)
    ledger = OrderLifecycleLedger(ledger_path=tmp_path / "canonical.sqlite")
    snapshot = asyncio.run(ledger.refresh_observations(
        handle.owner, handle.port,
        read_plan=plan(["orders", "positions", "holdings", "trades", "fees", "broker_protection", "quotes"]),
        ledger=LedgerRequest("2026-10-23", "2026-10-24"),
        quotes=BatchQuoteRequest((InstrumentRef("SYNTHETIC-OPTION", "NFO"),)),
    ))
    assert [call[0] for call in source.calls] == [
        "orders", "positions", "holdings", "trades", "fees", "forever", "super", "quotes",
    ]
    assert [(row.surface, row.family) for row in snapshot.surfaces] == [
        ("orders", "regular"), ("positions", None), ("holdings", None), ("trades", "daily"),
        ("fees", "account_postings"), ("broker_protection", "forever"),
        ("broker_protection", "super"), ("quotes", None),
    ]
    assert all(row.coverage.availability == "available" for row in snapshot.surfaces)
    assert json.loads(snapshot.surfaces[-1].value_json)[0]["ltp"] == 12.5
    assert all(row.coverage.source_digest is not None for row in snapshot.surfaces)
    assert all(row.coverage.generation == snapshot.generation for row in snapshot.surfaces)
    assert not snapshot.admission_available
    assert "paid_allocation_producer_unavailable" in snapshot.missing_evidence
    reopened = OrderLifecycleLedger(ledger_path=tmp_path / "canonical.sqlite").observation_snapshot(handle.selector)
    assert reopened.surfaces == snapshot.surfaces
    assert reopened.surface_history == snapshot.surface_history


def test_plan_limits_actual_operations_and_retains_every_requested_surface(bound: Any) -> None:
    """Exhaustion cannot disappear a requested surface or become a complete empty book."""
    source = FullSource([richer_trade()])
    handle = bound(source)
    captured = asyncio.run(handle.owner.capture_observations(handle.port,
        read_plan=plan(["orders", "positions", "holdings", "trades", "fees", "quotes"], reads=3),
        ledger=LedgerRequest("2026-10-23", "2026-10-24"),
        quotes=BatchQuoteRequest((InstrumentRef("SYNTHETIC-OPTION", "NFO"),))))
    assert [call[0] for call in source.calls] == ["orders", "positions", "holdings"]
    assert len(captured.surfaces) == 6
    assert all(row.coverage.availability != "available" for row in captured.surfaces[3:])
    budget = json.loads(captured.read_budget_json)
    assert budget["reserved_reads"] == 3
    assert "read_budget_exceeded" in budget["issues"]


def test_plan_page_ceiling_is_shared_with_daily_capture(bound: Any) -> None:
    """A history selection cannot receive a fresh page budget at each call."""
    from flinttrade_core.broker_read_port import TradeHistoryRequest

    class History(FullSource):
        async def trade_history(self, session: Any, start: str, end: str, page: int) -> list:
            self.calls.append(("history", page))
            return [richer_trade()]
    source = History([richer_trade()])
    handle = bound(source)
    captured = asyncio.run(handle.owner.capture_observations(handle.port,
        read_plan=plan(["trades"], pages=1), history=TradeHistoryRequest("2026-10-23", "2026-10-24", 3)))
    assert source.calls == [("trades", "NativeCase"), ("history", 0)]
    budget = json.loads(captured.read_budget_json)
    assert budget["reserved_pages"] == 1 and budget["reserved_reads"] == 2
    assert "page_budget_exceeded" in budget["issues"]
    assert captured.surfaces[-1].coverage.completeness != "complete"


def test_native_aggregate_book_counts_each_installed_sdk_invocation(bound: Any, monkeypatch: Any) -> None:
    """One adapter method is not permission for its entire multi-resource horizon."""
    from types import SimpleNamespace
    from dhanhq import DhanContext, dhanhq
    from flinttrade_gateway.brokers.dhan import DhanAdapter

    sdk = dhanhq(DhanContext("NativeCase", "synthetic"))
    calls = []
    def send(method: str, url: str, **kwargs: Any) -> Any:
        assert method == "GET"
        calls.append(url)
        return SimpleNamespace(status_code=200, content=b'[]')
    monkeypatch.setattr(sdk.dhan_http.session, "request", send)
    handle = bound(DhanAdapter(client_factory=lambda _: sdk))
    try:
        captured = asyncio.run(handle.owner.capture_observations(handle.port,
            read_plan=plan(["orders", "trades"], reads=2)))
        assert len(calls) == 2
        assert json.loads(captured.read_budget_json)["reserved_reads"] == 2
        assert all(row.coverage.availability != "available" for row in captured.surfaces)
    finally:
        assert handle.owner.close(timeout=1)
        sdk.dhan_http.session.close()


def test_initial_binding_cannot_extend_the_requested_absolute_deadline(bound: Any, monkeypatch: Any) -> None:
    """A real authority check delayed before return cannot create a fresh read window."""
    source = FullSource([richer_trade()])
    handle = bound(source)
    original = type(handle.owner).observation_binding
    held = []

    def delayed(self: Any, *args: Any, **kwargs: Any) -> Any:
        result = original(self, *args, **kwargs)
        if self is handle.owner and not held:
            held.append(True)
            time.sleep(0.15)
        return result

    monkeypatch.setattr(type(handle.owner), "observation_binding", delayed)
    selected = ReadPlanV2(surfaces=["orders"], max_reads=1, max_pages=1,
                          deadline_ms=int(time.time()*1000)+100)
    captured = asyncio.run(handle.owner.capture_observations(handle.port, read_plan=selected))
    assert held == [True]
    assert source.calls == [], "initial binding must not restart an already elapsed absolute deadline"
    assert len(captured.surfaces) == 1 and captured.surfaces[0].coverage.availability != "available"
    assert "read_deadline_exceeded" in json.loads(captured.read_budget_json)["issues"]
