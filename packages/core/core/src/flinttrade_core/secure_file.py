"""Harden secret files and provide durable atomic file operations."""

from __future__ import annotations

import ctypes
import functools
import os
import pathlib
import stat
import tempfile

SENSITIVE_PATTERNS = (
    "*master*", "*pepper*", "*secret*", "*jwt*", "*credentials*", "*.db",
)

_MOVEFILE_REPLACE_EXISTING = 0x1
_MOVEFILE_WRITE_THROUGH = 0x8
_TOKEN_QUERY = 0x0008
_TOKEN_USER = 1
_SE_FILE_OBJECT = 1
_OWNER_SECURITY_INFORMATION = 0x00000001
_DACL_SECURITY_INFORMATION = 0x00000004
_PROTECTED_DACL_SECURITY_INFORMATION = 0x80000000
_SE_DACL_PROTECTED = 0x1000
_ACL_REVISION = 2
_ACCESS_ALLOWED_ACE_TYPE = 0
_INHERITED_ACE = 0x10
# Inheritance ACE flags for DIRECTORY DACLs. Setting a protected DACL on a
# directory makes Windows recalculate inheritance on every existing child; a
# child whose DACL was purely inherited (the normal case for files created
# under an ordinary parent) is left with an EMPTY DACL — denied to everyone,
# including its owner — if the new directory ACEs carry no inheritance flags.
# Directory ACEs therefore always carry OBJECT_INHERIT|CONTAINER_INHERIT so
# both existing and future children inherit the same owner + SYSTEM grants.
# File ACEs stay non-inheritable (the flags are meaningless on files).
_OBJECT_INHERIT_ACE = 0x1
_CONTAINER_INHERIT_ACE = 0x2
_DIRECTORY_ACE_FLAGS = _OBJECT_INHERIT_ACE | _CONTAINER_INHERIT_ACE
_FILE_ALL_ACCESS = 0x001F01FF
_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
_READ_CONTROL = 0x00020000
_WRITE_DAC = 0x00040000
_FILE_SHARE_READ = 0x00000001
_FILE_SHARE_WRITE = 0x00000002
_FILE_SHARE_DELETE = 0x00000004
_ERROR_INSUFFICIENT_BUFFER = 122
_SYSTEM_SID = b"\x01\x01\x00\x00\x00\x00\x00\x05\x12\x00\x00\x00"


class _Acl(ctypes.Structure):
    _fields_ = [
        ("revision", ctypes.c_ubyte),
        ("reserved", ctypes.c_ubyte),
        ("size", ctypes.c_ushort),
        ("ace_count", ctypes.c_ushort),
        ("reserved2", ctypes.c_ushort),
    ]


class _AceHeader(ctypes.Structure):
    _fields_ = [
        ("ace_type", ctypes.c_ubyte),
        ("ace_flags", ctypes.c_ubyte),
        ("ace_size", ctypes.c_ushort),
    ]


class _AccessAllowedAce(ctypes.Structure):
    _fields_ = [
        ("header", _AceHeader),
        ("access_mask", ctypes.c_uint32),
        ("sid_start", ctypes.c_uint32),
    ]


class _SidAndAttributes(ctypes.Structure):
    _fields_ = [
        ("sid", ctypes.c_void_p),
        ("attributes", ctypes.c_uint32),
    ]


class _TokenUser(ctypes.Structure):
    _fields_ = [("user", _SidAndAttributes)]


class PendingDurableUnlinkError(OSError):
    """A Windows unlink is logically committed but tombstone cleanup is pending."""


class InsecureFilePermissionsError(PermissionError):
    """An owner-owned regular file has broader access than the secret policy."""


def _is_windows() -> bool:
    return os.name == "nt"


