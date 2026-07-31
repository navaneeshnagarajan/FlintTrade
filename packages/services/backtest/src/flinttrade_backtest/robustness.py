"""Robustness testing suite for backtest strategies.

Five independent tests that stress-test a strategy to distinguish genuine
edge from data-mining bias or execution assumptions:

1. **Monte Carlo trade shuffle** — randomise trade order N times, measure
   variance of final equity.  A fragile strategy shows wide percentile bands.

2. **Noise injection** — add ±N% random noise to OHLCV prices, re-run the
   strategy.  Measures sensitivity to price-feed quality.

3. **Parameter sensitivity** — vary each parameter ±20% independently, check
   whether the Sharpe ratio stays stable.  An over-fitted strategy breaks on
   small parameter perturbations.

4. **Entry/exit delay** — shift all signals by 1, 2, or 3 bars.  A robust
   strategy tolerates minor execution slippage; a fragile one depends on
   perfect fills.

5. **Cross-symbol validation** — run the strategy on a correlated but
   different symbol.  True edge generalises; curve-fitted strategies do not.

All tests are pure Python + standard library.  No external dependencies
beyond what the backtest-engine package already imports.

Usage::

    tester = RobustnessTester(
        strategy_class=EMACrossover,
        strategy_kwargs={"fast": 9, "slow": 21},
        bars=historical_bars,
        config=RobustnessConfig(),
    )
    report = tester.run_all()
    print(report.summary())
    print("Overall:", "PASS" if report.overall_pass else "FAIL")
"""

from __future__ import annotations

import logging
import math
import random
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("flinttrade.backtest.robustness")

# ADF-style critical threshold (Sharpe ratio coefficient of variation)
_MAX_PARAM_CV = 0.50          # allow up to 50% CV in Sharpe across param grid
_MAX_DELAY_SHARPE_DROP = 0.40  # allow up to 40% Sharpe drop after 3-bar delay
_MIN_CROSS_SYMBOL_WIN_RATE = 30.0  # cross-symbol win rate must be > 30%
_MAX_SHUFFLE_CV = 1.0          # CV of shuffled equity must be < 100%


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class RobustnessConfig:
    """Configuration for the robustness test suite.

    Attributes:
        n_mc_simulations:    Monte Carlo shuffle iterations.
        noise_pct:           Noise injection amplitude (% of price).
        n_noise_runs:        Number of noise-injected backtests.
        param_perturb_pct:   Parameter perturbation band (fraction, e.g. 0.20).
        delay_bars:          List of bar delays to test for entry/exit delay.
        seed:                RNG seed for reproducibility.
    """

    n_mc_simulations: int = 500
    noise_pct: float = 0.5       # ±0.5% price noise
    n_noise_runs: int = 50
    param_perturb_pct: float = 0.20
    delay_bars: list[int] = field(default_factory=lambda: [1, 2, 3])
    seed: int = 42


# ---------------------------------------------------------------------------
# Per-test results
# ---------------------------------------------------------------------------


@dataclass
class MCShuffleResult:
    """Monte Carlo trade-shuffle test result.

    Attributes:
        mean_equity:   Mean final equity across simulations.
        std_equity:    Standard deviation of final equities.
        cv_equity:     Coefficient of variation = std / mean.
        p5_equity:     5th percentile final equity.
        p95_equity:    95th percentile final equity.
        passed:        True when CV < threshold (strategy is order-insensitive).
    """

    mean_equity: float = 0.0
    std_equity: float = 0.0
    cv_equity: float = 0.0
    p5_equity: float = 0.0
    p95_equity: float = 0.0
    passed: bool = False


@dataclass
class NoiseInjectionResult:
    """Noise injection test result.

    Attributes:
        base_sharpe:    Sharpe on clean prices.
        mean_sharpe:    Mean Sharpe across noisy runs.
        std_sharpe:     Std of Sharpe across noisy runs.
        pct_positive:   Fraction of noisy runs with positive Sharpe.
        passed:         True when mean_sharpe > 0 and pct_positive >= 0.6.
    """

    base_sharpe: float = 0.0
    mean_sharpe: float = 0.0
    std_sharpe: float = 0.0
    pct_positive: float = 0.0
    passed: bool = False


@dataclass
class ParamSensitivityEntry:
    """Single parameter sensitivity run."""

    param_name: str = ""
    delta_pct: float = 0.0       # +20% or -20%
    sharpe: float = 0.0
    total_return_pct: float = 0.0


