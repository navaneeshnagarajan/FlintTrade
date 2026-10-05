"""Journal boot retains explicit availability after a local storage failure."""

from unittest.mock import MagicMock

from flinttrade_core.app import create_flask_app
from flinttrade_core.auth_routes import _create_token


def test_failed_journal_initialisation_keeps_routes_registered(tmp_path, monkeypatch):
    import flinttrade_journal.journal_routes as routes
    import flinttrade_journal.trade_journal as journal

    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setattr(routes, "_journal", None)
    monkeypatch.setattr(
        journal.TradeJournal, "initialise", MagicMock(side_effect=RuntimeError("local storage unavailable"))
    )
    app = create_flask_app()
    assert app.config["JOURNAL"] is None
    assert "journal" in app.blueprints
    with app.app_context():
        token = _create_token("operator", mode="explore")
    with app.test_client() as client:
        for path in ("/api/v1/journal/entries", "/api/v1/journal/notes", "/api/v1/journal/stats"):
            assert client.get(path, headers={"Authorization": f"Bearer {token}"}).status_code == 503


def test_retired_integration_routes_are_absent(tmp_path, monkeypatch):
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    app = create_flask_app()
    paths = {rule.rule for rule in app.url_map.iter_rules()}
    assert not any(path.startswith(("/api/v1/flows", "/api/v1/voice", "/api/v1/integration/excel")) for path in paths)
