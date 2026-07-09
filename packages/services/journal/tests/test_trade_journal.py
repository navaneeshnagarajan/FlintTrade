"""Tests for trade_journal — JournalEntry, TradeJournal, JournalStats.

All tests use an in-memory SQLite journal via TradeJournal(":memory:") so no
filesystem state is created or left behind.

Run with::

    python -m pytest packages/core/data/tests/test_trade_journal.py -v --import-mode=importlib
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

IST = timezone(timedelta(hours=5, minutes=30))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_journal():
    """Return a ``(None, TradeJournal)`` pair backed by an in-memory SQLite DB.

    The first element is unused (kept so existing ``_, journal = ...`` unpacking
    stays valid); the journal owns its own ``:memory:`` connection.
    """
    from flinttrade_journal.trade_journal import TradeJournal

    journal = TradeJournal(":memory:")
    journal.initialise()
    return None, journal


def _entry(**kwargs):
    """Return a minimal valid JournalEntry with optional overrides."""
    from flinttrade_journal.trade_journal import JournalEntry

    defaults = {
        "symbol": "NIFTY26APR24500CE",
        "exchange": "NFO",
        "side": "BUY",
        "quantity": 50,
        "entry_price": 120.0,
    }
    defaults.update(kwargs)
    return JournalEntry(**defaults)


# ---------------------------------------------------------------------------
# JournalEntry model tests
# ---------------------------------------------------------------------------


class TestJournalEntry:
    """Unit tests for JournalEntry pydantic model."""

    def test_minimal_fields(self):
        """Minimal required fields are accepted."""
        entry = _entry()
        assert entry.symbol == "NIFTY26APR24500CE"
        assert entry.side == "BUY"
        assert entry.pnl is None  # no exit price

    def test_side_normalised_to_uppercase(self):
        """Side field is normalised to uppercase."""
        entry = _entry(side="buy")
        assert entry.side == "BUY"
        entry2 = _entry(side="SELL")
        assert entry2.side == "SELL"

    def test_invalid_side_raises(self):
        """Invalid side value raises ValidationError."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="BUY.*SELL"):
            _entry(side="SHORT")

    def test_pnl_auto_computed_buy(self):
        """P&L is auto-computed for BUY entry when exit_price provided."""
        entry = _entry(entry_price=100.0, exit_price=120.0, quantity=50)
        assert entry.pnl == pytest.approx(1000.0)
        assert entry.pnl_pct == pytest.approx(20.0)

    def test_pnl_auto_computed_sell(self):
        """P&L is auto-computed for SELL (short) entry."""
        entry = _entry(side="SELL", entry_price=100.0, exit_price=80.0, quantity=50)
        assert entry.pnl == pytest.approx(1000.0)

    def test_pnl_negative_on_loss(self):
        """Negative P&L for a losing trade."""
        entry = _entry(entry_price=100.0, exit_price=90.0, quantity=50)
        assert entry.pnl == pytest.approx(-500.0)

    def test_explicit_pnl_not_overwritten(self):
        """Explicitly provided pnl is NOT recomputed."""
        entry = _entry(entry_price=100.0, exit_price=120.0, quantity=50, pnl=999.0)
        assert entry.pnl == pytest.approx(999.0)

    def test_quality_validation_bounds(self):
        """Setup and execution quality must be 1–5."""
        from pydantic import ValidationError

        entry = _entry(setup_quality=5, execution_quality=1)
        assert entry.setup_quality == 5

        with pytest.raises(ValidationError):
            _entry(setup_quality=0)

        with pytest.raises(ValidationError):
            _entry(execution_quality=6)

    def test_id_auto_generated(self):
        """UUID is auto-generated if not provided."""
        e1 = _entry()
        e2 = _entry()
        assert e1.id != e2.id
        assert len(e1.id) == 36  # standard UUID4 length

    def test_tags_default_empty_list(self):
        """Tags default to an empty list."""
        entry = _entry()
        assert entry.tags == []

    def test_timestamps_default_to_now(self):
        """created_at and updated_at are set to approximately now."""
        before = datetime.now(IST)
        entry = _entry()
        after = datetime.now(IST)
        # Allow 1-second tolerance
        assert before <= entry.created_at <= after + timedelta(seconds=1)


# ---------------------------------------------------------------------------
# TradeJournal CRUD tests
# ---------------------------------------------------------------------------


