"""Owner-validated cross-process locks that retain one persistent inode."""

from __future__ import annotations

import errno
import os
import pathlib
import stat
import time
from typing import Any, Protocol, cast

from filelock import AcquireReturnProxy, UnixFileLock, WindowsFileLock

if os.name != "nt":
    import fcntl

_OPEN_DENIAL_RETRY_SECONDS = 2.0
"""How long a Windows open denial is treated as contention before it turns fatal.

Windows reports a *transient* sharing violation - a foreign handle opened
without ``FILE_SHARE_WRITE``, or a delete still pending - through the very same
``EACCES`` that a *permanent* ACL denial uses, and ``os.open`` discards the
``NTSTATUS`` that would tell them apart. Treating every denial as fatal turned a
momentary foreign handle on the lock file into an immediate hard failure, which
is what made first-run provisioning fail and then succeed on the next attempt.

Retrying briefly recovers the transient case. Re-raising once the budget is
spent keeps a genuine denial fast and fatal, rather than stalling for the
caller's whole (possibly 30 s) acquisition timeout.
"""


class UnsafeFileLockPathError(RuntimeError):
    """A lock path does not identify one owner-owned regular file."""


def _is_reparse_point(path_stat: os.stat_result) -> bool:
    reparse_mask = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(reparse_mask and getattr(path_stat, "st_file_attributes", 0) & reparse_mask)


