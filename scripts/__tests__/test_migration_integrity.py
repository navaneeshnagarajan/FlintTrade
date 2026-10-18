"""Public migration CLIs on disposable, fully synthetic databases only."""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import duckdb
import pytest

from flinttrade_journal.trade_journal import TradeJournal

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]
JOURNAL = ROOT / "scripts/migrate-journal-duckdb-to-sqlite.py"
AUTH = ROOT / "scripts/migrate-auth-state-duckdb-to-sqlite.py"


def cli(script: Path, workspace: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTEST_XDIST_")}
    return subprocess.run(
        [sys.executable, str(script), "--workspace", str(workspace), *args],
        env=env, capture_output=True, text=True, timeout=45, check=False,
    )


def journal_source(workspace: Path, *, invalid: bool = False) -> Path:
    workspace.mkdir(parents=True, exist_ok=True)
    source = workspace / "journal.db"
    db = duckdb.connect(str(source), config={"threads": 1})
    try:
        db.execute("""CREATE TABLE journal_entries (
            id VARCHAR PRIMARY KEY, symbol VARCHAR, exchange VARCHAR, side VARCHAR,
            quantity DOUBLE, entry_price DOUBLE, exit_price DOUBLE,
            entry_time TIMESTAMP, exit_time TIMESTAMP, strategy VARCHAR, tags VARCHAR,
            notes VARCHAR, screenshot_path VARCHAR, emotion_before VARCHAR, emotion_after VARCHAR,
            setup_quality INTEGER, execution_quality INTEGER, pnl DOUBLE, pnl_pct DOUBLE,
            risk_reward_ratio DOUBLE, created_at TIMESTAMP, updated_at TIMESTAMP)""")
        for i in range(2):
            db.execute(
                "INSERT INTO journal_entries VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [f"entry-{i}", f"SYNTHETIC{i}", "NSE", "BUY", 1.5 if invalid and i else 3,
                 12.5, None, "2025-01-02 09:15:00.123456", None, None,
                 json.dumps(["breakout", "注釈"]) if i == 0 else None,
                 "synthetic migration note", None, None, None, None, None, None, None, None,
                 "2025-01-02 09:15:00.123456", "2025-01-02 09:15:00.654321"],
            )
    finally:
        db.close()
    return source


def test_journal_failed_copy_never_publishes_partial_destination(tmp_path: Path) -> None:
    source = journal_source(tmp_path, invalid=True)
    original = source.read_bytes()
    result = cli(JOURNAL, tmp_path)
    assert result.returncode != 0
    assert source.read_bytes() == original
    assert not (tmp_path / "journal.sqlite").exists()
    retry = cli(JOURNAL, tmp_path)
    assert retry.returncode != 0
    assert source.read_bytes() == original
    assert not (tmp_path / "journal.sqlite").exists()


def test_journal_preserves_nulls_and_reopens_with_current_reader(tmp_path: Path) -> None:
    source = journal_source(tmp_path)
    original = source.read_bytes()
    result = cli(JOURNAL, tmp_path)
    assert result.returncode == 0, "journal CLI did not complete"
    target = tmp_path / "journal.sqlite"
    with TradeJournal(target) as reader:
        assert {row.id for row in reader.list_entries()} == {"entry-0", "entry-1"}
        assert reader.get_entry("entry-0").entry_time.microsecond == 123456
        assert {row.id for row in reader.search("breakout")} == {"entry-0"}
    with sqlite3.connect(target) as db:
        assert db.execute("SELECT tags, pnl, pnl_pct FROM journal_entries WHERE id='entry-1'").fetchone() == (
            None, None, None,
        )
    archives = list((tmp_path / "archive/migrations").rglob("journal.db"))
    assert len(archives) == 1
    assert archives[0].read_bytes() == original
    assert not source.exists()
    retry = cli(JOURNAL, tmp_path)
    assert retry.returncode == 0


def fault_cli(script: Path, workspace: Path, fault: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts/__tests__/migration_fault_driver.py"), fault, str(script), str(workspace)],
        capture_output=True, text=True, timeout=45, check=False,
    )


@pytest.mark.parametrize("fault", ["copy", "write", "validation", "fsync_stage", "rename_receipt", "publish_before"])
def test_journal_prepublication_failure_retains_source_and_retry(fault: str, tmp_path: Path) -> None:
    source = journal_source(tmp_path)
    original = source.read_bytes()
    result = fault_cli(JOURNAL, tmp_path, fault)
    assert result.returncode == 2
    assert source.read_bytes() == original
    assert not (tmp_path / "journal.sqlite").exists()
    assert cli(JOURNAL, tmp_path).returncode == 0
    with TradeJournal(tmp_path / "journal.sqlite") as reader:
        assert len(reader.list_entries()) == 2


