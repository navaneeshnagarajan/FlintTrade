"""Tests for packages/data/src/audit_export.py.

Covers: CSV export, PDF export (mocked if reportlab missing),
        summary stats, date range handling, error paths.

Run with:
    python -m pytest packages/data/tests/test_audit_export.py -v --import-mode=importlib
"""

from __future__ import annotations

import csv
from datetime import date, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from packages.data.src.audit_export import AuditExporter, AuditExportError

IST = timezone(timedelta(hours=5, minutes=30))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_event(
    event_type: str = "ORDER_PLACED",
    day: str = "2026-04-15",
    **kwargs,
) -> dict:
    base = {
        "ts": f"{day}T10:00:00+05:30",
        "event_type": event_type,
        "strategy": "TestStrat",
        "symbol": "NIFTY",
        "exchange": "NSE",
        "action": "BUY",
        "quantity": "50",
        "price": "22000",
        "pricetype": "MARKET",
        "product": "MIS",
        "orderid": "ORD001",
    }
    base.update(kwargs)
    return base


def _make_logger(events_by_day: dict[str, list[dict]]) -> MagicMock:
    """Build a mock AuditLogger that returns events keyed by day string."""
    mock = MagicMock()
    mock.read_day.side_effect = lambda day: events_by_day.get(day, [])
    return mock


# ---------------------------------------------------------------------------
# AuditExporter._date_range
# ---------------------------------------------------------------------------


class TestDateRange:
    def test_single_day(self) -> None:
        exporter = AuditExporter(MagicMock())
        result = exporter._date_range(date(2026, 4, 1), date(2026, 4, 1))
        assert result == ["2026-04-01"]

    def test_multi_day_range(self) -> None:
        exporter = AuditExporter(MagicMock())
        result = exporter._date_range(date(2026, 4, 1), date(2026, 4, 3))
        assert result == ["2026-04-01", "2026-04-02", "2026-04-03"]

    def test_from_equals_to(self) -> None:
        exporter = AuditExporter(MagicMock())
        assert len(exporter._date_range(date(2026, 4, 5), date(2026, 4, 5))) == 1


# ---------------------------------------------------------------------------
# AuditExporter.to_csv
# ---------------------------------------------------------------------------


