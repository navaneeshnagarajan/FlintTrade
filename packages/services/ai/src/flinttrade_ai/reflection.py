"""Compatibility imports for the canonical trade-reflection implementation.

New code should import from :mod:`flinttrade_ai.trade_reflection`. This module
remains so existing single-trade imports resolve to the same classes rather than
retaining a second implementation.
"""

from .trade_reflection import TradeOutcome, TradeReflector

__all__ = ["TradeOutcome", "TradeReflector"]
