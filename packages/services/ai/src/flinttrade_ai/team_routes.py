"""Flask blueprint for multi-agent team endpoints.

Endpoints:
- POST /api/v1/ai/team/analyse — run team analysis on a symbol
- GET  /api/v1/ai/team/config  — get current team configuration
- POST /api/v1/ai/team/config  — update team configuration
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
import json
import logging
import queue
import threading
from typing import Any

from flask import Blueprint, Response, jsonify, request, stream_with_context

from .llm_client import LLMClient, LLMConfig

logger = logging.getLogger("flinttrade.ai.team")

team_bp = Blueprint("ai_team", __name__, url_prefix="/api/v1/ai/team")

_PUBLIC_ANALYSIS_ERROR = "Analysis failed"
_STREAM_POLL_SECONDS = 0.1

# Module-level singleton — created on first use, re-used across requests.
_team_instance = None
_team_lock = threading.Lock()


def _get_team():
    """Lazy-initialise the AgentTeam singleton."""
    global _team_instance  # noqa: PLW0603
    if _team_instance is None:
        with _team_lock:
            if _team_instance is None:
                from .multi_agent import AgentTeam  # noqa: PLC0415

                cfg = LLMConfig.from_env()
                if not cfg.provider:
                    return None
                client = LLMClient(config=cfg)
                _team_instance = AgentTeam(llm_client=client)
    return _team_instance


def _reset_team() -> None:
    """Reset the singleton (used after config updates)."""
    global _team_instance  # noqa: PLW0603
    with _team_lock:
        _team_instance = None


def _positive_int(body: dict[str, Any], key: str, default: int, maximum: int) -> int | None:
    """Read one bounded positive integer, rejecting booleans and coercion."""
    value = body.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        return None
    return value


def _parse_analysis_request(body: Any) -> tuple[dict[str, Any] | None, str | None]:
    """Validate the shared JSON/SSE analysis request without side effects."""
    from .multi_agent import AgentTeam  # noqa: PLC0415

    if not isinstance(body, dict):
        return None, "request body must be a JSON object"
    symbol = body.get("symbol", "")
    exchange = body.get("exchange", "")
    if not isinstance(symbol, str) or not symbol.strip():
        return None, "symbol is required"
    if not isinstance(exchange, str) or not exchange.strip():
        return None, "exchange is required"

    market_data = body.get("market_data")
    if market_data is not None and not isinstance(market_data, dict):
        return None, "market_data must be an object"
    mode = body.get("mode", "flat")
    if not isinstance(mode, str) or mode not in AgentTeam.available_modes():
        return None, "mode is invalid"
    preset_provided = "preset" in body
    preset = body.get("preset")
    if preset is not None and (not isinstance(preset, str) or not preset.strip()):
        return None, "preset must be a non-empty string"
    if preset is not None and mode in {"sequential", "debate"}:
        return None, "preset is not supported for sequential or debate modes"

    debate_rounds = _positive_int(body, "debate_rounds", 2, 5)
    max_concurrent = _positive_int(body, "max_concurrent", 4, 16)
    task_timeout_seconds = _positive_int(body, "task_timeout_seconds", 120, 300)
    if debate_rounds is None:
        return None, "debate_rounds must be between 1 and 5"
    if max_concurrent is None:
        return None, "max_concurrent must be between 1 and 16"
    if task_timeout_seconds is None:
        return None, "task_timeout_seconds must be between 1 and 300"

    return {
        "symbol": symbol.strip(),
        "exchange": exchange.strip(),
        "market_data": dict(market_data) if market_data is not None else None,
        "mode": mode,
        "preset": preset.strip() if preset is not None else None,
        "use_active_preset": not preset_provided,
        "debate_rounds": debate_rounds,
        "max_concurrent": max_concurrent,
        "task_timeout_seconds": task_timeout_seconds,
    }, None


def _public_agent_analysis_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return one agent-analysis payload with exception details removed."""
    public_payload = dict(payload)
    if public_payload.get("error"):
        public_payload["error"] = _PUBLIC_ANALYSIS_ERROR
    return public_payload


def _public_team_analysis_payload(result: Any) -> dict[str, Any]:
    """Build a public TeamAnalysis payload without raw exception messages."""
    raw = result.to_dict()
    payload = dict(raw) if isinstance(raw, dict) else {}

    agent_analyses = payload.get("agent_analyses", [])
    if isinstance(agent_analyses, list):
        payload["agent_analyses"] = [
            _public_agent_analysis_payload(analysis)
            for analysis in agent_analyses
            if isinstance(analysis, dict)
        ]
    else:
        payload["agent_analyses"] = []

    errors = payload.get("errors", [])
    if isinstance(errors, list):
        payload["errors"] = [_PUBLIC_ANALYSIS_ERROR for error in errors if error]
    else:
        payload["errors"] = []
    return payload


def _team_result_payload(team: Any, result: Any) -> dict[str, Any]:
    """Build the stable analysis/recommendation response data."""
    recommendation = team.get_recommendation(result)
    return {
        "analysis": _public_team_analysis_payload(result),
        "recommendation": recommendation.to_dict(),
    }


