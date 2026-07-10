"""Compatibility exports for the canonical adversarial debate team mode.

The implementation lives in :mod:`flinttrade_ai._team_modes`.  This module
retains the established import path for downstream users.
"""

from ._team_modes import DebateResult, DebateRound, RiskDebate

__all__ = ["DebateResult", "DebateRound", "RiskDebate"]
