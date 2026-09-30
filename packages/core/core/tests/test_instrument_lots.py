"""Lot size comes from a scrip-master row, not a built-in contract table."""

from __future__ import annotations

import json
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from flinttrade_core.indian_charges import round_trip
from flinttrade_core.instrument_lots import (
    contract_quantity_message,
    fixture_path,
    load_fixture_rows,
    lot_size_for_contract,
    index_lot_line,
    lot_size_from_master,
    lot_sizes_from_rows,
    scalper_lot_label,
)

_ROOT = Path(__file__).resolve().parents[4]
_REVISION_PATH = Path(__file__).parent / "data" / "instrument_lot_revision_window.json"
_AS_OF = date(2026, 9, 1)
_SYNTHETIC_IDS = ("13", "14", "25", "51", "9013", "9014", "9025", "9051")


def _revision_window() -> tuple[list[dict[str, str]], dict[str, str]]:
    """Test-only rows. October stays 75; November is already listed at 65."""
    payload = json.loads(_REVISION_PATH.read_text(encoding="utf-8"))
    return payload["rows"], payload["clash_row"]


@pytest.mark.unit
def test_revision_window_keeps_both_sizes_and_rejects_one_conflict() -> None:
    rows, clash = _revision_window()
    nifty = [row for row in rows if row.get("SEM_CUSTOM_SYMBOL") == "NIFTY" or row.get("pSymbolName") == "NIFTY"]
    assert lot_sizes_from_rows(nifty) == {"13": 75, "14": 65, "9013": 75, "9014": 65}
    assert scalper_lot_label("NIFTY", nifty, as_of=_AS_OF) == "75 · Oct expiry, 65 · Nov expiry"
    assert scalper_lot_label("BANKNIFTY", rows, as_of=_AS_OF) == "30 · Sep expiry"
    assert scalper_lot_label("SENSEX", rows, as_of=_AS_OF) == "20 · Sep expiry"
    assert lot_size_from_master("FINNIFTY", rows, as_of=_AS_OF) is None
    with pytest.raises(ValueError, match="disagrees on the lot size for NIFTY 2026-10-27"):
        lot_size_for_contract("13", [*nifty, clash], as_of=_AS_OF)


@pytest.mark.unit
def test_charges_and_validation_use_each_contracts_lot() -> None:
    """The October contract is priced and checked at 75; November at 65."""
    rows, _clash = _revision_window()
    rows = [row for row in rows if row.get("SEM_CUSTOM_SYMBOL") == "NIFTY" or row.get("pSymbolName") == "NIFTY"]
    near = lot_size_for_contract("13", rows, as_of=_AS_OF)
    nxt = lot_size_for_contract("14", rows, as_of=_AS_OF)
    assert near == 75
    assert nxt == 65
    on = date(2026, 6, 1)
    near_notional = Decimal(near) * Decimal(25000)
    next_notional = Decimal(nxt) * Decimal(25000)
    near_buy, near_sell = round_trip(
        exchange="NSE",
        segment="equity_futures",
        buy_value=near_notional,
        sell_value=near_notional,
        on=on,
    )
    next_buy, next_sell = round_trip(
        exchange="NSE",
        segment="equity_futures",
        buy_value=next_notional,
        sell_value=next_notional,
        on=on,
    )
    assert near_buy.total + near_sell.total != next_buy.total + next_sell.total
    assert contract_quantity_message("13", 75, rows, as_of=_AS_OF) is None
    assert contract_quantity_message("13", 65, rows, as_of=_AS_OF) == (
        "Quantity must be a positive multiple of the lot size (75)"
    )
    assert contract_quantity_message("14", 65, rows, as_of=_AS_OF) is None
    assert contract_quantity_message("14", 75, rows, as_of=_AS_OF) == (
        "Quantity must be a positive multiple of the lot size (65)"
    )
    assert contract_quantity_message(
        "missing", 75, rows, as_of=_AS_OF, contract="NIFTY 24500 CE"
    ) == (
        "Not placed. The lot size for NIFTY 24500 CE isn't in the instrument master, "
        "so this order can't be sized."
    )
    assert contract_quantity_message(
        "missing", 65, rows, as_of=_AS_OF, contract="NIFTY24APR2524500CE"
    ) == (
        "Not placed. The lot size for NIFTY 24500 CE isn't in the instrument master, "
        "so this order can't be sized."
    )