@team_bp.route("/analyse", methods=["POST"])
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

    analysis_request, validation_error = _parse_analysis_request(request.get_json(silent=True))
    if analysis_request is None:
        return jsonify({"status": "error", "message": validation_error}), 400

    try:
        result = asyncio.run(
            team.analyse_async(
                analysis_request["symbol"],
                analysis_request["exchange"],
                analysis_request["market_data"],
                mode=analysis_request["mode"],
                preset=analysis_request["preset"],
                use_active_preset=analysis_request["use_active_preset"],
                debate_rounds=analysis_request["debate_rounds"],
                max_concurrent=analysis_request["max_concurrent"],
                task_timeout_seconds=analysis_request["task_timeout_seconds"],
            )
        )
        return jsonify({
            "status": "success",
            "data": _team_result_payload(team, result),
        }), 200
    except Exception:
        logger.exception("team_analyze error")
        return jsonify({"status": "error", "message": "Internal server error"}), 500


@team_bp.route("/analyse/stream", methods=["POST"])
def team_analyze_stream() -> Response | tuple[Any, int]:
    """Stream lifecycle events and the canonical team result over SSE."""
    team = _get_team()
    if team is None:
        return jsonify({
            "status": "error",
            "message": "LLM not configured. Multi-agent analysis requires an LLM provider.",
        }), 503

    analysis_request, validation_error = _parse_analysis_request(request.get_json(silent=True))
    if analysis_request is None:
        return jsonify({"status": "error", "message": validation_error}), 400

    messages: queue.Queue[tuple[str, Any]] = queue.Queue()
    disconnected = threading.Event()

    def worker() -> None:
        async def run() -> None:
            async def on_event(event: Any) -> None:
                if not disconnected.is_set():
                    messages.put(("event", event.model_dump(mode="json")))

            analysis_task = asyncio.create_task(
                team.analyse_async(
                    analysis_request["symbol"],
                    analysis_request["exchange"],
                    analysis_request["market_data"],
                    mode=analysis_request["mode"],
                    preset=analysis_request["preset"],
                    use_active_preset=analysis_request["use_active_preset"],
                    debate_rounds=analysis_request["debate_rounds"],
                    max_concurrent=analysis_request["max_concurrent"],
                    task_timeout_seconds=analysis_request["task_timeout_seconds"],
                    on_event=on_event,
                )
            )
            while not analysis_task.done():
                if disconnected.is_set():
                    analysis_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await analysis_task
                    return
                try:
                    await asyncio.wait_for(
                        asyncio.shield(analysis_task),
                        timeout=_STREAM_POLL_SECONDS,
                    )
                except TimeoutError:
                    continue

            result = analysis_task.result()
            if not disconnected.is_set():
                messages.put(("result", _team_result_payload(team, result)))

        try:
            asyncio.run(run())
        except Exception:
            logger.exception("team_analyze_stream worker error")
            if not disconnected.is_set():
                messages.put(("error", _PUBLIC_ANALYSIS_ERROR))
        finally:
            if not disconnected.is_set():
                messages.put(("done", None))

    threading.Thread(target=worker, name="flinttrade-team-analysis", daemon=True).start()

    @stream_with_context
    def generate():
        try:
            while True:
                try:
                    frame_type, payload = messages.get(timeout=_STREAM_POLL_SECONDS)
                except queue.Empty:
                    yield ": keep-alive\n\n"
                    continue
                if frame_type == "event":
                    frame = {"type": "event", "event": payload}
                elif frame_type == "result":
                    frame = {"type": "result", "data": payload}
                elif frame_type == "error":
                    frame = {"type": "error", "message": payload}
                else:
                    yield f"data: {json.dumps({'type': 'done'})}\n\n"
                    break
                yield f"data: {json.dumps(frame)}\n\n"
        finally:
            disconnected.set()

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
        from .multi_agent import AgentTeam, default_agents  # noqa: PLC0415
        agents = [agent.to_dict() for agent in default_agents()]
        return jsonify({
            "status": "success",
            "data": {
                "agents": agents,
                "custom_agents": agents,
                "modes": AgentTeam.available_modes(),
                "presets": AgentTeam.available_presets(),
                "active_preset": "",
            },
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

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"status": "error", "message": "request body must be a JSON object"}), 400
    has_agents = isinstance(body.get("agents"), list) and bool(body["agents"])
    has_preset = isinstance(body.get("preset"), str) and bool(body["preset"].strip())
    if has_agents == has_preset:
        return jsonify({"status": "error", "message": "provide either agents or preset"}), 400

    try:
        team.update_config(body)
        return jsonify({
            "status": "success",
            "data": team.get_config(),
        }), 200
    except (KeyError, TypeError, ValueError):
        return jsonify({"status": "error", "message": "Invalid team configuration"}), 400
    except Exception:
        logger.exception("team_config_update error")
        return jsonify({"status": "error", "message": "Internal server error"}), 500
