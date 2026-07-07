"""Small helpers for keeping broker identifiers out of runtime logs."""

from __future__ import annotations

import hmac
import logging
import secrets
from hashlib import sha256
from pathlib import Path

_logger = logging.getLogger("flinttrade.gateway.log_safety")

# Per-install random key for the log-ref HMAC. A plain unsalted hash of a
# short identifier (client codes, account ids) is brute-forceable from logs;
# keying the digest with install-local secret material makes the refs stable
# per install and non-reversible without the key file.
_SALT_FILENAME = "log_ref_salt"
_salt: bytes | None = None


def _load_salt() -> bytes:
    global _salt  # noqa: PLW0603
    if _salt is not None:
        return _salt
    try:
        from flinttrade_core.workspace import workspace_dir  # noqa: PLC0415

        path = Path(workspace_dir()) / _SALT_FILENAME
        if path.exists():
            _salt = path.read_bytes()
        else:
            _salt = secrets.token_bytes(32)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(_salt)
            try:
                path.chmod(0o600)
            except OSError:  # pragma: no cover - platform-specific
                pass
    except Exception:  # pragma: no cover - unwritable workspace
        # Ephemeral per-process salt: refs stay non-reversible, only their
        # cross-restart stability is lost.
        _logger.debug("log_ref salt not persistable; using process-local salt")
        _salt = secrets.token_bytes(32)
    return _salt


def log_ref(value: object, *, kind: str = "id") -> str:
    """Return a stable non-reversible reference for a sensitive identifier."""
    raw = str(value or "").strip()
    if not raw:
        return f"{kind}#[empty]"
    digest = hmac.new(_load_salt(), raw.encode("utf-8"), sha256).hexdigest()[:10]
    return f"{kind}#{digest}"


def account_ref(account_id: object) -> str:
    """Stable log-safe reference for a broker account identifier."""
    return log_ref(account_id, kind="account")


def selector_ref(adapter_id: object, account_id: object) -> str:
    """Stable log-safe reference for a broker selector."""
    return f"{adapter_id}:{account_ref(account_id)}"
