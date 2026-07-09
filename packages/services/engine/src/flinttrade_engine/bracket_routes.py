"""Bracket order Flask Blueprint — POST/GET/DELETE for bracket orders.

All endpoints live under ``/api/v1/orders/`` and delegate to a
:class:`~flinttrade_engine.bracket_order.BracketOrderService` instance
stored on ``app.config["BRACKET_SERVICE"]``, constructed by the core app
with GATED leg dispatchers (SafetySystem L1–L5 → ``gate_order`` →
``BrokerRouter``) — see
:func:`~flinttrade_engine.bracket_order.build_gated_leg_dispatchers`.

Both write routes (place + cancel) are behind
:func:`~flinttrade_engine.mode_guard.require_live_unlocked`:

- **explore** → 403 ``mode_blocked``
- **practice** → 403 ``practice_unsupported`` — the sandbox cannot execute
  multi-leg brackets, so a Practice JWT gets an honest refusal instead of a
  silent live order
- **live** without the PIN-minted ``live_mode_unlocked`` claim → 403
  ``live_locked``

Supported bracket shape today (OCO honesty): entry + EXACTLY ONE protective
exit leg (``stoploss`` OR ``target``). A ``stoploss``+``target`` pair
(``code="oco_unsupported"``) and ``trailing_sl``
(``code="trailing_unsupported"``) are refused with HTTP 422 because no fill
monitor exists yet to cancel the sibling leg / trail the stop.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from flask import Blueprint, Response, current_app, jsonify, request

from flinttrade_core.rate_limiter import rate_limit

from .bracket_order import BracketOrderError, BracketPrincipal
from .mode_guard import _decode_payload, require_live_unlocked

logger = logging.getLogger("flinttrade.engine.bracket_routes")

bracket_bp = Blueprint("brackets", __name__, url_prefix="/api/v1/orders")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_service():
    """Retrieve the BracketOrderService from the Flask app config."""
    return current_app.config.get("BRACKET_SERVICE")


def _service_required() -> tuple[Any, Response | None]:
    """Return (service, None) or (None, error_response)."""
    svc = _get_service()
    if svc is None:
        return None, (
            jsonify({"status": "error", "message": "Bracket service not configured"}),
            503,
        )
    return svc, None


def _resolve_target(params: Mapping[str, Any]) -> tuple[str, str]:
    """Resolve the ``(adapter_id, account_id)`` broker target for a bracket write.

    Explicit ``broker``/``account_id`` request fields win; otherwise the
    configured ``brokers.execution.default`` selector is used (mirroring the
    core order routes' target resolution), falling back to
    ``("openalgo", "default")``.

    Args:
        params: Mapping-like request body carrying optional ``broker`` and
            ``account_id`` fields.

    Returns:
        The ``(adapter_id, account_id)`` tuple.
    """
    if str(params.get("broker") or "").strip() or str(params.get("account_id") or "").strip():
        adapter_id = str(params.get("broker") or "openalgo").strip().lower()
        account_id = str(params.get("account_id") or "default").strip() or "default"
        return adapter_id, account_id

    router = current_app.config.get("BROKER_ROUTER")
    selector = str(getattr(router, "default_selector", None) or "").strip()
    if selector:
        try:
            from .request_context import parse_selector  # noqa: PLC0415

            return parse_selector(selector)
        except ValueError:
            logger.warning("Ignoring malformed brokers.execution.default selector")
    return "openalgo", "default"


def _request_principal(body: Mapping[str, Any]) -> BracketPrincipal:
    """Build the selector-bound principal for a bracket write from the request.

    Identity (actor/jti) comes from the verified session JWT (the
    ``require_live_unlocked`` guard has already validated it); the broker
    target comes from :func:`_resolve_target`.

    Args:
        body: Decoded JSON request body (may be empty for DELETE).

    Returns:
        The BracketPrincipal every gated leg write is bound to.
    """
    payload = _decode_payload() or {}
    actor_id = str(payload.get("sub") or payload.get("actor_id") or "unknown")
    jti = str(payload.get("jti") or "")
    adapter_id, account_id = _resolve_target(body)
    return BracketPrincipal(
        actor_id=actor_id, jti=jti, adapter_id=adapter_id, account_id=account_id
    )


# ---------------------------------------------------------------------------
# POST /api/v1/orders/bracket  — place bracket order
# ---------------------------------------------------------------------------


@bracket_bp.route("/bracket", methods=["POST"])
@require_live_unlocked
@rate_limit("orders", user_rate=10, global_rate=100)
def place_bracket() -> Response:
    """Place a bracket order — entry plus ONE protective exit leg.

    Every leg traverses the gated live chain (SafetySystem L1–L5 →
    ``gate_order`` one-shot HMAC ``SafetyContext`` → ``BrokerRouter``).
    Practice-mode JWTs are refused with 403 ``practice_unsupported`` by the
    route guard — the sandbox cannot execute multi-leg brackets.

    Supported today: entry + EXACTLY ONE of ``stoploss`` (stop-loss exit leg)
    or ``target`` (limit exit leg). Refused honestly with HTTP 422:

    - ``stoploss`` + ``target`` together (``code="oco_unsupported"``) — with
      no fill monitor, the sibling leg could not be cancelled when one leg
      fills, leaving both exits live;
    - ``trailing_sl`` (``code="trailing_unsupported"``) — nothing exists yet
      to trail the stop.

    Request body (JSON):

    .. code-block:: json

        {
            "entry": {
                "symbol": "NIFTY25APRFUT",
                "exchange": "NFO",
                "action": "BUY",
                "quantity": 50,
                "price": 0,
                "strategy": "Flint",
                "product": "MIS"
            },
            "stoploss": 22000.0,
            "broker": "openalgo",
            "account_id": "default"
        }

    ``broker``/``account_id`` are optional — the configured
    ``brokers.execution.default`` selector is the fallback target.

    Returns:
        201 with bracket details on success; 400 on bad input; 401/403 from
        the mode guard; 422 for unsupported/failed placement — a bracket with
        ``status="partial"`` in ``data`` means the entry leg is live but
        UNPROTECTED (the exit leg failed) and needs operator action; 503 when
        the service or broker routing is unavailable.
    """
    svc, err = _service_required()
    if err:
        return err

    body: dict[str, Any] = request.get_json(silent=True) or {}

    entry = body.get("entry")
    if not entry or not isinstance(entry, dict):
        return jsonify({"status": "error", "message": "'entry' object is required"}), 400

    def _optional_float(key: str) -> tuple[float | None, Response | None]:
        raw = body.get(key)
        if raw is None:
            return None, None
        try:
            return float(raw), None
        except (TypeError, ValueError):
            return None, (
                jsonify({"status": "error", "message": f"'{key}' must be a number"}),
                400,
            )

    stoploss, sl_err = _optional_float("stoploss")
    if sl_err:
        return sl_err
    target, tgt_err = _optional_float("target")
    if tgt_err:
        return tgt_err
    trailing_sl, trail_err = _optional_float("trailing_sl")
    if trail_err:
        return trail_err

    # OCO honesty — refuse what the service cannot honour (no fill monitor).
    if trailing_sl is not None:
        return (
            jsonify(
                {
                    "status": "error",
                    "code": "trailing_unsupported",
                    "message": (
                        "trailing_sl is not supported yet: the bracket service has "
                        "no fill monitor to trail the stop. Omit trailing_sl and "
                        "manage the stop manually."
                    ),
                }
            ),
            422,
        )
    if stoploss is not None and target is not None:
        return (
            jsonify(
                {
                    "status": "error",
                    "code": "oco_unsupported",
                    "message": (
                        "stoploss and target together (an OCO pair) are not "
                        "supported yet: without a fill monitor the sibling leg "
                        "cannot be cancelled when one leg fills, which would leave "
                        "both exit legs live. Provide exactly one of stoploss or "
                        "target."
                    ),
                }
            ),
            422,
        )
    if stoploss is None and target is None:
        return (
            jsonify(
                {
                    "status": "error",
                    "message": (
                        "Provide exactly one of 'stoploss' or 'target' — a bracket "
                        "needs one protective exit leg."
                    ),
                }
            ),
            400,
        )

    principal = _request_principal(body)
    result = svc.place_bracket(
        entry,
        stoploss=stoploss,
        target=target,
        trailing_sl=None,
        principal=principal,
    )

    if not result.success:
        payload: dict[str, Any] = {
            "status": "error",
            "message": result.message,
            "error": result.error,
        }
        # A "partial" bracket (entry live, exit leg failed) MUST reach the
        # caller so the unprotected position is visible and actionable.
        if result.bracket is not None:
            payload["data"] = result.bracket.to_dict()
        return jsonify(payload), 422

    return (
        jsonify(
            {
                "status": "success",
                "message": result.message,
                "data": result.bracket.to_dict() if result.bracket else None,
            }
        ),
        201,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/orders/brackets  — list active brackets
# ---------------------------------------------------------------------------


@bracket_bp.route("/brackets", methods=["GET"])
def list_brackets() -> Response:
    """List all active (non-completed, non-cancelled) bracket orders.

    Read-only — no broker write, so no live-unlock guard (matching the
    codebase convention for order-state reads).

    Returns:
        JSON with ``data.brackets`` list.
    """
    svc, err = _service_required()
    if err:
        return err

    brackets = svc.get_active_brackets()
    return jsonify(
        {
            "status": "success",
            "data": {
                "count": len(brackets),
                "brackets": [b.to_dict() for b in brackets],
            },
        }
    )


# ---------------------------------------------------------------------------
# DELETE /api/v1/orders/bracket/<id>  — cancel bracket
# ---------------------------------------------------------------------------


@bracket_bp.route("/bracket/<bracket_id>", methods=["DELETE"])
@require_live_unlocked
@rate_limit("orders", user_rate=10, global_rate=100)
def cancel_bracket(bracket_id: str) -> Response:
    """Cancel all resting legs of a bracket order — a live broker WRITE.

    Each leg cancel dispatches through the gated ``BrokerRouter`` cancel verb
    (one-shot ``SafetyContext`` + account ACL) bound to the selector the
    bracket was placed on. Guarded exactly like placement: Practice JWTs get
    403 ``practice_unsupported``, a locked Live session gets 403
    ``live_locked``. Cancellation is best-effort per leg — a leg that already
    filled at the broker cannot be cancelled; the failure is recorded and the
    remaining legs are still swept. When EVERY leg cancel fails the service
    fails closed (503) and the bracket stays tracked. The 200 body carries
    ``data.warnings`` with honest caveats — e.g. a filled MARKET entry
    position that this cancel does NOT close.

    Args:
        bracket_id: UUID of the bracket to cancel.

    Returns:
        200 on success (with ``data.warnings``); 401/403 from the mode guard;
        404 if the bracket is unknown; 409 if it is already
        completed/cancelled; 503 when the service or the gated cancel path is
        unavailable or every leg cancel failed.
    """
    svc, err = _service_required()
    if err:
        return err

    # Check existence first for a clean 404
    bracket = svc.get_bracket(bracket_id)
    if bracket is None:
        return jsonify({"status": "error", "message": f"Bracket '{bracket_id}' not found"}), 404

    principal = _request_principal(request.get_json(silent=True) or {})
    try:
        cancelled = svc.cancel_bracket(bracket_id, principal=principal)
    except BracketOrderError as exc:
        # Fail-closed cancel path. Log the underlying detail server-side (it may
        # embed raw broker/dispatcher exception text); return a FIXED, still
        # actionable operator message so no internal detail is reflected to the
        # caller (CodeQL py/stack-trace-exposure — same treatment as the other
        # routes). The operator still learns the legs may be live and what to do.
        logger.error("Bracket cancel unavailable for '%s': %s", bracket_id, exc)
        return jsonify({
            "status": "error",
            "message": (
                "The bracket could not be cancelled and its legs may still rest "
                "live at the broker. Retry, or square off the position directly "
                "at your broker."
            ),
        }), 503

    if not cancelled:
        return (
            jsonify(
                {
                    "status": "error",
                    "message": (
                        f"Bracket '{bracket_id}' could not be cancelled — "
                        "it may already be completed or cancelled"
                    ),
                }
            ),
            409,
        )

    warnings = list(bracket.cancel_warnings)
    message = f"Bracket '{bracket_id}' cancelled"
    if warnings:
        message += " — " + " ".join(warnings)
    return jsonify(
        {
            "status": "success",
            "message": message,
            "data": {"warnings": warnings},
        }
    )