@pytest.mark.unit
def test_charges_practice_and_calculator_do_not_hardcode_a_lot_map() -> None:
    """Those paths must not carry a per-underlying multiplier such as NIFTY 75."""
    paths = [
        _ROOT / "packages/core/core/src/flinttrade_core/indian_charges.py",
        _ROOT / "packages/core/data/src/flinttrade_data/sandbox_engine.py",
        _ROOT / "packages/apps/terminal/src/widgets/utility/Calculator/CalculatorWidget.tsx",
    ]
    forbidden = (
        '"NIFTY": 75',
        '"NIFTY": 25',
        '"NIFTY": 15',
        "NIFTY: 75",
        "NIFTY: 25",
        "lotSize: 25",
        "quantity: 25",
        "75-lot",
    )
    offenders: list[str] = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in text:
                offenders.append(f"{path.relative_to(_ROOT)} contains {token}")
    assert offenders == []


@pytest.mark.unit
def test_displayed_lot_sizes_do_not_revive_retired_index_lots() -> None:
    """Screener fallback, Scalper, demo client, the options builder, and the risk skill.

    A Nifty lot of 75 or 25, a Bank Nifty lot of 15 or 35, or a Sensex lot of
    10 in these sources is a retired contract multiplier.
    """
    from flinttrade_screener.lot_sizes import FALLBACK_LOT_SIZES

    paths = [
        _ROOT / "packages/services/screener/src/flinttrade_screener/lot_sizes.py",
        _ROOT / "packages/apps/terminal/src/widgets/trading/Scalper/types.ts",
        _ROOT / "packages/apps/terminal/src/widgets/trading/Scalper/ScalperControls.tsx",
        _ROOT / "packages/apps/terminal/src/widgets/trading/Scalper/ScalperWidget.tsx",
        _ROOT / "packages/apps/terminal/src/services/ftApi.screener.ts",
        _ROOT / "packages/apps/terminal/src/tools/StrategyBuilder/types.ts",
        _ROOT / "packages/services/ai/skills/risk_management.md",
        _ROOT / "packages/core/core/src/flinttrade_core/instrument_lots.py",
    ]
    forbidden = (
        '"NIFTY": 75',
        '"NIFTY": 25',
        "'NIFTY': 75",
        "'NIFTY': 25",
        "lotSize: 75",
        "lotSize: 25",
        "lotSize: 15",
        "lotSize: 35",
        "lotSize: 10",
        '"BANKNIFTY": 15',
        '"BANKNIFTY": 35',
        "'BANKNIFTY': 15",
        "'BANKNIFTY': 35",
        '"SENSEX": 10',
        "'SENSEX': 10",
        "? 75",
        ": 75",
        "else 75",
    )
    anchored = (
        re.compile(r"\bNIFTY\b\s*[:=]\s*(?:75|25)\b"),
        re.compile(r"\bBANKNIFTY\b\s*[:=]\s*(?:15|35)\b"),
        re.compile(r"\bSENSEX\b\s*[:=]\s*10\b"),
    )
    offenders: list[str] = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in text:
                offenders.append(f"{path.relative_to(_ROOT)} contains {token}")
        for pattern in anchored:
            if pattern.search(text):
                offenders.append(f"{path.relative_to(_ROOT)} matches {pattern.pattern}")
        for line in text.splitlines():
            if re.search(r"\bNIFTY\b", line, re.IGNORECASE) and re.search(r"\b(75|25)\b", line):
                offenders.append(f"{path.relative_to(_ROOT)} pairs Nifty with a retired lot: {line.strip()}")
            if re.search(r"\bBANK\s*NIFTY\b", line, re.IGNORECASE) and re.search(r"\b(15|35)\b", line):
                offenders.append(f"{path.relative_to(_ROOT)} pairs Bank Nifty with a retired lot: {line.strip()}")
            if re.search(r"\bSENSEX\b", line, re.IGNORECASE) and re.search(r"\b10\b", line):
                offenders.append(f"{path.relative_to(_ROOT)} pairs Sensex with a retired lot: {line.strip()}")
    assert offenders == []

    nifty = lot_size_from_master("NIFTY")
    bank = lot_size_from_master("BANKNIFTY")
    sensex = lot_size_from_master("SENSEX")
    if nifty is None:
        assert "NIFTY" not in FALLBACK_LOT_SIZES
    else:
        assert FALLBACK_LOT_SIZES["NIFTY"] == nifty
    if bank is None:
        assert "BANKNIFTY" not in FALLBACK_LOT_SIZES
    else:
        assert FALLBACK_LOT_SIZES["BANKNIFTY"] == bank
        assert FALLBACK_LOT_SIZES["BANKNIFTY"] not in {15, 35}
    if sensex is None:
        assert "SENSEX" not in FALLBACK_LOT_SIZES
    else:
        assert FALLBACK_LOT_SIZES["SENSEX"] == sensex
        assert FALLBACK_LOT_SIZES["SENSEX"] != 10


