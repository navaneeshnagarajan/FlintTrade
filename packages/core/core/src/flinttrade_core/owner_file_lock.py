"""Owner-validated cross-process locks that never truncate POSIX paths."""

from __future__ import annotations

import errno
import os
import stat

from filelock import FileLock, UnixFileLock

if os.name != "nt":
    import fcntl


class UnsafeFileLockPathError(RuntimeError):
    """A lock path does not identify one owner-owned regular file."""


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
    OwnerSafeFileLock = FileLock
