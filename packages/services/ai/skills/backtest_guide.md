---
name: backtest_guide
category: strategy
description: Run the selected FlintTrade strategy on provenance-bound history; interpret failures and evidence honestly
version: 2
---
# FlintTrade Backtest Guide

## Choose the actual strategy interface

`flinttrade_backtest.simulator.BacktestSimulator` accepts a `BacktestConfig`,
then `run(strategy, bars)`. This surface consumes an engine `BaseStrategy`:
`start`, `on_bar`, `generate_orders`, and `stop` are load-bearing callbacks.
Do not substitute a `generate_signals` function or a different template interface.
The backtest-template engine has its own `BaseBacktestStrategy` contract; use the
engine matching the selected candidate, not a buy-and-hold replacement.

```python
from flinttrade_backtest.simulator import BacktestConfig, BacktestSimulator
from flinttrade_engine.strategy import BaseStrategy


def evaluate_candidate(strategy: BaseStrategy, bars: list[dict], config: BacktestConfig):
    result = BacktestSimulator(config).run(strategy, bars)
    if result.error:
        raise RuntimeError(result.error)
    return result
```

Supply previously authorised historical bars with `timestamp`, `open`, `high`,
`low`, `close`, and `volume`. A simulator does not fetch history automatically.
Keep source, venue, currency, calendar, adjustments, coverage and immutable dataset
identity with the experiment. Missing history is unavailable, not a reason to
silently switch providers or fabricate prices. Check the configured historical
source's actual supported range; there is no universal years-of-history promise.

## Freeze before measuring

Record the exact candidate code and parameters, data manifest, split, simulator,
cost model and acceptance policy. Define chronological development and held-out
periods before optimisation. Purge overlapping labels and keep related examples
in the same split. Never tune against the final-test labels or report training
scores as out-of-sample performance. Historical as-of LLM prompts cannot remove
knowledge acquired during pretraining; prospective frozen-candidate evidence is
needed for economic conclusions.

## Failed runs are failed evidence

Check the returned error and completion evidence before storing scores. A failed
callback, partial history or uncertain fill is not a successful zero-return run.
Do not manufacture closing fills from unvisited bars. Keep failed trials and the
original error; never replace a failed candidate with a baseline strategy.

## Metrics and costs

Report return, drawdown, turnover, exposure and risk-adjusted metrics with units,
period, sample size and cost assumptions. Win rate alone does not establish
profitability. Use source-appropriate commissions, taxes, spread, slippage,
funding, borrow and impact assumptions; this guide supplies no universal numeric
acceptance thresholds or profitable defaults. Absence of adequate evidence means
no promotion, not an invented confidence score.

## Resampling and robustness

A permutation of fixed trade P&Ls changes path-dependent drawdowns but preserves
the terminal P&L sum. It is not a distribution of possible terminal profits or
proof of a worst realistic scenario. Use a statistically justified null for the
advertised statistic; preserve dependence where relevant. Walk-forward must run
the selected strategy and fit only on the permitted past. Test sensitivity to
costs, gaps and regime changes without modifying sealed acceptance criteria.

## Adoption is separate

A backtest result does not grant trading authority. Qualification, prospective
checks, current data rights and the exact run's unchanged account/time/risk grant
remain necessary. Retain the incumbent and verify handover/rollback. Neither a
skill update nor a trained model can increase limits or bypass gated execution.
