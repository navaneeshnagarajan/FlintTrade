"""Fail-closed custody for model authority using the existing secure file owners."""
from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from .db import open_sqlite
from .owner_file_lock import OwnerSafeFileLock
from .secure_file import HeldOwnerDirectory, harden_directory, validate_owner_owned_regular_file


class ModelEvidenceDatabase:
    """Create once; refuse lost/replaced authority, markers, schema or symlinks.

    A pre-custody database needs explicit migration, never automatic recreation.
    SQLite and directory handles are scoped to each transaction; no close leak.
    """

    def __init__(self, path: Path, schema: str) -> None:
        self.path = Path(path).absolute()
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        harden_directory(self.path.parent)
        self.marker = self.path.name + ".authority.json"
        self.lock = OwnerSafeFileLock(str(self.path) + ".lock", timeout=10)
        self.pid = os.getpid()
        with self.lock, HeldOwnerDirectory(self.path.parent) as directory:
            exists, marked = directory.exists(self.path.name), directory.exists(self.marker)
            if exists != marked:
                raise ValueError("Model authority incomplete; explicit recovery required")
            if not exists:
                directory.create_empty_hardened_member(self.path.name)
                identity = str(uuid4())
                db = open_sqlite(self.path, durability="full", strict_existing=True)
                try:
                    db.executescript(schema + "; CREATE TABLE model_authority(id TEXT PRIMARY KEY); " )
                    db.execute("INSERT INTO model_authority VALUES (?)", (identity,))
                    tables = self._schema(db)
                finally:
                    db.close()
                directory.write_text(self.marker, json.dumps({"id": identity, "schema": tables}, sort_keys=True))
            self.anchor = directory.read_text(self.marker)
            self.inode = validate_owner_owned_regular_file(self.path, require_hardened=True).st_ino
            self.directory_identity = (self.path.parent.stat().st_dev, self.path.parent.stat().st_ino)
        with self.transaction():
            pass

    @staticmethod
    def _schema(db: sqlite3.Connection) -> list[str]:
        return [row[0] for row in db.execute("SELECT sql FROM sqlite_master WHERE name NOT GLOB 'sqlite_*' ORDER BY name")]

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.lock, HeldOwnerDirectory(self.path.parent) as directory:
            parent = directory.revalidate()
            info = validate_owner_owned_regular_file(self.path, require_hardened=True)
            if (self.pid != os.getpid() or info.st_ino != self.inode
                    or (parent.st_dev, parent.st_ino) != self.directory_identity
                    or directory.read_text(self.marker) != self.anchor):
                raise ValueError("Model authority replaced or inherited")
            for suffix in ("-wal", "-shm", "-journal"):
                if directory.exists(self.path.name + suffix):
                    validate_owner_owned_regular_file(Path(str(self.path) + suffix), require_hardened=True)
            db = open_sqlite(self.path, durability="full", strict_existing=True)
            try:
                db.execute("BEGIN IMMEDIATE")
                marker = json.loads(self.anchor)
                if (self._schema(db) != marker["schema"]
                        or db.execute("SELECT id FROM model_authority").fetchall() != [(marker["id"],)]):
                    raise ValueError("Model authority/schema lost")
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise
            finally:
                db.close()
