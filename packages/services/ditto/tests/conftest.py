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
def _isolated_local_state(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    """Give each test its own workspace and installation state.

    A package-only run never loads the repo-root conftest, so without this every
    xdist worker resolves the operator's workspace and contends for its backend
    lease.
    """
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path / "workspace"))
    monkeypatch.setenv("FLINTTRADE_INSTALLATION_STATE_DIR", str(tmp_path / "installation-state"))