@functools.lru_cache(maxsize=1)
def _windows_security_libraries():  # type: ignore[no-untyped-def]
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)  # type: ignore[attr-defined]

    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    kernel32.ReOpenFile.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_uint32,
    ]
    kernel32.ReOpenFile.restype = ctypes.c_void_p

    advapi32.OpenProcessToken.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    advapi32.OpenProcessToken.restype = ctypes.c_int
    advapi32.GetTokenInformation.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint32),
    ]
    advapi32.GetTokenInformation.restype = ctypes.c_int
    advapi32.LookupAccountNameW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.c_wchar_p,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.POINTER(ctypes.c_uint32),
    ]
    advapi32.LookupAccountNameW.restype = ctypes.c_int
    advapi32.IsValidSid.argtypes = [ctypes.c_void_p]
    advapi32.IsValidSid.restype = ctypes.c_int
    advapi32.GetLengthSid.argtypes = [ctypes.c_void_p]
    advapi32.GetLengthSid.restype = ctypes.c_uint32
    advapi32.InitializeAcl.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32]
    advapi32.InitializeAcl.restype = ctypes.c_int
    advapi32.AddAccessAllowedAceEx.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    advapi32.AddAccessAllowedAceEx.restype = ctypes.c_int
    advapi32.SetNamedSecurityInfoW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    advapi32.SetNamedSecurityInfoW.restype = ctypes.c_uint32
    advapi32.SetSecurityInfo.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    advapi32.SetSecurityInfo.restype = ctypes.c_uint32
    advapi32.GetNamedSecurityInfoW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    advapi32.GetNamedSecurityInfoW.restype = ctypes.c_uint32
    advapi32.GetSecurityInfo.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    advapi32.GetSecurityInfo.restype = ctypes.c_uint32
    advapi32.GetSecurityDescriptorControl.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_ushort),
        ctypes.POINTER(ctypes.c_uint32),
    ]
    advapi32.GetSecurityDescriptorControl.restype = ctypes.c_int
    advapi32.GetAce.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
    advapi32.GetAce.restype = ctypes.c_int
    return kernel32, advapi32


def _raise_windows_error(code: int | None = None) -> None:
    raise ctypes.WinError(code if code is not None else ctypes.get_last_error())


def _reopen_windows_descriptor_for_security(
    descriptor: int,
    *,
    allow_delete_sharing: bool = True,
    write_dacl: bool,
) -> int:
    """Reopen the same file object with the rights needed for DACL proof/update."""
    import msvcrt

    kernel32, _advapi32 = _windows_security_libraries()
    original_handle = msvcrt.get_osfhandle(descriptor)
    desired_access = _GENERIC_READ | _READ_CONTROL
    descriptor_flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOINHERIT", 0)
    if write_dacl:
        desired_access |= _GENERIC_WRITE | _WRITE_DAC
        descriptor_flags = os.O_RDWR | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOINHERIT", 0)
    share_mode = _FILE_SHARE_READ | _FILE_SHARE_WRITE
    if allow_delete_sharing:
        share_mode |= _FILE_SHARE_DELETE
    reopened_handle = kernel32.ReOpenFile(
        ctypes.c_void_p(original_handle),
        desired_access,
        share_mode,
        0,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    if not reopened_handle or reopened_handle == invalid_handle:
        _raise_windows_error()
    try:
        reopened_descriptor = msvcrt.open_osfhandle(
            reopened_handle,
            descriptor_flags,
        )
    except Exception:
        kernel32.CloseHandle(ctypes.c_void_p(reopened_handle))
        raise
    try:
        os.close(descriptor)
    except Exception:
        os.close(reopened_descriptor)
        raise
    return reopened_descriptor


def _copy_windows_sid(sid: ctypes.c_void_p) -> bytes:
    _kernel32, advapi32 = _windows_security_libraries()
    if not sid or not advapi32.IsValidSid(sid):
        raise OSError("Windows returned an invalid security identifier")
    length = advapi32.GetLengthSid(sid)
    if not length:
        _raise_windows_error()
    return ctypes.string_at(sid, length)


def _windows_current_user_sid() -> bytes:
    kernel32, advapi32 = _windows_security_libraries()
    token = ctypes.c_void_p()
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), _TOKEN_QUERY, ctypes.byref(token)):
        _raise_windows_error()
    try:
        required = ctypes.c_uint32()
        ctypes.set_last_error(0)
        advapi32.GetTokenInformation(token, _TOKEN_USER, None, 0, ctypes.byref(required))
        if ctypes.get_last_error() != _ERROR_INSUFFICIENT_BUFFER or not required.value:
            _raise_windows_error()
        buffer = ctypes.create_string_buffer(required.value)
        if not advapi32.GetTokenInformation(
            token,
            _TOKEN_USER,
            buffer,
            required.value,
            ctypes.byref(required),
        ):
            _raise_windows_error()
        token_user = ctypes.cast(buffer, ctypes.POINTER(_TokenUser)).contents
        return _copy_windows_sid(token_user.user.sid)
    finally:
        kernel32.CloseHandle(token)


