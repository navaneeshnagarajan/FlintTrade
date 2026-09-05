"""Harden secret files and provide durable atomic file operations."""

from __future__ import annotations

import ctypes
import errno
import functools
import hashlib
import os
import pathlib
import stat
import sys
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


class HeldOwnerDirectory:
    """Retain an owner-validated directory as publication authority.

    Descendants retain their parent scope. POSIX operations are relative to
    descriptors; Windows holds the namespace without delete sharing. This
    prevents pathname redirection, not arbitrary compromise of the OS owner.
    """

    def __init__(
        self,
        path: pathlib.Path,
        *,
        require_hardened: bool = True,
        _parent: HeldOwnerDirectory | None = None,
    ) -> None:
        self.path = pathlib.Path(path)
        self.require_hardened = require_hardened
        self._parent = _parent
        self._descriptor = -1

    @staticmethod
    def _name(name: str) -> str:
        if type(name) is not str or not name or name in {".", ".."} or any(c in name for c in "/\\\0:"):
            raise OSError("unsafe directory member")
        return name

    def __enter__(self) -> HeldOwnerDirectory:
        if self._descriptor != -1:
            raise OSError("directory scope already open")
        if self._parent is not None:
            self._parent.revalidate()
        before = self.path.lstat()
        if not stat.S_ISDIR(before.st_mode) or stat.S_ISLNK(before.st_mode) or _is_reparse_point(before):
            raise OSError("unsafe directory")
        if _is_windows():
            self._descriptor = _open_windows_directory(self.path)
        else:
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
            self._descriptor = os.open(
                self.path.name if self._parent else self.path,
                flags,
                dir_fd=self._parent._descriptor if self._parent else None,
            )
        try:
            self._stat = os.fstat(self._descriptor)
            if not _same_file_identity(before, self._stat):
                raise OSError("directory changed while opened")
            self.revalidate()
            return self
        except BaseException:
            self.__exit__()
            raise

    def __exit__(self, *args: object) -> None:
        if self._descriptor != -1:
            os.close(self._descriptor)
            self._descriptor = -1

    def revalidate(self) -> os.stat_result:
        """Prove the held directory still occupies its admitted path."""
        if self._descriptor == -1:
            raise OSError("directory scope is closed")
        if self._parent is not None:
            self._parent.revalidate()
        opened = os.fstat(self._descriptor)
        current = self.path.lstat()
        if (
            not stat.S_ISDIR(opened.st_mode)
            or not stat.S_ISDIR(current.st_mode)
            or stat.S_ISLNK(current.st_mode)
            or _is_reparse_point(current)
            or not _same_file_identity(opened, current)
            or not _same_file_identity(opened, self._stat)
            or not opened.st_ino
        ):
            raise OSError("directory identity changed")
        _assert_current_user_owns(self._descriptor, opened)
        if self.require_hardened:
            if _is_windows():
                valid, _reason = _verify_exact_windows_descriptor_dacl(self._descriptor)
                if not valid:
                    raise InsecureFilePermissionsError("directory is not hardened")
            elif stat.S_IMODE(opened.st_mode) != 0o700:
                raise InsecureFilePermissionsError("directory is not hardened")
        return opened

    def child(self, name: str, *, create: bool = False) -> HeldOwnerDirectory:
        """Return a child scope; create only a previously absent directory."""
        self.revalidate()
        name = self._name(name)
        if create:
            try:
                if _is_windows():
                    os.mkdir(self.path / name, 0o700)
                    harden_directory(self.path / name)
                else:
                    os.mkdir(name, 0o700, dir_fd=self._descriptor)
                    os.fsync(self._descriptor)
            except FileExistsError:
                pass
        return HeldOwnerDirectory(self.path / name, _parent=self)

    def exists(self, name: str) -> bool:
        self.revalidate()
        try:
            self._entry_stat(name)
            return True
        except FileNotFoundError:
            return False

    def existing_member(self, name: str) -> str | None:
        """Locate an entry or its deterministic durable-delete remainder."""
        name = self._name(name)
        pending = pending_unlink_path(self.path / name).name
        present, pending_present = self.exists(name), self.exists(pending)
        if present and pending_present:
            raise OSError("ambiguous pending deletion")
        return name if present else pending if pending_present else None

    def _entry_stat(self, name: str) -> os.stat_result:
        name = self._name(name)
        if _is_windows():
            return (self.path / name).lstat()
        return os.stat(name, dir_fd=self._descriptor, follow_symlinks=False)

    def read_text(self, name: str, *, max_bytes: int = 64 * 1024) -> str:
        """Read one bounded hardened regular member of the retained directory."""
        return self.read_text_with_identity(name, max_bytes=max_bytes)[0]

    def read_text_with_identity(
        self,
        name: str,
        *,
        max_bytes: int = 64 * 1024,
    ) -> tuple[str, os.stat_result]:
        """Observe bounded text and its physical member identity together.

        This is not an inode-CAS. Exclusive claim users must compare the moved
        object with this observation before publishing a replacement.
        """
        self.revalidate()
        name = self._name(name)
        before = self._entry_stat(name)
        if _is_windows():
            result = read_hardened_owner_owned_text(self.path / name, max_bytes=max_bytes)
            opened = before
        else:
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                raise OSError("unsafe directory member")
            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=self._descriptor)
            try:
                opened = os.fstat(descriptor)
                if not _same_file_identity(before, opened):
                    raise OSError("directory member changed")
                result = _read_bounded_descriptor(
                    descriptor,
                    max_bytes=max_bytes,
                    path=self.path / name,
                    require_hardened=True,
                ).decode("utf-8")
                after = os.fstat(descriptor)
                if (opened.st_size, opened.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise OSError("directory member changed while read")
                if not _same_file_identity(opened, self._entry_stat(name)):
                    raise OSError("directory member changed")
            finally:
                os.close(descriptor)
        self.revalidate()
        current = self._entry_stat(name)
        if (
            not _same_file_identity(opened, current)
            or (opened.st_size, opened.st_mtime_ns) != (current.st_size, current.st_mtime_ns)
            or not opened.st_ino
        ):
            raise OSError("directory member changed while read")
        return result, opened

    def write_text(self, name: str, value: str) -> None:
        """Atomically publish text under the retained namespace authority."""
        self.revalidate()
        name = self._name(name)
        if self.exists(name):
            self.read_text(name, max_bytes=1024 * 1024)
        if _is_windows():
            write_secret_text(self.path / name, value)
            self.revalidate()
            return
        import uuid

        temporary = f".{name}.{uuid.uuid4()}.tmp"
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=self._descriptor,
        )
        created = os.fstat(descriptor)
        try:
            os.fchmod(descriptor, 0o600)
            _assert_current_user_owns(descriptor, os.fstat(descriptor))
            payload = value.encode("utf-8")
            offset = 0
            while offset < len(payload):
                written = os.write(descriptor, payload[offset:])
                if written <= 0:
                    raise OSError("secure write made no progress")
                offset += written
            os.fsync(descriptor)
            self.revalidate()
            if not _same_file_identity(created, self._entry_stat(temporary)):
                raise OSError("candidate changed")
            os.replace(temporary, name, src_dir_fd=self._descriptor, dst_dir_fd=self._descriptor)
            os.fsync(self._descriptor)
            self.revalidate()
        except BaseException:
            try:
                if _same_file_identity(created, self._entry_stat(temporary)):
                    os.unlink(temporary, dir_fd=self._descriptor)
                    os.fsync(self._descriptor)
            except FileNotFoundError:
                pass
            raise
        finally:
            os.close(descriptor)

    def replace(self, name: str, destination: HeldOwnerDirectory, target: str) -> None:
        """Publish a validated journal-owned candidate into another held scope."""
        name, target = self._name(name), self._name(target)
        self.read_text(name, max_bytes=1024 * 1024)
        destination.revalidate()
        if destination.exists(target):
            destination.read_text(target, max_bytes=1024 * 1024)
        if _is_windows():
            durable_replace(self.path / name, destination.path / target)
        else:
            os.replace(name, target, src_dir_fd=self._descriptor, dst_dir_fd=destination._descriptor)
            os.fsync(destination._descriptor)
            os.fsync(self._descriptor)
        self.revalidate()
        destination.revalidate()

    def move_no_replace(self, name: str, destination: HeldOwnerDirectory, target: str) -> None:
        """Exclusively move a hardened member; never overwrite a destination.

        Unsupported native/filesystem semantics fail closed. The caller owns
        journalled member identity and authentication, including crash recovery.
        """
        name, target = self._name(name), self._name(target)
        self.read_text_with_identity(name, max_bytes=1024 * 1024)
        destination.revalidate()
        if _is_windows():
            _windows_replace_write_through(self.path / name, destination.path / target, replace=False)
        else:
            _posix_move_no_replace(self._descriptor, name, destination._descriptor, target)
            os.fsync(destination._descriptor)
            os.fsync(self._descriptor)
        self.revalidate()
        destination.revalidate()

    def unlink(self, name: str) -> None:
        """Durably remove a validated member; transaction ownership is caller policy."""
        name = self._name(name)
        actual = self.existing_member(name)
        if actual is None:
            raise FileNotFoundError("directory member is absent")
        self.read_text(actual, max_bytes=1024 * 1024)
        if _is_windows():
            if actual != name:
                cleanup_pending_unlink(self.path / name)
            else:
                durable_unlink(self.path / name)
        else:
            os.unlink(actual, dir_fd=self._descriptor)
            os.fsync(self._descriptor)
        self.revalidate()


