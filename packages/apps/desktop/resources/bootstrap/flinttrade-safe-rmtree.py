#!/usr/bin/env python3
"""Remove one journal-bound POSIX directory without following path aliases.

The Electron caller supplies a trusted absolute parent directory, two confined
entry names, and the device/inode identity recorded in the promotion journal.
The parent must be an owner-only managed directory.  FlintTrade serialises every
writer to that namespace with its singleton-authorised source-operation lease; arbitrary
same-account filesystem mutation is outside this helper's authority boundary
(and cannot be made inode-conditional by POSIX unlink/rmdir APIs).
The helper emits only stable JSON result codes; filesystem paths are never
included in output.
"""

from __future__ import annotations

import argparse
import ctypes
import errno
import json
import os
import stat
import sys
from dataclasses import dataclass
from typing import NoReturn, TextIO


@dataclass(frozen=True)
class _Identity:
    dev: int
    ino: int
    mode: int
    nlink: int
    uid: int


class _SafeDeleteError(Exception):
    def __init__(self, code: str, exit_code: int = 4) -> None:
        super().__init__(code)
        self.code = code
        self.exit_code = exit_code


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> NoReturn:
        raise _SafeDeleteError("INVALID_ARGUMENTS", 2)


def _emit(stream: TextIO, payload: dict[str, object]) -> None:
    stream.write(json.dumps(payload, separators=(",", ":")) + "\n")
    stream.flush()


def _parse_unsigned(value: str) -> int:
    if not value or len(value) > 20 or not value.isascii() or not value.isdecimal():
        raise _SafeDeleteError("INVALID_IDENTITY", 2)
    parsed = int(value, 10)
    if parsed > (1 << 64) - 1:
        raise _SafeDeleteError("INVALID_IDENTITY", 2)
    return parsed


