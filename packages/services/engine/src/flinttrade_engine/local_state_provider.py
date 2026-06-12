"""Journal-backed local-state provider for broker reconciliation (contract §14).

Every native broker adapter accepts a ``local_state_provider`` constructor
kwarg (``session -> LocalStateSnapshot``) supplying the flinttrade-side mirror
that ``reconcile(session)`` diffs broker state against. This module is the
journal-backed implementation the app wires into that kwarg.

What the journal actually records today
---------------------------------------

The shared trade store (``flinttrade_data.storage.StorageManager``, the
``trades`` table) is written by the gated live-order dispatch
(``flinttrade_core.order_routes._record_trade_journal``) with: ``ts`` /
``orderid`` / ``symbol`` / ``exchange`` / ``action`` / ``quantity`` /
``price`` / ``product`` / ``strategy``. Three properties of that record make
it UNUSABLE as a reconciliation mirror without fabricating discrepancies:

* **No broker order status and no filled quantity.** Rows are stamped at
  DISPATCH time, before the broker accepts, fills, or rejects the order.
  Feeding them to ``diff_orders`` would fabricate a ``status_mismatch``
  (local ``""`` vs broker ``"COMPLETE"``) plus a ``filled_quantity``
  ``qty_mismatch`` warning for every genuinely matched order.
* **No (adapter_id, account_id) attribution.** A journal row cannot be
  assigned to the session being reconciled; with two live broker accounts,
  every other account's order ids would surface as phantom-order CRITICALs
  (``exists_only_in_flinttrade``) on every cycle.
* **No positions or holdings mirror exists anywhere in the journal.**
  Deriving net positions from dispatch stamps would invent exposure for
  rejected/unfilled orders and miss carried-forward overnight positions.

Honest behaviour, therefore: **every snapshot surface is currently empty.**
The diff then reports each broker-side row as ``exists_only_on_broker``,
exactly the documented empty-mirror semantics in
``flinttrade_gateway.reconciliation`` — no state is invented, no discrepancy
is fabricated. The provider still owns the storage seam (handles resolved
lazily at call time), so when the journal grows account-attributed,
status-bearing order/position mirrors, only this module changes — the
adapters, the runner, and the app wiring stay untouched.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:  # pragma: no cover - typing only
    from flinttrade_gateway.reconciliation import LocalStateSnapshot

logger = logging.getLogger("flinttrade.engine.local_state_provider")


class JournalLocalStateProvider:
    """The journal-backed ``session -> LocalStateSnapshot`` callable.

    Storage handles are injected as zero-argument PROVIDERS (not live objects)
    so construction order does not matter: the app builds this before the
    shared trade store exists, and each call resolves the current handle.

    Args:
        storage_provider: Zero-argument callable returning the shared trade
            store (``StorageManager``) or ``None`` when journalling is not
            wired. Unused today (see module docstring); kept as the seam for
            the account-attributed mirror.
        lock_provider: Zero-argument callable returning the lock that
            serialises access to the store's single DuckDB connection, or
            ``None``. Same seam rationale as ``storage_provider``.
    """

    def __init__(
        self,
        *,
        storage_provider: Callable[[], Any] | None = None,
        lock_provider: Callable[[], Any] | None = None,
    ) -> None:
        self._storage_provider = storage_provider
        self._lock_provider = lock_provider

    def __call__(self, session: Any) -> LocalStateSnapshot:
        """Return the flinttrade-side mirror for ``session``'s account.

        Currently ALWAYS the empty snapshot — the journal cannot attribute
        rows to a broker account and records no order status, positions, or
        holdings (see module docstring). Deliberately does not synthesise any
        row from the dispatch-time trade stamps: that would fabricate
        discrepancies rather than reveal them.

        Args:
            session: The adapter-layer session being reconciled (duck-typed;
                only present so the signature matches the adapter contract).

        Returns:
            An empty :class:`~flinttrade_gateway.reconciliation.LocalStateSnapshot`.
        """
        from flinttrade_gateway.reconciliation import LocalStateSnapshot  # noqa: PLC0415

        return LocalStateSnapshot(orders=(), positions=(), holdings=())
