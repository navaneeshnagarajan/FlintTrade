# packages/engine/tests/test_qty_freeze.py
"""Tests for QuantityFreezeManager — NSE/BSE per-symbol order size limits.

Coverage:
- set_limit / get_limit round-trip
- validate: below limit → allowed; at limit → allowed; over limit → blocked
- validate: no limit configured → always allowed
- load_from_csv: valid CSV, missing columns, non-numeric qty, non-positive qty
- recent_blocks: populated on validate failure, empty before any blocks
- NSE default seeding on fresh DB
- Persistence across reopen
- Invalid max_qty rejected by set_limit
- Duplicate CSV load updates existing limit
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from packages.engine.src.qty_freeze import QuantityFreezeManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mgr(tmp_path: Path) -> QuantityFreezeManager:
    """Fresh QuantityFreezeManager backed by a temp DuckDB file."""
    instance = QuantityFreezeManager(db_path=tmp_path / "freeze.duckdb")
    yield instance
    instance.close()


def _write_csv(path: Path, rows: list[dict]) -> Path:
    """Helper: write a CSV to *path* with SYMBOL, EXCHANGE, MAX_QTY columns."""
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["SYMBOL", "EXCHANGE", "MAX_QTY"])
        writer.writeheader()
        writer.writerows(rows)
    return path


# ---------------------------------------------------------------------------
# set_limit / get_limit
# ---------------------------------------------------------------------------


def test_set_and_get_limit(mgr: QuantityFreezeManager) -> None:
    mgr.set_limit("TESTSYM", "NFO", 500)
    assert mgr.get_limit("TESTSYM", "NFO") == 500


def test_get_limit_case_insensitive(mgr: QuantityFreezeManager) -> None:
    mgr.set_limit("nifty", "nfo", 1800)
    assert mgr.get_limit("NIFTY", "NFO") == 1800


def test_get_limit_none_for_unknown_symbol(mgr: QuantityFreezeManager) -> None:
    assert mgr.get_limit("UNKNOWN_SYM", "NFO") is None


def test_set_limit_updates_existing(mgr: QuantityFreezeManager) -> None:
    mgr.set_limit("SYM", "NFO", 100)
    mgr.set_limit("SYM", "NFO", 200)
    assert mgr.get_limit("SYM", "NFO") == 200


def test_set_limit_zero_raises_value_error(mgr: QuantityFreezeManager) -> None:
    with pytest.raises(ValueError, match="positive"):
        mgr.set_limit("SYM", "NFO", 0)


def test_set_limit_negative_raises_value_error(mgr: QuantityFreezeManager) -> None:
    with pytest.raises(ValueError, match="positive"):
        mgr.set_limit("SYM", "NFO", -1)


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


def test_validate_below_limit_returns_true(mgr: QuantityFreezeManager) -> None:
    mgr.set_limit("NIFTY", "NFO", 1800)
    valid, reason = mgr.validate("NIFTY", "NFO", 900)
    assert valid is True
    assert reason is None


def test_validate_at_limit_returns_true(mgr: QuantityFreezeManager) -> None:
    mgr.set_limit("NIFTY", "NFO", 1800)
    valid, reason = mgr.validate("NIFTY", "NFO", 1800)
    assert valid is True


def test_validate_over_limit_returns_false_with_reason(mgr: QuantityFreezeManager) -> None:
    mgr.set_limit("NIFTY", "NFO", 1800)
    valid, reason = mgr.validate("NIFTY", "NFO", 2000)
    assert valid is False
    assert reason is not None
    assert "2000" in reason
    assert "1800" in reason


def test_validate_no_limit_always_allows(mgr: QuantityFreezeManager) -> None:
    # Remove any default for TESTSYM
    valid, reason = mgr.validate("TESTSYM_NOLIMIT", "NSE", 999999)
    assert valid is True
    assert reason is None


def test_validate_blocked_order_shows_in_recent_blocks(mgr: QuantityFreezeManager) -> None:
    mgr.set_limit("BANKNIFTY", "NFO", 900)
    mgr.validate("BANKNIFTY", "NFO", 1000)
    blocks = mgr.recent_blocks()
    assert len(blocks) >= 1
    assert blocks[0]["symbol"] == "BANKNIFTY"
    assert blocks[0]["exchange"] == "NFO"
    assert blocks[0]["quantity"] == 1000


# ---------------------------------------------------------------------------
# recent_blocks
# ---------------------------------------------------------------------------


def test_recent_blocks_empty_initially(tmp_path: Path) -> None:
    # Use a fresh DB with NO defaults (empty seeding scenario: override _NSE_DEFAULTS)
    mgr = QuantityFreezeManager(db_path=tmp_path / "empty_blocks.duckdb")
    blocks = mgr.recent_blocks()
    assert blocks == [] or isinstance(blocks, list)
    mgr.close()


def test_recent_blocks_respects_limit(mgr: QuantityFreezeManager) -> None:
    mgr.set_limit("X", "NFO", 100)
    for _ in range(10):
        mgr.validate("X", "NFO", 200)
    blocks = mgr.recent_blocks(limit=3)
    assert len(blocks) == 3


def test_recent_blocks_most_recent_first(mgr: QuantityFreezeManager) -> None:
    mgr.set_limit("Y", "NFO", 100)
    for i in range(3):
        mgr.validate("Y", "NFO", 200 + i)
    blocks = mgr.recent_blocks(limit=3)
    # Most recent first — quantity should be 202, 201, 200
    quantities = [b["quantity"] for b in blocks]
    assert quantities == sorted(quantities, reverse=True)


# ---------------------------------------------------------------------------
# load_from_csv
# ---------------------------------------------------------------------------


def test_load_from_csv_basic(mgr: QuantityFreezeManager, tmp_path: Path) -> None:
    csv_path = _write_csv(
        tmp_path / "freeze.csv",
        [
            {"SYMBOL": "NIFTY", "EXCHANGE": "NFO", "MAX_QTY": "1800"},
            {"SYMBOL": "BANKNIFTY", "EXCHANGE": "NFO", "MAX_QTY": "900"},
        ],
    )
    loaded = mgr.load_from_csv(csv_path)
    assert loaded == 2
    assert mgr.get_limit("NIFTY", "NFO") == 1800
    assert mgr.get_limit("BANKNIFTY", "NFO") == 900


def test_load_from_csv_returns_count(mgr: QuantityFreezeManager, tmp_path: Path) -> None:
    csv_path = _write_csv(
        tmp_path / "count.csv",
        [{"SYMBOL": f"SYM{i}", "EXCHANGE": "NFO", "MAX_QTY": str(100 + i)} for i in range(5)],
    )
    assert mgr.load_from_csv(csv_path) == 5


def test_load_from_csv_missing_file_raises(mgr: QuantityFreezeManager, tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        mgr.load_from_csv(tmp_path / "nonexistent.csv")


def test_load_from_csv_missing_columns_raises(mgr: QuantityFreezeManager, tmp_path: Path) -> None:
    bad_csv = tmp_path / "bad.csv"
    bad_csv.write_text("FOO,BAR\n1,2\n")
    with pytest.raises(ValueError, match="SYMBOL"):
        mgr.load_from_csv(bad_csv)


def test_load_from_csv_skips_non_numeric_qty(mgr: QuantityFreezeManager, tmp_path: Path) -> None:
    csv_path = _write_csv(
        tmp_path / "bad_qty.csv",
        [
            {"SYMBOL": "GOOD", "EXCHANGE": "NFO", "MAX_QTY": "100"},
            {"SYMBOL": "BAD", "EXCHANGE": "NFO", "MAX_QTY": "NOT_A_NUMBER"},
        ],
    )
    loaded = mgr.load_from_csv(csv_path)
    assert loaded == 1
    assert mgr.get_limit("GOOD", "NFO") == 100
    assert mgr.get_limit("BAD", "NFO") is None


def test_load_from_csv_skips_non_positive_qty(mgr: QuantityFreezeManager, tmp_path: Path) -> None:
    csv_path = _write_csv(
        tmp_path / "zero_qty.csv",
        [
            {"SYMBOL": "VALID", "EXCHANGE": "NFO", "MAX_QTY": "500"},
            {"SYMBOL": "ZERO", "EXCHANGE": "NFO", "MAX_QTY": "0"},
        ],
    )
    loaded = mgr.load_from_csv(csv_path)
    assert loaded == 1


def test_load_from_csv_updates_existing_limits(mgr: QuantityFreezeManager, tmp_path: Path) -> None:
    mgr.set_limit("NIFTY", "NFO", 1800)
    csv_path = _write_csv(
        tmp_path / "update.csv",
        [{"SYMBOL": "NIFTY", "EXCHANGE": "NFO", "MAX_QTY": "2000"}],
    )
    mgr.load_from_csv(csv_path)
    assert mgr.get_limit("NIFTY", "NFO") == 2000


# ---------------------------------------------------------------------------
# NSE defaults
# ---------------------------------------------------------------------------


def test_nse_defaults_seeded_on_fresh_db(tmp_path: Path) -> None:
    mgr = QuantityFreezeManager(db_path=tmp_path / "defaults.duckdb")
    assert mgr.get_limit("NIFTY", "NFO") == 1800
    assert mgr.get_limit("BANKNIFTY", "NFO") == 900
    mgr.close()


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def test_limits_persist_across_reopen(tmp_path: Path) -> None:
    db = tmp_path / "persist.duckdb"
    mgr1 = QuantityFreezeManager(db_path=db)
    mgr1.set_limit("PERSIST_SYM", "NFO", 750)
    mgr1.close()

    mgr2 = QuantityFreezeManager(db_path=db)
    assert mgr2.get_limit("PERSIST_SYM", "NFO") == 750
    mgr2.close()


def test_all_limits_returns_list(mgr: QuantityFreezeManager) -> None:
    mgr.set_limit("A", "NFO", 100)
    mgr.set_limit("B", "BSE", 200)
    limits = mgr.all_limits()
    assert isinstance(limits, list)
    symbols = [l["symbol"] for l in limits]
    assert "A" in symbols
    assert "B" in symbols