def _posix_move_no_replace(source_fd: int, source: str, target_fd: int, target: str) -> None:
    """Native descriptor-relative exclusive rename, with no fallback."""
    if sys.platform == "darwin":
        symbol, flags = "renameatx_np", 0x4  # RENAME_EXCL, Darwin sys/stdio.h
    elif sys.platform.startswith("linux"):
        symbol, flags = "renameat2", 0x1  # RENAME_NOREPLACE
    else:
        raise OSError(errno.ENOTSUP, "exclusive rename is unsupported")
    library = ctypes.CDLL(None, use_errno=True)
    function = getattr(library, symbol, None)
    if function is None:
        raise OSError(errno.ENOTSUP, "exclusive rename is unavailable")
    function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    function.restype = ctypes.c_int
    if function(source_fd, os.fsencode(source), target_fd, os.fsencode(target), flags):
        raise OSError(ctypes.get_errno(), "exclusive rename failed")


def _open_windows_directory(path: pathlib.Path) -> int:
    """Open a directory with native no-reparse and no-delete-sharing semantics."""
    import msvcrt

    kernel32, _advapi32 = _windows_security_libraries()
    create = kernel32.CreateFileW
    create.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    create.restype = ctypes.c_void_p
    handle = create(
        str(path),
        _GENERIC_READ | _READ_CONTROL,
        _FILE_SHARE_READ | _FILE_SHARE_WRITE,
        None,
        3,
        0x02000000 | 0x00200000,
        None,
    )
    if not handle or handle == ctypes.c_void_p(-1).value:
        _raise_windows_error()
    try:
        return msvcrt.open_osfhandle(handle, os.O_RDONLY | getattr(os, "O_BINARY", 0))
    except BaseException:
        kernel32.CloseHandle(ctypes.c_void_p(handle))
        raise


