"""secure_file ACL hardening tests (supply-chain §13; SC-04 / HI18)."""

from __future__ import annotations

import os
import errno
import sys
from pathlib import Path

import pytest

from flinttrade_core import secure_file
from flinttrade_core.secure_file import assert_hardened, harden, startup_check, write_secret_text

try:  # pragma: no cover - env-dependent
    import win32security  # noqa: F401

    _HAS_PYWIN32 = True
except ImportError:  # pragma: no cover
    _HAS_PYWIN32 = False

_IS_WIN = sys.platform == "win32"


def test_exclusive_member_move_never_overwrites_a_destination(tmp_path):
    with secure_file.HeldOwnerDirectory(tmp_path) as directory:
        directory.write_text("candidate", "candidate")
        directory.write_text("occupied", "retain entrant")
        move = getattr(directory, "move_no_replace", directory.replace)
        try:
            move("candidate", directory, "occupied")
        except OSError:
            pass
        assert directory.read_text("occupied") == "retain entrant"
        assert directory.read_text("candidate") == "candidate"


@pytest.mark.skipif(_IS_WIN, reason="POSIX mode-bit fixture for cross-platform recovery logic")
def test_opt_in_child_recovery_hardens_an_empty_owner_directory(tmp_path):
    child = tmp_path / "interrupted"
    child.mkdir(mode=0o700)
    child.chmod(0o755)

    with secure_file.HeldOwnerDirectory(tmp_path) as parent:
        with parent.child("interrupted", create=True, recover_empty=True) as recovered:
            assert recovered.revalidate()

    assert child.stat().st_mode & 0o777 == 0o700


@pytest.mark.skipif(_IS_WIN, reason="POSIX mode-bit fixture for cross-platform recovery logic")
def test_opt_in_child_recovery_refuses_a_nonempty_unhardened_directory(tmp_path):
    child = tmp_path / "foreign"
    child.mkdir(mode=0o700)
    child.chmod(0o755)
    retained = child / "retain"
    retained.write_text("unchanged")

    with secure_file.HeldOwnerDirectory(tmp_path) as parent:
        with pytest.raises(secure_file.InsecureFilePermissionsError):
            parent.child("foreign", create=True, recover_empty=True)

    assert child.stat().st_mode & 0o777 == 0o755
    assert retained.read_text() == "unchanged"


@pytest.mark.skipif(not _IS_WIN, reason="native Windows inherited-DACL recovery")
def test_windows_opt_in_child_recovery_replaces_an_inherited_directory_dacl(tmp_path):
    secure_file.harden_directory(tmp_path)
    child = tmp_path / "interrupted"
    child.mkdir()

    with secure_file.HeldOwnerDirectory(tmp_path) as parent:
        with pytest.raises(secure_file.InsecureFilePermissionsError):
            with parent.child("interrupted"):
                pass
        with parent.child("interrupted", create=True, recover_empty=True) as recovered:
            assert recovered.revalidate()


@pytest.mark.skipif(_IS_WIN, reason="POSIX descriptor barriers")
def test_exclusive_move_preserves_member_identity_and_flushes_both_namespaces(tmp_path, monkeypatch):
    with secure_file.HeldOwnerDirectory(tmp_path) as parent:
        with parent.child("source", create=True) as source, parent.child("target", create=True) as target:
            source.write_text("candidate", "fixture")
            payload, observed = source.read_text_with_identity("candidate")
            calls = []
            sync = os.fsync

            def synced(descriptor):
                calls.append(descriptor)
                sync(descriptor)

            monkeypatch.setattr(os, "fsync", synced)
            source.move_no_replace("candidate", target, "installed")
            installed, current = target.read_text_with_identity("installed")
            assert installed == payload == "fixture"
            assert (observed.st_dev, observed.st_ino) == (current.st_dev, current.st_ino)
            assert not source.exists("candidate")
            assert calls == [target._descriptor, source._descriptor]


