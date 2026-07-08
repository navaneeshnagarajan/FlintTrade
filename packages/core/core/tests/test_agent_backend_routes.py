"""End-to-end route tests for the agent-backend layer (replaces OpenClaw).

These prove the ``/api/v1/ai/agents/*`` endpoints are actually WIRED through the
Flask app — the backends list reports live detection status, an uninstalled CLI
agent fails honestly (never a fake stream), and the SSE run endpoint forwards a
mocked session's ``AgentEvent`` stream. They also guard that no ``/ai/openclaw/*``
route and no ``openclaw_bridge`` module survive the removal.

    uv run pytest packages/core/core/tests/test_agent_backend_routes.py -v --import-mode=importlib
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit

_EXPECTED_IDS = {
    "claude-code",
    "claude-code-oauth",
    "cerebras",
    "codex",
    "antigravity",
    "hermes",
}
_VALID_STATUSES = {"not_installed", "needs_config", "installed", "ready"}


@pytest.fixture()
def client():
    from flask import Flask

    from flinttrade_core.operations_routes import operations_bp

    app = Flask(__name__)
    app.register_blueprint(operations_bp)  # carries its own /api/v1 url_prefix
    with app.test_client() as c:
        yield c


# ======================================================================
# GET /ai/agents/backends
# ======================================================================


def test_backends_route_lists_all_six_with_statuses(client) -> None:
    resp = client.get("/api/v1/ai/agents/backends")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"
    backends = body["data"]["backends"]
    assert len(backends) == 6
    assert {b["id"] for b in backends} == _EXPECTED_IDS
    for b in backends:
        # The frontend contract: id, display_name, kind, status (+ richer fields).
        assert b["id"] and b["display_name"] and b["kind"]
        assert b["status"] in _VALID_STATUSES


def test_backends_route_kinds_are_reported(client) -> None:
    resp = client.get("/api/v1/ai/agents/backends")
    kinds = {b["id"]: b["kind"] for b in resp.get_json()["data"]["backends"]}
    assert kinds["claude-code"] == "llm"
    assert kinds["cerebras"] == "llm"
    assert kinds["codex"] == "cli_agent"
    assert kinds["antigravity"] == "cli_agent"
    assert kinds["hermes"] == "acp_agent"


def test_backends_route_survives_detect_failure(client) -> None:
    # A detection crash must degrade to an honest per-backend status, not 500.
    with patch("flinttrade_ai.agent_backends.detect_backend", side_effect=RuntimeError("boom")):
        resp = client.get("/api/v1/ai/agents/backends")

    assert resp.status_code == 200
    statuses = {b["id"]: b["status"] for b in resp.get_json()["data"]["backends"]}
    assert statuses["claude-code"] == "needs_config"  # llm fallback
    assert statuses["codex"] == "not_installed"  # agent fallback


# ======================================================================
# POST /ai/agents/run — honest error cases
# ======================================================================


def test_run_requires_backend_id(client) -> None:
    resp = client.post("/api/v1/ai/agents/run", json={"prompt": "hi"})
    assert resp.status_code == 400
    assert "backend_id" in resp.get_json()["message"]


def test_run_requires_prompt(client) -> None:
    resp = client.post("/api/v1/ai/agents/run", json={"backend_id": "codex"})
    assert resp.status_code == 400
    assert "prompt" in resp.get_json()["message"]


def test_run_unknown_backend_404(client) -> None:
    resp = client.post("/api/v1/ai/agents/run", json={"backend_id": "nope", "prompt": "hi"})
    assert resp.status_code == 404
    assert "Unknown agent backend" in resp.get_json()["message"]


def test_run_llm_backend_points_to_advisor(client) -> None:
    resp = client.post("/api/v1/ai/agents/run", json={"backend_id": "claude-code", "prompt": "hi"})
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["code"] == "llm_backend_not_agent_run"
    assert "/api/v1/advisor" in body["message"]
    # It is a JSON error, never a stream.
    assert "text/event-stream" not in resp.content_type


def test_run_not_installed_cli_agent_fails_honestly(client) -> None:
    from flinttrade_ai.agent_backends import BackendStatus

    with patch(
        "flinttrade_ai.agent_backends.detect_backend",
        return_value=BackendStatus.NOT_INSTALLED,
    ):
        resp = client.post("/api/v1/ai/agents/run", json={"backend_id": "codex", "prompt": "hi"})

    assert resp.status_code == 503
    body = resp.get_json()
    assert body["code"] == "backend_not_installed"
    assert body["data"]["status"] == "not_installed"
    # Honest failure, not a fabricated stream.
    assert "text/event-stream" not in resp.content_type


# ======================================================================
# POST /ai/agents/run — SSE streaming from a mocked session
# ======================================================================


class _FakeSession:
    """A minimal in-process AgentSession that streams a fixed event script."""

    backend_id = "codex"

    def __init__(self) -> None:
        self.started = False
        self.closed = False

    async def ensure_started(self) -> None:
        self.started = True

    async def run_turn(self, prompt: str, on_event: Any = None) -> Any:
        from flinttrade_ai.agent_backends import AgentEvent, AgentEventKind

        await on_event(AgentEvent(AgentEventKind.OUTPUT, text=f"echo: {prompt}"))
        await on_event(AgentEvent(AgentEventKind.TOOL, text="$ ls", data={"tool": "exec_command"}))
        done = AgentEvent(
            AgentEventKind.DONE,
            text=f"echo: {prompt}",
            data={"final_text": f"echo: {prompt}", "tool_iterations": 1},
        )
        await on_event(done)
        return done

    async def close(self) -> None:
        self.closed = True


def test_run_streams_events_from_mocked_session(client) -> None:
    from flinttrade_ai.agent_backends import BackendStatus

    fake = _FakeSession()
    with (
        patch("flinttrade_ai.agent_backends.detect_backend", return_value=BackendStatus.READY),
        patch("flinttrade_ai.agent_backends.get_session", return_value=fake),
    ):
        resp = client.post("/api/v1/ai/agents/run", json={"backend_id": "codex", "prompt": "hi"})
        data = resp.get_data(as_text=True)

    assert resp.status_code == 200
    assert resp.content_type.startswith("text/event-stream")
    # Each AgentEvent is a JSON SSE frame; assert the full script streamed through.
    assert '"kind": "output"' in data
    assert '"kind": "tool"' in data
    assert '"kind": "done"' in data
    assert "echo: hi" in data
    # Frames use the SSE ``data:`` convention.
    assert data.startswith("data: ")
    assert fake.started and fake.closed


def test_run_stream_emits_terminal_done_on_unavailable(client) -> None:
    from flinttrade_ai.agent_backends import AgentBackendUnavailable, BackendStatus

    def _boom(*_a: Any, **_k: Any):
        raise AgentBackendUnavailable("codex", "could not launch 'codex': install it")

    with (
        patch("flinttrade_ai.agent_backends.detect_backend", return_value=BackendStatus.READY),
        patch("flinttrade_ai.agent_backends.get_session", side_effect=_boom),
    ):
        resp = client.post("/api/v1/ai/agents/run", json={"backend_id": "codex", "prompt": "hi"})
        data = resp.get_data(as_text=True)

    assert resp.status_code == 200
    # Honest: an error frame plus a guaranteed terminal done frame.
    assert '"kind": "error"' in data
    assert '"kind": "done"' in data
    assert "install it" in data


# ======================================================================
# Removal guards — no OpenClaw route or module survives
# ======================================================================


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/ai/openclaw/status",
        "/api/v1/ai/openclaw/agents",
        "/api/v1/ai/openclaw/agents/a-9/logs",
    ],
)
def test_no_openclaw_get_route_remains(client, path: str) -> None:
    assert client.get(path).status_code == 404


def test_no_openclaw_post_route_remains(client) -> None:
    assert client.post("/api/v1/ai/openclaw/agents", json={"name": "x"}).status_code == 404


def test_openclaw_bridge_module_is_removed() -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("flinttrade_ai.openclaw_bridge")


def test_openclaw_bridge_file_is_deleted() -> None:
    import flinttrade_ai

    pkg_dir = Path(flinttrade_ai.__file__).resolve().parent
    assert not (pkg_dir / "openclaw_bridge.py").exists()


def test_flinttrade_ai_no_longer_exports_openclaw() -> None:
    import flinttrade_ai

    assert not hasattr(flinttrade_ai, "OpenClawBridge")
    assert not hasattr(flinttrade_ai, "OpenClawAgent")
    # The agent-backend surface replaces it.
    assert hasattr(flinttrade_ai, "get_session")
    assert hasattr(flinttrade_ai, "detect_backend")
    assert hasattr(flinttrade_ai, "list_backends")