def _same_file_identity(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _assert_safe_windows_lock_stat(
    path_stat: os.stat_result,
    *,
    expected: os.stat_result | None = None,
) -> None:
    if (
        not stat.S_ISREG(path_stat.st_mode)
        or stat.S_ISLNK(path_stat.st_mode)
        or _is_reparse_point(path_stat)
        or path_stat.st_nlink != 1
        or (expected is not None and not _same_file_identity(path_stat, expected))
    ):
        raise UnsafeFileLockPathError("owner-validated lock path is unsafe")


class _WindowsDescriptorSecurity(Protocol):
    def prepare(self, descriptor: int) -> int: ...

    def assert_current_user_owns(
        self,
        descriptor: int,
        path_stat: os.stat_result,
    ) -> None: ...

    def harden(self, descriptor: int) -> None: ...

    def verify_exact_dacl(self, descriptor: int) -> tuple[bool, str]: ...


class _SecureFileWindowsDescriptorSecurity:
    """Late-bound adapter that keeps secure-file and lock imports acyclic."""

    @staticmethod
    def prepare(descriptor: int) -> int:
        from . import secure_file

        return secure_file._reopen_windows_descriptor_for_security(
            descriptor,
            allow_delete_sharing=False,
            write_dacl=True,
        )

    @staticmethod
    def assert_current_user_owns(
        descriptor: int,
        path_stat: os.stat_result,
    ) -> None:
        from . import secure_file

        secure_file._assert_current_user_owns(descriptor, path_stat)

    @staticmethod
    def harden(descriptor: int) -> None:
        from . import secure_file

        secure_file._install_exact_windows_descriptor_dacl(descriptor)

    @staticmethod
    def verify_exact_dacl(descriptor: int) -> tuple[bool, str]:
        from . import secure_file

        return secure_file._verify_exact_windows_descriptor_dacl(descriptor)


def _windows_descriptor_security() -> _WindowsDescriptorSecurity:
    return _SecureFileWindowsDescriptorSecurity()


def _validate_windows_lock_descriptor(
    descriptor: int,
    descriptor_stat: os.stat_result,
    security: _WindowsDescriptorSecurity,
) -> None:
    _assert_safe_windows_lock_stat(descriptor_stat)
    try:
        security.assert_current_user_owns(descriptor, descriptor_stat)
        hardened, _reason = security.verify_exact_dacl(descriptor)
    except Exception as exc:
        raise UnsafeFileLockPathError("owner-validated lock path is unsafe") from exc
    if not hardened:
        raise UnsafeFileLockPathError("owner-validated lock path is unsafe")


class _WindowsOwnerSafeFileLock(WindowsFileLock):
    """Windows byte-range lock with descriptor-bound ownership and ACL proof."""

    def acquire(self, *args: Any, **kwargs: Any) -> AcquireReturnProxy:
        """Acquire the lock, giving this attempt its own open-denial budget.

        The budget spans one acquisition's poll loop, not the lock object's
        lifetime. These locks are long-lived and reused - ``AuditLogger`` builds
        its chain lock once and enters it on every append - so a deadline left
        behind by an earlier acquisition would already be in the past, and the
        next brief sharing violation would be judged fatal on sight instead of
        being retried. Only an intervening successful open cleared it otherwise,
        which is precisely the case that never happens when the denial persists.

        Args:
            *args: Forwarded unchanged to :meth:`filelock.BaseFileLock.acquire`.
            **kwargs: Forwarded unchanged to the same method.

        Returns:
            The base class's proxy, which releases the lock when its context exits.
        """
        self._open_denial_deadline = None
        return super().acquire(*args, **kwargs)

    def _open_denial_is_still_contention(self, exc: OSError) -> bool:
        """Report whether an open denial may still be transient contention.

        The first denial of an acquisition starts a short budget; while it lasts
        the caller polls again, exactly as it already does for
        ``FileExistsError`` and a busy byte-range lock. Once the budget is spent
        the denial is reported as the permission failure it is. :meth:`acquire`
        reopens the budget, so it bounds one acquisition rather than the reused
        lock object's whole lifetime.

        Args:
            exc: The error raised by :func:`os.open` on the lock path.

        Returns:
            ``True`` while the denial should be retried as contention.
        """
        if exc.errno not in (errno.EACCES, errno.EPERM):
            return False
        deadline = getattr(self, "_open_denial_deadline", None)
        if deadline is None:
            deadline = time.monotonic() + _OPEN_DENIAL_RETRY_SECONDS
            self._open_denial_deadline = deadline
        return time.monotonic() < deadline

    def _open_validated_candidate(
        self,
    ) -> tuple[int, bool, os.stat_result | None] | None:
        lock_path = pathlib.Path(self.lock_file)
        try:
            lock_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise UnsafeFileLockPathError("owner-validated lock path is unsafe") from exc
        try:
            parent_stat = lock_path.parent.lstat()
        except OSError as exc:
            raise UnsafeFileLockPathError("owner-validated lock path is unsafe") from exc
        if (
            not stat.S_ISDIR(parent_stat.st_mode)
            or stat.S_ISLNK(parent_stat.st_mode)
            or _is_reparse_point(parent_stat)
        ):
            raise UnsafeFileLockPathError("owner-validated lock path is unsafe")

        try:
            path_stat = lock_path.lstat()
        except FileNotFoundError:
            path_stat = None
        except OSError as exc:
            raise UnsafeFileLockPathError("owner-validated lock path is unsafe") from exc

        flags = os.O_RDWR | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOINHERIT", 0)
        if path_stat is None:
            try:
                descriptor = os.open(
                    lock_path,
                    flags | os.O_CREAT | os.O_EXCL,
                    self._open_mode(),
                )
            except FileExistsError:
                return None
            except OSError as exc:
                if self._open_denial_is_still_contention(exc):
                    return None
                raise UnsafeFileLockPathError("owner-validated lock path is unsafe") from exc
            self._open_denial_deadline = None
            return descriptor, True, None

        _assert_safe_windows_lock_stat(path_stat)
        try:
            descriptor = os.open(lock_path, flags)
        except FileNotFoundError:
            return None
        except OSError as exc:
            if self._open_denial_is_still_contention(exc):
                return None
            raise UnsafeFileLockPathError("owner-validated lock path is unsafe") from exc
        self._open_denial_deadline = None
        return descriptor, False, path_stat

    def _acquire(self) -> None:
        import msvcrt

        candidate = self._open_validated_candidate()
        if candidate is None:
            return
        descriptor, _created, opened_path_stat = candidate
        security = _windows_descriptor_security()
        locked = False
        acquired = False
        try:
            try:
                descriptor = security.prepare(descriptor)
            except Exception as exc:
                raise UnsafeFileLockPathError(
                    "owner-validated lock path is unsafe"
                ) from exc
            descriptor_stat = os.fstat(descriptor)
            _assert_safe_windows_lock_stat(
                descriptor_stat,
                expected=opened_path_stat,
            )
            try:
                security.assert_current_user_owns(descriptor, descriptor_stat)
            except Exception as exc:
                raise UnsafeFileLockPathError(
                    "owner-validated lock path is unsafe"
                ) from exc

            try:
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                busy_errors = {
                    errno.EACCES,
                    errno.EAGAIN,
                    getattr(errno, "EDEADLK", errno.EACCES),
                }
                if exc.errno in busy_errors:
                    return
                raise
            locked = True

            # O_EXCL publishes a new inode before its exact DACL can be installed.
            # Own the byte lock first so a concurrent first-run waiter observes a
            # busy lock and retries instead of rejecting that short hardening window.
            # This lock file contains no payload. Once the exact regular,
            # single-link, non-reparse inode is current-user-owned and held by
            # this process, repair its DACL in place. That also recovers a
            # creator crash between O_EXCL publication and initial hardening.
            try:
                security.harden(descriptor)
            except Exception as exc:
                raise UnsafeFileLockPathError(
                    "owner-validated lock path is unsafe"
                ) from exc
            descriptor_stat = os.fstat(descriptor)
            _validate_windows_lock_descriptor(descriptor, descriptor_stat, security)

            try:
                current_path_stat = os.lstat(self.lock_file)
            except OSError as exc:
                raise UnsafeFileLockPathError(
                    "owner-validated lock path is unsafe"
                ) from exc
            _assert_safe_windows_lock_stat(
                current_path_stat,
                expected=descriptor_stat,
            )
            final_descriptor_stat = os.fstat(descriptor)
            _assert_safe_windows_lock_stat(
                final_descriptor_stat,
                expected=current_path_stat,
            )
            _validate_windows_lock_descriptor(
                descriptor,
                final_descriptor_stat,
                security,
            )
            self._context.lock_file_fd = descriptor
            acquired = True
        except Exception:
            if locked:
                try:
                    msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            raise
        finally:
            if not acquired:
                os.close(descriptor)

    def _release(self) -> None:
        import msvcrt

        descriptor = cast("int", self._context.lock_file_fd)
        self._context.lock_file_fd = None
        try:
            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        finally:
            os.close(descriptor)


if os.name != "nt":

    class OwnerSafeFileLock(UnixFileLock):
        """Acquire a POSIX advisory lock without following or truncating paths."""

        def _acquire(self) -> None:
            flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
            try:
                descriptor = os.open(self.lock_file, flags, self._open_mode())
            except FileNotFoundError:
                return
            except OSError as exc:
                raise UnsafeFileLockPathError("owner-validated lock path is unsafe") from exc

            locked = False
            acquired = False
            try:
                descriptor_stat = os.fstat(descriptor)
                getuid = getattr(os, "getuid", None)
                if (
                    not stat.S_ISREG(descriptor_stat.st_mode)
                    or descriptor_stat.st_nlink != 1
                    or (callable(getuid) and descriptor_stat.st_uid != getuid())
                ):
                    raise UnsafeFileLockPathError("owner-validated lock path is unsafe")
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError as exc:
                    if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK}:
                        return
                    raise
                locked = True
                path_stat = os.lstat(self.lock_file)
                if (
                    not stat.S_ISREG(path_stat.st_mode)
                    or path_stat.st_nlink != 1
                    or path_stat.st_dev != descriptor_stat.st_dev
                    or path_stat.st_ino != descriptor_stat.st_ino
                    or (callable(getuid) and path_stat.st_uid != getuid())
                ):
                    raise UnsafeFileLockPathError("owner-validated lock path is unsafe")
                self._context.lock_file_fd = descriptor
                acquired = True
            except Exception:
                if locked:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                raise
            finally:
                if not acquired:
                    os.close(descriptor)

else:
    OwnerSafeFileLock = _WindowsOwnerSafeFileLock