def validate_owner_owned_directory(path: pathlib.Path, *, require_hardened: bool = True) -> os.stat_result:
    """Observe a safe directory; retain a scope separately for later publication."""
    with HeldOwnerDirectory(path, require_hardened=require_hardened) as directory:
        return directory.revalidate()


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


def _windows_replace_write_through(
    source: pathlib.Path,
    destination: pathlib.Path,
    *,
    replace: bool = True,
) -> None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    move_file = kernel32.MoveFileExW
    move_file.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
    move_file.restype = ctypes.c_int
    flags = _MOVEFILE_WRITE_THROUGH | (_MOVEFILE_REPLACE_EXISTING if replace else 0)
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


def validate_owner_owned_regular_file(
    path: pathlib.Path,
    *,
    require_hardened: bool = False,
) -> os.stat_result:
    """Validate one current-user-owned regular file without reading its payload.

    The path is opened without following links where the platform supports it,
    ownership is proved on the descriptor, and the directory entry is compared
    again before returning.  This is the streaming-safe counterpart to the
    bounded secure readers for large SQLite snapshots.
    """
    path = pathlib.Path(path)
    path_stat = path.lstat()
    parent_stat = path.parent.lstat()
    if (
        not stat.S_ISDIR(parent_stat.st_mode)
        or stat.S_ISLNK(parent_stat.st_mode)
        or _is_reparse_point(parent_stat)
        or not stat.S_ISREG(path_stat.st_mode)
        or stat.S_ISLNK(path_stat.st_mode)
        or _is_reparse_point(path_stat)
        or path_stat.st_nlink != 1
    ):
        raise OSError("secure file path is unsafe")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
    if not _is_windows():
        flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        if _is_windows():
            descriptor = _reopen_windows_descriptor_for_security(descriptor, write_dacl=False)
        opened_stat = os.fstat(descriptor)
        if not _same_file_identity(path_stat, opened_stat) or opened_stat.st_nlink != 1:
            raise OSError("secure file changed while it was opened")
        _assert_current_user_owns(descriptor, opened_stat)
        if require_hardened:
            _assert_hardened_descriptor(descriptor, opened_stat, path=path)
        final_stat = path.lstat()
        if (
            not _same_file_identity(opened_stat, final_stat)
            or stat.S_ISLNK(final_stat.st_mode)
            or _is_reparse_point(final_stat)
            or final_stat.st_nlink != 1
        ):
            raise OSError("secure file changed while it was validated")
        return opened_stat
    finally:
        os.close(descriptor)


