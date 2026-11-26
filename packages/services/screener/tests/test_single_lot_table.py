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

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
PACKAGES = REPO_ROOT / "packages"

# A module-level lot table written out as a dict literal.
_LOT_TABLE_LITERAL = re.compile(r"^\s*(?P<name>\w*LOT\w*)\s*(?::[^=\n]*)?=\s*(?:dict\()?\{", re.MULTILINE)
# A front-end lot table (a ``*LOT*`` record) that lists an NSE index.
_TS_INDEX_LOT = re.compile(r"\w*LOT\w*[^=\n]*=\s*\{[^}]*\b(?:FINNIFTY|BANKNIFTY|MIDCPNIFTY)\b", re.IGNORECASE)

# A guessed lot used when none is known: an annotated default, the default of a
# ``.get("lot_size", ...)``, or the fallback of a lot table ``.get``. 0 and 1
# mean "no lot" and are allowed.
_LOT_DEFAULT_LITERAL = re.compile(
    r"\blot_?size\w*\s*:[^=\n]*=\s*(?P<annotated>\d[\d_]*)\b"
    r"|\.get\(\s*[\"'](?:lot_?size|lotsize)[\"']\s*,\s*(?P<body>\d[\d_]*)"
    r"|\w*LOT\w*\.get\([^\n]*?,\s*(?P<table>\d[\d_]*)\s*\)",
    re.IGNORECASE,
)

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


# A front-end lot that falls back to 1 when none is known.
_TS_LOT_FALLBACK = re.compile(
    r"\blot\w*\s*(?:\?\?|\|\|)\s*1\b"
    r"|\.lotsize\s*>\s*0\s*\?\s*[\w.]+\s*:\s*1\b"
    r"|LOT\w*\[[^\]\n]*\]\s*\?\?\s*1\b",
    re.IGNORECASE,
)


@pytest.mark.parametrize(
    "line",
    [
        "Qty: {lots} × {lotSize ?? 1} = {displayQuantity}",
        "setLotSize(info.lotsize > 0 ? info.lotsize : 1);",
        "return MCX_LOT_SIZES[symbol.toUpperCase()] ?? 1;",
        "const lot = row.lot_size || 1;",
    ],
)
def test_ts_lot_fallback_guard_catches_a_lot_of_one(line: str) -> None:
    assert _TS_LOT_FALLBACK.search(line)


def test_terminal_source_has_no_lot_fallback_of_one() -> None:
    terminal = PACKAGES / "apps" / "terminal" / "src"
    hits = [
        f"{path.relative_to(REPO_ROOT)}: {match.group(0)}"
        for pattern in ("*.ts", "*.tsx")
        for path in terminal.rglob(pattern)
        if "__tests__" not in path.parts and ".test." not in path.name
        for match in _TS_LOT_FALLBACK.finditer(path.read_text(encoding="utf-8", errors="ignore"))
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

    call = parse_order_command("Buy SENSEX26DEC85000CE 2 lots")
    assert call is not None
    assert call.tool_name == "lot_size_unknown"
    assert call.arguments == {"message": "The lot size for SENSEX isn't known. Order not placed."}
    assert parse_order_command("Buy RELIANCE 10 shares") is not None


def _lot_default_hits(text: str) -> list[str]:
    hits = []
    for match in _LOT_DEFAULT_LITERAL.finditer(text):
        value = next(group for group in match.groups() if group is not None)
        if int(value.replace("_", "")) > 1:
            hits.append(match.group(0))
    return hits


@pytest.mark.parametrize(
    "line",
    [
        'lot_size = FALLBACK_LOT_SIZES.get(symbol.strip().upper(), 50)',
        'lot_size: int = int(body.get("lot_size", 50))',
        "        lot_size: int = 50,",
        "    lot_size: int = 65",
    ],
)
def test_lot_default_guard_catches_a_guessed_lot(line: str) -> None:
    assert _lot_default_hits(line)


def test_lot_default_guard_allows_no_lot() -> None:
    assert not _lot_default_hits('lot_size = int(body.get("lot_size", 1) or 1)')
    assert not _lot_default_hits("lot_size = _LOT_SIZE_TABLE.get(base, 0)")


def test_no_python_source_guesses_a_lot() -> None:
    found = [
        f"{path.relative_to(REPO_ROOT)}: {hit}"
        for path in _python_sources()
        for hit in _lot_default_hits(path.read_text(encoding="utf-8", errors="ignore"))
    ]
    assert found == []