@pytest.mark.parametrize("fault", ["publish_after", "archive_before", "archive_after", "unlink_source", "fsync_unlink"])
def test_journal_published_archive_pending_is_resumable(fault: str, tmp_path: Path) -> None:
    source = journal_source(tmp_path)
    original = source.read_bytes()
    result = fault_cli(JOURNAL, tmp_path, fault)
    assert result.returncode == 3
    assert "published/archive-pending" in result.stdout
    if source.exists():
        assert source.read_bytes() == original
    else:
        assert any(p.read_bytes() == original for p in (tmp_path / "archive/migrations").rglob("journal.db"))
    target = tmp_path / "journal.sqlite"
    with TradeJournal(target) as reader:
        assert {row.id for row in reader.list_entries()} == {"entry-0", "entry-1"}
    assert cli(JOURNAL, tmp_path).returncode == 0
    assert cli(JOURNAL, tmp_path).returncode == 0
    assert not source.exists()
    archives = list((tmp_path / "archive/migrations").rglob("journal.db"))
    assert len(archives) == 1
    assert archives[0].read_bytes() == original


@pytest.mark.parametrize("lost", ["target", "receipt", "both"])
def test_completed_migration_lost_state_never_recreates_empty_db(lost: str, tmp_path: Path) -> None:
    journal_source(tmp_path)
    assert cli(JOURNAL, tmp_path).returncode == 0
    target = tmp_path / "journal.sqlite"
    if lost in {"target", "both"}:
        target.unlink()
    if lost in {"receipt", "both"}:
        (tmp_path / ".journal.sqlite.migration.json").unlink()
    before = target.read_bytes() if target.exists() else None
    assert cli(JOURNAL, tmp_path).returncode != 0
    assert (target.read_bytes() if target.exists() else None) == before


@pytest.mark.parametrize("pending", [False, True])
def test_divergent_destination_is_never_overwritten(pending: bool, tmp_path: Path) -> None:
    source = journal_source(tmp_path)
    original = source.read_bytes()
    target = tmp_path / "journal.sqlite"
    if pending:
        assert fault_cli(JOURNAL, tmp_path, "archive_before").returncode == 3
    else:
        with TradeJournal(target) as reader:
            reader.initialise()
    with sqlite3.connect(target) as db:
        db.execute("CREATE TABLE new_current_data (value TEXT)")
        db.execute("INSERT INTO new_current_data VALUES ('retained')")
    before = target.read_bytes()
    assert cli(JOURNAL, tmp_path).returncode != 0
    assert target.read_bytes() == before
    assert source.read_bytes() == original


@pytest.mark.parametrize("invalid", ["missing_table", "extra_table", "extra_column", "null_id", "null_created",
                                    "fraction_quality", "invalid_time", "submicrosecond_time", "corrupt_source", "wal", "bad_receipt"])
def test_invalid_journal_source_fails_closed_without_disclosure(invalid: str, tmp_path: Path) -> None:
    source = journal_source(tmp_path)
    if invalid == "corrupt_source":
        source.write_bytes(b"not a database")
    elif invalid == "wal":
        source.with_suffix(".db.wal").write_bytes(b"unreconciled")
    elif invalid == "bad_receipt":
        (tmp_path / ".journal.sqlite.migration.json").write_text("{")
    else:
        with duckdb.connect(str(source), config={"threads": 1}) as db:
            if invalid == "missing_table":
                db.execute("DROP TABLE journal_entries")
            elif invalid == "extra_table":
                db.execute("CREATE TABLE retained_unknown (value VARCHAR)")
            elif invalid == "extra_column":
                db.execute("ALTER TABLE journal_entries ADD COLUMN retained_unknown VARCHAR")
            elif invalid == "null_id":
                db.execute("CREATE TABLE replacement AS SELECT * FROM journal_entries")
                db.execute("DROP TABLE journal_entries")
                db.execute("ALTER TABLE replacement RENAME TO journal_entries")
                db.execute("UPDATE journal_entries SET id=NULL")
            elif invalid == "null_created":
                db.execute("UPDATE journal_entries SET created_at=NULL")
            elif invalid in {"invalid_time", "submicrosecond_time"}:
                db.execute("ALTER TABLE journal_entries ALTER COLUMN entry_time TYPE VARCHAR")
                value = "unparseable" if invalid == "invalid_time" else "2025-01-02T09:15:00.123456789"
                db.execute("UPDATE journal_entries SET entry_time=?", [value])
            elif invalid == "fraction_quality":
                db.execute("ALTER TABLE journal_entries ALTER COLUMN setup_quality TYPE DOUBLE")
                db.execute("UPDATE journal_entries SET setup_quality=2.5")
    original = source.read_bytes()
    result = cli(JOURNAL, tmp_path)
    assert result.returncode == 2
    assert source.read_bytes() == original
    assert not (tmp_path / "journal.sqlite").exists()
    assert "synthetic migration note" not in result.stdout + result.stderr
    assert "Traceback" not in result.stdout + result.stderr


def test_real_backend_writer_excludes_migration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from flinttrade_core.backend_instance import acquire_backend_instance_lease

    source = journal_source(tmp_path)
    original = source.read_bytes()
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    lease = acquire_backend_instance_lease()
    try:
        assert cli(JOURNAL, tmp_path).returncode == 2
        assert source.read_bytes() == original
        assert not (tmp_path / "journal.sqlite").exists()
    finally:
        lease.release()
    assert cli(JOURNAL, tmp_path).returncode == 0


