"""FlintTrade automation package — cron, Telegram, OpenClaw, post-market, n8n, flows."""

__version__ = "0.1.0-alpha"

from .cron_manager import CronManager, JobDefinition, JobHistory, JobStatus
from .n8n_bridge import N8nBridge, N8nBridgeError
from .openclaw_bridge import OpenClawBridge, OpenClawConfig, Skill, SkillResult
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
    # OpenClaw
    "OpenClawBridge",
    "OpenClawConfig",
    "Skill",
    "SkillResult",
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
