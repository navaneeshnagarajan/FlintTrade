"""secure_file ACL hardening tests (supply-chain §13; SC-04 / HI18).

Full Windows DACL verification needs pywin32 (present on CI's windows-latest);
where it is absent the assert_hardened Windows path degrades gracefully, so
those assertions are skipped. harden() itself (icacls) is exercised everywhere.
"""

from __future__ import annotations

import sys

import pytest

from flinttrade_core.secure_file import assert_hardened, harden, startup_check

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
def test_assert_hardened_windows_without_pywin32_degrades(tmp_path) -> None:
    f = tmp_path / "jwt_secret"
    f.write_text("s3cret")
    harden(f)
    ok, reason = assert_hardened(f)
    assert ok is False and "pywin32" in reason