def _parse_arguments(argv: list[str]) -> argparse.Namespace:
    parser = _ArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument("--parent", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--quarantine", required=True)
    parser.add_argument("--expected-dev", required=True)
    parser.add_argument("--expected-ino", required=True)
    arguments = parser.parse_args(argv)
    arguments.expected_dev = _parse_unsigned(arguments.expected_dev)
    arguments.expected_ino = _parse_unsigned(arguments.expected_ino)
    return arguments


def _require_supported_runtime() -> None:
    if os.name != "posix":
        raise _SafeDeleteError("UNSUPPORTED_PLATFORM", 3)
    required_flags = ("O_CLOEXEC", "O_DIRECTORY", "O_NOFOLLOW")
    if any(not hasattr(os, name) for name in required_flags):
        raise _SafeDeleteError("UNSUPPORTED_RUNTIME", 3)
    required_dir_fd = (os.open, os.rename, os.rmdir, os.stat, os.unlink)
    if any(operation not in os.supports_dir_fd for operation in required_dir_fd):
        raise _SafeDeleteError("UNSUPPORTED_RUNTIME", 3)
    if os.listdir not in os.supports_fd:
        raise _SafeDeleteError("UNSUPPORTED_RUNTIME", 3)
    if not hasattr(os, "geteuid"):
        raise _SafeDeleteError("UNSUPPORTED_RUNTIME", 3)


def _validate_parent(parent: str) -> None:
    if (
        not parent
        or not os.path.isabs(parent)
        or os.path.normpath(parent) != parent
        or parent.startswith(os.sep * 2)
        or os.path.dirname(parent) == parent
    ):
        raise _SafeDeleteError("INVALID_PARENT", 2)


def _validate_entry_name(name: str) -> None:
    if not name or name in {".", ".."} or os.path.basename(name) != name or os.sep in name:
        raise _SafeDeleteError("INVALID_ENTRY_NAME", 2)
    if os.path.altsep and os.path.altsep in name:
        raise _SafeDeleteError("INVALID_ENTRY_NAME", 2)


def _identity(value: os.stat_result) -> _Identity:
    return _Identity(dev=value.st_dev, ino=value.st_ino, mode=value.st_mode, nlink=value.st_nlink, uid=value.st_uid)


def _same_object(left: _Identity, right: _Identity) -> bool:
    return left.dev == right.dev and left.ino == right.ino and stat.S_IFMT(left.mode) == stat.S_IFMT(right.mode)


def _lstat_optional(parent_fd: int, name: str) -> _Identity | None:
    try:
        return _identity(os.stat(name, dir_fd=parent_fd, follow_symlinks=False))
    except FileNotFoundError:
        return None


def _open_directory(parent_fd: int, name: str) -> int:
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW
    return os.open(name, flags, dir_fd=parent_fd)


def _open_absolute_directory(path: str) -> int:
    """Open every absolute parent component without following an alias."""
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW
    current_fd = os.open(os.sep, flags)
    try:
        for component in path.removeprefix(os.sep).split(os.sep):
            next_fd = _open_directory(current_fd, component)
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except BaseException:
        os.close(current_fd)
        raise


def _require_directory_identity(
    directory_fd: int,
    observed: _Identity,
    expected_dev: int,
    expected_ino: int,
) -> _Identity:
    opened = _identity(os.fstat(directory_fd))
    if (
        not stat.S_ISDIR(observed.mode)
        or not stat.S_ISDIR(opened.mode)
        or not _same_object(observed, opened)
        or opened.dev != expected_dev
        or opened.ino != expected_ino
    ):
        raise _SafeDeleteError("IDENTITY_MISMATCH")
    return opened


def _require_private_owned_parent(parent: _Identity, owner: int) -> None:
    """Reject namespaces writable by anyone outside the current account.

    Descriptor-relative traversal prevents path aliases, while this owner-only
    boundary and the caller-held source-operation lease exclude cooperative
    concurrent writers.  POSIX exposes no unlink-by-inode primitive, so it
    would be unsafe to run the pathname mutation below in a shared directory.
    """
    if not stat.S_ISDIR(parent.mode) or parent.nlink < 1:
        raise _SafeDeleteError("INVALID_PARENT")
    if parent.uid != owner:
        raise _SafeDeleteError("UNTRUSTED_PARENT")
    if stat.S_IMODE(parent.mode) != 0o700:
        raise _SafeDeleteError("UNTRUSTED_PARENT")


def _require_no_darwin_extended_acl(directory_fd: int) -> None:
    """Reject a Darwin ACL which can grant access despite mode 0700."""
    if sys.platform != "darwin":
        return
    libc = ctypes.CDLL(None, use_errno=True)
    try:
        acl_get_fd_np = libc.acl_get_fd_np
        acl_free = libc.acl_free
    except AttributeError as error:
        raise _SafeDeleteError("UNSUPPORTED_RUNTIME", 3) from error
    acl_get_fd_np.argtypes = [ctypes.c_int, ctypes.c_int]
    acl_get_fd_np.restype = ctypes.c_void_p
    acl_free.argtypes = [ctypes.c_void_p]
    acl_free.restype = ctypes.c_int
    ctypes.set_errno(0)
    acl = acl_get_fd_np(directory_fd, 0x00000100)  # ACL_TYPE_EXTENDED
    if acl:
        acl_free(acl)
        raise _SafeDeleteError("UNTRUSTED_PARENT")
    if ctypes.get_errno() != errno.ENOENT:
        raise _SafeDeleteError("UNTRUSTED_PARENT")


def _open_leaf(parent_fd: int, name: str, observed: _Identity) -> int:
    if stat.S_ISREG(observed.mode):
        flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0)
    elif stat.S_ISLNK(observed.mode):
        if hasattr(os, "O_PATH"):
            flags = os.O_PATH | os.O_CLOEXEC | os.O_NOFOLLOW  # type: ignore[attr-defined]
        elif hasattr(os, "O_SYMLINK"):
            # Darwin's O_SYMLINK opens the link itself. Combining it with
            # O_NOFOLLOW is rejected by the kernel, so O_SYMLINK is the
            # no-follow primitive for this branch.
            flags = os.O_RDONLY | os.O_CLOEXEC | os.O_SYMLINK  # type: ignore[attr-defined]
        else:
            raise _SafeDeleteError("UNSUPPORTED_SYMLINK_PIN", 3)
    else:
        raise _SafeDeleteError("UNSUPPORTED_ENTRY_TYPE")
    return os.open(name, flags, dir_fd=parent_fd)


def _require_path_still_bound(parent_fd: int, name: str, pinned: _Identity) -> None:
    current = _lstat_optional(parent_fd, name)
    if current is None or not _same_object(current, pinned):
        raise _SafeDeleteError("EVIDENCE_CHANGED")


def _remove_leaf(parent_fd: int, name: str, observed: _Identity) -> None:
    leaf_fd = _open_leaf(parent_fd, name, observed)
    try:
        pinned = _identity(os.fstat(leaf_fd))
        if not _same_object(observed, pinned) or pinned.nlink < 1:
            raise _SafeDeleteError("EVIDENCE_CHANGED")
        _require_path_still_bound(parent_fd, name, pinned)
        os.unlink(name, dir_fd=parent_fd)
        after = _identity(os.fstat(leaf_fd))
        if after.dev != pinned.dev or after.ino != pinned.ino or after.nlink != pinned.nlink - 1:
            raise _SafeDeleteError("REMOVAL_NOT_PROVEN")
        if _lstat_optional(parent_fd, name) is not None:
            raise _SafeDeleteError("EVIDENCE_REAPPEARED")
    finally:
        os.close(leaf_fd)


