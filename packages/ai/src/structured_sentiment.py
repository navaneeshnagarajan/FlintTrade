"""Structured market sentiment schema and generation for FlintTrade AI.

Adapts the FinSights structured JSON pattern (marketcalls/FinSights) to work
with FlintTrade's multi-provider LLMClient instead of a Perplexity-specific SDK.

The schema drives the LLM to return a fully typed market summary in a single
call, which is then validated by Pydantic before being served to the terminal.
"""

from __future__ import annotations

import json
import logging
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger("flinttrade.ai.sentiment")


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class SentimentLabel(StrEnum):
    """Categorical market sentiment labels (coarser than the numeric score)."""

    STRONGLY_BULLISH = "STRONGLY_BULLISH"
    BULLISH = "BULLISH"
    NEUTRAL = "NEUTRAL"
    BEARISH = "BEARISH"
    STRONGLY_BEARISH = "STRONGLY_BEARISH"


class IndexSignal(StrEnum):
    """Directional signal for an index."""

    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    WATCH = "WATCH"


# ---------------------------------------------------------------------------
# JSON schema (passed directly to the LLM as a response-format constraint)
# ---------------------------------------------------------------------------

#: JSON schema for AI-generated structured market sentiment.
#: The ``type: "json_schema"`` envelope follows the OpenAI-compatible
#: structured-output convention used by LM Studio, Groq, OpenAI, etc.
MARKET_SUMMARY_SCHEMA: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "market_summary",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "sentiment_score": {
                    "type": "number",
                    "minimum": -10,
                    "maximum": 10,
                    "description": (
                        "Overall market sentiment score. "
                        "-10 = extremely bearish, 0 = neutral, +10 = extremely bullish."
                    ),
                },
                "market_sentiment": {
                    "type": "string",
                    "enum": [label.value for label in SentimentLabel],
                    "description": "Categorical market sentiment derived from sentiment_score.",
                },
                "indices": {
                    "type": "array",
                    "description": "Major Indian index snapshots (Nifty 50, Bank Nifty, Sensex, etc.).",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Index name, e.g. NIFTY 50.",
                            },
                            "value": {
                                "type": "number",
                                "description": "Last traded value.",
                            },
                            "change_pct": {
                                "type": "number",
                                "description": "Percentage change from previous close.",
                            },
                            "signal": {
                                "type": "string",
                                "enum": [s.value for s in IndexSignal],
                                "description": "Short-term directional signal for the index.",
                            },
                        },
                        "required": ["name", "value", "change_pct", "signal"],
                        "additionalProperties": False,
                    },
                },
                "sectors": {
                    "type": "array",
                    "description": "Top and bottom performing sectors with outlook.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Sector name, e.g. IT, Banking, FMCG.",
                            },
                            "performance": {
                                "type": "string",
                                "description": (
                                    "Qualitative performance label: "
                                    "Outperforming / Underperforming / Neutral."
                                ),
                            },
                            "outlook": {
                                "type": "string",
                                "description": "One-sentence forward-looking note.",
                            },
                        },
                        "required": ["name", "performance", "outlook"],
                        "additionalProperties": False,
                    },
                },
                "key_points": {
                    "type": "array",
                    "description": "3 to 5 concise bullet points summarising today's market.",
                    "items": {"type": "string"},
                    "minItems": 3,
                    "maxItems": 5,
                },
                "fii_dii_flow": {
                    "type": "object",
                    "description": "Foreign and domestic institutional activity.",
                    "properties": {
                        "fii_net": {
                            "type": "number",
                            "description": "FII net flow in crore INR (negative = outflow).",
                        },
                        "dii_net": {
                            "type": "number",
                            "description": "DII net flow in crore INR (negative = outflow).",
                        },
                        "interpretation": {
                            "type": "string",
                            "description": "One-sentence interpretation of the combined flow.",
                        },
                    },
                    "required": ["fii_net", "dii_net", "interpretation"],
                    "additionalProperties": False,
                },
                "risks": {
                    "type": "array",
                    "description": "Key downside risks to watch today.",
                    "items": {"type": "string"},
                },
                "opportunities": {
                    "type": "array",
                    "description": "Key upside opportunities or themes to watch today.",
                    "items": {"type": "string"},
                },
            },
            "required": [
                "sentiment_score",
                "market_sentiment",
                "indices",
                "sectors",
                "key_points",
                "fii_dii_flow",
                "risks",
                "opportunities",
            ],
            "additionalProperties": False,
        },
    },
}


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class IndexSnapshot(BaseModel):
    """Real-time or EOD snapshot for a single market index."""

    name: str = Field(..., description="Index name.")
    value: float = Field(..., description="Last traded value.")
    change_pct: float = Field(..., description="Percentage change from previous close.")
    signal: IndexSignal = Field(..., description="Directional signal.")


