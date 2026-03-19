"""Backtest strategy sub-package.

This package shadows the parent ``strategies.py`` module when Python resolves
``import strategies`` with ``src/`` on sys.path. To keep backward compatibility,
we re-export everything from that module here so that existing test imports like
``from strategies import EMACrossover`` continue to work.

Additional strategies (e.g. EMASuperTrendDEMA) live in sub-modules of this package:
    from packages.backtest_engine.src.strategies.ema_supertrend_dema import EMASuperTrendDEMA
"""

from __future__ import annotations

# Re-export the entire public API of the parent strategies.py module.
# The parent file is not a package so we must import it by loading the .py
# file directly via importlib to avoid a circular reference.
import importlib.util
import os as _os

_parent_strategies_path = _os.path.join(_os.path.dirname(__file__), "..", "strategies.py")
_parent_strategies_path = _os.path.normpath(_parent_strategies_path)

_spec = importlib.util.spec_from_file_location("_backtest_strategies_parent", _parent_strategies_path)
if _spec is not None and _spec.loader is not None:
    _parent = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_parent)  # type: ignore[union-attr]

    # Re-export all public names
    from typing import Any as _Any

    def _re_export(name: str) -> _Any:
        return getattr(_parent, name)

    # Indicator helpers
    ema = _re_export("ema")
    sma = _re_export("sma")
    rsi = _re_export("rsi")
    bollinger_bands = _re_export("bollinger_bands")
    macd = _re_export("macd")
    supertrend = _re_export("supertrend")

    # Strategy classes
    _BacktestStrategyMixin = _re_export("_BacktestStrategyMixin")
    EMACrossover = _re_export("EMACrossover")
    SupertrendStrategy = _re_export("SupertrendStrategy")
    MACDRSIStrategy = _re_export("MACDRSIStrategy")
    BollingerMeanReversion = _re_export("BollingerMeanReversion")
    VWAPDeviation = _re_export("VWAPDeviation")
    StraddleSell = _re_export("StraddleSell")
    StrangleSell = _re_export("StrangleSell")
    IronCondor = _re_export("IronCondor")
    BullPutSpread = _re_export("BullPutSpread")
    BearCallSpread = _re_export("BearCallSpread")
    MomentumBreakout = _re_export("MomentumBreakout")
    OpeningRangeBreakout = _re_export("OpeningRangeBreakout")
    BUILTIN_STRATEGIES = _re_export("BUILTIN_STRATEGIES")

