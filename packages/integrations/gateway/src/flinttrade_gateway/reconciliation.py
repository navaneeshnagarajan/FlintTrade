"""Reconciliation report model + pure diff helpers (contract §14, parent §11.6).

Every native broker adapter implements ``reconcile(session)`` returning a
:class:`ReconciliationReport` — the broker-side truth (order book / positions /
holdings fetched through the adapter's own reads) diffed against the
flinttrade-side mirror (a :class:`LocalStateSnapshot` supplied by an injectable
``local_state_provider`` on the adapter; the engine runner wires the durable
workspace provider without changing the adapter contract).

The diff itself (:func:`build_report` and the ``diff_*`` helpers) is PURE and
deterministic: given the same snapshots it always produces the same report,
with diffs ordered by their natural key. Broker order evidence must carry the
complete lifecycle schema (identity, status, instrument, side, quantities,
prices, order type, variety, validity, strategy, and average fill price).
Adapters may explicitly mark only broker-unavailable text attributes as
``UNKNOWN``; missing numeric evidence always fails closed.

Severity policy (deterministic, documented here once):

================  ===========================  ==========
surface           discrepancy                  severity
================  ===========================  ==========
orders            exists_only_on_broker        warning
orders            exists_only_in_flinttrade    critical
orders            status_mismatch              warning
orders            qty_mismatch                 warning
positions         exists_only_on_broker        critical
positions         exists_only_in_flinttrade    critical
positions         qty_mismatch                 critical
holdings          any                          warning
================  ===========================  ==========

Rationale: a position discrepancy is live, unhedged exposure FlintTrade is not
tracking (or thinks it holds but does not) — always critical. An order the
broker lists but FlintTrade does not is usually the operator trading in the
broker's own app — a warning. An order FlintTrade tracks that the broker has
no record of is a phantom order (a failed/uncertain write) — critical.
Holdings are settled demat stock, not intraday risk — warnings.

Flat rows (quantity ``0``) are dropped from BOTH sides before positions and
holdings are diffed: a closed position listed broker-side and absent locally
both mean "flat" and are not a discrepancy.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
from dataclasses import asdict, dataclass, field as dataclass_field
from datetime import datetime
from types import MappingProxyType
from typing import Any, Iterable, Mapping

# ---------------------------------------------------------------------------
# Severity + discrepancy vocabulary
# ---------------------------------------------------------------------------

SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_CRITICAL = "critical"

_SEVERITY_RANK = {SEVERITY_INFO: 0, SEVERITY_WARNING: 1, SEVERITY_CRITICAL: 2}

DISCREPANCY_ONLY_ON_BROKER = "exists_only_on_broker"
DISCREPANCY_ONLY_IN_FLINTTRADE = "exists_only_in_flinttrade"
DISCREPANCY_QTY_MISMATCH = "qty_mismatch"
DISCREPANCY_STATUS_MISMATCH = "status_mismatch"


_ORDER_STATUS_ALIASES = {
    "ACKED": "OPEN",
    "ACKNOWLEDGED": "OPEN",
    "AFTER_MARKET_ORDER_REQ_RECEIVED": "OPEN",
    "AMO_REQ_RECEIVED": "OPEN",
    "APPROVED": "OPEN",
    "CREATED": "OPEN",
    "NEW": "OPEN",
    "OPEN": "OPEN",
    "O_PENDING": "OPEN",
    "PENDING": "OPEN",
    "PLACED": "OPEN",
    "PUT_ORDER_REQ_RECEIVED": "OPEN",
    "SUBMITTED": "OPEN",
    "TRANSIT": "OPEN",
    "VALIDATION_PENDING": "OPEN",
    "TRIGGER_PENDING": "TRIGGER_PENDING",
    "TRIGGERED": "TRIGGERED",
    "PARTIAL": "PARTIALLY_FILLED",
    "PARTIAL_FILL": "PARTIALLY_FILLED",
    "PARTIALLY_EXECUTED": "PARTIALLY_FILLED",
    "PARTIALLY_FILLED": "PARTIALLY_FILLED",
    "PARTIALLY_TRADED": "PARTIALLY_FILLED",
    "PARTIALLY_FILLED_CANCELLED": "CANCELLED",
    "PARTIALLY_FILLED_CANCELED": "CANCELLED",
    "PARTIALLY_FILLED_EXPIRED": "EXPIRED",
    "COMPLETE": "COMPLETE",
    "COMPLETED": "COMPLETE",
    "EXECUTED": "COMPLETE",
    "FILLED": "COMPLETE",
    "FULLY_EXECUTED": "COMPLETE",
    "SUCCESS": "COMPLETE",
    "TRADED": "COMPLETE",
    "CANCEL_PENDING": "CANCEL_PENDING",
    "CANCEL_REQ_RECEIVED": "CANCEL_PENDING",
    "CANCEL_REQUESTED": "CANCEL_PENDING",
    "CANCELLATION_PENDING": "CANCEL_PENDING",
    "CANCELLATION_REQUESTED": "CANCEL_PENDING",
    "CANCELED": "CANCELLED",
    "CANCELLED": "CANCELLED",
    "DELETED": "CANCELLED",
    "DISABLED": "CANCELLED",
    "CLOSED": "CLOSED",
    "DELIVERY_AWAITED": "DELIVERY_AWAITED",
    "MODIFICATION_REQUESTED": "MODIFICATION_PENDING",
    "MODIFY_PENDING": "MODIFICATION_PENDING",
    "MODIFY_VALIDATION_PENDING": "MODIFICATION_PENDING",
    "EXPIRED": "EXPIRED",
    "FAILED": "REJECTED",
    "FAILURE": "REJECTED",
    "REJECTED": "REJECTED",
    "NA": "UNKNOWN",
    "N_A": "UNKNOWN",
    "UNKNOWN": "UNKNOWN",
}

_ROW_FIELDS = (
    "orderid",
    "order_id",
    "status",
    "symbol",
    "exchange",
    "product",
    "action",
    "quantity",
    "filled_quantity",
    "price",
    "trigger_price",
    "price_type",
    "pricetype",
    "variety",
    "validity",
    "strategy",
    "average_price",
)

_ORDER_REQUIRED_TEXT_FIELDS = (
    "status",
    "symbol",
    "exchange",
    "product",
    "action",
    "price_type",
    "variety",
    "validity",
    "strategy",
)
_ORDER_REQUIRED_NUMERIC_FIELDS = (
    "quantity",
    "filled_quantity",
    "price",
    "trigger_price",
    "average_price",
)
_DECLARABLE_UNAVAILABLE_ORDER_TEXT_FIELDS = frozenset({"variety", "validity", "strategy"})
_EVIDENCE_SCHEMA = "flinttrade.reconciliation.evidence.v1"
_REPORT_CONTRACT_TOKEN = object()


class _InvalidReconciliationInput(ValueError):
    """Internal control flow for deterministic fail-closed reports."""


@dataclass(frozen=True, slots=True)
class _ReportContractSeal:
    """Immutable construction seal retaining the report's original binding."""

    token: object
    evidence_sha256: str


