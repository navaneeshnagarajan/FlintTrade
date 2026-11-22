"""Guard: FlintTrade keeps exactly one built-in lot table.

Contract sizes come from the instrument master where it lists a contract and
from ``flinttrade_screener.lot_sizes.FALLBACK_LOT_SIZES`` otherwise. Every
other module reads that lookup. A second hand-written table drifts (the old
option-chain copy fed the Greeks a stale FINNIFTY size), so these tests fail
the moment one reappears.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
PACKAGES = REPO_ROOT / "packages"

# A module-level lot table written out as a dict literal.
_LOT_TABLE_LITERAL = re.compile(r"^\s*(?P<name>\w*LOT\w*)\s*(?::[^=\n]*)?=\s*(?:dict\()?\{", re.MULTILINE)
# A front-end lot table (a ``*LOT*`` record) that lists an NSE index.
_TS_INDEX_LOT = re.compile(r"\w*LOT\w*[^=\n]*=\s*\{[^}]*\b(?:FINNIFTY|BANKNIFTY|MIDCPNIFTY)\b", re.IGNORECASE)


def _python_sources() -> list[Path]:
    return [
        path
        for path in PACKAGES.rglob("*.py")
        if "/tests/" not in path.as_posix()
        and "/node_modules/" not in path.as_posix()
        and "/.venv/" not in path.as_posix()
    ]


def test_only_one_python_lot_table_literal() -> None:
    found = []
    for path in _python_sources():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in _LOT_TABLE_LITERAL.finditer(text):
            found.append(f"{path.relative_to(REPO_ROOT)}:{match.group('name')}")
    assert found == ["packages/services/screener/src/flinttrade_screener/lot_sizes.py:FALLBACK_LOT_SIZES"]


def test_option_chain_has_no_lot_table() -> None:
    from flinttrade_screener import option_chain

    assert not hasattr(option_chain, "LOT_SIZES")


def test_remaining_aliases_are_the_shared_table() -> None:
    from flinttrade_backtest.strategies import options_short_straddle_indian
    from flinttrade_screener import sample_data_routes
    from flinttrade_screener.lot_sizes import FALLBACK_LOT_SIZES

    assert options_short_straddle_indian.LOT_SIZES is FALLBACK_LOT_SIZES
    assert sample_data_routes._LOT_SIZE_TABLE is FALLBACK_LOT_SIZES


def test_terminal_source_has_no_index_lot_literal() -> None:
    terminal = PACKAGES / "apps" / "terminal" / "src"
    hits = [
        str(path.relative_to(REPO_ROOT))
        for pattern in ("*.ts", "*.tsx")
        for path in terminal.rglob(pattern)
        if "__tests__" not in path.parts and _TS_INDEX_LOT.search(path.read_text(encoding="utf-8", errors="ignore"))
    ]
    assert hits == []


def test_finnifty_is_60_everywhere() -> None:
    from flinttrade_backtest.strategies.ema_supertrend_dema import lot_size_for as ema_lot_size_for
    from flinttrade_backtest.strategies.options_short_straddle_indian import lot_size_for
    from flinttrade_screener.greeks import PortfolioGreeks
    from flinttrade_screener.lot_sizes import FALLBACK_LOT_SIZES, get_lot_size_sync
    from flinttrade_screener.option_chain import OptionChainAnalyzer

    assert FALLBACK_LOT_SIZES["FINNIFTY"] == 60
    assert get_lot_size_sync("FINNIFTY") == 60
    assert OptionChainAnalyzer.get_lot_size("FINNIFTY") == 60
    assert PortfolioGreeks.from_lot_size("FINNIFTY", lots=2) == 120
    assert lot_size_for("FINNIFTY") == 60
    assert ema_lot_size_for("FINNIFTY") == 60


def test_sensex_lot_comes_from_the_master() -> None:
    from flinttrade_core.instrument_lots import lot_size_from_master
    from flinttrade_screener.greeks import PortfolioGreeks
    from flinttrade_screener.option_chain import OptionChainAnalyzer

    master = lot_size_from_master("SENSEX")
    assert master is not None
    assert OptionChainAnalyzer.get_lot_size("SENSEX") == master
    assert PortfolioGreeks.from_lot_size("SENSEX") == master


def test_missing_sensex_master_row_leaves_the_lot_unknown(monkeypatch) -> None:
    from flinttrade_backtest.strategies.ema_supertrend_dema import lot_size_for as ema_lot_size_for
    from flinttrade_backtest.strategies.options_short_straddle_indian import lot_size_for
    from flinttrade_screener.greeks import PortfolioGreeks
    from flinttrade_screener.lot_sizes import FALLBACK_LOT_SIZES, get_lot_size_sync
    from flinttrade_screener.option_chain import OptionChainAnalyzer

    monkeypatch.delitem(FALLBACK_LOT_SIZES, "SENSEX", raising=False)

    assert get_lot_size_sync("SENSEX") is None
    assert OptionChainAnalyzer.get_lot_size("SENSEX") is None
    assert PortfolioGreeks.from_lot_size("SENSEX", lots=2) is None
    assert lot_size_for("SENSEX") is None
    assert ema_lot_size_for("SENSEX") is None


def test_strategies_refuse_an_unknown_derivatives_lot(monkeypatch) -> None:
    import pytest

    from flinttrade_backtest.strategies.ema_supertrend_dema import EMASuperTrendDEMA
    from flinttrade_backtest.strategies.options_short_straddle_indian import IndianShortStraddle
    from flinttrade_screener.lot_sizes import FALLBACK_LOT_SIZES

    monkeypatch.delitem(FALLBACK_LOT_SIZES, "SENSEX", raising=False)

    with pytest.raises(ValueError, match="The lot size for SENSEX isn't known."):
        IndianShortStraddle(underlying="SENSEX")
    with pytest.raises(ValueError, match="The lot size for SENSEX isn't known."):
        EMASuperTrendDEMA(symbol="SENSEX", exchange="BFO")


def test_cash_strategy_keeps_a_one_share_unit() -> None:
    from flinttrade_backtest.strategies.ema_supertrend_dema import EMASuperTrendDEMA

    strategy = EMASuperTrendDEMA(symbol="RELIANCE", exchange="NSE", lots=3)
    assert strategy._quantity == "3"


def test_order_command_with_lots_refuses_an_unknown_lot(monkeypatch) -> None:
    from flinttrade_ai.mcp_bridge import parse_order_command
    from flinttrade_screener.lot_sizes import FALLBACK_LOT_SIZES

    monkeypatch.delitem(FALLBACK_LOT_SIZES, "SENSEX", raising=False)

    assert parse_order_command("Buy SENSEX26DEC85000CE 2 lots") is None
    assert parse_order_command("Buy RELIANCE 10 shares") is not None
