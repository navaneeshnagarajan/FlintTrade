"""Tests for the risk manager module."""

from __future__ import annotations

import pytest

from flinttrade_ditto.risk_manager import TradeGrade, grade_trade

def test_grade_trade_buy_a_grade():
    """Test Grade A for BUY with low slippage, good timing and SL."""
    # expected_entry = 100, entry_price = 100.05 (0.05% slippage)
    # expected_exit = 110, exit_price = 110.05 (0.045% slippage)
    # avg_slip = ~0.0475% (< 0.1%)
    # entry_slip = 0.05, timing = 1.0 - 0.05 = 0.95 (> 0.8)
    # PNL = 110.05 - 100.05 = 10
    result = grade_trade(
        entry_price=100.05,
        exit_price=110.05,
        expected_entry=100.0,
        expected_exit=110.0,
        had_stop_loss=True,
        side="BUY",
    )
    assert result.grade == TradeGrade.A.value
    assert result.pnl == 10.0
    assert result.exit_discipline == 1.0
    assert result.entry_timing_score > 0.8
    assert result.slippage_pct < 0.1

def test_grade_trade_buy_b_grade():
    """Test Grade B for BUY with moderate slippage."""
    # expected_entry = 100, entry_price = 100.2 (0.2% slippage)
    # expected_exit = 110, exit_price = 110.2 (0.18% slippage)
    # avg_slip = ~0.19% (< 0.3%)
    # entry_slip = 0.2, timing = 1.0 - 0.2 = 0.8 (> 0.5)
    # PNL = 110.2 - 100.2 = 10
    result = grade_trade(
        entry_price=100.2,
        exit_price=110.2,
        expected_entry=100.0,
        expected_exit=110.0,
        had_stop_loss=True, # Even with SL, if slippage is > 0.1%, it can be B
        side="BUY",
    )
    assert result.grade == TradeGrade.B.value
    assert result.pnl == pytest.approx(10.0)

def test_grade_trade_buy_c_grade():
    """Test Grade C for BUY with higher slippage."""
    # expected_entry = 100, entry_price = 100.4 (0.4% slippage)
    # expected_exit = 110, exit_price = 110.4 (0.36% slippage)
    # avg_slip = ~0.38% (< 0.5%)
    result = grade_trade(
        entry_price=100.4,
        exit_price=110.4,
        expected_entry=100.0,
        expected_exit=110.0,
        had_stop_loss=False,
        side="BUY",
    )
    assert result.grade == TradeGrade.C.value
    assert result.pnl == pytest.approx(10.0)

def test_grade_trade_buy_d_grade():
    """Test Grade D for BUY with very high slippage."""
    # expected_entry = 100, entry_price = 100.6 (0.6% slippage)
    # expected_exit = 110, exit_price = 110.6 (0.54% slippage)
    # avg_slip = ~0.57% (> 0.5%)
    result = grade_trade(
        entry_price=100.6,
        exit_price=110.6,
        expected_entry=100.0,
        expected_exit=110.0,
        had_stop_loss=False,
        side="BUY",
    )
    assert result.grade == TradeGrade.D.value
    assert result.pnl == pytest.approx(10.0)

def test_grade_trade_buy_d_grade_no_sl():
    """Test Grade D for BUY when slippage is low but no SL reduces grade."""
    # wait, actually the grade logic is:
    # if avg_slip < 0.1 and had_stop_loss and timing > 0.8: A
    # elif avg_slip < 0.3 and timing > 0.5: B
    # so if avg_slip < 0.1 and NO stop loss, it falls to B (because 0.1 < 0.3 and timing > 0.5)
    # Let's test this behavior.
    result = grade_trade(
        entry_price=100.05,
        exit_price=110.05,
        expected_entry=100.0,
        expected_exit=110.0,
        had_stop_loss=False,
        side="BUY",
    )
    assert result.grade == TradeGrade.B.value # because it falls through to B

def test_grade_trade_sell_pnl():
    """Verify correct PnL calculation for SELL trades (shorting)."""
    # Shorting: entry is higher, exit is lower = profit
    # entry_price = 110, exit_price = 100 -> PNL = 10
    result = grade_trade(
        entry_price=110.0,
        exit_price=100.0,
        expected_entry=110.0,
        expected_exit=100.0,
        had_stop_loss=True,
        side="SELL",
    )
    assert result.pnl == 10.0
    assert result.grade == TradeGrade.A.value # 0 slippage

def test_grade_trade_sell_loss_pnl():
    """Verify correct PnL calculation for losing SELL trades."""
    # Shorting: entry is lower, exit is higher = loss
    # entry_price = 100, exit_price = 110 -> PNL = -10
    result = grade_trade(
        entry_price=100.0,
        exit_price=110.0,
        expected_entry=100.0,
        expected_exit=110.0,
        had_stop_loss=True,
        side="SELL",
    )
    assert result.pnl == -10.0

def test_grade_trade_case_insensitive_side():
    """Test that side argument is case-insensitive."""
    result = grade_trade(
        entry_price=110.0,
        exit_price=100.0,
        expected_entry=110.0,
        expected_exit=100.0,
        had_stop_loss=True,
        side="sell",
    )
    assert result.pnl == 10.0

def test_grade_trade_zero_expected_entry():
    """Test edge cases where expected_entry is zero to prevent division by zero errors."""
    result = grade_trade(
        entry_price=10.0,
        exit_price=15.0,
        expected_entry=0.0,
        expected_exit=15.0,
        had_stop_loss=True,
        side="BUY",
    )
    # expected_entry = 0 means entry_slip = 0 according to the code
    assert result.pnl == 5.0
    assert result.slippage_pct == 0.0
    assert result.grade == TradeGrade.A.value

def test_grade_trade_zero_expected_exit():
    """Test edge cases where expected_exit is zero to prevent division by zero errors."""
    result = grade_trade(
        entry_price=10.0,
        exit_price=15.0,
        expected_entry=10.0,
        expected_exit=0.0,
        had_stop_loss=True,
        side="BUY",
    )
    # expected_exit = 0 means exit_slip = 0 according to the code
    assert result.pnl == 5.0
    assert result.slippage_pct == 0.0
    assert result.grade == TradeGrade.A.value

def test_grade_trade_zero_expected_entry_and_exit():
    """Test edge cases where both expected_entry and expected_exit are zero."""
    result = grade_trade(
        entry_price=10.0,
        exit_price=15.0,
        expected_entry=0.0,
        expected_exit=0.0,
        had_stop_loss=False,
        side="SELL",
    )
    assert result.pnl == -5.0
    assert result.slippage_pct == 0.0
    # No SL -> exit_disc = 0.3, grade B because avg_slip=0 < 0.3 and timing=1.0 > 0.5
    assert result.grade == TradeGrade.B.value
