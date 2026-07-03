"""Tests for packages/services/ai/src/team_routes.py (Flask Blueprint).

Covers:
  POST /api/v1/ai/team/analyse  — happy path, missing fields, LLM absent
  GET  /api/v1/ai/team/config   — with and without team
  POST /api/v1/ai/team/config   — valid payload, missing agents, LLM absent

The module-level _team_instance singleton is reset between tests.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

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

    def test_analyse_sanitises_analysis_errors(self, client) -> None:
        """Raw analysis exception details are not returned by the team route."""
        team = _make_team()
        team.analyse.return_value.to_dict.return_value = {
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
        """Exception inside team.analyse surfaces as HTTP 500.

        Args:
            client: Flask test client.
        """
        team = MagicMock()
        team.analyse.side_effect = RuntimeError("LLM timeout")
        with patch("flinttrade_ai.team_routes._get_team", return_value=team):
            resp = client.post(
                "/api/v1/ai/team/analyse",
                json={"symbol": "NIFTY", "exchange": "NSE_INDEX"},
            )
        assert resp.status_code == 500


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