def _windows_account_sid(user: str | None = None) -> bytes:
    if not user:
        return _windows_current_user_sid()
    _kernel32, advapi32 = _windows_security_libraries()
    sid_size = ctypes.c_uint32()
    domain_size = ctypes.c_uint32()
    sid_type = ctypes.c_uint32()
    ctypes.set_last_error(0)
    advapi32.LookupAccountNameW(
        None,
        user,
        None,
        ctypes.byref(sid_size),
        None,
        ctypes.byref(domain_size),
        ctypes.byref(sid_type),
    )
    if ctypes.get_last_error() != _ERROR_INSUFFICIENT_BUFFER or not sid_size.value:
        _raise_windows_error()
    sid_buffer = ctypes.create_string_buffer(sid_size.value)
    domain_buffer = ctypes.create_unicode_buffer(max(1, domain_size.value))
    if not advapi32.LookupAccountNameW(
        None,
        user,
        sid_buffer,
        ctypes.byref(sid_size),
        domain_buffer,
        ctypes.byref(domain_size),
        ctypes.byref(sid_type),
    ):
        _raise_windows_error()
    return _copy_windows_sid(ctypes.cast(sid_buffer, ctypes.c_void_p))


def _install_exact_windows_dacl(path: pathlib.Path, *, user: str | None = None) -> None:
    _kernel32, advapi32 = _windows_security_libraries()
    ace_flags = _DIRECTORY_ACE_FLAGS if path.is_dir() else 0
    sid_values = (_windows_account_sid(user), _SYSTEM_SID)
    acl_size = ctypes.sizeof(_Acl) + sum(
        ctypes.sizeof(_AccessAllowedAce) - ctypes.sizeof(ctypes.c_uint32) + len(sid)
        for sid in sid_values
    )
    acl = ctypes.create_string_buffer(acl_size)
    if not advapi32.InitializeAcl(acl, acl_size, _ACL_REVISION):
        _raise_windows_error()
    sid_buffers = [ctypes.create_string_buffer(sid) for sid in sid_values]
    for sid_buffer in sid_buffers:
        if not advapi32.AddAccessAllowedAceEx(
            acl,
            _ACL_REVISION,
            ace_flags,
            _FILE_ALL_ACCESS,
            sid_buffer,
        ):
            _raise_windows_error()
    result = advapi32.SetNamedSecurityInfoW(
        str(path),
        _SE_FILE_OBJECT,
        _DACL_SECURITY_INFORMATION | _PROTECTED_DACL_SECURITY_INFORMATION,
        None,
        None,
        acl,
        None,
    )
    if result:
        _raise_windows_error(result)


