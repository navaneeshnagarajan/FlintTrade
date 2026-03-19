"""Position mirroring — replicate master orders across slave accounts.

Allocation modes:
1. Equal: same qty to all accounts
2. Weighted: proportional to account allocation weight
3. Margin-aware: calculate available margin, size accordingly
4. Lot-based: round to nearest lot size per account

Uses ThreadPoolExecutor for parallel execution across accounts
(absorbs AlgoMirror's strategy_executor.py pattern).
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import StrEnum

import httpx

from packages.core.src.models import Order, OrderResponse

from .account_manager import BrokerAccount

logger = logging.getLogger("flinttrade.ditto.mirror")

IST = timezone(timedelta(hours=5, minutes=30))


class AllocationMode(StrEnum):
    EQUAL = "EQUAL"
    WEIGHTED = "WEIGHTED"
    MARGIN_AWARE = "MARGIN_AWARE"
    LOT_BASED = "LOT_BASED"


# Lot sizes for F&O instruments
LOT_SIZES: dict[str, int] = {
    "NIFTY": 75, "BANKNIFTY": 30, "FINNIFTY": 40, "MIDCPNIFTY": 50,
    "SENSEX": 20, "BANKEX": 30, "SENSEX50": 25,
    "USDINR": 1000, "EURINR": 1000,
    "CRUDEOIL": 100, "GOLD": 100, "GOLDM": 10,
    "SILVER": 30, "SILVERM": 5, "NATURALGAS": 1250,
}


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

    return result


def _get_lot_size(symbol: str) -> int:
    """Determine lot size from symbol name."""
    sym = symbol.upper()
    for key, size in LOT_SIZES.items():
        if key in sym:
            return size
    return 1


class PositionMirror:
    """Mirror orders from master to slave accounts in parallel.

    Usage::

        mirror = PositionMirror(accounts, mode=AllocationMode.WEIGHTED)
        result = mirror.execute(master_order)
        print(f"{result.successful}/{result.total_accounts} succeeded")
    """

    def __init__(
        self,
        accounts: list[BrokerAccount] | None = None,
        mode: AllocationMode | str = AllocationMode.EQUAL,
        max_workers: int = 5,
    ) -> None:
        self._accounts = accounts or []
        self._mode = mode
        self._max_workers = max_workers
        self._history: list[MirrorResult] = []

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
    ) -> MirrorResult:
        """Mirror a master order across all target accounts in parallel."""
        target_accounts = accounts or self._accounts
        use_mode = mode or self._mode
        now = datetime.now(IST).isoformat()

        # Filter to enabled accounts only
        enabled = [a for a in target_accounts if a.enabled and not a.is_master]

        master_qty = int(order.quantity)
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

    @staticmethod
    def _place_on_account(
        order: Order,
        account: BrokerAccount,
        quantity: int,
    ) -> MirrorOrderResult:
        """Place an order on a single account's OpenAlgo instance."""
        result = MirrorOrderResult(
            account_id=account.account_id,
            quantity_sent=quantity,
        )

        action = order.action.value if hasattr(order.action, "value") else str(order.action)
        exchange = order.exchange.value if hasattr(order.exchange, "value") else str(order.exchange)
        pricetype = order.pricetype.value if hasattr(order.pricetype, "value") else str(order.pricetype)
        product = order.product.value if hasattr(order.product, "value") else str(order.product)

        url = f"{account.openalgo_host.rstrip('/')}/api/v1/placeorder"
        payload = {
            "apikey": account.api_key,
            "strategy": order.strategy,
            "symbol": order.symbol,
            "action": action,
            "exchange": exchange,
            "pricetype": pricetype,
            "product": product,
            "quantity": str(quantity),
            "price": order.price,
            "trigger_price": order.trigger_price,
            "disclosed_quantity": order.disclosed_quantity,
        }

        try:
            with httpx.Client(timeout=15.0) as http:
                resp = http.post(url, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("status") != "error":
                        result.success = True
                        result.order_response = OrderResponse(**data)
                    else:
                        result.error = data.get("message", "Unknown error")
                else:
                    result.error = f"HTTP {resp.status_code}"
        except Exception as exc:
            result.error = str(exc)
            logger.error("Mirror order to %s failed: %s", account.account_id, exc)

        return result
