"""Windows secret-file ACL hardening contract (HI18 / Security H5; sub-spec §13.3)."""

from __future__ import annotations

import sys

import pytest

from flinttrade_core.secure_file import assert_hardened, harden, startup_check

IS_WIN = sys.platform == "win32"

try:  # pragma: no cover - availability differs per runner
    import win32security  # noqa: F401

    HAS_PYWIN32 = True
except ImportError:
    HAS_PYWIN32 = False

posix_only = pytest.mark.skipif(IS_WIN, reason="POSIX mode-bit semantics")
win_dacl = pytest.mark.skipif(
    not (IS_WIN and HAS_PYWIN32), reason="needs Windows + pywin32 for DACL inspection"
)
windows_only = pytest.mark.skipif(not IS_WIN, reason="Windows DACL semantics")


# --------------------------------------------------------------------------
# Cross-platform behaviour
# --------------------------------------------------------------------------
def test_idempotent_double_harden(tmp_path):
    f = tmp_path / "master_password"
    f.write_text("secret", encoding="utf-8")
    harden(f)
    harden(f)  # second call must be a no-op, no error


def test_harden_raises_on_missing_file(tmp_path):
    missing = tmp_path / "does_not_exist_secret"
    with pytest.raises(OSError) as exc:
        harden(missing)
    if IS_WIN:
        # Security L1: the Windows error message names only the file, not the home layout.
        assert missing.name in str(exc.value)
        assert str(tmp_path) not in str(exc.value)


# --------------------------------------------------------------------------
# POSIX mode-bit path
# --------------------------------------------------------------------------
@posix_only
def test_harden_sets_owner_only_mode(tmp_path):
    f = tmp_path / "jwt_secret"
    f.write_text("k", encoding="utf-8")
    harden(f)
    ok, reason = assert_hardened(f)
    assert ok, reason
    assert (f.stat().st_mode & 0o077) == 0


@posix_only
def test_assert_hardened_detects_world_readable(tmp_path):
    f = tmp_path / "credentials.db"
    f.write_text("x", encoding="utf-8")
    f.chmod(0o644)
    ok, reason = assert_hardened(f)
    assert ok is False
    assert reason


@posix_only
def test_startup_check_flags_unhardened_secrets(tmp_path):
    (tmp_path / "master_password").write_text("p", encoding="utf-8")
    (tmp_path / "credentials.db").write_text("d", encoding="utf-8")
    for p in tmp_path.iterdir():
        p.chmod(0o644)
    flagged = startup_check(tmp_path)
    assert len(flagged) == 2


@posix_only
def test_startup_check_reports_filenames_not_paths(tmp_path):
    secret = tmp_path / "jwt_secret"
    secret.write_text("k", encoding="utf-8")
    secret.chmod(0o644)
    flagged = startup_check(tmp_path)
    assert flagged
    for entry in flagged:
        assert entry.startswith(secret.name)
        assert str(tmp_path) not in entry  # Security L1: no parent-dir leakage


# --------------------------------------------------------------------------
# Windows DACL path (pywin32 required)
# --------------------------------------------------------------------------
def _dacl_sids(path):
    sd = win32security.GetFileSecurity(str(path), win32security.DACL_SECURITY_INFORMATION)
    dacl = sd.GetSecurityDescriptorDacl()
    return [dacl.GetAce(i)[2] for i in range(dacl.GetAceCount())]


@win_dacl
def test_harden_makes_owner_plus_system_dacl(tmp_path):
    import getpass

    f = tmp_path / "master_password"
    f.write_text("secret", encoding="utf-8")
    harden(f)
    ok, reason = assert_hardened(f)
    assert ok, reason
    sids = set(_dacl_sids(f))
    user_sid, _, _ = win32security.LookupAccountName(None, getpass.getuser())
    system_sid, _, _ = win32security.LookupAccountName(None, "SYSTEM")
    assert sids == {user_sid, system_sid}


@win_dacl
def test_harden_removes_administrators_ace(tmp_path):
    import subprocess

    f = tmp_path / "api_key_pepper"
    f.write_text("p", encoding="utf-8")
    subprocess.run(["icacls", str(f), "/grant", "Administrators:F"], check=True,
                   capture_output=True, text=True)
    harden(f)
    admins_sid, _, _ = win32security.LookupAccountName(None, "Administrators")
    assert admins_sid not in set(_dacl_sids(f))  # Security H5 regression guard


@win_dacl
def test_harden_preserves_system_for_defender(tmp_path):
    f = tmp_path / "credentials.db"
    f.write_text("d", encoding="utf-8")
    harden(f)
    system_sid, _, _ = win32security.LookupAccountName(None, "SYSTEM")
    assert system_sid in set(_dacl_sids(f))  # OS-level ops must keep working


@windows_only
def test_assert_hardened_accepts_system_ace_rejects_administrators(tmp_path):
    import subprocess

    f = tmp_path / "totp_secret"
    f.write_text("t", encoding="utf-8")
    harden(f)
    assert assert_hardened(f)[0] is True
    subprocess.run(["icacls", str(f), "/grant", "Administrators:F"], check=True,
                   capture_output=True, text=True)
    assert assert_hardened(f)[0] is False


@windows_only
@pytest.mark.unit
def test_hardening_a_directory_keeps_existing_children_accessible(tmp_path):
    """Regression: protected flag-less directory ACEs stripped every pre-existing child's DACL.

    Setting a protected DACL on a directory makes Windows recalculate
    inheritance on the children. A child created before the harden (whose DACL
    was purely inherited from the ordinary parent chain) was left with an
    EMPTY DACL — denied to everyone including its owner. That single defect
    made ``workspace.json`` unreadable after the Ollama runtime hardened the
    workspace root, failing hundreds of Windows tests. Directory ACEs now
    carry OBJECT_INHERIT|CONTAINER_INHERIT, so existing children keep
    inherited owner + SYSTEM access.
    """
    from flinttrade_core.secure_file import harden_directory

    child = tmp_path / "existing.json"
    child.write_text("{}", encoding="utf-8")
    sub = tmp_path / "subdir"
    sub.mkdir()
    grandchild = sub / "nested.txt"
    grandchild.write_text("nested", encoding="utf-8")

    harden_directory(tmp_path)

    # Pre-existing children must stay readable and writable after the harden.
    assert child.read_text(encoding="utf-8") == "{}"
    child.write_text('{"ok": true}', encoding="utf-8")
    assert grandchild.read_text(encoding="utf-8") == "nested"

    # New children keep working too.
    fresh = tmp_path / "after.txt"
    fresh.write_text("x", encoding="utf-8")
    assert fresh.read_text(encoding="utf-8") == "x"

    # Re-hardening (the idempotent startup path) must not regress any of it.
    harden_directory(tmp_path)
    assert child.read_text(encoding="utf-8") == '{"ok": true}'


@windows_only
@pytest.mark.unit
def test_hardened_file_dacl_stays_strict_and_verifiable(tmp_path):
    """Files keep exact, non-inheritable protected DACLs after the directory fix."""
    f = tmp_path / "secret.key"
    f.write_text("s", encoding="utf-8")
    harden(f)
    ok, reason = assert_hardened(f)
    assert ok, reason
    # Hardening the parent directory afterwards must not disturb the file's
    # protected DACL or its verifiability.
    from flinttrade_core.secure_file import harden_directory

    harden_directory(tmp_path)
    ok, reason = assert_hardened(f)
    assert ok, reason
    assert f.read_text(encoding="utf-8") == "s"