# ---------------------------------------------------------------------------
# Diff rows
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OrderDiff:
    """One order-level discrepancy (keyed by broker order id)."""

    order_id: str
    symbol: str
    discrepancy: str
    severity: str
    flinttrade_status: str = ""
    broker_status: str = ""
    detail: str = ""


@dataclass(frozen=True, slots=True)
class PositionDiff:
    """One position-level discrepancy (keyed by symbol + exchange + product)."""

    symbol: str
    exchange: str
    product: str
    flinttrade_qty: float
    broker_qty: float
    discrepancy: str
    severity: str


@dataclass(frozen=True, slots=True)
class HoldingDiff:
    """One holding-level discrepancy (keyed by symbol + exchange)."""

    symbol: str
    exchange: str
    flinttrade_qty: float
    broker_qty: float
    discrepancy: str
    severity: str


# ---------------------------------------------------------------------------
# FlintTrade-side mirror
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LocalStateSnapshot:
    """The flinttrade-side mirror handed to :func:`build_report`.

    Rows use the SAME normalised dict shapes the adapters' own reads emit
    (``order_book`` / ``positions`` / ``holdings``), so a journal-backed
    provider can replay recorded reads verbatim. The default is EMPTY state.
    :class:`flinttrade_engine.local_state_provider.JournalLocalStateProvider`
    supplies the previous durable selector-scoped snapshot. The empty default
    remains the fail-closed fallback when no provider is wired or its ledger
    cannot be read.
    """

    orders: tuple[Mapping[str, Any], ...] = ()
    positions: tuple[Mapping[str, Any], ...] = ()
    holdings: tuple[Mapping[str, Any], ...] = ()