def _install_exact_windows_descriptor_dacl(
    descriptor: int,
    *,
    user: str | None = None,
) -> None:
    import msvcrt

    _kernel32, advapi32 = _windows_security_libraries()
    ace_flags = _DIRECTORY_ACE_FLAGS if stat.S_ISDIR(os.fstat(descriptor).st_mode) else 0
    sid_values = (_windows_account_sid(user), _SYSTEM_SID)
    acl_size = ctypes.sizeof(_Acl) + sum(
        ctypes.sizeof(_AccessAllowedAce) - ctypes.sizeof(ctypes.c_uint32) + len(sid)
        for sid in sid_values
    )
    acl = ctypes.create_string_buffer(acl_size)
    if not advapi32.InitializeAcl(acl, acl_size, _ACL_REVISION):
        _raise_windows_error()
    sid_buffers = [ctypes.create_string_buffer(sid) for sid in sid_values]
    for sid_buffer in sid_buffers:
        if not advapi32.AddAccessAllowedAceEx(
            acl,
            _ACL_REVISION,
            ace_flags,
            _FILE_ALL_ACCESS,
            sid_buffer,
        ):
            _raise_windows_error()
    result = advapi32.SetSecurityInfo(
        ctypes.c_void_p(msvcrt.get_osfhandle(descriptor)),
        _SE_FILE_OBJECT,
        _DACL_SECURITY_INFORMATION | _PROTECTED_DACL_SECURITY_INFORMATION,
        None,
        None,
        acl,
        None,
    )
    if result:
        _raise_windows_error(result)


def _verify_windows_security_descriptor(
    owner: ctypes.c_void_p,
    dacl: ctypes.c_void_p,
    descriptor: ctypes.c_void_p,
    *,
    user: str | None,
    expected_ace_flags: int = 0,
) -> tuple[bool, str]:
    _kernel32, advapi32 = _windows_security_libraries()
    if _copy_windows_sid(owner) != _windows_account_sid(user):
        return False, "file owner is not the selected user"
    if not dacl:
        return False, "no DACL (file accessible to everyone)"

    control = ctypes.c_ushort()
    revision = ctypes.c_uint32()
    if not advapi32.GetSecurityDescriptorControl(
        descriptor,
        ctypes.byref(control),
        ctypes.byref(revision),
    ):
        return False, "DACL control flags could not be inspected"
    if not control.value & _SE_DACL_PROTECTED:
        return False, "DACL inheritance is not protected"

    acl = ctypes.cast(dacl, ctypes.POINTER(_Acl)).contents
    if acl.ace_count != 2:
        return False, "DACL must contain exactly owner and SYSTEM ACEs"
    actual_sids: set[bytes] = set()
    for index in range(acl.ace_count):
        ace_pointer = ctypes.c_void_p()
        if not advapi32.GetAce(dacl, index, ctypes.byref(ace_pointer)):
            return False, "DACL ACE could not be inspected"
        ace = ctypes.cast(ace_pointer, ctypes.POINTER(_AccessAllowedAce)).contents
        if ace.header.ace_type != _ACCESS_ALLOWED_ACE_TYPE:
            return False, "DACL contains a non-allow ACE"
        if ace.header.ace_flags & _INHERITED_ACE:
            return False, "DACL contains an inherited ACE"
        if ace.header.ace_flags != expected_ace_flags:
            # A directory hardened before inheritance flags were introduced
            # carries flag-less ACEs that strip every pre-existing child's
            # inherited DACL — failing here makes harden() reinstall the
            # corrected DACL, which restores the children on propagation.
            return False, "DACL ACE inheritance flags do not match the object type"
        if ace.access_mask != _FILE_ALL_ACCESS:
            return False, "DACL ACE does not grant exact full control"
        sid_pointer = ctypes.c_void_p(
            ace_pointer.value + _AccessAllowedAce.sid_start.offset
        )
        actual_sids.add(_copy_windows_sid(sid_pointer))
    if actual_sids != {_windows_account_sid(user), _SYSTEM_SID}:
        return False, "DACL contains an unexpected SID"
    return True, ""