class TestToCSV:
    def test_csv_creates_file(self, tmp_path: Path) -> None:
        logger = _make_logger({"2026-04-15": [_make_event()]})
        exporter = AuditExporter(logger)
        out = tmp_path / "audit.csv"
        count = exporter.to_csv(date(2026, 4, 15), date(2026, 4, 15), out)
        assert out.exists()
        assert count == 1

    def test_csv_returns_row_count(self, tmp_path: Path) -> None:
        events = [_make_event(orderid=f"ORD{i:03d}") for i in range(5)]
        logger = _make_logger({"2026-04-15": events})
        exporter = AuditExporter(logger)
        count = exporter.to_csv(date(2026, 4, 15), date(2026, 4, 15), tmp_path / "a.csv")
        assert count == 5

    def test_csv_header_contains_known_columns(self, tmp_path: Path) -> None:
        logger = _make_logger({"2026-04-15": [_make_event()]})
        exporter = AuditExporter(logger)
        out = tmp_path / "audit.csv"
        exporter.to_csv(date(2026, 4, 15), date(2026, 4, 15), out)
        with open(out, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            assert "ts" in (reader.fieldnames or [])
            assert "event_type" in (reader.fieldnames or [])
            assert "symbol" in (reader.fieldnames or [])

    def test_csv_data_round_trip(self, tmp_path: Path) -> None:
        ev = _make_event(symbol="BANKNIFTY", action="SELL")
        logger = _make_logger({"2026-04-15": [ev]})
        exporter = AuditExporter(logger)
        out = tmp_path / "audit.csv"
        exporter.to_csv(date(2026, 4, 15), date(2026, 4, 15), out)
        with open(out, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 1
        assert rows[0]["symbol"] == "BANKNIFTY"
        assert rows[0]["action"] == "SELL"

    def test_csv_multi_day_aggregates(self, tmp_path: Path) -> None:
        logger = _make_logger(
            {
                "2026-04-01": [_make_event(day="2026-04-01", orderid="O1")],
                "2026-04-02": [_make_event(day="2026-04-02", orderid="O2")],
            }
        )
        exporter = AuditExporter(logger)
        count = exporter.to_csv(date(2026, 4, 1), date(2026, 4, 2), tmp_path / "a.csv")
        assert count == 2

    def test_csv_empty_range_writes_header_only(self, tmp_path: Path) -> None:
        logger = _make_logger({})
        exporter = AuditExporter(logger)
        out = tmp_path / "empty.csv"
        count = exporter.to_csv(date(2026, 4, 1), date(2026, 4, 1), out)
        assert count == 0
        assert out.exists()
        with open(out) as f:
            lines = f.readlines()
        # Should have header only (1 line)
        assert len(lines) == 1

    def test_csv_creates_parent_directories(self, tmp_path: Path) -> None:
        logger = _make_logger({"2026-04-15": [_make_event()]})
        exporter = AuditExporter(logger)
        out = tmp_path / "deep" / "nested" / "audit.csv"
        exporter.to_csv(date(2026, 4, 15), date(2026, 4, 15), out)
        assert out.exists()


# ---------------------------------------------------------------------------
# AuditExporter.to_pdf
# ---------------------------------------------------------------------------


class TestToPDF:
    def test_pdf_raises_export_error_without_reportlab(self, tmp_path: Path) -> None:
        """to_pdf() raises AuditExportError when reportlab is not installed."""
        logger = _make_logger({"2026-04-15": [_make_event()]})
        exporter = AuditExporter(logger)
        out = tmp_path / "audit.pdf"

        with patch.dict("sys.modules", {"reportlab": None, "reportlab.lib": None}):
            import sys

            # Simulate import failure by temporarily removing reportlab.
            saved = {}
            for key in list(sys.modules):
                if key.startswith("reportlab"):
                    saved[key] = sys.modules.pop(key)

            try:
                with pytest.raises(AuditExportError, match="reportlab"):
                    exporter.to_pdf(date(2026, 4, 15), date(2026, 4, 15), out)
            finally:
                sys.modules.update(saved)

    def test_pdf_creates_file_when_reportlab_available(self, tmp_path: Path) -> None:
        """to_pdf() creates a PDF file when reportlab is importable."""
        pytest.importorskip("reportlab", reason="reportlab not installed — skipping PDF test")

        events = [_make_event(orderid=f"ORD{i:03d}") for i in range(3)]
        logger = _make_logger({"2026-04-15": events})
        exporter = AuditExporter(logger)
        out = tmp_path / "audit.pdf"
        count = exporter.to_pdf(date(2026, 4, 15), date(2026, 4, 15), out)
        assert out.exists()
        assert count == 3

    def test_pdf_row_count_matches_events(self, tmp_path: Path) -> None:
        """to_pdf() returns the number of events written."""
        pytest.importorskip("reportlab", reason="reportlab not installed — skipping")

        n = 7
        logger = _make_logger({"2026-04-10": [_make_event() for _ in range(n)]})
        exporter = AuditExporter(logger)
        count = exporter.to_pdf(date(2026, 4, 10), date(2026, 4, 10), tmp_path / "r.pdf")
        assert count == n


# ---------------------------------------------------------------------------
# AuditExporter.summary_stats
# ---------------------------------------------------------------------------


class TestSummaryStats:
    def _exporter(self, events_by_day: dict) -> AuditExporter:
        return AuditExporter(_make_logger(events_by_day))

    def test_total_events_correct(self) -> None:
        exporter = self._exporter(
            {
                "2026-04-01": [_make_event(), _make_event()],
                "2026-04-02": [_make_event()],
            }
        )
        stats = exporter.summary_stats(date(2026, 4, 1), date(2026, 4, 2))
        assert stats["total_events"] == 3

    def test_events_by_type_counts(self) -> None:
        exporter = self._exporter(
            {
                "2026-04-01": [
                    _make_event("ORDER_PLACED"),
                    _make_event("ORDER_PLACED"),
                    _make_event("LOGIN"),
                ],
            }
        )
        stats = exporter.summary_stats(date(2026, 4, 1), date(2026, 4, 1))
        assert stats["events_by_type"]["ORDER_PLACED"] == 2
        assert stats["events_by_type"]["LOGIN"] == 1

    def test_orders_placed_counter(self) -> None:
        events = [_make_event("ORDER_PLACED") for _ in range(4)]
        exporter = self._exporter({"2026-04-01": events})
        stats = exporter.summary_stats(date(2026, 4, 1), date(2026, 4, 1))
        assert stats["orders_placed"] == 4

    def test_orders_rejected_counts_safety_rejections(self) -> None:
        events = [
            {"ts": "2026-04-01T10:00:00", "event_type": "SAFETY_CHECK", "verdict": "REJECT"},
            {"ts": "2026-04-01T10:01:00", "event_type": "SAFETY_CHECK", "verdict": "PASS"},
        ]
        exporter = self._exporter({"2026-04-01": events})
        stats = exporter.summary_stats(date(2026, 4, 1), date(2026, 4, 1))
        assert stats["orders_rejected"] == 1

    def test_safety_triggers_includes_kill_switch(self) -> None:
        events = [
            {"ts": "t", "event_type": "KILL_SWITCH_ACTIVATED", "reason": "mtm_breach"},
            {"ts": "t", "event_type": "SAFETY_CHECK", "verdict": "REJECT"},
        ]
        exporter = self._exporter({"2026-04-01": events})
        stats = exporter.summary_stats(date(2026, 4, 1), date(2026, 4, 1))
        assert stats["safety_triggers"] == 2

    def test_empty_range_returns_zeros(self) -> None:
        exporter = self._exporter({})
        stats = exporter.summary_stats(date(2026, 4, 1), date(2026, 4, 1))
        assert stats["total_events"] == 0
        assert stats["orders_placed"] == 0
        assert stats["orders_rejected"] == 0
        assert stats["safety_triggers"] == 0
        assert stats["events_by_type"] == {}
