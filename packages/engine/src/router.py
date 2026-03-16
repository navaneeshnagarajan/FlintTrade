"""Order router — runs orders through safety layers, then dispatches to OpenAlgo."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from packages.core.src.models import Order, OrderResponse, Position
from packages.core.src.openalgo_client import OpenAlgoClient

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

    Usage::

        router = OrderRouter(client=client, safety=safety)
        decision = router.route(order, ltp=2500.0, positions=positions, ...)
        if decision.passed:
            print(f"Order placed: {decision.order_response.orderid}")
        else:
            print(f"Blocked by: {decision.blocking_layers()}")
    """

    def __init__(
        self,
        client: OpenAlgoClient,
        safety: SafetySystem | None = None,
        strategy_configs: dict[str, StrategyRouteConfig] | None = None,
    ) -> None:
        self.client = client
        self.safety = safety or SafetySystem()
        self._strategy_configs = strategy_configs or {}
        self._history: list[RoutingDecision] = []

    @property
    def history(self) -> list[RoutingDecision]:
        return list(self._history)

    def add_strategy_config(self, config: StrategyRouteConfig) -> None:
        self._strategy_configs[config.strategy_name] = config

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
        """Run the order through safety, then place it if all layers pass."""
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

        # Place order via OpenAlgo
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
