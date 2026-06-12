"""Reconciliation report model + pure diff helpers (contract §14, parent §11.6).

Every native broker adapter implements ``reconcile(session)`` returning a
:class:`ReconciliationReport` — the broker-side truth (order book / positions /
holdings fetched through the adapter's own reads) diffed against the
flinttrade-side mirror (a :class:`LocalStateSnapshot` supplied by an injectable
``local_state_provider`` on the adapter; the engine wave's runner wires the
journal-backed provider later without any signature change).

The diff itself (:func:`build_report` and the ``diff_*`` helpers) is PURE and
deterministic: given the same snapshots it always produces the same report,
with diffs ordered by their natural key. Row shapes are the adapters' own
normalised read dicts (``orderid``/``status``/``symbol``/``exchange``/
``product``/``quantity``/``filled_quantity``), so the same mirror rows the
journal records from adapter reads diff cleanly against fresh broker fetches.

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

import math
from dataclasses import asdict, dataclass
from datetime import datetime
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
    provider can replay recorded reads verbatim. The default is EMPTY state:
    until the engine wave wires the real provider, every broker-side row
    surfaces as ``exists_only_on_broker``.
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
    with every diff tuple left empty — when the broker fetch failed; the
    runner retries next cycle (§14.3).
    """

    adapter_id: str
    account_id: str
    generated_at: datetime
    orders_diff: tuple[OrderDiff, ...] = ()
    positions_diff: tuple[PositionDiff, ...] = ()
    holdings_diff: tuple[HoldingDiff, ...] = ()
    error: str = ""

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
    return str(row.get(key, "") or "").strip()


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


def _index_orders(rows: Iterable[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    # Rows without an order id cannot be matched and are skipped (a broker
    # row always carries one; a local row without one is unkeyable noise).
    return {oid: row for row in rows if (oid := _order_id(row))}


def _position_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (_text(row, "symbol").upper(), _text(row, "exchange").upper(), _text(row, "product").upper())


def _holding_key(row: Mapping[str, Any]) -> tuple[str, str]:
    return (_text(row, "symbol").upper(), _text(row, "exchange").upper())


def _index_nonflat(
    rows: Iterable[Mapping[str, Any]], key_fn: Any
) -> dict[Any, Mapping[str, Any]]:
    return {key_fn(row): row for row in rows if not _qty_equal(_qty(row), 0.0)}


def diff_orders(
    broker_rows: Iterable[Mapping[str, Any]], local_rows: Iterable[Mapping[str, Any]]
) -> tuple[OrderDiff, ...]:
    """Diff broker vs flinttrade order books, keyed by order id.

    A matched order can emit both a ``status_mismatch`` and a ``qty_mismatch``
    diff. Status comparison is case-insensitive (both sides come from the same
    adapter vocabulary; casing differences are not a discrepancy).
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
                    flinttrade_status=_text(local_only, "status"),
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
                    broker_status=_text(broker_only, "status"),
                )
            )
            continue
        broker_row = broker[order_id]
        local_row = local[order_id]
        local_status = _text(local_row, "status")
        broker_status = _text(broker_row, "status")
        if local_status.casefold() != broker_status.casefold():
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
    broker_orders: Iterable[Mapping[str, Any]] = (),
    broker_positions: Iterable[Mapping[str, Any]] = (),
    broker_holdings: Iterable[Mapping[str, Any]] = (),
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
        error: Non-empty when the broker fetch failed. The diff tuples are
            then left EMPTY — diffing against an unknown broker state would
            fabricate discrepancies (§14.3: the runner retries next cycle).

    Returns:
        The frozen :class:`ReconciliationReport`.
    """
    if error:
        return ReconciliationReport(
            adapter_id=adapter_id, account_id=account_id, generated_at=generated_at, error=error
        )
    local = local_state if local_state is not None else EMPTY_LOCAL_STATE
    return ReconciliationReport(
        adapter_id=adapter_id,
        account_id=account_id,
        generated_at=generated_at,
        orders_diff=diff_orders(broker_orders, local.orders),
        positions_diff=diff_positions(broker_positions, local.positions),
        holdings_diff=diff_holdings(broker_holdings, local.holdings),
    )
