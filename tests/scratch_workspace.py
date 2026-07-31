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

Two properties keep the sweep from eating a workspace that is still in use:

* :func:`acquire_workspace` mints **one** workspace per process. Every conftest
  that isolates ``FLINTTRADE_WORKSPACE_DIR`` calls it, so the last one imported
  no longer decides which of three freshly minted directories the process ends
  up pointing at.
* :func:`register` takes an OS-level exclusive lock on the workspace and holds
  it for the process lifetime, and :func:`sweep_stale` refuses any candidate
  whose lock is still held. Liveness is therefore an operating-system fact
  rather than an inference from a timestamp, so no clock skew, no long-running
  session and no caller can talk the sweep into removing a live sibling's
  workspace.
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
it. The next run collects it instead, and waiting six hours means a workspace
left by a run that predates :data:`_LOCK_NAME` is very unlikely still to be in
use.

This is a grace period, not the safety property. It used to be treated as the
safety property - "six hours is longer than any suite invocation, so a
concurrently running sibling can never be swept out from under itself" - and
that reasoning does not survive anything that distorts the comparison. The
liveness claim is what actually protects a live sibling.
"""

_SWEEP_LIMIT = 200
"""Cap on directories swept per run, so session finish never stalls."""

_LOCK_NAME = ".flinttrade-pytest-scratch.lock"
"""Liveness claim: an exclusive OS lock held for the owning process's lifetime.

:data:`_STALE_AGE_SECONDS` alone was never a safe liveness test. It infers "no
one is using this" from a timestamp, and an inference can be wrong - a clock
that skews, a suite that outruns the window, or a caller that supplies its own
reference time. When it was wrong the sweep did not merely leave rubbish behind:
it recursively removed a *live* sibling xdist worker's workspace, taking that
worker's ``master_password`` with it and failing every subsequent test there
with a misleading "master password required but no TTY available".

A held lock is not an inference. The operating system releases it when the
owning process exits, however it exits, so a workspace is sweepable exactly
when nobody is left to care.
"""

_registered: list[Path] = []
_deferred: list[Path] = []
_claims: dict[Path, int] = {}
_atexit_armed = False


def _open_lock_fd(path: Path) -> int | None:
    """Open (creating if needed) a workspace's lock file.

    Args:
        path: The lock file itself.

    Returns:
        A read/write descriptor, or ``None`` if it could not be opened.
    """
    try:
        return os.open(str(path), os.O_RDWR | os.O_CREAT, 0o600)
    except OSError:
        return None


def _try_lock(fd: int) -> bool:
    """Take the exclusive lock without blocking.

    Args:
        fd: A descriptor on the lock file.

    Returns:
        ``True`` if the lock was taken, ``False`` if another process holds it.
    """
    try:
        if os.name == "nt":
            import msvcrt  # noqa: PLC0415

            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl  # noqa: PLC0415

            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _unlock(fd: int) -> None:
    """Drop the exclusive lock, tolerating any failure.

    Args:
        fd: A descriptor that currently holds the lock.
    """
    try:
        if os.name == "nt":
            import msvcrt  # noqa: PLC0415

            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl  # noqa: PLC0415

            fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        pass


def _claim(path: Path) -> bool:
    """Announce that this process is using *path*, for as long as it lives.

    Args:
        path: The scratch workspace root.

    Returns:
        ``True`` once this process holds the workspace's lock.
    """
    if path in _claims:
        return True
    fd = _open_lock_fd(path / _LOCK_NAME)
    if fd is None:
        return False
    if _try_lock(fd):
        _claims[path] = fd
        return True
    os.close(fd)
    return False


def _unclaim(path: Path) -> None:
    """Drop this process's claim so the workspace can be removed.

    Windows will not unlink a file another handle holds open, so the claim has
    to go before the tree can.

    Args:
        path: The scratch workspace root.
    """
    fd = _claims.pop(path, None)
    if fd is None:
        return
    _unlock(fd)
    try:
        os.close(fd)
    except OSError:
        pass


def _owner_is_live(candidate: Path) -> bool:
    """Whether some process is still using *candidate*.

    Args:
        candidate: A marked scratch workspace found in the temp directory.

    Returns:
        ``True`` while any process holds the workspace's lock. A workspace left
        by a run that predates the lock has no lock file and is not live.
    """
    if candidate in _claims:
        return True
    lock_path = candidate / _LOCK_NAME
    try:
        if not lock_path.is_file():
            return False
    except OSError:
        return True
    fd = _open_lock_fd(lock_path)
    if fd is None:
        # Windows refuses the open while the owner holds the handle.
        return True
    try:
        if _try_lock(fd):
            _unlock(fd)
            return False
        return True
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


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

    Also takes the liveness claim, so a concurrently sweeping process - another
    xdist worker, a second checkout, another agent's run - can see that this
    directory is in use rather than having to guess from its age.

    Args:
        path: The directory that was just created for this run.

    Returns:
        The same path, as a :class:`~pathlib.Path`, so call sites can wrap the
        ``mkdtemp`` result inline.
    """
    resolved = Path(path)
    # Claim BEFORE marking, and mark only if the claim held. The marker is what
    # makes a directory sweepable; a marked-but-unclaimed workspace looks dead to
    # every other process the moment it passes the age threshold, which is the
    # exact deletion this module exists to prevent. If the lock cannot be taken
    # the directory simply stays unmarked: no later run will collect it, so it
    # leaks into the temp directory instead of being deleted while in use.
    # Leaking a scratch directory is recoverable; wiping a live one is not.
    if _claim(resolved):
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
    _unclaim(path)
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