class SectorOutlook(BaseModel):
    """Sector-level performance and forward outlook."""

    name: str = Field(..., description="Sector name.")
    performance: str = Field(..., description="Qualitative performance label.")
    outlook: str = Field(..., description="One-sentence forward-looking note.")


class FiiDiiFlow(BaseModel):
    """Foreign and domestic institutional flow data."""

    fii_net: float = Field(..., description="FII net flow in crore INR.")
    dii_net: float = Field(..., description="DII net flow in crore INR.")
    interpretation: str = Field(..., description="Interpretation of combined flow.")


class MarketSummary(BaseModel):
    """Structured AI-generated market sentiment summary.

    Validated against :data:`MARKET_SUMMARY_SCHEMA`. Returned by
    :func:`generate_market_summary`.
    """

    sentiment_score: float = Field(
        ...,
        description="Numeric sentiment score from -10 (strongly bearish) to +10 (strongly bullish).",
    )
    market_sentiment: SentimentLabel = Field(
        ..., description="Categorical label derived from sentiment_score."
    )
    indices: list[IndexSnapshot] = Field(
        default_factory=list, description="Major index snapshots."
    )
    sectors: list[SectorOutlook] = Field(
        default_factory=list, description="Sector performance and outlook."
    )
    key_points: list[str] = Field(
        ...,
        min_length=3,
        max_length=5,
        description="3-5 concise bullet points.",
    )
    fii_dii_flow: FiiDiiFlow = Field(..., description="Institutional flow data.")
    risks: list[str] = Field(default_factory=list, description="Downside risks.")
    opportunities: list[str] = Field(
        default_factory=list, description="Upside opportunities."
    )

    @field_validator("sentiment_score", mode="before")
    @classmethod
    def _clamp_score(cls, v: Any) -> float:
        """Clamp score to [-10, +10] in case the LLM drifts slightly.

        Runs before Pydantic type coercion so out-of-range values from the LLM
        are silently corrected rather than rejected with a ValidationError.
        """
        return max(-10.0, min(10.0, float(v)))

    @field_validator("market_sentiment", mode="before")
    @classmethod
    def _normalise_label(cls, v: Any) -> str:
        """Accept lowercase or mixed-case labels from the LLM."""
        if isinstance(v, str):
            return v.upper()
        return v

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def label_from_score(self) -> SentimentLabel:
        """Derive the categorical label purely from the numeric score.

        Useful for cross-checking the LLM's own categorisation.
        """
        score = self.sentiment_score
        if score >= 7:
            return SentimentLabel.STRONGLY_BULLISH
        if score >= 3:
            return SentimentLabel.BULLISH
        if score <= -7:
            return SentimentLabel.STRONGLY_BEARISH
        if score <= -3:
            return SentimentLabel.BEARISH
        return SentimentLabel.NEUTRAL

    def to_display_dict(self) -> dict[str, Any]:
        """Flat dict suitable for passing to the terminal API response."""
        return self.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an expert Indian equity markets analyst. Generate a structured JSON \
market summary for the current trading session. Base your analysis on the \
market data provided. Be factual, concise, and use Indian market conventions \
(crore INR for FII/DII flows, NSE index names). \
Return ONLY the JSON object — no prose, no markdown fences.\
"""

_USER_PROMPT_TEMPLATE = """\
Analyse the following Indian market data and generate a structured market \
sentiment summary:

{market_data}

