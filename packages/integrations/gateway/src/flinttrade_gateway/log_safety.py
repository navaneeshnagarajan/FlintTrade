"""Small helpers for keeping broker identifiers out of runtime logs."""

from __future__ import annotations

import hashlib


def log_ref(value: object, *, kind: str = "id") -> str:
    """Return a stable non-reversible reference for a sensitive identifier."""
    raw = str(value or "").strip()
    if not raw:
        return f"{kind}#[empty]"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:10]
    return f"{kind}#{digest}"


def account_ref(account_id: object) -> str:
    """Stable log-safe reference for a broker account identifier."""
    return log_ref(account_id, kind="account")


def selector_ref(adapter_id: object, account_id: object) -> str:
    """Stable log-safe reference for a broker selector."""
    return f"{adapter_id}:{account_ref(account_id)}"
