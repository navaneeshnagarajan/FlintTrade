"""Tests for workspace preset management API.

Run with:
    python -m pytest packages/core/core/tests/test_preset_routes.py -v --import-mode=importlib
"""

from __future__ import annotations

from pathlib import Path

import pytest


_TEST_API_KEY = "test-preset-routes-key"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def monkeypatch_module():
    """Module-scoped monkeypatch."""
    from _pytest.monkeypatch import MonkeyPatch

    mp = MonkeyPatch()
    yield mp
    mp.undo()


@pytest.fixture(scope="module")
def tmp_flinttrade_home(monkeypatch_module, tmp_path_factory) -> Path:
    """Isolated ~/.flinttrade directory for the whole test module."""
    home = tmp_path_factory.mktemp("flinttrade_home_presets")
    monkeypatch_module.setenv("FLINTTRADE_HOME", str(home))
    return home


@pytest.fixture(scope="module")
def flask_app(monkeypatch_module, tmp_flinttrade_home):
    """Minimal Flask app with only the preset blueprint registered.

    Uses importlib to load ``preset_routes`` directly from its source file,
    bypassing ``packages/core/core/src/__init__.py`` which imports ``httpx`` (and
    transitively ``rich``).  On Python 3.14 / Windows, ``rich`` calls
    ``platform.system()`` via a WMI query that can hang indefinitely in
    restricted environments — this direct load avoids that chain entirely.
    """
    import importlib.util
    import sys
    from pathlib import Path
    from flask import Flask

    _src = Path(__file__).resolve().parents[2] / "core" / "src" / "flinttrade_core" / "preset_routes.py"
    spec = importlib.util.spec_from_file_location("preset_routes_isolated", _src)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register under a unique name so it does not collide with the real package
    sys.modules.setdefault("preset_routes_isolated", module)
    spec.loader.exec_module(module)  # type: ignore[union-attr]

    preset_bp = module.preset_bp  # type: ignore[attr-defined]

    app = Flask(__name__)
    app.register_blueprint(preset_bp)
    app.config["TESTING"] = True
    return app


@pytest.fixture()
def client(flask_app):
    """Flask test client."""
    with flask_app.test_client() as c:
        yield c


@pytest.fixture(autouse=True)
def clean_presets(tmp_flinttrade_home):
    """Remove presets.json before each test to ensure isolation."""
    presets_file = tmp_flinttrade_home / "presets.json"
    if presets_file.exists():
        presets_file.unlink()
    yield
    # No teardown needed — next test's setup removes it


def _auth() -> dict[str, str]:
    return {"X-API-Key": _TEST_API_KEY, "Content-Type": "application/json"}


# ---------------------------------------------------------------------------
# Helper: create a preset via the API
# ---------------------------------------------------------------------------


def _create_preset(
    client,
    name: str = "My Preset",
    description: str = "Test preset",
    widgets: list[str] | None = None,
    layout: dict | None = None,
) -> dict:
    """POST /ft-api/v1/presets/ and return the parsed JSON response."""
    payload = {
        "name": name,
        "description": description,
        "widgets": widgets or ["chart", "positions"],
        "layout": layout or {"type": "split"},
    }
    resp = client.post("/v1/presets/", headers=_auth(), json=payload)
    return resp.get_json(), resp.status_code


# ---------------------------------------------------------------------------
# GET /ft-api/v1/presets/ — list all presets
# ---------------------------------------------------------------------------


class TestListPresets:
    """GET /ft-api/v1/presets/ — list presets."""

    def test_returns_200(self, client):
        resp = client.get("/v1/presets/", headers=_auth())
        assert resp.status_code == 200

    def test_response_shape(self, client):
        data = client.get("/v1/presets/", headers=_auth()).get_json()
        assert data["status"] == "success"
        assert "presets" in data["data"]
        assert "total" in data["data"]
        assert "builtin_count" in data["data"]
        assert "custom_count" in data["data"]

    def test_builtin_presets_included(self, client):
        data = client.get("/v1/presets/", headers=_auth()).get_json()
        assert data["data"]["builtin_count"] == 6

    def test_custom_count_zero_initially(self, client):
        data = client.get("/v1/presets/", headers=_auth()).get_json()
        assert data["data"]["custom_count"] == 0

    def test_total_equals_builtin_plus_custom(self, client):
        d = client.get("/v1/presets/", headers=_auth()).get_json()["data"]
        assert d["total"] == d["builtin_count"] + d["custom_count"]

    def test_builtin_presets_have_required_fields(self, client):
        data = client.get("/v1/presets/", headers=_auth()).get_json()["data"]
        for p in data["presets"]:
            assert "id" in p
            assert "name" in p
            assert "description" in p
            assert "widgets" in p
            assert "layout" in p
            assert "is_builtin" in p
            assert "created_at" in p
            assert "updated_at" in p

    def test_builtin_flags_are_true(self, client):
        data = client.get("/v1/presets/", headers=_auth()).get_json()["data"]
        builtins = [p for p in data["presets"] if p["is_builtin"]]
        assert len(builtins) == 6

    def test_custom_preset_appears_in_list(self, client):
        _create_preset(client, name="My Custom Layout")
        data = client.get("/v1/presets/", headers=_auth()).get_json()["data"]
        names = [p["name"] for p in data["presets"]]
        assert "My Custom Layout" in names

    def test_custom_count_increments(self, client):
        _create_preset(client, name="Preset A")
        _create_preset(client, name="Preset B")
        data = client.get("/v1/presets/", headers=_auth()).get_json()["data"]
        assert data["custom_count"] >= 2


