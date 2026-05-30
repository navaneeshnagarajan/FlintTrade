"""FlintTrade gateway package — broker connections, adapters, registry, credentials, WebSocket bridge."""

from .broker_interface import (
    AuthResult,
    BrokerCredentials,
    BrokerInterface,
    BrokerRegistry,
    FundsInfo,
    Holding,
    OpenAlgoBroker,
    Order,
    OrderRequest,
    OrderResponse,
    Position,
    Quote,
)

__all__ = [
    # Protocol + models
    "BrokerInterface",
    "BrokerCredentials",
    "AuthResult",
    "OrderRequest",
    "OrderResponse",
    "Position",
    "Order",
    "Holding",
    "FundsInfo",
    "Quote",
    # Registry + concrete implementation
    "BrokerRegistry",
    "OpenAlgoBroker",
]
