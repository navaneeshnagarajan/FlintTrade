from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import threading
import time

import pytest
from filelock import FileLock, Timeout


_CRASH_LLM_CONFIG_TRANSACTION = r"""
import os
import sys
from pathlib import Path

from flinttrade_core import llm_config, secure_file
from flinttrade_core.workspace import Workspace

workspace_dir = Path(sys.argv[1])
fault = sys.argv[2]
secret_path = workspace_dir / "secrets" / "llm_api_key"

if fault.startswith("workspace-update-"):
    crash_after = int(fault.rsplit("-", 1)[1])
    original_update = Workspace.update
    update_count = [0]

    def crash_after_workspace_update(self, updater):
        result = original_update(self, updater)
        update_count[0] += 1
        if update_count[0] == crash_after:
            os._exit(91)
        return result

    Workspace.update = crash_after_workspace_update
elif fault == "secret-installed":
    original_replace = os.replace

    def portable_windows_harden(path, user=None):
        del user
        os.chmod(path, 0o600)

    def crash_after_windows_secret_install(source, destination):
        result = original_replace(source, destination)
        source_path = Path(source)
        if Path(destination) == secret_path and source_path.name.startswith(".llm_api_key") and "new" in source_path.name:
            os._exit(91)
        return result

    secure_file._is_windows = lambda: True
    secure_file.harden = portable_windows_harden
    secure_file._assert_current_user_owns = lambda *args: None
    secure_file._windows_replace_write_through = crash_after_windows_secret_install
elif fault == "committed-cleanup":
    original_unlink = Path.unlink

    def crash_before_backup_cleanup(self, *args, **kwargs):
        if self.name.startswith(".llm_api_key") and "old" in self.name:
            os._exit(91)
        return original_unlink(self, *args, **kwargs)

    Path.unlink = crash_before_backup_cleanup
else:
    raise AssertionError(f"unknown fault boundary: {fault}")

llm_config.persist_llm_config(
    {
        "provider": "custom",
        "host": "https://new-models.example.invalid",
        "model": "new-model",
        "api_key": "new-secret",
    },
    Workspace(workspace_dir),
)
raise AssertionError("fault boundary was not reached")
"""


_WRITE_LLM_CONFIG_AFTER_TRANSITION_LOCK = r"""
import sys
from pathlib import Path

from flinttrade_core.llm_config import persist_llm_config
from flinttrade_core.workspace import Workspace

workspace_dir = Path(sys.argv[1])
started_path = Path(sys.argv[2])
completed_path = Path(sys.argv[3])
started_path.write_text("started", encoding="utf-8")
persist_llm_config({"model": "writer-model"}, Workspace(workspace_dir))
completed_path.write_text("completed", encoding="utf-8")
"""