@pytest.mark.unit
def test_index_lot_line_uses_the_scalper_rows_and_marks_gaps() -> None:
    """Names stay with their lots. A missing underlying is an em dash, not a dropped name."""
    rows, _clash = _revision_window()
    nifty = [row for row in rows if row.get("SEM_CUSTOM_SYMBOL") == "NIFTY" or row.get("pSymbolName") == "NIFTY"]
    assert index_lot_line(nifty, as_of=_AS_OF) == (
        "NIFTY 75 · Oct expiry, 65 · Nov expiry · BANKNIFTY — · SENSEX — (Oct/Nov expiry)"
    )
    assert index_lot_line(rows, as_of=_AS_OF) == (
        "NIFTY 75 · Oct expiry, 65 · Nov expiry · BANKNIFTY 30 · SENSEX 20 (Sep/Oct/Nov expiry)"
    )
    assert not re.fullmatch(r"[\d\s·,./()-]+", index_lot_line(rows, as_of=_AS_OF))


@pytest.mark.unit
def test_risk_skill_lot_line_matches_the_scalper_labels() -> None:
    """The skill states the same near-month labels the Scalper reads from the master."""
    line = index_lot_line()
    assert line == "NIFTY 65 · BANKNIFTY 30 · SENSEX 20 (Sep/Oct expiry)"
    assert "—" not in line
    assert re.search(r"\bNIFTY\b", line) and re.search(r"\bBANKNIFTY\b", line) and re.search(r"\bSENSEX\b", line)
    skill = (_ROOT / "packages/services/ai/skills/risk_management.md").read_text(encoding="utf-8")
    assert line in skill


def _security_ids(payload: dict[str, object]) -> set[str]:
    found: set[str] = set()
    rows = payload.get("rows")
    if not isinstance(rows, list):
        return found
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key in ("SEM_SMST_SECURITY_ID", "pSymbol"):
            value = row.get(key)
            if isinstance(value, str) and value:
                found.add(value)
    return found


@pytest.mark.unit
def test_shipped_excerpt_names_its_source_and_has_no_synthetic_ids() -> None:
    payload = json.loads(fixture_path().read_text(encoding="utf-8"))
    assert isinstance(payload.get("source"), list) and payload["source"]
    assert all(isinstance(url, str) and url.startswith("https://") for url in payload["source"])
    assert isinstance(payload.get("fetched_at"), str) and payload["fetched_at"]
    assert _security_ids(payload).isdisjoint(_SYNTHETIC_IDS)
    for row in payload["rows"]:
        expiry = row.get("SEM_EXPIRY_DATE") or row.get("pExpiryDate")
        assert isinstance(expiry, str) and len(expiry) == 10


@pytest.mark.unit
def test_expired_contracts_are_dropped_when_the_date_is_frozen() -> None:
    rows, _clash = _revision_window()
    october = date(2026, 10, 28)
    assert lot_size_for_contract("13", rows, as_of=october) is None
    assert lot_size_for_contract("9013", rows, as_of=october) is None
    assert lot_size_for_contract("14", rows, as_of=october) == 65
    assert scalper_lot_label("NIFTY", rows, as_of=october) == "65 · Nov expiry"
    assert lot_size_from_master("BANKNIFTY", rows, as_of=date(2026, 9, 25)) is None
    assert contract_quantity_message("13", 75, rows, as_of=october) == (
        "Not placed. The lot size for NIFTY-OCT2026-FUT isn't in the instrument master, "
        "so this order can't be sized."
    )


