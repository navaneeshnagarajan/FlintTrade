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
import uuid
from datetime import UTC, datetime
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


def _shutdown_event(app: Any) -> threading.Event:
    """Return the process-owned agent shutdown event for one Flask app."""
    configured = app.config.get("AUTONOMOUS_AGENT_SHUTDOWN_EVENT")
    if configured is None:
        configured = threading.Event()
        app.config["AUTONOMOUS_AGENT_SHUTDOWN_EVENT"] = configured
    if not isinstance(configured, threading.Event):
        raise TypeError("AUTONOMOUS_AGENT_SHUTDOWN_EVENT must be a threading.Event")
    return configured


def shutdown_agent_runtime(app: Any, *, timeout: float = 30.0) -> bool:
    """Stop and join the process-wide autonomous agent before dependencies close.

    The trader's own stop path performs its configured square-off through the
    existing ``GatedChildExecutor``. The shutdown event blocks new sessions but
    deliberately does not short-circuit that reduce-only cleanup path.
    """
    _shutdown_event(app).set()
    with _RUNNER_LOCK:
        trader = _RUNNER.get("trader")
        thread = _RUNNER.get("thread")

    if trader is None and thread is None:
        return True
    if trader is None or thread is None:
        logger.error("Autonomous agent ownership is incomplete during shutdown")
        return False

    if thread.is_alive():
        try:
            trader.request_stop(square_off=True)
        except Exception:  # noqa: BLE001 - shutdown must fail closed without leaking details
            logger.exception("Autonomous agent stop request failed")
            return False
        thread.join(timeout=max(0.0, float(timeout)))
        if thread.is_alive():
            logger.error("Autonomous agent did not stop within the shutdown deadline")
            return False

    try:
        shutdown_complete = bool(trader.shutdown_complete)
    except Exception:  # noqa: BLE001 - an unreadable terminal state fails closed
        logger.exception("Autonomous agent terminal state is unavailable")
        return False
    if not shutdown_complete:
        failure = str(getattr(trader, "stop_failure", "") or "incomplete square-off")
        logger.error("Autonomous agent shutdown incomplete: %s", failure[:256])
        return False
    return True


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
    """Construct the Obsidian vault context when configured (best-effort).

    The path resolves through the shared helper (env override first, then the
    UI-persisted workspace key) so the agent and the Obsidian widget always
    agree on one vault.
    """
    try:
        from flinttrade_ai.obsidian_routes import resolve_obsidian_vault_path  # noqa: PLC0415

        vault_path = resolve_obsidian_vault_path()
        if not vault_path:
            return None
        from flinttrade_ai.obsidian_bridge import ObsidianVault  # noqa: PLC0415

        return ObsidianVault(vault_path)
    except Exception:  # pragma: no cover — the vault is never order-critical
        logger.warning("Obsidian vault unavailable for the agent", exc_info=True)
        return None


# Process-lifetime fallback learning memory (see _build_learning_memory).
_FALLBACK_LEARNING_MEMORY: Any | None = None


def _build_learning_memory() -> Any | None:
    """Construct the agent's learning-memory backend (best-effort).

    Persistent ChromaDB under ``<workspace_dir>/agent_memory`` when the
    dependency imports, in-process hierarchical fallback otherwise — the
    loop still runs, it just does not survive a restart (logged honestly).
    Disabled entirely via workspace ``ai.autonomous_agent.learning.enabled``
    (default true). Never order-critical: any failure returns ``None`` and
    the agent trades exactly as before, with no learning tier.
    """
    try:
        from .workspace import Workspace, workspace_dir  # noqa: PLC0415

        if not bool(Workspace().get("ai.autonomous_agent.learning.enabled", True)):
            return None
        from importlib.util import find_spec  # noqa: PLC0415

        from flinttrade_ai.memory import MemoryBackendConfig, create_memory_backend  # noqa: PLC0415

        # TradedMemory imports chromadb lazily (at first use), so probe the
        # dependency here to fail over at construction time, not mid-session.
        if find_spec("chromadb") is not None:
            return create_memory_backend(
                MemoryBackendConfig(persist_dir=str(workspace_dir() / "agent_memory"))
            )
        logger.warning(
            "chromadb unavailable — agent lessons persist only for this backend "
            "process (in-process memory), not across restarts"
        )
        # Module-level singleton: a per-session instance would make the
        # fallback write-only — lessons stored at session end would die with
        # the trader before the next session could ever read them.
        global _FALLBACK_LEARNING_MEMORY
        if _FALLBACK_LEARNING_MEMORY is None:
            _FALLBACK_LEARNING_MEMORY = create_memory_backend(
                MemoryBackendConfig(backend="hierarchical")
            )
        return _FALLBACK_LEARNING_MEMORY
    except Exception:  # pragma: no cover — learning is never order-critical
        logger.warning("Agent learning memory unavailable", exc_info=True)
        return None