def _verify_exact_windows_dacl(path: pathlib.Path, *, user: str | None = None) -> tuple[bool, str]:
    kernel32, advapi32 = _windows_security_libraries()
    owner = ctypes.c_void_p()
    dacl = ctypes.c_void_p()
    descriptor = ctypes.c_void_p()
    result = advapi32.GetNamedSecurityInfoW(
        str(path),
        _SE_FILE_OBJECT,
        _OWNER_SECURITY_INFORMATION | _DACL_SECURITY_INFORMATION,
        ctypes.byref(owner),
        None,
        ctypes.byref(dacl),
        None,
        ctypes.byref(descriptor),
    )
    if result:
        return False, f"ACL inspection failed with Windows error {result}"
    try:
        return _verify_windows_security_descriptor(
            owner,
            dacl,
            descriptor,
            user=user,
            expected_ace_flags=_DIRECTORY_ACE_FLAGS if path.is_dir() else 0,
        )
    finally:
        if descriptor:
            kernel32.LocalFree(descriptor)


def _verify_exact_windows_descriptor_dacl(
    descriptor: int,
    *,
    user: str | None = None,
) -> tuple[bool, str]:
    import msvcrt

    kernel32, advapi32 = _windows_security_libraries()
    owner = ctypes.c_void_p()
    dacl = ctypes.c_void_p()
    security_descriptor = ctypes.c_void_p()
    result = advapi32.GetSecurityInfo(
        ctypes.c_void_p(msvcrt.get_osfhandle(descriptor)),
        _SE_FILE_OBJECT,
        _OWNER_SECURITY_INFORMATION | _DACL_SECURITY_INFORMATION,
        ctypes.byref(owner),
        None,
        ctypes.byref(dacl),
        None,
        ctypes.byref(security_descriptor),
    )
    if result:
        return False, f"ACL inspection failed with Windows error {result}"
    try:
        return _verify_windows_security_descriptor(
            owner,
            dacl,
            security_descriptor,
            user=user,
            expected_ace_flags=(
                _DIRECTORY_ACE_FLAGS if stat.S_ISDIR(os.fstat(descriptor).st_mode) else 0
            ),
        )
    finally:
        if security_descriptor:
            kernel32.LocalFree(security_descriptor)


def harden(path: pathlib.Path, user: str | None = None) -> None:
    """Restrict *path* to owner-only (+ SYSTEM on Windows). Idempotent.

    Security H5: SYSTEM:F is granted alongside ``<user>:F`` so OS-level
    operations (Defender scans, Backup, VSS, crash dumps) keep working;
    Administrators are intentionally NOT granted for secret files.
    """
    path = pathlib.Path(path)
    if not _is_windows():
        path.chmod(0o600)
        return
    try:
        _install_exact_windows_dacl(path, user=user)
        hardened, reason = _verify_exact_windows_dacl(path, user=user)
        if not hardened:
            raise PermissionError(reason)
    except Exception as exc:
        detail = str(exc).replace(str(path.parent), "<dir>").replace(str(path), path.name)
        raise OSError(f"failed to harden {path.name}: {detail}") from exc


def harden_directory(path: pathlib.Path, user: str | None = None) -> None:
    """Restrict a directory to its owner (+ SYSTEM on Windows)."""
    path = pathlib.Path(path)
    if not path.is_dir():
        raise NotADirectoryError(path)
    if _is_windows():
        harden(path, user=user)
        return
    path.chmod(0o700)


def _windows_replace_write_through(source: pathlib.Path, destination: pathlib.Path) -> None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    move_file = kernel32.MoveFileExW
    move_file.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
    move_file.restype = ctypes.c_int
    flags = _MOVEFILE_REPLACE_EXISTING | _MOVEFILE_WRITE_THROUGH
    if not move_file(str(source), str(destination), flags):
        raise ctypes.WinError(ctypes.get_last_error())


def durable_replace(source: pathlib.Path, destination: pathlib.Path) -> None:
    """Atomically replace *destination* with a persistence barrier."""
    source = pathlib.Path(source)
    destination = pathlib.Path(destination)
    if _is_windows():
        _windows_replace_write_through(source, destination)
        return
    os.replace(source, destination)
    fsync_parent_directory(destination)
    if source.parent != destination.parent:
        fsync_parent_directory(source)


