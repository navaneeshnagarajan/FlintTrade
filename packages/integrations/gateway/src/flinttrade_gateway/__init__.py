"""FlintTrade gateway package — broker connections, adapters, registry, credentials, WebSocket bridge.

The package root intentionally exposes only the canonical broker surfaces:

* :class:`flinttrade_gateway.registry.BrokerRegistry` for session lookup.
* :class:`flinttrade_gateway.brokers._base.BrokerAdapter` for adapter contracts.
* :class:`flinttrade_gateway.brokers.openalgo.OpenAlgoAdapter` for OpenAlgo bridge sessions.
* domain models from :mod:`flinttrade_core.models`.

Do not add sync order-write adapters here. Every broker write must go through
``gate_order()`` → ``BrokerRouter`` → an async ``BrokerAdapter``.
"""

from flinttrade_core.models import Fund, Holding, Order, OrderResponse, Position, Quote

from .brokers._base import BrokerAdapter, Session
from .brokers.openalgo import OpenAlgoAdapter
from .models import (
    AccountStatus,
    AuthFlowType,
    AuthMethod,
    AuthMethodField,
    BrokerAccountInfo,
    BrokerInfo,
    BrokerMCPInfo,
    MCPClientConfig,
)
from .registry import BrokerRegistry

__all__ = [
    # Canonical adapter/session surfaces
    "BrokerAdapter",
    "BrokerRegistry",
    "OpenAlgoAdapter",
    "Session",
    # Gateway catalogue/runtime models
    "AccountStatus",
    "AuthFlowType",
    "AuthMethod",
    "AuthMethodField",
    "BrokerAccountInfo",
    "BrokerInfo",
    "BrokerMCPInfo",
    "MCPClientConfig",
    # Canonical trading/domain models
    "Fund",
    "Holding",
    "Order",
    "OrderResponse",
    "Position",
    "Quote",
]
