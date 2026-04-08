"""Tests for admin REST endpoints (dev/debug only).

Run with:
    python -m pytest packages/core/tests/test_admin_routes.py -v --import-mode=importlib
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest


_TEST_API_KEY = "test-admin-routes-key"


@pytest.fixture(scope="module")
def monkeypatch_module():
    """Module-scoped monkeypatch fixture."""
    from _pytest.monkeypatch import MonkeyPatch
    mp = MonkeyPatch()
    yield mp
    mp.undo()


@pytest.fixture(scope="module")
def flask_app(monkeypatch_module):
    """Create a Flask app with admin blueprint enabled (FLINTTRADE_DEV=1)."""
    monkeypatch_module.setenv("OPENALGO_API_KEY", _TEST_API_KEY)
    monkeypatch_module.setenv("FLINTTRADE_DEV", "1")
    from packages.core.src.app import create_flask_app
    app = create_flask_app()
    app.config["TESTING"] = True
    return app


@pytest.fixture()
def client(flask_app):
    """Flask test client with API key header."""
    with flask_app.test_client() as c:
        yield c


def _auth_headers() -> dict[str, str]:
    return {
        "X-API-Key": _TEST_API_KEY,
        "Content-Type": "application/json",
    }


class TestAdminHealth:
    """GET /v1/admin/health — aggregate package health."""

    def test_health_returns_200(self, client):
        resp = client.get("/v1/admin/health", headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert "packages" in data["data"]
        assert "total_packages" in data["data"]
        assert "total_tests" in data["data"]

    def test_health_packages_have_expected_fields(self, client):
        resp = client.get("/v1/admin/health", headers=_auth_headers())
        data = resp.get_json()["data"]
        assert isinstance(data["packages"], list)
        if data["packages"]:
            pkg = data["packages"][0]
            assert "name" in pkg
            assert "type" in pkg
            assert "testCount" in pkg
            assert "testFiles" in pkg


class TestAdminIntrospect:
    """GET /v1/admin/introspect — project introspection data."""

    def test_introspect_returns_200(self, client):
        resp = client.get("/v1/admin/introspect", headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert "packages" in data["data"]
        assert "endpoints" in data["data"]
        assert "endpoint_count" in data["data"]
        assert "package_count" in data["data"]

    def test_introspect_endpoints_are_sorted(self, client):
        resp = client.get("/v1/admin/introspect", headers=_auth_headers())
        data = resp.get_json()
        endpoints = data["data"]["endpoints"]
        paths = [e["path"] for e in endpoints]
        assert paths == sorted(paths)


class TestAdminWidgets:
    """GET /v1/admin/widgets — widget registry."""

    def test_widgets_returns_200(self, client):
        resp = client.get("/v1/admin/widgets", headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert "widgets" in data["data"]
        assert "total" in data["data"]
        assert "by_category" in data["data"]
        assert data["data"]["total"] > 0

    def test_widgets_have_required_fields(self, client):
        resp = client.get("/v1/admin/widgets", headers=_auth_headers())
        data = resp.get_json()["data"]
        for widget in data["widgets"]:
            assert "id" in widget
            assert "name" in widget
            assert "category" in widget
            assert "status" in widget


class TestAdminFeatures:
    """GET /v1/admin/features — feature flag status."""

    def test_features_returns_200(self, client):
        resp = client.get("/v1/admin/features", headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert "features" in data["data"]
        assert "total" in data["data"]
        assert "by_status" in data["data"]
        assert data["data"]["total"] > 0

    def test_features_by_status_sums_to_total(self, client):
        resp = client.get("/v1/admin/features", headers=_auth_headers())
        data = resp.get_json()["data"]
        assert sum(data["by_status"].values()) == data["total"]


class TestAdminRepos:
    """GET /v1/admin/repos — absorption status file."""

    def test_repos_returns_404_when_file_missing(self, client):
        """absorption-status.json may not exist; endpoint should return 404."""
        resp = client.get("/v1/admin/repos", headers=_auth_headers())
        # Either 200 (file exists) or 404 (file missing) is acceptable
        assert resp.status_code in (200, 404)
        data = resp.get_json()
        if resp.status_code == 404:
            assert data["status"] == "error"
            assert "message" in data
