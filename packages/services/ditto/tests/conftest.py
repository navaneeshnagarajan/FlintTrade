"""Isolated lifecycle configuration for native copy-account metadata tests."""

from __future__ import annotations

import pytest


@pytest.fixture
def backend_lease_factory(monkeypatch):
    """Explicit real ownership acquired after the test selects its workspace."""
    from flinttrade_core.backend_instance import acquire_backend_instance_lease
    from flinttrade_core.workspace import workspace_dir

    leases = {}

    def acquire():
        path = workspace_dir().resolve()
        if path not in leases:
            leases[path] = acquire_backend_instance_lease()
        return leases[path].proof

    try:
        yield acquire
    finally:
        monkeypatch.undo()
        for lease in leases.values():
            lease.release()


@pytest.fixture(autouse=True)
def _isolated_installation_state(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    """Keep every Ditto constructor/fence away from real installation state."""
    monkeypatch.setenv("FLINTTRADE_INSTALLATION_STATE_DIR", str(tmp_path / "installation-state"))
