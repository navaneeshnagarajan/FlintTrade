"""Position mirroring — replicate master orders across slave accounts.

Allocation modes:
1. Equal: same qty to all accounts
2. Weighted: proportional to account allocation weight
3. Margin-aware: calculate available margin, size accordingly
4. Lot-based: round to nearest lot size per account

Additional capabilities:
- WebSocket-based position-change detection via ``PositionWatcher``
- Multiplier-based allocation: slave qty = master qty × per-account multiplier
- Broker cost metadata on mirror configs for routing cost-aware decisions

Uses ThreadPoolExecutor for parallel execution across accounts
(adapts AlgoMirror's strategy_executor.py pattern).
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any, Callable

import httpx

from flinttrade_core.models import Order, OrderResponse
from flinttrade_screener.lot_sizes import FALLBACK_LOT_SIZES

from .account_manager import BrokerAccount

logger = logging.getLogger("flinttrade.ditto.mirror")

IST = timezone(timedelta(hours=5, minutes=30))


class AllocationMode(StrEnum):
    EQUAL = "EQUAL"
    WEIGHTED = "WEIGHTED"
    MARGIN_AWARE = "MARGIN_AWARE"
    LOT_BASED = "LOT_BASED"
    MULTIPLIER = "MULTIPLIER"


# Lot sizes for F&O instruments — single source of truth is the screener's
# contract-size table (union-merged 2026-07-07; live symbol-master values are
# served by flinttrade_screener.lot_sizes.LotSizeResolver). This module held
# its own badly stale copy (BANKNIFTY 15, FINNIFTY 25) that mis-sized mirror
# quantities.
LOT_SIZES: dict[str, int] = FALLBACK_LOT_SIZES


@dataclass
class MirrorOrderResult:
    """Result of mirroring an order to a single account."""

    account_id: str
    success: bool = False
    order_response: OrderResponse | None = None
    quantity_sent: int = 0
    error: str = ""


@dataclass
class MirrorResult:
    """Aggregate result of mirroring an order across all accounts."""

    master_order: Order | None = None
    allocation_mode: str = ""
    total_accounts: int = 0
    successful: int = 0
    failed: int = 0
    skipped: int = 0
    results: list[MirrorOrderResult] = field(default_factory=list)
    timestamp: str = ""

    @property
    def all_succeeded(self) -> bool:
        return self.failed == 0 and self.successful > 0


def compute_allocation(
    master_qty: int,
    accounts: list[BrokerAccount],
    mode: AllocationMode | str,
    symbol: str = "",
    available_margins: dict[str, float] | None = None,
    price_per_unit: float = 0.0,
) -> dict[str, int]:
    """Compute per-account quantity allocation.

    Returns: {account_id: quantity}
    """
    mode_val = mode.value if isinstance(mode, AllocationMode) else mode
    result: dict[str, int] = {}

    if not accounts:
        return result

    if mode_val == AllocationMode.EQUAL.value:
        for acc in accounts:
            result[acc.account_id] = master_qty

    elif mode_val == AllocationMode.WEIGHTED.value:
        total_weight = sum(a.allocation_weight for a in accounts)
        if total_weight <= 0:
            total_weight = len(accounts)
        for acc in accounts:
            frac = acc.allocation_weight / total_weight
            qty = max(1, int(round(master_qty * frac)))
            result[acc.account_id] = qty

    elif mode_val == AllocationMode.MARGIN_AWARE.value:
        margins = available_margins or {}
        total_margin = sum(margins.values())
        if total_margin <= 0 or price_per_unit <= 0:
            # Fall back to equal
            for acc in accounts:
                result[acc.account_id] = master_qty
        else:
            for acc in accounts:
                avail = margins.get(acc.account_id, 0.0)
                max_affordable = int(avail / price_per_unit) if price_per_unit > 0 else 0
                frac = avail / total_margin
                qty = max(0, min(int(round(master_qty * frac)), max_affordable))
                if qty > 0:
                    result[acc.account_id] = qty

    elif mode_val == AllocationMode.LOT_BASED.value:
        lot_size = _get_lot_size(symbol)
        total_weight = sum(a.allocation_weight for a in accounts)
        if total_weight <= 0:
            total_weight = len(accounts)
        for acc in accounts:
            frac = acc.allocation_weight / total_weight
            raw_qty = master_qty * frac
            lots = max(1, round(raw_qty / lot_size)) if lot_size > 0 else max(1, int(raw_qty))
            result[acc.account_id] = lots * lot_size

    # MULTIPLIER mode is handled by compute_multiplier_allocation; reaching
    # here means compute_allocation was called with MULTIPLIER without a
    # MirrorConfig.  Fall back to equal allocation.
    elif mode_val == AllocationMode.MULTIPLIER.value:
        for acc in accounts:
            result[acc.account_id] = master_qty

    return result


def _get_lot_size(symbol: str) -> int:
    """Determine lot size from symbol name.

    Prefers the LONGEST matching underlying — plain substring iteration
    resolved ``BANKNIFTY24JULFUT`` to NIFTY's lot (``"NIFTY" in sym`` is true
    for every *NIFTY contract) depending on dict order.
    """
    sym = symbol.upper()
    matches = [key for key in LOT_SIZES if key in sym]
    if matches:
        return LOT_SIZES[max(matches, key=len)]
    return 1


# ---------------------------------------------------------------------------
# Broker cost metadata
# ---------------------------------------------------------------------------


@dataclass
class BrokerCostMetadata:
    """Per-broker transaction cost breakdown for routing decisions.

    Costs are expressed as fractions of trade value unless otherwise noted.
    This metadata is attached to a mirror config so the orchestration layer
    can route cost-sensitive orders to the cheapest execution venue.

    Example (Kotak Neo post-April 2026)::

        BrokerCostMetadata(
            broker_key="kotak",
            brokerage_frac=0.0,          # ₹0 brokerage
            stt_futures_sell=0.0005,     # 0.05% from April 2026
            stt_options_sell=0.0015,     # 0.15% from April 2026
            exchange_charge_futures=1.73e-5,
            exchange_charge_options=3.503e-4,
            gst_rate=0.18,
            sebi_charge_per_crore=10.0,
            stamp_duty_buy_futures=2e-5,
            stamp_duty_buy_options=3e-5,
            demat_amc_annual=600.0,
            notes="Zero brokerage on all API orders from Nov 2025",
        )
    """

    broker_key: str = ""
    display_name: str = ""

    # Brokerage
    brokerage_frac: float = 0.0002          # fraction of trade value
    brokerage_flat_per_order: float = 0.0   # flat ₹ per order (if applicable)

    # STT (Securities Transaction Tax)
    stt_futures_sell: float = 0.0005        # fraction of futures sell-side value
    stt_options_sell: float = 0.0015        # fraction of options sell-side premium

    # Exchange transaction charges (NSE defaults)
    exchange_charge_futures: float = 1.73e-5    # ₹1.73 per lakh
    exchange_charge_options: float = 3.503e-4   # ₹35.03 per lakh premium

    # Regulatory
    gst_rate: float = 0.18                  # 18% on brokerage + exchange + SEBI
    sebi_charge_per_crore: float = 10.0     # ₹10 per crore
    stamp_duty_buy_futures: float = 2e-5    # 0.002% buy-side futures
    stamp_duty_buy_options: float = 3e-5    # 0.003% buy-side options

    # Annual fixed costs (not per-trade, but tracked for cost modelling)
    demat_amc_annual: float = 0.0           # Annual maintenance charge ₹

    notes: str = ""

    def estimated_roundtrip_cost_frac(
        self,
        is_options: bool = True,
        trade_value: float = 0.0,
    ) -> float:
        """Rough per-trade round-trip cost as a fraction of *trade_value*.

        This is an approximation for pre-trade cost estimation.  Regulatory
        charges that depend on actual fill prices are computed separately.

        Args:
            is_options: True for options, False for futures.
            trade_value: Notional trade value in ₹ (used for SEBI scaling).

        Returns:
            Estimated fraction of trade value consumed by costs.
        """
        brok = self.brokerage_frac * 2  # entry + exit
        if is_options:
            stt = self.stt_options_sell
            exc = self.exchange_charge_options * 2
            stamp = self.stamp_duty_buy_options
        else:
            stt = self.stt_futures_sell
            exc = self.exchange_charge_futures * 2
            stamp = self.stamp_duty_buy_futures

        gst_base = brok + exc
        gst = gst_base * self.gst_rate
        sebi = (self.sebi_charge_per_crore / 1e7) * 2  # 2 legs
        return brok + stt + exc + gst + sebi + stamp


# ---------------------------------------------------------------------------
# Mirror configuration with broker cost routing
# ---------------------------------------------------------------------------


@dataclass
class MirrorConfig:
    """Configuration for a mirroring session.

    Attaches allocation preferences and broker cost metadata to a set of
    accounts so the ``PositionMirror`` can apply per-account multipliers and
    expose cost-routing information to higher-level orchestration.

    Attributes:
        mode: Default ``AllocationMode`` for this config.
        multiplier: Global lot multiplier applied on top of master quantity
            when ``mode`` is ``AllocationMode.MULTIPLIER``.  Per-account
            overrides are stored in ``account_multipliers``.
        account_multipliers: Per-account multiplier overrides keyed by
            ``BrokerAccount.account_id``.  Falls back to ``multiplier`` for
            accounts not listed here.
        broker_costs: Optional cost metadata for each account's broker, keyed
            by ``BrokerAccount.account_id``.  Used by orchestration layers that
            want to route to the cheapest venue.
    """

    mode: AllocationMode | str = AllocationMode.EQUAL
    multiplier: float = 1.0
    account_multipliers: dict[str, float] = field(default_factory=dict)
    broker_costs: dict[str, BrokerCostMetadata] = field(default_factory=dict)

    def get_multiplier(self, account_id: str) -> float:
        """Return the effective multiplier for *account_id*.

        Args:
            account_id: The ``BrokerAccount.account_id`` to look up.

        Returns:
            Per-account multiplier if configured, else the global ``multiplier``.
        """
        return self.account_multipliers.get(account_id, self.multiplier)

    def get_broker_cost(self, account_id: str) -> BrokerCostMetadata | None:
        """Return broker cost metadata for *account_id*, or None if absent.

        Args:
            account_id: The ``BrokerAccount.account_id`` to look up.

        Returns:
            ``BrokerCostMetadata`` if registered, else ``None``.
        """
        return self.broker_costs.get(account_id)

    def cheapest_account(
        self,
        account_ids: list[str],
        is_options: bool = True,
        trade_value: float = 0.0,
    ) -> str | None:
        """Return the account ID with the lowest estimated round-trip cost.

        Only accounts that have broker cost metadata registered are considered.
        If no metadata is registered for any account, returns ``None``.

        Args:
            account_ids: Candidate account IDs to compare.
            is_options: Whether to use options or futures cost model.
            trade_value: Notional trade value for SEBI scaling.

        Returns:
            Account ID with the lowest cost, or ``None`` if no cost data.
        """
        best_id: str | None = None
        best_cost = float("inf")
        for acc_id in account_ids:
            meta = self.broker_costs.get(acc_id)
            if meta is None:
                continue
            cost = meta.estimated_roundtrip_cost_frac(
                is_options=is_options, trade_value=trade_value
            )
            if cost < best_cost:
                best_cost = cost
                best_id = acc_id
        return best_id


# ---------------------------------------------------------------------------
# Multiplier-based allocation
# ---------------------------------------------------------------------------


def compute_multiplier_allocation(
    master_qty: int,
    accounts: list[BrokerAccount],
    config: MirrorConfig,
) -> dict[str, int]:
    """Compute per-account quantities using per-account multipliers.

    Each slave account receives ``master_qty × multiplier`` lots, rounded to
    the nearest integer (minimum 1 if multiplier > 0).

    Args:
        master_qty: Master account's order quantity.
        accounts: Slave accounts to allocate to.
        config: MirrorConfig supplying per-account multipliers.

    Returns:
        Dict mapping account_id to computed quantity.  Accounts with a
        zero or negative multiplier are omitted.
    """
    result: dict[str, int] = {}
    for acc in accounts:
        mult = config.get_multiplier(acc.account_id)
        if mult <= 0:
            continue
        qty = max(1, int(round(master_qty * mult)))
        result[acc.account_id] = qty
    return result


# ---------------------------------------------------------------------------
# WebSocket-based position change detection
# ---------------------------------------------------------------------------

#: Callback type: receives ``(account_id, position_snapshot)`` where
#: ``position_snapshot`` is the raw dict from the OpenAlgo positionbook API.
PositionChangeCallback = Callable[[str, dict], None]


class PositionWatcher:
    """Poll positionbook over REST and fire callbacks on detected changes.

    OpenAlgo does not currently emit position events over its WebSocket
    (which is limited to market data feeds).  This class bridges the gap by
    polling the ``/api/v1/positionbook`` endpoint at a configurable interval
    and detecting net position changes by comparing consecutive snapshots.

    When the WebSocket protocol gains position events this class can be
    extended to subscribe instead of polling — the callback interface remains
    identical.

    Usage::

        watcher = PositionWatcher(account, poll_interval=2.0)
        watcher.on_change(lambda acc_id, snap: print(acc_id, snap))
        watcher.start()
        # ... later ...
        watcher.stop()

    Args:
        account: The ``BrokerAccount`` whose positions are watched.
        poll_interval: Seconds between positionbook polls.
    """

    def __init__(
        self,
        account: BrokerAccount,
        poll_interval: float = 2.0,
    ) -> None:
        self._account = account
        self._poll_interval = max(0.5, poll_interval)
        self._callbacks: list[PositionChangeCallback] = []
        self._last_snapshot: dict[str, dict] = {}  # symbol → position dict
        self._running = False
        self._thread: threading.Thread | None = None
        # Cooperative stop: the poll loop blocks on this event instead of
        # time.sleep() so stop() can wake it instantly. With a plain
        # time.sleep(poll_interval), stop() had to wait the full interval
        # before the loop noticed _running=False, which deadlocked CI
        # whenever tests used poll_interval≥60 (pytest-timeout's SIGALRM
        # can't interrupt CPython's thread.join() reliably on Linux).
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def on_change(self, callback: PositionChangeCallback) -> None:
        """Register a callback invoked on every detected position change.

        Args:
            callback: Callable with signature ``(account_id: str, position: dict) → None``.
                Called once per changed symbol per poll cycle.
        """
        self._callbacks.append(callback)

    def start(self) -> None:
        """Start the background polling thread.

        Safe to call multiple times — subsequent calls are no-ops if already
        running.
        """
        if self._running:
            return
        self._running = True
        self._stop_event.clear()  # Reset in case the watcher is restarted.
        self._thread = threading.Thread(
            target=self._poll_loop,
            name=f"pos-watcher-{self._account.account_id}",
            daemon=True,
        )
        self._thread.start()
        logger.info("PositionWatcher started for %s", self._account.account_id)

    def stop(self) -> None:
        """Signal the polling thread to stop and wait for it to exit."""
        self._running = False
        self._stop_event.set()  # Wake the loop immediately.
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=self._poll_interval * 2 + 1)
        self._thread = None
        logger.info("PositionWatcher stopped for %s", self._account.account_id)

    @property
    def is_running(self) -> bool:
        """True if the watcher thread is active."""
        return self._running and bool(self._thread and self._thread.is_alive())

    # ------------------------------------------------------------------
    # Internal polling
    # ------------------------------------------------------------------

    def _poll_loop(self) -> None:
        """Background loop: poll positionbook and detect changes.

        Blocks on ``_stop_event.wait(timeout=poll_interval)`` rather than
        ``time.sleep`` so that ``stop()`` can wake the loop immediately —
        otherwise a watcher created with a large poll interval (e.g. 60 s
        in lifecycle tests) would force ``stop()`` to wait the full
        interval before the thread observed the stop signal and exited.
        """
        while not self._stop_event.is_set():
            try:
                self._poll_once()
            except Exception as exc:
                logger.warning(
                    "PositionWatcher poll error for %s: %s",
                    self._account.account_id,
                    exc,
                )
            # Returns True if event was set (stop requested), False on timeout
            # (continue polling). Either way the next while-check handles it.
            self._stop_event.wait(timeout=self._poll_interval)

    def _poll_once(self) -> None:
        """Fetch current positionbook and compare with the last snapshot."""
        url = f"{self._account.openalgo_host.rstrip('/')}/api/v1/positionbook"
        payload = {"apikey": self._account.api_key}

        with httpx.Client(timeout=10.0) as http:
            resp = http.post(url, json=payload)
            if resp.status_code != 200:
                logger.debug(
                    "positionbook HTTP %d for %s",
                    resp.status_code,
                    self._account.account_id,
                )
                return

        data = resp.json()
        if not isinstance(data, dict):
            return

        positions: list[dict] = data.get("data", []) or []
        current: dict[str, dict] = {
            pos["tradingsymbol"]: pos
            for pos in positions
            if isinstance(pos, dict) and "tradingsymbol" in pos
        }

        changed = self._detect_changes(current)
        self._last_snapshot = current

        for symbol, pos in changed.items():
            for cb in self._callbacks:
                try:
                    cb(self._account.account_id, pos)
                except Exception as exc:
                    logger.error("PositionWatcher callback error: %s", exc)

    def _detect_changes(
        self, current: dict[str, dict]
    ) -> dict[str, dict]:
        """Return positions whose net quantity changed since the last poll.

        A new symbol or a symbol whose ``netqty`` field changed is reported.
        Symbols that disappeared (closed positions) are also reported with
        their last known state.

        Args:
            current: Latest positionbook snapshot keyed by tradingsymbol.

        Returns:
            Dict of changed/new positions keyed by tradingsymbol.
        """
        changed: dict[str, dict] = {}

        # New or changed positions
        for symbol, pos in current.items():
            prev = self._last_snapshot.get(symbol)
            if prev is None:
                changed[symbol] = pos
            else:
                prev_qty = prev.get("netqty", prev.get("net_qty", 0))
                curr_qty = pos.get("netqty", pos.get("net_qty", 0))
                if prev_qty != curr_qty:
                    changed[symbol] = pos

        # Positions that were closed (disappeared from current snapshot)
        for symbol, pos in self._last_snapshot.items():
            if symbol not in current:
                closed = dict(pos)
                closed["netqty"] = 0
                changed[symbol] = closed

        return changed


class PositionMirror:
    """Mirror orders from master to slave accounts in parallel.

    Usage::

        mirror = PositionMirror(accounts, mode=AllocationMode.WEIGHTED)
        result = mirror.execute(master_order)
        print(f"{result.successful}/{result.total_accounts} succeeded")

    Multiplier mode example::

        config = MirrorConfig(
            mode=AllocationMode.MULTIPLIER,
            multiplier=1.0,
            account_multipliers={"acc_family": 2.0},
        )
        mirror = PositionMirror(accounts, mirror_config=config)
        result = mirror.execute(master_order)
        # acc_family receives 2× master quantity; others receive 1×.
    """

    def __init__(
        self,
        accounts: list[BrokerAccount] | None = None,
        mode: AllocationMode | str = AllocationMode.EQUAL,
        max_workers: int = 5,
        mirror_config: MirrorConfig | None = None,
        broker_router: Any | None = None,
        actor_id: str = "ditto",
        trading_mode: str = "live",
    ) -> None:
        self._accounts = accounts or []
        self._mode = mode
        self._max_workers = max_workers
        self._mirror_config = mirror_config
        self._history: list[MirrorResult] = []
        # The operator's three-mode trading state (live/practice/explore) — NOT
        # the AllocationMode above. The gated dispatch targets a live OpenAlgo
        # account directly (it does not consult the Practice SandboxEngine), so a
        # non-live mode fails closed rather than routing a paper mirror to a live
        # broker. Threaded from the caller's session; defaults to "live" because
        # a mirror is inherently a live-account feature.
        self._trading_mode = trading_mode
        # Every mirrored order dispatches through the safety-gated BrokerRouter
        # (G6): gate_order -> router.place_order (account-bound HMAC + ACL +
        # one-shot consume). There is NO ungated path — without an injected
        # router the mirror fails closed per account (the raw-httpx fallback was
        # retired 2026-07-04; contract §8.1). ``actor_id`` must be authorised in
        # workspace.json.brokers.account_acls for each openalgo:<account_id>
        # the mirror targets.
        self._broker_router = broker_router
        self._actor_id = actor_id

    @property
    def history(self) -> list[MirrorResult]:
        return list(self._history)

    def set_accounts(self, accounts: list[BrokerAccount]) -> None:
        self._accounts = accounts

    def execute(
        self,
        order: Order,
        accounts: list[BrokerAccount] | None = None,
        mode: AllocationMode | str | None = None,
        available_margins: dict[str, float] | None = None,
        price_per_unit: float = 0.0,
        mirror_config: MirrorConfig | None = None,
    ) -> MirrorResult:
        """Mirror a master order across all target accounts in parallel.

        Args:
            order: The master order to mirror.
            accounts: Override the instance-level account list for this call.
            mode: Override the instance-level allocation mode for this call.
            available_margins: Margin available per account (MARGIN_AWARE mode).
            price_per_unit: Current instrument price (MARGIN_AWARE mode).
            mirror_config: Override the instance-level ``MirrorConfig`` for
                this call.  If ``mode`` is ``AllocationMode.MULTIPLIER`` and
                no config is provided the instance-level config is used; if
                that is also absent a global multiplier of 1.0 is assumed
                (equivalent to EQUAL mode).

        Returns:
            ``MirrorResult`` summarising the outcome for all accounts.
        """
        target_accounts = accounts or self._accounts
        use_mode = mode or (
            self._mirror_config.mode
            if self._mirror_config and mode is None
            else self._mode
        )
        cfg = mirror_config or self._mirror_config
        now = datetime.now(IST).isoformat()

        # Filter to enabled accounts only
        enabled = [a for a in target_accounts if a.enabled and not a.is_master]

        master_qty = int(order.quantity)

        # Choose allocation strategy
        mode_val = use_mode.value if isinstance(use_mode, AllocationMode) else use_mode
        if mode_val == AllocationMode.MULTIPLIER.value:
            effective_cfg = cfg or MirrorConfig(mode=AllocationMode.MULTIPLIER)
            allocation = compute_multiplier_allocation(master_qty, enabled, effective_cfg)
        else:
            allocation = compute_allocation(
                master_qty, enabled, use_mode,
                symbol=order.symbol,
                available_margins=available_margins,
                price_per_unit=price_per_unit,
            )

        result = MirrorResult(
            master_order=order,
            allocation_mode=use_mode.value if isinstance(use_mode, AllocationMode) else use_mode,
            total_accounts=len(enabled),
            timestamp=now,
        )

        # Execute in parallel using ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            futures = {}
            for acc in enabled:
                qty = allocation.get(acc.account_id, 0)
                if qty <= 0:
                    result.skipped += 1
                    result.results.append(MirrorOrderResult(
                        account_id=acc.account_id,
                        error="Zero allocation — skipped",
                    ))
                    continue
                futures[pool.submit(self._place_on_account, order, acc, qty)] = acc.account_id

            for future in as_completed(futures):
                acc_id = futures[future]
                try:
                    order_result = future.result()
                    result.results.append(order_result)
                    if order_result.success:
                        result.successful += 1
                    else:
                        result.failed += 1
                except Exception as exc:
                    result.failed += 1
                    result.results.append(MirrorOrderResult(
                        account_id=acc_id, error=str(exc),
                    ))

        self._history.append(result)
        logger.info(
            "Mirror: %s %s qty=%d mode=%s → %d ok, %d fail, %d skip",
            order.action, order.symbol, master_qty,
            result.allocation_mode, result.successful, result.failed, result.skipped,
        )
        return result

    def _place_on_account(
        self,
        order: Order,
        account: BrokerAccount,
        quantity: int,
    ) -> MirrorOrderResult:
        """Place an order on a single account through the gated router.

        Dispatches through ``gate_order`` -> ``BrokerRouter.place_order`` (G6).
        Without an injected router this fails closed — there is no ungated
        path (contract §8.1; the raw OpenAlgo httpx POST was retired
        2026-07-04).
        """
        result = MirrorOrderResult(
            account_id=account.account_id,
            quantity_sent=quantity,
        )

        if self._broker_router is None:
            result.error = (
                "ungated mirroring is not supported — inject a broker_router so "
                "every mirrored order traverses gate_order -> BrokerRouter"
            )
            logger.error(
                "Mirror to %s refused — no broker_router (fails closed, §8.1)",
                account.account_id,
            )
            return result

        return self._place_via_router(order, account, quantity, result)

    def _place_via_router(
        self,
        order: Order,
        account: BrokerAccount,
        quantity: int,
        result: MirrorOrderResult,
    ) -> MirrorOrderResult:
        """Dispatch one mirrored order through the safety-gated BrokerRouter (G6).

        Each account resolves to the ``openalgo:<account_id>`` selector; the
        router's AuthenticatingSessionProvider checks ``self._actor_id`` against
        ``account_acls`` and verifies the account-bound SafetyContext before the
        OpenAlgo bridge adapter places the order.
        """
        import asyncio  # noqa: PLC0415
        import uuid  # noqa: PLC0415

        from flinttrade_core.exceptions import BrokerError, SafetyBypassError  # noqa: PLC0415
        from flinttrade_engine.request_context import RequestContext  # noqa: PLC0415
        from flinttrade_engine.safety import gate_order  # noqa: PLC0415
        from flinttrade_gateway.routing_config import RoutingHint  # noqa: PLC0415

        # Fail closed on a non-live operator mode. This path dispatches straight
        # to a live OpenAlgo account and never routes to the Practice
        # SandboxEngine, so honouring a "practice"/"explore" mode here would send
        # a paper mirror to a live broker — refuse instead.
        if self._trading_mode != "live":
            result.error = (
                f"Mirror refused: operator mode is {self._trading_mode!r}, not 'live'. "
                "The gated mirror dispatch is live-account only."
            )
            logger.warning(
                "Mirror to %s refused: non-live operator mode %r",
                account.account_id,
                self._trading_mode,
            )
            return result

        try:
            mirror_order = order.model_copy(update={"quantity": quantity})
        except AttributeError:
            mirror_order = order

        request_ctx = RequestContext(
            jti=f"ditto-{uuid.uuid4().hex}",
            actor_type="agent",
            actor_id=self._actor_id,
            mode=self._trading_mode,
            selector=f"openalgo:{account.account_id}",
        )
        try:
            safety_ctx = gate_order(
                mirror_order, request_ctx, adapter_id="openalgo", account_id=account.account_id
            )
            broker_order_id = asyncio.run(
                self._broker_router.place_order(
                    request_ctx,
                    order=mirror_order,
                    safety_ctx=safety_ctx,
                    hint=RoutingHint(adapter_id="openalgo", account_id=account.account_id),
                )
            )
            result.success = True
            result.order_response = OrderResponse(status="success", orderid=str(broker_order_id or ""))
        except (SafetyBypassError, BrokerError) as exc:
            result.error = str(exc)
            logger.warning("Mirror (gated) to %s refused: %s", account.account_id, exc)
        except Exception as exc:  # pragma: no cover - defensive
            result.error = str(exc)
            logger.error("Mirror (gated) to %s failed: %s", account.account_id, exc)
        return result
