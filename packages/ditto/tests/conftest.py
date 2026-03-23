"""Pytest configuration for ditto tests.

Sets required environment variables before tests run so that
AccountManager can find DITTO_ENCRYPTION_KEY.
"""
from __future__ import annotations

import os

import pytest
from cryptography.fernet import Fernet

# A stable test-only key — never used in production
_TEST_FERNET_KEY = Fernet.generate_key().decode()


@pytest.fixture(autouse=True)
def set_ditto_encryption_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inject DITTO_ENCRYPTION_KEY for every ditto test."""
    monkeypatch.setenv("DITTO_ENCRYPTION_KEY", _TEST_FERNET_KEY)
