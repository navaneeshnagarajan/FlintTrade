"""Autonomous-agent control plane — start/stop/status over the gated path.

Endpoints (registered by ``create_flask_app``):

- ``POST /api/v1/ai/agent/start``  — start a trading session (202)
- ``POST /api/v1/ai/agent/stop``   — request a stop (square-off by default)
- ``GET  /api/v1/ai/agent/status`` — live session snapshot

Safety model (do not weaken):
    The :class:`~flinttrade_ai.autonomous_agent.AutonomousTrader` cannot place
    orders without an injected gated executor — this route is the ONLY place
    one is wired, and it wires :class:`GatedChildExecutor`, so every agent
    order runs SafetySystem L1–L5 → ``gate_order`` → ``BrokerRouter``.

    The agent runs as its OWN principal (``actor_type="agent"``,
    ``actor_id="autonomous-trader"``): the operator must explicitly add that
    actor id to ``workspace.json brokers.account_acls[broker][account]``
    before a single agent order can pass the router's ACL. The start route
    fails fast with that exact instruction instead of starting an agent whose
    every order would be refused.

    The feature is OFF by default — enable via workspace.json::

        "ai": {"autonomous_agent": {"enabled": true}}

    Live mode only; one session at a time.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime, timezone
from typing import Any

from flask import Blueprint, current_app, jsonify, request

logger = logging.getLogger("flinttrade.core.agent_routes")

agent_bp = Blueprint("agent_control", __name__, url_prefix="/api/v1/ai/agent")

_MODE_LIVE = "live"
_AGENT_ACTOR_ID = "autonomous-trader"

# Single-session runner state.
_RUNNER: dict[str, Any] = {}
_RUNNER_LOCK = threading.Lock()


def _reset_runner_for_tests() -> None:
    """Clear the runner state (test isolation helper)."""
    with _RUNNER_LOCK:
        _RUNNER.clear()


def _agent_flag_enabled() -> bool:
    """Live-read the ``ai.autonomous_agent.enabled`` workspace flag."""
    try:
        from .workspace import Workspace  # noqa: PLC0415

        return bool(Workspace().get("ai.autonomous_agent.enabled", False))
    except Exception:  # pragma: no cover — a broken workspace means disabled
        logger.warning("Could not read ai.autonomous_agent.enabled", exc_info=True)
        return False


def _acl_grants_agent(adapter_id: str, account_id: str) -> bool:
    """True when the agent actor id is in the account's ACL list."""
    try:
        from .app import _read_workspace_brokers  # noqa: PLC0415

        brokers = _read_workspace_brokers() or {}
        acls = brokers.get("account_acls", {}) or {}
        actors = (acls.get(adapter_id, {}) or {}).get(account_id, []) or []
        return _AGENT_ACTOR_ID in actors
    except Exception:  # pragma: no cover — unreadable ACLs fail closed
        logger.warning("Could not read brokers.account_acls", exc_info=True)
        return False


def _build_llm() -> Any:
    """Construct the configured LLM client (separated for test injection)."""
    from flinttrade_ai.llm_client import LLMClient  # noqa: PLC0415

    return LLMClient()


def _build_vault() -> Any | None:
    """Construct the Obsidian vault context when configured (best-effort)."""
    try:
        import os  # noqa: PLC0415

        if not os.environ.get("FLINTTRADE_OBSIDIAN_VAULT"):
            return None
        from flinttrade_ai.obsidian_bridge import ObsidianVault  # noqa: PLC0415

        return ObsidianVault()
    except Exception:  # pragma: no cover — the vault is never order-critical
        logger.warning("Obsidian vault unavailable for the agent", exc_info=True)
        return None


def _trader_factory(**kwargs: Any) -> Any:
    """Construct the AutonomousTrader (separated for test injection)."""
    from flinttrade_ai.autonomous_agent import AutonomousTrader  # noqa: PLC0415

    return AutonomousTrader(**kwargs)


def _snapshot() -> dict[str, Any]:
    """Serialise the runner + agent state for the status endpoint."""
    with _RUNNER_LOCK:
        trader = _RUNNER.get("trader")
        thread = _RUNNER.get("thread")
        started_at = _RUNNER.get("started_at", "")
        params = dict(_RUNNER.get("params", {}))

    running = bool(thread is not None and thread.is_alive())
    snap: dict[str, Any] = {
        "enabled": _agent_flag_enabled(),
        "running": running,
        "started_at": started_at,
        "params": params,
        "actor_id": _AGENT_ACTOR_ID,
    }
    if trader is not None:
        state = trader.state
        snap.update({
            "agent_status": str(getattr(trader.status, "value", trader.status)),
            "daily_pnl": state.daily_pnl,
            "cycle_count": state.cycle_count,
            "active_positions": dict(state.active_positions),
            "position_details": {k: dict(v) for k, v in state.position_details.items()},
            "trade_counts": dict(state.trade_counts),
            "last_signals": {k: str(v) for k, v in state.last_signals.items()},
            "squared_off": state.squared_off,
            "stop_loss_hit": state.stop_loss_hit,
        })
    return snap


