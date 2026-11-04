"""Immutable-generation integrity controls using synthetic owned observations."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sqlite3
import sys
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest

from flinttrade_engine.local_state_provider import LifecycleStateError, OrderLifecycleLedger

# Use a private module identity under both repository and package-local discovery.
_spec = importlib.util.spec_from_file_location(
    "_canonical_integrity_fixture", Path(__file__).with_name("test_canonical_broker_observations.py")
)
assert _spec is not None and _spec.loader is not None
_fixture = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _fixture
_spec.loader.exec_module(_fixture)
bound = _fixture.bound
pytestmark = pytest.mark.unit


@pytest.mark.parametrize("alteration", ["schema", "missing_schema", "empty_evidence", "invalid_json", "non_object"])
def test_manifest_integrity_precedes_payload_dispatch(
    bound: Callable[..., SimpleNamespace], tmp_path: Path, alteration: str
) -> None:
    """Refuse a damaged stored generation without silently dropping its fill.

    Args:
        bound: Real registry/read-owner fixture with inert synthetic adapters.
        tmp_path: Disposable ledger directory.
        alteration: Damage applied while retaining the original digest.
    """
    handle = bound(_fixture.SyntheticAdapter([_fixture.richer_trade()]))
    path = tmp_path / "ledger.db"
    ledger = OrderLifecycleLedger(ledger_path=path)
    assert len(asyncio.run(ledger.refresh_observations(handle.owner, handle.port)).fills) == 1
    with sqlite3.connect(path) as connection:
        original, digest = connection.execute(
            "SELECT evidence_json, content_digest FROM snapshot_generation_manifests"
        ).fetchone()
        payload = json.loads(original)
        if alteration == "schema":
            payload["schema"] = "flinttrade.canonical-observations.v0"
        elif alteration == "missing_schema":
            del payload["schema"]
        text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        if alteration == "empty_evidence":
            text = ""
        elif alteration == "invalid_json":
            text = "{"
        elif alteration == "non_object":
            text = "[]"
        connection.execute("UPDATE snapshot_generation_manifests SET evidence_json=?", (text,))
    with pytest.raises(LifecycleStateError, match="integrity"):
        OrderLifecycleLedger(ledger_path=path).observation_snapshot(handle.selector)
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT evidence_json, content_digest FROM snapshot_generation_manifests"
        ).fetchone() == (text, digest)
        connection.execute("UPDATE snapshot_generation_manifests SET evidence_json=?", (original,))
    assert len(OrderLifecycleLedger(ledger_path=path).observation_snapshot(handle.selector).fills) == 1


@pytest.mark.parametrize("populated", [False, True])
def test_legacy_empty_manifest_requires_matching_independent_rows(
    bound: Callable[..., SimpleNamespace], tmp_path: Path, populated: bool
) -> None:
    """Keep legacy empty payloads readable when their retained rows match.

    Args:
        bound: Real registry/read-owner fixture with inert synthetic adapters.
        tmp_path: Disposable ledger directory.
        populated: Whether the legacy broker generation contains an order.
    """
    handle = bound(_fixture.SyntheticAdapter([]))
    path = tmp_path / "ledger.db"
    ledger = OrderLifecycleLedger(ledger_path=path)
    order = {
        "orderid": "legacy-order", "symbol": "SYNTHETIC", "exchange": "NSE", "product": "CNC",
        "action": "BUY", "status": "PARTIALLY_FILLED", "quantity": 2, "filled_quantity": 1, "price": 1,
    }
    ledger.record_broker_snapshot(
        adapter_id="dhan", account_id="AliasCase", orders=[order] if populated else [], positions=[], holdings=[]
    )
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE snapshot_generation_manifests SET evidence_json=''")
    result = OrderLifecycleLedger(ledger_path=path).observation_snapshot(handle.selector)
    assert not result.fills and not result.admission_available
    if populated:
        assert result.order_fills[0].unexplained_quantity == "1.0"
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 8
        assert connection.execute("SELECT evidence_json FROM snapshot_generation_manifests").fetchone() == ("",)
