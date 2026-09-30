"""Laya — typed decision and risk admission.

Laya allows, clamps, or refuses a proposal before SafetySystem runs. It does not place
an order, and it does not mint a write ticket. The only write ticket
remains the existing order gate. A full admit while Down refuses the proposal.
A server-proven reduce-only exit is recorded and is not refused or clamped.
There is no path that treats a chat model as a substitute verdict.

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
* Client ``orderGuards`` refuse Example, an unverified lot size, a lot
  multiple, and a missing limit or trigger price. They are a courtesy on
  the ticket. They are not the reason an order is safe.

Laya owns the typed allow or deny, the quantity ceiling (tighter while
Degraded), and the mode rule: Example is refused, and a Down engine refuses
Live and Practice proposals that are not a proven reduce-only exit. Chat is
suggest and explain only, so a chat source is refused here. Lot size, price
band, margin, Greeks, daily loss, and the kill switch stay outside this module.

When a decision host is configured, free-text questions run after the floor.
The host may deny or clamp. It cannot raise a quantity or overturn a floor
refusal. Unreachable, timeout, malformed, and a real revision or digest
mismatch are Down for Practice and Live. That refusal uses one sentence in
both modes. A decision that carries no revision or digest, and no record
from the running sidecar, refuses that order only. Live can also stay
closed while Laya is Ready or Degraded, until a qualification record matches
the pinned revision, weight digest, and policy version. That refusal names
the qualification requirement.
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

LAYA_DOWN_REASON = (
    "Laya is Down. New orders are paused until it's Ready. You can still close positions."
)


class DecisionStatus(StrEnum):
    """Operator-facing state of the decision engine."""

    READY = "ready"
    DEGRADED = "degraded"
    DOWN = "down"


LAYA_REASON_NOT_STARTED = "not_started"
LAYA_REASON_STOPPED = "stopped"
LAYA_REASON_PORT_IN_USE = "port_in_use"
LAYA_REASON_STILL_LOADING = "still_loading"
LAYA_REASON_DOWNLOADING = "downloading"
LAYA_REASON_DOWNLOAD_FAILED = "download_failed"
LAYA_REASON_UNREACHABLE = "unreachable"
LAYA_REASON_WRONG_REVISION = "wrong_revision"
LAYA_REASON_UNVERIFIED = "unverified"
LAYA_REASON_KEY_REJECTED = "key_rejected"
LAYA_REASON_KEY_MISSING = "key_missing"
LAYA_REASON_CODES = frozenset(
    {
        LAYA_REASON_NOT_STARTED,
        LAYA_REASON_STOPPED,
        LAYA_REASON_PORT_IN_USE,
        LAYA_REASON_STILL_LOADING,
        LAYA_REASON_DOWNLOADING,
        LAYA_REASON_DOWNLOAD_FAILED,
        LAYA_REASON_UNREACHABLE,
        LAYA_REASON_WRONG_REVISION,
        LAYA_REASON_UNVERIFIED,
        LAYA_REASON_KEY_REJECTED,
        LAYA_REASON_KEY_MISSING,
    }
)

LAYA_START_COMMAND = "python -m flinttrade_core.laya_runtime start"
LAYA_DOWNLOAD_FAILED_DETAIL = "Can't download the model"
LAYA_DOWNLOAD_FAILED_TOOLTIP = "Check your connection, then Start Laya again."
# Decimal gigabytes, so 1_200_000_000 of 3_400_000_000 reads "1.2 of 3.4 GB".
_DECIMAL_GB = 1_000_000_000

_REASON_TOOLTIPS = {
    LAYA_REASON_UNVERIFIED: (
        "The installed model couldn't be checked against the pinned version. "
        "Restart Laya. If it keeps happening, reinstall it."
    ),
    LAYA_REASON_WRONG_REVISION: "Laya is running a different model than FlintTrade expects.",
    LAYA_REASON_KEY_REJECTED: "Laya restarted with a new key. Reconnecting…",
    LAYA_REASON_KEY_MISSING: "The Laya API key file is missing.",
    LAYA_REASON_DOWNLOAD_FAILED: LAYA_DOWNLOAD_FAILED_TOOLTIP,
}


def format_download_progress(done_bytes: int, total_bytes: int) -> str:
    """Live download line. One decimal place, decimal gigabytes.

    ``Downloading the model · 1.2 of 3.4 GB``
    """
    done = done_bytes / _DECIMAL_GB
    total = total_bytes / _DECIMAL_GB
    return f"Downloading the model · {done:.1f} of {total:.1f} GB"


def laya_reason_detail(
    reason: str | None,
    port: int,
    *,
    progress: tuple[int, int] | None = None,
) -> str | None:
    """Plain words for a sidecar reason code. ``None`` when the sidecar is up."""
    if reason == LAYA_REASON_PORT_IN_USE:
        return f"Port {port} in use"
    if reason == LAYA_REASON_DOWNLOADING:
        done, total = progress if progress is not None else (0, 0)
        return format_download_progress(done, total)
    labels = {
        LAYA_REASON_NOT_STARTED: "Not started",
        LAYA_REASON_STOPPED: "Stopped",
        LAYA_REASON_STILL_LOADING: "Still loading",
        LAYA_REASON_DOWNLOAD_FAILED: LAYA_DOWNLOAD_FAILED_DETAIL,
        LAYA_REASON_UNREACHABLE: "Unreachable",
        LAYA_REASON_WRONG_REVISION: "Wrong model version",
        LAYA_REASON_UNVERIFIED: "Can't verify the model",
        LAYA_REASON_KEY_REJECTED: "Can't reach Laya",
        LAYA_REASON_KEY_MISSING: "The Laya API key file is missing.",
    }
    if reason is None:
        return None
    return labels.get(reason)


def laya_reason_tooltip(
    reason: str | None,
    port: int,
    *,
    progress: tuple[int, int] | None = None,
) -> str | None:
    """Hover text for a sidecar reason. ``None`` when the sidecar is up.

    ``downloading`` has no tooltip and no Next line. The popover is the
    progress sentence itself.
    """
    if reason == LAYA_REASON_DOWNLOADING:
        return None
    if reason in _REASON_TOOLTIPS:
        return _REASON_TOOLTIPS[reason]
    detail = laya_reason_detail(reason, port, progress=progress)
    if detail is None:
        return None
    return f"{detail}. Next: {LAYA_START_COMMAND}"


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
        rationale: Free text supplied with the place. Empty when the caller
            sent none. The host is not asked for facts the floor already knows.
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
    rationale: str = ""


@dataclass(frozen=True, slots=True)
class VerdictLimits:
    """Sizing bound that applied to this verdict."""

    max_quantity: int


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    """One row in the decision log.

    Attributes:
        proof_kind: ``admit`` for a full admit, ``reduce_only`` for a proven exit.
        symbol: Instrument symbol.
        exchange: Exchange code.
        action: BUY or SELL.
        quantity: Quantity the caller asked for.
        applied_quantity: Quantity the verdict accepted.
        status: Decision status at the time of the record.
        allow: Whether the verdict let the quantity continue.
    """

    proof_kind: str
    symbol: str
    exchange: str
    action: str
    quantity: int
    applied_quantity: int
    status: str
    allow: bool


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
        tightened: True when an uncertain host answer holds the quantity even
            if the number did not shrink. Ceiling clamps leave this false.
        evidence: Log tokens from the host step. Empty when that step did not run.
    """

    allow: bool
    reason: str
    limits: VerdictLimits
    applied_quantity: int
    tightened: bool = False
    evidence: tuple[tuple[str, str], ...] = ()


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
        self._live_qualified = status is not DecisionStatus.DOWN
        self._reason: str | None = LAYA_REASON_NOT_STARTED if status is DecisionStatus.DOWN else None
        self._reason_port = 8000
        self._sticky_refusal = False
        self._download_progress: tuple[int, int] | None = None
        self._decision_client: Any = None
        self._qualification: Any = None
        self._gate_checking = False
        self._lock = threading.Lock()
        self._log: list[DecisionRecord] = []
        self._log_lock = threading.Lock()

    @property
    def status(self) -> DecisionStatus:
        """Current runtime status, before the Live qualification rule."""
        with self._lock:
            return self._status

    @property
    def qualification(self) -> Any:
        """Qualification record used by the health probe, if one was recorded."""
        with self._lock:
            return self._qualification

    def set_status(self, status: DecisionStatus) -> None:
        """Record Ready, Degraded, or Down.

        An explicit Ready or Degraded opens Live as well as Practice. The
        health probe uses :meth:`apply_runtime_status`, which keeps Live
        Down until a qualification record exists.
        """
        with self._lock:
            self._status = status
            self._live_qualified = status is not DecisionStatus.DOWN
            if status is not DecisionStatus.DOWN:
                self._reason = None
                self._sticky_refusal = False
                self._download_progress = None

    def apply_runtime_status(self, status: DecisionStatus, *, live_qualified: bool) -> None:
        """Record a probe result. Live opens only when ``live_qualified`` is set.

        Down does not invent an operational reason. The sidecar probe sets
        that separately. Ready and Degraded clear it.
        """
        with self._lock:
            self._status = status
            self._live_qualified = bool(live_qualified) and status is not DecisionStatus.DOWN
            if status is not DecisionStatus.DOWN:
                self._reason = None
                self._sticky_refusal = False
                self._download_progress = None

    def set_runtime_reason(
        self,
        reason: str | None,
        port: int,
        *,
        progress: tuple[int, int] | None = None,
        sticky: bool = False,
    ) -> None:
        """Record why the sidecar is Down, and the port that status checked.

        ``progress`` is ``(done_bytes, total_bytes)`` while ``reason`` is
        ``downloading``. Any other reason clears it. ``sticky`` keeps a
        refused start in place until the next start or an explicit clear.
        A health check must not replace that reason with ``not_started``.
        """
        if reason is not None and reason not in LAYA_REASON_CODES:
            raise ValueError("Laya reason is not recognised")
        if not 1 <= port <= 65535:
            raise ValueError("Laya sidecar port is invalid")
        if progress is not None and (
            len(progress) != 2 or isinstance(progress[0], bool) or isinstance(progress[1], bool)
        ):
            raise ValueError("Laya download progress is invalid")
        if progress is not None and (
            not isinstance(progress[0], int) or not isinstance(progress[1], int) or progress[0] < 0 or progress[1] < 0
        ):
            raise ValueError("Laya download progress is invalid")
        with self._lock:
            self._reason = reason
            self._reason_port = port
            self._sticky_refusal = bool(sticky) and reason is not None
            if reason != LAYA_REASON_DOWNLOADING:
                self._download_progress = None
            elif progress is not None:
                self._download_progress = (progress[0], progress[1])

    def refusal_is_sticky(self) -> bool:
        """True when a refused start must survive the next health check."""
        with self._lock:
            return self._sticky_refusal

    def clear_sticky_refusal(self) -> None:
        """Drop a sticky refusal so the next start or an explicit clear can move on."""
        with self._lock:
            self._sticky_refusal = False

    def runtime_reason(self) -> tuple[str | None, int]:
        """Reason code and port. ``None`` when Ready or Degraded has cleared it."""
        with self._lock:
            return self._reason, self._reason_port

    def download_progress(self) -> tuple[int, int] | None:
        """Bytes done and bytes expected while a download is in progress."""
        with self._lock:
            return self._download_progress

    def set_gate_checking(self, checking: bool) -> None:
        """Record the unconfirmed Checking window. The sidecar leaves this false."""
        with self._lock:
            self._gate_checking = bool(checking)

    def gate_checking(self) -> bool:
        """True while an Ollama start is unconfirmed. False on the sidecar path."""
        with self._lock:
            return self._gate_checking

    def set_decision_client(self, client: Any) -> None:
        """Attach the host used for free-text questions. ``None`` skips that step."""
        with self._lock:
            self._decision_client = client

    def set_qualification(self, record: Any) -> None:
        """Record the Live qualification evidence, or clear it with ``None``."""
        if record is not None:
            from .laya_decision import LayaQualification  # noqa: PLC0415

            if type(record) is not LayaQualification:
                raise TypeError("qualification record is not recognised")
        with self._lock:
            self._qualification = record

    def effective_status(self, mode: str) -> DecisionStatus:
        """Status that applies to ``mode``. Unqualified Live stays Down."""
        with self._lock:
            if self._status is DecisionStatus.DOWN:
                return DecisionStatus.DOWN
            if mode.strip().lower() == "live" and not self._live_qualified:
                return DecisionStatus.DOWN
            return self._status

    def note_heartbeat(self) -> DecisionStatus:
        """Return the Live-facing status a desk heartbeat should publish.

        A heartbeat does not invent Ready. Unqualified Live stays Down.
        """
        return self.effective_status("live")

    def desk_heartbeat(self) -> tuple[DecisionStatus, DecisionStatus, bool]:
        """Practice status, Live-facing status, and whether Live is qualified.

        Practice follows the sidecar. Live is Down when the sidecar is Down
        or when no qualification record covers the pin.
        """
        with self._lock:
            runtime = self._status
            qualified = bool(self._live_qualified) and runtime is not DecisionStatus.DOWN
        live = runtime if qualified else DecisionStatus.DOWN
        return runtime, live, qualified

    def decision_log(self) -> tuple[DecisionRecord, ...]:
        """Return the decision log, oldest first."""
        with self._log_lock:
            return tuple(self._log)

    def admit_reduce_only(self, proposal: Proposal) -> Verdict:
        """Record a server-proven reduce-only exit.

        Down, Degraded, and an unheard status cannot refuse or clamp this
        verdict. The place pipeline decides the proof. This method does not
        read a client flag, and it does not place the order.
        """
        limits = VerdictLimits(max_quantity=max(proposal.quantity, self._active_ceiling()))
        verdict = Verdict(
            allow=True,
            reason="",
            limits=limits,
            applied_quantity=proposal.quantity,
        )
        self._record("reduce_only", proposal, verdict)
        return verdict

    def admit(self, proposal: Proposal) -> Verdict:
        """Return a verdict for ``proposal``.

        Order: Down, then the deterministic floor, then free-text questions
        when a host is configured. Down refuses before any other rule. A
        floor refusal is final. The host cannot raise a quantity. A proven
        reduce-only exit uses :meth:`admit_reduce_only` instead.
        """
        from .laya_ollama import laya_backend  # noqa: PLC0415

        if laya_backend() != "sidecar":
            return self._admit_ollama_backend(proposal)
        self._watch_sidecar()
        status = self.effective_status(proposal.mode)
        with self._lock:
            client = self._decision_client
            ceiling = self._ceiling_for(status)
        limits = VerdictLimits(max_quantity=ceiling)
        if status is DecisionStatus.DOWN:
            return self._down_verdict(limits)

        reason = self._schema_reason(proposal)
        if reason:
            return Verdict(allow=False, reason=reason, limits=limits, applied_quantity=0)
        if client is None:
            return self._ceiling_verdict(proposal, limits)
        from .laya_decision import evaluate_free_text  # noqa: PLC0415

        decision = evaluate_free_text(
            mode=proposal.mode,
            action=proposal.action,
            rationale=proposal.rationale,
            requested_quantity=proposal.quantity,
            degraded_ceiling=self._degraded_max_quantity,
            client=client,
        )
        if decision.effect == "unverified":
            return Verdict(
                allow=False,
                reason=decision.reason,
                limits=limits,
                applied_quantity=0,
                evidence=decision.evidence,
            )
        if decision.effect == "down":
            self.set_status(DecisionStatus.DOWN)
            failure = next((item[1] for item in decision.evidence if item[0] == "failure"), "")
            chip_reason = _reason_for_decision_failure(failure)
            if chip_reason is not None:
                self.set_runtime_reason(chip_reason, self.runtime_reason()[1])
            verdict = self._down_verdict(VerdictLimits(max_quantity=self._ceiling_for(DecisionStatus.DOWN)))
            return Verdict(
                allow=verdict.allow,
                reason=verdict.reason,
                limits=verdict.limits,
                applied_quantity=0,
                evidence=decision.evidence,
            )
        if decision.effect == "deny":
            return Verdict(
                allow=False,
                reason=decision.reason,
                limits=limits,
                applied_quantity=0,
                evidence=decision.evidence,
            )
        if decision.effect == "clamp":
            applied = min(decision.applied_quantity, limits.max_quantity, proposal.quantity)
            return Verdict(
                allow=True,
                reason=decision.reason,
                limits=limits,
                applied_quantity=applied,
                tightened=True,
                evidence=decision.evidence,
            )
        return self._ceiling_verdict(proposal, limits, evidence=decision.evidence)

    def _admit_ollama_backend(self, proposal: Proposal) -> Verdict:
        """Score free text with the Ollama client. A missing client does not admit.

        The sidecar watch is not run. Closing a position still uses
        :meth:`admit_reduce_only`, which does not call this method.
        """
        from .laya_ollama import bind_ollama_gate  # noqa: PLC0415

        client = bind_ollama_gate(self)
        status = self.effective_status(proposal.mode)
        with self._lock:
            ceiling = self._ceiling_for(status)
        limits = VerdictLimits(max_quantity=ceiling)
        if client is None or status is DecisionStatus.DOWN:
            if status is not DecisionStatus.DOWN:
                self.apply_runtime_status(DecisionStatus.DOWN, live_qualified=False)
            return self._down_verdict(VerdictLimits(max_quantity=self._ceiling_for(DecisionStatus.DOWN)))
        reason = self._schema_reason(proposal)
        if reason:
            return Verdict(allow=False, reason=reason, limits=limits, applied_quantity=0)
        from .laya_decision import evaluate_free_text  # noqa: PLC0415

        decision = evaluate_free_text(
            mode=proposal.mode,
            action=proposal.action,
            rationale=proposal.rationale,
            requested_quantity=proposal.quantity,
            degraded_ceiling=self._degraded_max_quantity,
            client=client,
        )
        if decision.effect == "unverified":
            return Verdict(
                allow=False,
                reason=decision.reason,
                limits=limits,
                applied_quantity=0,
                evidence=decision.evidence,
            )
        if decision.effect == "down":
            self.set_status(DecisionStatus.DOWN)
            failure = next((item[1] for item in decision.evidence if item[0] == "failure"), "")
            chip_reason = _reason_for_decision_failure(failure)
            if chip_reason is not None:
                self.set_runtime_reason(chip_reason, self.runtime_reason()[1])
            verdict = self._down_verdict(VerdictLimits(max_quantity=self._ceiling_for(DecisionStatus.DOWN)))
            return Verdict(
                allow=verdict.allow,
                reason=verdict.reason,
                limits=verdict.limits,
                applied_quantity=0,
                evidence=decision.evidence,
            )
        if decision.effect == "deny":
            return Verdict(
                allow=False,
                reason=decision.reason,
                limits=limits,
                applied_quantity=0,
                evidence=decision.evidence,
            )
        if decision.effect == "clamp":
            applied = min(decision.applied_quantity, limits.max_quantity, proposal.quantity)
            return Verdict(
                allow=True,
                reason=decision.reason,
                limits=limits,
                applied_quantity=applied,
                tightened=True,
                evidence=decision.evidence,
            )
        return self._ceiling_verdict(proposal, limits, evidence=decision.evidence)

    def _down_verdict(self, limits: VerdictLimits) -> Verdict:
        with self._lock:
            runtime = self._status
        if runtime is DecisionStatus.DOWN:
            reason = _DOWN_PAUSE
        else:
            reason = _UNQUALIFIED_LIVE
        return Verdict(
            allow=False,
            reason=reason,
            limits=limits,
            applied_quantity=0,
        )

    def _ceiling_verdict(
        self,
        proposal: Proposal,
        limits: VerdictLimits,
        *,
        evidence: tuple[tuple[str, str], ...] = (),
    ) -> Verdict:
        if proposal.quantity > limits.max_quantity:
            return Verdict(
                allow=True,
                reason="",
                limits=limits,
                applied_quantity=limits.max_quantity,
                evidence=evidence,
            )
        return Verdict(
            allow=True,
            reason="",
            limits=limits,
            applied_quantity=proposal.quantity,
            evidence=evidence,
        )

    @staticmethod
    def _watch_sidecar() -> None:
        """Re-read the pid, key, and runtime record before this admission."""
        try:
            from flinttrade_core.laya_runtime import process_runtime  # noqa: PLC0415
        except ImportError:
            return
        runtime = process_runtime()
        reconcile = getattr(runtime, "reconcile_watched_state", None)
        if callable(reconcile):
            reconcile()

    def _ceiling_for(self, status: DecisionStatus) -> int:
        if status is DecisionStatus.DEGRADED:
            return self._degraded_max_quantity
        return self._max_quantity

    def _record(self, proof_kind: str, proposal: Proposal, verdict: Verdict) -> None:
        record = DecisionRecord(
            proof_kind=proof_kind,
            symbol=proposal.symbol,
            exchange=proposal.exchange,
            action=proposal.action,
            quantity=proposal.quantity,
            applied_quantity=verdict.applied_quantity,
            status=self._status.value,
            allow=verdict.allow,
        )
        with self._log_lock:
            self._log.append(record)

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
            return "Example cannot place orders."
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


