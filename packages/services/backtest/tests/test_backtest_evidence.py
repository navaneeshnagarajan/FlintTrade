"""Evidence tests: built-in strategies exist and the backtest engine runs them."""

from __future__ import annotations

import pytest

from flinttrade_backtest import strategies as builtin
from flinttrade_backtest.simulator import BacktestConfig, BacktestResult, BacktestSimulator
from flinttrade_backtest.strategies import EMACrossover

pytestmark = pytest.mark.unit


def test_multiple_builtin_strategies_exist():
    names = [
        "EMACrossover", "SupertrendStrategy", "MACDRSIStrategy", "BollingerMeanReversion",
        "VWAPDeviation", "StraddleSell", "MomentumBreakout", "OpeningRangeBreakout",
    ]
    present = [n for n in names if hasattr(builtin, n)]
    assert len(present) >= 5  # "multiple built-in strategies"


def _synthetic_bars(n: int = 60) -> list[dict]:
    bars = []
    price = 100.0
    for i in range(n):
        price += 1.0 if i < n // 2 else -1.0  # rise then fall → EMA crossovers
        bars.append({
            "timestamp": f"2026-01-{(i % 28) + 1:02d}",
            "open": price, "high": price + 1, "low": price - 1, "close": price,
            "volume": 10_000, "oi": 0,
        })
    return bars


def test_backtest_runs_a_builtin_strategy_end_to_end():
    config = BacktestConfig(symbol="RELIANCE", interval="1d", initial_capital=1_000_000.0)
    sim = BacktestSimulator(config)
    strategy = EMACrossover(symbol="RELIANCE", fast_period=5, slow_period=10)

    result = sim.run(strategy, _synthetic_bars(60))

    assert isinstance(result, BacktestResult)
    assert result.error == ""
    assert len(result.equity_curve) == 60       # one equity point per bar
    assert result.final_equity > 0
    # total_return_pct is computable (proves the metrics path works)
    assert isinstance(result.total_return_pct, float)


def test_empty_bars_is_handled_gracefully():
    sim = BacktestSimulator(BacktestConfig(symbol="X"))
    result = sim.run(EMACrossover(symbol="X"), [])
    assert result.error  # honest error, not a crash
