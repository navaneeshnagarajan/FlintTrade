"""Auth-only fault boundaries, always through the public CLI __main__."""
from __future__ import annotations

import runpy
import sys
from pathlib import Path

from flinttrade_core import legacy_sqlite_migration as migration

fault, script, workspace, *arguments = sys.argv[1:]


def fail() -> None:
    raise OSError("synthetic auth migration fault")


if fault == "missing_age":
    sys.modules["pyrage"] = None
elif fault in {"archive_encrypt", "archive_decrypt"}:
    from pyrage import passphrase

    def crypto_failure(*args, **kwargs):
        fail()

    if fault == "archive_encrypt":
        passphrase.encrypt = crypto_failure
    else:
        passphrase.decrypt = crypto_failure
elif fault == "fsync_archive":
    real_sync = migration.fsync_file

    def sync(path):
        if Path(path).name.endswith(".age"):
            fail()
        return real_sync(path)

    migration.fsync_file = sync
elif fault == "archive_temp_cleanup":
    real_unlink = Path.unlink

    def unlink(path, *args, **kwargs):
        if path.name.endswith(".age.tmp"):
            fail()
        return real_unlink(path, *args, **kwargs)

    Path.unlink = unlink
else:
    # Reuse the real generic syscall boundaries, not a substitute migration.
    sys.argv = [str(Path(__file__).with_name("migration_fault_driver.py")), fault, script, workspace, *arguments]
    runpy.run_path(sys.argv[0], run_name="__main__")
    raise AssertionError("public CLI returned without exiting")

sys.argv = [script, "--workspace", workspace, *arguments]
runpy.run_path(script, run_name="__main__")