EMPTY_LOCAL_STATE = LocalStateSnapshot()


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    """Broker-side vs flinttrade-side state diff (contract §14.1).

    ``generated_at`` is supplied by the caller (the adapter stamps it at fetch
    time), keeping construction free of hidden clock reads. ``error`` is set —
    with every diff and private snapshot left empty — when the broker fetch
    failed or either snapshot is malformed; the runner retries next cycle
    (§14.3).
    """

    adapter_id: str
    account_id: str
    generated_at: datetime
    orders_diff: tuple[OrderDiff, ...] = ()
    positions_diff: tuple[PositionDiff, ...] = ()
    holdings_diff: tuple[HoldingDiff, ...] = ()
    error: str = ""
    # Private recursively frozen snapshots and their canonical digest bind the
    # public diff to the exact evidence used to compute it. They are excluded
    # from equality/repr and deliberately never enter as_dict()/JSONL/audit.
    broker_orders: tuple[Mapping[str, Any], ...] = dataclass_field(
        default=(), init=False, repr=False, compare=False
    )
    broker_positions: tuple[Mapping[str, Any], ...] = dataclass_field(
        default=(), init=False, repr=False, compare=False
    )
    broker_holdings: tuple[Mapping[str, Any], ...] = dataclass_field(
        default=(), init=False, repr=False, compare=False
    )
    local_state: LocalStateSnapshot = dataclass_field(
        default=EMPTY_LOCAL_STATE,
        init=False,
        repr=False,
        compare=False,
    )
    _evidence_sha256: str = dataclass_field(default="", init=False, repr=False, compare=False)
    _contract_token: object | None = dataclass_field(default=None, init=False, repr=False, compare=False)

    @property
    def clean(self) -> bool:
        """True when the broker and FlintTrade agree completely (and no error)."""
        return not (self.orders_diff or self.positions_diff or self.holdings_diff or self.error)

    @property
    def severity(self) -> str:
        """The worst severity across every diff; ``""`` when clean.

        A fetch ``error`` is critical — the broker state is unknown.
        """
        if self.error:
            return SEVERITY_CRITICAL
        worst = ""
        worst_rank = -1
        for diff in (*self.orders_diff, *self.positions_diff, *self.holdings_diff):
            rank = _SEVERITY_RANK.get(diff.severity, 0)
            if rank > worst_rank:
                worst, worst_rank = diff.severity, rank
        return worst

    @property
    def severity_counts(self) -> dict[str, int]:
        """Diff counts per severity level (all levels present, zero-filled)."""
        counts = {SEVERITY_INFO: 0, SEVERITY_WARNING: 0, SEVERITY_CRITICAL: 0}
        for diff in (*self.orders_diff, *self.positions_diff, *self.holdings_diff):
            counts[diff.severity] = counts.get(diff.severity, 0) + 1
        return counts

    def as_dict(self) -> dict[str, Any]:
        """JSON-serialisable form (for the runner's JSONL persistence, §14.2)."""
        return {
            "adapter_id": self.adapter_id,
            "account_id": self.account_id,
            "generated_at": self.generated_at.isoformat(),
            "orders_diff": [asdict(d) for d in self.orders_diff],
            "positions_diff": [asdict(d) for d in self.positions_diff],
            "holdings_diff": [asdict(d) for d in self.holdings_diff],
            "error": self.error,
            "clean": self.clean,
            "severity": self.severity,
            "severity_counts": self.severity_counts,
        }


# ---------------------------------------------------------------------------
# Pure diff computation
# ---------------------------------------------------------------------------


def _text(row: Mapping[str, Any], key: str) -> str:
    value = row.get(key, "")
    value = getattr(value, "value", value)
    return str(value or "").strip()


def normalise_order_status(
    raw_status: Any,
    *,
    quantity: float = 0.0,
    filled_quantity: float = 0.0,
) -> str:
    """Return a deterministic, lifecycle-preserving canonical order status.

    Working aliases collapse to ``OPEN``; partial fills use
    ``PARTIALLY_FILLED``; cancellation requests remain ``CANCEL_PENDING``;
    and ``CLOSED`` is not conflated with ``COMPLETE``. Confirmed terminal
    states remain ``COMPLETE``, ``CANCELLED``, ``REJECTED``, or ``EXPIRED``.
    Trigger, modification, and delivery-wait states retain their own visible
    canonical values. Blank or unrecognised input is always ``UNKNOWN``.

    For a recognised open state, numeric evidence satisfying
    ``0 < filled_quantity < quantity`` promotes the result to
    ``PARTIALLY_FILLED``. That inference never masks a stronger lifecycle
    state such as cancellation pending, closed, terminal, or unknown.
    """
    try:
        value = getattr(raw_status, "value", raw_status)
        text = str(value or "").strip()
    except Exception:
        return "UNKNOWN"
    if not text:
        return "UNKNOWN"
    key = text.upper().replace("-", "_").replace("/", "_")
    key = "_".join(key.split())
    while "__" in key:
        key = key.replace("__", "_")
    canonical = _ORDER_STATUS_ALIASES.get(key, "UNKNOWN")
    if canonical != "OPEN":
        return canonical
    try:
        requested = float(quantity)
        filled = float(filled_quantity)
    except Exception:
        return canonical
    if math.isfinite(requested) and math.isfinite(filled) and 0 < filled < requested:
        return "PARTIALLY_FILLED"
    return canonical