class TestTradeJournalCRUD:
    """Integration tests for CRUD operations on TradeJournal."""

    def test_add_and_get_entry(self):
        """add_entry round-trips correctly through DuckDB."""
        _, journal = _make_journal()
        entry = _entry(tags=["options", "nifty"], notes="Test note")
        eid = journal.add_entry(entry)
        assert eid == entry.id

        fetched = journal.get_entry(eid)
        assert fetched is not None
        assert fetched.symbol == "NIFTY26APR24500CE"
        assert fetched.notes == "Test note"
        assert set(fetched.tags) == {"options", "nifty"}

    def test_get_entry_nonexistent_returns_none(self):
        """get_entry returns None for unknown ID."""
        _, journal = _make_journal()
        assert journal.get_entry("does-not-exist") is None

    def test_delete_entry(self):
        """delete_entry removes the row and returns True."""
        _, journal = _make_journal()
        eid = journal.add_entry(_entry())
        assert journal.delete_entry(eid) is True
        assert journal.get_entry(eid) is None

    def test_delete_nonexistent_returns_false(self):
        """delete_entry returns False for a missing entry."""
        _, journal = _make_journal()
        assert journal.delete_entry("phantom-id") is False

    def test_update_entry_notes(self):
        """update_entry modifies only the specified fields."""
        _, journal = _make_journal()
        eid = journal.add_entry(_entry(notes="Original"))
        updated = journal.update_entry(eid, {"notes": "Revised"})
        assert updated is not None
        assert updated.notes == "Revised"
        # Unchanged fields preserved
        assert updated.symbol == "NIFTY26APR24500CE"

    def test_update_entry_recomputes_pnl_when_exit_price_set(self):
        """Updating exit_price triggers P&L recomputation."""
        _, journal = _make_journal()
        eid = journal.add_entry(_entry(entry_price=100.0, quantity=50))
        updated = journal.update_entry(eid, {"exit_price": 130.0})
        assert updated is not None
        assert updated.pnl == pytest.approx(1500.0)

    def test_update_nonexistent_entry_returns_none(self):
        """update_entry returns None for a missing entry."""
        _, journal = _make_journal()
        assert journal.update_entry("ghost", {"notes": "x"}) is None

    def test_list_all_entries(self):
        """list_entries returns all persisted entries when no filters given."""
        _, journal = _make_journal()
        for i in range(5):
            journal.add_entry(_entry(symbol=f"SYM{i}"))
        entries = journal.list_entries()
        assert len(entries) >= 5

    def test_list_filter_by_symbol(self):
        """list_entries filters by exact symbol match."""
        _, journal = _make_journal()
        journal.add_entry(_entry(symbol="RELIANCE"))
        journal.add_entry(_entry(symbol="INFY"))
        journal.add_entry(_entry(symbol="RELIANCE"))

        from flinttrade_journal.trade_journal import JournalFilters

        result = journal.list_entries(JournalFilters(symbol="RELIANCE"))
        assert len(result) == 2
        assert all(e.symbol == "RELIANCE" for e in result)

    def test_list_filter_by_strategy(self):
        """list_entries filters by exact strategy match."""
        _, journal = _make_journal()
        journal.add_entry(_entry(strategy="Straddle"))
        journal.add_entry(_entry(strategy="Iron Condor"))
        journal.add_entry(_entry(strategy="Straddle"))

        from flinttrade_journal.trade_journal import JournalFilters

        result = journal.list_entries(JournalFilters(strategy="Straddle"))
        assert len(result) == 2

    def test_list_filter_by_tags(self):
        """list_entries filters entries that contain all requested tags."""
        _, journal = _make_journal()
        journal.add_entry(_entry(tags=["options", "nifty"]))
        journal.add_entry(_entry(tags=["options"]))
        journal.add_entry(_entry(tags=["equity", "nifty"]))

        from flinttrade_journal.trade_journal import JournalFilters

        # Both tags required
        result = journal.list_entries(JournalFilters(tags=["options", "nifty"]))
        assert len(result) == 1

    def test_list_filter_by_side(self):
        """list_entries filters by trade side."""
        _, journal = _make_journal()
        journal.add_entry(_entry(side="BUY"))
        journal.add_entry(_entry(side="SELL"))
        journal.add_entry(_entry(side="BUY"))

        from flinttrade_journal.trade_journal import JournalFilters

        result = journal.list_entries(JournalFilters(side="BUY"))
        assert len(result) == 2

    def test_list_pagination(self):
        """list_entries respects limit and offset."""
        _, journal = _make_journal()
        for _ in range(10):
            journal.add_entry(_entry())

        from flinttrade_journal.trade_journal import JournalFilters

        page1 = journal.list_entries(JournalFilters(limit=3, offset=0))
        page2 = journal.list_entries(JournalFilters(limit=3, offset=3))
        assert len(page1) == 3
        assert len(page2) == 3
        ids_p1 = {e.id for e in page1}
        ids_p2 = {e.id for e in page2}
        assert ids_p1.isdisjoint(ids_p2), "Pages must not overlap"


