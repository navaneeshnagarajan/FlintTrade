"""T4-A (gap G4): composite (adapter_id, account_id) session store on BrokerRegistry.

The selector-keyed adapter-session store the BrokerRouter resolves against,
additive to the legacy account_id-only ``get_session`` used by OpenAlgo reads.
"""

from __future__ import annotations

import pytest

from flinttrade_gateway.registry import BrokerRegistry
from flinttrade_gateway.exceptions import BrokerNotFoundError


def test_put_and_get_session_for_round_trip() -> None:
    reg = BrokerRegistry()
    s_personal = object()
    s_family = object()
    reg.put_session("dhan", "personal", s_personal)
    reg.put_session("dhan", "family", s_family)
    assert reg.get_session_for("dhan", "personal") is s_personal
    assert reg.get_session_for("dhan", "family") is s_family


def test_get_session_for_missing_raises_naming_selector() -> None:
    reg = BrokerRegistry()
    with pytest.raises(BrokerNotFoundError, match="selector"):
        reg.get_session_for("dhan", "personal")


def test_composite_store_independent_of_legacy_account_map() -> None:
    # Storing in the composite adapter-session store must not register the
    # account in the legacy account_id-keyed map.
    reg = BrokerRegistry()
    reg.put_session("dhan", "personal", object())
    with pytest.raises(BrokerNotFoundError):
        reg.get_session("personal")