@pytest.mark.skipif(_IS_WIN, reason="POSIX native failure branches")
@pytest.mark.parametrize(
    "platform,symbol,flags,error",
    [
        ("darwin", "renameatx_np", 4, errno.EXDEV),
        ("linux", "renameat2", 1, errno.ENOTSUP),
    ],
)
def test_exclusive_native_failure_has_no_overwrite_fallback(tmp_path, monkeypatch, platform, symbol, flags, error):
    calls = []

    class NativeFailure:
        def __call__(self, *arguments):
            calls.append(arguments)
            secure_file.ctypes.set_errno(error)
            return -1

    class Library:
        pass

    library = Library()
    setattr(library, symbol, NativeFailure())
    with secure_file.HeldOwnerDirectory(tmp_path) as directory:
        directory.write_text("candidate", "retain candidate")
        directory.write_text("occupied", "retain entrant")
        monkeypatch.setattr(sys, "platform", platform)
        monkeypatch.setattr(secure_file.ctypes, "CDLL", lambda *args, **kwargs: library)
        with pytest.raises(OSError) as caught:
            directory.move_no_replace("candidate", directory, "occupied")
        assert caught.value.errno == error
        assert calls == [(directory._descriptor, b"candidate", directory._descriptor, b"occupied", flags)]
        assert directory.read_text("candidate") == "retain candidate"
        assert directory.read_text("occupied") == "retain entrant"


@pytest.mark.skipif(_IS_WIN, reason="POSIX native availability")
def test_missing_exclusive_native_symbol_fails_closed(tmp_path, monkeypatch):
    with secure_file.HeldOwnerDirectory(tmp_path) as directory:
        directory.write_text("candidate", "retained")
        monkeypatch.setattr(secure_file.ctypes, "CDLL", lambda *args, **kwargs: object())
        with pytest.raises(OSError) as caught:
            directory.move_no_replace("candidate", directory, "installed")
        assert caught.value.errno == errno.ENOTSUP
        assert directory.read_text("candidate") == "retained"
        assert not directory.exists("installed")


def test_windows_exclusive_move_has_only_write_through_flag(monkeypatch):
    calls = []

    class Move:
        def __call__(self, *args):
            calls.append(args)
            return 0

    class Kernel:
        MoveFileExW = Move()

    monkeypatch.setattr(secure_file.ctypes, "WinDLL", lambda *args, **kwargs: Kernel(), raising=False)
    monkeypatch.setattr(secure_file.ctypes, "get_last_error", lambda: 80, raising=False)
    monkeypatch.setattr(secure_file.ctypes, "WinError", lambda error: OSError(error, "fixture conflict"), raising=False)
    with pytest.raises(OSError):
        secure_file._windows_replace_write_through(Path("candidate"), Path("occupied"), replace=False)
    assert calls == [("candidate", "occupied", secure_file._MOVEFILE_WRITE_THROUGH)]


@pytest.mark.skipif(_IS_WIN, reason="POSIX substitution; Windows denies directory delete sharing")
def test_held_directory_publication_cannot_follow_replaced_root(tmp_path):
    root = tmp_path / "root"
    root.mkdir(mode=0o700)
    with secure_file.HeldOwnerDirectory(root) as directory:
        root.rename(tmp_path / "original")
        root.mkdir(mode=0o700)
        try:
            directory.write_text("candidate", "1234")
        except OSError:
            pass
        assert list(root.iterdir()) == [], "a replaced root must never receive the candidate"
        with pytest.raises(OSError):
            directory.revalidate()


def test_held_directory_roundtrip_and_lifetime(tmp_path):
    with secure_file.HeldOwnerDirectory(tmp_path) as directory:
        directory.write_text("candidate", "1234")
        assert directory.read_text("candidate", max_bytes=4) == "1234"
        with pytest.raises(OSError):
            directory.read_text("candidate", max_bytes=3)
        directory.replace("candidate", directory, "installed")
        assert directory.read_text("installed", max_bytes=4) == "1234"
        directory.unlink("installed")
        assert not directory.exists("installed")
    with pytest.raises(OSError):
        directory.revalidate()


