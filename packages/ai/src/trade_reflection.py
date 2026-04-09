"""Automated batch trade reflection system.

Absorbed from LLM-TradeBot/src/agents/reflection_agent.py:
- Trigger-every-N-trades pattern
- Structured JSON output for patterns and recommendations
- Rule-based fallback when no LLM is configured (confidence calibration,
  win-rate, risk-reward diagnostics)
- LLM-enhanced path when an LLMClient is supplied

This module is distinct from reflection.py (single-trade post-trade loop).
That module processes individual closed trades; this module processes *batches*
of trades and produces strategic meta-analysis.

Usage::

    from packages.ai.src.trade_reflection import TradeReflector, ReflectionConfig

    reflector = TradeReflector(config=ReflectionConfig())

    # After each trade:
    if reflector.should_reflect(total_trade_count):
        result = await reflector.reflect(recent_trades_list)
        print(result.recommendations)

Trade dict format (flexible — reflector tolerates missing keys)::

    {
        "symbol":      "NIFTY",
        "action":      "BUY",          # or "side"
        "entry_price": 22000.0,
        "exit_price":  22450.0,
        "pnl":         450.0,          # absolute INR
        "pnl_pct":     2.05,           # % of entry value
        "confidence":  0.8,            # optional
        "timestamp":   "2026-04-09",   # optional
    }
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger("flinttrade.ai.trade_reflection")


# ---------------------------------------------------------------------------
# Config and result models
# ---------------------------------------------------------------------------


class ReflectionConfig(BaseModel):
    """Configuration for TradeReflector.

    Attributes:
        trigger_every_n_trades: How many completed trades between reflections.
        lookback_trades: Maximum number of trades to include in one reflection.
        min_trades_for_reflection: Minimum trades required to run reflection.
    """

    trigger_every_n_trades: int = Field(default=10, ge=1)
    lookback_trades: int = Field(default=20, ge=1)
    min_trades_for_reflection: int = Field(default=5, ge=1)


class ReflectionResult(BaseModel):
    """Output of a single reflection run.

    Attributes:
        timestamp: UTC time the reflection was generated.
        trades_analysed: Number of trades included in the analysis.
        win_rate: Fraction of winning trades (0–1).
        avg_pnl: Average P&L percentage across analysed trades.
        winning_patterns: List of observed patterns in winning trades.
        losing_patterns: List of observed patterns in losing trades.
        recommendations: Actionable suggestions for the next N trades.
        confidence: Self-reported confidence of the reflection (0–1).
        market_insights: Free-text observations about recent market behaviour.
        confidence_calibration: Assessment of whether the agent's confidence
            scores align with actual trade outcomes.
    """

    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    trades_analysed: int
    win_rate: float = Field(ge=0.0, le=1.0)
    avg_pnl: float
    winning_patterns: list[str]
    losing_patterns: list[str]
    recommendations: list[str]
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    market_insights: str = ""
    confidence_calibration: str = ""


# ---------------------------------------------------------------------------
# TradeReflector
# ---------------------------------------------------------------------------


class TradeReflector:
    """Automated trade reflection system for FlintTrade AI agents.

    Tracks a rolling trade count and triggers structured analysis every
    ``config.trigger_every_n_trades`` completed trades.

    When an LLM client is supplied, reflection is LLM-enhanced (structured
    JSON extracted from the model response). Without an LLM client, a fast
    rule-based fallback is used — this is the default and works without any
    external service.

    Args:
        config: ReflectionConfig controlling trigger frequency and lookback.
        llm_client: Optional LLMClient instance. If provided, reflection
            uses the LLM for pattern extraction. If None, rule-based fallback.

    Example::

        reflector = TradeReflector(config=ReflectionConfig(trigger_every_n_trades=5))
        if reflector.should_reflect(trade_count):
            result = await reflector.reflect(last_20_trades)
    """

    def __init__(
        self,
        config: ReflectionConfig | None = None,
        llm_client: Any | None = None,
    ) -> None:
        self._config = config or ReflectionConfig()
        self._llm_client = llm_client
        self._last_reflected_count: int = 0
        self._reflection_history: list[ReflectionResult] = []
        logger.info(
            "TradeReflector initialised (trigger_every=%d, llm=%s)",
            self._config.trigger_every_n_trades,
            "yes" if llm_client else "no (rule-based fallback)",
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def should_reflect(self, trade_count: int) -> bool:
        """Return True when a new reflection should be triggered.

        Args:
            trade_count: Total number of completed trades since session start.

        Returns:
            True if ``trade_count - last_reflected`` >= trigger threshold.
        """
        trades_since = trade_count - self._last_reflected_count
        return trades_since >= self._config.trigger_every_n_trades

    async def reflect(self, recent_trades: list[dict[str, Any]]) -> ReflectionResult | None:
        """Analyse recent trades and generate a ReflectionResult.

        Uses LLM if configured, falls back to rule-based analysis otherwise.
        The result is appended to the internal history and the last-reflected
        counter is advanced by the number of trades analysed.

        Args:
            recent_trades: List of trade dicts. See module docstring for
                expected keys. Missing keys are handled gracefully.

        Returns:
            ReflectionResult, or None if fewer than min_trades_for_reflection
            valid trades are provided.
        """
        trades = recent_trades[: self._config.lookback_trades]
        if len(trades) < self._config.min_trades_for_reflection:
            logger.warning(
                "TradeReflector: only %d trades supplied, minimum is %d — skipping",
                len(trades),
                self._config.min_trades_for_reflection,
            )
            return None

        if self._llm_client is not None:
            result = await self._llm_reflect(trades)
        else:
            result = self._rule_reflect(trades)

        if result is not None:
            self._reflection_history.append(result)
            self._last_reflected_count += len(trades)
            logger.info(
                "TradeReflector: reflection #%d — %d trades, win_rate=%.1f%%, avg_pnl=%.2f%%",
                len(self._reflection_history),
                result.trades_analysed,
                result.win_rate * 100,
                result.avg_pnl,
            )

        return result

    def get_reflection_prompt(self, trades: list[dict[str, Any]]) -> str:
        """Build the LLM reflection prompt for a set of trades.

        This is public so callers can inspect or log the prompt before
        submitting it to their own LLM client.

        Args:
            trades: List of trade dicts.

        Returns:
            Formatted prompt string.
        """
        return self._build_user_prompt(trades)

    def get_history(self) -> list[ReflectionResult]:
        """Return all past ReflectionResult objects, oldest first.

        Returns:
            Immutable view (copy) of the reflection history list.
        """
        return list(self._reflection_history)

    def latest(self) -> ReflectionResult | None:
        """Return the most recent ReflectionResult, or None.

        Returns:
            The last ReflectionResult produced, or None if no reflections have
            been run yet.
        """
        return self._reflection_history[-1] if self._reflection_history else None

    def format_for_prompt(self) -> str:
        """Format the latest reflection as an LLM-ready context block.

        Returns:
            Formatted string suitable for injection into an LLM system prompt,
            or an empty string if no reflections have been run.
        """
        result = self.latest()
        if result is None:
            return ""
        lines = [
            f"[Trade Reflection — {result.timestamp.strftime('%Y-%m-%d %H:%M UTC')}]",
            f"Trades analysed: {result.trades_analysed}",
            f"Win rate: {result.win_rate * 100:.1f}%  |  Avg P&L: {result.avg_pnl:+.2f}%",
            "",
            "Winning patterns:",
            *[f"  - {p}" for p in result.winning_patterns[:3]],
            "",
            "Losing patterns:",
            *[f"  - {p}" for p in result.losing_patterns[:3]],
            "",
            "Recommendations:",
            *[f"  - {r}" for r in result.recommendations[:3]],
        ]
        if result.confidence_calibration:
            lines += ["", f"Confidence calibration: {result.confidence_calibration}"]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Rule-based fallback (no LLM)
    # ------------------------------------------------------------------

    def _rule_reflect(self, trades: list[dict[str, Any]]) -> ReflectionResult:
        """Produce a rule-based ReflectionResult without an LLM.

        Absorbed from LLM-TradeBot ReflectionAgent (no-LLM variant):
        win-rate, risk-reward, confidence calibration, and action stats.

        Args:
            trades: List of trade dicts.

        Returns:
            ReflectionResult populated from statistical analysis.
        """
        pnls: list[float] = []
        win_pnls: list[float] = []
        loss_pnls: list[float] = []
        conf_wins: list[float] = []
        conf_losses: list[float] = []
        action_pnls: dict[str, list[float]] = {}

        for trade in trades:
            pnl = self._extract_pnl(trade)
            pnls.append(pnl)

            action = str(trade.get("action") or trade.get("side") or "UNKNOWN").upper()
            action_pnls.setdefault(action, []).append(pnl)

            confidence = self._extract_confidence(trade)
            if pnl > 0:
                win_pnls.append(pnl)
                if confidence is not None:
                    conf_wins.append(confidence)
            elif pnl < 0:
                loss_pnls.append(abs(pnl))
                if confidence is not None:
                    conf_losses.append(confidence)

        wins = len(win_pnls)
        losses = len(loss_pnls)
        total = wins + losses or len(trades)
        win_rate = wins / total if total > 0 else 0.0
        avg_pnl = sum(pnls) / len(pnls) if pnls else 0.0
        avg_win = sum(win_pnls) / len(win_pnls) if win_pnls else 0.0
        avg_loss = sum(loss_pnls) / len(loss_pnls) if loss_pnls else 0.0

        # Confidence calibration
        avg_conf_win = sum(conf_wins) / len(conf_wins) if conf_wins else None
        avg_conf_loss = sum(conf_losses) / len(conf_losses) if conf_losses else None
        if avg_conf_win is not None and avg_conf_loss is not None:
            confidence_calibration = (
                "Confidence aligns with outcomes — winning trades carry higher confidence."
                if avg_conf_win >= avg_conf_loss
                else "Mis-calibrated — losing trades carry higher confidence; recalibrate."
            )
        else:
            confidence_calibration = "Insufficient confidence data for calibration."

        # Patterns
        winning_patterns: list[str] = []
        losing_patterns: list[str] = []

        if win_rate >= 0.55:
            winning_patterns.append("Win rate above 55% — current entry filters are effective.")
        if avg_win > avg_loss > 0:
            winning_patterns.append("Average win exceeds average loss — risk-reward is healthy.")

        # Best-performing action
        best_action: str | None = None
        best_avg: float | None = None
        for action, pnl_list in action_pnls.items():
            if len(pnl_list) < 2:
                continue
            avg = sum(pnl_list) / len(pnl_list)
            if best_avg is None or avg > best_avg:
                best_avg = avg
                best_action = action
        if best_action and best_avg is not None and best_avg > 0:
            winning_patterns.append(f"{best_action} trades show the strongest average P&L.")

        if win_rate < 0.45:
            losing_patterns.append("Win rate below 45% — entry edge is weak; tighten filters.")
        if avg_loss > avg_win:
            losing_patterns.append("Average loss exceeds average win — risk-reward needs tightening.")
        if avg_pnl < 0:
            losing_patterns.append("Net P&L is negative — review position sizing.")

        # Recommendations
        recommendations: list[str] = []
        if win_rate < 0.50:
            recommendations.append("Reduce low-conviction trades; wait for cleaner setups.")
        if avg_loss > avg_win:
            recommendations.append("Tighten stop-losses or reduce size on counter-trend entries.")
        if avg_conf_win is not None and avg_conf_loss is not None and avg_conf_win < avg_conf_loss:
            recommendations.append("Recalibrate confidence scoring — avoid high-confidence overrides.")
        if best_action and best_avg is not None and best_avg > 0:
            recommendations.append(f"Favour {best_action} setups until regime changes.")
        if not recommendations:
            recommendations.append("Maintain discipline; prioritise high-conviction, trend-aligned setups.")

        return ReflectionResult(
            trades_analysed=len(trades),
            win_rate=win_rate,
            avg_pnl=avg_pnl,
            winning_patterns=winning_patterns,
            losing_patterns=losing_patterns,
            recommendations=recommendations,
            confidence=0.75,
            confidence_calibration=confidence_calibration,
            market_insights=(
                "Rule-based analysis — no LLM. Prioritise trend-aligned entries."
                if len(trades) >= 5
                else "Sample size is limited; maintain conservative risk."
            ),
        )

    # ------------------------------------------------------------------
    # LLM-enhanced path
    # ------------------------------------------------------------------

    async def _llm_reflect(self, trades: list[dict[str, Any]]) -> ReflectionResult | None:
        """Produce an LLM-enhanced ReflectionResult.

        Falls back to the rule-based analyser if the LLM call fails or returns
        unparseable JSON.

        Args:
            trades: List of trade dicts.

        Returns:
            ReflectionResult or None on unrecoverable failure.
        """
        from packages.ai.src.llm_client import LLMMessage  # local import to avoid circular deps

        system_prompt = (
            "You are a professional trading retrospection analyst for Indian F&O and equity markets.\n"
            "Analyse the provided trade history and return a JSON object with these exact keys:\n"
            "  summary, win_rate (0-1), avg_pnl (%), winning_patterns (list), "
            "losing_patterns (list), recommendations (list), confidence (0-1), "
            "market_insights, confidence_calibration.\n"
            "Be specific and data-driven. No markdown, pure JSON only."
        )
        user_prompt = self._build_user_prompt(trades)

        messages = [
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(role="user", content=user_prompt),
        ]

        try:
            response = self._llm_client.chat(messages)
            raw = response.content.strip()

            # Strip markdown code fences if present
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0].strip()
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0].strip()

            data: dict[str, Any] = json.loads(raw)

            return ReflectionResult(
                trades_analysed=len(trades),
                win_rate=float(data.get("win_rate", 0.0)),
                avg_pnl=float(data.get("avg_pnl", 0.0)),
                winning_patterns=list(data.get("winning_patterns", [])),
                losing_patterns=list(data.get("losing_patterns", [])),
                recommendations=list(data.get("recommendations", [])),
                confidence=float(data.get("confidence", 0.8)),
                market_insights=str(data.get("market_insights", "")),
                confidence_calibration=str(data.get("confidence_calibration", "")),
            )

        except json.JSONDecodeError as exc:
            logger.warning("TradeReflector: LLM returned invalid JSON (%s) — using rule fallback", exc)
            return self._rule_reflect(trades)
        except Exception as exc:
            logger.error("TradeReflector: LLM call failed (%s) — using rule fallback", exc)
            return self._rule_reflect(trades)

    # ------------------------------------------------------------------
    # Prompt builder
    # ------------------------------------------------------------------

    def _build_user_prompt(self, trades: list[dict[str, Any]]) -> str:
        """Build the user-facing prompt sent to the LLM.

        Args:
            trades: List of trade dicts.

        Returns:
            Formatted prompt string.
        """
        rows: list[str] = []
        total_pnl = 0.0
        wins = losses = 0
        win_pnls: list[float] = []
        loss_pnls: list[float] = []

        for i, trade in enumerate(trades, 1):
            symbol = trade.get("symbol", "UNKNOWN")
            action = trade.get("action") or trade.get("side") or "?"
            entry = trade.get("entry_price", 0.0)
            exit_ = trade.get("exit_price") or trade.get("close_price") or 0.0
            pnl_pct = self._extract_pnl(trade)
            ts = trade.get("timestamp") or trade.get("time") or ""

            total_pnl += pnl_pct
            if pnl_pct > 0:
                wins += 1
                win_pnls.append(pnl_pct)
            elif pnl_pct < 0:
                losses += 1
                loss_pnls.append(abs(pnl_pct))

            pnl_str = f"+{pnl_pct:.2f}%" if pnl_pct >= 0 else f"{pnl_pct:.2f}%"
            rows.append(f"| {i} | {ts} | {symbol} | {action} | {entry:.2f} | {exit_:.2f} | {pnl_str} |")

        total_trades = wins + losses or len(trades)
        win_rate = wins / total_trades * 100 if total_trades > 0 else 0
        avg_win = sum(win_pnls) / len(win_pnls) if win_pnls else 0
        avg_loss = sum(loss_pnls) / len(loss_pnls) if loss_pnls else 0

        table = "\n".join(rows)
        return (
            f"## Recent Trade History (Last {len(trades)} Trades)\n\n"
            f"| # | Time | Symbol | Action | Entry | Exit | PnL% |\n"
            f"|---|------|--------|--------|-------|------|------|\n"
            f"{table}\n\n"
            f"## Summary\n"
            f"- Total trades: {total_trades}\n"
            f"- Win rate: {win_rate:.1f}% ({wins} wins, {losses} losses)\n"
            f"- Avg win: +{avg_win:.2f}%  |  Avg loss: -{avg_loss:.2f}%\n"
            f"- Net P&L: {'+' if total_pnl >= 0 else ''}{total_pnl:.2f}%\n\n"
            "Analyse and return valid JSON as instructed."
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_pnl(trade: dict[str, Any]) -> float:
        """Extract P&L percentage from a trade dict, trying several keys.

        Args:
            trade: Trade dict with potentially varied key names.

        Returns:
            P&L as a float (percentage). Returns 0.0 if no matching key found.
        """
        for key in ("pnl_pct", "pnl", "realized_pnl", "profit_pct", "profit"):
            val = trade.get(key)
            if val is not None:
                try:
                    return float(val)
                except (TypeError, ValueError):
                    pass
        return 0.0

    @staticmethod
    def _extract_confidence(trade: dict[str, Any]) -> float | None:
        """Extract optional confidence score from a trade dict.

        Args:
            trade: Trade dict.

        Returns:
            Confidence float or None if not present.
        """
        for key in ("confidence", "conf", "confidence_score", "score"):
            val = trade.get(key)
            if val is not None:
                try:
                    return float(val)
                except (TypeError, ValueError):
                    pass
        return None
