"""Strategy refiner — closes the loop between backtest results and AI improvement.

Pattern: backtest results → format as prompt → LLM analysis →
suggested parameter changes → save to refinement log.

Designed to be used from the Backtest Lab after a run completes:
    refiner = StrategyRefiner(llm_client=LLMClient())
    suggestion = refiner.refine("ema_crossover", metrics, params)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("flinttrade.ai.strategy_refiner")


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class RefinementSuggestion:
    """One round of AI-suggested parameter improvements.

    Attributes:
        strategy_name: Name of the strategy being refined.
        analysis: LLM's narrative analysis of the backtest results.
        suggested_params: New parameter values recommended by the LLM (or
            rule-based fallback).  Keys mirror the current_params dict.
        reasoning: Why these specific changes were suggested.
        confidence: Confidence in the suggestion, 0.0 (low) to 1.0 (high).
        timestamp: ISO-8601 UTC timestamp of the suggestion.
    """

    strategy_name: str
    analysis: str
    suggested_params: dict[str, Any]
    reasoning: str
    confidence: float
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict for JSON logging."""
        return {
            "strategy_name": self.strategy_name,
            "analysis": self.analysis,
            "suggested_params": self.suggested_params,
            "reasoning": self.reasoning,
            "confidence": self.confidence,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# Core refiner
# ---------------------------------------------------------------------------


class StrategyRefiner:
    """Takes backtest results and asks the LLM to suggest improvements.

    When an LLM client is provided the full analysis is delegated to the
    model.  When no client is available (offline / unconfigured) a set of
    simple rule-based heuristics are applied instead so the feature degrades
    gracefully rather than failing hard.

    Args:
        llm_client: Optional :class:`~flinttrade_ai.llm_client.LLMClient`
            instance.  If *None* the rule-based fallback is always used.

    Examples::

        refiner = StrategyRefiner()  # rule-based only
        result = refiner.refine("ema_crossover", backtest_metrics, params)
        print(result.suggested_params)
    """

    _SYSTEM_PROMPT = (
        "You are a quantitative trading strategy analyst. "
        "Analyse the provided backtest metrics and current parameters, "
        "then suggest concrete parameter improvements to boost risk-adjusted returns. "
        "Respond with a JSON object containing exactly these keys: "
        '"analysis" (string), "suggested_params" (object), "reasoning" (string), '
        '"confidence" (float 0-1). '
        "Keep suggested_params to the same keys as current_params — only change values."
    )

    def __init__(self, llm_client: Any | None = None) -> None:
        self.llm_client = llm_client
        self._refinement_log: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def refine(
        self,
        strategy_name: str,
        backtest_results: dict[str, Any],
        current_params: dict[str, Any],
    ) -> RefinementSuggestion:
        """Analyse backtest results and suggest parameter improvements.

        Args:
            strategy_name: Human-readable name of the strategy.
            backtest_results: Metrics dict from the backtest engine.  Expected
                keys: ``sharpe_ratio``, ``max_drawdown``, ``win_rate``,
                ``total_trades``, ``total_return``, ``profit_factor``,
                ``sortino_ratio``.  Unknown keys are passed through to the LLM.
            current_params: Current strategy parameter values.

        Returns:
            :class:`RefinementSuggestion` with analysis and suggested changes.
        """
        if self.llm_client is not None:
            suggestion = self._llm_refinement(
                strategy_name, backtest_results, current_params
            )
        else:
            suggestion = self._rule_based_refinement(
                strategy_name, backtest_results, current_params
            )

        self._refinement_log.append(suggestion.to_dict())
        logger.info(
            "Refinement logged for '%s' (confidence=%.2f)",
            strategy_name,
            suggestion.confidence,
        )
        return suggestion

    def get_refinement_history(self) -> list[dict[str, Any]]:
        """Return all past refinement suggestions for this session.

        Returns:
            List of dicts, each matching :meth:`RefinementSuggestion.to_dict`.
        """
        return list(self._refinement_log)

    # ------------------------------------------------------------------
    # LLM-based path
    # ------------------------------------------------------------------

    def _llm_refinement(
        self,
        strategy_name: str,
        backtest_results: dict[str, Any],
        current_params: dict[str, Any],
    ) -> RefinementSuggestion:
        """Delegate analysis to the LLM and parse its structured response."""
        from .llm_client import LLMMessage  # noqa: PLC0415

        prompt = self._build_refinement_prompt(
            strategy_name, backtest_results, current_params
        )
        messages = [
            LLMMessage(role="system", content=self._SYSTEM_PROMPT),
            LLMMessage(role="user", content=prompt),
        ]

        try:
            response = self.llm_client.chat(messages, temperature=0.3)
            if response.success:
                return self._parse_suggestion(
                    strategy_name, response.content, current_params
                )
            logger.warning(
                "LLM refinement failed (%s), using rule-based fallback",
                response.error,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM call raised %s, using rule-based fallback", exc)

        return self._rule_based_refinement(
            strategy_name, backtest_results, current_params
        )

    def _build_refinement_prompt(
        self,
        strategy_name: str,
        backtest_results: dict[str, Any],
        current_params: dict[str, Any],
    ) -> str:
        """Format backtest data into an LLM prompt.

        Args:
            strategy_name: Strategy identifier.
            backtest_results: Backtest metrics.
            current_params: Current parameter values.

        Returns:
            Formatted prompt string ready for the LLM.
        """
        return (
            f"Strategy: {strategy_name}\n\n"
            f"Backtest metrics:\n{json.dumps(backtest_results, indent=2)}\n\n"
            f"Current parameters:\n{json.dumps(current_params, indent=2)}\n\n"
            "Suggest improved parameters to increase Sharpe ratio and reduce "
            "drawdown while maintaining a healthy trade count."
        )

    def _parse_suggestion(
        self,
        strategy_name: str,
        llm_response: str,
        current_params: dict[str, Any],
    ) -> RefinementSuggestion:
        """Parse LLM JSON response into a :class:`RefinementSuggestion`.

        Tolerates markdown code fences around the JSON block.  Falls back to
        a minimal suggestion when parsing fails.

        Args:
            strategy_name: Strategy identifier.
            llm_response: Raw text from the LLM.
            current_params: Used as fallback for suggested_params on parse error.

        Returns:
            Parsed :class:`RefinementSuggestion`.
        """
        # Strip markdown code fences if present
        text = llm_response.strip()
        for fence in ("```json", "```"):
            if text.startswith(fence):
                text = text[len(fence):]
                if text.endswith("```"):
                    text = text[:-3]
                break
        text = text.strip()

        try:
            data = json.loads(text)
            return RefinementSuggestion(
                strategy_name=strategy_name,
                analysis=str(data.get("analysis", "")),
                suggested_params=dict(data.get("suggested_params", current_params)),
                reasoning=str(data.get("reasoning", "")),
                confidence=float(data.get("confidence", 0.5)),
            )
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            logger.warning("Could not parse LLM suggestion JSON: %s", exc)
            return RefinementSuggestion(
                strategy_name=strategy_name,
                analysis=llm_response[:500],
                suggested_params=dict(current_params),
                reasoning="LLM response could not be parsed as JSON.",
                confidence=0.1,
            )

    # ------------------------------------------------------------------
    # Rule-based fallback path
    # ------------------------------------------------------------------

    def _rule_based_refinement(
        self,
        strategy_name: str,
        results: dict[str, Any],
        params: dict[str, Any],
    ) -> RefinementSuggestion:
        """Apply simple heuristics when no LLM is available.

        Rules applied (in order, multiple may fire):

        * Sharpe < 1 → widen stop-loss, reduce position size.
        * Max drawdown > 20 % → tighten risk limits.
        * Win rate < 40 % → suggest tighter entry conditions.
        * Default → no changes, inform the user.

        Args:
            strategy_name: Strategy identifier.
            results: Backtest metrics.
            params: Current parameter values.

        Returns:
            :class:`RefinementSuggestion` based on heuristics.
        """
        sharpe: float = float(results.get("sharpe_ratio", 0) or 0)
        max_dd: float = abs(float(results.get("max_drawdown", 0) or 0))
        win_rate: float = float(results.get("win_rate", 0) or 0)

        suggestions: list[str] = []
        reasoning_parts: list[str] = []
        suggested = dict(params)
        confidence = 0.6

        # Rule 1 — low Sharpe
        if sharpe < 1.0:
            reasoning_parts.append(
                f"Sharpe ratio {sharpe:.2f} is below 1.0 — risk-adjusted returns are poor."
            )
            suggestions.append("widen stop-loss, reduce position size")
            if "stop_loss_pct" in suggested:
                suggested["stop_loss_pct"] = round(
                    float(suggested["stop_loss_pct"]) * 1.25, 4
                )
            if "position_size_pct" in suggested:
                suggested["position_size_pct"] = round(
                    float(suggested["position_size_pct"]) * 0.8, 4
                )
            confidence = max(confidence, 0.65)

        # Rule 2 — high drawdown
        if max_dd > 0.20:
            reasoning_parts.append(
                f"Max drawdown {max_dd*100:.1f}% exceeds 20% — tighten risk limits."
            )
            suggestions.append("tighten risk limits")
            if "risk_pct" in suggested:
                suggested["risk_pct"] = round(float(suggested["risk_pct"]) * 0.75, 4)
            if "max_loss_per_day" in suggested:
                suggested["max_loss_per_day"] = round(
                    float(suggested["max_loss_per_day"]) * 0.9, 2
                )
            confidence = max(confidence, 0.70)

        # Rule 3 — low win rate
        if win_rate < 0.40:
            reasoning_parts.append(
                f"Win rate {win_rate*100:.1f}% is below 40% — entry conditions need tightening."
            )
            suggestions.append("tighten entry signal conditions")
            if "fast_period" in suggested:
                suggested["fast_period"] = max(
                    2, int(float(suggested["fast_period"]) - 1)
                )
            if "slow_period" in suggested:
                suggested["slow_period"] = int(float(suggested["slow_period"]) + 2)
            confidence = max(confidence, 0.55)

        if not suggestions:
            analysis = (
                f"Backtest metrics look reasonable "
                f"(Sharpe={sharpe:.2f}, DD={max_dd*100:.1f}%, WinRate={win_rate*100:.1f}%). "
                "No rule-based changes suggested — consider fine-tuning with LLM analysis."
            )
            reasoning = "No heuristic rules triggered."
            confidence = 0.3
        else:
            analysis = (
                f"Rule-based analysis for '{strategy_name}': "
                + " | ".join(reasoning_parts)
            )
            reasoning = "Changes: " + ", ".join(suggestions) + "."

        return RefinementSuggestion(
            strategy_name=strategy_name,
            analysis=analysis,
            suggested_params=suggested,
            reasoning=reasoning,
            confidence=confidence,
        )
