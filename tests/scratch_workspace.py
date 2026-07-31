"""Release the throw-away workspace directories the pytest suite creates.

Every conftest that isolates ``FLINTTRADE_WORKSPACE_DIR`` does so with
``tempfile.mkdtemp(prefix="flinttrade-pytest-…")``, and nothing ever removed the
result. Worse, the suite hardens that workspace with an owner-only *protected*
DACL on Windows (``flinttrade_core.secure_file.harden_directory``), which clears
the inheritance flag on the directory and every descendant it hardens. Nothing
unwound that either, so each invocation left another tree in the system temp
directory that ordinary recursive-delete tools stumble over and that needs
``takeown``/``icacls`` to clear by hand.

Registering each directory as it is created and releasing the registered set
from ``pytest_sessionfinish`` makes a run clean up after itself. Only
directories this process created are ever touched: an operator-supplied
``FLINTTRADE_WORKSPACE_DIR`` is never registered, and release refuses any path
that is not a ``flinttrade-pytest-`` directory inside the temp directory.

Every step is best-effort. A cleanup failure must never fail an otherwise green
run, so all errors are swallowed and a directory that will not go away is simply
left behind.
"""

from __future__ import annotations

import atexit
import gc
import os
import shutil
import stat
import subprocess
import tempfile
import time
from pathlib import Path

_SCRATCH_PREFIX = "flinttrade-pytest-"
_ICACLS_TIMEOUT_SECONDS = 120.0
_REMOVE_ATTEMPTS = 4
_REMOVE_BACKOFF_SECONDS = 0.2

_MARKER_NAME = ".flinttrade-pytest-scratch"
"""Marker proving a directory was created by this finaliser-aware suite.

The sweep only ever considers directories carrying this file. Directories left by
runs from before the finaliser existed have no marker and are never touched, so
adopting the finaliser cannot mass-delete an operator's accumulated temp trees -
those stay for the operator to clear (or not) as they see fit.
"""

_STALE_AGE_SECONDS = 6 * 60 * 60
"""How old a marked workspace must be before another run may sweep it.

An app-building test holds DuckDB/SQLite handles on its workspace for the whole
process lifetime - later than ``atexit``, so no in-process finaliser can unlink
it. The next run collects it instead. Six hours is far longer than any suite
invocation, so a concurrently running sibling process (xdist workers, a second
checkout, another agent's run) can never be swept out from under itself.
"""

_SWEEP_LIMIT = 200
"""Cap on directories swept per run, so session finish never stalls."""

_registered: list[Path] = []
_deferred: list[Path] = []
_atexit_armed = False


def _mark(path: Path) -> None:
    """(Re-)stamp the marker that makes a workspace sweepable by a later run.

    Re-stamping matters after a failed removal: ``shutil.rmtree`` deletes what it
    can before it fails, so the marker is usually one of the first casualties and
    the surviving tree would otherwise look like an unmarked pre-finaliser one.

    Args:
        path: The scratch workspace root.
    """
    try:
        if path.is_dir():
            (path / _MARKER_NAME).touch()
    except OSError:
        pass


def register(path: Path | str) -> Path:
    """Record a scratch workspace for release at the end of the session.

    Args:
        path: The directory that was just created for this run.

    Returns:
        The same path, as a :class:`~pathlib.Path`, so call sites can wrap the
        ``mkdtemp`` result inline.
    """
    resolved = Path(path)
    _mark(resolved)
    _registered.append(resolved)
    return resolved


def _is_releasable(path: Path) -> bool:
    """Whether *path* is one of this suite's own scratch workspaces.

    Args:
        path: A candidate directory.

    Returns:
        ``True`` when the path is a ``flinttrade-pytest-`` directory directly
        inside the system temp directory.
    """
    if not path.name.startswith(_SCRATCH_PREFIX):
        return False
    try:
        temp_root = Path(tempfile.gettempdir()).resolve()
        return path.resolve().parent == temp_root
    except OSError:
        return False