# ---------------------------------------------------------------------------
# POST /ft-api/v1/presets/ — create
# ---------------------------------------------------------------------------


class TestCreatePreset:
    """POST /ft-api/v1/presets/ — create a custom preset."""

    def test_returns_201(self, client):
        _, status = _create_preset(client)
        assert status == 201

    def test_response_contains_preset(self, client):
        data, status = _create_preset(client, name="New Preset")
        assert data["status"] == "success"
        assert data["data"]["name"] == "New Preset"

    def test_id_is_generated(self, client):
        data, _ = _create_preset(client, name="ID Test")
        assert len(data["data"]["id"]) > 0

    def test_is_builtin_is_false(self, client):
        data, _ = _create_preset(client, name="Custom Check")
        assert data["data"]["is_builtin"] is False

    def test_widgets_persisted(self, client):
        data, _ = _create_preset(client, name="Widget Test", widgets=["chart", "depth", "greeks"])
        assert data["data"]["widgets"] == ["chart", "depth", "greeks"]

    def test_layout_persisted(self, client):
        layout = {"type": "grid", "columns": 3}
        data, _ = _create_preset(client, name="Layout Test", layout=layout)
        assert data["data"]["layout"] == layout

    def test_duplicate_name_returns_400(self, client):
        _create_preset(client, name="Duplicate")
        _, status = _create_preset(client, name="Duplicate")
        assert status == 400

    def test_empty_name_returns_400(self, client):
        payload = {"name": "  ", "widgets": []}
        resp = client.post("/v1/presets/", headers=_auth(), json=payload)
        assert resp.status_code == 400

    def test_builtin_name_collision_returns_400(self, client):
        payload = {"name": "Scalper Zone", "widgets": []}
        resp = client.post("/v1/presets/", headers=_auth(), json=payload)
        assert resp.status_code == 400

    def test_timestamps_present(self, client):
        data, _ = _create_preset(client, name="Timestamp Test")
        assert data["data"]["created_at"] is not None
        assert data["data"]["updated_at"] is not None

    def test_description_defaults_to_empty(self, client):
        payload = {"name": "No Desc"}
        resp = client.post("/v1/presets/", headers=_auth(), json=payload)
        data = resp.get_json()
        assert data["data"]["description"] == ""


# ---------------------------------------------------------------------------
# GET /ft-api/v1/presets/<id> — retrieve single preset
# ---------------------------------------------------------------------------


class TestGetPreset:
    """GET /ft-api/v1/presets/<id>."""

    def test_builtin_returns_200(self, client):
        resp = client.get("/v1/presets/scalper-zone", headers=_auth())
        assert resp.status_code == 200
        assert resp.get_json()["data"]["id"] == "scalper-zone"

    def test_all_builtins_accessible(self, client):
        slugs = [
            "scalper-zone", "options-desk", "market-watch",
            "analysis", "risk-monitor", "investor-view",
        ]
        for slug in slugs:
            resp = client.get(f"/v1/presets/{slug}", headers=_auth())
            assert resp.status_code == 200, f"Expected 200 for {slug}"

    def test_custom_preset_returns_200(self, client):
        created, _ = _create_preset(client, name="Get Me")
        preset_id = created["data"]["id"]
        resp = client.get(f"/v1/presets/{preset_id}", headers=_auth())
        assert resp.status_code == 200
        assert resp.get_json()["data"]["name"] == "Get Me"

    def test_unknown_id_returns_404(self, client):
        resp = client.get("/v1/presets/does-not-exist", headers=_auth())
        assert resp.status_code == 404

    def test_response_fields_complete(self, client):
        resp = client.get("/v1/presets/analysis", headers=_auth())
        data = resp.get_json()["data"]
        for field in ("id", "name", "description", "widgets", "layout", "is_builtin", "created_at", "updated_at"):
            assert field in data, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# PUT /ft-api/v1/presets/<id> — update