def _qty(row: Mapping[str, Any], key: str = "quantity") -> float:
    """Parse a quantity field defensively (adapters emit them as strings)."""
    try:
        return float(str(row.get(key, 0) or 0))
    except (TypeError, ValueError):
        return 0.0


def _qty_equal(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=0.0, abs_tol=1e-9)


def _fmt(value: float) -> str:
    return f"{value:g}"


def _order_id(row: Mapping[str, Any]) -> str:
    return _text(row, "orderid") or _text(row, "order_id")


def _order_status(row: Mapping[str, Any]) -> str:
    return normalise_order_status(
        _text(row, "status"),
        quantity=_qty(row, "quantity"),
        filled_quantity=_qty(row, "filled_quantity"),
    )


def _row_mapping(row: Any, *, label: str) -> dict[str, Any]:
    if isinstance(row, Mapping):
        try:
            return dict(row)
        except Exception as exc:
            raise _InvalidReconciliationInput(f"{label} is not a valid row object") from exc

    for method_name in ("model_dump", "dict", "_asdict"):
        try:
            method = getattr(row, method_name, None)
        except Exception as exc:
            raise _InvalidReconciliationInput(f"{label} is not a valid row object") from exc
        if not callable(method):
            continue
        try:
            converted = method()
        except Exception as exc:
            raise _InvalidReconciliationInput(f"{label} is not a valid row object") from exc
        if isinstance(converted, Mapping):
            return dict(converted)
        raise _InvalidReconciliationInput(f"{label} is not a valid row object")

    try:
        row_mapping = getattr(row, "_mapping", None)
    except Exception as exc:
        raise _InvalidReconciliationInput(f"{label} is not a valid row object") from exc
    if isinstance(row_mapping, Mapping):
        return dict(row_mapping)

    try:
        converted = dict(row)
    except (TypeError, ValueError):
        converted = None
    except Exception as exc:
        raise _InvalidReconciliationInput(f"{label} is not a valid row object") from exc
    if isinstance(converted, Mapping):
        return dict(converted)

    try:
        attributes = vars(row)
    except Exception:
        attributes = {}
    if isinstance(attributes, Mapping) and attributes:
        return dict(attributes)

    attributes = {}
    for field in _ROW_FIELDS:
        try:
            attributes[field] = getattr(row, field)
        except AttributeError:
            continue
        except Exception as exc:
            raise _InvalidReconciliationInput(f"{label} is not a valid row object") from exc
    if attributes:
        return attributes
    raise _InvalidReconciliationInput(f"{label} is not a valid row object")


def declare_unavailable_order_fields(
    rows: Iterable[Any],
    *,
    fields: Iterable[str],
) -> tuple[dict[str, Any], ...]:
    """Mark broker-unavailable text evidence without inventing a value.

    Adapters may use this only for text attributes their broker's order-book
    read surface does not expose. Identity, lifecycle, and numeric evidence can
    never be declared unavailable and must instead make reconciliation fail
    closed.
    """
    declared = tuple(dict.fromkeys(str(field) for field in fields))
    invalid = set(declared) - _DECLARABLE_UNAVAILABLE_ORDER_TEXT_FIELDS
    if invalid:
        names = ", ".join(sorted(invalid))
        raise ValueError(f"only broker-unavailable text evidence may be declared: {names}")
    if rows is None or isinstance(rows, (str, bytes, bytearray, Mapping)):
        raise ValueError("broker order evidence must be an iterable of rows")
    try:
        iterator = iter(rows)
    except Exception as exc:
        raise ValueError("broker order evidence must be an iterable of rows") from exc
    completed: list[dict[str, Any]] = []
    index = 0
    while True:
        try:
            row = next(iterator)
        except StopIteration:
            break
        except Exception as exc:
            raise ValueError("broker order evidence rows could not be read") from exc
        mapped = _row_mapping(row, label=f"broker orders row {index}")
        for field in declared:
            if not _text(mapped, field):
                mapped[field] = "UNKNOWN"
        completed.append(mapped)
        index += 1
    return tuple(completed)


def _canonicalise_order_aliases(row: dict[str, Any]) -> dict[str, Any]:
    """Collapse accepted read-model aliases into the lifecycle schema."""
    canonical = dict(row)
    if "orderid" not in canonical and "order_id" in canonical:
        canonical["orderid"] = canonical["order_id"]
    canonical.pop("order_id", None)
    if "price_type" not in canonical and "pricetype" in canonical:
        canonical["price_type"] = canonical["pricetype"]
    canonical.pop("pricetype", None)
    return canonical


