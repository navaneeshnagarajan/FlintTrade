"""Fault injection around real storage/syscalls; always dispatch the real CLI."""
from __future__ import annotations

import os
import runpy
import sqlite3
import sys
from pathlib import Path

from flinttrade_core import legacy_sqlite_migration as migration

fault, script, workspace, *arguments = sys.argv[1:]
workspace_path = Path(workspace)
source_name = "journal.db" if "journal" in Path(script).name else "auth_state.duckdb"
destination_name = "journal.sqlite" if source_name == "journal.db" else "auth_state.sqlite"


def fail() -> None:
    raise OSError("synthetic injected I/O failure")


if fault == "copy":
    real_copy = migration.shutil.copyfile

    def bad_copy(source, target, **kwargs):
        result = real_copy(source, target, **kwargs)
        with Path(target).open("ab") as stream:
            stream.write(b"injected corruption")
        return result

    migration.shutil.copyfile = bad_copy
elif fault == "write":
    real_connect = sqlite3.connect

    class FailingConnection(sqlite3.Connection):
        def executemany(self, statement, parameters):
            values = list(parameters)
            if "INSERT INTO journal_entries" in statement or "INSERT INTO revoked_jtis" in statement:
                super().executemany(statement, values[:1])
                fail()
            return super().executemany(statement, values)

    def connect(*args, **kwargs):
        kwargs["factory"] = FailingConnection
        return real_connect(*args, **kwargs)

    sqlite3.connect = connect
elif fault == "validation":
    real_digest = migration.database_digest

    def digest(path):
        if Path(path).name == "target.sqlite":
            fail()
        return real_digest(path)

    migration.database_digest = digest
elif fault == "fsync_stage":
    real_sync = migration.fsync_file

    def sync(path):
        if Path(path).name == "target.sqlite":
            fail()
        return real_sync(path)

    migration.fsync_file = sync
elif fault == "rename_receipt":
    real_replace = os.replace
    calls = 0

    def replace(source, target, **kwargs):
        global calls
        if str(target).endswith(".migration.json"):
            calls += 1
            if calls == 2:
                fail()
        return real_replace(source, target, **kwargs)

    os.replace = replace
elif fault == "publication_collision":
    real_publish = migration.publish_noreplace

    def publish(source, target):
        if Path(target).name == destination_name:
            Path(target).write_bytes(b"unrelated concurrent destination")
        real_publish(source, target)

    migration.publish_noreplace = publish
elif fault in {"publish_before", "publish_after", "archive_before", "archive_after"}:
    real_publish = migration.publish_noreplace

    def publish(source, target):
        match = (Path(target).name == destination_name if fault.startswith("publish")
                 else Path(target).name.startswith(source_name))
        if match and fault.endswith("before"):
            fail()
        real_publish(source, target)
        if match:
            fail()

    migration.publish_noreplace = publish
elif fault in {"unlink_source", "cleanup_snapshot"}:
    real_unlink = Path.unlink

    def unlink(path, *args, **kwargs):
        if ((fault == "unlink_source" and path == workspace_path / source_name)
                or (fault == "cleanup_snapshot" and path.name == "source.duckdb"
                    and not (workspace_path / source_name).exists())):
            fail()
        return real_unlink(path, *args, **kwargs)

    Path.unlink = unlink
elif fault == "fsync_unlink":
    real_directory_sync = migration.fsync_directory

    def directory_sync(path):
        if Path(path) == workspace_path and not (workspace_path / source_name).exists():
            fail()
        return real_directory_sync(path)

    migration.fsync_directory = directory_sync
elif fault == "assert_lease":
    from flinttrade_core.backend_instance import BackendInstanceAlreadyRunning, acquire_backend_instance_lease

    real_publish = migration.publish_noreplace
    os.environ["FLINTTRADE_WORKSPACE_DIR"] = workspace

    def publish(source, target):
        try:
            lease = acquire_backend_instance_lease()
        except BackendInstanceAlreadyRunning:
            print("REAL_BACKEND_EXCLUDED", flush=True)
        else:
            lease.release()
            raise AssertionError("backend entered migration maintenance")
        real_publish(source, target)

    migration.publish_noreplace = publish
else:
    raise AssertionError("unknown fault")

sys.argv = [script, "--workspace", workspace, *arguments]
runpy.run_path(script, run_name="__main__")
