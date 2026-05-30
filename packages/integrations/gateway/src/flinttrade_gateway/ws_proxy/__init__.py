"""FlintTrade WebSocket proxy — broker-native tick fan-out.

Public surface:
    WSProxyServer      — main server class (start / stop / add_broker / stats)
    ClientManager      — client connection + subscription registry
    AbstractBrokerAdapter — base class for all broker WS adapters
    MockBrokerAdapter  — synthetic-tick adapter for testing
    TickRouter         — fan-out engine (subscribe / unsubscribe / route)
    validate_api_key   — API key validation helper
"""

from .broker_adapter import AbstractBrokerAdapter
from .client_manager import ClientManager, ClientSession
from .mock_adapter import MockBrokerAdapter
from .router import TickRouter
from .server import WSProxyServer
from .auth import validate_api_key

__all__ = [
    "WSProxyServer",
    "ClientManager",
    "ClientSession",
    "AbstractBrokerAdapter",
    "MockBrokerAdapter",
    "TickRouter",
    "validate_api_key",
]
