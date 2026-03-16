"""FlintTrade core package — config, client, models, exceptions."""

__version__ = "0.1.0-alpha"

from .config import Settings
from .exceptions import (
    APIError,
    AuthError,
    ConfigError,
    FlintTradeError,
    RateLimitError,
)
from .models import (
    Action,
    BasketOrder,
    BasketOrderItem,
    Depth,
    DepthLevel,
    Exchange,
    Fund,
    Holding,
    Interval,
    ModifyOrder,
    OHLCV,
    OptionChain,
    OptionChainStrike,
    OptionGreek,
    OptionsLeg,
    OptionsMultiOrder,
    OptionsOrder,
    OptionType,
    Order,
    OrderResponse,
    OrderStatus,
    Position,
    PriceType,
    Product,
    Quote,
    SmartOrder,
    SplitOrder,
    Trade,
)
from .openalgo_client import OpenAlgoClient
from .app import FlintTradeApp

__all__ = [
    # App
    "FlintTradeApp",
    # Client
    "OpenAlgoClient",
    # Config
    "Settings",
    # Exceptions
    "FlintTradeError",
    "APIError",
    "AuthError",
    "RateLimitError",
    "ConfigError",
    # Enums
    "Action",
    "Exchange",
    "PriceType",
    "Product",
    "OptionType",
    "Interval",
    # Order models
    "Order",
    "SmartOrder",
    "OptionsOrder",
    "OptionsLeg",
    "OptionsMultiOrder",
    "BasketOrder",
    "BasketOrderItem",
    "SplitOrder",
    "ModifyOrder",
    # Response models
    "OrderResponse",
    "OrderStatus",
    # Position / Holding / Trade
    "Position",
    "Holding",
    "Trade",
    # Market data
    "Quote",
    "Depth",
    "DepthLevel",
    "OHLCV",
    # Account
    "Fund",
    # Options analytics
    "OptionGreek",
    "OptionChain",
    "OptionChainStrike",
]
