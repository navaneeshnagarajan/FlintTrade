"""FlintTrade automation package — cron, Telegram, post-market, n8n, flows."""

from flinttrade_core.version import APP_VERSION

__version__ = APP_VERSION

from .cron_manager import CronManager, JobDefinition, JobHistory, JobStatus
from .n8n_bridge import N8nBridge, N8nBridgeError
from .post_market import (
    DailyReport,
    PostMarketAnalysis,
    StrategyPerformance,
    TradeEntry,
)
from .telegram_bot import BotConfig, CommandResult, TelegramBot
from .totp_login import LoginResult, is_trading_day
from .whatsapp_alerts import WhatsAppAlerter, WhatsAppConfig
from .whatsapp_alerter import AlertRouter, AlertRouterConfig, WhatsAppAlerter as WhatsAppBridgeAlerter
from .flows import FlowDefinition, FlowError, FlowManager
from .flow_nodes import (
    AlertNode,
    AndGate,
    DelayNode,
    FlowContext,
    FlowExecutor,
    FlowNode,
    FlowResult,
    HTTPRequestNode,
    IfThenElseNode,
    MathNode,
    NotGate,
    OrderNode,
    OrGate,
    SwitchNode,
    XorGate,
)

__all__ = [
    # Trading day utilities (retained from totp_login)
    "LoginResult",
    "is_trading_day",
    # Cron
    "CronManager",
    "JobDefinition",
    "JobHistory",
    "JobStatus",
    # Telegram
    "TelegramBot",
    "BotConfig",
    "CommandResult",
    # Post-market
    "PostMarketAnalysis",
    "DailyReport",
    "TradeEntry",
    "StrategyPerformance",
    # WhatsApp (webhook-based)
    "WhatsAppAlerter",
    "WhatsAppConfig",
    # WhatsApp (wabridge sidecar)
    "WhatsAppBridgeAlerter",
    "AlertRouter",
    "AlertRouterConfig",
    # n8n
    "N8nBridge",
    "N8nBridgeError",
    # Flows
    "FlowManager",
    "FlowDefinition",
    "FlowError",
    # Flow nodes
    "FlowNode",
    "FlowContext",
    "FlowResult",
    "FlowExecutor",
    "AndGate",
    "OrGate",
    "NotGate",
    "XorGate",
    "DelayNode",
    "HTTPRequestNode",
    "IfThenElseNode",
    "SwitchNode",
    "MathNode",
    "AlertNode",
    "OrderNode",
]
