"""Webhook DEK crypto tests (data-layer §7.2 / §7.5; Security C4 + H14)."""

from __future__ import annotations

import pytest
from cryptography.exceptions import InvalidTag

from flinttrade_webhooks.webhook_keys import (
    decrypt_webhook_secret,
    derive_webhook_dek,
    encrypt_webhook_secret,
    rotate_webhook_secret,
)

MASTER_DEK = b"\x11" * 32
WEBHOOK_A = "11111111-1111-1111-1111-111111111111"
WEBHOOK_B = "22222222-2222-2222-2222-222222222222"


def test_round_trip_recovers_plaintext() -> None:
    secret = b"super-secret-signing-key"
    blob = encrypt_webhook_secret(secret, WEBHOOK_A, MASTER_DEK)
    assert decrypt_webhook_secret(blob, WEBHOOK_A, MASTER_DEK) == secret


def test_ciphertext_is_not_plaintext() -> None:
    secret = b"super-secret-signing-key"
    blob = encrypt_webhook_secret(secret, WEBHOOK_A, MASTER_DEK)
    assert secret not in blob


def test_dek_swap_attack_fails() -> None:
    """Ciphertext for webhook A must not decrypt under webhook B's identity."""
    blob = encrypt_webhook_secret(b"secret", WEBHOOK_A, MASTER_DEK)
    with pytest.raises(InvalidTag):
        decrypt_webhook_secret(blob, WEBHOOK_B, MASTER_DEK)


def test_dek_key_version_swap_fails() -> None:
    """Security H14: a v1 ciphertext must not decrypt with the v2 key_version."""
    blob = encrypt_webhook_secret(b"secret", WEBHOOK_A, MASTER_DEK, key_version=1)
    with pytest.raises(InvalidTag):
        decrypt_webhook_secret(blob, WEBHOOK_A, MASTER_DEK, key_version=2)


def test_wrong_master_dek_fails() -> None:
    blob = encrypt_webhook_secret(b"secret", WEBHOOK_A, MASTER_DEK)
    with pytest.raises(InvalidTag):
        decrypt_webhook_secret(blob, WEBHOOK_A, b"\x22" * 32)


def test_dek_rotation_round_trip() -> None:
    """Encrypt with v1 DEK, rotate master password, re-encrypt → plaintext recovered."""
    secret = b"rotate-me"
    old_dek = MASTER_DEK
    new_dek = b"\x33" * 32
    blob_v1 = encrypt_webhook_secret(secret, WEBHOOK_A, old_dek, key_version=1)

    new_blob, new_version = rotate_webhook_secret(
        blob_v1, WEBHOOK_A, old_dek, new_dek, old_key_version=1
    )
    assert new_version == 2
    assert decrypt_webhook_secret(new_blob, WEBHOOK_A, new_dek, key_version=2) == secret
    # the old blob must NOT decrypt under the new DEK/version
    with pytest.raises(InvalidTag):
        decrypt_webhook_secret(blob_v1, WEBHOOK_A, new_dek, key_version=2)


def test_derive_is_deterministic_and_distinct() -> None:
    k1 = derive_webhook_dek(MASTER_DEK, WEBHOOK_A, 1)
    assert k1 == derive_webhook_dek(MASTER_DEK, WEBHOOK_A, 1)  # deterministic
    assert k1 != derive_webhook_dek(MASTER_DEK, WEBHOOK_B, 1)  # per-webhook
    assert k1 != derive_webhook_dek(MASTER_DEK, WEBHOOK_A, 2)  # per-version
    assert len(k1) == 32


def test_nonce_is_random_per_encryption() -> None:
    secret = b"secret"
    b1 = encrypt_webhook_secret(secret, WEBHOOK_A, MASTER_DEK)
    b2 = encrypt_webhook_secret(secret, WEBHOOK_A, MASTER_DEK)
    assert b1[:12] != b2[:12]  # fresh nonce each time
    # both still decrypt to the same plaintext
    assert decrypt_webhook_secret(b1, WEBHOOK_A, MASTER_DEK) == secret
    assert decrypt_webhook_secret(b2, WEBHOOK_A, MASTER_DEK) == secret
