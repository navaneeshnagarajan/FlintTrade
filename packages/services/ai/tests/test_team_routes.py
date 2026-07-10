"""Tests for packages/services/ai/src/team_routes.py (Flask Blueprint).

Covers:
  POST /api/v1/ai/team/analyse  — happy path, missing fields, LLM absent
  GET  /api/v1/ai/team/config   — with and without team
  POST /api/v1/ai/team/config   — valid payload, missing agents, LLM absent

The module-level _team_instance singleton is reset between tests.
"""

from __future__ import annotations

import asyncio
import json
import threading
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from flask import Flask


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_team() -> MagicMock:
    """Build a mock AgentTeam with the full interface.

    Returns:
        MagicMock representing an AgentTeam.
    """
    team = MagicMock()

    analysis = MagicMock()
    analysis.to_dict.return_value = {
        "symbol": "NIFTY",
        "agents": [],
        "consensus": "BUY",
    }
    team.analyse.return_value = analysis
    team.analyse_async = AsyncMock(return_value=analysis)

    recommendation = MagicMock()
    recommendation.to_dict.return_value = {
        "action": "BUY",
        "confidence": 0.75,
        "reasoning": "Bullish consensus",
    }
    team.get_recommendation.return_value = recommendation

    team.get_config.return_value = {"agents": []}
    return team


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_team_singleton():
    """Reset the module-level team singleton before and after each test.

    This ensures tests do not bleed state into each other via the singleton.
    """
    import flinttrade_ai.team_routes as _mod
    _mod._team_instance = None
    yield
    _mod._team_instance = None


@pytest.fixture()
def app():
    """Flask test app with team_bp registered.

    Yields:
        Flask application instance.
    """
    from flinttrade_ai.team_routes import team_bp

    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(team_bp)
    return flask_app


@pytest.fixture()
def client(app):
    """Flask test client.

    Args:
        app: Flask application fixture.

    Returns:
        Test client.
    """
    return app.test_client()


# ---------------------------------------------------------------------------
# POST /api/v1/ai/team/analyse
# ---------------------------------------------------------------------------