def unwind_protected_dacls(path: Path) -> None:
    """Restore inherited permissions across a hardened scratch tree.

    On Windows ``icacls /reset`` replaces each object's access-control list with
    the one it inherits from its parent, which is exactly the state that existed
    before ``harden_directory`` set the protected flag. On POSIX the hardening is
    a ``0700`` chmod, which already permits the owner to remove the tree, so
    there is nothing to unwind.

    Args:
        path: The root of the tree to unwind.
    """
    if os.name != "nt":
        return
    icacls = shutil.which("icacls")
    if icacls is None:
        return
    try:
        subprocess.run(
            [icacls, str(path), "/reset", "/T", "/C", "/Q"],
            capture_output=True,
            check=False,
            timeout=_ICACLS_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return


def _clear_read_only(_function, path, _excinfo) -> None:  # type: ignore[no-untyped-def]
    """Drop a read-only bit that blocked a removal, then retry once."""
    try:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        if os.path.isdir(path):
            os.rmdir(path)
        else:
            os.unlink(path)
    except OSError:
        pass


def _try_remove(path: Path) -> bool:
    """Attempt the removal a few times, dropping stale handles between tries.

    An app-building test leaves DuckDB/SQLite handles open on the workspace, and
    Windows refuses to unlink an open file. A ``gc.collect()`` between attempts
    closes the ones that are merely unreferenced, which is most of them.

    Args:
        path: The tree to remove.

    Returns:
        ``True`` once the tree is gone.
    """
    for attempt in range(_REMOVE_ATTEMPTS):
        try:
            shutil.rmtree(path, onexc=_clear_read_only)
        except OSError:
            pass
        if not path.exists():
            return True
        gc.collect()
        time.sleep(_REMOVE_BACKOFF_SECONDS * (attempt + 1))
    return not path.exists()


def _release_deferred() -> None:
    """Retry the workspaces that were still held open at session finish."""
    while _deferred:
        path = _deferred.pop()
        if _is_releasable(path) and path.exists() and not _try_remove(path):
            _mark(path)


def release(path: Path) -> None:
    """Unwind and remove one scratch workspace, tolerating any failure.

    A workspace that will not go away yet - an app-building test's store handles
    are typically still open at ``pytest_sessionfinish`` - is deferred to an
    ``atexit`` retry, which runs late enough for the interpreter to have dropped
    them.

    Args:
        path: The scratch workspace to release.
    """
    global _atexit_armed

    if not _is_releasable(path):
        return
    if not path.exists():
        return
    unwind_protected_dacls(path)
    if _try_remove(path):
        return
    _mark(path)
    _deferred.append(path)
    if not _atexit_armed:
        atexit.register(_release_deferred)
        _atexit_armed = True


def release_all() -> None:
    """Release every scratch workspace registered by this process."""
    while _registered:
        release(_registered.pop())


def sweep_stale(*, now: float | None = None) -> list[Path]:
    """Collect marked workspaces that an earlier run could not remove itself.

    A workspace whose test built the Flask app keeps store handles open until the
    process exits, which is later than any finaliser can run, so it survives its
    own session. The next run picks it up here. Only directories carrying this
    suite's marker and older than :data:`_STALE_AGE_SECONDS` are considered.

    Args:
        now: Reference timestamp, for tests. Defaults to the current time.

    Returns:
        The workspaces that were successfully removed.
    """
    reference = time.time() if now is None else now
    try:
        candidates = sorted(Path(tempfile.gettempdir()).glob(f"{_SCRATCH_PREFIX}*"))
    except OSError:
        return []
    swept: list[Path] = []
    for candidate in candidates:
        if len(swept) >= _SWEEP_LIMIT:
            break
        marker = candidate / _MARKER_NAME
        try:
            if not candidate.is_dir() or not marker.is_file():
                continue
            if reference - marker.stat().st_mtime < _STALE_AGE_SECONDS:
                continue
        except OSError:
            continue
        if not _is_releasable(candidate):
            continue
        unwind_protected_dacls(candidate)
        if _try_remove(candidate):
            swept.append(candidate)
    return swept


# ---------------------------------------------------------------------------
# Master-password seeding
#
# Not cleanup, so the best-effort rule above does NOT apply here: a seeding
# failure must be loud. This lives beside register() because all three
# conftests that isolate a workspace already load this module, and because
# keeping three copies of it is what broke CI. The copy in
# packages/core/data/tests wrote the secret with a plain Path.write_text, which
# on POSIX leaves mode 0644 while the backend reads through
# read_hardened_owner_owned_text and rejects anything broader than owner-only.
# Every test in that worker which built a full app then failed with "master
# password required but no TTY available", naming a workspace that did have the
# file. Windows has no POSIX mode bits, so it never reproduced there.
# ---------------------------------------------------------------------------

#: The value every seeded workspace's ``master_password`` file carries.
TEST_MASTER_PASSWORD = "pytest-master-password"


def seed_master_password(base: Path | str) -> None:
    """Seed *base*'s master password, and prove the backend will accept it.

    Existence is not the property that matters - the file must also be hardened
    to owner-only, or the reader rejects it exactly as it rejects a missing one.
    So this reseeds an unreadable file rather than only an absent one, and
    writes through ``write_secret_text`` rather than a plain write.

    Args:
        base: The workspace directory to seed.

    Raises:
        RuntimeError: If the secret cannot be written, or cannot be read back
            by the same reader the backend uses.
    """
    from flinttrade_core.secure_file import read_hardened_owner_owned_text, write_secret_text

    pw_file = Path(base) / "master_password"

    def _usable() -> bool:
        try:
            return read_hardened_owner_owned_text(pw_file) == TEST_MASTER_PASSWORD
        except (OSError, ValueError, UnicodeDecodeError):
            return False

    if _usable():
        return

    try:
        pw_file.unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise RuntimeError(f"could not replace the unusable test master password at {pw_file}: {exc}") from exc

    try:
        write_secret_text(pw_file, TEST_MASTER_PASSWORD)
    except OSError as exc:
        raise RuntimeError(f"could not seed the test master password at {pw_file}: {exc}") from exc

    if not _usable():
        raise RuntimeError(
            f"seeded the test master password at {pw_file}, but the backend's own reader rejects it. "
            "Every test that builds a full app in this worker would fail with a misleading "
            "'master password required' error."
        )