@pytest.mark.skipif(_IS_WIN, reason="POSIX descriptor-relative race")
def test_held_publication_remains_anchored_when_root_moves_during_open(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir(mode=0o700)
    original_open = os.open

    def replace_during_open(name, flags, *args, **kwargs):
        if str(name).startswith(".candidate."):
            root.rename(tmp_path / "original")
            root.mkdir(mode=0o700)
        return original_open(name, flags, *args, **kwargs)

    with secure_file.HeldOwnerDirectory(root) as directory:
        monkeypatch.setattr(os, "open", replace_during_open)
        with pytest.raises(OSError):
            directory.write_text("candidate", "1234")
    assert list(root.iterdir()) == []
    assert list((tmp_path / "original").iterdir()) == []


def test_held_directory_rejects_links_and_hardlinked_members(tmp_path):
    root = tmp_path / "root"
    root.mkdir(mode=0o700)
    link = tmp_path / "link"
    link.symlink_to(root, target_is_directory=True)
    with pytest.raises(OSError):
        with secure_file.HeldOwnerDirectory(link):
            pass
    with secure_file.HeldOwnerDirectory(root) as directory:
        directory.write_text("candidate", "1234")
        os.link(root / "candidate", root / "second")
        with pytest.raises(OSError):
            directory.unlink("candidate")
        with pytest.raises(OSError):
            directory.write_text("candidate", "5678")
    assert (root / "candidate").read_text() == "1234"


@pytest.mark.skipif(_IS_WIN, reason="POSIX owner and fd checks")
def test_held_directory_owner_failure_closes_descriptor(tmp_path, monkeypatch):
    descriptors = []

    def reject(descriptor, _stat):
        descriptors.append(descriptor)
        raise PermissionError("foreign owner")

    monkeypatch.setattr(secure_file, "_assert_current_user_owns", reject)
    with pytest.raises(PermissionError):
        with secure_file.HeldOwnerDirectory(tmp_path):
            pass
    assert len(descriptors) == 1
    with pytest.raises(OSError):
        os.fstat(descriptors[0])


@pytest.mark.skipif(_IS_WIN, reason="POSIX fsync ordering")
def test_held_write_hardens_before_payload_and_flushes_file_then_directory(tmp_path, monkeypatch):
    calls = []
    write, chmod, sync = os.write, os.fchmod, os.fsync

    def hardened(descriptor, mode):
        calls.append("harden")
        return chmod(descriptor, mode)

    def written(descriptor, payload):
        calls.append("write")
        return write(descriptor, payload[:2])

    def synced(descriptor):
        calls.append("directory-sync" if __import__("stat").S_ISDIR(os.fstat(descriptor).st_mode) else "file-sync")
        return sync(descriptor)

    with secure_file.HeldOwnerDirectory(tmp_path) as directory:
        monkeypatch.setattr(os, "fchmod", hardened)
        monkeypatch.setattr(os, "write", written)
        monkeypatch.setattr(os, "fsync", synced)
        directory.write_text("candidate", "123456")
        assert directory.read_text("candidate") == "123456"
    assert calls == ["harden", "write", "write", "write", "file-sync", "directory-sync"]


def test_native_windows_directory_open_denies_delete_sharing_and_opens_reparse_object(monkeypatch):
    calls = []

    class Create:
        def __call__(self, *args):
            calls.append(args)
            return 222

    class Kernel:
        CreateFileW = Create()

        def CloseHandle(self, handle):
            calls.append(("closed", handle.value))

    class CRT:
        @staticmethod
        def open_osfhandle(handle, flags):
            assert handle == 222
            return 73

    monkeypatch.setattr(secure_file, "_windows_security_libraries", lambda: (Kernel(), object()))
    monkeypatch.setitem(sys.modules, "msvcrt", CRT)
    assert secure_file._open_windows_directory(Path("fixture")) == 73
    args = calls[0]
    assert not args[2] & secure_file._FILE_SHARE_DELETE
    assert args[2] & secure_file._FILE_SHARE_READ and args[2] & secure_file._FILE_SHARE_WRITE
    assert args[5] & 0x02000000 and args[5] & 0x00200000


@pytest.mark.skipif(_IS_WIN, reason="POSIX modes")
@pytest.mark.parametrize("mode", [0o755, 0o777, 0o600])
def test_held_directory_rejects_unsafe_modes(tmp_path, mode):
    root = tmp_path / "root"
    root.mkdir(mode=mode)
    with pytest.raises(OSError):
        with secure_file.HeldOwnerDirectory(root):
            pass


def test_harden_is_idempotent(tmp_path) -> None:
    f = tmp_path / "jwt_secret"
    f.write_text("s3cret")
    harden(f)
    harden(f)  # second run must not raise


def test_startup_check_returns_filenames(tmp_path) -> None:
    (tmp_path / "master_password").write_text("pw")
    (tmp_path / "credentials.db").write_text("x")
    result = startup_check(tmp_path)
    assert isinstance(result, list)
    # warnings must be filenames only (Security L1), never full paths
    for entry in result:
        assert "\\" not in entry.split(":")[0]
        assert "/" not in entry.split(":")[0]


def test_write_secret_text_creates_hardened_file(tmp_path) -> None:
    secret = tmp_path / "jwt_secret"

    write_secret_text(secret, "secret-value")

    assert secret.read_text(encoding="utf-8") == "secret-value"
    ok, reason = assert_hardened(secret)
    assert ok, reason


def test_read_hardened_owner_owned_text_roundtrips_a_secure_file(tmp_path) -> None:
    secret = tmp_path / "jwt_secret"
    write_secret_text(secret, "secret-value")

    assert secure_file.read_hardened_owner_owned_text(secret) == "secret-value"


def test_windows_hardened_validation_uses_the_open_descriptor(tmp_path, monkeypatch) -> None:
    secret = tmp_path / "jwt_secret"
    secret.write_text("secret-value", encoding="utf-8")
    path_stat = secret.stat()
    inspected_descriptors: list[int] = []

    monkeypatch.setattr(secure_file, "_is_windows", lambda: True)
    monkeypatch.setattr(
        secure_file,
        "_verify_exact_windows_descriptor_dacl",
        lambda descriptor: (inspected_descriptors.append(descriptor) or True, ""),
    )

    secure_file._assert_hardened_descriptor(73, path_stat, path=secret)

    assert inspected_descriptors == [73]


@pytest.mark.parametrize("write_dacl", [False, True])
@pytest.mark.parametrize("allow_delete_sharing", [False, True])
def test_windows_security_reopen_requests_rights_on_the_same_handle(
    monkeypatch,
    write_dacl,
    allow_delete_sharing,
) -> None:
    calls: list[tuple[object, ...]] = []

    class FakeKernel32:
        def ReOpenFile(self, handle, desired_access, share_mode, flags):  # type: ignore[no-untyped-def]
            calls.append(("reopen", handle.value, desired_access, share_mode, flags))
            return 222

        def CloseHandle(self, handle):  # type: ignore[no-untyped-def]
            calls.append(("close-handle", handle.value))

    fake_msvcrt = type(
        "FakeMsvcrt",
        (),
        {
            "get_osfhandle": staticmethod(lambda descriptor: 111 if descriptor == 17 else -1),
            "open_osfhandle": staticmethod(lambda handle, _flags: 23 if handle == 222 else -1),
        },
    )
    monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)
    monkeypatch.setattr(
        secure_file,
        "_windows_security_libraries",
        lambda: (FakeKernel32(), object()),
    )
    monkeypatch.setattr(secure_file.os, "close", lambda descriptor: calls.append(("close-fd", descriptor)))

    reopened = secure_file._reopen_windows_descriptor_for_security(
        17,
        allow_delete_sharing=allow_delete_sharing,
        write_dacl=write_dacl,
    )

    assert reopened == 23
    reopen_call = calls[0]
    assert reopen_call[0:2] == ("reopen", 111)
    assert reopen_call[2] & secure_file._READ_CONTROL
    assert bool(reopen_call[2] & secure_file._WRITE_DAC) is write_dacl
    assert bool(reopen_call[2] & secure_file._GENERIC_WRITE) is write_dacl
    expected_share_mode = secure_file._FILE_SHARE_READ | secure_file._FILE_SHARE_WRITE
    if allow_delete_sharing:
        expected_share_mode |= secure_file._FILE_SHARE_DELETE
    assert reopen_call[3] == expected_share_mode
    assert calls[-1] == ("close-fd", 17)
    assert all(call[0] != "close-handle" for call in calls)


