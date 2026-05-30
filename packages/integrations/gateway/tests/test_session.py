"""Tests for BrokerSession auth lifecycle and API delegation.

All tests mock the adapter — no real broker imports are required.
The adapter loader is patched at its definition site so that
BrokerSession.authenticate() and every delegation method receive
a MagicMock instead of a real adapter.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from typing import Any

import pytest

from flinttrade_gateway.session import BrokerSession
from flinttrade_gateway.models import AccountStatus, BrokerAccountInfo
from flinttrade_gateway.exceptions import SessionError, AuthFlowError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ACCOUNT_ID = "AB1234"
_BROKER = "zerodha"
_LABEL = "Primary Zerodha"
_TOKEN = "tok_abc123"

# Patch target: the loader function *inside* the adapter module that
# session.py imported from.  We patch the name as it appears in session.py's
# namespace so every internal call goes through the mock.
_PATCH_TARGET = "flinttrade_gateway.session.load_broker_adapter"


def _make_session() -> BrokerSession:
    """Return a fresh disconnected session."""
    return BrokerSession(_ACCOUNT_ID, _BROKER, _LABEL)


def _connected_session(mock_adapter: MagicMock) -> BrokerSession:
    """Return a session that has already authenticated successfully."""
    session = _make_session()
    mock_adapter.authenticate.return_value = (_TOKEN, None)
    with patch(_PATCH_TARGET, return_value=mock_adapter):
        session.authenticate({"api_key": "key", "totp": "123456"})
    return session


# ---------------------------------------------------------------------------
# 1. Initial state
# ---------------------------------------------------------------------------


class TestInitialState:
    def test_initial_state_disconnected(self) -> None:
        """A newly created session must start in the DISCONNECTED state."""
        session = _make_session()
        assert session.info.status == AccountStatus.disconnected

    def test_is_connected_false_on_creation(self) -> None:
        """is_connected must be False before authenticate() is called."""
        session = _make_session()
        assert session.is_connected is False


# ---------------------------------------------------------------------------
# 2. info property
# ---------------------------------------------------------------------------


class TestInfoProperty:
    def test_info_returns_broker_account_info(self) -> None:
        """info property returns a BrokerAccountInfo with correct field values."""
        session = _make_session()
        info = session.info
        assert isinstance(info, BrokerAccountInfo)
        assert info.account_id == _ACCOUNT_ID
        assert info.broker == _BROKER
        assert info.label == _LABEL
        assert info.status == AccountStatus.disconnected
        assert info.connected_at is None
        assert info.error_message is None

    def test_info_is_snapshot_not_live_reference(self) -> None:
        """Each call to info must return a fresh snapshot."""
        session = _make_session()
        info1 = session.info
        info2 = session.info
        # They should be equal but not the same object
        assert info1 == info2
        assert info1 is not info2


# ---------------------------------------------------------------------------
# 3. authenticate — success path
# ---------------------------------------------------------------------------


class TestAuthenticateSuccess:
    def test_authenticate_success_sets_connected_status(self) -> None:
        """On success authenticate() must set status to CONNECTED."""
        mock_adapter = MagicMock()
        mock_adapter.authenticate.return_value = (_TOKEN, None)
        session = _make_session()
        with patch(_PATCH_TARGET, return_value=mock_adapter):
            session.authenticate({"api_key": "key"})
        assert session.info.status == AccountStatus.connected

    def test_authenticate_success_sets_is_connected(self) -> None:
        """is_connected must be True after a successful authenticate()."""
        mock_adapter = MagicMock()
        mock_adapter.authenticate.return_value = (_TOKEN, None)
        session = _make_session()
        with patch(_PATCH_TARGET, return_value=mock_adapter):
            session.authenticate({"api_key": "key"})
        assert session.is_connected is True

    def test_authenticate_success_stores_connected_at_timestamp(self) -> None:
        """connected_at must be populated with a UTC datetime on success."""
        from datetime import timezone
        mock_adapter = MagicMock()
        mock_adapter.authenticate.return_value = (_TOKEN, None)
        session = _make_session()
        with patch(_PATCH_TARGET, return_value=mock_adapter):
            session.authenticate({"api_key": "key"})
        assert session.info.connected_at is not None
        assert session.info.connected_at.tzinfo is not None
        assert session.info.connected_at.tzinfo == timezone.utc

    def test_authenticate_success_clears_error_message(self) -> None:
        """error_message must be None after a successful authenticate()."""
        mock_adapter = MagicMock()
        mock_adapter.authenticate.return_value = (_TOKEN, None)
        session = _make_session()
        with patch(_PATCH_TARGET, return_value=mock_adapter):
            session.authenticate({"api_key": "key"})
        assert session.info.error_message is None

    def test_authenticate_passes_credentials_to_adapter(self) -> None:
        """authenticate() must forward credentials verbatim to the adapter."""
        mock_adapter = MagicMock()
        mock_adapter.authenticate.return_value = (_TOKEN, None)
        creds = {"api_key": "mykey", "totp": "654321"}
        session = _make_session()
        with patch(_PATCH_TARGET, return_value=mock_adapter):
            session.authenticate(creds)
        mock_adapter.authenticate.assert_called_once_with(creds)


# ---------------------------------------------------------------------------
# 4. authenticate — failure path
# ---------------------------------------------------------------------------


class TestAuthenticateFailure:
    def test_authenticate_failure_sets_error_status(self) -> None:
        """On failure authenticate() must set status to ERROR."""
        mock_adapter = MagicMock()
        mock_adapter.authenticate.return_value = (None, "TOTP mismatch")
        session = _make_session()
        with patch(_PATCH_TARGET, return_value=mock_adapter):
            with pytest.raises(AuthFlowError):
                session.authenticate({"api_key": "bad"})
        assert session.info.status == AccountStatus.error

    def test_authenticate_failure_stores_error_message(self) -> None:
        """The broker's error description must appear in info.error_message."""
        mock_adapter = MagicMock()
        mock_adapter.authenticate.return_value = (None, "Invalid API key")
        session = _make_session()
        with patch(_PATCH_TARGET, return_value=mock_adapter):
            with pytest.raises(AuthFlowError):
                session.authenticate({"api_key": "bad"})
        assert session.info.error_message == "Invalid API key"

    def test_authenticate_failure_raises_auth_flow_error(self) -> None:
        """authenticate() must raise AuthFlowError on broker-reported failure."""
        mock_adapter = MagicMock()
        mock_adapter.authenticate.return_value = (None, "Session limit reached")
        session = _make_session()
        with patch(_PATCH_TARGET, return_value=mock_adapter):
            with pytest.raises(AuthFlowError, match="Session limit reached"):
                session.authenticate({"api_key": "x"})

    def test_authenticate_failure_leaves_not_connected(self) -> None:
        """is_connected must remain False after a failed authenticate()."""
        mock_adapter = MagicMock()
        mock_adapter.authenticate.return_value = (None, "Error")
        session = _make_session()
        with patch(_PATCH_TARGET, return_value=mock_adapter):
            with pytest.raises(AuthFlowError):
                session.authenticate({"api_key": "x"})
        assert session.is_connected is False


