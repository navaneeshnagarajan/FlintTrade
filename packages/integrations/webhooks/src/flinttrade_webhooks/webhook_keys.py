"""Per-webhook secret encryption — HKDF-SHA256 DEK + AES-GCM-SIV (data-layer §7.2).

Each webhook's signing secret is stored encrypted at rest in
``auth_state.sqlite`` (``webhooks.secret_encrypted_aes_gcm_siv``). The data
encryption key (DEK) for a row is derived per-webhook from the operator's
master-password DEK via HKDF, bound to ``(webhook_id, key_version)`` through
the HKDF ``info`` parameter, and the ciphertext is additionally bound to the
same pair as AES-GCM-SIV associated data (Security H14). The combination
defeats two attack classes:

  - cross-webhook swap: row A's ciphertext pasted into row B fails to decrypt
    because B derives a different DEK *and* presents a different AAD.
  - silent rotation confusion: a v1 ciphertext cannot be decrypted with the v2
    DEK/AAD, so a partially-rotated table fails loud rather than silently
    returning the wrong plaintext.

AES-GCM-SIV is nonce-misuse-resistant, so a (rare) nonce repeat does not
catastrophically leak the key the way plain GCM would.
"""

from __future__ import annotations

import secrets

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCMSIV
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

# Versioned domain-separation salt. Bumping the suffix is a hard key-domain
# change (every webhook must be re-encrypted) — do NOT change casually.
_HKDF_SALT = b"flinttrade-webhook-v1"

# AES-GCM-SIV nonce length (bytes). Prepended to the ciphertext on disk.
_NONCE_LEN = 12


def derive_webhook_dek(
    master_password_dek: bytes,
    webhook_id: str,
    key_version: int = 1,
) -> bytes:
    """Per-webhook DEK derived from the master-password DEK + key_version.

    Binds the key to ``(webhook_id, key_version)`` via the HKDF ``info``
    parameter so cross-webhook swap attacks fail (different ``webhook_id`` →
    different DEK) and rotation produces a distinct key under the same
    ``webhook_id``.

    Args:
        master_password_dek: 32-byte DEK from ``auth_service._derive_dek()``
            (Argon2id of the operator's master password).
        webhook_id: UUID string from ``webhooks.webhook_id`` — immutable.
        key_version: rotation counter; ``1`` for fresh webhooks.

    Returns:
        32-byte AES-256 key for AES-GCM-SIV.
    """
    info_blob = f"{key_version}:{webhook_id}".encode()
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_HKDF_SALT,
        info=info_blob,
    ).derive(master_password_dek)


def _aad(webhook_id: str, key_version: int) -> bytes:
    """Associated data binds ciphertext to (key_version, webhook_id) (Security H14)."""
    return f"{key_version}:{webhook_id}".encode()


def encrypt_webhook_secret(
    secret: bytes,
    webhook_id: str,
    master_password_dek: bytes,
    key_version: int = 1,
) -> bytes:
    """Encrypt ``secret`` for one webhook. Returns ``nonce(12) || ciphertext``."""
    dek = derive_webhook_dek(master_password_dek, webhook_id, key_version)
    aesgcm = AESGCMSIV(dek)
    nonce = secrets.token_bytes(_NONCE_LEN)
    ciphertext = aesgcm.encrypt(nonce, secret, associated_data=_aad(webhook_id, key_version))
    return nonce + ciphertext


def decrypt_webhook_secret(
    blob: bytes,
    webhook_id: str,
    master_password_dek: bytes,
    key_version: int = 1,
) -> bytes:
    """Decrypt a ``nonce(12) || ciphertext`` blob.

    Raises ``cryptography.exceptions.InvalidTag`` if the blob was encrypted for
    a different ``(webhook_id, key_version)`` or with a different DEK.
    """
    dek = derive_webhook_dek(master_password_dek, webhook_id, key_version)
    aesgcm = AESGCMSIV(dek)
    nonce, ciphertext = blob[:_NONCE_LEN], blob[_NONCE_LEN:]
    return aesgcm.decrypt(nonce, ciphertext, associated_data=_aad(webhook_id, key_version))


def rotate_webhook_secret(
    blob: bytes,
    webhook_id: str,
    old_master_password_dek: bytes,
    new_master_password_dek: bytes,
    old_key_version: int,
) -> tuple[bytes, int]:
    """Re-encrypt one webhook secret under the next key_version (Security C4).

    Decrypts with the OLD ``(key_version, webhook_id)`` AAD + OLD DEK, then
    re-encrypts with ``key_version + 1`` + the NEW DEK. The plaintext secret
    never touches disk. Used by the master-password rotation routine, which
    iterates every ``webhooks`` row and UPDATEs ``secret_encrypted_aes_gcm_siv``,
    ``key_version``, and ``last_rotated_at`` in one transaction.

    Returns:
        ``(new_blob, new_key_version)``.
    """
    plaintext = decrypt_webhook_secret(blob, webhook_id, old_master_password_dek, old_key_version)
    new_key_version = old_key_version + 1
    new_blob = encrypt_webhook_secret(plaintext, webhook_id, new_master_password_dek, new_key_version)
    return new_blob, new_key_version