@pytest.mark.unit
def test_session_cache_overrides_the_shipped_excerpt(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    cache = tmp_path / "instrument_lot_cache.json"
    cache.write_text(
        json.dumps(
            {
                "source": ["https://images.dhan.co/api-data/api-scrip-master.csv"],
                "fetched_at": "2026-10-01T09:00:00+05:30",
                "rows": [
                    {
                        "SEM_SMST_SECURITY_ID": "48704",
                        "SEM_CUSTOM_SYMBOL": "NIFTY",
                        "SEM_INSTRUMENT_NAME": "FUTIDX",
                        "SEM_TRADING_SYMBOL": "NIFTY-Oct2026-FUT",
                        "SEM_EXPIRY_DATE": "2026-10-27",
                        "SEM_LOT_UNITS": "65",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    assert lot_size_for_contract("48704", as_of=date(2026, 10, 1)) == 65
    assert lot_size_for_contract("68407", as_of=date(2026, 10, 1)) is None


@pytest.mark.unit
def test_ui_label_and_order_check_agree_after_a_revision(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A newer cache lot sizes both the label and the order check.

    The shipped excerpt keeps the previous lot. The two must not diverge.
    """
    from flask import Flask

    from flinttrade_core.instrument_lot_routes import instrument_lots_bp

    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    as_of = date(2026, 9, 29)
    assert lot_size_from_master("NIFTY", load_fixture_rows(), as_of=as_of) == 65
    assert scalper_lot_label("NIFTY", load_fixture_rows(), as_of=as_of) == "65 · Sep expiry"
    cache = tmp_path / "instrument_lot_cache.json"
    cache.write_text(
        json.dumps(
            {
                "source": ["https://images.dhan.co/api-data/api-scrip-master.csv"],
                "fetched_at": "2026-09-29T09:00:00+05:30",
                "rows": [
                    {
                        "SEM_SMST_SECURITY_ID": "CACHE-NIFTY",
                        "SEM_CUSTOM_SYMBOL": "NIFTY",
                        "SEM_INSTRUMENT_NAME": "FUTIDX",
                        "SEM_TRADING_SYMBOL": "NIFTY-Oct2026-FUT",
                        "SEM_EXPIRY_DATE": "2099-12-31",
                        "SEM_LOT_UNITS": "50",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    label = scalper_lot_label("NIFTY")
    assert label == "50 · Dec expiry"
    line = index_lot_line()
    assert line.startswith("NIFTY 50")
    assert "BANKNIFTY —" in line
    assert "SENSEX —" in line
    assert contract_quantity_message("CACHE-NIFTY", 50) is None
    assert contract_quantity_message("CACHE-NIFTY", 65) == (
        "Quantity must be a positive multiple of the lot size (50)"
    )
    app = Flask(__name__)
    app.register_blueprint(instrument_lots_bp)
    response = app.test_client().get("/api/v1/instrument-lots")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["line"] == line
    assert payload["line"].startswith("NIFTY 50")
    ids = {row.get("SEM_SMST_SECURITY_ID") for row in payload["rows"]}
    assert "CACHE-NIFTY" in ids
    assert lot_size_from_master("NIFTY", load_fixture_rows(), as_of=as_of) == 65


@pytest.mark.unit
def test_failed_download_writes_an_empty_excerpt(tmp_path: Path) -> None:
    from flinttrade_core.instrument_lot_master import build_excerpt, write_excerpt

    def _downloader(_url: str) -> str:
        raise OSError("offline")

    payload = build_excerpt(downloader=_downloader, as_of=date(2026, 9, 29))
    assert payload["rows"] == []
    assert payload["source"]
    assert payload["fetched_at"]
    destination = tmp_path / "excerpt.json"
    write_excerpt(destination, payload)
    written = json.loads(destination.read_text(encoding="utf-8"))
    assert written["rows"] == []
    assert "13" not in destination.read_text(encoding="utf-8")
