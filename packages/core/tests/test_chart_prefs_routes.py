"""Tests for packages/core/src/chart_prefs_routes.py (Flask Blueprint).

Uses a real ChartPreferences instance backed by an in-memory DuckDB database
so the full CRUD cycle can be verified without touching the filesystem.
"""

from __future__ import annotations

import pytest
from flask import Flask


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(tmp_path):
    """Flask test client with ChartPreferences wired to a temp DuckDB.

    Args:
        tmp_path: Pytest-provided temporary directory.

    Yields:
        Flask test client with the chart_prefs_bp registered.
    """
    import packages.core.src.chart_prefs_routes as _mod
    from packages.core.src.chart_prefs import ChartPreferences

    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True

    prefs = ChartPreferences(db_path=tmp_path / "chart_prefs.duckdb")
    _mod.init_chart_prefs_routes(prefs)

    flask_app.register_blueprint(_mod.chart_prefs_bp)
    with flask_app.test_client() as c:
        yield c


_HEADERS = {"X-User-Id": "default"}


# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------


class TestTheme:
    def test_get_theme_not_found(self, client) -> None:
        """GET /chart-prefs/theme returns 404 when no theme has been saved.

        Args:
            client: Flask test client.
        """
        resp = client.get("/chart-prefs/theme", headers=_HEADERS)
        assert resp.status_code == 404

    def test_set_and_get_theme(self, client) -> None:
        """POST then GET returns the saved theme data.

        Args:
            client: Flask test client.
        """
        theme = {"background": "#0a0a0f", "upColor": "#22c55e"}
        post_resp = client.post("/chart-prefs/theme", json=theme, headers=_HEADERS)
        assert post_resp.status_code == 200
        assert post_resp.get_json()["status"] == "success"

        get_resp = client.get("/chart-prefs/theme", headers=_HEADERS)
        assert get_resp.status_code == 200
        data = get_resp.get_json()
        assert data["status"] == "success"
        assert data["data"]["background"] == "#0a0a0f"

    def test_set_theme_missing_user_id_returns_400(self, client) -> None:
        """POST /chart-prefs/theme without X-User-Id returns 400.

        Args:
            client: Flask test client.
        """
        resp = client.post("/chart-prefs/theme", json={"bg": "#000"})
        assert resp.status_code == 400

    def test_set_theme_wrong_body_type_returns_400(self, client) -> None:
        """POST /chart-prefs/theme with a JSON array body returns 400.

        Args:
            client: Flask test client.
        """
        resp = client.post("/chart-prefs/theme", json=["not", "a", "dict"], headers=_HEADERS)
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Indicator sets
# ---------------------------------------------------------------------------


class TestIndicatorSets:
    def test_list_empty(self, client) -> None:
        """Listing indicator sets for a fresh user returns empty list.

        Args:
            client: Flask test client.
        """
        resp = client.get("/chart-prefs/indicators", headers=_HEADERS)
        assert resp.status_code == 200
        assert resp.get_json()["data"] == []

    def test_save_and_load_indicator_set(self, client) -> None:
        """Saving then loading a named indicator set round-trips correctly.

        Args:
            client: Flask test client.
        """
        payload = [{"name": "EMA", "params": {"period": 9}}]
        save_resp = client.post(
            "/chart-prefs/indicators/scalping", json=payload, headers=_HEADERS
        )
        assert save_resp.status_code == 200

        load_resp = client.get("/chart-prefs/indicators/scalping", headers=_HEADERS)
        assert load_resp.status_code == 200
        assert load_resp.get_json()["data"][0]["name"] == "EMA"

    def test_get_missing_indicator_set_returns_404(self, client) -> None:
        """GET for a non-existent indicator set returns 404.

        Args:
            client: Flask test client.
        """
        resp = client.get("/chart-prefs/indicators/nonexistent", headers=_HEADERS)
        assert resp.status_code == 404

    def test_delete_indicator_set(self, client) -> None:
        """Deleting an existing indicator set returns success.

        Args:
            client: Flask test client.
        """
        client.post(
            "/chart-prefs/indicators/to_delete",
            json=[{"name": "RSI"}],
            headers=_HEADERS,
        )
        del_resp = client.delete("/chart-prefs/indicators/to_delete", headers=_HEADERS)
        assert del_resp.status_code == 200
        assert del_resp.get_json()["status"] == "success"

    def test_delete_missing_indicator_set_returns_404(self, client) -> None:
        """Deleting a non-existent indicator set returns 404.

        Args:
            client: Flask test client.
        """
        resp = client.delete("/chart-prefs/indicators/ghost", headers=_HEADERS)
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Layouts
# ---------------------------------------------------------------------------


class TestLayouts:
    def test_list_layouts_empty(self, client) -> None:
        """Listing layouts for a fresh user returns empty list.

        Args:
            client: Flask test client.
        """
        resp = client.get("/chart-prefs/layouts", headers=_HEADERS)
        assert resp.status_code == 200
        assert resp.get_json()["data"] == []

    def test_save_and_load_layout(self, client) -> None:
        """Saving then loading a named layout round-trips correctly.

        Args:
            client: Flask test client.
        """
        layout = {"panels": [{"id": "chart1"}]}
        save_resp = client.post(
            "/chart-prefs/layouts/intraday", json=layout, headers=_HEADERS
        )
        assert save_resp.status_code == 200

        load_resp = client.get("/chart-prefs/layouts/intraday", headers=_HEADERS)
        assert load_resp.status_code == 200
        assert load_resp.get_json()["data"]["panels"][0]["id"] == "chart1"

    def test_get_missing_layout_returns_404(self, client) -> None:
        """GET for a non-existent layout returns 404.

        Args:
            client: Flask test client.
        """
        resp = client.get("/chart-prefs/layouts/missing", headers=_HEADERS)
        assert resp.status_code == 404

    def test_delete_layout(self, client) -> None:
        """Deleting an existing layout returns success.

        Args:
            client: Flask test client.
        """
        client.post(
            "/chart-prefs/layouts/to_del",
            json={"panels": []},
            headers=_HEADERS,
        )
        del_resp = client.delete("/chart-prefs/layouts/to_del", headers=_HEADERS)
        assert del_resp.status_code == 200
        assert del_resp.get_json()["status"] == "success"

    def test_delete_missing_layout_returns_404(self, client) -> None:
        """Deleting a non-existent layout returns 404.

        Args:
            client: Flask test client.
        """
        resp = client.delete("/chart-prefs/layouts/ghost", headers=_HEADERS)
        assert resp.status_code == 404