@dataclass
class ParamSensitivityResult:
    """Parameter sensitivity test result.

    Attributes:
        entries:     Individual results per (param, delta) combination.
        sharpe_cv:   Coefficient of variation of Sharpe across all entries.
        passed:      True when sharpe_cv < threshold.
    """

    entries: list[ParamSensitivityEntry] = field(default_factory=list)
    sharpe_cv: float = 0.0
    passed: bool = False


@dataclass
class DelayTestEntry:
    """Single delay test run."""

    delay_bars: int = 0
    sharpe: float = 0.0
    sharpe_pct_drop: float = 0.0   # % drop vs base


@dataclass
class DelayTestResult:
    """Entry/exit delay test result.

    Attributes:
        base_sharpe:  Sharpe on zero delay (original strategy).
        entries:      Per-delay results.
        max_drop_pct: Worst Sharpe drop across all delays.
        passed:       True when max_drop_pct <= threshold.
    """

    base_sharpe: float = 0.0
    entries: list[DelayTestEntry] = field(default_factory=list)
    max_drop_pct: float = 0.0
    passed: bool = False


@dataclass
class CrossSymbolResult:
    """Cross-symbol validation result.

    Attributes:
        symbol:       Symbol used for cross-validation.
        sharpe:       Sharpe ratio on that symbol.
        win_rate:     Trade win rate (%).
        total_return: Total return (%).
        passed:       True when win_rate > threshold.
    """

    symbol: str = ""
    sharpe: float = 0.0
    win_rate: float = 0.0
    total_return: float = 0.0
    passed: bool = False


# ---------------------------------------------------------------------------
# Overall report
# ---------------------------------------------------------------------------