def pending_unlink_path(path: pathlib.Path) -> pathlib.Path:
    """Return the deterministic recovery tombstone used by :func:`durable_unlink`."""
    path = pathlib.Path(path)
    return path.with_name(f".{path.name}.delete-pending")


def _windows_delete_file(path: pathlib.Path) -> None:
    path.unlink()


def cleanup_pending_unlink(path: pathlib.Path) -> None:
    """Finish a prior Windows tombstone deletion, if one exists."""
    if not _is_windows():
        return
    tombstone = pending_unlink_path(path)
    try:
        tombstone.lstat()
    except FileNotFoundError:
        return
    try:
        _windows_delete_file(tombstone)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise PendingDurableUnlinkError(
            f"durable unlink cleanup remains pending for {path.name}"
        ) from exc


def durable_unlink(path: pathlib.Path) -> None:
    """Durably remove a path, retaining a recoverable Windows tombstone on failure."""
    path = pathlib.Path(path)
    if not _is_windows():
        try:
            path.unlink()
        except FileNotFoundError:
            return
        fsync_parent_directory(path)
        return

    cleanup_pending_unlink(path)
    tombstone = pending_unlink_path(path)
    try:
        _windows_replace_write_through(path, tombstone)
    except FileNotFoundError:
        return
    try:
        _windows_delete_file(tombstone)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise PendingDurableUnlinkError(
            f"durable unlink committed; cleanup remains pending for {path.name}"
        ) from exc


def write_secret_text(path: pathlib.Path, value: str, user: str | None = None) -> None:
    """Write secret text through an owner-only file descriptor.

    The file is created with ``0600`` on POSIX before any secret bytes are
    written. On Windows an empty file is created first, then hardened with the
    same DACL policy as :func:`harden`, so plaintext is never written into a
    broadly inherited file.
    """
    path = pathlib.Path(path)
    parent_existed = path.parent.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not parent_existed:
        fsync_parent_directory(path.parent)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = pathlib.Path(temporary_name)
    try:
        harden(temporary_path, user=user)
        payload = value.encode("utf-8")
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise OSError("secret file write made no progress")
            offset += written
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        durable_replace(temporary_path, path)
    except Exception:
        if descriptor != -1:
            os.close(descriptor)
            descriptor = -1
        try:
            durable_unlink(temporary_path)
        except OSError:
            pass
        raise
    finally:
        if descriptor != -1:
            os.close(descriptor)


def fsync_parent_directory(path: pathlib.Path) -> None:
    """Persist a completed directory-entry change on POSIX.

    Windows does not expose directory ``fsync`` through ``os.open``; callers
    use write-through rename primitives there instead.
    """
    if _is_windows():
        return
    directory = pathlib.Path(path).parent
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(directory, flags)
    try:
        directory_stat = os.fstat(descriptor)
        if not stat.S_ISDIR(directory_stat.st_mode):
            raise OSError("secure file parent is not a directory")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _is_reparse_point(path_stat: os.stat_result) -> bool:
    reparse_mask = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(reparse_mask and getattr(path_stat, "st_file_attributes", 0) & reparse_mask)