def _freeze_json(value: Any, *, label: str, _active: set[int] | None = None) -> Any:
    """Return a detached immutable JSON value, rejecting lossy coercions."""
    active = set() if _active is None else _active
    try:
        value = getattr(value, "value", value)
    except Exception as exc:
        raise _InvalidReconciliationInput(f"{label} value could not be read") from exc
    if value is None or type(value) in (bool, int, str):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise _InvalidReconciliationInput(f"{label} contains a non-finite number")
        return value
    if isinstance(value, Mapping):
        marker = id(value)
        if marker in active:
            raise _InvalidReconciliationInput(f"{label} contains a cyclic JSON value")
        active.add(marker)
        try:
            frozen: dict[str, Any] = {}
            try:
                keys = tuple(value.keys())
            except Exception as exc:
                raise _InvalidReconciliationInput(f"{label} object keys could not be read") from exc
            for key in keys:
                if type(key) is not str:
                    raise _InvalidReconciliationInput(f"{label} contains a non-string object key")
            for key in sorted(keys):
                try:
                    nested = value[key]
                except Exception as exc:
                    raise _InvalidReconciliationInput(f"{label}.{key} could not be read") from exc
                frozen[key] = _freeze_json(nested, label=f"{label}.{key}", _active=active)
            return MappingProxyType(frozen)
        finally:
            active.remove(marker)
    if isinstance(value, (list, tuple)):
        marker = id(value)
        if marker in active:
            raise _InvalidReconciliationInput(f"{label} contains a cyclic JSON value")
        active.add(marker)
        try:
            return tuple(
                _freeze_json(item, label=f"{label}[{index}]", _active=active)
                for index, item in enumerate(value)
            )
        finally:
            active.remove(marker)
    raise _InvalidReconciliationInput(f"{label} contains non-JSON value {type(value).__name__}")


def _plain_json(value: Any) -> Any:
    """Convert validated frozen evidence into plain JSON containers."""
    if isinstance(value, Mapping):
        return {key: _plain_json(value[key]) for key in sorted(value)}
    if isinstance(value, tuple):
        return [_plain_json(item) for item in value]
    return value


def _required_text(row: Mapping[str, Any], key: str, *, label: str) -> str:
    try:
        value = _text(row, key)
    except Exception as exc:
        raise _InvalidReconciliationInput(f"{label} has invalid {key}") from exc
    if not value:
        raise _InvalidReconciliationInput(f"{label} missing {key}")
    return value


def _validated_quantity(
    row: Mapping[str, Any],
    key: str,
    *,
    label: str,
    allow_negative: bool,
    required: bool = True,
) -> float:
    if key not in row:
        if required:
            raise _InvalidReconciliationInput(f"{label} missing {key}")
        return 0.0
    if row[key] is None or (isinstance(row[key], str) and not row[key].strip()):
        raise _InvalidReconciliationInput(f"{label} {key} is missing")
    value = row[key]
    if isinstance(value, bool):
        raise _InvalidReconciliationInput(f"{label} {key} must be finite")
    try:
        number = float(value)
    except Exception as exc:
        raise _InvalidReconciliationInput(f"{label} {key} must be finite") from exc
    if not math.isfinite(number):
        raise _InvalidReconciliationInput(f"{label} {key} must be finite")
    if not allow_negative and number < 0:
        raise _InvalidReconciliationInput(f"{label} {key} must not be negative")
    return number


def _validate_row(row: Mapping[str, Any], *, side: str, surface: str, label: str) -> Any:
    if surface == "orders":
        try:
            order_id = _order_id(row)
        except Exception as exc:
            raise _InvalidReconciliationInput(f"{label} missing order id") from exc
        if not order_id:
            raise _InvalidReconciliationInput(f"{label} missing order id")
        if side == "broker":
            for field in _ORDER_REQUIRED_TEXT_FIELDS:
                _required_text(row, field, label=label)
            validated_numbers = {
                field: _validated_quantity(row, field, label=label, allow_negative=False)
                for field in _ORDER_REQUIRED_NUMERIC_FIELDS
            }
            quantity = validated_numbers["quantity"]
            filled_quantity = validated_numbers["filled_quantity"]
        else:
            _required_text(row, "status", label=label)
            quantity = _validated_quantity(row, "quantity", label=label, allow_negative=False)
            filled_quantity = _validated_quantity(
                row,
                "filled_quantity",
                label=label,
                allow_negative=False,
                required=False,
            )
        if filled_quantity > quantity:
            raise _InvalidReconciliationInput(f"{label} filled_quantity exceeds quantity")
        return order_id

    symbol = _required_text(row, "symbol", label=label).upper()
    exchange = _required_text(row, "exchange", label=label).upper()
    if surface == "positions":
        product = _required_text(row, "product", label=label).upper()
        _validated_quantity(row, "quantity", label=label, allow_negative=True)
        return symbol, exchange, product
    if surface == "holdings":
        _validated_quantity(row, "quantity", label=label, allow_negative=False)
        return symbol, exchange
    raise _InvalidReconciliationInput(f"{label} has unsupported surface")