class TestTeamAnalyse:
    def test_no_llm_returns_503(self, client) -> None:
        """Missing LLM configuration returns HTTP 503.

        Args:
            client: Flask test client.
        """
        with patch("flinttrade_ai.team_routes._get_team", return_value=None):
            resp = client.post(
                "/api/v1/ai/team/analyse",
                json={"symbol": "NIFTY", "exchange": "NSE_INDEX"},
            )
        assert resp.status_code == 503
        assert resp.get_json()["status"] == "error"

    def test_missing_symbol_returns_400(self, client) -> None:
        """Missing symbol field returns HTTP 400.

        Args:
            client: Flask test client.
        """
        team = _make_team()
        with patch("flinttrade_ai.team_routes._get_team", return_value=team):
            resp = client.post(
                "/api/v1/ai/team/analyse",
                json={"exchange": "NSE_INDEX"},
            )
        assert resp.status_code == 400
        assert "symbol" in resp.get_json()["message"]

    def test_missing_exchange_returns_400(self, client) -> None:
        """Missing exchange field returns HTTP 400.

        Args:
            client: Flask test client.
        """
        team = _make_team()
        with patch("flinttrade_ai.team_routes._get_team", return_value=team):
            resp = client.post(
                "/api/v1/ai/team/analyse",
                json={"symbol": "NIFTY"},
            )
        assert resp.status_code == 400
        assert "exchange" in resp.get_json()["message"]

    def test_analyse_success(self, client) -> None:
        """Valid payload with mocked team returns 200 with analysis and recommendation.

        Args:
            client: Flask test client.
        """
        team = _make_team()
        with patch("flinttrade_ai.team_routes._get_team", return_value=team):
            resp = client.post(
                "/api/v1/ai/team/analyse",
                json={"symbol": "NIFTY", "exchange": "NSE_INDEX"},
            )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert "analysis" in data["data"]
        assert "recommendation" in data["data"]
        assert data["data"]["recommendation"]["action"] == "BUY"
        team.analyse_async.assert_awaited_once()
        team.analyse.assert_not_called()

    def test_analyse_sanitises_analysis_errors(self, client) -> None:
        """Raw analysis exception details are not returned by the team route."""
        team = _make_team()
        team.analyse_async.return_value.to_dict.return_value = {
            "symbol": "NIFTY",
            "exchange": "NSE_INDEX",
            "agent_analyses": [
                {
                    "agent_name": "Technical Analyst",
                    "role_type": "technical",
                    "report": "",
                    "signal": "HOLD",
                    "confidence": 0.0,
                    "timestamp": "2026-07-03T00:00:00+00:00",
                    "error": "Traceback: /Users/example/.env token failed",
                }
            ],
            "consensus_signal": "HOLD",
            "consensus_confidence": 0.0,
            "consensus_reasoning": "Fallback",
            "timestamp": "2026-07-03T00:00:00+00:00",
            "errors": ["Technical Analyst: /Users/example/.env token failed"],
        }
        with patch("flinttrade_ai.team_routes._get_team", return_value=team):
            resp = client.post(
                "/api/v1/ai/team/analyse",
                json={"symbol": "NIFTY", "exchange": "NSE_INDEX"},
            )
        assert resp.status_code == 200
        body = resp.get_json()
        analysis = body["data"]["analysis"]
        assert analysis["errors"] == ["Analysis failed"]
        assert analysis["agent_analyses"][0]["error"] == "Analysis failed"
        assert "Traceback" not in str(body)
        assert "/Users/example" not in str(body)

    def test_team_exception_returns_500(self, client) -> None:
        """Exception inside team.analyse_async surfaces as HTTP 500.

        Args:
            client: Flask test client.
        """
        team = _make_team()
        team.analyse_async.side_effect = RuntimeError("LLM timeout")
        with patch("flinttrade_ai.team_routes._get_team", return_value=team):
            resp = client.post(
                "/api/v1/ai/team/analyse",
                json={"symbol": "NIFTY", "exchange": "NSE_INDEX"},
            )
        assert resp.status_code == 500

    def test_value_error_does_not_expose_analysis_details(self, client) -> None:
        team = _make_team()
        secret = "provider failed with token at /Users/private/.env"
        team.analyse_async.side_effect = ValueError(secret)

        with patch("flinttrade_ai.team_routes._get_team", return_value=team):
            resp = client.post(
                "/api/v1/ai/team/analyse",
                json={"symbol": "NIFTY", "exchange": "NSE_INDEX"},
            )

        assert resp.status_code == 500
        assert secret not in resp.get_data(as_text=True)

    def test_analyse_forwards_mode_preset_and_execution_limits(self, client) -> None:
        team = _make_team()
        body = {
            "symbol": "NIFTY",
            "exchange": "NSE_INDEX",
            "market_data": {"vix": 14},
            "mode": "dag",
            "preset": "derivatives_desk",
            "debate_rounds": 3,
            "max_concurrent": 2,
            "task_timeout_seconds": 30,
        }

        with patch("flinttrade_ai.team_routes._get_team", return_value=team):
            resp = client.post("/api/v1/ai/team/analyse", json=body)

        assert resp.status_code == 200
        team.analyse_async.assert_awaited_once_with(
            "NIFTY",
            "NSE_INDEX",
            {"vix": 14},
            mode="dag",
            preset="derivatives_desk",
            use_active_preset=False,
            debate_rounds=3,
            max_concurrent=2,
            task_timeout_seconds=30,
        )
        team.analyse.assert_not_called()

    @pytest.mark.parametrize(
        ("body_preset", "include_key", "use_active_preset"),
        [
            (None, False, True),
            (None, True, False),
        ],
    )
    def test_analyse_distinguishes_omitted_and_null_preset(
        self,
        client,
        body_preset,
        include_key,
        use_active_preset,
    ) -> None:
        team = _make_team()
        body = {"symbol": "NIFTY", "exchange": "NSE_INDEX", "mode": "flat"}
        if include_key:
            body["preset"] = body_preset

        with patch("flinttrade_ai.team_routes._get_team", return_value=team):
            resp = client.post("/api/v1/ai/team/analyse", json=body)

        assert resp.status_code == 200
        assert team.analyse_async.await_args.kwargs["preset"] is None
        assert team.analyse_async.await_args.kwargs["use_active_preset"] is use_active_preset

    @pytest.mark.parametrize("mode", ["sequential", "debate"])
    def test_named_preset_is_rejected_for_fixed_mode(self, client, mode) -> None:
        team = _make_team()

        with patch("flinttrade_ai.team_routes._get_team", return_value=team):
            resp = client.post(
                "/api/v1/ai/team/analyse",
                json={
                    "symbol": "NIFTY",
                    "exchange": "NSE_INDEX",
                    "mode": mode,
                    "preset": "derivatives_desk",
                },
            )

        assert resp.status_code == 400
        assert resp.get_json()["message"] == "preset is not supported for sequential or debate modes"
        team.analyse_async.assert_not_awaited()

    @pytest.mark.parametrize(
        "body",
        [
            {"symbol": 123, "exchange": "NSE"},
            {"symbol": "NIFTY", "exchange": "NSE_INDEX", "market_data": []},
            {"symbol": "NIFTY", "exchange": "NSE_INDEX", "mode": "unknown"},
            {"symbol": "NIFTY", "exchange": "NSE_INDEX", "debate_rounds": 0},
            {"symbol": "NIFTY", "exchange": "NSE_INDEX", "max_concurrent": 0},
            {"symbol": "NIFTY", "exchange": "NSE_INDEX", "task_timeout_seconds": 0},
        ],
    )
    def test_invalid_analysis_request_returns_400(self, client, body) -> None:
        with patch("flinttrade_ai.team_routes._get_team", return_value=_make_team()):
            resp = client.post("/api/v1/ai/team/analyse", json=body)

        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# GET /api/v1/ai/team/config