def _remove_directory_contents(directory_fd: int, root_device: int) -> None:
    for name in sorted(os.listdir(directory_fd)):
        if name in {".", ".."} or os.sep in name or (os.path.altsep and os.path.altsep in name):
            raise _SafeDeleteError("INVALID_DIRECTORY_ENTRY")
        observed = _lstat_optional(directory_fd, name)
        if observed is None:
            raise _SafeDeleteError("EVIDENCE_CHANGED")

        if stat.S_ISDIR(observed.mode):
            if observed.dev != root_device:
                raise _SafeDeleteError("CROSS_DEVICE_ENTRY")
            child_fd = _open_directory(directory_fd, name)
            try:
                pinned = _require_directory_identity(child_fd, observed, observed.dev, observed.ino)
                _remove_directory_contents(child_fd, root_device)
                if os.listdir(child_fd):
                    raise _SafeDeleteError("DIRECTORY_NOT_EMPTY")
                _require_path_still_bound(directory_fd, name, pinned)
                os.fsync(child_fd)
                os.rmdir(name, dir_fd=directory_fd)
                if _lstat_optional(directory_fd, name) is not None:
                    raise _SafeDeleteError("EVIDENCE_REAPPEARED")
                os.fsync(directory_fd)
            finally:
                os.close(child_fd)
        else:
            _remove_leaf(directory_fd, name, observed)
            os.fsync(directory_fd)


def _safe_remove(arguments: argparse.Namespace) -> None:
    _validate_parent(arguments.parent)
    _validate_entry_name(arguments.target)
    _validate_entry_name(arguments.quarantine)
    if arguments.target == arguments.quarantine:
        raise _SafeDeleteError("ENTRY_NAMES_ALIAS", 2)

    parent_fd = _open_absolute_directory(arguments.parent)
    directory_fd: int | None = None
    try:
        parent_identity = _identity(os.fstat(parent_fd))
        _require_private_owned_parent(parent_identity, os.geteuid())
        _require_no_darwin_extended_acl(parent_fd)

        target = _lstat_optional(parent_fd, arguments.target)
        quarantine = _lstat_optional(parent_fd, arguments.quarantine)
        if (target is None) == (quarantine is None):
            raise _SafeDeleteError("AMBIGUOUS_EVIDENCE")

        entry_name = arguments.target if target is not None else arguments.quarantine
        observed = target if target is not None else quarantine
        if observed is None:
            raise _SafeDeleteError("AMBIGUOUS_EVIDENCE")
        directory_fd = _open_directory(parent_fd, entry_name)
        pinned = _require_directory_identity(
            directory_fd,
            observed,
            arguments.expected_dev,
            arguments.expected_ino,
        )
        if pinned.dev != parent_identity.dev:
            raise _SafeDeleteError("CROSS_DEVICE_TARGET")

        if target is not None:
            _require_path_still_bound(parent_fd, arguments.target, pinned)
            if _lstat_optional(parent_fd, arguments.quarantine) is not None:
                raise _SafeDeleteError("AMBIGUOUS_EVIDENCE")
            os.rename(
                arguments.target,
                arguments.quarantine,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
            )
            os.fsync(parent_fd)

        if _lstat_optional(parent_fd, arguments.target) is not None:
            raise _SafeDeleteError("AMBIGUOUS_EVIDENCE")
        _require_path_still_bound(parent_fd, arguments.quarantine, pinned)
        if not _same_object(_identity(os.fstat(directory_fd)), pinned):
            raise _SafeDeleteError("EVIDENCE_CHANGED")

        _remove_directory_contents(directory_fd, pinned.dev)
        if os.listdir(directory_fd):
            raise _SafeDeleteError("DIRECTORY_NOT_EMPTY")
        os.fsync(directory_fd)
        _require_path_still_bound(parent_fd, arguments.quarantine, pinned)
        if _lstat_optional(parent_fd, arguments.target) is not None:
            raise _SafeDeleteError("AMBIGUOUS_EVIDENCE")
        os.rmdir(arguments.quarantine, dir_fd=parent_fd)
        if _lstat_optional(parent_fd, arguments.quarantine) is not None:
            raise _SafeDeleteError("EVIDENCE_REAPPEARED")
        if _lstat_optional(parent_fd, arguments.target) is not None:
            raise _SafeDeleteError("EVIDENCE_REAPPEARED")
        os.fsync(parent_fd)
    finally:
        if directory_fd is not None:
            os.close(directory_fd)
        os.close(parent_fd)


def main(argv: list[str] | None = None) -> int:
    try:
        _require_supported_runtime()
        arguments = _parse_arguments(sys.argv[1:] if argv is None else argv)
        _safe_remove(arguments)
    except _SafeDeleteError as error:
        _emit(sys.stderr, {"ok": False, "code": error.code})
        return error.exit_code
    except BaseException:
        _emit(sys.stderr, {"ok": False, "code": "FILESYSTEM_ERROR"})
        return 5
    _emit(sys.stdout, {"ok": True, "status": "removed"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