def _build_skills_workspace() -> Any | None:
    """Workspace path for post-session skill DRAFTS, or None when disabled.

    Gated by ``ai.autonomous_agent.learning.skill_drafts`` (default true) —
    drafting is pure file output for operator review, never order-critical.
    """
    try:
        from .workspace import Workspace, workspace_dir  # noqa: PLC0415

        if not bool(Workspace().get("ai.autonomous_agent.learning.skill_drafts", True)):
            return None
        return workspace_dir()
    except Exception:  # pragma: no cover — drafting is never order-critical
        logger.warning("Skill-draft workspace unavailable", exc_info=True)
        return None


def _trader_factory(**kwargs: Any) -> Any:
    """Construct the AutonomousTrader (separated for test injection)."""
    from flinttrade_ai.autonomous_agent import AutonomousTrader  # noqa: PLC0415

    return AutonomousTrader(**kwargs)


def authorise_action_center_request(*, require_live_unlock: bool = False) -> tuple[Any, int] | None:
    """Authorise an Action Centre request against the current JWT only."""
    from .order_routes import (  # noqa: PLC0415
        _decode_request_payload,
        _require_live_payload,
    )

    if require_live_unlock:
        _payload, denied = _require_live_payload(require_unlock=True)
        return denied
    if _decode_request_payload() is None:
        return jsonify({
            "status": "error",
            "message": "Authentication required — provide a valid JWT",
        }), 401
    return None


