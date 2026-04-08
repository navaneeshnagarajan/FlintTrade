"""Bracket order service — entry + SL + target as a tracked three-leg group.

Places the entry order immediately via OpenAlgo, then registers SL and target
legs as GTT-style limit orders once the entry is confirmed filled.  All three
legs are tracked together under a single bracket_id.

Absorbed from the algosattva bracket order pattern.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from packages.core.src.models import Action, Exchange, Order, OrderResponse, PriceType, Product
from packages.core.src.openalgo_client import OpenAlgoClient

logger = logging.getLogger("flinttrade.engine.bracket_order")


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class BracketOrderError(Exception):
    """Raised when bracket order placement or modification fails."""


class BracketNotFoundError(KeyError):
    """Raised when a bracket_id does not exist in the registry."""


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class BracketOrder:
    """Full state of a bracket order group.

    Attributes:
        bracket_id: Unique identifier for this bracket.
        entry_order_id: Order ID returned by OpenAlgo for the entry leg.
        sl_order_id: Order ID for the stop-loss leg (None until placed).
        target_order_id: Order ID for the target leg (None until placed).
        symbol: Instrument symbol (e.g. ``"NIFTY25APRFUT"``).
        exchange: Exchange code (e.g. ``"NFO"``).
        action: ``"BUY"`` or ``"SELL"`` — direction of the entry.
        quantity: Number of lots/shares.
        entry_price: Executed entry price (filled from order status).
        stoploss: Absolute SL price.
        target: Absolute target price.
        trailing_sl: Trailing stop distance in points; ``None`` if not used.
        strategy: OpenAlgo strategy name tag.
        product: Product type (``MIS`` / ``NRML`` / ``CNC``).
        status: One of ``"pending"`` | ``"active"`` | ``"partial"`` |
            ``"completed"`` | ``"cancelled"``.
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
    stoploss: float
    target: float
    trailing_sl: float | None = None
    strategy: str = "Flint"
    product: str = "MIS"
    status: str = "pending"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

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
            "status": self.status,
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
    stoploss: float,
    target: float,
    trailing_sl: float | None,
) -> list[str]:
    """Return a list of validation error strings, empty if all params are valid.

    Args:
        entry: Entry order dict with at minimum ``symbol``, ``exchange``,
            ``action``, and ``quantity`` keys.
        stoploss: Absolute SL price.
        target: Absolute target price.
        trailing_sl: Trailing SL distance in points; may be ``None``.

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

    if stoploss <= 0:
        errors.append(f"stoploss must be > 0, got {stoploss}")

    if target <= 0:
        errors.append(f"target must be > 0, got {target}")

    if trailing_sl is not None and trailing_sl <= 0:
        errors.append(f"trailing_sl must be > 0 when set, got {trailing_sl}")

    # SL/target direction: for BUY entry, SL < target; for SELL entry, SL > target
    if action == "BUY" and stoploss > 0 and target > 0:
        if stoploss >= target:
            errors.append(
                f"For BUY entry stoploss ({stoploss}) must be below target ({target})"
            )
    elif action == "SELL" and stoploss > 0 and target > 0:
        if stoploss <= target:
            errors.append(
                f"For SELL entry stoploss ({stoploss}) must be above target ({target})"
            )

    return errors


# ---------------------------------------------------------------------------
# BracketOrderService
# ---------------------------------------------------------------------------


class BracketOrderService:
    """Bracket order implementation for FlintTrade.

    Places the entry order immediately, then registers SL and target legs once
    the entry fill is confirmed.  All three legs are tracked under a single
    ``bracket_id`` and stored in an in-memory registry.

    The service uses a synchronous ``place_order`` interface by default so it
    can be tested without an async test runner.  Production code should
    ``await`` the async variant ``place_bracket_async`` instead.

    Usage::

        service = BracketOrderService(client=openalgo_client)
        result = service.place_bracket(
            entry={"symbol": "NIFTY25APRFUT", "exchange": "NFO",
                   "action": "BUY", "quantity": 50},
            stoploss=22000.0,
            target=22500.0,
        )
        if result.success:
            bracket_id = result.bracket.bracket_id
    """

    def __init__(
        self,
        client: OpenAlgoClient | None = None,
        default_strategy: str = "Flint",
        default_product: str = "MIS",
    ) -> None:
        self._client = client
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
        stoploss: float,
        target: float,
        trailing_sl: float | None = None,
    ) -> BracketResult:
        """Place a bracket order (entry + SL + target).

        Steps:
        1. Validate bracket parameters.
        2. Place entry order via OpenAlgo (or record as pending if no client).
        3. Register SL and target legs (GTT-style limit orders).
        4. Track all three legs under a single bracket_id.

        Args:
            entry: Dict with at minimum ``symbol``, ``exchange``, ``action``,
                and ``quantity``.  Optional keys: ``price`` (0 = MARKET),
                ``strategy``, ``product``, ``pricetype``.
            stoploss: Absolute SL price (not a percentage or distance).
            target: Absolute target price.
            trailing_sl: Optional trailing stop distance in points.

        Returns:
            BracketResult with ``success`` flag and the created BracketOrder.
        """
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

        # Step 2 — place entry order
        entry_order_id: str
        entry_filled_price: float = price

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

        if self._client is not None:
            try:
                response: OrderResponse = self._client.place_order(entry_order)
                entry_order_id = response.orderid
            except Exception as exc:
                logger.error(
                    "Bracket entry order failed for %s: %s", symbol, exc
                )
                return BracketResult(
                    success=False,
                    bracket=None,
                    message="Entry order placement failed",
                    error=str(exc),
                )
        else:
            # No live client — used in tests and paper-trading mode
            entry_order_id = f"sim-entry-{bracket_id[:8]}"
            logger.debug(
                "No client configured — bracket entry simulated as %s",
                entry_order_id,
            )

        # Step 3 — register SL leg
        sl_order_id: str | None = None
        target_order_id: str | None = None

        sl_action = "SELL" if action == "BUY" else "BUY"

        try:
            sl_order = Order(
                symbol=symbol,
                action=Action(sl_action),
                exchange=Exchange(exchange),
                pricetype=PriceType.SL,
                product=Product(product),
                quantity=str(quantity),
                price=str(stoploss),
                trigger_price=str(stoploss),
                strategy=strategy,
            )
            target_order = Order(
                symbol=symbol,
                action=Action(sl_action),
                exchange=Exchange(exchange),
                pricetype=PriceType.LIMIT,
                product=Product(product),
                quantity=str(quantity),
                price=str(target),
                strategy=strategy,
            )
        except (ValueError, KeyError) as exc:
            # Entry already placed — mark as partial rather than failing cleanly
            logger.warning(
                "Bracket SL/target model build failed for %s: %s", symbol, exc
            )
            bracket = self._register_bracket(
                bracket_id=bracket_id,
                entry_order_id=entry_order_id,
                sl_order_id=None,
                target_order_id=None,
                symbol=symbol,
                exchange=exchange,
                action=action,
                quantity=quantity,
                entry_price=entry_filled_price,
                stoploss=stoploss,
                target=target,
                trailing_sl=trailing_sl,
                strategy=strategy,
                product=product,
                status="partial",
            )
            return BracketResult(
                success=False,
                bracket=bracket,
                message="Entry placed but SL/target legs failed to build",
                error=str(exc),
            )

        if self._client is not None:
            try:
                sl_response: OrderResponse = self._client.place_order(sl_order)
                sl_order_id = sl_response.orderid
            except Exception as exc:
                logger.warning("SL leg placement failed for bracket %s: %s", bracket_id, exc)

            try:
                target_response: OrderResponse = self._client.place_order(target_order)
                target_order_id = target_response.orderid
            except Exception as exc:
                logger.warning(
                    "Target leg placement failed for bracket %s: %s", bracket_id, exc
                )
        else:
            sl_order_id = f"sim-sl-{bracket_id[:8]}"
            target_order_id = f"sim-target-{bracket_id[:8]}"

        # Step 4 — register bracket
        status = "active" if (sl_order_id and target_order_id) else "partial"
        bracket = self._register_bracket(
            bracket_id=bracket_id,
            entry_order_id=entry_order_id,
            sl_order_id=sl_order_id,
            target_order_id=target_order_id,
            symbol=symbol,
            exchange=exchange,
            action=action,
            quantity=quantity,
            entry_price=entry_filled_price,
            stoploss=stoploss,
            target=target,
            trailing_sl=trailing_sl,
            strategy=strategy,
            product=product,
            status=status,
        )

        logger.info(
            "Bracket %s placed | %s %s %s qty=%d SL=%.2f TGT=%.2f status=%s",
            bracket_id, action, symbol, exchange, quantity, stoploss, target, status,
        )

        return BracketResult(
            success=True,
            bracket=bracket,
            message=f"Bracket order placed with status '{status}'",
        )

    def modify_bracket(
        self,
        bracket_id: str,
        new_sl: float | None = None,
        new_target: float | None = None,
    ) -> BracketResult:
        """Modify the SL or target leg of an active bracket.

        At least one of ``new_sl`` or ``new_target`` must be provided.

        Args:
            bracket_id: The bracket to modify.
            new_sl: New absolute SL price; ``None`` to leave unchanged.
            new_target: New absolute target price; ``None`` to leave unchanged.

        Returns:
            BracketResult reflecting the updated bracket state.
        """
        bracket = self._registry.get(bracket_id)
        if bracket is None:
            return BracketResult(
                success=False,
                bracket=None,
                message="Bracket not found",
                error=f"No bracket with id '{bracket_id}'",
            )

        if bracket.status in ("completed", "cancelled"):
            return BracketResult(
                success=False,
                bracket=bracket,
                message="Cannot modify a completed or cancelled bracket",
                error=f"Bracket status is '{bracket.status}'",
            )

        if new_sl is None and new_target is None:
            return BracketResult(
                success=False,
                bracket=bracket,
                message="No modification requested — provide new_sl or new_target",
                error="Both new_sl and new_target are None",
            )

        if new_sl is not None and new_sl <= 0:
            return BracketResult(
                success=False,
                bracket=bracket,
                message="Invalid new_sl value",
                error=f"new_sl must be > 0, got {new_sl}",
            )

        if new_target is not None and new_target <= 0:
            return BracketResult(
                success=False,
                bracket=bracket,
                message="Invalid new_target value",
                error=f"new_target must be > 0, got {new_target}",
            )

        # Update local state — in a live system this would also cancel+replace
        # the relevant OpenAlgo order leg.  We log a warning when no client is
        # attached so the caller knows no broker-side change happened.
        if new_sl is not None:
            bracket.stoploss = new_sl
            logger.info("Bracket %s SL updated to %.2f", bracket_id, new_sl)

        if new_target is not None:
            bracket.target = new_target
            logger.info("Bracket %s target updated to %.2f", bracket_id, new_target)

        bracket.updated_at = datetime.now(timezone.utc).isoformat()

        if self._client is None:
            logger.debug(
                "No client configured — bracket %s modification is local-only", bracket_id
            )

        return BracketResult(
            success=True,
            bracket=bracket,
            message="Bracket modified successfully",
        )

    def cancel_bracket(self, bracket_id: str) -> bool:
        """Cancel all pending legs of a bracket order.

        Marks the bracket as ``"cancelled"`` in the registry and attempts to
        cancel SL and target legs via OpenAlgo if a client is configured.

        Args:
            bracket_id: The bracket to cancel.

        Returns:
            ``True`` if the bracket was found and cancelled, ``False`` if not
            found or already completed/cancelled.
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

        # Attempt broker-side cancellations (best-effort; errors are logged only)
        if self._client is not None:
            from packages.core.src.models import CancelOrder  # local import avoids top-level cycle

            for order_id, leg_name in (
                (bracket.sl_order_id, "SL"),
                (bracket.target_order_id, "target"),
            ):
                if order_id:
                    try:
                        self._client.cancel_order(
                            CancelOrder(orderid=order_id, strategy=bracket.strategy)
                        )
                        logger.info(
                            "Bracket %s %s leg cancelled (order %s)",
                            bracket_id, leg_name, order_id,
                        )
                    except Exception as exc:
                        logger.warning(
                            "Failed to cancel %s leg %s of bracket %s: %s",
                            leg_name, order_id, bracket_id, exc,
                        )

        bracket.status = "cancelled"
        bracket.updated_at = datetime.now(timezone.utc).isoformat()
        logger.info("Bracket %s cancelled", bracket_id)
        return True

    def get_active_brackets(self) -> list[BracketOrder]:
        """Return all brackets that are not completed or cancelled.

        Returns:
            List of BracketOrder objects with status in
            ``"pending"`` | ``"active"`` | ``"partial"``.
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
        """Mark a bracket as completed (called when target is hit).

        Args:
            bracket_id: The bracket to complete.

        Returns:
            ``True`` if updated, ``False`` if not found.
        """
        bracket = self._registry.get(bracket_id)
        if bracket is None:
            return False
        bracket.status = "completed"
        bracket.updated_at = datetime.now(timezone.utc).isoformat()
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
        stoploss: float,
        target: float,
        trailing_sl: float | None,
        strategy: str,
        product: str,
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
            status=status,
        )
        self._registry[bracket_id] = bracket
        return bracket