def _make_app(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("FLINTTRADE_API_KEY", "unit-backend-key")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_HOST", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
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
    monkeypatch.delenv("CEREBRAS_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("HERMES_API_KEY", raising=False)
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
        client.post(
            "/v1/config/llm",
            json={"provider": "openai", "api_key": "sk-unit-secret"},
            headers=_headers(),
        )
        resp = client.post("/v1/config/llm", json={"api_key": ""}, headers=_headers())

    assert resp.status_code == 200
    assert resp.get_json()["data"]["api_key_configured"] is False
    assert resolve_llm_api_key() == ""


def test_llm_config_endpoint_delegates_provider_changes_to_the_runtime_transaction(
    monkeypatch,
    tmp_path: Path,
) -> None:
    app = _make_app(monkeypatch, tmp_path)
    from flinttrade_core import local_ai_routes

    calls: list[tuple[object, dict[str, str]]] = []

    def persist_with_runtime(flask_app, payload):
        calls.append((flask_app, dict(payload)))
        return {
            "provider": "ollama",
            "host": "",
            "model": "qwen3:8b",
            "api_key_configured": False,
            "api_key_last4": "",
        }

    monkeypatch.setattr(local_ai_routes, "persist_llm_config_with_runtime", persist_with_runtime)

    response = app.test_client().post(
        "/v1/config/llm",
        json={"provider": "ollama", "model": "qwen3:8b"},
        headers=_headers(),
    )

    assert response.status_code == 200
    assert calls == [(app, {"provider": "ollama", "model": "qwen3:8b"})]


def test_llm_config_endpoint_reports_a_failed_runtime_transition_without_persisting(
    monkeypatch,
    tmp_path: Path,
) -> None:
    app = _make_app(monkeypatch, tmp_path)
    from flinttrade_core import local_ai_routes
    from flinttrade_core.ollama_runtime import OllamaRuntimeError

    monkeypatch.setattr(
        local_ai_routes,
        "persist_llm_config_with_runtime",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            OllamaRuntimeError("managed Ollama runtime is not installed")
        ),
    )

    response = app.test_client().post(
        "/v1/config/llm",
        json={"provider": "ollama"},
        headers=_headers(),
    )

    assert response.status_code == 409
    assert response.get_json() == {
        "status": "error",
        "message": "managed Ollama runtime is not installed",
    }


def test_llm_config_endpoint_requires_control_auth_even_when_global_keys_are_unset(
    monkeypatch,
    tmp_path: Path,
) -> None:
    app = _make_app(monkeypatch, tmp_path)
    monkeypatch.delenv("FLINTTRADE_API_KEY", raising=False)
    monkeypatch.delenv("OPENALGO_API_KEY", raising=False)

    response = app.test_client().post(
        "/v1/config/llm",
        json={"provider": "openai", "api_key": "must-not-persist"},
    )

    assert response.status_code == 401
    assert response.get_json() == {
        "status": "error",
        "message": "LLM configuration requires an authenticated session",
    }
    assert not (tmp_path / "secrets" / "llm_api_key").exists()


def test_llm_connection_test_uses_the_effective_server_side_credential(
    monkeypatch,
    tmp_path: Path,
) -> None:
    app = _make_app(monkeypatch, tmp_path)
    from flinttrade_ai import llm_client

    observed: dict[str, object] = {}

    class FakeClient:
        def __init__(self, *, config, timeout_seconds: float) -> None:
            observed["config"] = config
            observed["timeout_seconds"] = timeout_seconds

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            observed["closed"] = True

        def chat(self, messages, **kwargs):
            observed["messages"] = messages
            observed["chat_kwargs"] = kwargs
            return llm_client.LLMResponse(
                content="OK",
                provider="openai",
                model="gpt-test",
            )

    monkeypatch.setattr(llm_client, "LLMClient", FakeClient)
    monkeypatch.setattr(
        llm_client.LLMConfig,
        "from_env",
        classmethod(
            lambda _cls: llm_client.LLMConfig(
                provider="openai",
                model="gpt-test",
                api_key="stored-server-side-secret",
            )
        ),
    )

    response = app.test_client().post("/v1/config/llm/test", headers=_headers())

    assert response.status_code == 200
    assert response.get_json() == {
        "status": "success",
        "data": {"provider": "openai", "model": "gpt-test"},
    }
    assert observed["timeout_seconds"] == 15.0
    assert observed["config"].api_key == "stored-server-side-secret"
    assert observed["chat_kwargs"] == {"temperature": 0.0, "max_tokens": 8}
    assert observed["closed"] is True


def test_llm_connection_test_uses_the_exact_operator_draft(
    monkeypatch,
    tmp_path: Path,
) -> None:
    app = _make_app(monkeypatch, tmp_path)
    from flinttrade_ai import llm_client

    observed: dict[str, object] = {}

    class FakeClient:
        def __init__(self, *, config, timeout_seconds: float) -> None:
            observed["config"] = config
            observed["timeout_seconds"] = timeout_seconds

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def chat(self, _messages, **_kwargs):
            return llm_client.LLMResponse(
                content="OK",
                provider="custom",
                model="draft-model",
            )

    monkeypatch.setattr(llm_client, "LLMClient", FakeClient)
    monkeypatch.setattr(
        llm_client.LLMConfig,
        "from_env",
        classmethod(
            lambda _cls: llm_client.LLMConfig(
                provider="openai",
                model="persisted-model",
                api_key="persisted-secret",
            )
        ),
    )

    response = app.test_client().post(
        "/v1/config/llm/test",
        json={
            "provider": "custom",
            "host": "http://127.0.0.1:9000",
            "model": "draft-model",
            "api_key": "draft-secret",
        },
        headers=_headers(),
    )

    assert response.status_code == 200
    config = observed["config"]
    assert config.provider == "custom"
    assert config.host == "http://127.0.0.1:9000"
    assert config.model == "draft-model"
    assert config.api_key == "draft-secret"
    assert observed["timeout_seconds"] == 15.0


def test_llm_connection_test_does_not_reuse_a_key_across_a_draft_destination(
    monkeypatch,
    tmp_path: Path,
) -> None:
    app = _make_app(monkeypatch, tmp_path)
    from flinttrade_ai import llm_client

    observed: dict[str, object] = {}

    class FakeClient:
        def __init__(self, *, config, timeout_seconds: float) -> None:
            observed["config"] = config

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def chat(self, _messages, **_kwargs):
            return llm_client.LLMResponse(error="missing key", provider="custom", model="draft-model")

    monkeypatch.setattr(llm_client, "LLMClient", FakeClient)
    monkeypatch.setattr(
        llm_client.LLMConfig,
        "from_env",
        classmethod(
            lambda _cls: llm_client.LLMConfig(
                provider="openai",
                model="persisted-model",
                api_key="must-not-cross-destination",
            )
        ),
    )

    response = app.test_client().post(
        "/v1/config/llm/test",
        json={
            "provider": "custom",
            "host": "http://127.0.0.1:9000",
            "model": "draft-model",
        },
        headers=_headers(),
    )

    assert response.status_code == 409
    assert observed["config"].api_key == ""


def test_llm_connection_test_never_exposes_provider_error_details(
    monkeypatch,
    tmp_path: Path,
) -> None:
    app = _make_app(monkeypatch, tmp_path)
    from flinttrade_ai import llm_client

    class FakeClient:
        def __init__(self, **_kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            pass

        def chat(self, *_args, **_kwargs):
            return llm_client.LLMResponse(error="HTTP 401: provider-secret-detail")

    monkeypatch.setattr(llm_client, "LLMClient", FakeClient)
    monkeypatch.setattr(
        llm_client.LLMConfig,
        "from_env",
        classmethod(lambda _cls: llm_client.LLMConfig(provider="openai", model="gpt-test")),
    )

    response = app.test_client().post("/v1/config/llm/test", headers=_headers())

    assert response.status_code == 409
    assert response.get_json() == {
        "status": "error",
        "message": "LLM connection test failed",
    }
    assert "provider-secret-detail" not in response.get_data(as_text=True)


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


def test_effective_config_reads_endpoint_and_credential_under_one_lock(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _make_app(monkeypatch, tmp_path)
    from flinttrade_core import llm_config
    from flinttrade_core.workspace import Workspace

    llm_config.persist_llm_config(
        {
            "provider": "custom",
            "host": "https://old-models.example.invalid",
            "model": "old-model",
            "api_key": "old-secret",
        }
    )
    original_read_secret = llm_config._read_secret
    read_started = threading.Event()
    release_read = threading.Event()
    writer_started = threading.Event()
    reader_result: dict[str, object] = {}

    def pause_first_secret_read(path: Path) -> str:
        if not read_started.is_set():
            read_started.set()
            assert release_read.wait(2.0)
        return original_read_secret(path)

    monkeypatch.setattr(llm_config, "_read_secret", pause_first_secret_read)

    def read_config() -> None:
        try:
            reader_result["config"] = llm_config.read_effective_llm_config(Workspace())
        except BaseException as exc:  # noqa: BLE001 - retained for assertion in the parent
            reader_result["error"] = exc

    def replace_config() -> None:
        writer_started.set()
        llm_config.persist_llm_config(
            {
                "provider": "custom",
                "host": "https://new-models.example.invalid",
                "model": "new-model",
                "api_key": "new-secret",
            },
            Workspace(),
        )

    reader = threading.Thread(target=read_config)
    reader.start()
    assert read_started.wait(2.0)
    try:
        with FileLock(tmp_path / ".llm-config.lock", timeout=0):
            snapshot_lock_held = False
    except Timeout:
        snapshot_lock_held = True
    writer = threading.Thread(target=replace_config)
    writer.start()
    assert writer_started.wait(2.0)
    release_read.set()
    reader.join(2.0)
    writer.join(2.0)

    assert reader.is_alive() is False
    assert writer.is_alive() is False
    assert snapshot_lock_held is True
    assert "error" not in reader_result
    assert reader_result["config"] == {
        "provider": "custom",
        "host": "https://old-models.example.invalid",
        "model": "old-model",
        "api_key": "old-secret",
    }


def test_ollama_effective_config_cannot_inherit_remote_host_or_credentials(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _make_app(monkeypatch, tmp_path)
    from flinttrade_ai.llm_client import LLMConfig
    from flinttrade_core.llm_config import persist_llm_config

    persist_llm_config(
        {
            "provider": "custom",
            "host": "https://models.example.invalid",
            "model": "workspace-model",
            "api_key": "workspace-secret",
        }
    )
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("LLM_API_KEY", "global-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-secret")

    cfg = LLMConfig.from_env()

    assert cfg.provider == "ollama"
    assert cfg.host == ""
    assert cfg.model == "workspace-model"
    assert cfg.api_key == ""


def test_cloud_provider_does_not_inherit_another_clouds_key(monkeypatch, tmp_path: Path) -> None:
    _make_app(monkeypatch, tmp_path)
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-only-secret")
    from flinttrade_ai.llm_client import LLMConfig

    cfg = LLMConfig.from_env()

    assert cfg.provider == "openai"
    assert cfg.api_key == ""


def test_generic_environment_key_never_overrides_provider_specific_key(monkeypatch, tmp_path: Path) -> None:
    _make_app(monkeypatch, tmp_path)
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_API_KEY", "unsafe-generic-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-only-secret")
    from flinttrade_ai.llm_client import LLMConfig

    config = LLMConfig.from_env()

    assert config.api_key == "openai-only-secret"


def test_generic_environment_key_is_not_used_without_a_provider_specific_key(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _make_app(monkeypatch, tmp_path)
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_API_KEY", "unsafe-generic-secret")
    from flinttrade_ai.llm_client import LLMConfig

    config = LLMConfig.from_env()

    assert config.api_key == ""


def test_provider_specific_environment_key_rejects_control_characters(monkeypatch, tmp_path: Path) -> None:
    _make_app(monkeypatch, tmp_path)
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-secret\nsmuggled-header")
    from flinttrade_ai.llm_client import LLMConfig

    with pytest.raises(ValueError, match="control characters"):
        LLMConfig.from_env()


def test_persist_rejects_remote_host_under_managed_ollama(monkeypatch, tmp_path: Path) -> None:
    _make_app(monkeypatch, tmp_path)
    from flinttrade_core.llm_config import persist_llm_config, read_llm_config

    with pytest.raises(ValueError, match="managed Ollama endpoint"):
        persist_llm_config(
            {
                "provider": "ollama",
                "host": "http://10.0.0.8:11434",
                "model": "qwen3:8b",
            }
        )

    assert read_llm_config()["provider"] == ""


def test_switching_to_ollama_drops_a_previous_custom_host(monkeypatch, tmp_path: Path) -> None:
    _make_app(monkeypatch, tmp_path)
    from flinttrade_core.llm_config import persist_llm_config

    persist_llm_config({"provider": "custom", "host": "https://models.example.invalid"})

    config = persist_llm_config({"provider": "ollama"})

    assert config["provider"] == "ollama"
    assert config["host"] == ""


def test_stored_secret_is_bound_to_provider_and_trust_destination(monkeypatch, tmp_path: Path) -> None:
    _make_app(monkeypatch, tmp_path)
    from flinttrade_core.llm_config import persist_llm_config
    from flinttrade_core.workspace import Workspace

    persist_llm_config(
        {
            "provider": "custom",
            "host": "https://models.example.invalid/root/",
            "api_key": "custom-secret",
        }
    )

    workspace = Workspace()
    assert workspace.get("llm.api_key_provider") == "custom"
    assert workspace.get("llm.api_key_destination") == "https://models.example.invalid/root"


def test_equivalent_custom_destination_spelling_preserves_the_bound_secret(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _make_app(monkeypatch, tmp_path)
    from flinttrade_core.llm_config import persist_llm_config, read_effective_llm_config
    from flinttrade_core.workspace import Workspace

    persist_llm_config(
        {
            "provider": "custom",
            "host": "HTTPS://Models.Example.INVALID:443/API/",
            "api_key": "custom-secret",
        }
    )

    result = persist_llm_config(
        {"host": "https://models.example.invalid/API"}
    )

    assert result["api_key_configured"] is True
    assert read_effective_llm_config()["api_key"] == "custom-secret"
    assert Workspace().get("llm.api_key_destination") == "https://models.example.invalid/API"
    assert (tmp_path / "secrets" / "llm_api_key").exists()


def test_destination_canonicalisation_preserves_path_case(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _make_app(monkeypatch, tmp_path)
    from flinttrade_core.llm_config import persist_llm_config

    persist_llm_config(
        {
            "provider": "custom",
            "host": "https://models.example.invalid/API",
            "api_key": "custom-secret",
        }
    )

    result = persist_llm_config(
        {"host": "https://models.example.invalid/api"}
    )

    assert result["api_key_configured"] is False
    assert not (tmp_path / "secrets" / "llm_api_key").exists()


@pytest.mark.parametrize(
    "host",
    [
        "https://operator:credential@models.example.invalid/api",
        "https://models.example.invalid/api?api_key=credential",
        "https://models.example.invalid/api#credential",
    ],
)
def test_persist_rejects_unsafe_custom_api_base_components(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    host: str,
) -> None:
    _make_app(monkeypatch, tmp_path)
    from flinttrade_core.llm_config import persist_llm_config

    with pytest.raises(ValueError, match="must not contain credentials"):
        persist_llm_config({"provider": "custom", "host": host})

    assert "credential" not in (tmp_path / "workspace.json").read_text(encoding="utf-8")


def test_workspace_secret_symlink_is_never_read(monkeypatch, tmp_path: Path) -> None:
    _make_app(monkeypatch, tmp_path)
    from flinttrade_core.llm_config import persist_llm_config, read_effective_llm_config

    persist_llm_config(
        {
            "provider": "custom",
            "host": "https://models.example.invalid",
            "api_key": "original-secret",
        }
    )
    secret_path = tmp_path / "secrets" / "llm_api_key"
    external_secret = tmp_path / "external-secret"
    external_secret.write_text("must-not-be-read", encoding="utf-8")
    external_secret.chmod(0o600)
    secret_path.unlink()
    secret_path.symlink_to(external_secret)

    assert read_effective_llm_config()["api_key"] == ""


@pytest.mark.skipif(not hasattr(os, "geteuid"), reason="POSIX ownership check")
def test_workspace_secret_not_owned_by_the_current_user_is_never_read(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _make_app(monkeypatch, tmp_path)
    from flinttrade_core.llm_config import persist_llm_config, read_effective_llm_config

    persist_llm_config(
        {
            "provider": "custom",
            "host": "https://models.example.invalid",
            "api_key": "owner-only-secret",
        }
    )
    actual_owner = os.geteuid()
    monkeypatch.setattr(os, "geteuid", lambda: actual_owner + 1)

    assert read_effective_llm_config()["api_key"] == ""


@pytest.mark.parametrize("provider", ["custom", "hermes"])
def test_host_change_without_replacement_clears_bound_secret(
    monkeypatch,
    tmp_path: Path,
    provider: str,
) -> None:
    _make_app(monkeypatch, tmp_path)
    from flinttrade_core.llm_config import persist_llm_config, read_effective_llm_config
    from flinttrade_core.workspace import Workspace

    persist_llm_config(
        {
            "provider": provider,
            "host": "https://old-models.example.invalid",
            "api_key": "old-destination-secret",
        }
    )

    config = persist_llm_config({"host": "https://new-models.example.invalid"})

    workspace = Workspace()
    assert config["host"] == "https://new-models.example.invalid"
    assert config["api_key_configured"] is False
    assert read_effective_llm_config()["api_key"] == ""
    assert workspace.get("llm.api_key_ref") == ""
    assert workspace.get("llm.api_key_provider") == ""
    assert workspace.get("llm.api_key_destination") == ""
    assert not (tmp_path / "secrets" / "llm_api_key").exists()


def test_destination_binding_blocks_a_manually_retained_secret(monkeypatch, tmp_path: Path) -> None:
    _make_app(monkeypatch, tmp_path)
    from flinttrade_core.llm_config import persist_llm_config, read_effective_llm_config
    from flinttrade_core.workspace import Workspace

    persist_llm_config(
        {
            "provider": "custom",
            "host": "https://old-models.example.invalid",
            "api_key": "old-destination-secret",
        }
    )
    workspace = Workspace()
    workspace.update(lambda config: config["llm"].update({"host": "https://new-models.example.invalid"}))

    effective = read_effective_llm_config(Workspace())

    assert effective["host"] == "https://new-models.example.invalid"
    assert effective["api_key"] == ""


def test_switching_provider_clears_previous_workspace_secret(monkeypatch, tmp_path: Path) -> None:
    _make_app(monkeypatch, tmp_path)
    from flinttrade_ai.llm_client import LLMConfig
    from flinttrade_core.llm_config import persist_llm_config

    persist_llm_config({"provider": "openai", "api_key": "openai-secret"})
    persist_llm_config({"provider": "anthropic"})

    anthropic = LLMConfig.from_env()

    assert anthropic.provider == "anthropic"
    assert anthropic.api_key == ""

    persist_llm_config({"provider": "openai"})
    assert LLMConfig.from_env().api_key == ""


def test_unbound_legacy_workspace_secret_fails_closed(monkeypatch, tmp_path: Path) -> None:
    _make_app(monkeypatch, tmp_path)
    from flinttrade_core.llm_config import LLM_API_KEY_REF, read_effective_llm_config
    from flinttrade_core.workspace import Workspace

    workspace = Workspace()
    secret_path = tmp_path / "secrets" / "llm_api_key"
    secret_path.parent.mkdir(parents=True, exist_ok=True)
    secret_path.write_text("legacy-unbound-secret", encoding="utf-8")
    workspace.update(
        lambda config: config["llm"].update(
            {
                "provider": "openai",
                "api_key_ref": LLM_API_KEY_REF,
            }
        )
    )

    assert read_effective_llm_config(Workspace())["api_key"] == ""


@pytest.mark.parametrize("api_key", ["line\nbreak", "tab\tbreak", "nul\0break", "delete\x7fbreak"])
def test_persistence_rejects_api_key_control_characters(
    monkeypatch,
    tmp_path: Path,
    api_key: str,
) -> None:
    _make_app(monkeypatch, tmp_path)
    from flinttrade_core.llm_config import persist_llm_config, read_llm_config

    with pytest.raises(ValueError, match="control characters"):
        persist_llm_config({"provider": "openai", "api_key": api_key})

    assert read_llm_config()["api_key_configured"] is False


def test_secret_write_failure_rolls_back_destination_and_preserves_old_secret(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _make_app(monkeypatch, tmp_path)
    from flinttrade_core import llm_config

    llm_config.persist_llm_config(
        {
            "provider": "custom",
            "host": "https://old-models.example.invalid",
            "api_key": "old-destination-secret",
        }
    )

    def partial_secret_write_then_fail(path: Path, value: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value[:7], encoding="utf-8")
        raise OSError("simulated secret write failure")

    monkeypatch.setattr(llm_config, "write_secret_text", partial_secret_write_then_fail)

    with pytest.raises(OSError, match="simulated secret write failure"):
        llm_config.persist_llm_config(
            {
                "provider": "custom",
                "host": "https://new-models.example.invalid",
                "api_key": "new-destination-secret",
            }
        )

    effective = llm_config.read_effective_llm_config()
    assert effective["host"] == "https://old-models.example.invalid"
    assert effective["api_key"] == "old-destination-secret"


def test_workspace_write_failure_restores_the_previous_secret(monkeypatch, tmp_path: Path) -> None:
    _make_app(monkeypatch, tmp_path)
    from flinttrade_core import llm_config
    from flinttrade_core.workspace import Workspace

    workspace = Workspace()
    llm_config.persist_llm_config(
        {"provider": "openai", "model": "old-model", "api_key": "old-secret"},
        workspace,
    )
    original_update = workspace.update

    def fail_workspace_update(_updater):
        raise OSError("simulated workspace write failure")

    monkeypatch.setattr(workspace, "update", fail_workspace_update)

    with pytest.raises(OSError, match="simulated workspace write failure"):
        llm_config.persist_llm_config({"model": "new-model", "api_key": "new-secret"}, workspace)

    monkeypatch.setattr(workspace, "update", original_update)
    effective = llm_config.read_effective_llm_config(Workspace())
    assert effective["model"] == "old-model"
    assert effective["api_key"] == "old-secret"


def test_same_destination_secret_patch_uses_one_workspace_update(monkeypatch, tmp_path: Path) -> None:
    _make_app(monkeypatch, tmp_path)
    from flinttrade_core import llm_config
    from flinttrade_core.workspace import Workspace

    workspace = Workspace()
    llm_config.persist_llm_config({"provider": "openai", "api_key": "old-secret"}, workspace)
    original_update = workspace.update
    update_count = 0

    def count_workspace_update(updater):
        nonlocal update_count
        update_count += 1
        return original_update(updater)

    monkeypatch.setattr(workspace, "update", count_workspace_update)

    llm_config.persist_llm_config({"model": "new-model", "api_key": "new-secret"}, workspace)

    assert update_count == 1


@pytest.mark.parametrize(
    ("fault", "expected_provider", "expected_host", "expected_model", "expected_key"),
    [
        (
            "workspace-update-1",
            "custom",
            "https://old-models.example.invalid",
            "old-model",
            "old-secret",
        ),
        (
            "secret-installed",
            "custom",
            "https://old-models.example.invalid",
            "old-model",
            "old-secret",
        ),
        (
            "workspace-update-2",
            "custom",
            "https://old-models.example.invalid",
            "old-model",
            "old-secret",
        ),
        (
            "committed-cleanup",
            "custom",
            "https://new-models.example.invalid",
            "new-model",
            "new-secret",
        ),
    ],
)
def test_startup_recovers_every_llm_config_transaction_fault_boundary(
    monkeypatch,
    tmp_path: Path,
    fault: str,
    expected_provider: str,
    expected_host: str,
    expected_model: str,
    expected_key: str,
) -> None:
    _make_app(monkeypatch, tmp_path)
    from flinttrade_core import llm_config
    from flinttrade_core.workspace import Workspace

    workspace = Workspace()
    llm_config.persist_llm_config(
        {
            "provider": "custom",
            "host": "https://old-models.example.invalid",
            "model": "old-model",
            "api_key": "old-secret",
        },
        workspace,
    )
    environment = os.environ.copy()
    crashed = subprocess.run(
        [sys.executable, "-c", _CRASH_LLM_CONFIG_TRANSACTION, str(tmp_path), fault],
        capture_output=True,
        check=False,
        env=environment,
        text=True,
    )

    assert crashed.returncode == 91, crashed.stdout + crashed.stderr

    effective = llm_config.read_effective_llm_config(Workspace())

    assert effective["provider"] == expected_provider
    assert effective["host"] == expected_host
    assert effective["model"] == expected_model
    assert effective["api_key"] == expected_key
    assert list((tmp_path / "secrets").glob(".llm_api_key*")) == []


def test_api_key_deletion_failure_is_reported_and_recovered_on_next_startup(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _make_app(monkeypatch, tmp_path)
    from flinttrade_core import llm_config
    from flinttrade_core.workspace import Workspace

    llm_config.persist_llm_config({"provider": "openai", "api_key": "old-secret"})
    secret_path = tmp_path / "secrets" / "llm_api_key"
    original_unlink = Path.unlink

    def refuse_secret_deletion(self, *args, **kwargs):
        if self == secret_path:
            raise PermissionError("simulated credential deletion failure")
        return original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", refuse_secret_deletion)

    with pytest.raises(RuntimeError, match="credential cleanup is pending"):
        llm_config.persist_llm_config({"api_key": ""})

    assert secret_path.read_text(encoding="utf-8") == "old-secret"
    assert Workspace().get("llm.api_key_ref") == ""

    monkeypatch.setattr(Path, "unlink", original_unlink)
    recovered = llm_config.read_llm_config(Workspace())

    assert recovered["api_key_configured"] is False
    assert not secret_path.exists()
    assert list((tmp_path / "secrets").glob(".llm_api_key*")) == []


def test_old_api_key_backup_deletion_failure_is_reported_and_recovered(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _make_app(monkeypatch, tmp_path)
    from flinttrade_core import llm_config
    from flinttrade_core.workspace import Workspace

    llm_config.persist_llm_config({"provider": "openai", "api_key": "old-secret"})
    original_unlink = Path.unlink

    def refuse_old_backup_deletion(self, *args, **kwargs):
        if self.name.startswith(".llm_api_key") and "old" in self.name:
            raise PermissionError("simulated backup deletion failure")
        return original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", refuse_old_backup_deletion)

    with pytest.raises(RuntimeError, match="credential cleanup is pending"):
        llm_config.persist_llm_config({"model": "new-model", "api_key": "new-secret"})

    secret_path = tmp_path / "secrets" / "llm_api_key"
    assert secret_path.read_text(encoding="utf-8") == "new-secret"
    assert Workspace().get("llm.api_key_ref") == "secret://llm/api_key"

    monkeypatch.setattr(Path, "unlink", original_unlink)
    recovered = llm_config.read_effective_llm_config(Workspace())

    assert recovered["model"] == "new-model"
    assert recovered["api_key"] == "new-secret"
    assert list((tmp_path / "secrets").glob(".llm_api_key*")) == []


@pytest.mark.skipif(os.name == "nt", reason="directory fsync is POSIX-only")
def test_llm_secret_transaction_fsyncs_workspace_and_secret_directories(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _make_app(monkeypatch, tmp_path)
    from flinttrade_core.llm_config import persist_llm_config

    real_fsync = os.fsync
    fsynced_directories: set[tuple[int, int]] = set()

    def record_fsync(descriptor: int) -> None:
        descriptor_stat = os.fstat(descriptor)
        if stat.S_ISDIR(descriptor_stat.st_mode):
            fsynced_directories.add((descriptor_stat.st_dev, descriptor_stat.st_ino))
        real_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", record_fsync)

    persist_llm_config(
        {
            "provider": "custom",
            "host": "https://models.example.invalid",
            "api_key": "durable-secret",
        }
    )

    workspace_stat = tmp_path.stat()
    secret_dir_stat = (tmp_path / "secrets").stat()
    assert (workspace_stat.st_dev, workspace_stat.st_ino) in fsynced_directories
    assert (secret_dir_stat.st_dev, secret_dir_stat.st_ino) in fsynced_directories


@pytest.mark.skipif(os.name == "nt", reason="directory fsync is POSIX-only")
def test_first_secret_write_persists_the_secret_directory_before_config_update(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _make_app(monkeypatch, tmp_path)
    from flinttrade_core.llm_config import persist_llm_config
    from flinttrade_core.workspace import Workspace

    events: list[str] = []
    real_fsync = os.fsync
    real_update = Workspace.update
    workspace_identity = (tmp_path.stat().st_dev, tmp_path.stat().st_ino)

    def record_fsync(descriptor: int) -> None:
        descriptor_stat = os.fstat(descriptor)
        if (
            stat.S_ISDIR(descriptor_stat.st_mode)
            and (descriptor_stat.st_dev, descriptor_stat.st_ino) == workspace_identity
        ):
            events.append("workspace-directory-fsync")
        real_fsync(descriptor)

    def record_update(self, updater):
        events.append("workspace-update")
        return real_update(self, updater)

    monkeypatch.setattr(os, "fsync", record_fsync)
    monkeypatch.setattr(Workspace, "update", record_update)

    persist_llm_config(
        {
            "provider": "custom",
            "host": "https://models.example.invalid",
            "api_key": "durable-secret",
        }
    )

    assert events.index("workspace-directory-fsync") < events.index("workspace-update")


def test_default_lmstudio_workspace_migrates_to_managed_ollama(monkeypatch, tmp_path: Path) -> None:
    _make_app(monkeypatch, tmp_path)
    from flinttrade_core.llm_config import read_llm_config
    from flinttrade_core.workspace import Workspace

    workspace = Workspace()
    legacy = workspace.as_dict()
    legacy["version"] = "1.1.0"
    legacy["llm"] = {
        "provider": "lmstudio",
        "host": "http://127.0.0.1:1234",
        "model": "local-model",
    }
    workspace.config_path.write_text(json.dumps(legacy), encoding="utf-8")

    config = read_llm_config(Workspace())

    assert config["provider"] == "ollama"
    assert config["host"] == ""
    assert config["model"] == "local-model"
    assert Workspace().get("llm.provider") == "ollama"


def test_non_default_lmstudio_host_migrates_to_managed_ollama(monkeypatch, tmp_path: Path) -> None:
    _make_app(monkeypatch, tmp_path)
    from flinttrade_core.llm_config import read_llm_config
    from flinttrade_core.workspace import Workspace

    workspace = Workspace()
    legacy = workspace.as_dict()
    legacy["version"] = "1.1.0"
    legacy["llm"] = {
        "provider": "lmstudio",
        "host": "http://10.0.0.8:9000",
        "model": "remote-model",
    }
    workspace.config_path.write_text(json.dumps(legacy), encoding="utf-8")

    config = read_llm_config(Workspace())

    assert config["provider"] == "ollama"
    assert config["host"] == ""
    assert config["model"] == "remote-model"


def test_non_default_lmstudio_migration_retires_a_destination_bound_secret(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _make_app(monkeypatch, tmp_path)
    from flinttrade_core.llm_config import LLM_API_KEY_REF, read_llm_config, resolve_llm_api_key
    from flinttrade_core.secure_file import write_secret_text
    from flinttrade_core.workspace import Workspace

    workspace = Workspace()
    host = "http://10.0.0.8:9000"
    legacy = workspace.as_dict()
    legacy["version"] = "1.1.0"
    legacy["llm"] = {
        "provider": "lmstudio",
        "host": host,
        "model": "remote-model",
        "api_key_ref": LLM_API_KEY_REF,
        "api_key_provider": "lmstudio",
        "api_key_destination": host,
    }
    workspace.config_path.write_text(json.dumps(legacy), encoding="utf-8")
    write_secret_text(tmp_path / "secrets" / "llm_api_key", "legacy-secret")

    config = read_llm_config(Workspace())

    assert config["provider"] == "ollama"
    assert config["host"] == ""
    assert config["api_key_configured"] is False
    assert resolve_llm_api_key(Workspace()) == ""
    assert Workspace().get("llm.api_key_provider") == ""
    assert Workspace().get("llm.api_key_destination") == ""
    assert not (tmp_path / "secrets" / "llm_api_key").exists()


def test_ref_only_remote_lmstudio_migration_retires_secret_before_a_later_model_patch(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _make_app(monkeypatch, tmp_path)
    from flinttrade_core.llm_config import (
        LLM_API_KEY_REF,
        persist_llm_config,
        read_effective_llm_config,
    )
    from flinttrade_core.secure_file import write_secret_text
    from flinttrade_core.workspace import Workspace

    workspace = Workspace()
    host = "HTTPS://Models.Example.INVALID:443/API"
    legacy = workspace.as_dict()
    legacy["version"] = "1.1.0"
    legacy["llm"] = {
        "provider": "lmstudio",
        "host": host,
        "model": "remote-model",
        "api_key_ref": LLM_API_KEY_REF,
    }
    workspace.config_path.write_text(json.dumps(legacy), encoding="utf-8")
    write_secret_text(tmp_path / "secrets" / "llm_api_key", "legacy-secret")

    migrated = read_effective_llm_config(Workspace())
    patched = persist_llm_config({"model": "updated-model"}, Workspace())

    assert migrated == {
        "provider": "ollama",
        "host": "",
        "model": "remote-model",
        "api_key": "",
    }
    assert patched["model"] == "updated-model"
    assert patched["api_key_configured"] is False
    assert read_effective_llm_config(Workspace())["api_key"] == ""
    assert not (tmp_path / "secrets" / "llm_api_key").exists()


def test_current_workspace_cannot_lazily_reintroduce_lmstudio(monkeypatch, tmp_path: Path) -> None:
    _make_app(monkeypatch, tmp_path)
    from flinttrade_core.llm_config import read_effective_llm_config
    from flinttrade_core.workspace import Workspace

    workspace = Workspace()
    workspace.update(
        lambda config: config["llm"].update(
            {"provider": "lmstudio", "host": "http://127.0.0.1:1234"}
        )
    )

    with pytest.raises(ValueError, match="LM Studio is retired"):
        read_effective_llm_config(Workspace())

    assert Workspace().get("llm.provider") == "lmstudio"


def test_persistence_rejects_lmstudio_after_the_versioned_migration(monkeypatch, tmp_path: Path) -> None:
    _make_app(monkeypatch, tmp_path)
    from flinttrade_core.llm_config import persist_llm_config

    with pytest.raises(ValueError, match="LM Studio is retired"):
        persist_llm_config({"provider": "lmstudio", "host": "http://127.0.0.1:1234"})


def test_legacy_environment_default_is_rejected(monkeypatch, tmp_path: Path) -> None:
    _make_app(monkeypatch, tmp_path)
    monkeypatch.setenv("LLM_PROVIDER", "lmstudio")
    monkeypatch.setenv("LLM_HOST", "http://localhost:1234")
    from flinttrade_ai.llm_client import LLMConfig

    with pytest.raises(ValueError, match="LM Studio is retired"):
        LLMConfig.from_env()


def test_legacy_environment_custom_host_is_rejected(monkeypatch, tmp_path: Path) -> None:
    _make_app(monkeypatch, tmp_path)
    monkeypatch.setenv("LLM_PROVIDER", "lmstudio")
    monkeypatch.setenv("LLM_HOST", "http://10.0.0.8:9000/")
    from flinttrade_ai.llm_client import LLMConfig

    with pytest.raises(ValueError, match="LM Studio is retired"):
        LLMConfig.from_env()


def test_legacy_environment_unsafe_custom_host_is_still_rejected_as_retired(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _make_app(monkeypatch, tmp_path)
    monkeypatch.setenv("LLM_PROVIDER", "lmstudio")
    monkeypatch.setenv("LLM_HOST", "HTTPS://Models.Example.INVALID:443/API/?Token=X/")
    from flinttrade_ai.llm_client import LLMConfig

    with pytest.raises(ValueError, match="LM Studio is retired"):
        LLMConfig.from_env()


def test_claude_oauth_token_round_trips_through_the_operator_secret(monkeypatch, tmp_path: Path) -> None:
    # A Claude Code OAuth token is an operator-supplied secret carried by the
    # SAME file-backed LLM secret path as any API key — no keychain read, no
    # OAuth flow. It must persist/resolve verbatim, load via from_env, and be
    # recognised as an OAuth token by the client's classifier.
    _make_app(monkeypatch, tmp_path)
    from flinttrade_ai.llm_client import LLMConfig, is_anthropic_oauth_token
    from flinttrade_core.llm_config import persist_llm_config, resolve_llm_api_key

    token = "sk-ant-oat01-operator-supplied"
    persist_llm_config({"provider": "anthropic", "model": "claude-sonnet-4", "api_key": token})

    assert resolve_llm_api_key() == token

    cfg = LLMConfig.from_env()
    assert cfg.provider == "anthropic"
    assert cfg.api_key == token
    assert is_anthropic_oauth_token(cfg.api_key) is True


def test_concurrent_first_workspace_patches_do_not_reinitialise_over_a_completed_write(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    from flinttrade_core import llm_config
    from flinttrade_core.llm_config import persist_llm_config, read_effective_llm_config
    from flinttrade_core.workspace import Workspace

    original_update = Workspace.update
    original_transition_guard = llm_config.llm_config_transition_guard
    first_update_entered = threading.Event()
    second_transition_attempted = threading.Event()
    second_update_entered = threading.Event()
    release_first_update = threading.Event()
    overlap_barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def checked_update(self, updater):  # type: ignore[no-untyped-def]
        thread_name = threading.current_thread().name
        if thread_name == "first-workspace-writer" and not first_update_entered.is_set():
            first_update_entered.set()
            assert overlap_barrier.wait(timeout=2.0) in {0, 1}
            assert release_first_update.wait(timeout=2.0)
        elif thread_name == "overlapping-workspace-writer":
            second_update_entered.set()
        return original_update(self, updater)

    @contextmanager
    def checked_transition_guard(workspace=None):  # type: ignore[no-untyped-def]
        if threading.current_thread().name == "overlapping-workspace-writer":
            second_transition_attempted.set()
        with original_transition_guard(workspace):
            yield

    monkeypatch.setattr(Workspace, "update", checked_update)
    monkeypatch.setattr(llm_config, "llm_config_transition_guard", checked_transition_guard)

    def persist(payload: dict[str, str], *, overlap: bool = False) -> None:
        try:
            if overlap:
                assert overlap_barrier.wait(timeout=2.0) in {0, 1}
            persist_llm_config(payload, Workspace(tmp_path))
        except BaseException as exc:  # noqa: BLE001 - retained for the parent assertion
            errors.append(exc)

    first = threading.Thread(
        name="first-workspace-writer",
        target=persist,
        args=(
            {
                "provider": "custom",
                "host": "https://models.example.invalid",
                "api_key": "first-secret",
            },
        ),
    )
    overlapping = threading.Thread(
        name="overlapping-workspace-writer",
        target=persist,
        args=({"model": "late-model"},),
        kwargs={"overlap": True},
    )

    first.start()
    assert first_update_entered.wait(timeout=2.0)
    overlapping.start()
    assert second_transition_attempted.wait(timeout=2.0)
    assert second_update_entered.is_set() is False
    release_first_update.set()
    first.join(timeout=2.0)
    overlapping.join(timeout=2.0)

    assert first.is_alive() is False
    assert overlapping.is_alive() is False
    assert second_update_entered.is_set()
    assert errors == []
    assert read_effective_llm_config(Workspace(tmp_path)) == {
        "provider": "custom",
        "host": "https://models.example.invalid",
        "model": "late-model",
        "api_key": "first-secret",
    }


def test_llm_transition_snapshot_is_unredacted_and_rejects_a_bypass_write(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    from flinttrade_core.llm_config import (
        LLMConfigConflictError,
        llm_config_transition,
        persist_llm_config,
        read_effective_llm_config,
    )
    from flinttrade_core.workspace import Workspace

    persist_llm_config(
        {
            "provider": "custom",
            "host": "https://models.example.invalid",
            "model": "old-model",
            "api_key": "snapshot-secret",
        },
        Workspace(tmp_path),
    )

    with llm_config_transition(Workspace(tmp_path)) as transition:
        assert transition.snapshot.api_key == "snapshot-secret"
        assert "snapshot-secret" not in repr(transition.snapshot)
        Workspace(tmp_path).update(lambda config: config["llm"].update({"model": "bypass-model"}))

        with pytest.raises(LLMConfigConflictError, match="changed during transition"):
            transition.persist({"model": "transition-model"})

    effective = read_effective_llm_config(Workspace(tmp_path))
    assert effective["model"] == "bypass-model"
    assert effective["api_key"] == "snapshot-secret"


def test_llm_transition_guard_blocks_a_separate_process_writer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    from flinttrade_core.llm_config import llm_config_transition_guard, persist_llm_config
    from flinttrade_core.workspace import Workspace

    workspace = Workspace(tmp_path)
    persist_llm_config({"provider": "custom", "host": "https://models.example.invalid"}, workspace)
    started_path = tmp_path / "writer-started"
    completed_path = tmp_path / "writer-completed"
    environment = os.environ.copy()

    with llm_config_transition_guard(workspace):
        writer = subprocess.Popen(
            [
                sys.executable,
                "-c",
                _WRITE_LLM_CONFIG_AFTER_TRANSITION_LOCK,
                str(tmp_path),
                str(started_path),
                str(completed_path),
            ],
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        deadline = time.monotonic() + 2.0
        while not started_path.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert started_path.exists()
        time.sleep(0.1)
        assert completed_path.exists() is False
        assert writer.poll() is None

    stdout, stderr = writer.communicate(timeout=5.0)
    assert writer.returncode == 0, stdout + stderr
    assert completed_path.exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX hard-link lock-path assertion")
@pytest.mark.parametrize("lock_name", [".llm-config.lock", ".llm-config-transition.lock"])
def test_llm_config_locks_reject_hard_links_without_truncating_the_target(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    lock_name: str,
) -> None:
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    from flinttrade_core.llm_config import llm_config_transition_guard, read_effective_llm_config
    from flinttrade_core.workspace import Workspace

    target = tmp_path / "outside.txt"
    target.write_text("do-not-truncate", encoding="utf-8")
    try:
        os.link(target, tmp_path / lock_name)
    except OSError:
        pytest.skip("hard links are unavailable on this platform")

    with pytest.raises(RuntimeError, match="lock path is unsafe"):
        if lock_name == ".llm-config.lock":
            read_effective_llm_config(Workspace(tmp_path))
        else:
            with llm_config_transition_guard(Workspace(tmp_path)):
                pytest.fail("an unsafe transition lock must never be acquired")

    assert target.read_text(encoding="utf-8") == "do-not-truncate"
