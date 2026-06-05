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

from datetime import datetime, timezone
from typing import Any, Callable

import logging

logger = logging.getLogger("flinttrade.ai.overnight_optimiser")


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
        self._clock = clock or (lambda: datetime.now(tz=timezone.utc))

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
