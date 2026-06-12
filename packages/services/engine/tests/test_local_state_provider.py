"""JournalLocalStateProvider — the honest (empty) reconciliation mirror.

The journal cannot attribute rows to a broker account and records no order
status / positions / holdings, so the provider MUST return empty state on
every surface (fabricating rows would fabricate discrepancies). These tests
pin that contract plus the lazy-handle seam.
"""

from __future__ import annotations

from typing import Any

import pytest

from flinttrade_engine.local_state_provider import JournalLocalStateProvider
from flinttrade_gateway.reconciliation import LocalStateSnapshot, build_report

pytestmark = pytest.mark.unit


class _Session:
    def __init__(self, account_id: str = "personal") -> None:
        self.account_id = account_id
        self.adapter_id = "dhan"


def test_returns_empty_snapshot() -> None:
    provider = JournalLocalStateProvider()
    snapshot = provider(_Session())
    assert isinstance(snapshot, LocalStateSnapshot)
    assert snapshot.orders == ()
    assert snapshot.positions == ()
    assert snapshot.holdings == ()


def test_does_not_touch_storage_handles_today() -> None:
    """The seam is held but unused: empty state needs no journal read."""
    calls: list[str] = []

    def _storage() -> Any:
        calls.append("storage")
        return object()

    def _lock() -> Any:
        calls.append("lock")
        return object()

    provider = JournalLocalStateProvider(storage_provider=_storage, lock_provider=_lock)
    provider(_Session())
    assert calls == []


def test_tolerates_missing_storage() -> None:
    provider = JournalLocalStateProvider(
        storage_provider=lambda: None, lock_provider=lambda: None
    )
    snapshot = provider(_Session("family"))
    assert snapshot.orders == ()


def test_empty_mirror_diffs_as_exists_only_on_broker() -> None:
    """End-to-end semantics: with the empty mirror, broker rows surface as
    ``exists_only_on_broker`` — documented behaviour, not fabricated state."""
    from datetime import datetime, timezone

    provider = JournalLocalStateProvider()
    report = build_report(
        adapter_id="dhan",
        account_id="personal",
        generated_at=datetime(2026, 6, 12, tzinfo=timezone.utc),
        broker_orders=[{"orderid": "B1", "symbol": "RELIANCE", "status": "OPEN"}],
        local_state=provider(_Session()),
    )
    assert len(report.orders_diff) == 1
    assert report.orders_diff[0].discrepancy == "exists_only_on_broker"
