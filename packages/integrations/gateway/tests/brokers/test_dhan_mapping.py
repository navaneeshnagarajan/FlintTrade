"""Tests for the canonical-to-Dhan mapping tables.

Values are checked against the official DhanHQ Agent Skill / v2 SDK constants,
and a drift invariant asserts the mapping covers every exchange Dhan advertises
in BROKER_CATALOG.
"""

from __future__ import annotations

import pytest

from flinttrade_gateway.adapter import BROKER_CATALOG
from flinttrade_gateway.brokers import dhan_mapping as m

pytestmark = pytest.mark.unit


def test_order_type_map_matches_dhan_sdk_constants() -> None:
    assert m.ORDER_TYPE_MAP == {
        "MARKET": "MARKET",
        "LIMIT": "LIMIT",
        "SL": "STOP_LOSS",
        "SLM": "STOP_LOSS_MARKET",
    }


def test_product_map_uses_dhan_names() -> None:
    # Dhan uses INTRADAY/MARGIN, not the MIS/NRML canonical names.
    assert m.PRODUCT_MAP["MIS"] == "INTRADAY"
    assert m.PRODUCT_MAP["NRML"] == "MARGIN"
    assert m.PRODUCT_MAP["CNC"] == "CNC"
    assert m.PRODUCT_MAP["MTF"] == "MTF"


def test_validity_map_routes_gtt_to_forever() -> None:
    assert m.VALIDITY_MAP["GTT"] == "FOREVER"
    assert m.VALIDITY_MAP["DAY"] == "DAY"
    assert m.VALIDITY_MAP["IOC"] == "IOC"


def test_exchange_segment_map_values() -> None:
    assert m.EXCHANGE_SEGMENT_MAP["NSE"] == "NSE_EQ"
    assert m.EXCHANGE_SEGMENT_MAP["NFO"] == "NSE_FNO"
    assert m.EXCHANGE_SEGMENT_MAP["BFO"] == "BSE_FNO"
    assert m.EXCHANGE_SEGMENT_MAP["MCX"] == "MCX_COMM"
    assert m.EXCHANGE_SEGMENT_MAP["CDS"] == "NSE_CURRENCY"
    assert m.EXCHANGE_SEGMENT_MAP["NSE_INDEX"] == "IDX_I"


def test_to_dhan_segment_is_case_insensitive_and_raises_on_unknown() -> None:
    assert m.to_dhan_segment("nse") == "NSE_EQ"
    assert m.to_dhan_segment("Nfo") == "NSE_FNO"
    with pytest.raises(KeyError):
        m.to_dhan_segment("NASDAQ")


def test_index_security_ids_match_skill_table() -> None:
    # From the DhanHQ skill "Instrument Resolution Rules" quick-reference table.
    assert m.INDEX_SECURITY_IDS["NIFTY 50"] == ("13", "IDX_I")
    assert m.INDEX_SECURITY_IDS["BANKNIFTY"] == ("25", "IDX_I")
    assert m.INDEX_SECURITY_IDS["FINNIFTY"] == ("27", "IDX_I")
    assert m.INDEX_SECURITY_IDS["MIDCPNIFTY"] == ("442", "IDX_I")
    assert m.INDEX_SECURITY_IDS["SENSEX"] == ("51", "IDX_I")


def test_every_advertised_dhan_exchange_has_a_segment_mapping() -> None:
    """Drift guard: each exchange Dhan advertises in BROKER_CATALOG must map.

    Without this, the catalog could advertise an exchange the adapter cannot
    actually route an order to.
    """
    advertised = BROKER_CATALOG["dhan"].exchanges
    missing = [e for e in advertised if e not in m.EXCHANGE_SEGMENT_MAP]
    assert not missing, f"Dhan exchanges with no segment mapping: {missing}"