def digest_owner_owned_regular_file(
    path: pathlib.Path,
    *,
    require_hardened: bool = False,
) -> str:
    """Return a SHA-256 digest from one validated, descriptor-pinned file."""
    digest, _path_stat = digest_owner_owned_regular_file_identity(
        path,
        require_hardened=require_hardened,
    )
    return digest


def digest_owner_owned_regular_file_identity(
    path: pathlib.Path,
    *,
    require_hardened: bool = False,
) -> tuple[str, os.stat_result]:
    """Return a stable descriptor-pinned digest and file generation.

    Size and timestamp metadata are checked on the open descriptor before and
    after streaming, as well as against the final directory entry.  Callers
    can therefore persist both the content digest and the exact generation
    that produced it without a path-based stat/hash race.
    """
    path = pathlib.Path(path)
    path_stat = path.lstat()
    parent_stat = path.parent.lstat()
    if (
        not stat.S_ISDIR(parent_stat.st_mode)
        or stat.S_ISLNK(parent_stat.st_mode)
        or _is_reparse_point(parent_stat)
        or not stat.S_ISREG(path_stat.st_mode)
        or stat.S_ISLNK(path_stat.st_mode)
        or _is_reparse_point(path_stat)
        or path_stat.st_nlink != 1
    ):
        raise OSError("secure file path is unsafe")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
    if not _is_windows():
        flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        if _is_windows():
            descriptor = _reopen_windows_descriptor_for_security(descriptor, write_dacl=False)
        opened_stat = os.fstat(descriptor)
        if not _same_file_identity(path_stat, opened_stat) or opened_stat.st_nlink != 1:
            raise OSError("secure file changed while it was opened")
        _assert_current_user_owns(descriptor, opened_stat)
        if require_hardened:
            _assert_hardened_descriptor(descriptor, opened_stat, path=path)
        digest = hashlib.sha256()
        while chunk := os.read(descriptor, 1 << 20):
            digest.update(chunk)
        final_descriptor_stat = os.fstat(descriptor)
        final_stat = path.lstat()
        if (
            _stable_file_generation(opened_stat) != _stable_file_generation(final_descriptor_stat)
            or _stable_file_generation(final_descriptor_stat) != _stable_file_generation(final_stat)
            or stat.S_ISLNK(final_stat.st_mode)
            or _is_reparse_point(final_stat)
            or final_stat.st_nlink != 1
        ):
            raise OSError("secure file changed while it was hashed")
        return digest.hexdigest(), final_descriptor_stat
    finally:
        os.close(descriptor)


