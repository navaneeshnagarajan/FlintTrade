"""FT-MONDAY-003 — AI Chat Practice + native Connected (read) context.

Acceptance lock (2026-09-20):

- When an LLM is configured, Chat may read Practice SandboxEngine fills
  and native Dhan/Neo Connected (read) feeds for analysis
- Suggest stays labelled illustrative
- Chat never shows green Connected without a real LLM
- AI does not place Live orders
- Profitable alphas are not a Monday ship criterion
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from flinttrade_gateway.brokers._base import Session
from flinttrade_gateway.monday_read_smoke import (
    CHROME_CONNECTED_READ,
    NEO_OPERATOR_COPY,
    WRITE_VERBS,
    collect_monday_ai_read_snapshot,
    format_monday_ai_read_context,
    list_monday_ai_read_handles,
    stamp_monday_read_smoke,
)


class _ReadAdapter:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def quotes(self, _session: object, symbols: list[str]) -> list[dict]:
        self.calls.append("quotes")
        return [{"symbol": symbols[0], "ltp": 1400.0}]

    async def market_depth(self, _session: object, symbols: list[str]) -> list[dict]:
        self.calls.append("depth")
        return [{"symbol": symbols[0], "bids": [], "asks": []}]

    async def place_order(self, *_a: object, **_k: object) -> None:
        self.calls.append("place_order")
        raise AssertionError("Monday AI reads must not place")


def _session(*, smoke_ok: bool = True) -> Session:
    session = Session("synthetic-read", 1e12, "Main", "dhan")
    if smoke_ok:
        stamp_monday_read_smoke(session, True)
    return session


@pytest.mark.unit
@pytest.mark.asyncio
async def test_monday_ai_snapshot_reads_without_writes() -> None:
    """Stamped Connected (read) sessions yield quotes; write verbs stay dark."""
    adapter = _ReadAdapter()
    session = _session()
    row = await collect_monday_ai_read_snapshot("dhan", "Main", adapter, session)
    assert row["ok"] is True
    assert row["chrome"] == CHROME_CONNECTED_READ
    assert row["quotes"] == [{"symbol": "NSE:RELIANCE", "ltp": 1400.0}]
    assert adapter.calls == ["quotes", "depth"]
    assert "place_order" not in adapter.calls
    for verb in WRITE_VERBS:
        assert not hasattr(collect_monday_ai_read_snapshot, verb)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_monday_ai_snapshot_refuses_unstamped_session() -> None:
    """Login-only (no read_smoke_ok) never fabricates quotes."""
    adapter = _ReadAdapter()
    session = _session(smoke_ok=False)
    row = await collect_monday_ai_read_snapshot("dhan", "Main", adapter, session)
    assert row["ok"] is False
    assert row["quotes"] is None
    assert adapter.calls == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_monday_ai_snapshot_rejects_non_monday_broker() -> None:
    """Upstox / others are not the Monday AI live-read path."""
    adapter = _ReadAdapter()
    session = _session()
    with pytest.raises(ValueError, match="Dhan \\+ Neo"):
        await collect_monday_ai_read_snapshot("upstox", "Main", adapter, session)
    assert adapter.calls == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_neo_snapshot_keeps_live_read_only_copy() -> None:
    """Neo analysis context never invents Practice."""
    adapter = _ReadAdapter()
    session = Session("synthetic-neo", 1e12, "Neo", "kotakneo")
    stamp_monday_read_smoke(session, True)
    row = await collect_monday_ai_read_snapshot("kotakneo", "Neo", adapter, session)
    assert row["ok"] is True
    assert row["operator_copy"] == NEO_OPERATOR_COPY
    formatted = format_monday_ai_read_context([row])
    assert "not Neo Practice" in formatted
    assert NEO_OPERATOR_COPY in formatted
    assert "Practice" not in formatted.replace("not Neo Practice", "")


@pytest.mark.unit
def test_format_skips_failed_rows() -> None:
    assert format_monday_ai_read_context([{"ok": False, "quotes": [{"ltp": 1}]}]) == ""


@pytest.mark.unit
def test_list_handles_filters_to_stamped_dhan_neo() -> None:
    dhan = _session()
    neo = Session("synthetic-neo", 1e12, "Neo", "kotakneo")
    stamp_monday_read_smoke(neo, True)
    upstox = Session("synthetic-up", 1e12, "Up", "upstox")
    stamp_monday_read_smoke(upstox, True)
    registry = SimpleNamespace(
        list_read_smoke_sessions=lambda: (
            (SimpleNamespace(adapter_id="dhan", account_id="Main"), dhan),
            (SimpleNamespace(adapter_id="kotakneo", account_id="Neo"), neo),
            (SimpleNamespace(adapter_id="upstox", account_id="Up"), upstox),
        )
    )
    handles = list_monday_ai_read_handles(registry)
    assert [(broker, account) for broker, account, _ in handles] == [
        ("dhan", "Main"),
        ("kotakneo", "Neo"),
    ]