# ---------------------------------------------------------------------------
# JournalStats tests
# ---------------------------------------------------------------------------


class TestJournalStats:
    """Tests for get_stats() aggregations."""

    def _journal_with_entries(self):
        _, journal = _make_journal()
        # 3 winning trades
        for _ in range(3):
            journal.add_entry(
                _entry(entry_price=100.0, exit_price=120.0, quantity=10, strategy="A")
            )
        # 2 losing trades
        for _ in range(2):
            journal.add_entry(
                _entry(entry_price=100.0, exit_price=90.0, quantity=10, strategy="B")
            )
        # 1 open trade (no exit_price)
        journal.add_entry(_entry(entry_price=100.0, strategy="A"))
        return journal

    def test_closed_count(self):
        """Closed entries count excludes open trades."""
        journal = self._journal_with_entries()
        stats = journal.get_stats()
        assert stats.closed_entries == 5

    def test_win_and_loss_counts(self):
        """Win/loss counts match expected values."""
        journal = self._journal_with_entries()
        stats = journal.get_stats()
        assert stats.win_count == 3
        assert stats.loss_count == 2

    def test_win_rate(self):
        """Win rate is 60% for 3/5 winning trades."""
        journal = self._journal_with_entries()
        stats = journal.get_stats()
        assert stats.win_rate == pytest.approx(60.0)

    def test_total_pnl(self):
        """Total P&L = 3*200 - 2*100 = 400."""
        journal = self._journal_with_entries()
        stats = journal.get_stats()
        assert stats.total_pnl == pytest.approx(400.0)

    def test_by_strategy(self):
        """by_strategy groups P&L correctly."""
        journal = self._journal_with_entries()
        stats = journal.get_stats()
        assert "A" in stats.by_strategy
        assert "B" in stats.by_strategy
        assert stats.by_strategy["A"] == pytest.approx(600.0)  # 3 * 200
        assert stats.by_strategy["B"] == pytest.approx(-200.0)  # 2 * -100

    def test_best_worst_trade(self):
        """best_trade_pnl and worst_trade_pnl are set correctly."""
        journal = self._journal_with_entries()
        stats = journal.get_stats()
        assert stats.best_trade_pnl == pytest.approx(200.0)
        assert stats.worst_trade_pnl == pytest.approx(-100.0)

    def test_avg_quality_scores(self):
        """Average quality scores are None when no scores set."""
        journal = self._journal_with_entries()
        stats = journal.get_stats()
        assert stats.avg_setup_quality is None
        assert stats.avg_execution_quality is None

    def test_avg_quality_scores_computed(self):
        """Average quality scores are computed when entries have scores."""
        _, journal = _make_journal()
        journal.add_entry(_entry(setup_quality=4, execution_quality=3))
        journal.add_entry(_entry(setup_quality=2, execution_quality=5))
        stats = journal.get_stats()
        assert stats.avg_setup_quality == pytest.approx(3.0)
        assert stats.avg_execution_quality == pytest.approx(4.0)

    def test_empty_journal_returns_zero_stats(self):
        """get_stats on an empty journal returns all-zero values."""
        _, journal = _make_journal()
        stats = journal.get_stats()
        assert stats.total_entries == 0
        assert stats.win_rate == 0.0
        assert stats.total_pnl == 0.0


# ---------------------------------------------------------------------------
# Export / Import tests
# ---------------------------------------------------------------------------


