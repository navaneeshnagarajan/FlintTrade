"""Strict SQLite opening never creates or quarantines credential authority."""

import sqlite3
import stat

import pytest

from flinttrade_core.db import open_sqlite
from flinttrade_core.secure_file import HeldOwnerDirectory, harden_directory


def test_strict_missing_and_foreign_files_are_preserved(tmp_path):
    missing = tmp_path / "missing.db"
    with pytest.raises(sqlite3.DatabaseError):
        open_sqlite(missing, strict_existing=True)
    assert not missing.exists()
    foreign = tmp_path / "foreign.db"
    foreign.write_bytes(b"12345678DUCK" + bytes(100))
    before = foreign.read_bytes()
    with pytest.raises(sqlite3.DatabaseError):
        open_sqlite(foreign, strict_existing=True)
    assert foreign.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["foreign.db"]


@pytest.mark.parametrize("value", [":memory:", "file:test?mode=memory", ""])
def test_strict_rejects_non_filesystem_inputs(value):
    with pytest.raises(ValueError):
        open_sqlite(value, strict_existing=True)


def test_strict_escaped_path_and_durability(tmp_path):
    path = tmp_path / "a?#%.db"
    sqlite3.connect(path).close()
    connection = open_sqlite(path, strict_existing=True, durability="full")
    try:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA synchronous").fetchone()[0] == 2
    finally:
        connection.close()


def test_held_directory_exclusively_creates_empty_hardened_member(tmp_path):
    harden_directory(tmp_path)
    with HeldOwnerDirectory(tmp_path) as held:
        assert hasattr(held, "create_empty_hardened_member")
        identity = held.create_empty_hardened_member("vault.db")
        assert identity.st_ino == (tmp_path / "vault.db").stat().st_ino
        assert (tmp_path / "vault.db").read_bytes() == b""
        if __import__("os").name != "nt":
            assert stat.S_IMODE(identity.st_mode) == 0o600
        with pytest.raises(FileExistsError):
            held.create_empty_hardened_member("vault.db")
        with pytest.raises(OSError):
            held.create_empty_hardened_member("../outside")