# ---------------------------------------------------------------------------
# 5. _ensure_connected — SessionError when not connected
# ---------------------------------------------------------------------------


class TestEnsureConnected:
    def test_get_positions_when_disconnected_raises_session_error(self) -> None:
        """get_positions() must raise SessionError when not connected."""
        session = _make_session()
        with pytest.raises(SessionError):
            session.get_positions()

    def test_get_orders_when_disconnected_raises_session_error(self) -> None:
        """get_orders() must raise SessionError when not connected."""
        session = _make_session()
        with pytest.raises(SessionError):
            session.get_orders()

    def test_get_quotes_when_disconnected_raises_session_error(self) -> None:
        """get_quotes() must raise SessionError when not connected."""
        session = _make_session()
        with pytest.raises(SessionError):
            session.get_quotes(["NIFTY"])

    def test_get_funds_when_disconnected_raises_session_error(self) -> None:
        """get_funds() must raise SessionError when not connected."""
        session = _make_session()
        with pytest.raises(SessionError):
            session.get_funds()


# ---------------------------------------------------------------------------
# 6. order write methods REMOVED (S7 / contract §12)
#
# place_order / modify_order / cancel_order / cancel_all_orders /
# close_position / place_options_order bypassed the SafetyContext/gate/mode
# check, so they were deleted from BrokerSession. Writes now flow through
# flinttrade_engine.safety.gate_order() → BrokerRouter.place_order(), covered
# by test_router.py + test_gate_order.py. The §8.1 grep guard
# test_session_exposes_no_write_methods asserts the methods stay gone.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 7. disconnect
# ---------------------------------------------------------------------------