# ---------------------------------------------------------------------------


class TestTeamConfigGet:
    def test_config_with_no_team_returns_defaults(self, client) -> None:
        """When team is None (LLM unconfigured), default agents are returned.

        Args:
            client: Flask test client.
        """
        mock_default_agents: list = []
        with (
            patch("flinttrade_ai.team_routes._get_team", return_value=None),
            patch("flinttrade_ai.multi_agent.default_agents", return_value=mock_default_agents),
        ):
            resp = client.get("/api/v1/ai/team/config")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert "agents" in data["data"]
        assert data["data"]["custom_agents"] == data["data"]["agents"]
        assert data["data"]["modes"] == ["flat", "dag", "sequential", "debate"]
        assert len(data["data"]["presets"]) == 10

    def test_config_with_team_configured(self, client) -> None:
        """When team is available, its get_config() is returned.

        Args:
            client: Flask test client.
        """
        team = _make_team()
        with patch("flinttrade_ai.team_routes._get_team", return_value=team):
            resp = client.get("/api/v1/ai/team/config")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert "agents" in data["data"]


# ---------------------------------------------------------------------------
# POST /api/v1/ai/team/config
# ---------------------------------------------------------------------------


class TestTeamConfigUpdate:
    def test_no_llm_returns_503(self, client) -> None:
        """Missing LLM returns 503 for config update.

        Args:
            client: Flask test client.
        """
        with patch("flinttrade_ai.team_routes._get_team", return_value=None):
            resp = client.post(
                "/api/v1/ai/team/config",
                json={"agents": [{"name": "analyst"}]},
            )
        assert resp.status_code == 503

    def test_missing_agents_returns_400(self, client) -> None:
        """Missing agents list returns HTTP 400.

        Args:
            client: Flask test client.
        """
        team = _make_team()
        with patch("flinttrade_ai.team_routes._get_team", return_value=team):
            resp = client.post("/api/v1/ai/team/config", json={})
        assert resp.status_code == 400
        assert "agents" in resp.get_json()["message"]

    def test_update_config_success(self, client) -> None:
        """Valid agents payload calls team.update_config and returns new config.

        Args:
            client: Flask test client.
        """
        team = _make_team()
        with patch("flinttrade_ai.team_routes._get_team", return_value=team):
            resp = client.post(
                "/api/v1/ai/team/config",
                json={"agents": [{"name": "analyst", "role_type": "MARKET"}]},
            )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        team.update_config.assert_called_once()

    def test_preset_update_is_accepted_without_agents(self, client) -> None:
        team = _make_team()
        with patch("flinttrade_ai.team_routes._get_team", return_value=team):
            resp = client.post(
                "/api/v1/ai/team/config",
                json={"preset": "derivatives_desk"},
            )

        assert resp.status_code == 200
        team.update_config.assert_called_once_with({"preset": "derivatives_desk"})

    def test_invalid_config_does_not_expose_internal_details(self, client) -> None:
        team = _make_team()
        secret = "invalid token at /Users/private/.env"
        team.update_config.side_effect = ValueError(secret)

        with patch("flinttrade_ai.team_routes._get_team", return_value=team):
            resp = client.post(
                "/api/v1/ai/team/config",
                json={"preset": "derivatives_desk"},
            )

        assert resp.status_code == 400
        assert resp.get_json()["message"] == "Invalid team configuration"
        assert secret not in resp.get_data(as_text=True)


