"""Public data-connector integrity controls; external I/O is always inert."""
from __future__ import annotations

import pytest

from flinttrade_backtest.data_connector import DataConnector, DataResult, DuckDBConnector, YFinanceConnector

pytestmark = pytest.mark.unit


def test_default_empty_local_history_never_falls_back_to_a_remote_provider(monkeypatch):
    calls = []
    monkeypatch.setattr(DuckDBConnector, "load", lambda *args: DataResult(source="duckdb", error="unavailable"))

    def remote(*args):
        calls.append(args)
        return DataResult(bars=[{"close": 100}], source="yfinance")

    monkeypatch.setattr(YFinanceConnector, "load", remote)
    result = DataConnector().load("SAME", "XNAS", "1d")
    assert not result.success
    assert calls == [], "auto must not silently switch market, entitlement or provider"
    assert result.source == "duckdb"
    assert result.error == "unavailable"


def test_reading_missing_local_history_does_not_create_a_replacement_store(tmp_path):
    missing = tmp_path / "lost.duckdb"
    result = DataConnector(str(missing)).load("synthetic", "XNAS", "1d", source="duckdb")
    assert not result.success
    assert not missing.exists(), "read failure must not recreate an empty historical store"


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), True, None])
def test_csv_and_json_cannot_turn_invalid_prices_into_success(bad):
    import json
    from flinttrade_backtest.data_connector import JSONConnector
    row = {"timestamp": "2026-01-01", "open": 100, "high": 102, "low": 99, "close": bad, "volume": 1}
    result = JSONConnector.load_string(json.dumps([row]))
    assert not result.success


def test_fractional_volume_and_unknown_oi_survive_import_without_invented_zero():
    from flinttrade_backtest.data_connector import CSVConnector
    result = CSVConnector.load_string("timestamp,open,high,low,close,volume\n2026-01-01,100,102,99,101,0.5\n")
    assert result.success
    assert result.bars[0]["volume"] == 0.5
    assert result.bars[0]["oi"] is None


def test_unsorted_or_conflicting_import_fails_instead_of_publishing_a_partial_series():
    from flinttrade_backtest.data_connector import CSVConnector
    result = CSVConnector.load_string(
        "timestamp,open,high,low,close,volume\n2026-01-02,100,102,99,101,1\n2026-01-01,100,102,99,101,1\n"
    )
    assert not result.success