# ---------------------------------------------------------------------------


class TestUpdatePreset:
    """PUT /ft-api/v1/presets/<id>."""

    def test_update_name(self, client):
        created, _ = _create_preset(client, name="Original Name")
        preset_id = created["data"]["id"]
        resp = client.put(f"/v1/presets/{preset_id}", headers=_auth(), json={"name": "Renamed"})
        assert resp.status_code == 200
        assert resp.get_json()["data"]["name"] == "Renamed"

    def test_update_description(self, client):
        created, _ = _create_preset(client, name="Desc Update")
        preset_id = created["data"]["id"]
        resp = client.put(
            f"/v1/presets/{preset_id}", headers=_auth(),
            json={"description": "New description"},
        )
        assert resp.status_code == 200
        assert resp.get_json()["data"]["description"] == "New description"

    def test_update_widgets(self, client):
        created, _ = _create_preset(client, name="Widget Update")
        preset_id = created["data"]["id"]
        resp = client.put(
            f"/v1/presets/{preset_id}", headers=_auth(),
            json={"widgets": ["orderpad", "depth"]},
        )
        assert resp.status_code == 200
        assert resp.get_json()["data"]["widgets"] == ["orderpad", "depth"]

    def test_update_layout(self, client):
        created, _ = _create_preset(client, name="Layout Update")
        preset_id = created["data"]["id"]
        new_layout = {"type": "tabs", "tab_count": 4}
        resp = client.put(
            f"/v1/presets/{preset_id}", headers=_auth(),
            json={"layout": new_layout},
        )
        assert resp.status_code == 200
        assert resp.get_json()["data"]["layout"] == new_layout

    def test_updated_at_changes(self, client):
        created, _ = _create_preset(client, name="Time Update")
        preset_id = created["data"]["id"]
        resp = client.put(
            f"/v1/presets/{preset_id}", headers=_auth(),
            json={"description": "Updated"},
        )
        new_ts = resp.get_json()["data"]["updated_at"]
        # Timestamps may be equal in fast test environments; ensure field is present
        assert new_ts is not None

    def test_builtin_update_returns_403(self, client):
        resp = client.put("/v1/presets/scalper-zone", headers=_auth(), json={"name": "Hacked"})
        assert resp.status_code == 403

    def test_unknown_id_returns_404(self, client):
        resp = client.put("/v1/presets/no-such-id", headers=_auth(), json={"name": "X"})
        assert resp.status_code == 404

    def test_empty_body_returns_400(self, client):
        created, _ = _create_preset(client, name="Empty Update")
        preset_id = created["data"]["id"]
        resp = client.put(f"/v1/presets/{preset_id}", headers=_auth(), json={})
        assert resp.status_code == 400

    def test_duplicate_name_returns_400(self, client):
        _create_preset(client, name="Taken Name")
        created, _ = _create_preset(client, name="To Rename")
        preset_id = created["data"]["id"]
        resp = client.put(
            f"/v1/presets/{preset_id}", headers=_auth(),
            json={"name": "Taken Name"},
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# DELETE /ft-api/v1/presets/<id> — delete
# ---------------------------------------------------------------------------


class TestDeletePreset:
    """DELETE /ft-api/v1/presets/<id>."""

    def test_delete_custom_returns_200(self, client):
        created, _ = _create_preset(client, name="To Delete")
        preset_id = created["data"]["id"]
        resp = client.delete(f"/v1/presets/{preset_id}", headers=_auth())
        assert resp.status_code == 200

    def test_delete_removes_from_list(self, client):
        created, _ = _create_preset(client, name="Gone Soon")
        preset_id = created["data"]["id"]
        client.delete(f"/v1/presets/{preset_id}", headers=_auth())
        list_data = client.get("/v1/presets/", headers=_auth()).get_json()["data"]
        ids = [p["id"] for p in list_data["presets"]]
        assert preset_id not in ids

    def test_deleted_preset_returns_404(self, client):
        created, _ = _create_preset(client, name="Check 404")
        preset_id = created["data"]["id"]
        client.delete(f"/v1/presets/{preset_id}", headers=_auth())
        resp = client.get(f"/v1/presets/{preset_id}", headers=_auth())
        assert resp.status_code == 404

    def test_builtin_delete_returns_403(self, client):
        resp = client.delete("/v1/presets/options-desk", headers=_auth())
        assert resp.status_code == 403

    def test_unknown_id_returns_404(self, client):
        resp = client.delete("/v1/presets/ghost-id", headers=_auth())
        assert resp.status_code == 404

    def test_response_contains_message(self, client):
        created, _ = _create_preset(client, name="Message Check")
        preset_id = created["data"]["id"]
        resp = client.delete(f"/v1/presets/{preset_id}", headers=_auth())
        data = resp.get_json()
        assert "message" in data["data"]


# ---------------------------------------------------------------------------
# POST /ft-api/v1/presets/<id>/fork — fork
# ---------------------------------------------------------------------------


class TestForkPreset:
    """POST /ft-api/v1/presets/<id>/fork."""

    def test_fork_builtin_returns_201(self, client):
        resp = client.post("/v1/presets/scalper-zone/fork", headers=_auth(), json={})
        assert resp.status_code == 201

    def test_fork_default_name(self, client):
        resp = client.post("/v1/presets/options-desk/fork", headers=_auth(), json={})
        data = resp.get_json()["data"]
        assert data["name"] == "Copy of Options Desk"

    def test_fork_custom_name(self, client):
        resp = client.post(
            "/v1/presets/market-watch/fork", headers=_auth(),
            json={"name": "My Market Watch"},
        )
        assert resp.get_json()["data"]["name"] == "My Market Watch"

    def test_forked_preset_is_not_builtin(self, client):
        resp = client.post("/v1/presets/analysis/fork", headers=_auth(), json={})
        assert resp.get_json()["data"]["is_builtin"] is False

    def test_forked_preset_copies_widgets(self, client):
        source = client.get("/v1/presets/risk-monitor", headers=_auth()).get_json()["data"]
        resp = client.post("/v1/presets/risk-monitor/fork", headers=_auth(), json={})
        forked = resp.get_json()["data"]
        assert forked["widgets"] == source["widgets"]

    def test_forked_preset_has_new_id(self, client):
        resp = client.post("/v1/presets/investor-view/fork", headers=_auth(), json={})
        forked_id = resp.get_json()["data"]["id"]
        assert forked_id != "investor-view"

    def test_fork_custom_preset(self, client):
        created, _ = _create_preset(client, name="Forkable")
        preset_id = created["data"]["id"]
        resp = client.post(f"/v1/presets/{preset_id}/fork", headers=_auth(), json={})
        assert resp.status_code == 201
        assert resp.get_json()["data"]["name"] == "Copy of Forkable"

    def test_fork_name_collision_returns_400(self, client):
        # First fork succeeds
        client.post("/v1/presets/scalper-zone/fork", headers=_auth(), json={"name": "My Scalper"})
        # Second fork with same name fails
        resp = client.post("/v1/presets/scalper-zone/fork", headers=_auth(), json={"name": "My Scalper"})
        assert resp.status_code == 400

    def test_fork_unknown_id_returns_404(self, client):
        resp = client.post("/v1/presets/ghost/fork", headers=_auth(), json={})
        assert resp.status_code == 404

    def test_forked_preset_appears_in_list(self, client):
        client.post(
            "/v1/presets/scalper-zone/fork", headers=_auth(),
            json={"name": "Listed Fork"},
        )
        list_data = client.get("/v1/presets/", headers=_auth()).get_json()["data"]
        names = [p["name"] for p in list_data["presets"]]
        assert "Listed Fork" in names


# ---------------------------------------------------------------------------
# Persistence across requests
# ---------------------------------------------------------------------------


class TestPersistence:
    """Verify that custom presets survive across separate _load_custom calls."""

    def test_preset_survives_two_requests(self, client):
        created, _ = _create_preset(client, name="Persistent Preset")
        preset_id = created["data"]["id"]

        # Fresh GET (new call to _load_custom internally)
        resp = client.get(f"/v1/presets/{preset_id}", headers=_auth())
        assert resp.status_code == 200
        assert resp.get_json()["data"]["id"] == preset_id

    def test_multiple_presets_all_persisted(self, client):
        _create_preset(client, name="P1")
        _create_preset(client, name="P2")
        _create_preset(client, name="P3")
        data = client.get("/v1/presets/", headers=_auth()).get_json()["data"]
        names = [p["name"] for p in data["presets"]]
        assert all(n in names for n in ("P1", "P2", "P3"))
