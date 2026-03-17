"""Order router — runs orders through safety layers, then dispatches to OpenAlgo."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from packages.core.src.models import Order, OrderResponse, Position
from packages.core.src.openalgo_client import OpenAlgoClient
from packages.data.src.audit_logger import AuditLogger

from .safety import SafetyResult, SafetySystem

logger = logging.getLogger("flinttrade.engine.router")


# ---------------------------------------------------------------------------
# Routing decision log entry
# ---------------------------------------------------------------------------


@dataclass
class RoutingDecision:
    """Immutable record of a routing decision."""

    timestamp: str
    order_symbol: str
    order_action: str
    order_exchange: str
    order_quantity: str
    strategy: str
    passed: bool
    safety_results: list[SafetyResult]
    order_response: OrderResponse | None = None
    error: str = ""

    def blocking_layers(self) -> list[SafetyResult]:
        return [r for r in self.safety_results if not r.passed]


# ---------------------------------------------------------------------------
# Strategy routing config
# ---------------------------------------------------------------------------


@dataclass
class StrategyRouteConfig:
    """Per-strategy routing configuration."""

    strategy_name: str
    enabled: bool = True
    # Optional override: route to a different OpenAlgo strategy name
    openalgo_strategy: str = "Flint"


# ---------------------------------------------------------------------------
# OrderRouter
# ---------------------------------------------------------------------------


class OrderRouter:
    """Takes an order, validates through SafetySystem, and routes to OpenAlgo.

    Supports both sync (route) and async (route_order) interfaces.
    When an AuditLogger is provided, all order events are audit-logged.

    Usage::

        router = OrderRouter(client=client, safety=safety)
        decision = router.route(order, ltp=2500.0, positions=positions, ...)

        # Or async with full audit trail:
        router = OrderRouter(
            client=client, safety=safety, audit_logger=auditor,
        )
        decision = await router.route_order(order)
    """

    def __init__(
        self,
        client: OpenAlgoClient | None = None,
        safety: SafetySystem | None = None,
        strategy_configs: dict[str, StrategyRouteConfig] | None = None,
        audit_logger: AuditLogger | None = None,
        # Alternative param names for convenience
        openalgo_client: OpenAlgoClient | None = None,
        safety_system: SafetySystem | None = None,
    ) -> None:
        self.client = client or openalgo_client
        self.safety = safety or safety_system or SafetySystem()
        self.audit = audit_logger
        self._strategy_configs = strategy_configs or {}
        self._history: list[RoutingDecision] = []

    @property
    def history(self) -> list[RoutingDecision]:
        return list(self._history)

    def add_strategy_config(self, config: StrategyRouteConfig) -> None:
        self._strategy_configs[config.strategy_name] = config

    # ------------------------------------------------------------------
    # Sync interface (backwards-compatible, uses mock/sync client)
    # ------------------------------------------------------------------

    def route(
        self,
        order: Order,
        *,
        ltp: float | None = None,
        positions: list[Position] | None = None,
        used_margin: float = 0.0,
        total_balance: float = 0.0,
        net_delta: float = 0.0,
        net_vega: float = 0.0,
        daily_pnl: float = 0.0,
        starting_capital: float = 0.0,
    ) -> RoutingDecision:
        """Run the order through safety, then place it if all layers pass.

        Sync interface — works with mock clients in tests.
        """
        now = datetime.now(timezone.utc).isoformat()

        # Check strategy-level enable/disable
        strategy_cfg = self._strategy_configs.get(order.strategy)
        if strategy_cfg and not strategy_cfg.enabled:
            decision = RoutingDecision(
                timestamp=now,
                order_symbol=order.symbol,
                order_action=order.action.value if hasattr(order.action, "value") else str(order.action),
                order_exchange=order.exchange.value if hasattr(order.exchange, "value") else str(order.exchange),
                order_quantity=order.quantity,
                strategy=order.strategy,
                passed=False,
                safety_results=[],
                error=f"Strategy '{order.strategy}' is disabled",
            )
            self._log_decision(decision)
            return decision

        # Run safety layers
        results = self.safety.check_order(
            order,
            ltp=ltp,
            positions=positions,
            used_margin=used_margin,
            total_balance=total_balance,
            net_delta=net_delta,
            net_vega=net_vega,
            daily_pnl=daily_pnl,
            starting_capital=starting_capital,
        )

        all_passed = all(r.passed for r in results)

        if not all_passed:
            decision = RoutingDecision(
                timestamp=now,
                order_symbol=order.symbol,
                order_action=order.action.value if hasattr(order.action, "value") else str(order.action),
                order_exchange=order.exchange.value if hasattr(order.exchange, "value") else str(order.exchange),
                order_quantity=order.quantity,
                strategy=order.strategy,
                passed=False,
                safety_results=results,
            )
            self._log_decision(decision)
            return decision

        # Apply strategy routing override if configured
        routed_order = order
        if strategy_cfg and strategy_cfg.openalgo_strategy != order.strategy:
            routed_order = order.model_copy(update={"strategy": strategy_cfg.openalgo_strategy})

        # Place order via OpenAlgo (sync — for mock clients in tests)
        order_response: OrderResponse | None = None
        error = ""
        try:
            order_response = self.client.place_order(routed_order)
        except Exception as exc:
            error = str(exc)
            logger.error("Order placement failed for %s: %s", order.symbol, exc)

        decision = RoutingDecision(
            timestamp=now,
            order_symbol=order.symbol,
            order_action=order.action.value if hasattr(order.action, "value") else str(order.action),
            order_exchange=order.exchange.value if hasattr(order.exchange, "value") else str(order.exchange),
            order_quantity=order.quantity,
            strategy=order.strategy,
            passed=not error,
            safety_results=results,
            order_response=order_response,
            error=error,
        )
        self._log_decision(decision)
        return decision

    # ------------------------------------------------------------------
    # Async interface (production — uses async OpenAlgoClient + audit)
    # ------------------------------------------------------------------

    async def route_order(
        self,
        order: Order,
        *,
        ltp: float | None = None,
        positions: list[Position] | None = None,
        used_margin: float = 0.0,
        total_balance: float = 0.0,
        net_delta: float = 0.0,
        net_vega: float = 0.0,
        daily_pnl: float = 0.0,
        starting_capital: float = 0.0,
    ) -> RoutingDecision:
        """Async order routing: safety → audit → broker → audit.

        Full production flow with audit trail.
        """
        now = datetime.now(timezone.utc).isoformat()
        exchange = order.exchange.value if hasattr(order.exchange, "value") else str(order.exchange)
        action = order.action.value if hasattr(order.action, "value") else str(order.action)

        # Check strategy-level enable/disable
        strategy_cfg = self._strategy_configs.get(order.strategy)
        if strategy_cfg and not strategy_cfg.enabled:
            decision = RoutingDecision(
                timestamp=now,
                order_symbol=order.symbol,
                order_action=action,
                order_exchange=exchange,
                order_quantity=order.quantity,
                strategy=order.strategy,
                passed=False,
                safety_results=[],
                error=f"Strategy '{order.strategy}' is disabled",
            )
            self._log_decision(decision)
            return decision

        # Run safety layers
        results = self.safety.check_order(
            order,
            ltp=ltp,
            positions=positions,
            used_margin=used_margin,
            total_balance=total_balance,
            net_delta=net_delta,
            net_vega=net_vega,
            daily_pnl=daily_pnl,
            starting_capital=starting_capital,
        )

        all_passed = all(r.passed for r in results)

        if not all_passed:
            # Audit the safety rejection
            if self.audit:
                blockers = [r for r in results if not r.passed]
                for r in blockers:
                    self.audit.log_safety_check(
                        layer=r.layer,
                        verdict=r.verdict.value,
                        reason=r.reason,
                        symbol=order.symbol,
                        exchange=exchange,
                        strategy=order.strategy,
                    )

            decision = RoutingDecision(
                timestamp=now,
                order_symbol=order.symbol,
                order_action=action,
                order_exchange=exchange,
                order_quantity=order.quantity,
                strategy=order.strategy,
                passed=False,
                safety_results=results,
            )
            self._log_decision(decision)
            return decision

        # Apply strategy routing override
        routed_order = order
        if strategy_cfg and strategy_cfg.openalgo_strategy != order.strategy:
            routed_order = order.model_copy(update={"strategy": strategy_cfg.openalgo_strategy})

        # Audit: log order placed BEFORE sending to broker
        if self.audit:
            pricetype = order.pricetype.value if hasattr(order.pricetype, "value") else str(order.pricetype)
            product = order.product.value if hasattr(order.product, "value") else str(order.product)
            self.audit.log_order_placed(
                strategy=order.strategy,
                symbol=order.symbol,
                exchange=exchange,
                action=action,
                quantity=order.quantity,
                price=order.price,
                pricetype=pricetype,
                product=product,
            )

        # Place order via async OpenAlgo client
        order_response: OrderResponse | None = None
        error = ""
        try:
            order_response = await self.client.place_order(routed_order)
        except Exception as exc:
            error = str(exc)
            logger.error("Order placement failed for %s: %s", order.symbol, exc)

        # Audit: log result after broker confirms
        if self.audit and order_response:
            self.audit.log_event(
                "ORDER_SENT",
                strategy=order.strategy,
                symbol=order.symbol,
                exchange=exchange,
                action=action,
                orderid=order_response.orderid,
                status=order_response.status,
            )

        decision = RoutingDecision(
            timestamp=now,
            order_symbol=order.symbol,
            order_action=action,
            order_exchange=exchange,
            order_quantity=order.quantity,
            strategy=order.strategy,
            passed=not error,
            safety_results=results,
            order_response=order_response,
            error=error,
        )
        self._log_decision(decision)
        return decision

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _log_decision(self, decision: RoutingDecision) -> None:
        self._history.append(decision)
        if decision.passed:
            oid = decision.order_response.orderid if decision.order_response else "N/A"
            logger.info(
                "ORDER PASSED | %s %s %s qty=%s strategy=%s orderid=%s",
                decision.order_action, decision.order_symbol,
                decision.order_exchange, decision.order_quantity,
                decision.strategy, oid,
            )
        else:
            blockers = decision.blocking_layers()
            block_reasons = "; ".join(f"[{r.layer}] {r.reason}" for r in blockers)
            extra = decision.error if decision.error else block_reasons
            logger.warning(
                "ORDER BLOCKED | %s %s %s qty=%s strategy=%s | %s",
                decision.order_action, decision.order_symbol,
                decision.order_exchange, decision.order_quantity,
                decision.strategy, extra,
            )