def _stable_file_generation(path_stat: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        path_stat.st_dev,
        path_stat.st_ino,
        path_stat.st_size,
        path_stat.st_mtime_ns,
        path_stat.st_ctime_ns,
    )


def copy_owner_owned_file_durable(source: pathlib.Path, destination: pathlib.Path) -> None:
    """Copy a hardened owner-owned file to a new hardened, fsynced candidate."""
    source = pathlib.Path(source)
    destination = pathlib.Path(destination)
    source_stat = validate_owner_owned_regular_file(source, require_hardened=True)
    parent_stat = destination.parent.lstat()
    if (
        not stat.S_ISDIR(parent_stat.st_mode)
        or stat.S_ISLNK(parent_stat.st_mode)
        or _is_reparse_point(parent_stat)
    ):
        raise OSError("secure copy destination parent is unsafe")
    source_flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
    if not _is_windows():
        source_flags |= getattr(os, "O_NOFOLLOW", 0)
    source_descriptor = os.open(source, source_flags)
    destination_descriptor = -1
    destination_stat: os.stat_result | None = None
    try:
        if _is_windows():
            source_descriptor = _reopen_windows_descriptor_for_security(source_descriptor, write_dacl=False)
        opened_source_stat = os.fstat(source_descriptor)
        if not _same_file_identity(source_stat, opened_source_stat):
            raise OSError("secure copy source changed while it was opened")
        _assert_current_user_owns(source_descriptor, opened_source_stat)
        _assert_hardened_descriptor(source_descriptor, opened_source_stat, path=source)
        destination_flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_CLOEXEC", 0)
        )
        destination_descriptor = os.open(destination, destination_flags, 0o600)
        if _is_windows():
            destination_descriptor = _reopen_windows_descriptor_for_security(
                destination_descriptor,
                write_dacl=True,
            )
        destination_stat = os.fstat(destination_descriptor)
        if _is_windows():
            _install_exact_windows_descriptor_dacl(destination_descriptor)
        else:
            os.fchmod(destination_descriptor, 0o600)
        hardened_destination_stat = os.fstat(destination_descriptor)
        _assert_current_user_owns(destination_descriptor, hardened_destination_stat)
        _assert_hardened_descriptor(destination_descriptor, hardened_destination_stat, path=destination)
        while chunk := os.read(source_descriptor, 1 << 20):
            offset = 0
            while offset < len(chunk):
                written = os.write(destination_descriptor, chunk[offset:])
                if written <= 0:
                    raise OSError("secure copy made no progress")
                offset += written
        final_source_stat = source.lstat()
        if (
            not _same_file_identity(opened_source_stat, final_source_stat)
            or stat.S_ISLNK(final_source_stat.st_mode)
            or _is_reparse_point(final_source_stat)
            or final_source_stat.st_nlink != 1
        ):
            raise OSError("secure copy source changed while it was read")
        os.fsync(destination_descriptor)
        final_destination_stat = destination.lstat()
        if not _same_file_identity(hardened_destination_stat, final_destination_stat):
            raise OSError("secure copy destination changed while it was written")
    except Exception:
        if destination_descriptor != -1:
            os.close(destination_descriptor)
            destination_descriptor = -1
        if destination_stat is not None:
            try:
                current_stat = destination.lstat()
                if _same_file_identity(destination_stat, current_stat):
                    durable_unlink(destination)
            except OSError:
                pass
        raise
    finally:
        if destination_descriptor != -1:
            os.close(destination_descriptor)
        os.close(source_descriptor)


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