def _validated_rows(rows: Any, *, side: str, surface: str) -> tuple[Mapping[str, Any], ...]:
    if rows is None or isinstance(rows, (str, bytes, bytearray, Mapping)):
        raise _InvalidReconciliationInput(f"{side} {surface} is not an iterable of rows")
    try:
        iterator = iter(rows)
    except Exception as exc:
        raise _InvalidReconciliationInput(f"{side} {surface} is not an iterable of rows") from exc

    converted_rows: list[tuple[Any, Mapping[str, Any]]] = []
    seen: set[Any] = set()
    index = 0
    while True:
        try:
            row = next(iterator)
        except StopIteration:
            break
        except Exception as exc:
            raise _InvalidReconciliationInput(f"{side} {surface} rows could not be read") from exc
        label = f"{side} {surface} row {index}"
        converted = _row_mapping(row, label=label)
        if surface == "orders":
            converted = _canonicalise_order_aliases(converted)
        key = _validate_row(converted, side=side, surface=surface, label=label)
        if key in seen:
            raise _InvalidReconciliationInput(f"{side} {surface} duplicate {surface} natural key at row {index}")
        seen.add(key)
        frozen = _freeze_json(converted, label=label)
        if not isinstance(frozen, Mapping):  # pragma: no cover - row conversion guarantees this
            raise _InvalidReconciliationInput(f"{label} is not a valid row object")
        converted_rows.append((key, frozen))
        index += 1
    converted_rows.sort(key=lambda item: item[0])
    return tuple(row for _key, row in converted_rows)


def reconciliation_evidence_sha256(
    *,
    adapter_id: str,
    account_id: str,
    generated_at: datetime,
    broker_orders: tuple[Mapping[str, Any], ...],
    broker_positions: tuple[Mapping[str, Any], ...],
    broker_holdings: tuple[Mapping[str, Any], ...],
    local_state: LocalStateSnapshot,
) -> str:
    """Hash the exact validated snapshots retained by a successful report."""
    document = {
        "schema": _EVIDENCE_SCHEMA,
        "adapter_id": adapter_id,
        "account_id": account_id,
        "generated_at": generated_at.isoformat(),
        "broker": {
            "orders": _plain_json(broker_orders),
            "positions": _plain_json(broker_positions),
            "holdings": _plain_json(broker_holdings),
        },
        "local": {
            "orders": _plain_json(local_state.orders),
            "positions": _plain_json(local_state.positions),
            "holdings": _plain_json(local_state.holdings),
        },
    }
    encoded = json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def is_canonical_reconciliation_report(report: Any) -> bool:
    """Return whether *report* was constructed by :func:`build_report`."""
    if type(report) is not ReconciliationReport or type(report._contract_token) is not _ReportContractSeal:
        return False
    seal = report._contract_token
    if type(report._evidence_sha256) is not str or type(seal.evidence_sha256) is not str:
        return False
    return seal.token is _REPORT_CONTRACT_TOKEN and hmac.compare_digest(
        report._evidence_sha256,
        seal.evidence_sha256,
    )


def original_reconciliation_evidence_sha256(report: ReconciliationReport) -> str:
    """Return the immutable evidence binding sealed at report construction."""
    if not is_canonical_reconciliation_report(report):
        return ""
    seal = report._contract_token
    return seal.evidence_sha256 if isinstance(seal, _ReportContractSeal) else ""


def _stamp_report(
    report: ReconciliationReport,
    *,
    broker_orders: tuple[Mapping[str, Any], ...] = (),
    broker_positions: tuple[Mapping[str, Any], ...] = (),
    broker_holdings: tuple[Mapping[str, Any], ...] = (),
    local_state: LocalStateSnapshot = EMPTY_LOCAL_STATE,
) -> ReconciliationReport:
    """Attach immutable private evidence to a newly constructed report."""
    object.__setattr__(report, "broker_orders", broker_orders)
    object.__setattr__(report, "broker_positions", broker_positions)
    object.__setattr__(report, "broker_holdings", broker_holdings)
    object.__setattr__(report, "local_state", local_state)
    evidence_sha256 = ""
    if not report.error:
        evidence_sha256 = reconciliation_evidence_sha256(
            adapter_id=report.adapter_id,
            account_id=report.account_id,
            generated_at=report.generated_at,
            broker_orders=broker_orders,
            broker_positions=broker_positions,
            broker_holdings=broker_holdings,
            local_state=local_state,
        )
    object.__setattr__(report, "_evidence_sha256", evidence_sha256)
    object.__setattr__(
        report,
        "_contract_token",
        _ReportContractSeal(_REPORT_CONTRACT_TOKEN, evidence_sha256),
    )
    return report