@agent_bp.route("/start", methods=["POST"])
def start_agent() -> tuple[Any, int]:
    """Start an autonomous trading session as a background thread.

    Request JSON:
        symbols (list[str], required) · exchange (str, default "NSE") ·
        product (str, default "MIS") · max_position_size (int, default 1) ·
        stop_loss_pct / take_profit_pct (float) · daily_stop_loss (float) ·
        max_trades_per_symbol (int) · cycle_interval_sec (int) ·
        broker (str, default "openalgo") · account_id (str, default "default")

    Returns:
        202 with the initial snapshot; 400 (validation), 401 (no JWT),
        403 (disabled / not live / not unlocked / agent not in the ACL),
        409 (already running), 503 (routing/LLM unavailable).
    """
    from flinttrade_engine.request_context import RequestContext  # noqa: PLC0415
    from flinttrade_engine.safety import SafetyConfig, SafetySystem  # noqa: PLC0415

    from .order_routes import (  # noqa: PLC0415
        _decode_request_payload,
        _is_live_mode_unlocked,
        _record_trade_journal,
    )
    from .smart_order_routes import GatedChildExecutor  # noqa: PLC0415

    if not _agent_flag_enabled():
        return jsonify({
            "status": "error",
            "message": (
                "The autonomous agent is disabled. Enable it via workspace.json "
                "ai.autonomous_agent.enabled (it places real orders in live mode)."
            ),
        }), 403

    payload = _decode_request_payload()
    if not payload:
        return jsonify({
            "status": "error",
            "message": "Authentication required — provide a valid JWT",
        }), 401

    if payload.get("mode") != _MODE_LIVE:
        return jsonify({
            "status": "error",
            "message": "The autonomous agent trades live only — switch to live mode first.",
        }), 403

    if not _is_live_mode_unlocked():
        return jsonify({
            "status": "error",
            "message": "Live mode not unlocked — verify PIN first",
        }), 403

    router = current_app.config.get("BROKER_ROUTER")
    client = current_app.config.get("OPENALGO_CLIENT")
    if router is None or client is None:
        return jsonify({
            "status": "error",
            "message": (
                "Order routing unavailable — workspace.json brokers configuration is "
                "missing or invalid. Check the startup logs, then restart."
            ),
        }), 503

    body: dict[str, Any] = request.get_json(silent=True) or {}
    symbols = [str(s).strip().upper() for s in (body.get("symbols") or []) if str(s).strip()]
    exchange = str(body.get("exchange") or "NSE").strip().upper()
    product = str(body.get("product") or "MIS").strip().upper()
    adapter_id = str(body.get("broker") or "openalgo").strip().lower()
    account_id = str(body.get("account_id") or "default")
    if not symbols:
        return jsonify({"status": "error", "message": "symbols is required (non-empty list)"}), 400
    try:
        max_position_size = int(body.get("max_position_size") or 1)
        max_trades = int(body.get("max_trades_per_symbol") or 5)
        cycle_interval = int(body.get("cycle_interval_sec") or 60)
        stop_loss_pct = float(body.get("stop_loss_pct") or 2.0)
        take_profit_pct = float(body.get("take_profit_pct") or 4.0)
        daily_stop_loss = float(body.get("daily_stop_loss") or -10_000.0)
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "numeric agent parameters are invalid"}), 400
    if max_position_size <= 0 or max_trades <= 0 or cycle_interval <= 0:
        return jsonify({
            "status": "error",
            "message": "max_position_size, max_trades_per_symbol and cycle_interval_sec must be positive",
        }), 400

    # Fail fast on the ACL: the agent is its own principal, and an agent whose
    # every order would be refused must not start at all.
    if not _acl_grants_agent(adapter_id, account_id):
        return jsonify({
            "status": "error",
            "message": (
                f"The agent actor '{_AGENT_ACTOR_ID}' is not authorised for "
                f"{adapter_id}:{account_id}. Add it to workspace.json "
                f"brokers.account_acls['{adapter_id}']['{account_id}'] to grant access."
            ),
        }), 403

    with _RUNNER_LOCK:
        thread = _RUNNER.get("thread")
        if thread is not None and thread.is_alive():
            return jsonify({
                "status": "error",
                "message": "An agent session is already running — stop it first.",
            }), 409

    try:
        llm = _build_llm()
    except Exception as exc:
        return jsonify({
            "status": "error",
            "message": f"LLM client unavailable — configure a provider in Settings ({exc})",
        }), 503

    safety = current_app.config.get("SAFETY")
    if safety is None:
        safety = SafetySystem(SafetyConfig())

    request_ctx = RequestContext(
        jti=str(payload.get("jti") or ""),
        actor_type="agent",
        actor_id=_AGENT_ACTOR_ID,
        mode=_MODE_LIVE,
        selector=f"{adapter_id}:{account_id}",
    )

    journal_store = current_app.config.get("TRADE_STORAGE")
    app_obj = current_app._get_current_object()  # noqa: SLF001

    def _journal_write(order: Any, orderid: str) -> None:
        if journal_store is None:
            return
        with app_obj.app_context():
            _record_trade_journal(order, orderid, strategy="AutonomousAgent")

    # Mid-flight brake: the session outlives this HTTP request, so the
    # operator's logout / live→practice downgrade (both revoke the starting
    # jti) must stop the agent's ORDERS even while its analysis loop runs.
    # An unavailable revocation store fails CLOSED — this is a live order path.
    starting_jti = str(payload.get("jti") or "")

    def _pre_dispatch_check() -> str | None:
        try:
            from .auth_routes import _is_jti_revoked  # noqa: PLC0415

            if starting_jti and _is_jti_revoked(starting_jti):
                return "operator session revoked (logout or mode change)"
        except Exception:
            logger.exception("agent revocation check failed — refusing order (fail closed)")
            return "session revocation check unavailable"
        return None

    executor = GatedChildExecutor(
        safety=safety,
        router=router,
        request_ctx=request_ctx,
        adapter_id=adapter_id,
        account_id=account_id,
        audit=current_app.config.get("AUDIT"),
        journal_write=_journal_write,
        pre_dispatch_check=_pre_dispatch_check,
    )

    from flinttrade_ai.autonomous_agent import AgentConfig  # noqa: PLC0415

    config = AgentConfig(
        symbols=symbols,
        exchange=exchange,
        product=product,
        max_position_size=max_position_size,
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
        daily_stop_loss=daily_stop_loss,
        max_trades_per_symbol=max_trades,
        cycle_interval_sec=cycle_interval,
    )
    trader = _trader_factory(
        llm_client=llm,
        openalgo_client=client,
        config=config,
        vault=_build_vault(),
        order_executor=executor,
    )

    def _run() -> None:
        try:
            asyncio.run(trader.run_session())
        except Exception:  # pragma: no cover — session errors land in status
            logger.exception("Agent session crashed")

    session_thread = threading.Thread(target=_run, name="autonomous-agent", daemon=True)
    with _RUNNER_LOCK:
        _RUNNER.update({
            "trader": trader,
            "thread": session_thread,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "params": {
                "symbols": symbols, "exchange": exchange, "product": product,
                "broker": adapter_id, "account_id": account_id,
                "max_position_size": max_position_size,
                "cycle_interval_sec": cycle_interval,
            },
        })
    session_thread.start()

    logger.info(
        "Agent session started | symbols=%s exchange=%s adapter=%s account=%s",
        symbols, exchange, adapter_id, account_id,
    )
    return jsonify({"status": "success", "data": _snapshot()}), 202


@agent_bp.route("/stop", methods=["POST"])
def stop_agent() -> tuple[Any, int]:
    """Request a session stop (squares off tracked positions by default).

    Request JSON:
        square_off (bool, optional, default True).
    """
    body: dict[str, Any] = request.get_json(silent=True) or {}
    square_off = bool(body.get("square_off", True))

    with _RUNNER_LOCK:
        trader = _RUNNER.get("trader")
        thread = _RUNNER.get("thread")
    if trader is None or thread is None or not thread.is_alive():
        return jsonify({"status": "error", "message": "No agent session is running."}), 404

    trader.request_stop(square_off=square_off)
    logger.info("Agent stop requested (square_off=%s)", square_off)
    return jsonify({"status": "success", "data": _snapshot()}), 200


@agent_bp.route("/status", methods=["GET"])
def agent_status() -> tuple[Any, int]:
    """Return the live agent snapshot (honest 'not running' shape when idle)."""
    return jsonify({"status": "success", "data": _snapshot()}), 200
