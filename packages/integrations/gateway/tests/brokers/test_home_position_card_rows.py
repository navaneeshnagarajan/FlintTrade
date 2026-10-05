"""The Home positions card is tested against live adapter rows, not a stub.

``adapterPositionRows.json`` is what ``from_dhan_position`` and
``from_kotak_position`` return for the payloads below. PositionsCard renders
that file. This test fails when either mapper drifts from the file.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from flinttrade_gateway.brokers.dhan_mapping import from_dhan_position
from flinttrade_gateway.brokers.kotakneo_mapping import from_kotak_position

_FIXTURE = (
    Path(__file__).resolve().parents[5]
    / "packages/apps/terminal/src/routes/home/__tests__/fixtures/adapterPositionRows.json"
)

_DHAN_WITHOUT_PNL = {
    "tradingSymbol": "NIFTY-JUN2026-FUT",
    "exchangeSegment": "NSE_FNO",
    "productType": "MARGIN",
    "netQty": 50,
    "costPrice": 22000,
    "buyAvg": 22100,
}

_DHAN_WITH_PNL = {
    "tradingSymbol": "BANKNIFTY-JUN2026-FUT",
    "exchangeSegment": "NSE_FNO",
    "productType": "MARGIN",
    "netQty": 15,
    "costPrice": 48000,
    "sellAvg": 48100,
    "realizedProfit": 0,
    "unrealizedProfit": -250,
}

_DHAN_NO_COST = {
    "tradingSymbol": "IDEA",
    "exchangeSegment": "NSE_EQ",
    "productType": "CNC",
    "netQty": 10,
}

_NEO_OPEN_LEG = {
    "trdSym": "NIFTY25JUNFUT",
    "exSeg": "nse_fo",
    "prod": "NRML",
    "cfBuyQty": 50,
    "flBuyQty": 0,
    "cfSellQty": 0,
    "flSellQty": 0,
    "cfBuyAmt": 1_100_000,
    "buyAmt": 0,
    "cfSellAmt": 0,
    "sellAmt": 0,
    "genNum": 1,
    "genDen": 1,
    "prcNum": 1,
    "prcDen": 1,
    "multiplier": 1,
    "precision": 2,
}

_NEO_NO_COST = {
    "trdSym": "RELIANCE",
    "exSeg": "nse_cm",
    "prod": "CNC",
    "cfBuyQty": 5,
    "flBuyQty": 0,
    "cfSellQty": 0,
    "flSellQty": 0,
}


@pytest.mark.unit
def test_home_position_card_rows_match_live_adapters() -> None:
    """Dhan and Neo rows omit pnlPercent. The card fixture is their real output."""
    fixture = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    rows = {
        "dhan_without_pnl": from_dhan_position(_DHAN_WITHOUT_PNL),
        "dhan_with_pnl": from_dhan_position(_DHAN_WITH_PNL),
        "dhan_no_cost": from_dhan_position(_DHAN_NO_COST),
        "neo_open_leg": from_kotak_position(_NEO_OPEN_LEG),
        "neo_no_cost": from_kotak_position(_NEO_NO_COST),
    }

    assert rows == fixture
    for name, row in rows.items():
        assert "pnlPercent" not in row, name
        assert "pnl_percent" not in row, name
    assert "pnl" not in rows["dhan_without_pnl"]
    assert "average_price" not in rows["dhan_no_cost"]
    assert "average_price" not in rows["neo_no_cost"]
    assert rows["dhan_with_pnl"]["pnl"] == "-250.0"
    assert rows["dhan_with_pnl"]["average_price"] == "48000"
    assert rows["neo_open_leg"]["pnl"] == "0.00"
    assert rows["neo_open_leg"]["average_price"] == "22000.00"