def _error_report(*, adapter_id: str, account_id: str, generated_at: datetime, error: str) -> ReconciliationReport:
    return _stamp_report(
        ReconciliationReport(
            adapter_id=adapter_id,
            account_id=account_id,
            generated_at=generated_at,
            error=error,
        )
    )


def _index_orders(rows: Iterable[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    # Rows without an order id cannot be matched and are skipped (a broker
    # row always carries one; a local row without one is unkeyable noise).
    return {oid: row for row in rows if (oid := _order_id(row))}


def _position_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (_text(row, "symbol").upper(), _text(row, "exchange").upper(), _text(row, "product").upper())


def _holding_key(row: Mapping[str, Any]) -> tuple[str, str]:
    return (_text(row, "symbol").upper(), _text(row, "exchange").upper())


def _index_nonflat(rows: Iterable[Mapping[str, Any]], key_fn: Any) -> dict[Any, Mapping[str, Any]]:
    return {key_fn(row): row for row in rows if not _qty_equal(_qty(row), 0.0)}


def diff_orders(
    broker_rows: Iterable[Mapping[str, Any]], local_rows: Iterable[Mapping[str, Any]]
) -> tuple[OrderDiff, ...]:
    """Diff broker vs flinttrade order books, keyed by order id.

    A matched order can emit both a ``status_mismatch`` and a ``qty_mismatch``
    diff. Documented status aliases are compared through
    :func:`normalise_order_status`, so spelling and casing differences do not
    hide lifecycle states or create false discrepancies.
    """
    broker = _index_orders(broker_rows)
    local = _index_orders(local_rows)
    diffs: list[OrderDiff] = []
    for order_id in sorted(broker.keys() | local.keys()):
        if order_id not in broker:
            local_only = local[order_id]
            diffs.append(
                OrderDiff(
                    order_id=order_id,
                    symbol=_text(local_only, "symbol"),
                    discrepancy=DISCREPANCY_ONLY_IN_FLINTTRADE,
                    severity=SEVERITY_CRITICAL,
                    flinttrade_status=_order_status(local_only),
                )
            )
            continue
        if order_id not in local:
            broker_only = broker[order_id]
            diffs.append(
                OrderDiff(
                    order_id=order_id,
                    symbol=_text(broker_only, "symbol"),
                    discrepancy=DISCREPANCY_ONLY_ON_BROKER,
                    severity=SEVERITY_WARNING,
                    broker_status=_order_status(broker_only),
                )
            )
            continue
        broker_row = broker[order_id]
        local_row = local[order_id]
        local_status = _order_status(local_row)
        broker_status = _order_status(broker_row)
        if local_status != broker_status:
            diffs.append(
                OrderDiff(
                    order_id=order_id,
                    symbol=_text(broker_row, "symbol"),
                    discrepancy=DISCREPANCY_STATUS_MISMATCH,
                    severity=SEVERITY_WARNING,
                    flinttrade_status=local_status,
                    broker_status=broker_status,
                )
            )
        qty_details: list[str] = []
        for field in ("quantity", "filled_quantity"):
            local_qty = _qty(local_row, field)
            broker_qty = _qty(broker_row, field)
            if not _qty_equal(local_qty, broker_qty):
                qty_details.append(f"{field}: flinttrade={_fmt(local_qty)} broker={_fmt(broker_qty)}")
        if qty_details:
            diffs.append(
                OrderDiff(
                    order_id=order_id,
                    symbol=_text(broker_row, "symbol"),
                    discrepancy=DISCREPANCY_QTY_MISMATCH,
                    severity=SEVERITY_WARNING,
                    flinttrade_status=local_status,
                    broker_status=broker_status,
                    detail="; ".join(qty_details),
                )
            )
    return tuple(diffs)


def diff_positions(
    broker_rows: Iterable[Mapping[str, Any]], local_rows: Iterable[Mapping[str, Any]]
) -> tuple[PositionDiff, ...]:
    """Diff broker vs flinttrade positions, keyed by (symbol, exchange, product).

    Flat rows (net quantity ``0``) are dropped from both sides first. Every
    position discrepancy is critical — it is live exposure one side is blind to.
    """
    broker = _index_nonflat(broker_rows, _position_key)
    local = _index_nonflat(local_rows, _position_key)
    diffs: list[PositionDiff] = []
    for key in sorted(broker.keys() | local.keys()):
        symbol, exchange, product = key
        broker_qty = _qty(broker[key]) if key in broker else 0.0
        local_qty = _qty(local[key]) if key in local else 0.0
        if key not in local:
            discrepancy = DISCREPANCY_ONLY_ON_BROKER
        elif key not in broker:
            discrepancy = DISCREPANCY_ONLY_IN_FLINTTRADE
        elif not _qty_equal(local_qty, broker_qty):
            discrepancy = DISCREPANCY_QTY_MISMATCH
        else:
            continue
        diffs.append(
            PositionDiff(
                symbol=symbol,
                exchange=exchange,
                product=product,
                flinttrade_qty=local_qty,
                broker_qty=broker_qty,
                discrepancy=discrepancy,
                severity=SEVERITY_CRITICAL,
            )
        )
    return tuple(diffs)


def diff_holdings(
    broker_rows: Iterable[Mapping[str, Any]], local_rows: Iterable[Mapping[str, Any]]
) -> tuple[HoldingDiff, ...]:
    """Diff broker vs flinttrade holdings, keyed by (symbol, exchange).

    Flat rows are dropped first. Holdings are settled demat stock, not
    intraday risk, so every holdings discrepancy is a warning.
    """
    broker = _index_nonflat(broker_rows, _holding_key)
    local = _index_nonflat(local_rows, _holding_key)
    diffs: list[HoldingDiff] = []
    for key in sorted(broker.keys() | local.keys()):
        symbol, exchange = key
        broker_qty = _qty(broker[key]) if key in broker else 0.0
        local_qty = _qty(local[key]) if key in local else 0.0
        if key not in local:
            discrepancy = DISCREPANCY_ONLY_ON_BROKER
        elif key not in broker:
            discrepancy = DISCREPANCY_ONLY_IN_FLINTTRADE
        elif not _qty_equal(local_qty, broker_qty):
            discrepancy = DISCREPANCY_QTY_MISMATCH
        else:
            continue
        diffs.append(
            HoldingDiff(
                symbol=symbol,
                exchange=exchange,
                flinttrade_qty=local_qty,
                broker_qty=broker_qty,
                discrepancy=discrepancy,
                severity=SEVERITY_WARNING,
            )
        )
    return tuple(diffs)


def build_report(
    *,
    adapter_id: str,
    generated_at: datetime,
    account_id: str = "",
    broker_orders: Iterable[Any] = (),
    broker_positions: Iterable[Any] = (),
    broker_holdings: Iterable[Any] = (),
    local_state: LocalStateSnapshot | None = None,
    error: str = "",
) -> ReconciliationReport:
    """Compute a deterministic broker-vs-flinttrade diff report (pure).

    Args:
        adapter_id: The adapter's canonical ``broker_id``.
        generated_at: Caller-supplied capture timestamp (no hidden clock read).
        account_id: The broker account the snapshots belong to.
        broker_orders: Normalised order-book rows fetched from the broker.
        broker_positions: Normalised position rows fetched from the broker.
        broker_holdings: Normalised holding rows fetched from the broker.
        local_state: The flinttrade-side mirror; ``None`` means empty state.
            Malformed broker or local rows return a critical error report with
            no diffs or retained snapshots.
        error: Non-empty when the broker fetch failed. The diff tuples are
            then left EMPTY — diffing against an unknown broker state would
            fabricate discrepancies (§14.3: the runner retries next cycle).

    Returns:
        The frozen :class:`ReconciliationReport`.
    """
    if error:
        return _error_report(
            adapter_id=adapter_id,
            account_id=account_id,
            generated_at=generated_at,
            error=error,
        )
    local = local_state if local_state is not None else EMPTY_LOCAL_STATE
    if not isinstance(local, LocalStateSnapshot):
        return _error_report(
            adapter_id=adapter_id,
            account_id=account_id,
            generated_at=generated_at,
            error="invalid reconciliation input: local state is not a LocalStateSnapshot",
        )
    try:
        orders_snapshot = _validated_rows(broker_orders, side="broker", surface="orders")
        positions_snapshot = _validated_rows(broker_positions, side="broker", surface="positions")
        holdings_snapshot = _validated_rows(broker_holdings, side="broker", surface="holdings")
        local_orders = _validated_rows(local.orders, side="local", surface="orders")
        local_positions = _validated_rows(local.positions, side="local", surface="positions")
        local_holdings = _validated_rows(local.holdings, side="local", surface="holdings")
    except _InvalidReconciliationInput as exc:
        return _error_report(
            adapter_id=adapter_id,
            account_id=account_id,
            generated_at=generated_at,
            error=f"invalid reconciliation input: {exc}",
        )
    frozen_local = LocalStateSnapshot(
        orders=local_orders,
        positions=local_positions,
        holdings=local_holdings,
    )
    return _stamp_report(
        ReconciliationReport(
            adapter_id=adapter_id,
            account_id=account_id,
            generated_at=generated_at,
            orders_diff=diff_orders(orders_snapshot, local_orders),
            positions_diff=diff_positions(positions_snapshot, local_positions),
            holdings_diff=diff_holdings(holdings_snapshot, local_holdings),
        ),
        broker_orders=orders_snapshot,
        broker_positions=positions_snapshot,
        broker_holdings=holdings_snapshot,
        local_state=frozen_local,
    )