class TestDisconnect:
    def test_disconnect_clears_state(self) -> None:
        """After disconnect(), status is DISCONNECTED and is_connected is False."""
        mock_adapter = MagicMock()
        mock_adapter.authenticate.return_value = (_TOKEN, None)
        session = _make_session()
        with patch(_PATCH_TARGET, return_value=mock_adapter):
            session.authenticate({"api_key": "key"})
            assert session.is_connected is True
            session.disconnect()
        assert session.info.status == AccountStatus.disconnected
        assert session.is_connected is False

    def test_disconnect_clears_connected_at(self) -> None:
        """connected_at must be None after disconnect()."""
        mock_adapter = MagicMock()
        mock_adapter.authenticate.return_value = (_TOKEN, None)
        session = _make_session()
        with patch(_PATCH_TARGET, return_value=mock_adapter):
            session.authenticate({"api_key": "key"})
            assert session.info.connected_at is not None
            session.disconnect()
        assert session.info.connected_at is None

    def test_disconnect_prevents_api_calls(self) -> None:
        """After disconnect(), a read call must raise SessionError again."""
        mock_adapter = MagicMock()
        mock_adapter.authenticate.return_value = (_TOKEN, None)
        session = _make_session()
        with patch(_PATCH_TARGET, return_value=mock_adapter):
            session.authenticate({"api_key": "key"})
            session.disconnect()
        with pytest.raises(SessionError):
            session.get_positions()


# ---------------------------------------------------------------------------
# 8. _load_adapter called once (caching)
# ---------------------------------------------------------------------------


class TestAdapterCaching:
    def test_load_adapter_called_once(self) -> None:
        """load_broker_adapter must be called exactly once even after multiple API calls."""
        mock_adapter = MagicMock()
        mock_adapter.authenticate.return_value = (_TOKEN, None)
        mock_adapter.get_positions.return_value = {"positions": []}
        mock_adapter.get_orders.return_value = {"orders": []}
        mock_adapter.get_funds.return_value = {"funds": {}}
        session = _make_session()
        with patch(_PATCH_TARGET, return_value=mock_adapter) as mock_loader:
            session.authenticate({"api_key": "key"})
            session.get_positions()
            session.get_orders()
            session.get_funds()
            # load_broker_adapter should have been called exactly once
            mock_loader.assert_called_once_with(_BROKER)

    def test_adapter_reused_across_calls(self) -> None:
        """The cached adapter instance must be used for all method calls."""
        mock_adapter = MagicMock()
        mock_adapter.authenticate.return_value = (_TOKEN, None)
        mock_adapter.get_positions.return_value = {"positions": []}
        mock_adapter.get_holdings.return_value = {"holdings": []}
        session = _make_session()
        with patch(_PATCH_TARGET, return_value=mock_adapter):
            session.authenticate({"api_key": "key"})
            session.get_positions()
            session.get_holdings()
        # Both calls went to the same mock_adapter instance
        mock_adapter.get_positions.assert_called_once()
        mock_adapter.get_holdings.assert_called_once()


# ---------------------------------------------------------------------------
# 9. get_positions delegates
# ---------------------------------------------------------------------------


class TestGetPositionsDelegation:
    def test_get_positions_delegates(self) -> None:
        """get_positions() must call adapter.get_positions with auth token."""
        mock_adapter = MagicMock()
        mock_adapter.authenticate.return_value = (_TOKEN, None)
        positions_response: dict[str, Any] = {
            "status": "success",
            "data": [
                {"symbol": "NIFTY25JUN21000CE", "qty": 50, "pnl": 1500.0}
            ],
        }
        mock_adapter.get_positions.return_value = positions_response
        session = _make_session()
        with patch(_PATCH_TARGET, return_value=mock_adapter):
            session.authenticate({"api_key": "key"})
            result = session.get_positions()
        mock_adapter.get_positions.assert_called_once_with(_TOKEN)
        assert result == positions_response

    def test_get_orders_delegates(self) -> None:
        """get_orders() must call adapter.get_orders with auth token."""
        mock_adapter = MagicMock()
        mock_adapter.authenticate.return_value = (_TOKEN, None)
        mock_adapter.get_orders.return_value = {"orders": []}
        session = _make_session()
        with patch(_PATCH_TARGET, return_value=mock_adapter):
            session.authenticate({"api_key": "key"})
            session.get_orders()
        mock_adapter.get_orders.assert_called_once_with(_TOKEN)

    def test_get_trades_delegates(self) -> None:
        """get_trades() must call adapter.get_trades with auth token."""
        mock_adapter = MagicMock()
        mock_adapter.authenticate.return_value = (_TOKEN, None)
        mock_adapter.get_trades.return_value = {"trades": []}
        session = _make_session()
        with patch(_PATCH_TARGET, return_value=mock_adapter):
            session.authenticate({"api_key": "key"})
            session.get_trades()
        mock_adapter.get_trades.assert_called_once_with(_TOKEN)

    def test_get_holdings_delegates(self) -> None:
        """get_holdings() must call adapter.get_holdings with auth token."""
        mock_adapter = MagicMock()
        mock_adapter.authenticate.return_value = (_TOKEN, None)
        mock_adapter.get_holdings.return_value = {"holdings": []}
        session = _make_session()
        with patch(_PATCH_TARGET, return_value=mock_adapter):
            session.authenticate({"api_key": "key"})
            session.get_holdings()
        mock_adapter.get_holdings.assert_called_once_with(_TOKEN)

    def test_get_funds_delegates(self) -> None:
        """get_funds() must call adapter.get_funds with auth token."""
        mock_adapter = MagicMock()
        mock_adapter.authenticate.return_value = (_TOKEN, None)
        mock_adapter.get_funds.return_value = {"available": 100000.0}
        session = _make_session()
        with patch(_PATCH_TARGET, return_value=mock_adapter):
            session.authenticate({"api_key": "key"})
            result = session.get_funds()
        mock_adapter.get_funds.assert_called_once_with(_TOKEN)
        assert result == {"available": 100000.0}

    def test_get_margin_delegates(self) -> None:
        """get_margin() must call adapter.get_margin with order_data and token."""
        mock_adapter = MagicMock()
        mock_adapter.authenticate.return_value = (_TOKEN, None)
        mock_adapter.get_margin.return_value = {"required": 15000.0}
        session = _make_session()
        order_data = {"symbol": "NIFTY", "qty": 50}
        with patch(_PATCH_TARGET, return_value=mock_adapter):
            session.authenticate({"api_key": "key"})
            session.get_margin(order_data)
        mock_adapter.get_margin.assert_called_once_with(order_data, _TOKEN)