def test_read_hardened_owner_owned_text_rejects_a_symlink(tmp_path) -> None:
    target = tmp_path / "target"
    target.write_text("secret-value", encoding="utf-8")
    target.chmod(0o600)
    link = tmp_path / "jwt_secret"
    link.symlink_to(target)

    with pytest.raises(OSError, match="unsafe"):
        secure_file.read_hardened_owner_owned_text(link)


def test_read_hardened_owner_owned_text_rejects_a_directory(tmp_path) -> None:
    secret = tmp_path / "jwt_secret"
    secret.mkdir()

    with pytest.raises(OSError):
        secure_file.read_hardened_owner_owned_text(secret)


@pytest.mark.skipif(_IS_WIN, reason="POSIX owner and mode semantics")
def test_read_hardened_owner_owned_text_rejects_another_owner(tmp_path, monkeypatch) -> None:
    secret = tmp_path / "jwt_secret"
    secret.write_text("secret-value", encoding="utf-8")
    secret.chmod(0o600)
    actual_user = secret.stat().st_uid
    monkeypatch.setattr(secure_file.os, "geteuid", lambda: actual_user + 1)

    with pytest.raises(PermissionError, match="owned by the current user"):
        secure_file.read_hardened_owner_owned_text(secret)


@pytest.mark.skipif(_IS_WIN, reason="POSIX mode-bit semantics")
def test_read_hardened_owner_owned_text_rejects_broad_mode(tmp_path) -> None:
    secret = tmp_path / "jwt_secret"
    secret.write_text("secret-value", encoding="utf-8")
    secret.chmod(0o640)

    with pytest.raises(PermissionError, match="not hardened"):
        secure_file.read_hardened_owner_owned_text(secret)