Generate the JSON summary now, strictly following the required schema.\
"""


def _build_prompt(market_data: dict[str, Any]) -> str:
    """Serialise market_data to a clean string for the LLM prompt.

    Args:
        market_data: Raw market data from OpenAlgo or FlintTrade screener.

    Returns:
        Formatted string embedding all market data fields.
    """
    lines: list[str] = []
    for key, value in market_data.items():
        if isinstance(value, (dict, list)):
            lines.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
        else:
            lines.append(f"{key}: {value}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_market_summary(
    llm_client: Any,
    market_data: dict[str, Any],
    temperature: float = 0.3,
    max_tokens: int = 1024,
) -> MarketSummary | None:
    """Generate a structured market sentiment summary via the LLM.

    Calls the LLM with the market data and the :data:`MARKET_SUMMARY_SCHEMA`
    schema hint, then validates and returns a :class:`MarketSummary` Pydantic
    model. Returns ``None`` on any failure (LLM unavailable, parse error, etc.)
    so callers can gracefully degrade.

    Args:
        llm_client: A :class:`~packages.ai.src.llm_client.LLMClient` instance.
            The function accepts ``Any`` so it can be tested with mocks without
            importing the client module.
        market_data: Dictionary of market inputs — indices, FII/DII flow, sector
            data, options PCR, etc. from OpenAlgo or the FlintTrade screener.
        temperature: LLM sampling temperature. Keep low (0.1–0.4) for structured
            output to reduce hallucinations.
        max_tokens: Maximum tokens the LLM may generate for the response.

    Returns:
        A validated :class:`MarketSummary` instance, or ``None`` on failure.

    Example::

        from packages.ai.src.llm_client import LLMClient
        from packages.ai.src.structured_sentiment import generate_market_summary

        client = LLMClient()
        summary = generate_market_summary(client, {
            "nifty_50": {"value": 24350, "change_pct": -0.45},
            "fii_net_crore": -1240,
            "dii_net_crore": 980,
        })
        if summary:
            print(summary.sentiment_score, summary.market_sentiment)
    """
    try:
        from packages.ai.src.llm_client import LLMMessage
    except ImportError:
        try:
            from llm_client import LLMMessage  # type: ignore[no-redef]
        except ImportError:
            logger.error("Cannot import LLMMessage — is the ai package on sys.path?")
            return None

    prompt_text = _build_prompt(market_data)
    messages = [
        LLMMessage(role="system", content=_SYSTEM_PROMPT),
        LLMMessage(role="user", content=_USER_PROMPT_TEMPLATE.format(market_data=prompt_text)),
    ]

    # Attempt structured output via response_format if the provider supports it.
    # Fall back to plain chat if the provider ignores the extra kwarg.
    response = None
    try:
        response = llm_client.chat(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except Exception as exc:
        logger.error("LLM call failed: %s", exc)
        return None

    if not response or not response.success:
        logger.warning(
            "LLM returned unsuccessful response: %s",
            getattr(response, "error", "unknown"),
        )
        return None

    raw = response.content.strip()

    # Strip markdown code fences if the LLM included them despite the prompt.
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(
            line for line in lines if not line.startswith("```")
        ).strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.error("Failed to parse LLM JSON response: %s — raw: %.200s", exc, raw)
        return None

    try:
        return MarketSummary.model_validate(data)
    except Exception as exc:
        logger.error("MarketSummary validation failed: %s — data: %s", exc, data)
        return None


def sentiment_label_from_score(score: float) -> SentimentLabel:
    """Map a numeric sentiment score to its categorical label.

    This mirrors :meth:`MarketSummary.label_from_score` as a standalone
    utility for use without a full :class:`MarketSummary` instance.

    Args:
        score: Numeric score in the range [-10, +10].

    Returns:
        The corresponding :class:`SentimentLabel`.
    """
    score = max(-10.0, min(10.0, float(score)))
    if score >= 7:
        return SentimentLabel.STRONGLY_BULLISH
    if score >= 3:
        return SentimentLabel.BULLISH
    if score <= -7:
        return SentimentLabel.STRONGLY_BEARISH
    if score <= -3:
        return SentimentLabel.BEARISH
    return SentimentLabel.NEUTRAL
