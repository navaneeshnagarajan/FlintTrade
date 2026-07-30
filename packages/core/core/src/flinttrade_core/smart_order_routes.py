"""Smart-order routing endpoints — liquidity-aware order slicing through the gate.

Endpoints (registered by ``create_flask_app``; all require a valid JWT):

- ``POST /api/v1/orders/smart-route``               — start a smart-routed order job (202)
- ``GET  /api/v1/orders/smart-route/<id>``          — poll a job's live snapshot
- ``GET  /api/v1/orders/smart-route``               — list recent job snapshots
- ``POST /api/v1/orders/smart-route/<id>/cancel``   — request cancellation

Safety model (do not weaken):
    The :class:`~flinttrade_engine.smart_router.SmartOrderRouter` only DECIDES
    how to slice (single market order / depth-aware chunks / TWAP). It cannot
    reach a broker except through :class:`GatedChildExecutor`, whose
    ``route_order`` runs the FULL gated execution path for EVERY child order
    independently: SafetySystem L1–L5 → ``gate_order`` (one-shot HMAC
    ``SafetyContext``) → ``BrokerRouter`` (re-verify + ACL + one-shot consume)
    → adapter. A child that fails any layer fails CLOSED for that child only.

    Mid-flight brakes — the job thread outlives its HTTP request, so before
    EVERY child the executor re-checks (a) operator cancellation and (b) jti
    revocation (logout and the live→practice mode downgrade both revoke the
    jti); either aborts the whole route. At most ``_MAX_RUNNING_JOBS`` jobs
    run concurrently, and a duplicate (symbol, action) submission while one
    is running is refused — a re-click cannot silently double the quantity.

    The feature is OFF by default — enable via workspace.json::

        "brokers": {"smart_routing": {"enabled": true,
                                       "twap_window_seconds": 300,
                                       "twap_slices": 5}}

    Live mode only: TWAP/slicing against the sandbox is not implemented, and
    explore mode has no broker. The route fails closed with a clear message.

Operational caveat:
    Job state is in-memory only. A backend restart kills the daemon worker
    (no further children are placed) and forgets the snapshot — after a
    restart mid-route, check the broker order book for what was accepted.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from flask import Blueprint, current_app, jsonify, request

from .rate_limiter import rate_limit

logger = logging.getLogger("flinttrade.core.smart_order_routes")

smart_order_bp = Blueprint("smart_orders", __name__, url_prefix="/api/v1/orders")

_MODE_LIVE = "live"

# Most-recent jobs kept for the list/status endpoints (oldest evicted).
_MAX_JOBS = 50


# ---------------------------------------------------------------------------
# Portfolio state for SafetySystem L2 (position count + margin %)
# ---------------------------------------------------------------------------


async def gather_portfolio_state(
    client: Any,
    adapter_id: str,
    *,
    account_id: str = "default",
    native_adapters: dict[str, Any] | None = None,
    registry: Any = None,
    orders: list[Any] | tuple[Any, ...] = (),
    reservations: list[Any] | tuple[Any, ...] = (),
) -> Any:
    """Gather the complete L2/L4 state for a smart-route or agent child.

    This compatibility wrapper keeps the executor-facing call signature while
    delegating all selector resolution and local P&L accounting to the one
    shared safety-state implementation. Failures propagate so the caller can
    refuse the child before minting a gate.
    """
    from .l2_state import gather_safety_state  # noqa: PLC0415

    config = {
        "OPENALGO_CLIENT": client,
        "NATIVE_ADAPTERS": native_adapters or {},
        "REGISTRY": registry,
    }
    return await gather_safety_state(
        config,
        adapter_id,
        account_id=account_id,
        orders=orders,
        reservations=reservations,
        include_order_margin=True,
    )


# ---------------------------------------------------------------------------
# Gated child executor — the ONLY broker access the smart router gets
# ---------------------------------------------------------------------------


class _GatedOrderResponse:
    """Minimal order-response shim carrying the broker order id."""

    def __init__(self, orderid: str) -> None:
        self.orderid = orderid


class _GatedDecision:
    """Decision shim matching what SmartOrderRouter reads from its base router."""

    def __init__(self, passed: bool, order_response: _GatedOrderResponse | None = None, error: str = "") -> None:
        self.passed = passed
        self.order_response = order_response
        self.error = error


class GatedChildExecutor:
    """Dispatches each smart-route child order through the full gated path.

    Every dependency or provider is captured at construction (no
    ``current_app``) because ``route_order`` runs on a background job thread
    outside any Flask context.

    Args:
        safety: The app's :class:`~flinttrade_engine.safety.SafetySystem`.
        router: Static :class:`~flinttrade_gateway.router.BrokerRouter` used by
            existing callers and whenever ``router_provider`` is absent.
        router_provider: Optional ``() -> BrokerRouter | None`` resolved before
            every child. Long-lived executors use it to follow runtime router
            rebuilds; ``None`` fails closed when routing was removed.
        request_ctx: Selector-bound request context for the initiating actor.
        adapter_id: Broker adapter id (e.g. ``"openalgo"``).
        account_id: Broker account id within the adapter.
        audit: Optional audit logger (``log_event``); best-effort.
        journal_write: Optional callable ``(order, orderid) -> None`` appending
            to the trade journal; best-effort.
        pre_dispatch_check: Optional ``() -> str | None`` evaluated BEFORE
            every child — a non-None return (e.g. "session token revoked",
            "cancelled by operator") raises
            :class:`~flinttrade_engine.smart_router.SmartRouteAbort` so the
            WHOLE route stops. This is the mid-flight brake: a background job
            outlives its HTTP request, so logout / live→practice downgrade
            (which revoke the jti) and operator cancellation must be
            re-checked per child, not just at submission.
        portfolio_state_provider: ``async (order, reservations) -> PortfolioSafetyState`` awaited
            before each child so SafetySystem L2 and L4 use selector-scoped
            positions, margin, locally computed daily P&L, and capital. Missing
            or failed state blocks the child. The provider owns its caching
            policy: smart routes cache once (bounded duration); the agent fetches
            fresh (low order frequency, freshest state).
    """

    def __init__(
        self,
        *,
        safety: Any,
        router: Any,
        router_provider: Any = None,
        request_ctx: Any,
        adapter_id: str,
        account_id: str,
        audit: Any = None,
        journal_write: Any = None,
        pre_dispatch_check: Any = None,
        portfolio_state_provider: Any = None,
    ) -> None:
        self._safety = safety
        self._router = router
        self._router_provider = router_provider
        self._request_ctx = request_ctx
        self._adapter_id = adapter_id
        self._account_id = account_id
        self._audit = audit
        self._journal_write = journal_write
        self._pre_dispatch_check = pre_dispatch_check
        self._portfolio_state_provider = portfolio_state_provider

    async def route_order(self, order: Any) -> _GatedDecision:
        """Run one child order through SafetySystem → gate_order → BrokerRouter.

        Fails CLOSED per child: any safety block, gate refusal, or dispatch
        error returns a failed decision for THIS child without raising, so the
        smart router records it honestly and continues (or stops) per its own
        logic. Never bypasses the gate. The one exception is the pre-dispatch
        check, which raises ``SmartRouteAbort`` to stop the whole route.

        Args:
            order: A typed :class:`flinttrade_core.models.Order` for the child.

        Returns:
            A :class:`_GatedDecision` with ``passed``/``order_response``/``error``.
        """
        from flinttrade_core.exceptions import SafetyBypassError  # noqa: PLC0415
        from flinttrade_engine.safety import gate_order  # noqa: PLC0415
        from flinttrade_engine.smart_router import SmartRouteAbort  # noqa: PLC0415
        from flinttrade_gateway.routing_config import RoutingHint  # noqa: PLC0415

        if self._pre_dispatch_check is not None:
            reason = self._pre_dispatch_check()
            if reason:
                raise SmartRouteAbort(reason)
        if self._portfolio_state_provider is None:
            return _GatedDecision(False, error="Portfolio safety state provider is unavailable")

        selector = f"{self._adapter_id}:{self._account_id}"
        async with self._safety.order_admission_async(selector) as lease:
            if self._pre_dispatch_check is not None:
                reason = self._pre_dispatch_check()
                if reason:
                    raise SmartRouteAbort(reason)
            try:
                portfolio_state = await self._portfolio_state_provider(order, lease.reservations)
                lease.reconcile(getattr(portfolio_state, "reconciled_reservation_ids", ()))
            except Exception as exc:  # noqa: BLE001 - refuse without leaking broker details
                logger.error("Portfolio safety state unavailable for smart-route child: %s", type(exc).__name__)
                return _GatedDecision(False, error="Portfolio safety state is unavailable")

            if self._pre_dispatch_check is not None:
                reason = self._pre_dispatch_check()
                if reason:
                    raise SmartRouteAbort(reason)
            try:
                admission = portfolio_state.admission_for(0)
                results = self._safety.check_order(
                    order,
                    selector=selector,
                    positions=admission.positions,
                    used_margin=admission.used_margin,
                    total_balance=portfolio_state.total_balance,
                    daily_pnl=portfolio_state.daily_pnl,
                    starting_capital=portfolio_state.starting_capital,
                    ltp=portfolio_state.ltp_for(order),
                    net_delta=admission.net_delta,
                    net_vega=admission.net_vega,
                )
            except Exception as exc:
                logger.warning("Smart-route child validation failed: %s", exc)
                return _GatedDecision(False, error="Order validation failed")
            blocked = next((result for result in results if not result.passed), None)
            if blocked is not None:
                return _GatedDecision(
                    False,
                    error=f"Blocked by safety system [{blocked.layer}]: {blocked.reason}",
                )

            if self._pre_dispatch_check is not None:
                reason = self._pre_dispatch_check()
                if reason:
                    raise SmartRouteAbort(reason)
            try:
                router = self._router_provider() if self._router_provider is not None else self._router
                if router is None:
                    raise SafetyBypassError("current BrokerRouter generation is unavailable")
                safety_ctx = gate_order(
                    order,
                    self._request_ctx,
                    adapter_id=self._adapter_id,
                    account_id=self._account_id,
                )
                reservation = lease.reserve(order, admission.positions)
                result = await router.place_order(
                    self._request_ctx,
                    order=order,
                    safety_ctx=safety_ctx,
                    hint=RoutingHint(adapter_id=self._adapter_id, account_id=self._account_id),
                )
                lease.acknowledge(reservation, result)
            except Exception as exc:
                logger.warning(
                    "Smart-route child refused | adapter=%s account=%s symbol=%s: %s",
                    self._adapter_id,
                    self._account_id,
                    getattr(order, "symbol", "?"),
                    exc,
                )
                if exc.__class__.__name__ == "SafetyBypassError":
                    return _GatedDecision(False, error="verification failed")
                return _GatedDecision(False, error="dispatch failed")

            orderid = str(result)

        # Best-effort audit + journal — never break the child path.
        try:
            if self._audit is not None:
                self._audit.log_event(
                    "ORDER_PLACED",
                    adapter_id=self._adapter_id,
                    account_id=self._account_id,
                    actor_id=self._request_ctx.actor_id,
                    symbol=getattr(order, "symbol", None),
                    action="smart-route",
                )
        except Exception:  # pragma: no cover
            logger.debug("audit stamp failed for smart-route child", exc_info=True)
        try:
            if self._journal_write is not None:
                self._journal_write(order, orderid)
        except Exception:  # pragma: no cover
            logger.debug("journal stamp failed for smart-route child", exc_info=True)

        return _GatedDecision(True, _GatedOrderResponse(orderid))


# ---------------------------------------------------------------------------
# Job store
# ---------------------------------------------------------------------------


@dataclass
class _SmartJob:
    """A background smart-route execution and its live result."""

    job_id: str
    params: dict[str, Any]
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    status: str = "running"  # running | done | error
    error: str = ""
    result: Any = None  # live SmartRouteResult once the router creates it
    cancel_requested: bool = False
    worker: threading.Thread | None = field(default=None, repr=False, compare=False)


_JOBS: dict[str, _SmartJob] = {}
_JOBS_LOCK = threading.Lock()
_ACCEPTING_JOBS = True

# Hard cap on SIMULTANEOUSLY RUNNING jobs (not just stored snapshots): each
# job is a live-order worker thread, and an unbounded number of them is a
# runaway-order/DoS surface even for an authenticated operator.
_MAX_RUNNING_JOBS = 4


def _evict_terminal_locked() -> None:
    """Evict oldest TERMINAL jobs over the cap. Caller MUST hold _JOBS_LOCK.

    Deleting a running job's snapshot would orphan a live worker (children
    keep placing with no observability and the widget's polling 404s
    mid-flight), so only finished jobs are evicted.
    """
    if len(_JOBS) > _MAX_JOBS:
        for key in list(_JOBS):
            if len(_JOBS) <= _MAX_JOBS:
                break
            if _JOBS[key].status != "running":
                del _JOBS[key]


def _store_job(job: _SmartJob) -> None:
    with _JOBS_LOCK:
        _JOBS[job.job_id] = job
        _evict_terminal_locked()


def _snapshot(job: _SmartJob) -> dict[str, Any]:
    """Serialise a job + its live result for the status endpoints."""
    result = job.result
    children: list[dict[str, Any]] = []
    filled = 0
    avg_slippage = 0.0
    completed = False
    if result is not None:
        # Reading the live list mid-flight is safe: the worker only appends.
        for child in list(result.child_orders):
            children.append({
                "quantity": child.quantity,
                "price_type": child.price_type,
                "status": child.status,
                "order_id": child.order_id,
                "error": child.error,
                "slippage_bps": child.slippage_bps,
                "placed_at": child.placed_at,
            })
        filled = result.filled_quantity
        avg_slippage = result.average_slippage_bps
        completed = result.completed
    return {
        "job_id": job.job_id,
        "created_at": job.created_at,
        "status": job.status,
        "cancel_requested": job.cancel_requested,
        "error": job.error or (result.error if result is not None else ""),
        "symbol": job.params.get("symbol", ""),
        "exchange": job.params.get("exchange", ""),
        "action": job.params.get("action", ""),
        "urgency": job.params.get("urgency", ""),
        "total_quantity": job.params.get("quantity", 0),
        # Broker-ACCEPTED quantity (order ids returned) — fills are confirmed
        # by the broker's trade book, not here. The UI labels it "accepted".
        "filled_quantity": filled,
        "average_slippage_bps": avg_slippage,
        "completed": completed,
        "child_orders": children,
    }


def _reset_jobs_for_tests() -> None:
    """Clear the job store (test isolation helper)."""
    global _ACCEPTING_JOBS
    with _JOBS_LOCK:
        _JOBS.clear()
        _ACCEPTING_JOBS = True


def start_smart_order_jobs() -> bool:
    """Open smart-route admission for a new runtime generation.

    Admission stays closed if an earlier generation still owns a live worker.
    """
    global _ACCEPTING_JOBS
    with _JOBS_LOCK:
        if any(job.worker is not None and job.worker.is_alive() for job in _JOBS.values()):
            return False
        _ACCEPTING_JOBS = True
        return True


def shutdown_smart_order_jobs(*, timeout: float) -> bool:
    """Close admission, cancel every running job, and join owned workers."""
    global _ACCEPTING_JOBS
    deadline = time.monotonic() + max(timeout, 0.0)
    with _JOBS_LOCK:
        _ACCEPTING_JOBS = False
        jobs = [job for job in _JOBS.values() if job.status == "running"]
        for job in jobs:
            job.cancel_requested = True
        workers = [job.worker for job in jobs if job.worker is not None]

    current = threading.current_thread()
    for worker in workers:
        if worker is current:
            continue
        worker.join(timeout=max(0.0, deadline - time.monotonic()))

    return all(worker is current or not worker.is_alive() for worker in workers)


# ---------------------------------------------------------------------------
# Providers — optional depth/volume from the OpenAlgo bridge client
# ---------------------------------------------------------------------------


def _make_providers(client: Any) -> tuple[Any, Any]:
    """Build async depth/volume providers over the optional OpenAlgo client.

    The smart router consumes raw OpenAlgo-shaped dicts; when the bridge
    client exists it returns typed models, so convert at this boundary. A
    missing client or depth-fetch failure returns an empty book; medium
    urgency then FAILS CLOSED (refuses, no orders placed) rather than blindly
    market-ordering, and high/low urgency do not consult depth at all.
    Empty-on-failure keeps the job from crashing while the router enforces the
    safe outcome.
    """

    async def depth_provider(symbol: str, exchange: str) -> dict[str, Any]:
        if client is None:
            logger.warning(
                "smart-route depth unavailable for %s/%s: OpenAlgo client is not configured",
                symbol,
                exchange,
            )
            return {"asks": [], "bids": []}
        try:
            depth = await client.depth(symbol, exchange)
            return {
                "asks": [{"price": lvl.price, "quantity": lvl.quantity} for lvl in depth.asks],
                "bids": [{"price": lvl.price, "quantity": lvl.quantity} for lvl in depth.bids],
            }
        except Exception as exc:
            logger.warning("smart-route depth fetch failed for %s/%s: %s", symbol, exchange, exc)
            return {"asks": [], "bids": []}

    async def volume_provider(symbol: str, exchange: str) -> int:
        if client is None:
            return 0
        try:
            quote = await client.quotes(symbol, exchange)
            return int(quote.volume)
        except Exception as exc:
            logger.warning("smart-route volume fetch failed for %s/%s: %s", symbol, exchange, exc)
            return 0

    return depth_provider, volume_provider


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

_VALID_URGENCY = {"low", "medium", "high"}
_VALID_ACTION = {"BUY", "SELL"}


@smart_order_bp.route("/smart-route", methods=["POST"])
@rate_limit("smart_orders", user_rate=2, global_rate=20)
def start_smart_route() -> tuple[Any, int]:
    """Start a smart-routed order as a background job.

    Request JSON:
        symbol (str, required) · exchange (str, required) ·
        action ("BUY"|"SELL", required) · quantity (int > 0, required) ·
        urgency ("low"|"medium"|"high", default "medium") ·
        max_slippage_bps (int, default 20) · product (str, default "MIS") ·
        optional broker/account_id target; omitted target uses brokers.execution.default

    Returns:
        202 with the initial job snapshot; 400 (validation), 401 (no JWT),
        403 (disabled / not live / not unlocked / parent safety block),
        503 (routing unavailable).
    """
    from flinttrade_core.models import Action, Exchange, Order, PriceType  # noqa: PLC0415
    from flinttrade_engine.request_context import RequestContext  # noqa: PLC0415
    from flinttrade_engine.smart_router import SmartOrderRouter  # noqa: PLC0415

    from .order_routes import (  # noqa: PLC0415
        _decode_request_payload,
        _gated_target,
        _is_live_mode_unlocked,
        _require_live_safety,
        _record_trade_journal,
        _run_on_client_loop,
        _safety_runtime_unavailable_response,
    )

    cfg = current_app.config.get("SMART_ROUTING") or {}
    if not cfg.get("enabled", False):
        return jsonify({
            "status": "error",
            "message": (
                "Smart routing is disabled. Enable it via workspace.json "
                "brokers.smart_routing.enabled and restart the backend."
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
            "message": (
                "Smart routing serves live mode only — slicing against the "
                "sandbox is not implemented. Switch to live mode first."
            ),
        }), 403

    if not _is_live_mode_unlocked():
        return jsonify({
            "status": "error",
            "message": "Live mode not unlocked — verify PIN first",
        }), 403

    router = current_app.config.get("BROKER_ROUTER")
    client = current_app.config.get("OPENALGO_CLIENT")
    if router is None:
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
        logger.error("Smart-route safety runtime unavailable: %s", type(exc).__name__)
        return _safety_runtime_unavailable_response()

    body: dict[str, Any] = request.get_json(silent=True) or {}
    symbol = str(body.get("symbol") or "").strip()
    exchange = str(body.get("exchange") or "").strip()
    action = str(body.get("action") or "").strip().upper()
    urgency = str(body.get("urgency") or "medium").strip().lower()
    product = str(body.get("product") or "MIS").strip().upper()
    adapter_id, account_id = _gated_target(body)
    try:
        quantity = int(body.get("quantity") or 0)
        # Distinguish an explicit 0 (a real "zero slippage tolerance" budget)
        # from an omitted field — `int(x or 20)` would silently turn 0 into the
        # default 20, undoing the widget's strict 0-stays-0 parsing.
        raw_bps = body.get("max_slippage_bps")
        max_slippage_bps = 20 if raw_bps is None else int(raw_bps)
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "quantity/max_slippage_bps must be integers"}), 400

    if not symbol or not exchange:
        return jsonify({"status": "error", "message": "symbol and exchange are required"}), 400
    if action not in _VALID_ACTION:
        return jsonify({"status": "error", "message": "action must be BUY or SELL"}), 400
    if urgency not in _VALID_URGENCY:
        return jsonify({"status": "error", "message": "urgency must be low, medium, or high"}), 400
    if quantity <= 0:
        return jsonify({"status": "error", "message": "quantity must be a positive integer"}), 400
    if max_slippage_bps < 0:
        return jsonify({"status": "error", "message": "max_slippage_bps must be >= 0"}), 400

    try:
        parent_order = Order(
            symbol=symbol,
            exchange=Exchange(exchange),
            action=Action(action),
            pricetype=PriceType.MARKET,
            quantity=str(quantity),
            strategy="smart-route",
            product=product,  # type: ignore[arg-type]
        )
    except Exception:
        return jsonify({"status": "error", "message": "Order validation failed"}), 400

    # --- parent-level fast-fail: validate the FULL order against L1–L5 -------
    # Each child is re-checked independently in GatedChildExecutor; this stops
    # an obviously-refusable parent before a background job spins up.
    try:
        from .l2_state import gather_safety_state  # noqa: PLC0415

        portfolio_state = _run_on_client_loop(
            gather_safety_state(
                current_app.config,
                adapter_id,
                account_id=account_id,
                orders=[parent_order],
            )
        )
    except Exception as exc:  # noqa: BLE001 - refuse without exposing broker details
        logger.error("Smart-route portfolio safety state is unavailable: %s", type(exc).__name__)
        return jsonify({
            "status": "error",
            "message": "Order safety state unavailable; no order was sent.",
        }), 503
    try:
        admission = portfolio_state.admission_for(0)
        parent_results = safety.check_order(
            parent_order,
            selector=f"{adapter_id}:{account_id}",
            positions=admission.positions,
            used_margin=admission.used_margin,
            total_balance=portfolio_state.total_balance,
            daily_pnl=portfolio_state.daily_pnl,
            starting_capital=portfolio_state.starting_capital,
            ltp=portfolio_state.ltp_for(parent_order),
            net_delta=admission.net_delta,
            net_vega=admission.net_vega,
        )
    except Exception:
        return jsonify({"status": "error", "message": "Order validation failed"}), 400
    blocked = next((r for r in parent_results if not r.passed), None)
    if blocked is not None:
        return jsonify({
            "status": "error",
            "message": f"Order blocked by safety system [{blocked.layer}]: {blocked.reason}",
        }), 403

    # --- concurrency cap + duplicate-submission guard -------------------------
    jti = str(payload.get("jti") or "")
    request_ctx = RequestContext(
        jti=jti,
        actor_type="human",
        actor_id=str(payload.get("sub") or payload.get("actor_id") or "unknown"),
        mode=_MODE_LIVE,
        selector=f"{adapter_id}:{account_id}",
    )

    job = _SmartJob(
        job_id=uuid.uuid4().hex[:12],
        params={
            "symbol": symbol, "exchange": exchange, "action": action,
            "quantity": quantity, "urgency": urgency, "product": product,
            "broker": adapter_id, "account_id": account_id,
            "max_slippage_bps": max_slippage_bps,
        },
    )

    # ATOMIC cap + duplicate guard + insert in ONE lock section. A multi-minute
    # unattended live-order job must not be silently duplicated (a re-click
    # after the 202 would otherwise run 2x the quantity), and the number of
    # simultaneous live-order workers must stay bounded. Doing the check and
    # the insert under the SAME _JOBS_LOCK closes the TOCTOU window two
    # concurrent submits could drive between a check-then-insert split.
    # (Cross-process note: _JOBS is process-local; under a multi-worker
    # deployment the cap/dup-guard and cancel are per-worker — documented in
    # the module docstring's operational caveat.)
    with _JOBS_LOCK:
        if not _ACCEPTING_JOBS:
            return jsonify({
                "status": "error",
                "message": "Smart-order routing is shutting down",
            }), 503
        running = [j for j in _JOBS.values() if j.status == "running"]
        if len(running) >= _MAX_RUNNING_JOBS:
            return jsonify({
                "status": "error",
                "message": (
                    f"Too many smart-route jobs already running "
                    f"(max {_MAX_RUNNING_JOBS}). Wait for one to finish or cancel it."
                ),
            }), 409
        dup = next(
            (
                j for j in running
                if j.params.get("symbol") == symbol and j.params.get("action") == action
            ),
            None,
        )
        if dup is not None:
            return jsonify({
                "status": "error",
                "message": (
                    f"A smart-route job for {action} {symbol} is already running "
                    f"(job {dup.job_id}). Cancel it first if you intend to replace it."
                ),
            }), 409
        # Insert NOW (status defaults to "running") so a concurrent submit sees
        # it as an existing running job and is refused.
        _JOBS[job.job_id] = job
        _evict_terminal_locked()

    # Mid-flight brake, evaluated before EVERY child: the job thread outlives
    # this HTTP request, so logout and the live→practice downgrade (both of
    # which revoke the jti) plus operator cancellation must keep working while
    # the route runs. An unavailable revocation store fails CLOSED — this is a
    # live order path.
    def _pre_dispatch_check() -> str | None:
        if job.cancel_requested:
            return "cancelled by operator"
        try:
            from .auth_routes import _is_jti_revoked  # noqa: PLC0415

            if jti and _is_jti_revoked(jti):
                return "session token revoked (logout or mode change)"
        except Exception:
            logger.exception("smart-route revocation check failed — aborting (fail closed)")
            return "session revocation check unavailable"
        return None

    # The job thread has no Flask context — capture the app object now and
    # re-enter an app context per journal write (_record_trade_journal reads
    # TRADE_STORAGE/TRADE_STORAGE_LOCK from app config and takes the lock).
    journal_store = current_app.config.get("TRADE_STORAGE")
    app_obj = current_app._get_current_object()  # noqa: SLF001

    def _journal_write(order: Any, orderid: str) -> None:
        with app_obj.app_context():
            if journal_store is not None:
                _record_trade_journal(order, orderid, strategy="smart-route")

    async def _route_safety_provider(order: Any, reservations: tuple[Any, ...]) -> Any:
        return await gather_safety_state(
            app_obj.config,
            adapter_id,
            account_id=account_id,
            orders=[order],
            reservations=reservations,
            include_order_margin=True,
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
        portfolio_state_provider=_route_safety_provider,
    )
    depth_provider, volume_provider = _make_providers(client)
    smart_router = SmartOrderRouter(
        base_router=executor,
        depth_provider=depth_provider,
        volume_provider=volume_provider,
        twap_window_seconds=int(cfg.get("twap_window_seconds", 300)),
        twap_slices=int(cfg.get("twap_slices", 5)),
    )

    # (job already registered atomically with the cap/dup guard above)

    def _observe(live_result: Any) -> None:
        job.result = live_result

    def _run() -> None:
        try:
            final = asyncio.run(
                smart_router.route(
                    symbol=symbol,
                    exchange=exchange,
                    quantity=quantity,
                    action=action,  # type: ignore[arg-type]
                    max_slippage_bps=max_slippage_bps,
                    urgency=urgency,  # type: ignore[arg-type]
                    strategy="smart-route",
                    product=product,
                    result_observer=_observe,
                )
            )
            job.result = final
            # "cancelled" only when the cancel actually CURTAILED the route —
            # a cancel that lands after the last child already placed (the
            # route carries no abort error) is an honest "done", not a
            # mislabelled cancellation.
            cancel_took_effect = job.cancel_requested and bool(final.error)
            if cancel_took_effect:
                job.status = "cancelled"
            elif final.error:
                job.status = "error"
            else:
                job.status = "done"
            job.error = final.error
        except Exception:  # pragma: no cover — route() catches internally
            logger.exception("smart-route job %s crashed", job.job_id)
            job.status = "error"
            job.error = "smart route failed"

    worker = threading.Thread(target=_run, name=f"smart-route-{job.job_id}", daemon=True)
    with _JOBS_LOCK:
        if not _ACCEPTING_JOBS or job.cancel_requested:
            job.status = "cancelled"
            job.error = "smart-order runtime is shutting down"
            return jsonify({
                "status": "error",
                "message": "Smart-order routing is shutting down",
            }), 503
        job.worker = worker
        # Start while holding the ownership lock so shutdown cannot observe an
        # assigned-but-not-started worker and return before it begins.
        worker.start()

    logger.info(
        "Smart-route job started | job=%s %s %s qty=%d urgency=%s adapter=%s account=%s",
        job.job_id, action, symbol, quantity, urgency, adapter_id, account_id,
    )
    return jsonify({"status": "success", "data": _snapshot(job)}), 202


def _require_auth() -> tuple[Any, int] | None:
    """Return a 401 response when the request carries no valid JWT.

    Job snapshots expose live order details (symbols, quantities, broker
    order ids) — operator-only data, not a public surface.
    """
    from .order_routes import _decode_request_payload  # noqa: PLC0415

    if _decode_request_payload() is None:
        return jsonify({
            "status": "error",
            "message": "Authentication required — provide a valid JWT",
        }), 401
    return None


@smart_order_bp.route("/smart-route/<job_id>", methods=["GET"])
def smart_route_status(job_id: str) -> tuple[Any, int]:
    """Return a smart-route job's live snapshot, or 404 when unknown."""
    denied = _require_auth()
    if denied is not None:
        return denied
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
    if job is None:
        return jsonify({"status": "error", "message": f"Unknown smart-route job {job_id}"}), 404
    return jsonify({"status": "success", "data": _snapshot(job)}), 200


@smart_order_bp.route("/smart-route", methods=["GET"])
def smart_route_list() -> tuple[Any, int]:
    """Return snapshots of the most recent smart-route jobs (newest first)."""
    denied = _require_auth()
    if denied is not None:
        return denied
    with _JOBS_LOCK:
        jobs = list(_JOBS.values())
    snapshots = [_snapshot(j) for j in reversed(jobs)]
    return jsonify({"status": "success", "data": snapshots}), 200


@smart_order_bp.route("/smart-route/<job_id>/cancel", methods=["POST"])
def smart_route_cancel(job_id: str) -> tuple[Any, int]:
    """Request cancellation of a running smart-route job.

    The flag is honoured before the NEXT child order (and during TWAP/chunk
    sleeps at the next wake-up) — children already accepted by the broker are
    not recalled. Idempotent; cancelling a finished job is a no-op.
    """
    denied = _require_auth()
    if denied is not None:
        return denied
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
    if job is None:
        return jsonify({"status": "error", "message": f"Unknown smart-route job {job_id}"}), 404
    job.cancel_requested = True
    logger.info("Smart-route job %s cancellation requested", job_id)
    return jsonify({"status": "success", "data": _snapshot(job)}), 200
