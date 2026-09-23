"""Laya — typed decision and risk admission.

Laya allows, clamps, or refuses a proposal before SafetySystem runs. It does not place
an order, and it does not mint a write ticket. The only write ticket
remains the existing order gate. A Down status refuses every proposal:
there is no path that treats a chat model as a substitute verdict.

A quantity above the active ceiling is a clamp: the verdict names the smaller
quantity and does not authorise the original size. The caller must show that
reduction before any later place. It must not send the reduced size on its own.

Overlap — what already exists, and what this admission still leaves open:

* Automate ``RiskAssessment`` carries ``allowed``, ``reason``,
  ``position_qty``, ``stop_loss``, and ``take_profit``. Those fields are a
  model note. They are not an admission verdict and they do not size the book.
* SafetySystem L1 checks the order fields and the price band. L2 checks
  position and margin limits. L3 checks portfolio Greeks. L4 checks daily
  loss. L5 is the kill switch. Laya does not replace any of those layers.
* Client ``orderGuards`` refuse Explore, an unverified lot size, a lot
  multiple, and a missing limit or trigger price. They are a courtesy on
  the ticket. They are not the reason an order is safe.

Laya owns the typed allow or deny, the quantity ceiling (tighter while
Degraded), and the mode rule: Explore is refused, and a Down engine refuses
Live and Practice proposals. Chat is suggest and explain only, so a chat
source is refused here. Lot size, price band, margin, Greeks, daily loss,
and the kill switch stay outside this module.
"""

from __future__ import annotations

import math
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

_ACTIONS = frozenset({"BUY", "SELL"})
_MODES = frozenset({"explore", "practice", "live"})
_ORDER_TYPES = frozenset({"MARKET", "LIMIT", "SL", "SL-M"})
_PRODUCTS = frozenset({"MIS", "CNC", "NRML"})
_PRICE_REQUIRED = frozenset({"LIMIT", "SL"})
_TRIGGER_REQUIRED = frozenset({"SL", "SL-M"})
_ADMITTED_SOURCES = frozenset({"operator", "automate"})


class DecisionStatus(StrEnum):
    """Operator-facing state of the decision engine."""

    READY = "ready"
    DEGRADED = "degraded"
    DOWN = "down"


@dataclass(frozen=True, slots=True)
class Proposal:
    """One order the operator or an automate flow wants admitted.

    Attributes:
        symbol: Instrument symbol.
        exchange: Exchange code.
        action: BUY or SELL.
        quantity: Whole quantity asked for.
        mode: explore, practice, or live.
        order_type: MARKET, LIMIT, SL, or SL-M.
        product: MIS, CNC, or NRML.
        price: Limit price when the order type needs one.
        trigger_price: Trigger price when the order type needs one.
        source: ``operator`` or ``automate``. Chat is not an admission source.
    """

    symbol: str
    exchange: str
    action: str
    quantity: int
    mode: str
    order_type: str = "MARKET"
    product: str = "MIS"
    price: float | None = None
    trigger_price: float | None = None
    source: str = "operator"


@dataclass(frozen=True, slots=True)
class VerdictLimits:
    """Sizing bound that applied to this verdict."""

    max_quantity: int


@dataclass(frozen=True, slots=True)
class Verdict:
    """Admission result. ``allow`` is the only proceed signal.

    Attributes:
        allow: True when some quantity may continue to SafetySystem.
        reason: Empty when allowed or clamped. A refusal the operator can read otherwise.
        limits: Quantity ceiling in force for this status.
        applied_quantity: Quantity this verdict will accept. ``0`` on a refusal.
            Smaller than the request on a clamp. The caller must not place a
            clamp until the operator has seen the reduced quantity.
    """

    allow: bool
    reason: str
    limits: VerdictLimits
    applied_quantity: int


