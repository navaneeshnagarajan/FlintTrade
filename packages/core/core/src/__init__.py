"""FlintTrade core package — config, client, models, exceptions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

__version__ = "0.1.0-alpha"

from .config import FlintTradeConfig, Settings
from .workspace import Workspace
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
from .system_metrics import SystemMetrics, get_system_metrics

# Lazy import for FlintTradeApp so that `python -m flinttrade_core.app`
# does not import .app through this __init__ before it has finished
# executing (which triggered a "RuntimeWarning: ... found in sys.modules
# after import of package ..." + duplicate initialisation log lines).
if TYPE_CHECKING:
    from .app import FlintTradeApp


def __getattr__(name: str) -> Any:
    if name == "FlintTradeApp":
        from .app import FlintTradeApp as _FlintTradeApp  # noqa: PLC0415
        return _FlintTradeApp
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    # App
    "FlintTradeApp",
    # System metrics
    "SystemMetrics",
    "get_system_metrics",
    # Client
    "OpenAlgoClient",
    # Config
    "Settings",
    "FlintTradeConfig",
    "Workspace",
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