_DOWN_PAUSE = "Laya is Down. New orders are paused until it's Ready. You can still close positions."

LAYA_DECISION_UNVERIFIED = "Not placed. Laya's decision couldn't be verified. Try again."


_UNQUALIFIED_LIVE = "Laya isn't qualified for Live yet. Practice orders are available."


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
        rationale=str(fields.get("rationale") or fields.get("note") or ""),
    )


def admission_kind(verdict: Verdict, requested_quantity: int) -> str:
    """Classify a verdict against the quantity the caller asked to place.

    Returns:
        ``allow`` when that quantity may continue to SafetySystem.
        ``clamp`` when the requested quantity is above the allowed quantity.
        Nothing is placed. A request that is already at that quantity is an allow,
        including when an uncertain note tightened the ceiling.
        ``deny`` when nothing may continue.
    """
    if not verdict.allow:
        return "deny"
    if requested_quantity > verdict.applied_quantity:
        return "clamp"
    return "allow"


def _reason_for_decision_failure(code: str) -> str | None:
    """Map a host failure onto a chip reason in the same request.

    A connect error or a timeout is ``unreachable``. A 401 or 403 from the
    sidecar is ``key_rejected`` (chip "Can't reach Laya"). Other failures
    stay with the probe.
    """
    if code in {"revision_mismatch", "digest_mismatch"}:
        return LAYA_REASON_WRONG_REVISION
    if code in {"digest_absent", "runtime_too_old", "unverified"}:
        return LAYA_REASON_UNVERIFIED
    if code == "model_missing":
        return LAYA_REASON_DOWNLOADING
    if code == "runtime_down":
        return LAYA_REASON_NOT_STARTED
    if code in {"http_401", "http_403"}:
        return LAYA_REASON_KEY_REJECTED
    if code in {"connection", "timeout"}:
        return LAYA_REASON_UNREACHABLE
    return None


