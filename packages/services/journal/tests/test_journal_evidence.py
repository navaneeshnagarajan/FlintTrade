"""Evidence tests: the trade journal records trades and computes realised P&L."""

from __future__ import annotations

import pytest

from flinttrade_data.storage import StorageManager
from flinttrade_journal.trade_journal import JournalEntry, TradeJournal

pytestmark = pytest.mark.unit


@pytest.fixture
def journal():
    storage = StorageManager(":memory:")
    storage.initialise()
    j = TradeJournal(storage)
    j.initialise()  # create the journal_entries table
    yield j
    storage.close()


def test_records_a_trade_and_computes_realised_pnl(journal):
    entry = JournalEntry(
        symbol="RELIANCE", exchange="NSE", side="BUY",
        quantity=10, entry_price=2900.0, exit_price=2950.0,
    )
    # (2950 - 2900) * 10 = 500 realised P&L (auto-computed for a closed BUY).
    assert entry.pnl == pytest.approx(500.0)

    entry_id = journal.add_entry(entry)
    assert entry_id

    fetched = journal.get_entry(entry_id)
    assert fetched is not None
    assert fetched.symbol == "RELIANCE"
    assert fetched.pnl == pytest.approx(500.0)


def test_lists_recorded_entries(journal):
    journal.add_entry(JournalEntry(symbol="TCS", exchange="NSE", side="BUY", quantity=5, entry_price=3700.0))
    journal.add_entry(JournalEntry(symbol="INFY", exchange="NSE", side="SELL", quantity=8, entry_price=1500.0))
    entries = journal.list_entries()
    symbols = {e.symbol for e in entries}
    assert {"TCS", "INFY"} <= symbols