def dispatch_action_center_approval(approval: Any) -> Any:
    """Dispatch one claimed autonomous-agent entry with fresh operator state.

    No JWT, ``RequestContext``, ``SafetyContext``, router, or broker session is
    retained in the durable request. This function resolves all of them at
    approval time and delegates to the canonical live placement path, which
    performs a fresh L1-L5 check before minting a one-shot gate and calling the
    current ``BrokerRouter``.
    """
    from flinttrade_engine.action_center import ApprovalDispatchResult  # noqa: PLC0415

    from .order_routes import (  # noqa: PLC0415
        _dispatch_live_order,
        _require_live_payload,
    )

    if (
        str(getattr(approval, "source", "")) != "autonomous-agent"
        or str(getattr(approval, "intent_type", "")) != "entry"
    ):
        return ApprovalDispatchResult.refused(
            400,
            "Only autonomous-agent entry intents can be approved on this path.",
        )

    producer_ref = str(getattr(approval, "producer_ref", "") or "")
    adapter_id = str(getattr(approval, "adapter_id", "") or "")
    account_id = str(getattr(approval, "account_id", "") or "")
    with _RUNNER_LOCK:
        current_producer = str(_RUNNER.get("producer_ref") or "")
        trader = _RUNNER.get("trader")
        thread = _RUNNER.get("thread")
        agent_loop = _RUNNER.get("loop")
        params = dict(_RUNNER.get("params") or {})

    if (
        not producer_ref
        or producer_ref != current_producer
        or trader is None
        or thread is None
        or not thread.is_alive()
        or bool(getattr(trader, "stop_requested", True))
    ):
        return ApprovalDispatchResult.refused(
            409,
            "The producing agent session is no longer active; the entry was not sent.",
        )
    if params.get("broker") != adapter_id or params.get("account_id") != account_id:
        return ApprovalDispatchResult.refused(
            409,
            "The agent execution target changed after this intent was created; the entry was not sent.",
        )
    if not _acl_grants_agent(adapter_id, account_id):
        return ApprovalDispatchResult.refused(
            403,
            "The agent account authorisation changed after this intent was created; the entry was not sent.",
        )

    payload, denied = _require_live_payload(require_unlock=True)
    if denied is not None:
        response, status_code = denied
        body = response.get_json(silent=True) or {}
        return ApprovalDispatchResult.refused(
            status_code,
            str(body.get("message") or "Current Live authorisation is unavailable."),
        )
    if payload is None:  # defensive: _require_live_payload returns one or the other
        return ApprovalDispatchResult.refused(
            401,
            "Current Live authorisation is unavailable.",
        )

    order_params = dict(getattr(approval, "order_params", {}) or {})
    embedded_broker = str(order_params.get("broker") or "").strip().lower()
    embedded_account = str(order_params.get("account_id") or "").strip()
    if (embedded_broker and embedded_broker != adapter_id) or (
        embedded_account and embedded_account != account_id
    ):
        return ApprovalDispatchResult.refused(
            409,
            "The persisted order target conflicts with its immutable selector; the entry was not sent.",
        )
    order_params["broker"] = adapter_id
    order_params["account_id"] = account_id

    context = dict(getattr(approval, "intent_context", {}) or {})
    try:
        quantity = int(order_params.get("quantity") or 0)
        entry_price = float(context.get("entry_price") or 0.0)
        stop_loss = float(context.get("stop_loss") or 0.0)
        take_profit = float(context.get("take_profit") or 0.0)
    except (TypeError, ValueError):
        return ApprovalDispatchResult.refused(
            400,
            "The persisted entry context is invalid; the entry was not sent.",
        )
    symbol = str(order_params.get("symbol") or "").strip().upper()
    action = str(order_params.get("action") or "").strip().upper()
    if not symbol or action not in {"BUY", "SELL"} or quantity <= 0 or entry_price <= 0:
        return ApprovalDispatchResult.refused(
            400,
            "The persisted entry context is incomplete; the entry was not sent.",
        )

    response, status_code = _dispatch_live_order(
        "place",
        order_params,
        payload,
        adapter_id=adapter_id,
        account_id=account_id,
    )
    response_body = response.get_json(silent=True) or {}
    if status_code != 200 or response_body.get("status") != "success":
        return ApprovalDispatchResult.refused(
            status_code,
            str(response_body.get("message") or "Approval dispatch was refused."),
            outcome_uncertain=status_code >= 500,
        )

    broker_order_id = str(response_body.get("orderid") or "")
    if not broker_order_id:
        return ApprovalDispatchResult.refused(
            500,
            "Broker acknowledgement did not include an order id; inspect the live order book.",
            outcome_uncertain=True,
        )

    record_entry = getattr(trader, "record_approved_entry", None)
    if callable(record_entry) and agent_loop is not None and agent_loop.is_running():
        try:
            future = asyncio.run_coroutine_threadsafe(
                record_entry(
                    symbol=symbol,
                    action=action,
                    quantity=quantity,
                    entry_price=entry_price,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                ),
                agent_loop,
            )
            future.result(timeout=5.0)
        except Exception:  # noqa: BLE001 - broker success remains authoritative
            logger.exception(
                "Approved entry %s dispatched but agent monitoring state could not be updated",
                getattr(approval, "id", "unknown"),
            )

    return ApprovalDispatchResult.success(broker_order_id)


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
            "shutdown_complete": bool(getattr(trader, "shutdown_complete", False)),
            "stop_failure": str(getattr(trader, "stop_failure", "") or ""),
        })
    return snap


