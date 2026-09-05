"""secure_file ACL hardening tests (supply-chain §13; SC-04 / HI18)."""

from __future__ import annotations

import os
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