@pytest.mark.skipif(_IS_WIN, reason="POSIX mode-bit semantics")
def test_read_hardened_owner_owned_text_requires_exact_0600(tmp_path) -> None:
    secret = tmp_path / "jwt_secret"
    secret.write_text("secret-value", encoding="utf-8")
    secret.chmod(0o400)

    with pytest.raises(PermissionError, match="not hardened"):
        secure_file.read_hardened_owner_owned_text(secret)


@pytest.mark.skipif(_IS_WIN, reason="POSIX hard-link semantics")
def test_read_hardened_owner_owned_text_rejects_a_hard_link(tmp_path) -> None:
    secret = tmp_path / "jwt_secret"
    secret.write_text("secret-value", encoding="utf-8")
    secret.chmod(0o600)
    os.link(secret, tmp_path / "second-name")

    with pytest.raises(OSError, match="one directory entry"):
        secure_file.read_hardened_owner_owned_text(secret)


@pytest.mark.skipif(_IS_WIN, reason="POSIX mode-bit semantics")
def test_assert_hardened_posix_roundtrip(tmp_path) -> None:
    f = tmp_path / "jwt_secret"
    f.write_text("s3cret")
    f.chmod(0o644)  # world-readable
    ok, reason = assert_hardened(f)
    assert ok is False and reason
    harden(f)  # → chmod 0o600
    ok, reason = assert_hardened(f)
    assert ok is True and reason == ""


@pytest.mark.skipif(not (_IS_WIN and _HAS_PYWIN32), reason="needs Windows + pywin32")
def test_assert_hardened_windows_roundtrip(tmp_path) -> None:
    f = tmp_path / "jwt_secret"
    f.write_text("s3cret")
    harden(f)
    ok, reason = assert_hardened(f)
    assert ok is True, reason