@agent_bp.route("/start", methods=["POST"])
def start_agent() -> tuple[Any, int]:
    """Start an AI agent session as a background thread.

    Request JSON:
        symbols (list[str], required) · exchange (str, default "NSE") ·
        product (str, default "MIS") · max_position_size (int, default 1) ·
        stop_loss_pct / take_profit_pct (float) · daily_stop_loss (float) ·
        max_trades_per_symbol (int) · cycle_interval_sec (int) ·
        optional broker/account_id target; omitted target uses brokers.execution.default

    Returns:
        202 with the initial snapshot; 400 (validation), 401 (no JWT),
        403 (disabled / not live / not unlocked / agent not in the ACL),
        409 (already running), 503 (routing/LLM unavailable).
    """
    from flinttrade_engine.request_context import RequestContext  # noqa: PLC0415

    from .order_routes import (  # noqa: PLC0415
        _decode_request_payload,
        _gated_target,
        _is_live_mode_unlocked,
        _record_trade_journal,
        _require_live_safety,
        _safety_runtime_unavailable_response,
    )
    from .smart_order_routes import GatedChildExecutor  # noqa: PLC0415

    app_obj = current_app._get_current_object()  # noqa: SLF001
    if _shutdown_event(app_obj).is_set():
        return jsonify({
            "status": "error",
            "message": "The application is shutting down; no new agent session can start.",
        }), 503

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

    try:
        safety = _require_live_safety()
    except Exception as exc:  # noqa: BLE001 - readiness failures are an admission refusal
        logger.error("Autonomous-agent safety runtime unavailable: %s", type(exc).__name__)
        return _safety_runtime_unavailable_response()

    approval_queue = current_app.config.get("PENDING_ORDER_QUEUE")
    if approval_queue is None or not callable(getattr(approval_queue, "enqueue", None)):
        return jsonify({
            "status": "error",
            "message": "Action Centre approval storage is unavailable; the agent remains disabled.",
        }), 503

    time_scheduler = current_app.config.get("TIME_SCHEDULER")
    get_market_session = getattr(time_scheduler, "get_market_session", None)
    market_clock = getattr(time_scheduler, "now_ist", None)
    if not callable(get_market_session) or not callable(market_clock):
        return jsonify({
            "status": "error",
            "message": "Market calendar unavailable — autonomous trading remains disabled.",
        }), 503

    body: dict[str, Any] = request.get_json(silent=True) or {}
    symbols = [str(s).strip().upper() for s in (body.get("symbols") or []) if str(s).strip()]
    exchange = str(body.get("exchange") or "NSE").strip().upper()
    product = str(body.get("product") or "MIS").strip().upper()
    adapter_id, account_id = _gated_target(body)
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

    # Claim the single-session slot ATOMICALLY before any slow construction
    # (LLM client, trader). Without the "starting" sentinel the alive-check and
    # the later _RUNNER.update were two separate lock sections — two concurrent
    # /start calls could both pass the check, both spawn live agents, and the
    # second update would orphan the first (unreachable by /stop). The sentinel
    # is rolled back on any failure below so a crashed start never wedges the slot.
    with _RUNNER_LOCK:
        if _shutdown_event(app_obj).is_set():
            return jsonify({
                "status": "error",
                "message": "The application is shutting down; no new agent session can start.",
            }), 503
        thread = _RUNNER.get("thread")
        if (thread is not None and thread.is_alive()) or _RUNNER.get("starting"):
            return jsonify({
                "status": "error",
                "message": "An agent session is already running — stop it first.",
            }), 409
        _RUNNER["starting"] = True

    def _release_slot() -> None:
        with _RUNNER_LOCK:
            _RUNNER.pop("starting", None)

    try:
        llm = _build_llm()
    except Exception as exc:
        _release_slot()
        logger.warning("LLM client unavailable: %s", exc)
        return jsonify({
            "status": "error",
            "message": "LLM client unavailable — configure a provider in Settings",
        }), 503

    # Everything from here to registration runs under ONE try so ANY failure
    # (config reads, RequestContext, the closures, executor/trader) releases
    # the sentinel — the slot can never wedge "starting" forever.
    try:
        producer_ref = str(uuid.uuid4())
        request_ctx = RequestContext(
            jti=str(payload.get("jti") or ""),
            actor_type="agent",
            actor_id=_AGENT_ACTOR_ID,
            mode=_MODE_LIVE,
            selector=f"{adapter_id}:{account_id}",
        )

        journal_store = current_app.config.get("TRADE_STORAGE")
        def _journal_write(order: Any, orderid: str) -> None:
            with app_obj.app_context():
                if journal_store is not None:
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
            if not _acl_grants_agent(adapter_id, account_id):
                return "agent account authorisation was revoked"
            return None

        # Complete L2/L4 state, fetched FRESH per order — the agent session is
        # long-lived (a cached snapshot would go stale across cycles) and its
        # order frequency is low, so a per-order fetch is the freshest, cheapest
        # correct choice. A missing local P&L snapshot fails the child closed.
        from .smart_order_routes import gather_portfolio_state  # noqa: PLC0415

        native_adapters = current_app.config.get("NATIVE_ADAPTERS") or {}
        registry = current_app.config.get("REGISTRY")

        async def _agent_safety_state_provider(
            order: Any,
            reservations: tuple[Any, ...],
        ) -> Any:
            return await gather_portfolio_state(
                client,
                adapter_id,
                account_id=account_id,
                native_adapters=native_adapters,
                registry=registry,
                orders=[order],
                reservations=reservations,
            )

        executor = GatedChildExecutor(
            safety=safety,
            router=router,
            router_provider=lambda: app_obj.config.get("BROKER_ROUTER"),
            request_ctx=request_ctx,
            adapter_id=adapter_id,
            account_id=account_id,
            audit=current_app.config.get("AUDIT"),
            journal_write=_journal_write,
            pre_dispatch_check=_pre_dispatch_check,
            portfolio_state_provider=_agent_safety_state_provider,
        )

        async def _entry_intent_sink(order: Any, intent_context: dict[str, Any]) -> dict[str, str]:
            """Persist an entry intent without retaining auth or gate material."""
            from flinttrade_engine.action_center import ActionCenterError  # noqa: PLC0415

            model_dump = getattr(order, "model_dump", None)
            if not callable(model_dump):
                raise TypeError("Autonomous-agent entry order is not serialisable")
            order_params = model_dump(mode="json")
            signal = str(intent_context.get("signal") or "ENTRY").upper()
            request_id = str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"flinttrade:agent-entry:{producer_ref}:{getattr(order, 'symbol', '')}",
                )
            )
            try:
                approval = await asyncio.to_thread(
                    approval_queue.enqueue,
                    order_params=order_params,
                    reason=f"Autonomous-agent {signal} entry requires operator approval",
                    request_id=request_id,
                    adapter_id=adapter_id,
                    account_id=account_id,
                    source="autonomous-agent",
                    intent_type="entry",
                    producer_ref=producer_ref,
                    intent_context=intent_context,
                )
            except ActionCenterError:
                approval = await asyncio.to_thread(approval_queue.get, request_id)
                if (
                    str(getattr(approval, "producer_ref", "")) != producer_ref
                    or str(getattr(approval, "status", "")) not in {"pending", "dispatching"}
                ):
                    raise
            return {
                "id": str(getattr(approval, "id", "") or ""),
                "status": str(getattr(approval, "status", "pending") or "pending"),
            }

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

        def _market_session_provider(
            provider_exchange: str,
            provider_symbol: str,
            session_date: Any,
        ) -> Any:
            return get_market_session(
                provider_exchange,
                on=session_date,
                symbol=provider_symbol,
            )

        trader = _trader_factory(
            llm_client=llm,
            openalgo_client=client,
            config=config,
            vault=_build_vault(),
            order_executor=executor,
            entry_intent_sink=_entry_intent_sink,
            market_session_provider=_market_session_provider,
            clock=market_clock,
            memory=_build_learning_memory(),
            skill_registry=app_obj.config.get("SKILL_REGISTRY"),
            skills_workspace=_build_skills_workspace(),
        )
    except Exception:
        _release_slot()
        logger.exception("Agent session construction failed")
        return jsonify({
            "status": "error",
            "message": "Could not start the agent session",
        }), 500

    async def _run_session() -> None:
        with _RUNNER_LOCK:
            if _RUNNER.get("trader") is trader and _RUNNER.get("producer_ref") == producer_ref:
                _RUNNER["loop"] = asyncio.get_running_loop()
        await trader.run_session()

    def _run() -> None:
        try:
            asyncio.run(_run_session())
        except Exception:  # pragma: no cover — session errors land in status
            logger.exception("Agent session crashed")
        finally:
            reject_pending = getattr(approval_queue, "reject_pending_by_producer", None)
            if callable(reject_pending):
                try:
                    reject_pending(producer_ref, "Autonomous-agent session ended before approval")
                except Exception:  # noqa: BLE001 - cleanup failure must not revive stale intents
                    logger.exception("Could not close stale autonomous-agent approval intents")
            with _RUNNER_LOCK:
                if _RUNNER.get("producer_ref") == producer_ref:
                    _RUNNER.pop("loop", None)

    session_thread = threading.Thread(target=_run, name="autonomous-agent", daemon=True)
    with _RUNNER_LOCK:
        if _shutdown_event(app_obj).is_set():
            _RUNNER.pop("starting", None)
            return jsonify({
                "status": "error",
                "message": "The application is shutting down; no new agent session can start.",
            }), 503
        _RUNNER.clear()  # replace the slot wholesale (drops the "starting" sentinel)
        _RUNNER.update({
            "trader": trader,
            "thread": session_thread,
            "producer_ref": producer_ref,
            "started_at": datetime.now(UTC).isoformat(),
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


def _require_auth() -> tuple[Any, int] | None:
    """Return a 401 response when the request carries no valid JWT.

    The session snapshot exposes live positions and P&L, and stopping a
    session is an operator action — neither is a public surface.
    """
    from .order_routes import _decode_request_payload  # noqa: PLC0415

    if _decode_request_payload() is None:
        return jsonify({
            "status": "error",
            "message": "Authentication required — provide a valid JWT",
        }), 401
    return None


@agent_bp.route("/stop", methods=["POST"])
def stop_agent() -> tuple[Any, int]:
    """Request a session stop (squares off tracked positions by default).

    Request JSON:
        square_off (bool, optional, default True).
    """
    denied = _require_auth()
    if denied is not None:
        return denied
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
    denied = _require_auth()
    if denied is not None:
        return denied
    return jsonify({"status": "success", "data": _snapshot()}), 200
