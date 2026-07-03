"""Tests for FlintTrade ditto package.

DO NOT RUN — written for pytest. All tests use mocks, no live API calls.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest

from flinttrade_ditto.account_manager import decrypt_value, encrypt_value


@pytest.fixture(autouse=True)
def _set_encryption_key(monkeypatch):
    """Provide a valid Fernet key for all tests that use AccountManager."""
    from cryptography.fernet import Fernet
    monkeypatch.setenv("DITTO_ENCRYPTION_KEY", Fernet.generate_key().decode())

# ======================================================================
# Helpers
# ======================================================================


def _make_account(
    account_id: str = "acc1",
    name: str = "Test",
    host: str = "http://127.0.0.1:5001",
    api_key: str = "test_key",
    weight: float = 1.0,
    group: str = "default",
    enabled: bool = True,
    is_master: bool = False,
):
    from flinttrade_ditto.account_manager import BrokerAccount
    return BrokerAccount(
        account_id=account_id, name=name, openalgo_host=host,
        api_key=api_key, allocation_weight=weight, group=group,
        enabled=enabled, is_master=is_master,
    )


# ======================================================================
# Account Manager — registration + health check
# ======================================================================


class TestAccountManager:
    """Test account registration, listing, groups, and health."""

    def test_add_and_list(self, tmp_path):
        from flinttrade_ditto.account_manager import AccountManager
        mgr = AccountManager(db_path=str(tmp_path / "test.sqlite"))
        mgr.add_account(_make_account("a1", name="Personal"))
        mgr.add_account(_make_account("a2", name="Family"))
        accounts = mgr.list_accounts()
        assert len(accounts) == 2
        mgr.close()

    def test_remove_account(self, tmp_path):
        from flinttrade_ditto.account_manager import AccountManager
        mgr = AccountManager(db_path=str(tmp_path / "test.sqlite"))
        mgr.add_account(_make_account("a1"))
        mgr.remove_account("a1")
        assert len(mgr.list_accounts()) == 0
        mgr.close()

    def test_get_account(self, tmp_path):
        from flinttrade_ditto.account_manager import AccountManager
        mgr = AccountManager(db_path=str(tmp_path / "test.sqlite"))
        mgr.add_account(_make_account("a1", name="Test"))
        acc = mgr.get_account("a1")
        assert acc is not None
        assert acc.name == "Test"
        mgr.close()

    def test_get_nonexistent(self, tmp_path):
        from flinttrade_ditto.account_manager import AccountManager
        mgr = AccountManager(db_path=str(tmp_path / "test.sqlite"))
        assert mgr.get_account("nope") is None
        mgr.close()

    def test_enabled_filter(self, tmp_path):
        from flinttrade_ditto.account_manager import AccountManager
        mgr = AccountManager(db_path=str(tmp_path / "test.sqlite"))
        mgr.add_account(_make_account("a1", enabled=True))
        mgr.add_account(_make_account("a2", enabled=False))
        assert len(mgr.get_enabled_accounts()) == 1
        mgr.close()

    def test_enable_disable(self, tmp_path):
        from flinttrade_ditto.account_manager import AccountManager
        mgr = AccountManager(db_path=str(tmp_path / "test.sqlite"))
        mgr.add_account(_make_account("a1"))
        mgr.disable_account("a1")
        assert len(mgr.get_enabled_accounts()) == 0
        mgr.enable_account("a1")
        assert len(mgr.get_enabled_accounts()) == 1
        mgr.close()

    def test_groups(self, tmp_path):
        from flinttrade_ditto.account_manager import AccountManager
        mgr = AccountManager(db_path=str(tmp_path / "test.sqlite"))
        mgr.add_account(_make_account("a1", group="family"))
        mgr.add_account(_make_account("a2", group="personal"))
        mgr.add_account(_make_account("a3", group="family"))
        assert len(mgr.get_accounts_by_group("family")) == 2
        assert len(mgr.get_accounts_by_group("personal")) == 1
        mgr.close()

    def test_master_account(self, tmp_path):
        from flinttrade_ditto.account_manager import AccountManager
        mgr = AccountManager(db_path=str(tmp_path / "test.sqlite"))
        mgr.add_account(_make_account("a1", is_master=False))
        mgr.add_account(_make_account("a2", is_master=True))
        master = mgr.get_master_account()
        assert master is not None
        assert master.account_id == "a2"
        mgr.close()

    def test_health_check_mock(self, tmp_path):
        from flinttrade_ditto.account_manager import AccountManager
        mgr = AccountManager(db_path=str(tmp_path / "test.sqlite"))
        acc = _make_account("a1")
        mgr.add_account(acc)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mgr._http = MagicMock()
        mgr._http.post.return_value = mock_resp

        health = mgr.health_check(acc)
        assert health.reachable
        assert health.account_id == "a1"
        mgr.close()

    def test_encryption_roundtrip(self):
        from cryptography.fernet import Fernet
        key = Fernet.generate_key().decode()
        plaintext = "my_secret_api_key"
        encrypted = encrypt_value(plaintext, key)
        assert encrypted != plaintext
        decrypted = decrypt_value(encrypted, key)
        assert decrypted == plaintext

    def test_encrypt_decrypt_env_key(self, monkeypatch):
        from cryptography.fernet import Fernet
        key = Fernet.generate_key().decode()
        monkeypatch.setenv("DITTO_ENCRYPTION_KEY", key)
        plaintext = "secret_env_key"
        encrypted = encrypt_value(plaintext)
        assert encrypted != plaintext
        decrypted = decrypt_value(encrypted)
        assert decrypted == plaintext

    def test_encrypt_no_key_raises(self, monkeypatch):
        monkeypatch.delenv("DITTO_ENCRYPTION_KEY", raising=False)
        with pytest.raises(ValueError, match="DITTO_ENCRYPTION_KEY environment variable is required"):
            encrypt_value("test")

    def test_decrypt_no_key_raises(self, monkeypatch):
        monkeypatch.delenv("DITTO_ENCRYPTION_KEY", raising=False)
        with pytest.raises(ValueError, match="DITTO_ENCRYPTION_KEY environment variable is required"):
            decrypt_value("test")


# ======================================================================
# Mirror — allocation modes
# ======================================================================


class TestMirrorAllocation:
    """Test mirror allocation modes: equal, weighted, margin-aware, lot-based."""

    def test_equal_allocation(self):
        from flinttrade_ditto.mirror import AllocationMode, compute_allocation
        accounts = [_make_account(f"a{i}") for i in range(3)]
        alloc = compute_allocation(100, accounts, AllocationMode.EQUAL)
        assert alloc == {"a0": 100, "a1": 100, "a2": 100}

    def test_weighted_allocation(self):
        from flinttrade_ditto.mirror import AllocationMode, compute_allocation
        accounts = [
            _make_account("a1", weight=1.0),
            _make_account("a2", weight=3.0),
        ]
        alloc = compute_allocation(100, accounts, AllocationMode.WEIGHTED)
        assert alloc["a1"] == 25  # 1/4 of 100
        assert alloc["a2"] == 75  # 3/4 of 100

    def test_weighted_allocation_equal_weights(self):
        from flinttrade_ditto.mirror import AllocationMode, compute_allocation
        accounts = [_make_account(f"a{i}", weight=1.0) for i in range(4)]
        alloc = compute_allocation(100, accounts, AllocationMode.WEIGHTED)
        assert all(v == 25 for v in alloc.values())

    def test_margin_aware_allocation(self):
        from flinttrade_ditto.mirror import AllocationMode, compute_allocation
        accounts = [
            _make_account("rich", weight=1.0),
            _make_account("poor", weight=1.0),
        ]
        margins = {"rich": 500000.0, "poor": 100000.0}
        alloc = compute_allocation(
            100, accounts, AllocationMode.MARGIN_AWARE,
            available_margins=margins, price_per_unit=2500.0,
        )
        assert alloc["rich"] > alloc["poor"]

    def test_margin_aware_skips_zero_margin(self):
        from flinttrade_ditto.mirror import AllocationMode, compute_allocation
        accounts = [
            _make_account("a1"),
            _make_account("a2"),
        ]
        margins = {"a1": 100000.0, "a2": 0.0}
        alloc = compute_allocation(
            100, accounts, AllocationMode.MARGIN_AWARE,
            available_margins=margins, price_per_unit=2500.0,
        )
        assert "a2" not in alloc or alloc.get("a2", 0) == 0

    def test_lot_based_allocation(self):
        from flinttrade_ditto.mirror import AllocationMode, compute_allocation
        accounts = [
            _make_account("a1", weight=1.0),
            _make_account("a2", weight=1.0),
        ]
        # NIFTY lot = 75
        alloc = compute_allocation(150, accounts, AllocationMode.LOT_BASED, symbol="NIFTY")
        for qty in alloc.values():
            assert qty % 75 == 0  # Must be multiple of lot size

    def test_lot_based_rounds_to_lot(self):
        from flinttrade_ditto.mirror import AllocationMode, compute_allocation
        accounts = [_make_account("a1", weight=1.0)]
        alloc = compute_allocation(80, accounts, AllocationMode.LOT_BASED, symbol="NIFTY")
        assert alloc["a1"] == 75  # Rounded to nearest lot

    def test_empty_accounts(self):
        from flinttrade_ditto.mirror import AllocationMode, compute_allocation
        alloc = compute_allocation(100, [], AllocationMode.EQUAL)
        assert alloc == {}

    def test_mirror_result_all_succeeded(self):
        from flinttrade_ditto.mirror import MirrorResult
        result = MirrorResult(successful=3, failed=0, total_accounts=3)
        assert result.all_succeeded

    def test_mirror_result_has_failures(self):
        from flinttrade_ditto.mirror import MirrorResult
        result = MirrorResult(successful=2, failed=1, total_accounts=3)
        assert not result.all_succeeded


# ======================================================================
# Margin Calculator — multi-leg
# ======================================================================


class TestMarginCalculator:
    """Test margin estimation and multi-leg hedge benefit."""

    def test_estimate_cnc(self):
        from flinttrade_ditto.margin_calculator import MarginCalculator
        est = MarginCalculator.estimate_order_margin("RELIANCE", "NSE", "CNC", 10, 2500)
        assert est.estimated_margin == 25000

    def test_estimate_mis(self):
        from flinttrade_ditto.margin_calculator import MarginCalculator
        est = MarginCalculator.estimate_order_margin("RELIANCE", "NSE", "MIS", 10, 2500)
        # MIS = 20% of notional for NSE
        assert est.estimated_margin == pytest.approx(5000, abs=100)

    def test_estimate_nrml_fno(self):
        from flinttrade_ditto.margin_calculator import MarginCalculator
        est = MarginCalculator.estimate_order_margin("NIFTY", "NFO", "NRML", 75, 24000)
        # NRML F&O = ~15% of notional
        notional = 75 * 24000
        assert est.estimated_margin == pytest.approx(notional * 0.15)

    def test_multi_leg_hedge_benefit(self):
        from flinttrade_ditto.margin_calculator import MarginCalculator
        # Bull put spread: sell put + buy put (hedged)
        legs = [
            {"symbol": "NIFTY25000PE", "exchange": "NFO", "product": "NRML", "quantity": 75, "price": 200, "action": "SELL"},
            {"symbol": "NIFTY24500PE", "exchange": "NFO", "product": "NRML", "quantity": 75, "price": 100, "action": "BUY"},
        ]
        result = MarginCalculator.calculate_multi_leg_margin(legs)
        assert result.hedge_benefit > 0
        assert result.net_margin < result.gross_margin
        assert result.benefit_pct > 0

    def test_single_leg_no_benefit(self):
        from flinttrade_ditto.margin_calculator import MarginCalculator
        legs = [
            {"symbol": "NIFTY", "exchange": "NFO", "product": "NRML", "quantity": 75, "price": 24000, "action": "BUY"},
        ]
        result = MarginCalculator.calculate_multi_leg_margin(legs)
        assert result.hedge_benefit == 0
        assert result.net_margin == result.gross_margin

    def test_has_sufficient_margin(self):
        from flinttrade_ditto.margin_calculator import MarginCalculator, MarginInfo
        info = MarginInfo(account_id="a1", available_balance=100000)
        acc = _make_account("a1")
        assert MarginCalculator.has_sufficient_margin(acc, 50000, margin_info=info)
        assert not MarginCalculator.has_sufficient_margin(acc, 200000, margin_info=info)

    def test_max_affordable_quantity_mis(self):
        from flinttrade_ditto.margin_calculator import MarginCalculator
        # NSE MIS = 20% margin, price 2500
        qty = MarginCalculator.max_affordable_quantity(100000, 2500, "NSE", "MIS")
        # Margin per unit = 2500 * 0.20 = 500; 100000/500 = 200
        assert qty == 200

    def test_max_affordable_quantity_zero_price(self):
        from flinttrade_ditto.margin_calculator import MarginCalculator
        assert MarginCalculator.max_affordable_quantity(100000, 0) == 0

    def test_margin_info_free_margin(self):
        from flinttrade_ditto.margin_calculator import MarginInfo
        info = MarginInfo(account_id="a1", available_balance=50000, used_margin=30000, total_balance=80000)
        assert info.free_margin == 50000


# ======================================================================
# Trailing SL — all 4 modes
# ======================================================================


class TestTrailingSL:
    """Test trailing SL calculation for all modes."""

    def test_points_trailing_long(self):
        from flinttrade_ditto.trailing_sl import SLTracker, calculate_trailing_sl
        tracker = SLTracker(
            position_id="p1", symbol="NIFTY", side="BUY",
            entry_price=24000, current_sl=23900,
            trail_mode="POINTS", trail_value=100,
        )
        # Price moves up to 24200 → peak = 24200 → SL should move to 24100
        new_sl = calculate_trailing_sl(tracker, 24200)
        assert new_sl == 24100.0

    def test_points_trailing_no_move_down(self):
        from flinttrade_ditto.trailing_sl import SLTracker, calculate_trailing_sl
        tracker = SLTracker(
            position_id="p1", symbol="NIFTY", side="BUY",
            entry_price=24000, current_sl=23950, peak_price=24050,
            trail_mode="POINTS", trail_value=100,
        )
        # Price drops → SL should NOT move down
        new_sl = calculate_trailing_sl(tracker, 23980)
        assert new_sl is None

    def test_percentage_trailing_long(self):
        from flinttrade_ditto.trailing_sl import SLTracker, calculate_trailing_sl
        tracker = SLTracker(
            position_id="p1", symbol="RELIANCE", side="BUY",
            entry_price=2500, current_sl=2400,
            trail_mode="PERCENTAGE", trail_value=2.0,
        )
        # Price goes to 2600 → SL = 2600 * 0.98 = 2548
        new_sl = calculate_trailing_sl(tracker, 2600)
        assert new_sl == pytest.approx(2548.0, abs=1)

    def test_points_trailing_short(self):
        from flinttrade_ditto.trailing_sl import SLTracker, calculate_trailing_sl
        tracker = SLTracker(
            position_id="p1", symbol="NIFTY", side="SELL",
            entry_price=24000, current_sl=24200,
            trail_mode="POINTS", trail_value=100,
            trough_price=24000,
        )
        # Price drops to 23800 → SL should trail down to 23900
        new_sl = calculate_trailing_sl(tracker, 23800)
        assert new_sl == 23900.0

    def test_short_sl_does_not_move_up(self):
        from flinttrade_ditto.trailing_sl import SLTracker, calculate_trailing_sl
        tracker = SLTracker(
            position_id="p1", symbol="NIFTY", side="SELL",
            entry_price=24000, current_sl=23900,
            trail_mode="POINTS", trail_value=100,
            trough_price=23800,
        )
        # Price bounces up → SL should NOT move up
        new_sl = calculate_trailing_sl(tracker, 24100)
        assert new_sl is None

    def test_atr_trailing(self):
        from flinttrade_ditto.trailing_sl import SLTracker, calculate_trailing_sl
        tracker = SLTracker(
            position_id="p1", symbol="NIFTY", side="BUY",
            entry_price=24000, current_sl=23800,
            trail_mode="ATR", trail_value=2.0,
            peak_price=24000,
        )
        # Provide price history for ATR calculation
        highs = [24000 + i * 10 for i in range(20)]
        lows = [23900 + i * 10 for i in range(20)]
        closes = [23950 + i * 10 for i in range(20)]
        new_sl = calculate_trailing_sl(
            tracker, 24200,
            highs=highs, lows=lows, closes=closes,
        )
        # Should have moved from 23800 to something higher
        assert new_sl is not None, "ATR trailing SL should return a value"
        assert new_sl > 23800

    def test_supertrend_trailing(self):
        from flinttrade_ditto.trailing_sl import compute_supertrend
        highs = [100 + i * 0.5 for i in range(30)]
        lows = [99 + i * 0.5 for i in range(30)]
        closes = [99.5 + i * 0.5 for i in range(30)]
        st, uptrend = compute_supertrend(highs, lows, closes, 10, 3.0)
        assert len(st) == 30
        assert len(uptrend) == 30
        # In an uptrend, last values should show support
        assert uptrend[-1]

    def test_manager_add_and_update(self):
        from flinttrade_ditto.trailing_sl import SLTracker, TrailingSLManager
        mgr = TrailingSLManager()
        mgr.add_tracker(SLTracker(
            position_id="p1", symbol="NIFTY", side="BUY",
            entry_price=24000, current_sl=23900,
            trail_mode="POINTS", trail_value=100,
        ))
        adj = mgr.update("p1", 24200)
        assert adj is not None
        assert adj.new_sl == 24100
        assert adj.old_sl == 23900
        assert mgr.get_sl("p1") == 24100

    def test_manager_update_all(self):
        from flinttrade_ditto.trailing_sl import SLTracker, TrailingSLManager
        mgr = TrailingSLManager()
        mgr.add_tracker(SLTracker(
            position_id="p1", symbol="NIFTY", side="BUY",
            entry_price=24000, current_sl=23900,
            trail_mode="POINTS", trail_value=100,
        ))
        mgr.add_tracker(SLTracker(
            position_id="p2", symbol="RELIANCE", side="BUY",
            entry_price=2500, current_sl=2400,
            trail_mode="POINTS", trail_value=50,
        ))
        adjs = mgr.update_all({"NIFTY": 24200, "RELIANCE": 2600})
        assert len(adjs) == 2

    def test_manager_remove_tracker(self):
        from flinttrade_ditto.trailing_sl import SLTracker, TrailingSLManager
        mgr = TrailingSLManager()
        mgr.add_tracker(SLTracker(position_id="p1", symbol="X", side="BUY", entry_price=100, current_sl=90, trail_mode="POINTS", trail_value=10))
        mgr.remove_tracker("p1")
        assert mgr.get_sl("p1") == 0.0

    def test_compute_atr(self):
        from flinttrade_ditto.trailing_sl import compute_atr
        highs = [110.0] * 20
        lows = [90.0] * 20
        closes = [100.0] * 20
        atr = compute_atr(highs, lows, closes, 10)
        assert len(atr) == 20
        assert atr[-1] == pytest.approx(20.0, abs=1)


# ======================================================================
# Risk Manager — threshold triggers
# ======================================================================


class TestRiskManager:
    """Test risk manager threshold enforcement and trade grading."""

    def test_ok_status_default(self):
        from flinttrade_ditto.risk_manager import RiskManager
        risk = RiskManager()
        state = risk.get_state("acc1")
        assert state.status == "OK"

    def test_pnl_loss_pauses_account(self):
        from flinttrade_ditto.risk_manager import RiskConfig, RiskManager
        risk = RiskManager()
        risk.set_config("acc1", RiskConfig(max_loss_daily=50000))
        risk.update_pnl("acc1", -55000)
        state = risk.get_state("acc1")
        assert state.status == "PAUSED"
        assert any("PAUSED" in a for a in state.alerts)

    def test_margin_warning(self):
        from flinttrade_ditto.risk_manager import RiskConfig, RiskManager
        risk = RiskManager()
        risk.set_config("acc1", RiskConfig(margin_warn_pct=70))
        risk.update_margin("acc1", 75)
        state = risk.get_state("acc1")
        assert state.status == "WARNING"

    def test_margin_critical_blocks(self):
        from flinttrade_ditto.risk_manager import RiskConfig, RiskManager
        risk = RiskManager()
        risk.set_config("acc1", RiskConfig(margin_block_pct=90))
        risk.update_margin("acc1", 95)
        check = risk.check_order("acc1")
        assert not check.allowed
        assert "margin" in check.reason.lower() or "Margin" in check.reason

    def test_position_limit_blocks(self):
        from flinttrade_ditto.risk_manager import RiskConfig, RiskManager
        risk = RiskManager()
        risk.set_config("acc1", RiskConfig(max_positions=5))
        risk.update_positions("acc1", 5)
        check = risk.check_order("acc1")
        assert not check.allowed

    def test_paused_account_blocks_all(self):
        from flinttrade_ditto.risk_manager import RiskConfig, RiskManager
        risk = RiskManager()
        risk.set_config("acc1", RiskConfig(max_loss_daily=10000))
        risk.update_pnl("acc1", -15000)
        check = risk.check_order("acc1")
        assert not check.allowed
        assert "PAUSED" in check.reason

    def test_single_trade_loss_limit(self):
        from flinttrade_ditto.risk_manager import RiskConfig, RiskManager
        risk = RiskManager()
        risk.set_config("acc1", RiskConfig(max_single_trade_loss=25000))
        check = risk.check_order("acc1", trade_loss_potential=30000)
        assert not check.allowed

    def test_order_allowed_when_healthy(self):
        from flinttrade_ditto.risk_manager import RiskManager
        risk = RiskManager()
        check = risk.check_order("acc1")
        assert check.allowed

    def test_combined_daily_pnl(self):
        from flinttrade_ditto.risk_manager import RiskManager
        risk = RiskManager()
        risk.update_pnl("acc1", -10000)
        risk.update_pnl("acc2", -20000)
        assert risk.combined_daily_pnl() == -30000

    def test_combined_loss_check(self):
        from flinttrade_ditto.risk_manager import RiskManager
        risk = RiskManager()
        risk.update_pnl("acc1", -100000)
        risk.update_pnl("acc2", -100000)
        assert not risk.check_combined_loss(max_combined=150000)

    def test_pause_resume(self):
        from flinttrade_ditto.risk_manager import RiskManager, RiskStatus
        risk = RiskManager()
        risk.pause_account("acc1")
        assert risk.get_state("acc1").status == RiskStatus.PAUSED.value
        risk.resume_account("acc1")
        assert risk.get_state("acc1").status == RiskStatus.OK.value

    def test_reset_daily(self):
        from flinttrade_ditto.risk_manager import RiskConfig, RiskManager
        risk = RiskManager()
        risk.set_config("acc1", RiskConfig(max_loss_daily=50000))
        risk.update_pnl("acc1", -60000)
        assert risk.get_state("acc1").status == "PAUSED"
        risk.reset_daily()
        assert risk.get_state("acc1").status == "OK"
        assert risk.get_state("acc1").daily_pnl == 0

    def test_record_trade(self):
        from flinttrade_ditto.risk_manager import RiskManager
        risk = RiskManager()
        risk.record_trade("acc1", pnl=500)
        risk.record_trade("acc1", pnl=-200)
        state = risk.get_state("acc1")
        assert state.trade_count == 2
        assert state.winning_trades == 1
        assert state.losing_trades == 1
        assert state.win_rate == 50.0

    def test_trade_grade_a(self):
        from flinttrade_ditto.risk_manager import grade_trade
        q = grade_trade(
            entry_price=100, exit_price=110,
            expected_entry=100, expected_exit=110,
            had_stop_loss=True,
        )
        assert q.grade == "A"
        assert q.slippage_pct < 0.1

    def test_trade_grade_b(self):
        from flinttrade_ditto.risk_manager import grade_trade
        q = grade_trade(
            entry_price=100.2, exit_price=110,
            expected_entry=100, expected_exit=110,
            had_stop_loss=True,
        )
        assert q.grade == "B"
        assert q.slippage_pct == pytest.approx(0.1, abs=0.001)

    def test_trade_grade_c(self):
        from flinttrade_ditto.risk_manager import grade_trade
        q = grade_trade(
            entry_price=100.8, exit_price=110,
            expected_entry=100, expected_exit=110,
            had_stop_loss=True,
        )
        assert q.grade == "C"
        assert q.slippage_pct == pytest.approx(0.4, abs=0.001)

    def test_trade_grade_d(self):
        from flinttrade_ditto.risk_manager import grade_trade
        q = grade_trade(
            entry_price=105, exit_price=95,
            expected_entry=100, expected_exit=110,
            had_stop_loss=False,
        )
        assert q.grade == "D"

    def test_trade_grade_zero_expected(self):
        from flinttrade_ditto.risk_manager import grade_trade
        q = grade_trade(
            entry_price=100, exit_price=110,
            expected_entry=0, expected_exit=0,
            had_stop_loss=True,
        )
        assert q.grade == "A"
        assert q.slippage_pct == 0.0

    def test_trade_grade_pnl_long(self):
        from flinttrade_ditto.risk_manager import grade_trade
        q = grade_trade(
            entry_price=100, exit_price=110,
            expected_entry=100, expected_exit=110,
            had_stop_loss=True, side="BUY",
        )
        assert q.pnl == 10

    def test_trade_grade_pnl_short(self):
        from flinttrade_ditto.risk_manager import grade_trade
        q = grade_trade(
            entry_price=110, exit_price=100,
            expected_entry=110, expected_exit=100,
            had_stop_loss=True, side="SELL",
        )
        assert q.pnl == 10


# ======================================================================
# Package exports
# ======================================================================


class TestPackageExports:
    """Verify __init__.py exports."""

    def test_all_exports(self):
        from flinttrade_ditto import __all__
        expected = [
            "AccountManager", "BrokerAccount", "PositionMirror",
            "AllocationMode", "MarginCalculator", "MarginInfo",
            "TrailingSLManager", "SLTracker", "TrailingMode",
            "RiskManager", "RiskConfig", "RiskStatus",
            "TradeGrade", "TradeQuality",
        ]
        for name in expected:
            assert name in __all__, f"Missing export: {name}"

    def test_version(self):
        from flinttrade_ditto import __version__
        from flinttrade_core.version import APP_VERSION

        assert __version__ == APP_VERSION

    def test_package_exists(self):
        pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        assert os.path.exists(os.path.join(pkg_dir, "src", "flinttrade_ditto", "__init__.py"))
        assert os.path.exists(os.path.join(pkg_dir, "README.md"))

class TestEncryptionDecryptionExtra:
    def test_encrypt_value_default_key(self, monkeypatch):
        from flinttrade_ditto.account_manager import encrypt_value, decrypt_value
        from cryptography.fernet import Fernet
        key = Fernet.generate_key().decode()
        monkeypatch.setenv("DITTO_ENCRYPTION_KEY", key)

        plaintext = "secret"
        # Test without passing key
        encrypted = encrypt_value(plaintext)
        assert encrypted != plaintext
        decrypted = decrypt_value(encrypted)
        assert decrypted == plaintext

    def test_encrypt_value_bytes_key(self, monkeypatch):
        from flinttrade_ditto.account_manager import encrypt_value, decrypt_value
        from cryptography.fernet import Fernet
        key = Fernet.generate_key()
        monkeypatch.setenv("DITTO_ENCRYPTION_KEY", key.decode())

        plaintext = "secret2"
        # Test with explicitly passing key
        encrypted = encrypt_value(plaintext, key=key.decode())
        assert encrypted != plaintext
        decrypted = decrypt_value(encrypted, key=key.decode())
        assert decrypted == plaintext

    def test_get_fernet_import_error(self, monkeypatch):
        import sys
        from flinttrade_ditto.account_manager import _get_fernet

        # Force ImportError
        monkeypatch.setitem(sys.modules, 'cryptography.fernet', None)

        with pytest.raises(ImportError, match="cryptography required — pip install cryptography"):
            _get_fernet("some_key")

class TestDefaultDB:
    def test_default_db_with_env_var(self, monkeypatch):
        from flinttrade_ditto.account_manager import _default_db
        monkeypatch.setenv("DATA_DIR", "/tmp/data")
        assert _default_db() == "/tmp/data/ditto_accounts.sqlite"

    def test_default_db_with_workspace(self, monkeypatch):
        import sys
        from pathlib import Path
        from flinttrade_ditto.account_manager import _default_db
        monkeypatch.delenv("DATA_DIR", raising=False)

        # Mock workspace module
        mock_core = MagicMock()
        mock_workspace = MagicMock()
        mock_workspace_instance = MagicMock()
        mock_workspace_instance.fast_data_dir = Path("/workspace/data")
        mock_workspace.Workspace.return_value = mock_workspace_instance
        mock_core.src.workspace = mock_workspace
        monkeypatch.setitem(sys.modules, 'flinttrade_core.workspace', mock_core.src.workspace)

        # Production code does str(Path(workspace.fast_data_dir) / "ditto_accounts.sqlite"),
        # so on Windows the separator is \, on POSIX it is /. Compose the expected
        # value through Path() the same way to keep the test cross-platform.
        expected = str(Path("/workspace/data") / "ditto_accounts.sqlite")
        assert _default_db() == expected

    def test_default_db_fallback(self, monkeypatch):
        import sys
        from pathlib import Path
        from flinttrade_ditto.account_manager import _default_db
        monkeypatch.delenv("DATA_DIR", raising=False)

        # Ensure importing workspace fails
        monkeypatch.setitem(sys.modules, 'flinttrade_core.workspace', None)

        # Mock Path.home()
        mock_home = Path("/home/mockuser")
        monkeypatch.setattr(Path, "home", lambda: mock_home)

        # As above, compose through Path() so the assertion uses the OS-native
        # separator and matches production output on Windows + POSIX alike.
        expected = str(mock_home / ".flinttrade" / "data" / "ditto_accounts.sqlite")
        assert _default_db() == expected


class TestAccountManagerExtra:
    def test_enter_exit(self, tmp_path):
        from flinttrade_ditto.account_manager import AccountManager
        with AccountManager(db_path=str(tmp_path / "test.sqlite")) as mgr:
            mgr.add_account(_make_account("a1"))
            assert len(mgr.list_accounts()) == 1

    def test_get_account_not_in_cache(self, tmp_path):
        from flinttrade_ditto.account_manager import AccountManager
        mgr = AccountManager(db_path=str(tmp_path / "test.sqlite"))
        mgr.add_account(_make_account("a1"))
        # Clear cache to force DB lookup
        mgr._cache.clear()
        acc = mgr.get_account("a1")
        assert acc is not None
        assert acc.account_id == "a1"
        mgr.close()

    def test_health_check_http_error(self, tmp_path):
        from flinttrade_ditto.account_manager import AccountManager
        mgr = AccountManager(db_path=str(tmp_path / "test.sqlite"))
        acc = _make_account("a1")

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mgr._http = MagicMock()
        mgr._http.post.return_value = mock_resp

        health = mgr.health_check(acc)
        assert not health.reachable
        assert health.error == "HTTP 500"
        mgr.close()

    def test_health_check_exception(self, tmp_path):
        from flinttrade_ditto.account_manager import AccountManager
        mgr = AccountManager(db_path=str(tmp_path / "test.sqlite"))
        acc = _make_account("a1")

        mgr._http = MagicMock()
        mgr._http.post.side_effect = Exception("Connection Refused")

        health = mgr.health_check(acc)
        assert not health.reachable
        assert health.error == "OpenAlgo health check failed"
        assert "Connection Refused" not in health.error
        mgr.close()

    def test_health_check_all(self, tmp_path):
        from flinttrade_ditto.account_manager import AccountManager
        mgr = AccountManager(db_path=str(tmp_path / "test.sqlite"))
        mgr.add_account(_make_account("a1", enabled=True))
        mgr.add_account(_make_account("a2", enabled=False)) # Should be skipped

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mgr._http = MagicMock()
        mgr._http.post.return_value = mock_resp

        results = mgr.health_check_all()
        assert len(results) == 1
        assert results[0].account_id == "a1"
        assert results[0].reachable
        mgr.close()

    def test_row_to_account_decryption_failure(self, tmp_path):
        from flinttrade_ditto.account_manager import AccountManager
        mgr = AccountManager(db_path=str(tmp_path / "test.sqlite"), encryption_key="wrong_key")

        # Create a valid account first (encrypted with a different key for testing)
        from cryptography.fernet import Fernet
        key1 = Fernet.generate_key()
        f1 = Fernet(key1)
        enc_api_key = f1.encrypt(b"my_api_key").decode()

        row = ("a1", "Test", "http://host", enc_api_key, 1, 1.0, "default", 50000.0, 0)

        acc = mgr._row_to_account(row)
        assert acc.account_id == "a1"
        assert acc.api_key == "" # Failed to decrypt
        mgr.close()
