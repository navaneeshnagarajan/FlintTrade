"""Bracket order service — entry + ONE protective exit leg as a tracked group.

Every leg WRITE traverses the gated live-order chain (contract §8.1):
``SafetySystem`` L1–L5 → :func:`~flinttrade_engine.safety.gate_order` (one-shot
HMAC ``SafetyContext`` bound to the selector-bound principal) →
``BrokerRouter`` (ACL + re-verification + one-shot gate consumption) → broker
adapter. The dispatch callables are injected by the Flask app via
:func:`build_gated_leg_dispatchers`; the service itself never holds a raw
broker/OpenAlgo client for writes, so an ungated leg write is structurally
impossible (``gateway/tests/test_no_legacy_order_path.py`` pins this).

OCO honesty: FlintTrade has no fill monitor for bracket legs yet, so the
service refuses configurations it cannot honour rather than silently leaving
both exit legs live:

* a ``stoploss`` + ``target`` pair (a true OCO — when one leg filled, nobody
  would cancel the sibling, so the survivor could open a reverse position);
* ``trailing_sl`` (nobody would trail the stop).

Supported today: entry + EXACTLY ONE protective exit leg (``stoploss`` OR
``target``). Once a fill monitor lands, sibling-cancel via the gated cancel
verb (already implemented for :meth:`BracketOrderService.cancel_bracket`)
unlocks the full OCO pair.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

from flask import Flask

from flinttrade_core.models import Action, Exchange, Order, PriceType, Product

logger = logging.getLogger("flinttrade.engine.bracket_order")


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class BracketOrderError(Exception):
    """Raised when bracket order placement, cancellation, or dispatch fails."""


class BracketNotFoundError(KeyError):
    """Raised when a bracket_id does not exist in the registry."""


# ---------------------------------------------------------------------------
# Principal + dispatcher types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BracketPrincipal:
    """Identity + broker target that every gated bracket-leg write is bound to.

    Attributes:
        actor_id: Operator identity from the verified session JWT (``sub``).
        jti: JWT id of the live session making the request.
        adapter_id: Target broker adapter (e.g. ``"openalgo"``, ``"dhan"``).
        account_id: Target account within the adapter.
    """

    actor_id: str
    jti: str
    adapter_id: str = "openalgo"
    account_id: str = "default"


# place_leg(order, principal) -> broker order id; raises BracketOrderError on refusal/failure.
PlaceLegFn = Callable[[Order, BracketPrincipal], str]
# cancel_leg(order_id, principal) -> None; raises BracketOrderError on refusal/failure.
CancelLegFn = Callable[[str, BracketPrincipal], None]


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class BracketOrder:
    """Full state of a bracket order group.

    Attributes:
        bracket_id: Unique identifier for this bracket.
        entry_order_id: Broker order id for the entry leg.
        sl_order_id: Order id for the stop-loss leg (``None`` when the bracket
            uses a target exit, or the exit leg failed to place).
        target_order_id: Order id for the target leg (``None`` when the bracket
            uses a stoploss exit, or the exit leg failed to place).
        symbol: Instrument symbol (e.g. ``"NIFTY25APRFUT"``).
        exchange: Exchange code (e.g. ``"NFO"``).
        action: ``"BUY"`` or ``"SELL"`` — direction of the entry.
        quantity: Number of lots/shares.
        entry_price: Requested entry price (0 for MARKET).
        stoploss: Absolute SL price, or ``None`` when the exit is a target.
        target: Absolute target price, or ``None`` when the exit is a stoploss.
        trailing_sl: Always ``None`` today — trailing is refused at placement.
        strategy: Strategy name tag forwarded on every leg.
        product: Product type (``MIS`` / ``NRML`` / ``CNC``).
        adapter_id: Broker adapter the legs were placed on (cancel targets it).
        account_id: Account within the adapter the legs were placed on.
        entry_pricetype: Entry leg price type — a MARKET entry is never
            broker-cancelled (it fills immediately), a LIMIT entry is swept on
            bracket cancel.
        status: One of ``"active"`` | ``"partial"`` | ``"completed"`` |
            ``"cancelled"``.
        cancel_warnings: Honest caveats from the last cancel (legs that could
            not be confirmed cancelled; a filled MARKET entry position that
            remains open). Empty until a cancel produces one.
        created_at: ISO 8601 UTC timestamp of creation.
        updated_at: ISO 8601 UTC timestamp of last update.
    """

    bracket_id: str
    entry_order_id: str
    sl_order_id: str | None
    target_order_id: str | None
    symbol: str
    exchange: str
    action: str  # "BUY" | "SELL"
    quantity: int
    entry_price: float
    stoploss: float | None
    target: float | None
    trailing_sl: float | None = None
    strategy: str = "Flint"
    product: str = "MIS"
    adapter_id: str = "openalgo"
    account_id: str = "default"
    entry_pricetype: str = "MARKET"
    status: str = "active"
    cancel_warnings: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict for API responses."""
        return {
            "bracket_id": self.bracket_id,
            "entry_order_id": self.entry_order_id,
            "sl_order_id": self.sl_order_id,
            "target_order_id": self.target_order_id,
            "symbol": self.symbol,
            "exchange": self.exchange,
            "action": self.action,
            "quantity": self.quantity,
            "entry_price": self.entry_price,
            "stoploss": self.stoploss,
            "target": self.target,
            "trailing_sl": self.trailing_sl,
            "strategy": self.strategy,
            "product": self.product,
            "broker": self.adapter_id,
            "status": self.status,
            "cancel_warnings": list(self.cancel_warnings),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class BracketResult:
    """Outcome of a bracket service operation.

    Attributes:
        success: Whether the operation succeeded.
        bracket: The BracketOrder state after the operation.
        message: Human-readable description of the outcome.
        error: Non-empty only when ``success`` is ``False``.
    """

    success: bool
    bracket: BracketOrder | None
    message: str
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict for API responses."""
        return {
            "success": self.success,
            "bracket": self.bracket.to_dict() if self.bracket else None,
            "message": self.message,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _validate_bracket_params(
    entry: dict[str, Any],
    stoploss: float | None,
    target: float | None,
    trailing_sl: float | None,
) -> list[str]:
    """Return a list of validation error strings, empty if all params are valid.

    Args:
        entry: Entry order dict with at minimum ``symbol``, ``exchange``,
            ``action``, and ``quantity`` keys.
        stoploss: Absolute SL price for the protective exit, or ``None``.
        target: Absolute target price for the protective exit, or ``None``.
        trailing_sl: Trailing SL distance; always refused (no fill monitor).

    Returns:
        List of human-readable error messages. Empty list means valid.
    """
    errors: list[str] = []

    # Required entry fields
    for key in ("symbol", "exchange", "action", "quantity"):
        if not entry.get(key):
            errors.append(f"entry.{key} is required")

    action = str(entry.get("action", "")).upper()
    if action not in ("BUY", "SELL"):
        errors.append(f"entry.action must be BUY or SELL, got '{action}'")

    qty = entry.get("quantity", 0)
    try:
        if int(qty) <= 0:
            errors.append("entry.quantity must be a positive integer")
    except (TypeError, ValueError):
        errors.append(f"entry.quantity must be an integer, got '{qty}'")

    # OCO honesty — refuse what cannot be honoured (no fill monitor yet).
    if trailing_sl is not None:
        errors.append(
            "trailing_sl is not supported yet: the bracket service has no fill "
            "monitor to trail the stop. Omit trailing_sl and manage the stop manually."
        )

    if stoploss is not None and target is not None:
        errors.append(
            "stoploss and target together (an OCO pair) are not supported yet: "
            "without a fill monitor the sibling leg cannot be cancelled when one "
            "leg fills, which would leave both exit legs live. Provide exactly "
            "one of stoploss or target."
        )
    elif stoploss is None and target is None:
        errors.append(
            "Provide exactly one of stoploss or target — a bracket needs one "
            "protective exit leg."
        )

    if stoploss is not None and stoploss <= 0:
        errors.append(f"stoploss must be > 0, got {stoploss}")

    if target is not None and target <= 0:
        errors.append(f"target must be > 0, got {target}")

    return errors


# ---------------------------------------------------------------------------
# BracketOrderService
# ---------------------------------------------------------------------------


class BracketOrderService:
    """Bracket order implementation for FlintTrade — gated writes only.

    Places the entry leg, then the single protective exit leg, tracking both
    under one ``bracket_id`` in an in-memory registry. Every broker write goes
    through the injected gated dispatchers (SafetySystem → ``gate_order`` →
    ``BrokerRouter``); the service holds NO broker/OpenAlgo client, so it
    fails closed when the dispatchers are absent instead of simulating fills.

    Usage::

        place_leg, cancel_leg = build_gated_leg_dispatchers(app)
        service = BracketOrderService(place_leg=place_leg, cancel_leg=cancel_leg)
        result = service.place_bracket(
            entry={"symbol": "NIFTY25APRFUT", "exchange": "NFO",
                   "action": "BUY", "quantity": 50},
            stoploss=22000.0,
            principal=BracketPrincipal(actor_id="operator", jti="…"),
        )
        if result.success:
            bracket_id = result.bracket.bracket_id
    """

    def __init__(
        self,
        place_leg: PlaceLegFn | None = None,
        cancel_leg: CancelLegFn | None = None,
        default_strategy: str = "Flint",
        default_product: str = "MIS",
    ) -> None:
        self._place_leg = place_leg
        self._cancel_leg = cancel_leg
        self._default_strategy = default_strategy
        self._default_product = default_product
        # bracket_id → BracketOrder
        self._registry: dict[str, BracketOrder] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def place_bracket(
        self,
        entry: dict[str, Any],
        stoploss: float | None = None,
        target: float | None = None,
        trailing_sl: float | None = None,
        principal: BracketPrincipal | None = None,
    ) -> BracketResult:
        """Place a bracket order (entry + ONE protective exit leg).

        Steps:
        1. Validate bracket parameters (incl. the OCO-honesty refusals).
        2. Place the entry leg through the gated dispatcher.
        3. Place the single protective exit leg (SL or target) the same way.
        4. Track both legs under a single bracket_id.

        Both legs traverse SafetySystem L1–L5 → ``gate_order`` →
        ``BrokerRouter`` via the injected dispatcher. If the exit leg fails
        after the entry was placed, the bracket is registered with status
        ``"partial"`` and the result is a FAILURE whose message states the
        position is unprotected — the caller must react.

        Args:
            entry: Dict with at minimum ``symbol``, ``exchange``, ``action``,
                and ``quantity``.  Optional keys: ``price`` (0 = MARKET),
                ``strategy``, ``product``, ``pricetype``.
            stoploss: Absolute SL price for the exit leg (mutually exclusive
                with ``target``).
            target: Absolute target price for the exit leg (mutually exclusive
                with ``stoploss``).
            trailing_sl: Always refused — no fill monitor exists to trail.
            principal: Identity + broker target the leg writes are bound to.
                Required — writes without a principal are refused.

        Returns:
            BracketResult with ``success`` flag and the created BracketOrder.
        """
        # Fail CLOSED without a gated dispatcher or principal — the service
        # must never invent simulated order ids on the write path.
        if self._place_leg is None:
            return BracketResult(
                success=False,
                bracket=None,
                message="Bracket service is not wired to the gated order path",
                error=(
                    "No gated placement dispatcher is configured — refusing to "
                    "place orders. Construct the service via "
                    "build_gated_leg_dispatchers()."
                ),
            )
        if principal is None:
            return BracketResult(
                success=False,
                bracket=None,
                message="Bracket placement requires a principal",
                error="No selector-bound principal supplied — refusing the broker write.",
            )

        # Step 1 — validate
        errors = _validate_bracket_params(entry, stoploss, target, trailing_sl)
        if errors:
            return BracketResult(
                success=False,
                bracket=None,
                message="Bracket parameter validation failed",
                error="; ".join(errors),
            )

        symbol: str = str(entry["symbol"])
        exchange: str = str(entry["exchange"]).upper()
        action: str = str(entry["action"]).upper()
        quantity: int = int(entry["quantity"])
        price: float = float(entry.get("price", 0))
        strategy: str = str(entry.get("strategy", self._default_strategy))
        product: str = str(entry.get("product", self._default_product))
        pricetype: str = str(entry.get("pricetype", "MARKET" if price == 0 else "LIMIT")).upper()

        bracket_id = str(uuid.uuid4())

        # Step 2 — build + place the entry leg through the gated dispatcher
        try:
            entry_order = Order(
                symbol=symbol,
                action=Action(action),
                exchange=Exchange(exchange),
                pricetype=PriceType(pricetype),
                product=Product(product),
                quantity=str(quantity),
                price=str(price),
                strategy=strategy,
            )
        except (ValueError, KeyError) as exc:
            return BracketResult(
                success=False,
                bracket=None,
                message="Failed to build entry order model",
                error=str(exc),
            )

        try:
            entry_order_id = self._place_leg(entry_order, principal)
        except Exception as exc:
            logger.error("Bracket entry leg failed for %s: %s", symbol, exc)
            return BracketResult(
                success=False,
                bracket=None,
                message="Entry order placement failed",
                error=str(exc),
            )

        # Step 3 — build + place the single protective exit leg
        exit_action = "SELL" if action == "BUY" else "BUY"
        exit_kind = "stoploss" if stoploss is not None else "target"

        try:
            if stoploss is not None:
                exit_order = Order(
                    symbol=symbol,
                    action=Action(exit_action),
                    exchange=Exchange(exchange),
                    pricetype=PriceType.SL,
                    product=Product(product),
                    quantity=str(quantity),
                    price=str(stoploss),
                    trigger_price=str(stoploss),
                    strategy=strategy,
                )
            else:
                exit_order = Order(
                    symbol=symbol,
                    action=Action(exit_action),
                    exchange=Exchange(exchange),
                    pricetype=PriceType.LIMIT,
                    product=Product(product),
                    quantity=str(quantity),
                    price=str(target),
                    strategy=strategy,
                )
        except (ValueError, KeyError) as exc:
            # Entry already placed — register as partial so the operator sees it.
            logger.warning("Bracket exit-leg model build failed for %s: %s", symbol, exc)
            bracket = self._register_bracket(
                bracket_id=bracket_id,
                entry_order_id=entry_order_id,
                sl_order_id=None,
                target_order_id=None,
                symbol=symbol,
                exchange=exchange,
                action=action,
                quantity=quantity,
                entry_price=price,
                stoploss=stoploss,
                target=target,
                trailing_sl=None,
                strategy=strategy,
                product=product,
                principal=principal,
                entry_pricetype=pricetype,
                status="partial",
            )
            return BracketResult(
                success=False,
                bracket=bracket,
                message=(
                    "Entry leg placed but the protective exit leg failed to build "
                    "— the position is UNPROTECTED. Cancel the bracket or place "
                    "an exit order manually."
                ),
                error=str(exc),
            )

        exit_order_id: str | None = None
        exit_error = ""
        try:
            exit_order_id = self._place_leg(exit_order, principal)
        except Exception as exc:
            exit_error = str(exc)
            logger.error(
                "Bracket %s exit leg (%s) placement failed: %s", bracket_id, exit_kind, exc
            )

        # Step 4 — register bracket
        status = "active" if exit_order_id else "partial"
        bracket = self._register_bracket(
            bracket_id=bracket_id,
            entry_order_id=entry_order_id,
            sl_order_id=exit_order_id if exit_kind == "stoploss" else None,
            target_order_id=exit_order_id if exit_kind == "target" else None,
            symbol=symbol,
            exchange=exchange,
            action=action,
            quantity=quantity,
            entry_price=price,
            stoploss=stoploss,
            target=target,
            trailing_sl=None,
            strategy=strategy,
            product=product,
            principal=principal,
            entry_pricetype=pricetype,
            status=status,
        )

        if status == "partial":
            return BracketResult(
                success=False,
                bracket=bracket,
                message=(
                    "Entry leg placed but the protective exit leg failed — the "
                    "position is UNPROTECTED. Cancel the bracket or place an "
                    "exit order manually."
                ),
                error=exit_error,
            )

        logger.info(
            "Bracket %s placed | %s %s %s qty=%d exit=%s status=%s",
            bracket_id, action, symbol, exchange, quantity, exit_kind, status,
        )

        return BracketResult(
            success=True,
            bracket=bracket,
            message=f"Bracket placed: entry + {exit_kind} exit leg",
        )

    def modify_bracket(
        self,
        bracket_id: str,
        new_sl: float | None = None,
        new_target: float | None = None,
    ) -> BracketResult:
        """Refuse a bracket modification — not yet routed through the gated path.

        A local-only registry update would silently diverge from the broker's
        resting leg (the UI would show a moved stop that never moved), so the
        honest behaviour is to refuse until a gated modify verb is wired.

        Args:
            bracket_id: The bracket the caller wanted to modify.
            new_sl: Ignored — kept for signature compatibility.
            new_target: Ignored — kept for signature compatibility.

        Returns:
            A failure BracketResult explaining the refusal (or the not-found
            case when ``bracket_id`` is unknown).
        """
        del new_sl, new_target  # deliberately unused — the refusal is total
        bracket = self._registry.get(bracket_id)
        if bracket is None:
            return BracketResult(
                success=False,
                bracket=None,
                message="Bracket not found",
                error=f"No bracket with id '{bracket_id}'",
            )

        return BracketResult(
            success=False,
            bracket=bracket,
            message="Bracket modify is not supported yet",
            error=(
                "Modifying bracket legs is not yet routed through the gated "
                "broker path. Cancel the bracket and place a new one."
            ),
        )

    def cancel_bracket(
        self,
        bracket_id: str,
        principal: BracketPrincipal | None = None,
    ) -> bool:
        """Cancel all resting legs of a bracket order through the gated path.

        Each leg cancel is dispatched through the injected gated cancel
        dispatcher, bound to the SAME broker selector the legs were placed on
        (never the caller-supplied target). Cancellation is best-effort per
        leg: a leg that already filled at the broker cannot be cancelled — the
        failure is recorded in ``bracket.cancel_warnings`` and the remaining
        legs are still swept. When EVERY leg cancel fails, the sweep fails
        closed instead: the registry must not claim "cancelled" while all legs
        may still rest live at the broker. A MARKET entry leg is never
        broker-cancelled (it filled at placement); a LIMIT entry leg is swept
        alongside the exit leg. Cancelling a bracket whose MARKET entry was
        placed records a warning that the entry position remains open — the
        cancel removes protective legs and tracking, never the position.

        Args:
            bracket_id: The bracket to cancel.
            principal: The caller's identity; its broker target is rebound to
                the bracket's stored selector.

        Returns:
            ``True`` if the bracket was found and cancelled, ``False`` if not
            found or already completed/cancelled. Caveats from the sweep are
            on ``bracket.cancel_warnings``.

        Raises:
            BracketOrderError: When broker-side legs exist but no gated cancel
                dispatcher or principal is available, or when every leg cancel
                failed (fails closed — the registry must not claim "cancelled"
                while legs rest live).
        """
        bracket = self._registry.get(bracket_id)
        if bracket is None:
            logger.warning("cancel_bracket: bracket '%s' not found", bracket_id)
            return False

        if bracket.status in ("completed", "cancelled"):
            logger.info(
                "cancel_bracket: bracket '%s' already %s", bracket_id, bracket.status
            )
            return False

        legs: list[tuple[str, str]] = []
        if bracket.entry_order_id and bracket.entry_pricetype != "MARKET":
            legs.append((bracket.entry_order_id, "entry"))
        if bracket.sl_order_id:
            legs.append((bracket.sl_order_id, "SL"))
        if bracket.target_order_id:
            legs.append((bracket.target_order_id, "target"))

        warnings: list[str] = []
        if legs:
            if self._cancel_leg is None:
                raise BracketOrderError(
                    "No gated cancel dispatcher is configured — refusing to mark "
                    "the bracket cancelled while its legs may rest live at the broker."
                )
            if principal is None:
                raise BracketOrderError(
                    "Bracket cancellation requires a principal — refusing the broker write."
                )
            # Rebind the caller's identity to the selector the legs live on.
            bound = replace(
                principal,
                adapter_id=bracket.adapter_id,
                account_id=bracket.account_id,
            )
            swept: list[str] = []
            failed: list[str] = []
            for order_id, leg_name in legs:
                try:
                    self._cancel_leg(order_id, bound)
                    swept.append(leg_name)
                    logger.info(
                        "Bracket %s %s leg cancelled (order %s)",
                        bracket_id, leg_name, order_id,
                    )
                except Exception as exc:
                    # The leg may already be filled/cancelled at the broker —
                    # record it and keep sweeping the remaining legs.
                    failed.append(f"{leg_name} (order {order_id}): {exc}")
                    logger.warning(
                        "Failed to cancel %s leg %s of bracket %s: %s",
                        leg_name, order_id, bracket_id, exc,
                    )
            if not swept:
                # Every cancel failed — fail closed. Claiming "cancelled" here
                # could leave live legs resting at the broker with no tracking.
                raise BracketOrderError(
                    "Every leg cancel failed — the bracket is NOT cancelled; its "
                    "legs may still rest live at the broker. Retry, or manage the "
                    f"orders at the broker: {'; '.join(failed)}"
                )
            if failed:
                warnings.append(
                    "Some legs could not be confirmed cancelled (they may already "
                    f"be filled or cancelled at the broker): {'; '.join(failed)}"
                )

        if bracket.entry_order_id and bracket.entry_pricetype == "MARKET":
            warnings.append(
                "The MARKET entry position (if filled) remains open — cancelling "
                "a bracket removes its protective legs and tracking, never the "
                "position. Square it off from the Positions widget if needed."
            )

        bracket.cancel_warnings = warnings
        bracket.status = "cancelled"
        bracket.updated_at = datetime.now(UTC).isoformat()
        logger.info("Bracket %s cancelled (%d warnings)", bracket_id, len(warnings))
        return True

    def get_active_brackets(self) -> list[BracketOrder]:
        """Return all brackets that are not completed or cancelled.

        Returns:
            List of BracketOrder objects with status in
            ``"active"`` | ``"partial"``.
        """
        return [
            b for b in self._registry.values()
            if b.status not in ("completed", "cancelled")
        ]

    def get_bracket(self, bracket_id: str) -> BracketOrder | None:
        """Return a bracket by ID, or ``None`` if not found.

        Args:
            bracket_id: The bracket identifier.

        Returns:
            BracketOrder or ``None``.
        """
        return self._registry.get(bracket_id)

    def mark_completed(self, bracket_id: str) -> bool:
        """Mark a bracket as completed (called when the exit leg fills).

        Args:
            bracket_id: The bracket to complete.

        Returns:
            ``True`` if updated, ``False`` if not found.
        """
        bracket = self._registry.get(bracket_id)
        if bracket is None:
            return False
        bracket.status = "completed"
        bracket.updated_at = datetime.now(UTC).isoformat()
        return True

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _register_bracket(
        self,
        *,
        bracket_id: str,
        entry_order_id: str,
        sl_order_id: str | None,
        target_order_id: str | None,
        symbol: str,
        exchange: str,
        action: str,
        quantity: int,
        entry_price: float,
        stoploss: float | None,
        target: float | None,
        trailing_sl: float | None,
        strategy: str,
        product: str,
        principal: BracketPrincipal,
        entry_pricetype: str,
        status: str,
    ) -> BracketOrder:
        bracket = BracketOrder(
            bracket_id=bracket_id,
            entry_order_id=entry_order_id,
            sl_order_id=sl_order_id,
            target_order_id=target_order_id,
            symbol=symbol,
            exchange=exchange,
            action=action,
            quantity=quantity,
            entry_price=entry_price,
            stoploss=stoploss,
            target=target,
            trailing_sl=trailing_sl,
            strategy=strategy,
            product=product,
            adapter_id=principal.adapter_id,
            account_id=principal.account_id,
            entry_pricetype=entry_pricetype,
            status=status,
        )
        self._registry[bracket_id] = bracket
        return bracket


# ---------------------------------------------------------------------------
# Gated leg dispatchers — the ONLY sanctioned write path for bracket legs
# ---------------------------------------------------------------------------


def build_gated_leg_dispatchers(app: Flask) -> tuple[PlaceLegFn, CancelLegFn]:
    """Build the gated place/cancel leg dispatchers bound to a Flask app.

    Every placement traverses the SAME enforced chain as a human ``/place``
    order (contract §8.1): SafetySystem L1–L5 (with complete selector-scoped
    state and post-order Layer 3 Greeks) → :func:`~flinttrade_engine.safety.gate_order`
    (one-shot HMAC ``SafetyContext`` bound to the selector-bound principal) →
    ``BrokerRouter.place_order`` (ACL + field-by-field re-verification +
    one-shot gate consumption) → broker adapter. Cancels mint the canonical
    ``{"_op": "cancel", …}`` fingerprint and dispatch through
    ``BrokerRouter.cancel_order`` (deliberately NOT kill-switch gated — a
    halted account must still be able to flatten its resting legs).

    The returned callables close over the app config; the bracket service
    holds them instead of any broker client, so a raw client write from the
    bracket path is structurally impossible.

    Args:
        app: The Flask application whose config carries ``BROKER_ROUTER``,
            ``SAFETY``, ``CLIENT``/``OPENALGO_CLIENT`` and ``AUDIT``.

    Returns:
        ``(place_leg, cancel_leg)`` callables for :class:`BracketOrderService`.
    """

    def _call_on_owner_loop(coro: Any) -> Any:
        # Broker-bound coroutines must run on the shared client's owner event
        # loop (pooled httpx connections are loop-affine) — mirrors the human
        # order path. Falls back to a fresh loop for test fakes/no client.
        from flinttrade_core.openalgo_client import client_call_sync  # noqa: PLC0415

        client = app.config.get("CLIENT") or app.config.get("OPENALGO_CLIENT")
        return client_call_sync(client, coro)

    def _require_router() -> Any:
        router = app.config.get("BROKER_ROUTER")
        if router is None:
            raise BracketOrderError(
                "Order routing unavailable — workspace.json brokers configuration "
                "is missing or invalid. Check the startup logs, fix workspace.json, "
                "then restart."
            )
        return router

    def _request_ctx(principal: BracketPrincipal) -> Any:
        from .request_context import RequestContext  # noqa: PLC0415

        return RequestContext(
            jti=principal.jti,
            actor_type="human",
            actor_id=principal.actor_id,
            mode="live",
            selector=f"{principal.adapter_id}:{principal.account_id}",
        )

    def _audit(event: str, principal: BracketPrincipal, **fields: Any) -> None:
        try:
            audit = app.config.get("AUDIT")
            if audit is not None:
                audit.log_event(
                    event,
                    adapter_id=principal.adapter_id,
                    account_id=principal.account_id,
                    actor_id=principal.actor_id,
                    **fields,
                )
        except Exception:  # pragma: no cover — audit must never break the order path
            logger.debug("bracket audit stamp failed", exc_info=True)

    def place_leg(order: Order, principal: BracketPrincipal) -> str:
        """Place ONE bracket leg through the gated chain; return the broker order id.

        Raises:
            BracketOrderError: On any safety block, gate refusal, missing
                broker session, unsupported capability, or dispatch fault —
                the caller must treat the leg as NOT placed.
        """
        from flinttrade_core.exceptions import (  # noqa: PLC0415
            SafetyBypassError,
            UnsupportedCapabilityError,
        )
        from flinttrade_gateway.exceptions import BrokerNotFoundError  # noqa: PLC0415
        from flinttrade_gateway.routing_config import RoutingHint  # noqa: PLC0415

        from .algo_tag_guard import AlgoTagLimitError  # noqa: PLC0415
        from .safety import gate_order  # noqa: PLC0415

        router = _require_router()

        try:
            from flinttrade_core.safety_config import (  # noqa: PLC0415
                SafetyRuntimeUnavailable,
                require_ready_safety,
            )

            safety = require_ready_safety(app.config)
        except SafetyRuntimeUnavailable as exc:
            raise BracketOrderError(
                "Validated order safety configuration is unavailable; no order was sent"
            ) from exc

        selector = f"{principal.adapter_id}:{principal.account_id}"
        with safety.order_admission(selector) as lease:
            try:
                from flinttrade_core.l2_state import gather_safety_state  # noqa: PLC0415

                portfolio_state = _call_on_owner_loop(
                    gather_safety_state(
                        app.config,
                        principal.adapter_id,
                        account_id=principal.account_id,
                        orders=[order],
                        reservations=lease.reservations,
                        include_order_margin=True,
                    )
                )
                lease.reconcile(getattr(portfolio_state, "reconciled_reservation_ids", ()))
            except Exception as exc:  # noqa: BLE001 - refuse without exposing broker details
                logger.error("Bracket portfolio safety state is unavailable: %s", type(exc).__name__)
                raise BracketOrderError("Order safety state unavailable; no order was sent") from exc

            admission = portfolio_state.admission_for(0)
            results = safety.check_order(
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
            blocked = next((result for result in results if not result.passed), None)
            if blocked is not None:
                logger.warning(
                    "Bracket leg blocked by safety layer %s | symbol=%s: %s",
                    blocked.layer, order.symbol, blocked.reason,
                )
                raise BracketOrderError(
                    f"Order blocked by safety system [{blocked.layer}]: {blocked.reason}"
                )

            ctx = _request_ctx(principal)
            try:
                safety_ctx = gate_order(
                    order, ctx, adapter_id=principal.adapter_id, account_id=principal.account_id
                )
                reservation = lease.reserve(order, admission.positions)
                result = _call_on_owner_loop(
                    router.place_order(
                        ctx,
                        order=order,
                        safety_ctx=safety_ctx,
                        hint=RoutingHint(
                            adapter_id=principal.adapter_id, account_id=principal.account_id
                        ),
                    )
                )
                lease.acknowledge(reservation, result)
            except SafetyBypassError as exc:
                logger.warning("Bracket leg refused by safety gate: %s", exc)
                raise BracketOrderError("Order refused by the safety gate") from exc
            except AlgoTagLimitError as exc:
                logger.warning("Bracket leg refused by algo-tag guard: %s", exc)
                raise BracketOrderError("Order refused by rate guard — retry shortly") from exc
            except (BrokerNotFoundError, KeyError) as exc:
                logger.warning(
                    "Bracket leg — broker not connected | adapter=%s", principal.adapter_id
                )
                raise BracketOrderError(
                    f"Broker '{principal.adapter_id}' (account '{principal.account_id}') "
                    "is not connected."
                ) from exc
            except (NotImplementedError, UnsupportedCapabilityError) as exc:
                raise BracketOrderError(
                    f"Order placement is not yet available for broker '{principal.adapter_id}'."
                ) from exc
            except Exception as exc:
                logger.exception(
                    "Bracket leg dispatch failed | adapter=%s symbol=%s",
                    principal.adapter_id, order.symbol,
                )
                raise BracketOrderError("Order dispatch failed") from exc

        _audit("BRACKET_LEG_PLACED", principal, symbol=order.symbol, orderid=str(result))
        return str(result)

    def cancel_leg(order_id: str, principal: BracketPrincipal) -> None:
        """Cancel ONE bracket leg through the gated chain (one-shot gate + ACL).

        Raises:
            BracketOrderError: On any gate refusal, missing broker session,
                unsupported capability, or dispatch fault.
        """
        from flinttrade_core.exceptions import (  # noqa: PLC0415
            SafetyBypassError,
            UnsupportedCapabilityError,
        )
        from flinttrade_gateway.exceptions import BrokerNotFoundError  # noqa: PLC0415
        from flinttrade_gateway.routing_config import RoutingHint  # noqa: PLC0415

        from .safety import gate_order  # noqa: PLC0415

        router = _require_router()
        canonical: dict[str, Any] = {"_op": "cancel", "order_id": order_id}
        ctx = _request_ctx(principal)
        try:
            safety_ctx = gate_order(
                canonical, ctx, adapter_id=principal.adapter_id, account_id=principal.account_id
            )
            _call_on_owner_loop(
                router.cancel_order(
                    ctx,
                    order=canonical,
                    order_id=order_id,
                    safety_ctx=safety_ctx,
                    hint=RoutingHint(
                        adapter_id=principal.adapter_id, account_id=principal.account_id
                    ),
                )
            )
        except SafetyBypassError as exc:
            logger.warning("Bracket leg cancel refused by safety gate: %s", exc)
            raise BracketOrderError("Cancel refused by the safety gate") from exc
        except (BrokerNotFoundError, KeyError) as exc:
            raise BracketOrderError(
                f"Broker '{principal.adapter_id}' (account '{principal.account_id}') "
                "is not connected."
            ) from exc
        except (NotImplementedError, UnsupportedCapabilityError) as exc:
            raise BracketOrderError(
                f"Order cancellation is not yet available for broker '{principal.adapter_id}'."
            ) from exc
        except Exception as exc:
            logger.exception(
                "Bracket leg cancel dispatch failed | adapter=%s", principal.adapter_id
            )
            raise BracketOrderError("Order cancel failed") from exc

        _audit("BRACKET_LEG_CANCELLED", principal, orderid=order_id)

    return place_leg, cancel_leg
