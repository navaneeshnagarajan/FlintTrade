"""Backend auth independence from OpenAlgo configuration."""

from __future__ import annotations

from pathlib import Path


def _make_app(monkeypatch, tmp_path: Path, *, flint_key: str | None = None):
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.delenv("OPENALGO_API_KEY", raising=False)
    master_password = tmp_path / "master_password"
    master_password.write_text("unit-test-master-password", encoding="utf-8")
    master_password.chmod(0o600)
    if flint_key is None:
        monkeypatch.delenv("FLINTTRADE_API_KEY", raising=False)
    else:
        monkeypatch.setenv("FLINTTRADE_API_KEY", flint_key)

    from flinttrade_core.app import create_flask_app

    app = create_flask_app()
    app.config["TESTING"] = True
    return app


def test_loopback_native_sandbox_works_without_openalgo_key(monkeypatch, tmp_path: Path) -> None:
    app = _make_app(monkeypatch, tmp_path)

    with app.test_client() as client:
        resp = client.get("/v1/sandbox/capital")

    assert resp.status_code == 200
    assert resp.get_json()["status"] == "success"


def test_flinttrade_api_key_authenticates_without_openalgo_key(monkeypatch, tmp_path: Path) -> None:
    app = _make_app(monkeypatch, tmp_path, flint_key="flint-local-key")

    with app.test_client() as client:
        missing = client.get("/v1/sandbox/capital")
        wrong = client.get("/v1/sandbox/capital", headers={"X-API-Key": "wrong"})
        ok = client.get("/v1/sandbox/capital", headers={"X-API-Key": "flint-local-key"})

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert ok.status_code == 200
    assert ok.get_json()["status"] == "success"
