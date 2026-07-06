"""Tests for the cash-future / cross-exchange arbitrage scanner (DP3).

All computation is pure and offline.
"""

from __future__ import annotations

from flinttrade_screener.cash_future_arbitrage import (
    ArbitrageScanResult,
    evaluate_cash_future,
    evaluate_cross_exchange,
    make_sample_arbitrage_scan,
    scan_arbitrage,
)


class TestCashFuture:
    def test_future_rich_flags_cash_and_carry(self):
        # Future well above fair carry over a short horizon → cash-and-carry.
        opp = evaluate_cash_future("NIFTY", spot=24000.0, future_price=24120.0, days_to_expiry=5)
        assert opp is not None
        assert opp.basis == 120.0
        assert opp.annualised_return_pct > 7.0  # clears funding
        assert opp.signal == "cash_and_carry"

    def test_future_below_spot_flags_reverse(self):
        opp = evaluate_cash_future("TATASTEEL", spot=165.0, future_price=164.0, days_to_expiry=12)
        assert opp is not None
        assert opp.basis == -1.0
        assert opp.signal == "reverse"

    def test_basis_near_carry_is_fair(self):
        # Future ≈ spot·e^{r t}; edge under the 1% threshold → fair.
        spot = 1000.0
        dte = 30
        fair_future = spot * (2.718281828 ** (0.07 * dte / 365.0))
        opp = evaluate_cash_future("X", spot=spot, future_price=fair_future, days_to_expiry=dte)
        assert opp is not None
        assert opp.signal == "fair"

    def test_non_positive_prices_return_none(self):
        assert evaluate_cash_future("X", spot=0.0, future_price=100.0, days_to_expiry=5) is None
        assert evaluate_cash_future("X", spot=100.0, future_price=-1.0, days_to_expiry=5) is None


class TestCrossExchange:
    def test_price_gap_picks_cheaper_to_buy(self):
        opp = evaluate_cross_exchange("RELIANCE", "NSE", 2850.0, "BSE", 2854.0)
        assert opp is not None
        assert opp.spread == 4.0
        assert opp.buy_on == "NSE"
        assert opp.sell_on == "BSE"
        assert opp.spread_pct > 0

    def test_non_positive_returns_none(self):
        assert evaluate_cross_exchange("X", "NSE", 0.0, "BSE", 10.0) is None


class TestScanArbitrage:
    def test_ranks_by_dislocation_size(self):
        rows = [
            {"underlying": "A", "spot": 100.0, "future_price": 100.2, "days_to_expiry": 30},
            {"underlying": "B", "spot": 100.0, "future_price": 105.0, "days_to_expiry": 5},
        ]
        result = scan_arbitrage(cash_future_rows=rows)
        assert isinstance(result, ArbitrageScanResult)
        # B has the far larger annualised edge → ranked first.
        assert result.cash_future[0].underlying == "B"

    def test_sample_scan_has_both_dimensions(self):
        result = make_sample_arbitrage_scan()
        assert len(result.cash_future) == 4
        assert len(result.cross_exchange) == 2

    def test_to_dict_is_json_serialisable(self):
        import json

        payload = make_sample_arbitrage_scan().to_dict()
        loaded = json.loads(json.dumps(payload))
        assert "cash_future" in loaded
        assert "cross_exchange" in loaded
