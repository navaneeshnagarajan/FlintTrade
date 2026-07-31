"""Overnight strategy optimisation pass.

Wires the mission's "optimise overnight → generate reports + improvement
suggestions" feature to a real engine. The scheduler
(``flinttrade_automation.cron_manager.make_overnight_optimise_job``) has long had
the slot but nothing injected an optimiser, so the job never did anything; this
module is the optimiser.

``OvernightOptimiser.run`` iterates the registered strategies, asks a
:class:`~flinttrade_ai.strategy_refiner.StrategyRefiner` to analyse each one's
recent performance and suggest parameter improvements, and assembles a timestamped
report (optionally persisted via an injected sink). It is fully injectable —
strategy source, refiner, clock, and sink are all parameters — so it runs
deterministically under test without a scheduler, an LLM, or live data.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, Callable

logger = logging.getLogger("flinttrade.ai.overnight_optimiser")


def enrich_strategies(
    strategies: list[dict[str, Any]],
    result_store: Any,
) -> list[dict[str, Any]]:
    """Attach each strategy's latest stored backtest metrics for the refiner.

    The live roster (uploaded strategies) carries no performance metrics, so the
    refiner saw an empty ``backtest_results`` for every strategy. This joins each
    strategy to its most recent stored backtest result by name, AND surfaces
    strategies that have been backtested but aren't in the live roster — so a
    strategy you backtested in the Lab still gets refined overnight.

    Args:
        strategies: The live roster (each a dict with ``name``/``id`` + optional
            ``params``), e.g. ``UserStrategyRunner.list_strategies()``.
        result_store: Object exposing ``latest(name) -> dict | None`` and
            ``names() -> list[str]`` (a :class:`BacktestResultStore`). Duck-typed
            so this module stays independent of the backtest package.

    Returns:
        One enriched dict per distinct strategy, each carrying ``name``,
        ``params`` and a ``backtest_results`` dict (empty when none stored).
    """
    merged: dict[str, dict[str, Any]] = {}
    for strat in strategies or []:
        name = str(strat.get("name") or strat.get("strategy_id") or strat.get("id") or "").strip()
        if not name:
            continue
        merged[name] = {**strat, "name": name, "backtest_results": result_store.latest(name) or {}}

    try:
        stored_names = result_store.names()
    except Exception as exc:  # a broken store must not sink the pass
        logger.warning("backtest result store names() failed — %s", exc)
        stored_names = []
    for name in stored_names:
        if name not in merged:
            merged[name] = {
                "name": name,
                "params": {},
                "backtest_results": result_store.latest(name) or {},
            }
    return list(merged.values())


class OvernightOptimiser:
    """Run a refinement pass over the registered strategies and report.

    Args:
        strategy_provider: ``() -> list[dict]`` returning the strategies to
            optimise. Each dict should carry ``name`` (or ``id``), optional
            ``params`` (current parameters) and optional ``backtest_results``
            (recent performance metrics). Missing pieces degrade gracefully — the
            refiner's rule-based path still produces a suggestion.
        refiner: object exposing ``refine(name, backtest_results, params) ->
            suggestion`` (the suggestion must expose ``to_dict()``), e.g.
            :class:`StrategyRefiner`.
        report_sink: optional ``(report: dict) -> None`` to persist the report
            (file, DB, notification). Failures here never fail the pass.
        clock: optional ``() -> datetime`` (injected for deterministic tests).
    """

    def __init__(
        self,
        strategy_provider: Callable[[], list[dict[str, Any]]],
        refiner: Any,
        *,
        report_sink: Callable[[dict[str, Any]], None] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._strategy_provider = strategy_provider
        self._refiner = refiner
        self._report_sink = report_sink
        self._clock = clock or (lambda: datetime.now(tz=UTC))

    def run(self) -> dict[str, Any]:
        """Optimise every registered strategy; return (and optionally persist) the report.

        This is the callable injected into the overnight cron job. It never
        raises for a single bad strategy — it records the error and carries on,
        so one malformed strategy can't sink the whole nightly pass.
        """
        started = self._clock()
        try:
            strategies = list(self._strategy_provider() or [])
        except Exception as exc:
            logger.error("overnight optimiser: could not list strategies — %s", exc)
            strategies = []

        suggestions: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        for strat in strategies:
            name = str(strat.get("name") or strat.get("id") or "unknown")
            try:
                suggestion = self._refiner.refine(
                    name,
                    strat.get("backtest_results", {}) or {},
                    strat.get("params", {}) or {},
                )
                suggestions.append(suggestion.to_dict())
            except Exception as exc:
                logger.warning("overnight optimiser: refining %s failed — %s", name, exc)
                errors.append({"strategy": name, "error": str(exc)})

        report = {
            "timestamp": started.isoformat(),
            "strategies_seen": len(strategies),
            "strategies_optimised": len(suggestions),
            "suggestions": suggestions,
            "errors": errors,
        }
        if self._report_sink is not None:
            try:
                self._report_sink(report)
            except Exception as exc:  # persistence must never fail the pass
                logger.warning("overnight optimiser: report sink failed — %s", exc)
        logger.info(
            "overnight optimiser: %d/%d strategies refined",
            len(suggestions), len(strategies),
        )
        return report
