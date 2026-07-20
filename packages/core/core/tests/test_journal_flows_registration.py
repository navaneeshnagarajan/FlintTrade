"""Boot-failure honesty for the journal + flows registration blocks.

Pins review finding 11 (localStorage-migration): ``app.register_blueprint``
must sit OUTSIDE the try that constructs each store, so a failed store
construction leaves the routes registered and every request answers the
routes' own 503 branch ("… not initialised") — never a bare 404 the frontend
cannot distinguish from a route typo.
"""

from __future__ import annotations

from typing import Any, NoReturn

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture()
def workspace(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Isolated workspace + loopback auth (no API key configured)."""
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.delenv("FLINTTRADE_API_KEY", raising=False)
    monkeypatch.delenv("OPENALGO_API_KEY", raising=False)
    master_password = tmp_path / "master_password"
    master_password.write_text("journal-flows-registration-test-password", encoding="utf-8")
    master_password.chmod(0o600)
    return tmp_path


def test_failed_store_construction_yields_503_not_404(
    workspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Journal + flows blueprints answer 503 when their store fails to build."""
    import flinttrade_journal.journal_routes as journal_routes
    import flinttrade_journal.trade_journal as trade_journal
    import flinttrade_webhooks.flow_routes as flow_routes
    import flinttrade_webhooks.flow_store as flow_store

    # Simulate a fresh process where boot-time construction fails: the module
    # singletons start unset and both stores raise during construction.
    monkeypatch.setattr(journal_routes, "_journal", None)
    monkeypatch.setattr(flow_routes, "_store", None)

    def _boom(self: Any, *args: Any, **kwargs: Any) -> NoReturn:
        raise RuntimeError("store construction failed (simulated)")

    monkeypatch.setattr(trade_journal.TradeJournal, "initialise", _boom)
    monkeypatch.setattr(flow_store.FlowFileStore, "__init__", _boom)

    from flinttrade_core.app import create_flask_app

    app = create_flask_app()

    # The except branches ran: config keys are None, yet the blueprints exist.
    assert app.config["JOURNAL"] is None
    assert app.config["FLOW_STORE"] is None
    assert "journal" in app.blueprints
    assert "flows" in app.blueprints

    with app.test_client() as client:
        for path in ("/api/v1/journal/entries", "/api/v1/journal/notes", "/api/v1/journal/stats"):
            resp = client.get(path)
            assert resp.status_code == 503, f"{path} -> {resp.status_code}"
            assert resp.get_json()["status"] == "error"
        for path in ("/api/v1/flows", "/api/v1/flows/flow_1"):
            resp = client.get(path)
            assert resp.status_code == 503, f"{path} -> {resp.status_code}"
            assert resp.get_json()["status"] == "error"


def test_healthy_boot_still_registers_and_serves_both_surfaces(
    workspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Control: with working stores the same routes answer 200, not 503."""
    import flinttrade_journal.journal_routes as journal_routes
    import flinttrade_webhooks.flow_routes as flow_routes

    monkeypatch.setattr(journal_routes, "_journal", None)
    monkeypatch.setattr(flow_routes, "_store", None)

    from flinttrade_core.app import create_flask_app

    app = create_flask_app()

    assert app.config["JOURNAL"] is not None
    assert app.config["FLOW_STORE"] is not None

    with app.test_client() as client:
        assert client.get("/api/v1/journal/entries").status_code == 200
        assert client.get("/api/v1/flows").status_code == 200