@pytest.mark.skipif(not (_IS_WIN and not _HAS_PYWIN32), reason="Windows without pywin32 only")
def test_assert_hardened_windows_without_pywin32_uses_native_apis(tmp_path) -> None:
    f = tmp_path / "jwt_secret"
    f.write_text("s3cret")
    harden(f)
    ok, reason = assert_hardened(f)
    assert ok is True, reason


def test_failed_hardening_preserves_the_existing_secret(tmp_path, monkeypatch) -> None:
    secret = tmp_path / "jwt_secret"
    secret.write_text("old-secret", encoding="utf-8")
    secret.chmod(0o600)
    monkeypatch.setattr(secure_file, "harden", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("ACL")))

    with pytest.raises(OSError, match="ACL"):
        write_secret_text(secret, "new-secret")

    assert secret.read_text(encoding="utf-8") == "old-secret"
    assert list(tmp_path.glob(".jwt_secret.*.tmp")) == []


def test_secret_write_retries_until_every_byte_is_written(tmp_path, monkeypatch) -> None:
    secret = tmp_path / "jwt_secret"
    real_write = os.write
    calls = 0

    def short_write(descriptor: int, data: bytes | memoryview) -> int:
        nonlocal calls
        calls += 1
        chunk = data[: max(1, len(data) // 2)]
        return real_write(descriptor, chunk)

    monkeypatch.setattr(os, "write", short_write)

    write_secret_text(secret, "complete-secret-value")

    assert calls > 1
    assert secret.read_text(encoding="utf-8") == "complete-secret-value"


def test_secret_temp_is_hardened_before_the_first_secret_byte(tmp_path, monkeypatch) -> None:
    secret = tmp_path / "jwt_secret"
    events: list[str] = []
    real_harden = secure_file.harden
    real_write = os.write

    def record_harden(path, user=None):  # type: ignore[no-untyped-def]
        events.append("harden")
        return real_harden(path, user=user)

    def record_write(descriptor: int, data: bytes | memoryview) -> int:
        events.append("write")
        return real_write(descriptor, data)

    monkeypatch.setattr(secure_file, "harden", record_harden)
    monkeypatch.setattr(os, "write", record_write)

    write_secret_text(secret, "secret-value")

    assert events[0:2] == ["harden", "write"]


def test_windows_replace_uses_the_write_through_primitive(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.write_text("new", encoding="utf-8")
    destination.write_text("old", encoding="utf-8")
    real_replace = os.replace
    calls: list[tuple[object, object]] = []

    monkeypatch.setattr(secure_file, "_is_windows", lambda: True)

    def replace_write_through(left, right):  # type: ignore[no-untyped-def]
        calls.append((left, right))
        real_replace(left, right)

    monkeypatch.setattr(secure_file, "_windows_replace_write_through", replace_write_through)

    secure_file.durable_replace(source, destination)

    assert calls == [(source, destination)]
    assert destination.read_text(encoding="utf-8") == "new"


def test_windows_unlink_recovers_a_write_through_tombstone(tmp_path, monkeypatch) -> None:
    secret = tmp_path / "secret"
    secret.write_text("credential", encoding="utf-8")
    real_replace = os.replace
    delete_attempts = 0

    monkeypatch.setattr(secure_file, "_is_windows", lambda: True)
    monkeypatch.setattr(secure_file, "_windows_replace_write_through", real_replace)

    def delete_tombstone(path):  # type: ignore[no-untyped-def]
        nonlocal delete_attempts
        delete_attempts += 1
        if delete_attempts == 1:
            raise PermissionError("scanner holds tombstone")
        path.unlink()

    monkeypatch.setattr(secure_file, "_windows_delete_file", delete_tombstone)

    with pytest.raises(secure_file.PendingDurableUnlinkError):
        secure_file.durable_unlink(secret)

    tombstone = secure_file.pending_unlink_path(secret)
    assert secret.exists() is False
    assert tombstone.read_text(encoding="utf-8") == "credential"

    secure_file.durable_unlink(secret)

    assert tombstone.exists() is False


@pytest.mark.skipif(not (_IS_WIN and _HAS_PYWIN32), reason="needs Windows + pywin32")
def test_harden_replaces_unrelated_explicit_windows_aces(tmp_path) -> None:
    import ntsecuritycon
    import win32security

    secret = tmp_path / "jwt_secret"
    secret.write_text("s3cret", encoding="utf-8")
    everyone_sid = win32security.CreateWellKnownSid(win32security.WinWorldSid)
    broad_dacl = win32security.ACL()
    broad_dacl.AddAccessAllowedAce(win32security.ACL_REVISION, ntsecuritycon.FILE_ALL_ACCESS, everyone_sid)
    win32security.SetNamedSecurityInfo(
        str(secret),
        win32security.SE_FILE_OBJECT,
        win32security.DACL_SECURITY_INFORMATION | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
        None,
        None,
        broad_dacl,
        None,
    )

    harden(secret)

    descriptor = win32security.GetFileSecurity(str(secret), win32security.DACL_SECURITY_INFORMATION)
    dacl = descriptor.GetSecurityDescriptorDacl()
    actual_sids = {dacl.GetAce(index)[2] for index in range(dacl.GetAceCount())}
    assert everyone_sid not in actual_sids
    assert len(actual_sids) == 2


@pytest.mark.parametrize(
    "operation",
    [
        secure_file.validate_owner_owned_regular_file,
        secure_file.digest_owner_owned_regular_file,
    ],
)
def test_streaming_file_apis_reject_symlinks(tmp_path, operation) -> None:  # type: ignore[no-untyped-def]
    source = tmp_path / "source"
    source.write_bytes(b"payload")
    source.chmod(0o600)
    link = tmp_path / "link"
    link.symlink_to(source)

    with pytest.raises(OSError, match="unsafe"):
        operation(link, require_hardened=True)


@pytest.mark.skipif(_IS_WIN, reason="POSIX hard-link and mode semantics")
@pytest.mark.parametrize(
    "operation",
    [
        secure_file.validate_owner_owned_regular_file,
        secure_file.digest_owner_owned_regular_file,
    ],
)
def test_streaming_file_apis_reject_hardlinks_and_broad_mode(tmp_path, operation) -> None:  # type: ignore[no-untyped-def]
    source = tmp_path / "source"
    source.write_bytes(b"payload")
    source.chmod(0o600)
    os.link(source, tmp_path / "other-name")
    with pytest.raises(OSError, match="unsafe"):
        operation(source, require_hardened=True)

    source.unlink()
    broad = tmp_path / "broad"
    broad.write_bytes(b"payload")
    broad.chmod(0o640)
    with pytest.raises(secure_file.InsecureFilePermissionsError):
        operation(broad, require_hardened=True)


def test_validate_owner_owned_regular_file_detects_open_path_replacement(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source"
    source.write_bytes(b"original")
    source.chmod(0o600)
    replacement = tmp_path / "replacement"
    replacement.write_bytes(b"replacement")
    replacement.chmod(0o600)
    real_open = secure_file.os.open
    swapped = False

    def swapping_open(path, flags, *args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal swapped
        if Path(path) == source and not swapped:
            swapped = True
            os.replace(replacement, source)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(secure_file.os, "open", swapping_open)

    with pytest.raises(OSError, match="changed"):
        secure_file.validate_owner_owned_regular_file(source, require_hardened=True)
    assert swapped is True


def test_digest_owner_owned_regular_file_detects_read_path_replacement(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source"
    source.write_bytes(b"original")
    source.chmod(0o600)
    replacement = tmp_path / "replacement"
    replacement.write_bytes(b"replacement")
    replacement.chmod(0o600)
    real_read = secure_file.os.read
    swapped = False

    def swapping_read(descriptor: int, count: int) -> bytes:
        nonlocal swapped
        payload = real_read(descriptor, count)
        if not swapped:
            swapped = True
            os.replace(replacement, source)
        return payload

    monkeypatch.setattr(secure_file.os, "read", swapping_read)

    with pytest.raises(OSError, match="changed"):
        secure_file.digest_owner_owned_regular_file(source, require_hardened=True)
    assert swapped is True


def test_digest_owner_owned_regular_file_detects_in_place_change_during_stream(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source"
    source.write_bytes(b"A" * ((1 << 20) + 1))
    source.chmod(0o600)
    real_read = secure_file.os.read
    mutated = False

    def mutating_read(descriptor: int, count: int) -> bytes:
        nonlocal mutated
        payload = real_read(descriptor, count)
        if payload and not mutated:
            mutated = True
            with source.open("r+b") as writer:
                writer.seek(-1, os.SEEK_END)
                writer.write(b"B")
                writer.flush()
                os.fsync(writer.fileno())
        return payload

    monkeypatch.setattr(secure_file.os, "read", mutating_read)

    with pytest.raises(OSError, match="changed"):
        secure_file.digest_owner_owned_regular_file(source, require_hardened=True)
    assert mutated is True


def test_durable_owner_copy_cleans_failed_candidate(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "candidate"
    source.write_bytes(b"payload")
    source.chmod(0o600)
    real_write = secure_file.os.write

    def fail_destination_write(descriptor: int, payload: bytes | memoryview) -> int:
        if os.fstat(descriptor).st_ino != source.stat().st_ino:
            raise OSError("injected write failure")
        return real_write(descriptor, payload)

    monkeypatch.setattr(secure_file.os, "write", fail_destination_write)

    with pytest.raises(OSError, match="injected write failure"):
        secure_file.copy_owner_owned_file_durable(source, destination)
    assert not destination.exists()


@pytest.mark.skipif(_IS_WIN, reason="POSIX descriptor-mode ordering")
def test_durable_owner_copy_hardens_then_writes_then_fsyncs(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "candidate"
    source.write_bytes(b"payload")
    source.chmod(0o600)
    events: list[str] = []
    real_fchmod = secure_file.os.fchmod
    real_write = secure_file.os.write
    real_fsync = secure_file.os.fsync

    def record_fchmod(descriptor: int, mode: int) -> None:
        events.append("harden")
        real_fchmod(descriptor, mode)

    def record_write(descriptor: int, payload: bytes | memoryview) -> int:
        events.append("write")
        return real_write(descriptor, payload)

    def record_fsync(descriptor: int) -> None:
        events.append("fsync")
        real_fsync(descriptor)

    monkeypatch.setattr(secure_file.os, "fchmod", record_fchmod)
    monkeypatch.setattr(secure_file.os, "write", record_write)
    monkeypatch.setattr(secure_file.os, "fsync", record_fsync)

    secure_file.copy_owner_owned_file_durable(source, destination)

    assert events.index("harden") < events.index("write") < events.index("fsync")
    assert destination.read_bytes() == b"payload"


@pytest.mark.skipif(_IS_WIN, reason="mocked Windows descriptor-DACL path runs on POSIX")
def test_windows_durable_owner_copy_installs_descriptor_dacl_before_write(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "candidate"
    source.write_bytes(b"payload")
    source.chmod(0o600)
    events: list[str] = []
    real_write = secure_file.os.write

    monkeypatch.setattr(secure_file, "_is_windows", lambda: True)

    def record_reopen(descriptor: int, **kwargs) -> int:  # type: ignore[no-untyped-def]
        if kwargs.get("write_dacl"):
            events.append("reopen-write-dacl")
        return descriptor

    monkeypatch.setattr(secure_file, "_reopen_windows_descriptor_for_security", record_reopen)
    monkeypatch.setattr(secure_file, "_assert_current_user_owns", lambda *_args: None)
    monkeypatch.setattr(secure_file, "_assert_hardened_descriptor", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        secure_file,
        "_install_exact_windows_descriptor_dacl",
        lambda _descriptor: events.append("dacl"),
    )

    def record_write(descriptor: int, payload: bytes | memoryview) -> int:
        events.append("write")
        return real_write(descriptor, payload)

    monkeypatch.setattr(secure_file.os, "write", record_write)

    secure_file.copy_owner_owned_file_durable(source, destination)

    assert events.index("reopen-write-dacl") < events.index("dacl") < events.index("write")