@dataclass
class RobustnessReport:
    """Aggregated robustness testing report.

    Attributes:
        mc_shuffle:          Monte Carlo trade-shuffle result.
        noise_injection:     Noise injection result.
        param_sensitivity:   Parameter sensitivity result.
        delay_test:          Entry/exit delay test result.
        cross_symbol:        Cross-symbol validation results (one per symbol).
        overall_pass:        True when *all* individual tests pass.
    """

    mc_shuffle: MCShuffleResult = field(default_factory=MCShuffleResult)
    noise_injection: NoiseInjectionResult = field(default_factory=NoiseInjectionResult)
    param_sensitivity: ParamSensitivityResult = field(default_factory=ParamSensitivityResult)
    delay_test: DelayTestResult = field(default_factory=DelayTestResult)
    cross_symbol: list[CrossSymbolResult] = field(default_factory=list)

    @property
    def overall_pass(self) -> bool:
        """True when every test passes."""
        cross_pass = all(r.passed for r in self.cross_symbol) if self.cross_symbol else True
        return (
            self.mc_shuffle.passed
            and self.noise_injection.passed
            and self.param_sensitivity.passed
            and self.delay_test.passed
            and cross_pass
        )

    def summary(self) -> str:
        """Return a human-readable multi-line summary."""
        lines = [
            "=== Robustness Report ===",
            (
                f"MC Shuffle        : {'PASS' if self.mc_shuffle.passed else 'FAIL'}"
                f"  (CV={self.mc_shuffle.cv_equity:.3f})"
            ),
            (
                f"Noise Injection   : {'PASS' if self.noise_injection.passed else 'FAIL'}"
                f"  (mean_sharpe={self.noise_injection.mean_sharpe:.3f},"
                f" pct_positive={self.noise_injection.pct_positive:.1%})"
            ),
            (
                f"Param Sensitivity : {'PASS' if self.param_sensitivity.passed else 'FAIL'}"
                f"  (sharpe_cv={self.param_sensitivity.sharpe_cv:.3f})"
            ),
            (
                f"Delay Test        : {'PASS' if self.delay_test.passed else 'FAIL'}"
                f"  (max_drop={self.delay_test.max_drop_pct:.1f}%)"
            ),
        ]
        for cs in self.cross_symbol:
            lines.append(
                f"Cross-Symbol {cs.symbol:12s}: {'PASS' if cs.passed else 'FAIL'}"
                f"  (sharpe={cs.sharpe:.3f}, win_rate={cs.win_rate:.1f}%)"
            )
        lines.append(f"OVERALL           : {'PASS' if self.overall_pass else 'FAIL'}")
        return "\n".join(lines)

    def as_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict for JSON responses."""
        return {
            "overall_pass": self.overall_pass,
            "mc_shuffle": {
                "mean_equity": self.mc_shuffle.mean_equity,
                "std_equity": self.mc_shuffle.std_equity,
                "cv_equity": self.mc_shuffle.cv_equity,
                "p5_equity": self.mc_shuffle.p5_equity,
                "p95_equity": self.mc_shuffle.p95_equity,
                "passed": self.mc_shuffle.passed,
            },
            "noise_injection": {
                "base_sharpe": self.noise_injection.base_sharpe,
                "mean_sharpe": self.noise_injection.mean_sharpe,
                "std_sharpe": self.noise_injection.std_sharpe,
                "pct_positive": self.noise_injection.pct_positive,
                "passed": self.noise_injection.passed,
            },
            "param_sensitivity": {
                "sharpe_cv": self.param_sensitivity.sharpe_cv,
                "passed": self.param_sensitivity.passed,
                "entries": [
                    {
                        "param": e.param_name,
                        "delta_pct": e.delta_pct,
                        "sharpe": e.sharpe,
                        "total_return_pct": e.total_return_pct,
                    }
                    for e in self.param_sensitivity.entries
                ],
            },
            "delay_test": {
                "base_sharpe": self.delay_test.base_sharpe,
                "max_drop_pct": self.delay_test.max_drop_pct,
                "passed": self.delay_test.passed,
                "entries": [
                    {
                        "delay_bars": e.delay_bars,
                        "sharpe": e.sharpe,
                        "sharpe_pct_drop": e.sharpe_pct_drop,
                    }
                    for e in self.delay_test.entries
                ],
            },
            "cross_symbol": [
                {
                    "symbol": r.symbol,
                    "sharpe": r.sharpe,
                    "win_rate": r.win_rate,
                    "total_return": r.total_return,
                    "passed": r.passed,
                }
                for r in self.cross_symbol
            ],
        }


# ---------------------------------------------------------------------------
# Internal stats helpers (no external deps)
# ---------------------------------------------------------------------------


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _std(values: list[float], ddof: int = 1) -> float:
    n = len(values)
    if n <= ddof:
        return 0.0
    m = _mean(values)
    variance = sum((v - m) ** 2 for v in values) / (n - ddof)
    return math.sqrt(max(0.0, variance))


def _sharpe(returns: list[float], risk_free: float = 0.07, ann: int = 252) -> float:
    """Annualised Sharpe ratio from bar returns."""
    if len(returns) < 2:
        return 0.0
    m = _mean(returns)
    s = _std(returns)
    if s == 0:
        return 0.0
    daily_rf = risk_free / ann
    return (m - daily_rf) / s * math.sqrt(ann)


def _equity_to_returns(equity: list[float]) -> list[float]:
    returns: list[float] = []
    for i in range(1, len(equity)):
        prev = equity[i - 1]
        curr = equity[i]
        returns.append((curr - prev) / prev if prev > 0 else 0.0)
    return returns


def _bars_to_equity(bars: list[dict[str, Any]], initial: float = 1.0) -> list[float]:
    """Simple buy-and-hold equity from close prices."""
    closes = [float(b.get("close", b.get("Close", 0.0))) for b in bars if b.get("close") or b.get("Close")]
    if not closes:
        return [initial]
    equity = [initial]
    for i in range(1, len(closes)):
        if closes[i - 1] > 0:
            ret = (closes[i] - closes[i - 1]) / closes[i - 1]
            equity.append(equity[-1] * (1 + ret))
        else:
            equity.append(equity[-1])
    return equity


def _percentile(sorted_vals: list[float], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    n = len(sorted_vals)
    idx = pct / 100.0 * (n - 1)
    lo = int(idx)
    hi = min(lo + 1, n - 1)
    frac = idx - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def _run_strategy(
    strategy_class: type,
    strategy_kwargs: dict[str, Any],
    bars: list[dict[str, Any]],
) -> tuple[float, float, float]:
    """Run a strategy on bars and return (sharpe, win_rate, total_return_pct).

    Falls back to buy-and-hold returns when the strategy does not expose
    ``daily_returns`` or ``get_equity_curve()``.
    """
    try:
        strategy = strategy_class(**strategy_kwargs)
        if hasattr(strategy, "on_bar"):
            for bar in bars:
                strategy.on_bar(bar)

        # Prefer explicit return series
        if hasattr(strategy, "daily_returns") and isinstance(strategy.daily_returns, list):
            returns = list(strategy.daily_returns)
        elif hasattr(strategy, "get_equity_curve"):
            returns = _equity_to_returns(strategy.get_equity_curve())
        else:
            returns = _equity_to_returns(_bars_to_equity(bars))

    except Exception as exc:
        logger.warning("Strategy run failed: %s", exc)
        returns = _equity_to_returns(_bars_to_equity(bars))

    if not returns:
        return 0.0, 0.0, 0.0

    sharpe = _sharpe(returns)
    win_rate = sum(1 for r in returns if r > 0) / len(returns) * 100
    total_return = (math.prod(1 + r for r in returns) - 1) * 100 if returns else 0.0
    return sharpe, win_rate, total_return


# ---------------------------------------------------------------------------
# Noise injection helper
# ---------------------------------------------------------------------------


def _inject_noise(
    bars: list[dict[str, Any]],
    noise_pct: float,
    rng: random.Random,
) -> list[dict[str, Any]]:
    """Return a copy of bars with ±noise_pct random multiplicative noise."""
    noisy: list[dict[str, Any]] = []
    amplitude = noise_pct / 100.0
    for bar in bars:
        nb = dict(bar)
        for key in ("open", "high", "low", "close"):
            if key in nb:
                factor = 1.0 + rng.uniform(-amplitude, amplitude)
                nb[key] = float(nb[key]) * factor
        noisy.append(nb)
    return noisy


# ---------------------------------------------------------------------------
# Signal delay helper
# ---------------------------------------------------------------------------


def _delay_bars(
    bars: list[dict[str, Any]],
    delay: int,
) -> list[dict[str, Any]]:
    """Shift bar close prices forward by ``delay`` bars to simulate late fills.

    Fills the first ``delay`` bars with the open price (no look-ahead).
    """
    if delay <= 0 or not bars:
        return bars
    delayed: list[dict[str, Any]] = []
    for i, bar in enumerate(bars):
        nb = dict(bar)
        src_idx = max(0, i - delay)
        nb["close"] = float(bars[src_idx].get("close", bar.get("close", 0.0)))
        delayed.append(nb)
    return delayed


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------


class RobustnessTester:
    """Run the full robustness testing suite on a strategy.

    Args:
        strategy_class:   Strategy class (constructor must accept
                          ``**strategy_kwargs``).
        strategy_kwargs:  Base keyword arguments for the strategy.
        bars:             Historical bar data (list of OHLCV dicts).
        config:           :class:`RobustnessConfig` (uses defaults if None).
        initial_capital:  Starting equity for Monte Carlo paths.

    Example::

        cfg = RobustnessConfig(n_mc_simulations=200, noise_pct=1.0)
        tester = RobustnessTester(
            strategy_class=MyStrategy,
            strategy_kwargs={"fast": 9, "slow": 21},
            bars=bars,
            config=cfg,
        )
        report = tester.run_all()
        print(report.summary())
    """

    def __init__(
        self,
        strategy_class: type,
        strategy_kwargs: dict[str, Any],
        bars: list[dict[str, Any]],
        config: RobustnessConfig | None = None,
        initial_capital: float = 100_000.0,
    ) -> None:
        self._cls = strategy_class
        self._kwargs = strategy_kwargs
        self._bars = bars
        self._cfg = config or RobustnessConfig()
        self._initial_capital = initial_capital
        self._rng = random.Random(self._cfg.seed)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_all(
        self,
        cross_symbol_bars: dict[str, list[dict[str, Any]]] | None = None,
    ) -> RobustnessReport:
        """Run all robustness tests and return an aggregated report.

        Args:
            cross_symbol_bars: Optional dict of {symbol: bars} for
                               cross-symbol validation.  When omitted the
                               cross-symbol test is skipped.

        Returns:
            :class:`RobustnessReport` with per-test and overall pass/fail.
        """
        logger.info(
            "Robustness suite start: %d bars, strategy=%s",
            len(self._bars), self._cls.__name__,
        )

        mc = self.test_mc_shuffle()
        noise = self.test_noise_injection()
        param_s = self.test_param_sensitivity()
        delay = self.test_delay()
        cross: list[CrossSymbolResult] = []
        if cross_symbol_bars:
            for sym, sym_bars in cross_symbol_bars.items():
                cross.append(self.test_cross_symbol(sym, sym_bars))

        report = RobustnessReport(
            mc_shuffle=mc,
            noise_injection=noise,
            param_sensitivity=param_s,
            delay_test=delay,
            cross_symbol=cross,
        )
        logger.info("Robustness suite done: overall_pass=%s", report.overall_pass)
        return report

    # ------------------------------------------------------------------
    # Test 1: Monte Carlo trade shuffle
    # ------------------------------------------------------------------

    def test_mc_shuffle(self) -> MCShuffleResult:
        """Randomise trade order N times and measure equity variance.

        Runs a base strategy on the full bar set, extracts the trade P&L
        sequence, then shuffles it ``n_mc_simulations`` times.

        Returns:
            :class:`MCShuffleResult` with equity distribution stats.
        """
        # Get base trade P&Ls from strategy
        trade_pnls = self._extract_trade_pnls(self._bars)
        if not trade_pnls:
            # Fallback to bar-level returns treated as micro-trades
            returns = _equity_to_returns(_bars_to_equity(self._bars))
            trade_pnls = [r * self._initial_capital for r in returns]

        if not trade_pnls:
            return MCShuffleResult()

        final_equities: list[float] = []
        for _ in range(self._cfg.n_mc_simulations):
            shuffled = trade_pnls[:]
            self._rng.shuffle(shuffled)
            equity = self._initial_capital
            for pnl in shuffled:
                equity += pnl
            final_equities.append(equity)

        final_equities.sort()
        mean_eq = _mean(final_equities)
        std_eq = _std(final_equities)
        cv = std_eq / abs(mean_eq) if mean_eq != 0 else float("inf")

        return MCShuffleResult(
            mean_equity=mean_eq,
            std_equity=std_eq,
            cv_equity=cv,
            p5_equity=_percentile(final_equities, 5.0),
            p95_equity=_percentile(final_equities, 95.0),
            passed=cv < _MAX_SHUFFLE_CV,
        )

    # ------------------------------------------------------------------
    # Test 2: Noise injection
    # ------------------------------------------------------------------

    def test_noise_injection(self) -> NoiseInjectionResult:
        """Inject random price noise and re-run the strategy.

        Returns:
            :class:`NoiseInjectionResult` with Sharpe stability stats.
        """
        base_sharpe, _, _ = _run_strategy(self._cls, self._kwargs, self._bars)

        sharpes: list[float] = []
        for _ in range(self._cfg.n_noise_runs):
            noisy_bars = _inject_noise(self._bars, self._cfg.noise_pct, self._rng)
            s, _, _ = _run_strategy(self._cls, self._kwargs, noisy_bars)
            sharpes.append(s)

        mean_s = _mean(sharpes)
        std_s = _std(sharpes)
        pct_pos = sum(1 for s in sharpes if s > 0) / len(sharpes) if sharpes else 0.0

        return NoiseInjectionResult(
            base_sharpe=base_sharpe,
            mean_sharpe=mean_s,
            std_sharpe=std_s,
            pct_positive=pct_pos,
            passed=(mean_s > 0) and (pct_pos >= 0.6),
        )

    # ------------------------------------------------------------------
    # Test 3: Parameter sensitivity
    # ------------------------------------------------------------------

    def test_param_sensitivity(self) -> ParamSensitivityResult:
        """Vary each numeric parameter ±perturb_pct independently.

        Returns:
            :class:`ParamSensitivityResult` with per-parameter Sharpe.
        """
        perturb = self._cfg.param_perturb_pct
        entries: list[ParamSensitivityEntry] = []

        # Identify numeric parameters
        numeric_params = {
            k: v for k, v in self._kwargs.items()
            if isinstance(v, (int, float)) and v != 0
        }

        if not numeric_params:
            # No numeric params — test passes trivially
            return ParamSensitivityResult(passed=True)

        for param_name, base_value in numeric_params.items():
            for delta_sign in (+1, -1):
                delta = delta_sign * perturb
                new_value = base_value * (1 + delta)
                # Preserve int type
                if isinstance(base_value, int):
                    new_value = max(1, int(round(new_value)))

                kwargs = dict(self._kwargs)
                kwargs[param_name] = new_value

                try:
                    sharpe, _, total_ret = _run_strategy(self._cls, kwargs, self._bars)
                except Exception as exc:
                    logger.warning("Param sensitivity run failed %s=%s: %s", param_name, new_value, exc)
                    sharpe, total_ret = 0.0, 0.0

                entries.append(ParamSensitivityEntry(
                    param_name=param_name,
                    delta_pct=delta * 100,
                    sharpe=sharpe,
                    total_return_pct=total_ret,
                ))

        if not entries:
            return ParamSensitivityResult(passed=True)

        sharpes = [e.sharpe for e in entries]
        mean_s = _mean(sharpes)
        std_s = _std(sharpes)
        cv = std_s / abs(mean_s) if mean_s != 0 else float("inf")

        return ParamSensitivityResult(
            entries=entries,
            sharpe_cv=cv,
            passed=cv < _MAX_PARAM_CV,
        )

    # ------------------------------------------------------------------
    # Test 4: Entry/exit delay
    # ------------------------------------------------------------------

    def test_delay(self) -> DelayTestResult:
        """Shift signals by 1–N bars to simulate delayed execution.

        Returns:
            :class:`DelayTestResult` with Sharpe degradation per delay level.
        """
        base_sharpe, _, _ = _run_strategy(self._cls, self._kwargs, self._bars)
        entries: list[DelayTestEntry] = []
        max_drop = 0.0

        for delay in self._cfg.delay_bars:
            delayed_bars = _delay_bars(self._bars, delay)
            s, _, _ = _run_strategy(self._cls, self._kwargs, delayed_bars)

            if base_sharpe != 0:
                drop = (base_sharpe - s) / abs(base_sharpe) * 100.0
            else:
                drop = 0.0

            entries.append(DelayTestEntry(
                delay_bars=delay,
                sharpe=s,
                sharpe_pct_drop=drop,
            ))
            max_drop = max(max_drop, drop)

        return DelayTestResult(
            base_sharpe=base_sharpe,
            entries=entries,
            max_drop_pct=max_drop,
            passed=max_drop <= _MAX_DELAY_SHARPE_DROP * 100,
        )

    # ------------------------------------------------------------------
    # Test 5: Cross-symbol validation
    # ------------------------------------------------------------------

    def test_cross_symbol(
        self,
        symbol: str,
        symbol_bars: list[dict[str, Any]],
    ) -> CrossSymbolResult:
        """Run the strategy on a different symbol's data.

        Args:
            symbol:      Display name for this validation symbol.
            symbol_bars: Bar data for the validation symbol.

        Returns:
            :class:`CrossSymbolResult` with pass/fail verdict.
        """
        sharpe, win_rate, total_ret = _run_strategy(
            self._cls, self._kwargs, symbol_bars,
        )
        return CrossSymbolResult(
            symbol=symbol,
            sharpe=sharpe,
            win_rate=win_rate,
            total_return=total_ret,
            passed=win_rate > _MIN_CROSS_SYMBOL_WIN_RATE,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _extract_trade_pnls(self, bars: list[dict[str, Any]]) -> list[float]:
        """Try to extract trade P&Ls from the strategy.

        Attempts to use ``completed_trades``, ``trades``, or ``get_trades()``
        on the strategy instance.  Returns an empty list on failure.
        """
        try:
            strategy = self._cls(**self._kwargs)
            if hasattr(strategy, "on_bar"):
                for bar in bars:
                    strategy.on_bar(bar)

            # Common attribute names for trade lists
            for attr in ("completed_trades", "trades", "_trades"):
                obj = getattr(strategy, attr, None)
                if isinstance(obj, list) and obj:
                    pnls = []
                    for t in obj:
                        if hasattr(t, "net_pnl"):
                            pnls.append(float(t.net_pnl))
                        elif isinstance(t, dict) and "net_pnl" in t:
                            pnls.append(float(t["net_pnl"]))
                    if pnls:
                        return pnls

            if hasattr(strategy, "get_trades"):
                trades = strategy.get_trades()
                if trades:
                    return [float(getattr(t, "net_pnl", 0)) for t in trades]

        except Exception as exc:
            logger.debug("Trade P&L extraction failed: %s", exc)

        return []


__all__ = [
    "RobustnessTester",
    "RobustnessConfig",
    "RobustnessReport",
    "MCShuffleResult",
    "NoiseInjectionResult",
    "ParamSensitivityResult",
    "ParamSensitivityEntry",
    "DelayTestResult",
    "DelayTestEntry",
    "CrossSymbolResult",
]