def _same_file_identity(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _assert_current_user_owns(descriptor: int, path_stat: os.stat_result) -> None:
    if not _is_windows():
        if path_stat.st_uid != os.geteuid():
            raise PermissionError("secure file is not owned by the current user")
        return

    import msvcrt

    kernel32, advapi32 = _windows_security_libraries()
    owner = ctypes.c_void_p()
    security_descriptor = ctypes.c_void_p()
    result = advapi32.GetSecurityInfo(
        ctypes.c_void_p(msvcrt.get_osfhandle(descriptor)),
        _SE_FILE_OBJECT,
        _OWNER_SECURITY_INFORMATION,
        ctypes.byref(owner),
        None,
        None,
        None,
        ctypes.byref(security_descriptor),
    )
    if result:
        raise OSError(f"secure file ownership inspection failed with Windows error {result}")
    try:
        if _copy_windows_sid(owner) != _windows_current_user_sid():
            raise PermissionError("secure file is not owned by the current user")
    finally:
        if security_descriptor:
            kernel32.LocalFree(security_descriptor)


def _assert_hardened_descriptor(
    descriptor: int,
    path_stat: os.stat_result,
    *,
    path: pathlib.Path,
) -> None:
    if path_stat.st_nlink != 1:
        raise OSError("secure file must have exactly one directory entry")
    if not _is_windows():
        if stat.S_IMODE(path_stat.st_mode) != 0o600:
            raise InsecureFilePermissionsError(
                "secure file is not hardened for the current user"
            )
        return

    hardened, reason = _verify_exact_windows_descriptor_dacl(descriptor)
    if not hardened:
        raise InsecureFilePermissionsError(
            f"secure file is not hardened for the current user: {reason}"
        )
    current_path_stat = path.lstat()
    if (
        not _same_file_identity(path_stat, current_path_stat)
        or stat.S_ISLNK(current_path_stat.st_mode)
        or _is_reparse_point(current_path_stat)
    ):
        raise OSError("secure file changed while its permissions were inspected")


def _read_bounded_descriptor(
    descriptor: int,
    *,
    max_bytes: int,
    path: pathlib.Path,
    require_hardened: bool,
) -> bytes:
    file_stat = os.fstat(descriptor)
    if (
        not stat.S_ISREG(file_stat.st_mode)
        or _is_reparse_point(file_stat)
        or file_stat.st_size > max_bytes
    ):
        raise OSError("secure file is not a bounded regular file")
    _assert_current_user_owns(descriptor, file_stat)
    if require_hardened:
        _assert_hardened_descriptor(descriptor, file_stat, path=path)
    chunks: list[bytes] = []
    remaining = max_bytes + 1
    while remaining:
        chunk = os.read(descriptor, min(64 * 1024, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    payload = b"".join(chunks)
    if len(payload) > max_bytes:
        raise OSError("secure file exceeds its read limit")
    return payload


def _read_owner_owned_bytes(
    path: pathlib.Path,
    *,
    max_bytes: int,
    require_hardened: bool,
) -> bytes:
    path = pathlib.Path(path)
    if max_bytes < 1:
        raise ValueError("max_bytes must be positive")

    if _is_windows():
        parent_stat = path.parent.lstat()
        path_stat = path.lstat()
        if (
            not stat.S_ISDIR(parent_stat.st_mode)
            or _is_reparse_point(parent_stat)
            or not stat.S_ISREG(path_stat.st_mode)
            or stat.S_ISLNK(path_stat.st_mode)
            or _is_reparse_point(path_stat)
        ):
            raise OSError("secure file path is unsafe")
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0))
        try:
            descriptor = _reopen_windows_descriptor_for_security(
                descriptor,
                write_dacl=False,
            )
            opened_stat = os.fstat(descriptor)
            current_path_stat = path.lstat()
            if (
                not _same_file_identity(path_stat, opened_stat)
                or not _same_file_identity(opened_stat, current_path_stat)
                or _is_reparse_point(current_path_stat)
            ):
                raise OSError("secure file changed while it was opened")
            payload = _read_bounded_descriptor(
                descriptor,
                max_bytes=max_bytes,
                path=path,
                require_hardened=require_hardened,
            )
            final_path_stat = path.lstat()
            if (
                not _same_file_identity(opened_stat, final_path_stat)
                or stat.S_ISLNK(final_path_stat.st_mode)
                or _is_reparse_point(final_path_stat)
            ):
                raise OSError("secure file changed while it was read")
            return payload
        finally:
            os.close(descriptor)

    parent_flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    parent_descriptor = os.open(path.parent, parent_flags)
    try:
        parent_stat = os.fstat(parent_descriptor)
        if not stat.S_ISDIR(parent_stat.st_mode):
            raise OSError("secure file parent is not a directory")
        flags = (
            os.O_RDONLY
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        try:
            path_stat = os.stat(
                path.name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            raise
        except OSError as exc:
            raise OSError("secure file path is unsafe") from exc
        if stat.S_ISLNK(path_stat.st_mode) or not stat.S_ISREG(path_stat.st_mode):
            raise OSError("secure file path is unsafe")
        try:
            descriptor = os.open(path.name, flags, dir_fd=parent_descriptor)
        except FileNotFoundError:
            raise
        except OSError as exc:
            raise OSError("secure file path is unsafe") from exc
        try:
            opened_stat = os.fstat(descriptor)
            if not _same_file_identity(path_stat, opened_stat):
                raise OSError("secure file changed while it was opened")
            payload = _read_bounded_descriptor(
                descriptor,
                max_bytes=max_bytes,
                path=path,
                require_hardened=require_hardened,
            )
            final_path_stat = os.stat(
                path.name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
            if (
                not _same_file_identity(opened_stat, final_path_stat)
                or stat.S_ISLNK(final_path_stat.st_mode)
            ):
                raise OSError("secure file changed while it was read")
            return payload
        finally:
            os.close(descriptor)
    finally:
        os.close(parent_descriptor)


def read_owner_owned_bytes(path: pathlib.Path, *, max_bytes: int = 64 * 1024) -> bytes:
    """Read a bounded, current-user-owned regular file without following links."""
    return _read_owner_owned_bytes(
        path,
        max_bytes=max_bytes,
        require_hardened=False,
    )


def read_hardened_owner_owned_bytes(
    path: pathlib.Path,
    *,
    max_bytes: int = 64 * 1024,
) -> bytes:
    """Read a bounded owner-owned secret only when its permissions are hardened."""
    return _read_owner_owned_bytes(
        path,
        max_bytes=max_bytes,
        require_hardened=True,
    )


def read_owner_owned_text(
    path: pathlib.Path,
    *,
    encoding: str = "utf-8",
    max_bytes: int = 64 * 1024,
) -> str:
    """Read owner-owned text through the no-follow binary reader."""
    return read_owner_owned_bytes(path, max_bytes=max_bytes).decode(encoding)


def read_hardened_owner_owned_text(
    path: pathlib.Path,
    *,
    encoding: str = "utf-8",
    max_bytes: int = 64 * 1024,
) -> str:
    """Read hardened owner-owned text without following links."""
    return read_hardened_owner_owned_bytes(path, max_bytes=max_bytes).decode(encoding)


def assert_hardened(path: pathlib.Path, user: str | None = None) -> tuple[bool, str]:
    """Return ``(is_hardened, reason)``. Owner + SYSTEM are the only allowed ACEs."""
    path = pathlib.Path(path)
    if not _is_windows():
        st = path.stat()
        too_broad = (st.st_mode & 0o077) != 0
        return (not too_broad, "" if not too_broad else f"mode is {oct(st.st_mode)}")
    try:
        return _verify_exact_windows_dacl(path, user=user)
    except OSError as exc:
        code = getattr(exc, "winerror", None) or getattr(exc, "errno", None) or "unknown"
        return False, f"ACL inspection failed with Windows error {code}"


def startup_check(flinttrade_dir: pathlib.Path) -> list[str]:
    """Walk *flinttrade_dir*; return FILENAMES (Security L1: not full paths) needing hardening."""
    flinttrade_dir = pathlib.Path(flinttrade_dir)
    needs_hardening: list[str] = []
    seen: set[pathlib.Path] = set()
    for pattern in SENSITIVE_PATTERNS:
        for path in flinttrade_dir.rglob(pattern):
            if path.is_dir() or path in seen:
                continue
            seen.add(path)
            ok, reason = assert_hardened(path)
            if not ok:
                needs_hardening.append(f"{path.name}: {reason}")
    return needs_hardening
