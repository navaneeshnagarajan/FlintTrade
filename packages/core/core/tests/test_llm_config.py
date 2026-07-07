from __future__ import annotations

from pathlib import Path


def _make_app(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("FLINTTRADE_API_KEY", "unit-backend-key")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GROK_API_KEY", raising=False)
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    monkeypatch.delenv("TOGETHER_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    master_password = tmp_path / "master_password"
    master_password.write_text("unit-test-master-password", encoding="utf-8")
    master_password.chmod(0o600)

    from flinttrade_core.app import create_flask_app

    app = create_flask_app()
    app.config["TESTING"] = True
    return app


def _headers() -> dict[str, str]:
    return {"X-API-Key": "unit-backend-key", "Content-Type": "application/json"}


def test_llm_config_endpoint_persists_secret_by_ref(monkeypatch, tmp_path: Path) -> None:
    app = _make_app(monkeypatch, tmp_path)

    with app.test_client() as client:
        resp = client.post(
            "/v1/config/llm",
            json={
                "provider": "openai",
                "host": "",
                "model": "gpt-4o",
                "api_key": "sk-unit-secret",
            },
            headers=_headers(),
        )
        get_resp = client.get("/v1/config/llm", headers={"X-API-Key": "unit-backend-key"})

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["data"]["api_key_configured"] is True
    assert body["data"]["api_key_last4"] == "cret"
    assert "sk-unit-secret" not in str(body)

    assert get_resp.status_code == 200
    get_body = get_resp.get_json()
    assert get_body["data"] == {
        "provider": "openai",
        "host": "",
        "model": "gpt-4o",
        "api_key_configured": True,
        "api_key_last4": "cret",
    }
    assert "sk-unit-secret" not in str(get_body)

    from flinttrade_core.workspace import Workspace

    workspace = Workspace()
    raw = workspace.config_path.read_text(encoding="utf-8")
    assert "sk-unit-secret" not in raw
    assert workspace.get("llm.api_key_ref") == "secret://llm/api_key"


def test_llm_config_endpoint_clears_secret(monkeypatch, tmp_path: Path) -> None:
    app = _make_app(monkeypatch, tmp_path)
    from flinttrade_core.llm_config import resolve_llm_api_key

    with app.test_client() as client:
        client.post("/v1/config/llm", json={"api_key": "sk-unit-secret"}, headers=_headers())
        resp = client.post("/v1/config/llm", json={"api_key": ""}, headers=_headers())

    assert resp.status_code == 200
    assert resp.get_json()["data"]["api_key_configured"] is False
    assert resolve_llm_api_key() == ""


def test_llm_config_from_env_reads_workspace_secret(monkeypatch, tmp_path: Path) -> None:
    _make_app(monkeypatch, tmp_path)
    from flinttrade_core.llm_config import persist_llm_config
    from flinttrade_ai.llm_client import LLMConfig

    persist_llm_config({
        "provider": "openai",
        "model": "gpt-4o",
        "api_key": "sk-unit-secret",
    })

    cfg = LLMConfig.from_env()

    assert cfg.provider == "openai"
    assert cfg.model == "gpt-4o"
    assert cfg.api_key == "sk-unit-secret"
