"""Exact derivative lots share the authorised context's durable receipt."""

from __future__ import annotations

import hashlib
import json

import pytest

from flinttrade_core.ai_broker_context import BrokerContextError
from flinttrade_core.broker_identity import BrokerSelector
from packages.core.core.tests.test_ai_broker_context import _collect
from packages.core.core.tests.test_ai_broker_context import runtime as runtime

_SYMBOL = "NIFTY30SEP2625000CE"


def _install_lots(runtime, monkeypatch, rows=None, after_read=lambda: None):
    async def instrument_lot_sizes(session, request):
        await runtime.adapter._read(session, "lot_sizes")
        assert request.exchange in {"NFO", "BFO", "MCX", "CDS", "BCD"}
        assert request.symbols == (_SYMBOL,)
        after_read()
        return (
            rows
            if rows is not None
            else [
                {"symbol": _SYMBOL, "exchange": request.exchange, "lot_size": 65, "instrument_id": "contract-1"},
            ]
        )

    monkeypatch.setattr(runtime.adapter, "instrument_lot_sizes", instrument_lot_sizes, raising=False)


@pytest.mark.parametrize("exchange", ["NFO", "BFO", "MCX", "CDS", "BCD"])
def test_exact_derivative_lot_is_receipted_with_quote_authority(runtime, monkeypatch, exchange):
    _install_lots(runtime, monkeypatch)
    result = _collect(runtime, symbol=_SYMBOL, exchange=exchange)
    record = result.market_data.get("lot_size")
    assert record is not None, "Derivative analysis omitted its broker-owned lot metadata"
    assert record["request"] == {"exchange": exchange, "symbols": [_SYMBOL]}
    assert record["value"] == {
        "symbol": _SYMBOL,
        "exchange": exchange,
        "lot_size": 65,
        "instrument_id": "contract-1",
    }
    assert record["provenance"] == result.market_data["quote"]["provenance"]
    assert record["observed_at"] and record["source_as_of"] is None
    assert ("lot_sizes", BrokerSelector("dhan", "Quotes")) in [
        (operation, selector) for operation, selector, _ in runtime.adapter.calls
    ]
    canonical = json.dumps(
        result.market_data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    assert result.receipt["input_digest"] == hashlib.sha256(canonical.encode()).hexdigest()
    events = [
        event
        for filename in runtime.audit.list_audit_files()
        for event in runtime.audit.read_day(filename.removeprefix("audit_").removesuffix(".jsonl"))
    ]
    assert len(events) == 1
    assert events[0]["market_data"]["lot_size"] == record
    assert events[0]["input_digest"] == result.receipt["input_digest"]


def test_equity_context_does_not_request_or_invent_lots(runtime, monkeypatch):
    _install_lots(runtime, monkeypatch)
    result = _collect(runtime)
    assert "lot_size" not in result.market_data
    assert all(operation != "lot_sizes" for operation, _, _ in runtime.adapter.calls)


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [{"symbol": "OTHER", "exchange": "NFO", "lot_size": 65}],
        [{"symbol": _SYMBOL, "exchange": "BFO", "lot_size": 65}],
        [{"symbol": _SYMBOL, "exchange": "NFO", "lot_size": True}],
        [{"symbol": _SYMBOL, "exchange": "NFO", "lot_size": 0}],
        [{"symbol": _SYMBOL, "exchange": "NFO", "lot_size": 1_000_001}],
        [
            {"symbol": _SYMBOL, "exchange": "NFO", "lot_size": 65},
            {"symbol": _SYMBOL, "exchange": "NFO", "lot_size": 75},
        ],
    ],
)
def test_malformed_missing_or_conflicting_lots_refuse_without_audit(runtime, monkeypatch, rows):
    _install_lots(runtime, monkeypatch, rows)
    with pytest.raises(BrokerContextError, match="broker_context_invalid_response"):
        _collect(runtime, symbol=_SYMBOL, exchange="NFO")
    assert runtime.audit.list_audit_files() == []


def test_missing_lot_capability_does_not_fall_back_to_default(runtime):
    with pytest.raises(BrokerContextError, match="broker_context_read_failed"):
        _collect(runtime, symbol=_SYMBOL, exchange="NFO")


def test_authority_revoked_during_lot_read_cannot_publish_context(runtime, monkeypatch):
    _install_lots(runtime, monkeypatch, after_read=lambda: runtime.revoked.add("test-session"))
    with pytest.raises(BrokerContextError):
        _collect(runtime, symbol=_SYMBOL, exchange="NFO")
    assert runtime.audit.list_audit_files() == []
