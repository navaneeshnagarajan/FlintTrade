"""Pytest configuration for ditto tests.

Ditto account api_keys are stored in the canonical credential vault
(:class:`flinttrade_gateway.credentials.CredentialStore`); tests pass a
``master_password`` (or an injected store) to ``AccountManager`` directly, so no
process-wide encryption key is set here.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolated_installation_state(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    """Keep every Ditto constructor/fence away from real installation state."""
    monkeypatch.setenv("FLINTTRADE_INSTALLATION_STATE_DIR", str(tmp_path / "installation-state"))