def clamp_place_message(applied_quantity: int) -> str:
    """Desk sentence for a clamp. Nothing has been placed."""
    return f"Not placed. Laya allows up to {applied_quantity}."


def place_block(verdict: Verdict, requested_quantity: int) -> dict[str, Any] | None:
    """Return a desk refusal body, or ``None`` when the place may continue.

    Clamp and deny both stop before SafetySystem. The message is the server
    text the desk shows. ``http_status`` is for the HTTP entry only. A Down
    pause does not include a quantity ceiling: nothing is being sized.
    """
    kind = admission_kind(verdict, requested_quantity)
    if kind == "allow":
        return None
    limits = {"max_quantity": verdict.limits.max_quantity}
    if kind == "clamp":
        return {
            "status": "error",
            "code": "laya_clamp",
            "message": clamp_place_message(verdict.applied_quantity),
            "reason": verdict.reason,
            "limits": limits,
            "applied_quantity": verdict.applied_quantity,
            "http_status": 409,
        }
    if verdict.reason == LAYA_DECISION_UNVERIFIED:
        return {
            "status": "error",
            "code": "laya_unverified",
            "message": LAYA_DECISION_UNVERIFIED,
            "reason": LAYA_DECISION_UNVERIFIED,
            "http_status": 409,
        }
    body: dict[str, Any] = {
        "status": "error",
        "code": "laya_denied",
        "message": verdict.reason,
        "reason": verdict.reason,
        "http_status": 403,
    }
    if verdict.reason != _DOWN_PAUSE:
        body["limits"] = limits
    return body


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
    """Process-wide Laya. Down until a probe or :meth:`Laya.set_status` says otherwise."""
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
    from flinttrade_core.laya_runtime import reset_process_runtime_for_tests  # noqa: PLC0415

    reset_process_runtime_for_tests()
