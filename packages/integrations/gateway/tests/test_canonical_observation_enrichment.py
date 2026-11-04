"""Synthetic immutable-fill enrichment, conflict and restart regressions."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest

from flinttrade_engine.local_state_provider import OrderLifecycleLedger

_spec = importlib.util.spec_from_file_location(
    "_canonical_enrichment_fixture", Path(__file__).with_name("test_canonical_broker_observations.py")
)
assert _spec is not None and _spec.loader is not None
_fixture = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _fixture
_spec.loader.exec_module(_fixture)
bound = _fixture.bound
pytestmark = pytest.mark.unit


def test_compatible_enrichment_survives_outage_without_rewriting_original(
    bound: Callable[..., SimpleNamespace], tmp_path: Path
) -> None:
    """Retain both independent raw observations for one execution after restart.

    Args:
        bound: Real registry and read owner with inert synthetic adapters.
        tmp_path: Disposable durable ledger directory.
    """
    adapter = _fixture.SyntheticAdapter([_fixture.richer_trade()])
    handle = bound(adapter)
    path = tmp_path / "ledger.db"
    ledger = OrderLifecycleLedger(ledger_path=path)
    first = asyncio.run(ledger.refresh_observations(handle.owner, handle.port))
    original = first.fills[0].trade.raw_observation_json
    adapter.rows = [_fixture.richer_trade(updated_at="new-update", broker_fields={"drvExpiryDate": "2026-10-29"})]
    second = asyncio.run(ledger.refresh_observations(handle.owner, handle.port))
    assert len(second.fills) == 1 and not second.conflicts
    adapter.rows = []
    asyncio.run(ledger.refresh_observations(handle.owner, handle.port))
    restarted = OrderLifecycleLedger(ledger_path=path).observation_snapshot(handle.selector)
    assert restarted.fills[0].trade.updated_at == "new-update"
    assert json.loads(restarted.fills[0].trade.raw_observation_json)["broker_fields"]["drvExpiryDate"] == "2026-10-29"
    assert len(restarted.trade_history) == 2
    assert restarted.trade_history[0].trade.raw_observation_json == original
    assert first.fills[0].trade.raw_observation_json == original
    assert not restarted.admission_available


@pytest.mark.parametrize("sparse_between", [False, True])
def test_enriched_immutable_fact_remains_comparison_evidence(
    bound: Callable[..., SimpleNamespace], tmp_path: Path, sparse_between: bool
) -> None:
    """Detect absence-to-A-to-B contradictions, including intervening sparse rows.

    Args:
        bound: Real registry and read owner with inert synthetic adapters.
        tmp_path: Disposable durable ledger directory.
        sparse_between: Whether another row omits the established expiry.
    """
    adapter = _fixture.SyntheticAdapter([_fixture.richer_trade(broker_fields={})])
    handle = bound(adapter)
    path = tmp_path / "ledger.db"
    ledger = OrderLifecycleLedger(ledger_path=path)
    asyncio.run(ledger.refresh_observations(handle.owner, handle.port))
    adapter.rows = [_fixture.richer_trade(broker_fields={"drvExpiryDate": "2026-10-29"})]
    enriched = asyncio.run(ledger.refresh_observations(handle.owner, handle.port))
    assert len(enriched.fills) == 1 and not enriched.conflicts
    if sparse_between:
        adapter.rows = [_fixture.richer_trade(updated_at="sparse", broker_fields={})]
        assert not asyncio.run(ledger.refresh_observations(handle.owner, handle.port)).conflicts
    adapter.rows = [_fixture.richer_trade(broker_fields={"drvExpiryDate": "2026-11-26"})]
    result = asyncio.run(ledger.refresh_observations(handle.owner, handle.port))
    assert any(item.startswith("immutable_fill_conflict:") for item in result.conflicts)
    assert len(result.fills) == 1
    adapter.rows = None
    asyncio.run(ledger.refresh_observations(handle.owner, handle.port))
    restart = OrderLifecycleLedger(ledger_path=path).observation_snapshot(handle.selector)
    assert restart.conflicts == result.conflicts and restart.fills == result.fills
    expiries = {
        json.loads(row.trade.raw_observation_json)["broker_fields"].get("drvExpiryDate")
        for row in restart.trade_history
    }
    assert expiries == {None, "2026-10-29", "2026-11-26"}
