"""Harden secret-file ACLs to current-user-only (supply-chain §13.2; HI18).

flinttrade secrets (``master_password``, ``api_key_pepper``, ``jwt_secret``,
``totp_install_key``, ``credentials.db``) are written ``chmod(0o600)`` on POSIX,
which Windows silently ignores — so on Windows they inherit the parent dir DACL
(typically Users + SYSTEM + Administrators, all full control). :func:`harden`
calls ``icacls /inheritance:r /grant:r`` so only the owner (plus SYSTEM, for OS
operations — Security H5) can read them. POSIX falls back to ``chmod 0o600``.
"""

from __future__ import annotations

import getpass
import pathlib
import subprocess
import sys

SENSITIVE_PATTERNS = (
    "*master*", "*pepper*", "*secret*", "*jwt*", "*credentials*", "*.db",
)


def harden(path: pathlib.Path, user: str | None = None) -> None:
    """Restrict *path* to owner-only (+ SYSTEM on Windows). Idempotent.

    Security H5: SYSTEM:F is granted alongside ``<user>:F`` so OS-level
    operations (Defender scans, Backup, VSS, crash dumps) keep working;
    Administrators are intentionally NOT granted for secret files.
    """
    path = pathlib.Path(path)
    if sys.platform != "win32":
        path.chmod(0o600)
        return
    user = user or getpass.getuser()
    result = subprocess.run(
        ["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:F", "SYSTEM:F"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        # Security L1: icacls echoes the full target path in its output; redact the
        # absolute path + parent dir so the error never leaks the home-dir layout.
        detail = (result.stdout + result.stderr).replace(str(path), path.name)
        detail = detail.replace(str(path.parent), "<dir>").strip()
        raise OSError(
            f"icacls failed for {path.name}: returncode={result.returncode}: {detail}"
        )


def assert_hardened(path: pathlib.Path, user: str | None = None) -> tuple[bool, str]:
    """Return ``(is_hardened, reason)``. Owner + SYSTEM are the only allowed ACEs."""
    path = pathlib.Path(path)
    if sys.platform != "win32":
        st = path.stat()
        too_broad = (st.st_mode & 0o077) != 0
        return (not too_broad, "" if not too_broad else f"mode is {oct(st.st_mode)}")
    try:
        import win32security  # pinned via pywin32 in requirements.lock
    except ImportError:
        return False, "pywin32 not installed; cannot verify Windows ACL"
    user = user or getpass.getuser()
    sd = win32security.GetFileSecurity(str(path), win32security.DACL_SECURITY_INFORMATION)
    dacl = sd.GetSecurityDescriptorDacl()
    if dacl is None:
        return False, "no DACL (file accessible to everyone)"
    user_sid, _, _ = win32security.LookupAccountName(None, user)
    system_sid, _, _ = win32security.LookupAccountName(None, "SYSTEM")
    allowed_sids = {user_sid, system_sid}
    for i in range(dacl.GetAceCount()):
        ace = dacl.GetAce(i)
        sid = ace[2]
        if sid not in allowed_sids:
            return False, (
                f"DACL contains ACE for non-allowlisted SID: "
                f"{win32security.LookupAccountSid(None, sid)}"
            )
    return True, ""


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
