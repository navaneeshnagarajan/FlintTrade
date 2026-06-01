"""T4-A (gap G4): composite (adapter_id, account_id) session store on BrokerRegistry.

The selector-keyed adapter-session store the BrokerRouter resolves against,
additive to the legacy account_id-only ``get_session`` used by OpenAlgo reads.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from flinttrade_gateway.registry import BrokerRegistry
from flinttrade_gateway.models import AccountStatus, BrokerAccountInfo
from flinttrade_gateway.exceptions import BrokerNotFoundError

_SESSION_PATCH = "flinttrade_gateway.registry.BrokerSession"


def _make_mock_session(account_id: str, broker: str, label: str) -> MagicMock:
    """Return a MagicMock mimicking a successfully-authenticated BrokerSession."""
    mock = MagicMock()
    mock.authenticate.return_value = None
    mock.disconnect.return_value = None
    mock.info = BrokerAccountInfo(
        account_id=account_id,
        broker=broker,
        label=label,
        status=AccountStatus.connected,
        is_primary=False,
    )
    return mock


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


def test_remove_session_for_evicts_composite_entry() -> None:
    # After remove_session_for, the selector must no longer resolve.
    reg = BrokerRegistry()
    reg.put_session("dhan", "personal", object())
    reg.remove_session_for("dhan", "personal")
    with pytest.raises(BrokerNotFoundError, match="selector"):
        reg.get_session_for("dhan", "personal")


def test_remove_session_for_absent_is_silent_noop() -> None:
    # Evicting a selector that was never registered must not raise.
    reg = BrokerRegistry()
    reg.remove_session_for("dhan", "personal")  # no error


def test_remove_account_evicts_matching_composite_entries() -> None:
    # remove_account must purge composite entries whose account_id matches,
    # while leaving entries for other accounts intact.
    reg = BrokerRegistry()
    mock_session = _make_mock_session("personal", "dhan", "Personal Dhan")
    with patch(_SESSION_PATCH, return_value=mock_session):
        reg.add_account("personal", "dhan", "Personal Dhan", {"api_key": "k"})

    keep = object()
    reg.put_session("dhan", "personal", object())
    reg.put_session("openalgo", "personal", object())
    reg.put_session("dhan", "family", keep)

    reg.remove_account("personal")

    # Both "personal" composite selectors are gone...
    with pytest.raises(BrokerNotFoundError, match="selector"):
        reg.get_session_for("dhan", "personal")
    with pytest.raises(BrokerNotFoundError, match="selector"):
        reg.get_session_for("openalgo", "personal")
    # ...but the unrelated "family" selector survives.
    assert reg.get_session_for("dhan", "family") is keep
