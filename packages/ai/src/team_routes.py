"""Flask blueprint for multi-agent team endpoints.

Endpoints:
- POST /api/v1/ai/team/analyze — run team analysis on a symbol
- GET  /api/v1/ai/team/config  — get current team configuration
- POST /api/v1/ai/team/config  — update team configuration
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, jsonify, request

from packages.ai.src.llm_client import LLMClient, LLMConfig

logger = logging.getLogger("flinttrade.ai.team")

team_bp = Blueprint("ai_team", __name__, url_prefix="/api/v1/ai/team")

# Module-level singleton — created on first use, re-used across requests.
_team_instance = None


def _get_team():
    """Lazy-initialise the AgentTeam singleton."""
    global _team_instance  # noqa: PLW0603
    if _team_instance is None:
        from packages.ai.src.multi_agent import AgentTeam  # noqa: PLC0415

        cfg = LLMConfig.from_env()
        if not cfg.provider:
            return None
        client = LLMClient(config=cfg)
        _team_instance = AgentTeam(llm_client=client)
    return _team_instance


def _reset_team() -> None:
    """Reset the singleton (used after config updates)."""
    global _team_instance  # noqa: PLW0603
    _team_instance = None


@team_bp.route("/analyze", methods=["POST"])
def team_analyze() -> tuple[Any, int]:
    """Run multi-agent team analysis on a symbol.

    Request JSON:
        symbol (str): Instrument symbol (e.g. "NIFTY", "RELIANCE").
        exchange (str): Exchange code (e.g. "NSE_INDEX", "NSE", "NFO").
        market_data (dict, optional): Additional market context.

    Returns:
        JSON with ``status`` and ``data`` containing the full
        ``TeamAnalysis`` (agent reports + consensus) and a simplified
        ``recommendation``.
    """
    team = _get_team()
    if team is None:
        return jsonify({
            "status": "error",
            "message": "LLM not configured. Multi-agent analysis requires an LLM provider.",
        }), 503

    body = request.get_json(silent=True) or {}
    symbol: str = body.get("symbol", "").strip()
    exchange: str = body.get("exchange", "").strip()
    market_data: dict[str, Any] | None = body.get("market_data")

    if not symbol:
        return jsonify({"status": "error", "message": "symbol is required"}), 400
    if not exchange:
        return jsonify({"status": "error", "message": "exchange is required"}), 400

    try:
        result = team.analyze(symbol, exchange, market_data)
        recommendation = team.get_recommendation(result)

        return jsonify({
            "status": "success",
            "data": {
                "analysis": result.to_dict(),
                "recommendation": recommendation.to_dict(),
            },
        }), 200
    except Exception:
        logger.exception("team_analyze error")
        return jsonify({"status": "error", "message": "Internal server error"}), 500


@team_bp.route("/config", methods=["GET"])
def team_config_get() -> tuple[Any, int]:
    """Return the current agent team configuration.

    Returns:
        JSON with ``status`` and ``data`` containing the list of
        agent roles and their settings.
    """
    team = _get_team()
    if team is None:
        # Return default config even if LLM is not configured
        from packages.ai.src.multi_agent import default_agents  # noqa: PLC0415
        return jsonify({
            "status": "success",
            "data": {"agents": [a.to_dict() for a in default_agents()]},
        }), 200

    return jsonify({
        "status": "success",
        "data": team.get_config(),
    }), 200


@team_bp.route("/config", methods=["POST"])
def team_config_update() -> tuple[Any, int]:
    """Update the agent team configuration.

    Request JSON:
        agents (list[dict]): List of agent role definitions.
            Each dict should contain: name, role_type, system_prompt,
            enabled (optional), temperature (optional).

    Returns:
        JSON with ``status`` and the updated configuration.
    """
    team = _get_team()
    if team is None:
        return jsonify({
            "status": "error",
            "message": "LLM not configured. Cannot update team configuration.",
        }), 503

    body = request.get_json(silent=True) or {}
    if not body.get("agents"):
        return jsonify({"status": "error", "message": "agents list is required"}), 400

    try:
        team.update_config(body)
        return jsonify({
            "status": "success",
            "data": team.get_config(),
        }), 200
    except Exception:
        logger.exception("team_config_update error")
        return jsonify({"status": "error", "message": "Internal server error"}), 500
