"""Compatibility imports for canonical structured market sentiment.

The schema, models, prompt builder, and generator live in
:mod:`flinttrade_ai.sentiment`. This module retains the former import surface
without carrying a second implementation.
"""

from .sentiment import (
    MARKET_SUMMARY_SCHEMA,
    FiiDiiFlow,
    IndexSignal,
    IndexSnapshot,
    MarketSummary,
    SectorOutlook,
    SentimentLabel,
    _SCHEMA_HINT,
    _SYSTEM_PROMPT,
    _USER_PROMPT_TEMPLATE,
    _build_prompt,
    generate_market_summary,
    prepare_market_summary_data,
    sentiment_label_from_score,
)

__all__ = [
    "MARKET_SUMMARY_SCHEMA",
    "FiiDiiFlow",
    "IndexSignal",
    "IndexSnapshot",
    "MarketSummary",
    "SectorOutlook",
    "SentimentLabel",
    "_SCHEMA_HINT",
    "_SYSTEM_PROMPT",
    "_USER_PROMPT_TEMPLATE",
    "_build_prompt",
    "generate_market_summary",
    "prepare_market_summary_data",
    "sentiment_label_from_score",
]