class Laya:
    """Admit or refuse a proposal. Never places.

    Args:
        status: Ready, Degraded, or Down. Required. There is no Ready default.
        max_quantity: Ceiling while Ready.
        degraded_max_quantity: Tighter ceiling while Degraded.
    """

    def __init__(
        self,
        *,
        status: DecisionStatus,
        max_quantity: int = 100,
        degraded_max_quantity: int = 1,
    ) -> None:
        if max_quantity < 1 or degraded_max_quantity < 1:
            raise ValueError("quantity bounds must be positive")
        if degraded_max_quantity > max_quantity:
            raise ValueError("degraded bound cannot exceed the ready bound")
        self._status = status
        self._max_quantity = max_quantity
        self._degraded_max_quantity = degraded_max_quantity

    @property
    def status(self) -> DecisionStatus:
        """Current decision status."""
        return self._status

    def set_status(self, status: DecisionStatus) -> None:
        """Record Ready, Degraded, or Down. This is authoritative."""
        self._status = status

    def note_heartbeat(self) -> DecisionStatus:
        """Return the status a desk heartbeat should publish.

        A heartbeat does not invent Ready. Down stays Down until
        :meth:`set_status` says otherwise.
        """
        return self._status

    def admit(self, proposal: Proposal) -> Verdict:
        """Return a verdict for ``proposal``.

        Down refuses before any other rule, so a chat model cannot fill in
        for a missing decision. Other refusals are schema, source, or mode.
        A quantity above the ceiling is a clamp, not a place.
        """
        limits = VerdictLimits(max_quantity=self._active_ceiling())
        if self._status is DecisionStatus.DOWN:
            return Verdict(
                allow=False,
                reason="Laya is Down. Live orders are blocked.",
                limits=limits,
                applied_quantity=0,
            )

        reason = self._schema_reason(proposal)
        if reason:
            return Verdict(allow=False, reason=reason, limits=limits, applied_quantity=0)
        if proposal.quantity > limits.max_quantity:
            return Verdict(
                allow=True,
                reason="",
                limits=limits,
                applied_quantity=limits.max_quantity,
            )
        return Verdict(
            allow=True,
            reason="",
            limits=limits,
            applied_quantity=proposal.quantity,
        )

    def _active_ceiling(self) -> int:
        if self._status is DecisionStatus.DEGRADED:
            return self._degraded_max_quantity
        return self._max_quantity

    @staticmethod
    def _schema_reason(proposal: Proposal) -> str:
        source = proposal.source.strip().lower()
        if source not in _ADMITTED_SOURCES:
            return "Chat can suggest and explain. It cannot admit an order."
        mode = proposal.mode.strip().lower()
        if mode not in _MODES:
            return "Mode is not recognised. Nothing was admitted."
        if mode == "explore":
            return "Explore cannot place orders."
        if not proposal.symbol.strip() or not proposal.exchange.strip():
            return "Symbol and exchange are required."
        action = proposal.action.strip().upper()
        if action not in _ACTIONS:
            return "Action must be BUY or SELL."
        order_type = proposal.order_type.strip().upper()
        if order_type not in _ORDER_TYPES:
            return "Order type is not recognised."
        product = proposal.product.strip().upper()
        if product not in _PRODUCTS:
            return "Product must be MIS, CNC, or NRML."
        if isinstance(proposal.quantity, bool) or not isinstance(proposal.quantity, int) or proposal.quantity < 1:
            return "Quantity must be a positive whole number."
        if order_type in _PRICE_REQUIRED and (proposal.price is None or proposal.price <= 0):
            return "Enter a price above zero before this order can be admitted."
        if order_type in _TRIGGER_REQUIRED and (
            proposal.trigger_price is None or proposal.trigger_price <= 0
        ):
            return "Enter a trigger price above zero before this order can be admitted."
        return ""


def proposal_from_place_fields(
    fields: Mapping[str, Any],
    *,
    mode: str,
    source: str,
) -> Proposal:
    """Build a proposal from place fields.

    ``source`` is chosen by the server entry. A client field named ``source``
    is ignored, so a request cannot present itself as chat or as automate.
    """
    quantity = _whole_quantity(fields.get("quantity"))
    order_type = str(fields.get("order_type") or fields.get("pricetype") or "MARKET")
    return Proposal(
        symbol=str(fields.get("symbol") or ""),
        exchange=str(fields.get("exchange") or ""),
        action=str(fields.get("action") or ""),
        quantity=quantity if quantity is not None else 0,
        mode=mode,
        order_type=order_type,
        product=str(fields.get("product") or "MIS"),
        price=_positive_price(fields.get("price")),
        trigger_price=_positive_price(fields.get("trigger_price")),
        source=source,
    )


def admission_kind(verdict: Verdict, requested_quantity: int) -> str:
    """Classify a verdict against the quantity the caller asked to place.

    Returns:
        ``allow`` when that quantity may continue to SafetySystem.
        ``clamp`` when only a smaller quantity is acceptable. Nothing is placed.
        ``deny`` when nothing may continue.
    """
    if not verdict.allow:
        return "deny"
    if verdict.applied_quantity != requested_quantity:
        return "clamp"
    return "allow"


def place_block(verdict: Verdict, requested_quantity: int) -> dict[str, Any] | None:
    """Return a desk refusal body, or ``None`` when the place may continue.

    Clamp and deny both stop before SafetySystem. The message is the server
    text the desk shows. ``http_status`` is for the HTTP entry only.
    """
    kind = admission_kind(verdict, requested_quantity)
    if kind == "allow":
        return None
    limits = {"max_quantity": verdict.limits.max_quantity}
    if kind == "clamp":
        return {
            "status": "error",
            "code": "laya_clamp",
            "message": f"Qty reduced to {verdict.applied_quantity} (Laya limit)",
            "reason": "",
            "limits": limits,
            "applied_quantity": verdict.applied_quantity,
            "http_status": 409,
        }
    return {
        "status": "error",
        "code": "laya_denied",
        "message": verdict.reason,
        "reason": verdict.reason,
        "limits": limits,
        "http_status": 403,
    }


def _whole_quantity(raw: object) -> int | None:
    if isinstance(raw, bool) or raw is None:
        return None
    if isinstance(raw, int):
        return raw if raw >= 1 else None
    if isinstance(raw, float):
        if not math.isfinite(raw) or not raw.is_integer():
            return None
        whole = int(raw)
        return whole if whole >= 1 else None
    if isinstance(raw, str):
        text = raw.strip()
        if not text.isdigit():
            return None
        whole = int(text)
        return whole if whole >= 1 else None
    return None


def _positive_price(raw: object) -> float | None:
    if isinstance(raw, bool) or raw is None:
        return None
    if isinstance(raw, (int, float)):
        value = float(raw)
    elif isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        try:
            value = float(text)
        except ValueError:
            return None
    else:
        return None
    if not math.isfinite(value) or value <= 0:
        return None
    return value


_process_lock = threading.Lock()
_process_laya: Laya | None = None


def process_laya() -> Laya:
    """Process-wide Laya. Down until :meth:`Laya.set_status` says otherwise."""
    global _process_laya
    with _process_lock:
        if _process_laya is None:
            _process_laya = Laya(status=DecisionStatus.DOWN)
        return _process_laya


def reset_process_laya_for_tests() -> None:
    """Drop the process-wide Laya so the next call starts unheard."""
    global _process_laya
    with _process_lock:
        _process_laya = None