class TestTeamAnalyseStream:
    def test_stream_emits_lifecycle_result_and_done_frames(self, client) -> None:
        from flinttrade_ai._team_dag import TeamEvent

        team = _make_team()

        async def analyse_async(*args, on_event=None, **kwargs):
            assert on_event is not None
            await on_event(
                TeamEvent(
                    task_id="technical_analyst",
                    agent_role="technical",
                    event_type="completed",
                    data={"result_preview": "Bullish"},
                )
            )
            return team.analyse.return_value

        team.analyse_async.side_effect = analyse_async
        with patch("flinttrade_ai.team_routes._get_team", return_value=team):
            resp = client.post(
                "/api/v1/ai/team/analyse/stream",
                json={"symbol": "NIFTY", "exchange": "NSE_INDEX", "mode": "flat"},
            )

        assert resp.status_code == 200
        assert resp.content_type.startswith("text/event-stream")
        frames = [
            json.loads(line.removeprefix("data: "))
            for line in resp.get_data(as_text=True).splitlines()
            if line.startswith("data: ")
        ]
        assert [frame["type"] for frame in frames] == ["event", "result", "done"]
        assert frames[0]["event"]["event_type"] == "completed"
        assert frames[1]["data"]["recommendation"]["action"] == "BUY"

    def test_stream_redacts_worker_exception_details(self, client) -> None:
        team = _make_team()
        secret = "token leaked at /Users/private/.env"

        async def fail(*args, **kwargs):
            raise RuntimeError(secret)

        team.analyse_async.side_effect = fail
        with patch("flinttrade_ai.team_routes._get_team", return_value=team):
            resp = client.post(
                "/api/v1/ai/team/analyse/stream",
                json={"symbol": "NIFTY", "exchange": "NSE_INDEX"},
            )

        body = resp.get_data(as_text=True)
        assert '"type": "error"' in body
        assert "Analysis failed" in body
        assert secret not in body

    def test_stream_forwards_explicit_null_as_custom_roster_override(self, client) -> None:
        team = _make_team()
        forwarded: dict[str, object] = {}

        async def analyse_async(*_args, **kwargs):
            forwarded.update(kwargs)
            return team.analyse.return_value

        team.analyse_async.side_effect = analyse_async
        with patch("flinttrade_ai.team_routes._get_team", return_value=team):
            resp = client.post(
                "/api/v1/ai/team/analyse/stream",
                json={
                    "symbol": "NIFTY",
                    "exchange": "NSE_INDEX",
                    "preset": None,
                },
            )

        resp.get_data(as_text=True)
        assert forwarded["preset"] is None
        assert forwarded["use_active_preset"] is False

    def test_stream_disconnect_cancels_pending_analysis(self, client) -> None:
        team = _make_team()
        started = threading.Event()
        cancelled = threading.Event()

        async def pending(*args, **kwargs):
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        team.analyse_async.side_effect = pending
        with patch("flinttrade_ai.team_routes._get_team", return_value=team):
            response = client.post(
                "/api/v1/ai/team/analyse/stream",
                json={"symbol": "NIFTY", "exchange": "NSE_INDEX"},
                buffered=False,
            )
            assert started.wait(timeout=1)
            response.close()

        assert cancelled.wait(timeout=1)
