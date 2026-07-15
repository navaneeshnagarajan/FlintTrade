"""Tests for WheelStrategy (live engine).

All tests are fully in-process — no live broker / network calls.
The OpenAlgo client is replaced with an AsyncMock throughout.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock


IST_OFFSET = 5.5 * 3600  # seconds — used for offset-aware datetimes if needed


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _mock_client(
    spot_ltp: float = 22000.0,
    option_ltp: float = 80.0,
    expiry_dates: list[str] | None = None,
) -> MagicMock:
    """Build a fully-mocked OpenAlgoClient for wheel strategy tests."""
    client = MagicMock()

    # quotes → returns a Quote-like object with .ltp
    quote_mock = MagicMock()
    quote_mock.ltp = spot_ltp

    option_quote_mock = MagicMock()
    option_quote_mock.ltp = option_ltp

    async def mock_quotes(symbol: str, exchange: str = "NSE") -> MagicMock:
        if exchange in ("NSE", "NSE_INDEX"):
            return quote_mock
        return option_quote_mock

    client.quotes = mock_quotes

    # expiry → returns a dict with {"data": {"expiry": [...]}}
    dates = expiry_dates or ["27-Apr-2025", "08-May-2025"]

    async def mock_expiry(symbol: str, exchange: str = "NFO") -> dict:
        return {"data": {"expiry": dates}}

    client.expiry = mock_expiry

    # place_order → AsyncMock (no return value needed)
    client.place_order = AsyncMock(return_value={"status": "success"})

    # telegram → AsyncMock
    client.telegram = AsyncMock(return_value={"status": "success"})

    return client


def _strategy(
    client=None,
    symbol: str = "NIFTY",
    quantity: int = 50,
    spot: float = 22000.0,
    option_ltp: float = 80.0,
    expiry_dates: list[str] | None = None,
):
    from flinttrade_engine.strategies.wheel_live import WheelStrategy
    c = client or _mock_client(spot_ltp=spot, option_ltp=option_ltp, expiry_dates=expiry_dates)
    strat = WheelStrategy(symbol=symbol, exchange="NFO", product="MIS", quantity=quantity, client=c)
    strat.start()
    return strat, c


def _run(coro):
    return asyncio.run(coro)


# ===========================================================================
# WheelPhase enum
# ===========================================================================


class TestWheelPhase:
    def test_phase_values(self):
        from flinttrade_engine.strategies.wheel_live import WheelPhase
        assert WheelPhase.WAITING_CSP == "WAITING_CSP"
        assert WheelPhase.CSP_ACTIVE == "CSP_ACTIVE"
        assert WheelPhase.ASSIGNED == "ASSIGNED"
        assert WheelPhase.CC_ACTIVE == "CC_ACTIVE"
        assert WheelPhase.CC_EXPIRED == "CC_EXPIRED"


# ===========================================================================
# Initial state
# ===========================================================================


class TestWheelStrategyInit:
    def test_initial_phase_is_waiting_csp(self):
        from flinttrade_engine.strategies.wheel_live import WheelPhase
        strat, _ = _strategy()
        assert strat.phase == WheelPhase.WAITING_CSP

    def test_strategy_starts_active(self):
        from flinttrade_engine.strategy import StrategyState
        strat, _ = _strategy()
        assert strat.state == StrategyState.ACTIVE

    def test_generate_orders_empty_initially(self):
        strat, _ = _strategy()
        assert strat.generate_orders() == []


# ===========================================================================
# CSP entry
# ===========================================================================


class TestWheelCSPEntry:
    def test_run_cycle_waiting_csp_places_sell_and_sl(self):
        strat, client = _strategy(option_ltp=80.0)
        _run(strat.run_cycle())
        from flinttrade_engine.strategies.wheel_live import WheelPhase
        assert strat.phase == WheelPhase.CSP_ACTIVE

    def test_csp_entry_sends_telegram(self):
        strat, client = _strategy(option_ltp=80.0)
        _run(strat.run_cycle())
        assert client.telegram.called

    def test_csp_entry_emits_two_intents_without_raw_client_write(self):
        """Sell + SL buy are queued for the canonical gated strategy runtime."""
        strat, client = _strategy(option_ltp=80.0)
        _run(strat.run_cycle())
        orders = strat.generate_orders()
        assert [(order.action.value, order.pricetype.value) for order in orders] == [
            ("SELL", "MARKET"),
            ("BUY", "SL"),
        ]
        client.place_order.assert_not_awaited()

    def test_csp_sl_price_is_30pct_above_premium(self):
        strat, client = _strategy(option_ltp=100.0)
        _run(strat.run_cycle())
        assert abs(strat._sl_price - 130.0) < 0.5

    def test_premium_below_minimum_skips_entry(self):
        from flinttrade_engine.strategies.wheel_live import WheelPhase
        strat, client = _strategy(option_ltp=5.0)  # below MIN_PREMIUM=10
        _run(strat.run_cycle())
        # Phase should NOT have advanced past WAITING_CSP
        assert strat.phase == WheelPhase.WAITING_CSP
        assert client.place_order.call_count == 0


# ===========================================================================
# CSP status check — assignment detection
# ===========================================================================


class TestWheelCSPAssignment:
    def test_assignment_when_spot_below_put_strike(self):
        from flinttrade_engine.strategies.wheel_live import WheelPhase
        strat, client = _strategy(spot=22000.0, option_ltp=80.0)
        # Enter CSP: put strike will be rounded from 22000 → put_strike = 22000
        _run(strat.run_cycle())  # → CSP_ACTIVE, put_strike set

        # Now simulate spot dropping below put strike
        put_strike = strat._put_strike
        client.quotes = AsyncMock(return_value=MagicMock(ltp=put_strike - 200))

        _run(strat.run_cycle())  # should detect assignment
        assert strat.phase == WheelPhase.ASSIGNED

    def test_no_assignment_when_spot_above_put_strike(self):
        from flinttrade_engine.strategies.wheel_live import WheelPhase
        strat, client = _strategy(spot=22000.0, option_ltp=80.0)
        _run(strat.run_cycle())  # → CSP_ACTIVE

        put_strike = strat._put_strike
        # Spot stays above put_strike
        client.quotes = AsyncMock(return_value=MagicMock(ltp=put_strike + 200))
        _run(strat.run_cycle())  # check — spot is above, no assignment
        assert strat.phase == WheelPhase.CSP_ACTIVE


# ===========================================================================
# Covered call entry
# ===========================================================================


class TestWheelCCEntry:
    def _reach_assigned_state(self, spot=22000.0, option_ltp=80.0):
        from flinttrade_engine.strategies.wheel_live import WheelPhase
        strat, client = _strategy(spot=spot, option_ltp=option_ltp)
        _run(strat.run_cycle())  # → CSP_ACTIVE

        put_strike = strat._put_strike
        client.quotes = AsyncMock(return_value=MagicMock(ltp=put_strike - 300))
        _run(strat.run_cycle())  # → ASSIGNED
        assert strat.phase == WheelPhase.ASSIGNED
        return strat, client

    def test_cc_entered_from_assigned(self):
        from flinttrade_engine.strategies.wheel_live import WheelPhase
        strat, client = self._reach_assigned_state()
        # Restore option_ltp to valid value for CC
        client.quotes = AsyncMock(return_value=MagicMock(ltp=100.0))
        _run(strat.run_cycle())  # → CC_ACTIVE
        assert strat.phase == WheelPhase.CC_ACTIVE

    def test_cc_sl_price_is_30pct_above_premium(self):
        strat, client = self._reach_assigned_state()
        client.quotes = AsyncMock(return_value=MagicMock(ltp=60.0))
        _run(strat.run_cycle())
        assert abs(strat._sl_price - 78.0) < 0.5


# ===========================================================================
# CC call-away detection
# ===========================================================================


class TestWheelCCCallAway:
    def _reach_cc_active(self):
        from flinttrade_engine.strategies.wheel_live import WheelPhase
        strat, client = _strategy(spot=22000.0, option_ltp=80.0)
        _run(strat.run_cycle())  # → CSP_ACTIVE

        put_strike = strat._put_strike
        client.quotes = AsyncMock(return_value=MagicMock(ltp=put_strike - 300))
        _run(strat.run_cycle())  # → ASSIGNED

        client.quotes = AsyncMock(return_value=MagicMock(ltp=100.0))
        _run(strat.run_cycle())  # → CC_ACTIVE
        assert strat.phase == WheelPhase.CC_ACTIVE
        return strat, client

    def test_cc_called_away_when_spot_above_call_strike(self):
        from flinttrade_engine.strategies.wheel_live import WheelPhase
        strat, client = self._reach_cc_active()
        call_strike = strat._call_strike
        # Spot above call strike
        client.quotes = AsyncMock(return_value=MagicMock(ltp=call_strike + 200))
        _run(strat.run_cycle())  # → CC_EXPIRED
        assert strat.phase == WheelPhase.CC_EXPIRED

    def test_cc_stays_active_when_spot_below_call_strike(self):
        from flinttrade_engine.strategies.wheel_live import WheelPhase
        strat, client = self._reach_cc_active()
        call_strike = strat._call_strike
        client.quotes = AsyncMock(return_value=MagicMock(ltp=call_strike - 200))
        _run(strat.run_cycle())
        assert strat.phase == WheelPhase.CC_ACTIVE


# ===========================================================================
# CC_EXPIRED → restart
# ===========================================================================


class TestWheelRestart:
    def test_cc_expired_transitions_to_waiting_csp(self):
        from flinttrade_engine.strategies.wheel_live import WheelPhase, WheelStrategy
        strat = WheelStrategy(symbol="NIFTY", client=None)
        strat.start()
        strat._phase = WheelPhase.CC_EXPIRED
        _run(strat.run_cycle())
        assert strat.phase == WheelPhase.WAITING_CSP


# ===========================================================================
# No-client fallback (pending orders)
# ===========================================================================


class TestWheelNoClient:
    def test_no_client_does_not_raise(self):
        from flinttrade_engine.strategies.wheel_live import WheelStrategy
        strat = WheelStrategy(symbol="NIFTY", client=None)
        strat.start()
        # run_cycle with no client should just log and return without error
        _run(strat.run_cycle())

    def test_generate_orders_returns_list(self):
        from flinttrade_engine.strategies.wheel_live import WheelStrategy
        strat = WheelStrategy(symbol="NIFTY", client=None)
        strat.start()
        assert isinstance(strat.generate_orders(), list)


# ===========================================================================
# _round_strike helper
# ===========================================================================


class TestRoundStrike:
    def test_rounds_to_nearest_50(self):
        from flinttrade_engine.strategies.wheel_live import WheelStrategy
        assert WheelStrategy._round_strike(22034.0, 50) == 22050.0
        assert WheelStrategy._round_strike(22010.0, 50) == 22000.0

    def test_rounds_to_nearest_100(self):
        from flinttrade_engine.strategies.wheel_live import WheelStrategy
        assert WheelStrategy._round_strike(47060.0, 100) == 47100.0


# ===========================================================================
# _build_option_symbol helper
# ===========================================================================


class TestBuildOptionSymbol:
    def test_put_symbol_format(self):
        from flinttrade_engine.strategies.wheel_live import WheelStrategy
        sym = WheelStrategy._build_option_symbol("NIFTY", "27-Apr-2025", 22000.0, "PE")
        assert "NIFTY" in sym
        assert "22000" in sym
        assert "PE" in sym

    def test_call_symbol_format(self):
        from flinttrade_engine.strategies.wheel_live import WheelStrategy
        sym = WheelStrategy._build_option_symbol("NIFTY", "27-Apr-2025", 22500.0, "CE")
        assert "CE" in sym
        assert "22500" in sym


# ===========================================================================
# State persistence
# ===========================================================================


class TestWheelStateDict:
    def test_state_dict_keys(self):
        strat, _ = _strategy(option_ltp=80.0)
        _run(strat.run_cycle())
        state = strat.get_state_dict()
        expected_keys = {
            "phase", "current_put_symbol", "current_call_symbol",
            "entry_premium", "sl_price", "put_strike", "call_strike",
            "cost_basis", "current_expiry",
        }
        assert expected_keys <= state.keys()

    def test_restore_from_state(self):
        from flinttrade_engine.strategies.wheel_live import WheelPhase, WheelStrategy
        strat = WheelStrategy(symbol="NIFTY", client=None)
        strat.start()
        strat.restore_from_state({
            "phase": "CC_ACTIVE",
            "current_put_symbol": "NIFTY27APR2522000PE",
            "current_call_symbol": "NIFTY27APR2522500CE",
            "entry_premium": 75.0,
            "sl_price": 97.5,
            "put_strike": 22000.0,
            "call_strike": 22500.0,
            "cost_basis": 21950.0,
            "current_expiry": "27-Apr-2025",
        })
        assert strat.phase == WheelPhase.CC_ACTIVE
        assert strat._entry_premium == 75.0
        assert strat._call_strike == 22500.0


# ===========================================================================
# Registration in engine strategies __init__
# ===========================================================================


def test_registered_in_engine_strategies():
    from flinttrade_engine.strategies import WheelPhase, WheelStrategy
    assert WheelStrategy is not None
    assert WheelPhase is not None