def test_migration_excludes_real_backend_through_publication_and_archive(tmp_path: Path) -> None:
    journal_source(tmp_path)
    result = fault_cli(JOURNAL, tmp_path, "assert_lease")
    assert result.returncode == 0
    assert result.stdout.count("REAL_BACKEND_EXCLUDED") == 2


def test_journal_keeps_stored_null_pnl_instead_of_recomputing(tmp_path: Path) -> None:
    source = journal_source(tmp_path)
    with duckdb.connect(str(source), config={"threads": 1}) as db:
        db.execute("UPDATE journal_entries SET exit_price=14.5 WHERE id='entry-0'")
    assert cli(JOURNAL, tmp_path).returncode == 0
    with sqlite3.connect(tmp_path / "journal.sqlite") as db:
        assert db.execute("SELECT pnl,pnl_pct FROM journal_entries WHERE id='entry-0'").fetchone() == (None, None)
    # The reader's normal computed presentation remains available; migration
    # must not silently overwrite the underlying historical NULLs with it.
    with TradeJournal(tmp_path / "journal.sqlite") as reader:
        assert reader.get_entry("entry-0").pnl == 6.0


def test_optional_journal_notes_and_screenshot_bytes_remain_readable(tmp_path: Path) -> None:
    import base64
    import hashlib

    source = journal_source(tmp_path)
    blob = b"synthetic-image-payload"
    screenshots = tmp_path / "journal_screenshots"
    screenshots.mkdir()
    image = screenshots / "screenshot-1.png"
    image.write_bytes(blob)
    with duckdb.connect(str(source), config={"threads": 1}) as db:
        db.execute("CREATE TABLE daily_notes (date VARCHAR,content VARCHAR,updated_at VARCHAR)")
        db.execute("INSERT INTO daily_notes VALUES ('2025-01-02','note with unicode 注釈','2025-01-02T09:15:00.123456')")
        db.execute("CREATE TABLE journal_screenshots (id VARCHAR,trade_key VARCHAR,content_sha256 VARCHAR,"
                   "content_type VARCHAR,size INTEGER,created_at VARCHAR)")
        db.execute("INSERT INTO journal_screenshots VALUES (?,?,?,?,?,?)", [
            "screenshot-1", "entry-0", hashlib.sha256(blob).hexdigest(), "image/png", len(blob),
            "2025-01-02T09:15:00.123456",
        ])
    assert cli(JOURNAL, tmp_path).returncode == 0
    with TradeJournal(tmp_path / "journal.sqlite") as reader:
        assert reader.get_daily_note("2025-01-02")["content"] == "note with unicode 注釈"
        screenshot = reader.get_screenshot("screenshot-1")
        assert base64.b64decode(screenshot["data_url"].split(",")[1]) == blob
    assert image.read_bytes() == blob


def test_publication_collision_is_refused_not_claimed_as_our_pending_archive(tmp_path: Path) -> None:
    source = journal_source(tmp_path)
    original = source.read_bytes()
    result = fault_cli(JOURNAL, tmp_path, "publication_collision")
    assert result.returncode == 2
    assert "published/archive-pending" not in result.stdout
    assert source.read_bytes() == original
    target = tmp_path / "journal.sqlite"
    assert target.read_bytes() == b"unrelated concurrent destination"
    assert cli(JOURNAL, tmp_path).returncode == 2
    assert target.read_bytes() == b"unrelated concurrent destination"


def test_archive_collision_is_not_overwritten_on_resume(tmp_path: Path) -> None:
    source = journal_source(tmp_path)
    original = source.read_bytes()
    assert fault_cli(JOURNAL, tmp_path, "archive_before").returncode == 3
    state = json.loads((tmp_path / ".journal.sqlite.migration.json").read_text())
    archive = tmp_path / "archive/migrations" / state["id"] / "journal.db"
    archive.write_bytes(b"unrelated retained archive")
    assert cli(JOURNAL, tmp_path).returncode == 3
    assert archive.read_bytes() == b"unrelated retained archive"
    assert source.read_bytes() == original


def test_cleanup_failure_does_not_record_complete(tmp_path: Path) -> None:
    journal_source(tmp_path)
    result = fault_cli(JOURNAL, tmp_path, "cleanup_snapshot")
    assert result.returncode == 3
    receipt = json.loads((tmp_path / ".journal.sqlite.migration.json").read_text())
    assert receipt["phase"] != "complete"
    assert cli(JOURNAL, tmp_path).returncode == 0
    assert json.loads((tmp_path / ".journal.sqlite.migration.json").read_text())["phase"] == "complete"


def test_foreign_duckdb_writer_refuses_before_snapshot_publication(tmp_path: Path) -> None:
    source = journal_source(tmp_path)
    original = source.read_bytes()
    writer = duckdb.connect(str(source), config={"threads": 1})
    try:
        result = cli(JOURNAL, tmp_path)
        assert result.returncode == 2
        assert source.read_bytes() == original
        assert not (tmp_path / "journal.sqlite").exists()
    finally:
        writer.close()
    assert cli(JOURNAL, tmp_path).returncode == 0
