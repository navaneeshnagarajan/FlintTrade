"""Shared webhook HMAC verification helpers."""

from __future__ import annotations

import hashlib
import hmac


def verify_hmac_sha256_signature(
    payload: bytes,
    signature: str,
    secret: str,
    *,
    skip_verification: bool = False,
) -> bool:
    """Verify a SHA-256 HMAC signature with fail-closed defaults.

    Args:
        payload: Raw request body bytes.
        signature: Signature header value, either ``sha256=<hex>`` or ``<hex>``.
        secret: Shared signing secret.
        skip_verification: Explicit opt-out for local tests or intentionally
            unsigned legacy flows. When ``False`` and ``secret`` is empty, the
            request is rejected.

    Returns:
        ``True`` when verification succeeds or is explicitly skipped.
    """
    if not secret:
        return bool(skip_verification)
    if not signature:
        return False

    sig_hex = signature.strip().removeprefix("sha256=")
    expected = hmac.new(
        secret.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, sig_hex)