# ---------------------------------------------------------------------------
# 10. get_quotes delegates
# ---------------------------------------------------------------------------


class TestGetQuotesDelegation:
    def test_get_quotes_delegates(self) -> None:
        """get_quotes() must call adapter.get_quotes with symbols list and token."""
        mock_adapter = MagicMock()
        mock_adapter.authenticate.return_value = (_TOKEN, None)
        quotes_response: dict[str, Any] = {
            "NIFTY": {"ltp": 22500.0, "volume": 1_000_000},
            "BANKNIFTY": {"ltp": 48000.0, "volume": 500_000},
        }
        mock_adapter.get_quotes.return_value = quotes_response
        session = _make_session()
        symbols = ["NIFTY", "BANKNIFTY"]
        with patch(_PATCH_TARGET, return_value=mock_adapter):
            session.authenticate({"api_key": "key"})
            result = session.get_quotes(symbols)
        mock_adapter.get_quotes.assert_called_once_with(symbols, _TOKEN)
        assert result == quotes_response

    def test_get_depth_delegates(self) -> None:
        """get_depth() must call adapter.get_depth with symbol and token."""
        mock_adapter = MagicMock()
        mock_adapter.authenticate.return_value = (_TOKEN, None)
        mock_adapter.get_depth.return_value = {"bids": [], "asks": []}
        session = _make_session()
        with patch(_PATCH_TARGET, return_value=mock_adapter):
            session.authenticate({"api_key": "key"})
            session.get_depth("NIFTY")
        mock_adapter.get_depth.assert_called_once_with("NIFTY", _TOKEN)

    def test_get_history_delegates(self) -> None:
        """get_history() must call adapter.get_history with params and token."""
        mock_adapter = MagicMock()
        mock_adapter.authenticate.return_value = (_TOKEN, None)
        mock_adapter.get_history.return_value = {"candles": []}
        session = _make_session()
        params = {"symbol": "NIFTY", "interval": "5m", "from": "2026-03-01", "to": "2026-03-24"}
        with patch(_PATCH_TARGET, return_value=mock_adapter):
            session.authenticate({"api_key": "key"})
            session.get_history(params)
        mock_adapter.get_history.assert_called_once_with(params, _TOKEN)

    def test_search_symbols_delegates(self) -> None:
        """search_symbols() must call adapter.search_symbols with query and token."""
        mock_adapter = MagicMock()
        mock_adapter.authenticate.return_value = (_TOKEN, None)
        mock_adapter.search_symbols.return_value = {"results": [{"symbol": "NIFTY"}]}
        session = _make_session()
        with patch(_PATCH_TARGET, return_value=mock_adapter):
            session.authenticate({"api_key": "key"})
            result = session.search_symbols("NIFTY")
        mock_adapter.search_symbols.assert_called_once_with("NIFTY", _TOKEN)
        assert result == {"results": [{"symbol": "NIFTY"}]}