def sweep_stale() -> list[Path]:
    """Collect marked workspaces that an earlier run could not remove itself.

    A workspace whose test built the Flask app keeps store handles open until the
    process exits, which is later than any finaliser can run, so it survives its
    own session. The next run picks it up here.

    The glob is over the whole shared temp directory, so most candidates belong
    to *other* processes and a mistake here is cross-process data loss. Three
    conditions must therefore all hold before a candidate is removed: it carries
    this suite's marker, nothing holds its liveness claim, and its marker is
    older than :data:`_STALE_AGE_SECONDS`.

    The claim is the load-bearing one. Age is a courtesy check for workspaces
    left by runs that predate the claim, and it takes no caller-supplied
    reference time: the previous signature accepted ``now``, and a test that
    passed a future timestamp to age its own decoy aged every live sibling
    worker's workspace with it and had them recursively removed mid-run.

    Returns:
        The workspaces that were successfully removed.
    """
    reference = time.time()
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
        if _owner_is_live(candidate):
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


# ---------------------------------------------------------------------------
# Workspace acquisition
# ---------------------------------------------------------------------------

_MIGRATED_SCRATCH_DBS = ("activity.db", "security.db", "emergency_intents.sqlite")
"""Scratch stores that must not carry state between independent pytest runs.

``activity``/``security`` changed engine DuckDB->SQLite and a reused workspace
may still hold a file ``open_sqlite`` cannot read. The emergency journal
intentionally survives production restarts, but a prior simulated kill episode
must not poison a later test process.
"""

_acquired: Path | None = None


def clean_legacy_scratch_dbs(base: Path | str) -> None:
    """Remove scratch stores that must not survive into this run.

    Args:
        base: The workspace directory to clean.
    """
    root = Path(base)
    for name in _MIGRATED_SCRATCH_DBS:
        for path in (root / name, root / f"{name}-wal", root / f"{name}-shm"):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass  # locked by a concurrent worker - that worker owns cleanup


def acquire_workspace() -> Path:
    """Return the one scratch workspace this pytest process uses.

    Three conftests isolate ``FLINTTRADE_WORKSPACE_DIR``: the repo-root one and
    one each under ``packages/core/core/tests`` and ``packages/core/data/tests``
    (the package ones exist because a per-package run resolves rootdir to that
    package and never loads the root conftest). Each used to mint and seed its
    own ``mkdtemp``, so a full-suite worker created three workspaces, whichever
    conftest was imported last won the env var, and the other two were abandoned
    still-registered. Memoising here makes the second and third callers adopt
    the first's directory, which is the only one any test ever sees.

    Isolation is unchanged: the memo is per process, so each xdist worker still
    gets its own directory and DuckDB/SQLite exclusive locks cannot collide. It
    is still ``mkdtemp`` rather than a deterministic per-worker path - a stable
    directory is reused by every later invocation, and stores encrypted under a
    previous run's master password then fail to decrypt with ``InvalidTag``.

    Returns:
        The workspace directory, which is also now
        ``os.environ["FLINTTRADE_WORKSPACE_DIR"]``.
    """
    global _acquired

    if _acquired is not None:
        return _acquired

    # Under xdist each worker MUST get its own directory even though the
    # controller already exported FLINTTRADE_WORKSPACE_DIR and workers inherit
    # it - otherwise every worker shares one directory and they collide on the
    # SandboxEngine / traffic / error stores. PYTEST_XDIST_WORKER is set per
    # worker (gw0, gw1, ...) and absent in the controller and in serial runs, so
    # an operator-supplied value is still honoured there.
    worker = os.environ.get("PYTEST_XDIST_WORKER")
    supplied = os.environ.get("FLINTTRADE_WORKSPACE_DIR")
    if supplied and not worker:
        base = Path(supplied)
        ours = False
    else:
        base = register(tempfile.mkdtemp(prefix=f"flinttrade-pytest-{worker or 'main'}-"))
        ours = True

    base.mkdir(parents=True, exist_ok=True)
    os.environ["FLINTTRADE_WORKSPACE_DIR"] = str(base)
    # The operator's machine-local .env may pin DUCKDB_PATH at one real, shared
    # DuckDB file (a single-writer engine). Full-app constructions on several
    # xdist workers then contend on that file - the losers boot with
    # TRADE_STORAGE=None and store-wiring tests flake. Pin the variable to a
    # per-worker scratch file FIRST: load_dotenv() never overrides an existing
    # env var, so the .env value cannot leak into any package's test run.
    os.environ["DUCKDB_PATH"] = str(base / "data" / "flint.duckdb")
    clean_legacy_scratch_dbs(base)
    # Master password no longer auto-generates (locked decision #13: getpass or
    # fd only), so app-building tests need a file or they block on a TTY prompt.
    # A directory the operator supplied is theirs: seed it only when it holds no
    # secret at all, never over the top of a real one.
    if ours or not (base / "master_password").exists():
        seed_master_password(base)

    _acquired = base
    return base