class TestExportImport:
    """Tests for CSV export and tradebook import."""

    def test_export_csv_headers(self):
        """CSV export includes the expected header row."""
        _, journal = _make_journal()
        journal.add_entry(_entry())
        csv_str = journal.export_csv()
        lines = csv_str.strip().splitlines()
        assert len(lines) >= 2
        header = lines[0]
        assert "symbol" in header
        assert "pnl" in header
        assert "entry_price" in header

    def test_export_csv_data_row(self):
        """CSV export data row contains the correct symbol."""
        _, journal = _make_journal()
        journal.add_entry(_entry(symbol="BANKNIFTY"))
        csv_str = journal.export_csv()
        assert "BANKNIFTY" in csv_str

    def test_export_empty_journal_has_only_header(self):
        """Exporting an empty journal returns just the header row."""
        _, journal = _make_journal()
        csv_str = journal.export_csv()
        lines = [line for line in csv_str.strip().splitlines() if line]
        assert len(lines) == 1  # header only

    def test_import_from_tradebook_creates_entries(self):
        """import_from_tradebook creates JournalEntry for each valid trade."""
        _, journal = _make_journal()
        trades = [
            {
                "symbol": "NIFTY",
                "exchange": "NSE",
                "action": "BUY",
                "quantity": "100",
                "price": "22000.0",
                "orderid": "ORD001",
                "timestamp": "2026-04-07T10:30:00",
            },
            {
                "symbol": "RELIANCE",
                "exchange": "NSE",
                "action": "SELL",
                "quantity": "10",
                "price": "2800.0",
                "orderid": "ORD002",
            },
        ]
        created = journal.import_from_tradebook(trades)
        assert len(created) == 2
        entries = journal.list_entries()
        symbols = {e.symbol for e in entries}
        assert "NIFTY" in symbols
        assert "RELIANCE" in symbols

    def test_import_adds_imported_tag(self):
        """Imported entries carry the 'imported' tag."""
        _, journal = _make_journal()
        trades = [
            {
                "symbol": "INFY",
                "exchange": "NSE",
                "action": "BUY",
                "quantity": "5",
                "price": "1500.0",
            }
        ]
        created = journal.import_from_tradebook(trades)
        entry = journal.get_entry(created[0])
        assert "imported" in entry.tags

    def test_import_skips_invalid_rows(self):
        """Rows with missing symbol or zero quantity are skipped."""
        _, journal = _make_journal()
        bad_trades = [
            {"symbol": "", "exchange": "NSE", "action": "BUY", "quantity": "10", "price": "100.0"},
            {"symbol": "XYZ", "exchange": "NSE", "action": "BUY", "quantity": "0", "price": "100.0"},
        ]
        created = journal.import_from_tradebook(bad_trades)
        assert len(created) == 0

    def test_import_skips_duplicates(self):
        """Duplicate tradebook rows on the same day are not re-imported."""
        _, journal = _make_journal()
        trade = {
            "symbol": "HDFC",
            "exchange": "NSE",
            "action": "BUY",
            "quantity": "20",
            "price": "1600.0",
            "timestamp": "2026-04-07T11:00:00",
        }
        first = journal.import_from_tradebook([trade])
        second = journal.import_from_tradebook([trade])
        assert len(first) == 1
        assert len(second) == 0  # duplicate skipped


# ---------------------------------------------------------------------------
# Full-text search (FTS5) + lifecycle
# ---------------------------------------------------------------------------


class TestJournalSearch:
    """The SQLite journal exposes an FTS5 search over symbol/notes/tags/strategy."""

    def _seed(self, journal):
        journal.add_entry(_entry(
            symbol="BANKNIFTY", strategy="momentum", tags=["breakout", "trending"],
            notes="Clean breakout above resistance on strong volume.",
        ))
        journal.add_entry(_entry(
            symbol="RELIANCE", strategy="meanreversion", tags=["reversal"],
            notes="Faded the gap-up open near VWAP.",
        ))

    def test_search_matches_notes(self):
        _, journal = _make_journal()
        self._seed(journal)
        hits = journal.search("breakout")
        assert len(hits) == 1
        assert hits[0].symbol == "BANKNIFTY"

    def test_search_matches_symbol_and_strategy_and_tags(self):
        _, journal = _make_journal()
        self._seed(journal)
        assert len(journal.search("RELIANCE")) == 1
        assert len(journal.search("momentum")) == 1
        assert len(journal.search("reversal")) == 1

    def test_search_blank_query_returns_empty(self):
        _, journal = _make_journal()
        self._seed(journal)
        assert journal.search("") == []
        assert journal.search("   ") == []

    def test_search_malformed_query_does_not_raise(self):
        _, journal = _make_journal()
        self._seed(journal)
        # Unbalanced quote / stray operator would be an FTS syntax error; the
        # method must degrade to a quoted-phrase search or empty list, never 500.
        assert isinstance(journal.search('"unterminated'), list)
        assert isinstance(journal.search("AND OR"), list)

    def test_search_reflects_update_and_delete(self):
        _, journal = _make_journal()
        eid = journal.add_entry(_entry(symbol="TCS", notes="initial thesis alpha"))
        assert len(journal.search("alpha")) == 1
        journal.update_entry(eid, {"notes": "revised thesis omega"})
        assert len(journal.search("alpha")) == 0  # FTS re-synced on update
        assert len(journal.search("omega")) == 1
        journal.delete_entry(eid)
        assert len(journal.search("omega")) == 0  # FTS row removed on delete

    def test_context_manager_closes(self):
        from flinttrade_journal.trade_journal import TradeJournal
        with TradeJournal(":memory:") as journal:
            journal.initialise()
            journal.add_entry(_entry(symbol="INFY"))
            assert len(journal.list_entries()) == 1


# ---------------------------------------------------------------------------
# Regression guards for the G31 adversarial-verify findings
# ---------------------------------------------------------------------------


class TestJournalVerifyRegressions:
    """Guards for the four defects found by the G31 adversarial verify."""

    def test_side_only_update_recomputes_pnl(self):
        # A BUY→SELL correction on a closed trade must flip the P&L sign, not
        # keep the old profit (the recompute guard once omitted `side`).
        _, journal = _make_journal()
        eid = journal.add_entry(_entry(side="BUY", entry_price=100.0, exit_price=120.0, quantity=50))
        assert journal.get_entry(eid).pnl == pytest.approx(1000.0)
        updated = journal.update_entry(eid, {"side": "SELL"})
        assert updated is not None
        assert updated.pnl == pytest.approx(-1000.0)

    def test_date_filter_includes_entries_without_entry_time(self):
        # Widget-created entries have no entry_time; a date-range filter must
        # fall back to created_at, not silently drop every such entry.
        from flinttrade_journal.trade_journal import JournalFilters

        _, journal = _make_journal()
        journal.add_entry(_entry(symbol="NOTIME"))  # entry_time defaults to None-in-DB
        today = datetime.now(IST).date().isoformat()
        got = journal.list_entries(JournalFilters(start_date=today, end_date=today))
        assert any(e.symbol == "NOTIME" for e in got)

    def test_date_filter_uses_local_ist_date_not_utc(self):
        # An entry at 02:00 IST must match its own IST date, not shift a day
        # earlier via SQLite date()'s UTC conversion.
        from flinttrade_journal.trade_journal import JournalFilters

        _, journal = _make_journal()
        journal.add_entry(_entry(symbol="EARLY", entry_time=datetime(2026, 4, 7, 2, 0, tzinfo=IST)))
        got = journal.list_entries(JournalFilters(start_date="2026-04-07", end_date="2026-04-07"))
        assert any(e.symbol == "EARLY" for e in got)

    def test_import_skips_malformed_rows_without_raising(self):
        # Untrusted import input: non-dict rows, a null side, and a non-numeric
        # quantity must be skipped, never raise (a webhook could post anything).
        _, journal = _make_journal()
        created = journal.import_from_tradebook([
            123, None, "x",
            {"symbol": "A", "action": None, "quantity": 1, "price": 1.0},
            {"symbol": "B", "quantity": "abc", "price": 1.0},
            {"symbol": "C", "exchange": "NSE", "action": "BUY", "quantity": 5, "price": 100.0},
        ])
        # A (null side → default BUY) and C import; the three non-dicts and B skip.
        assert len(created) == 2

    def test_concurrent_access_is_thread_safe(self):
        # The journal is one shared connection across Flask threads; without the
        # instance lock, concurrent ops corrupt statement state (SQLITE_MISUSE,
        # garbage reads). This reproduces the load and asserts zero failures.
        import threading

        _, journal = _make_journal()
        errors: list[str] = []

        def worker(n: int) -> None:
            try:
                for i in range(10):
                    eid = journal.add_entry(_entry(symbol=f"T{n}", quantity=n + 1, notes=f"{n}-{i}"))
                    journal.get_entry(eid)
                    journal.list_entries()
                    journal.search("T")
                    journal.get_stats()
                    journal.update_entry(eid, {"notes": f"u{n}-{i}"})
            except Exception as exc:  # noqa: BLE001 — capture any thread failure
                errors.append(f"{type(exc).__name__}: {exc}")

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(12)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []
