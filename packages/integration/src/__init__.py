"""FlintTrade integration package — webhooks, flow builder, alerting."""

__version__ = "0.1.0-alpha"

from .alerter import Alert, AlertChannel, Alerter, AlertType
from .chartink import ChartInkConfig, ChartInkScanResult, ChartInkWebhook
from .flow_builder import (
    ActionType,
    ConditionType,
    ExitType,
    FlowBuilder,
    FlowDefinition,
    FlowNode,
    NodeType,
    SignalSource,
    ValidationResult,
)
from .tradingview import TradingViewAlert, TradingViewWebhook
from .webhook_server import WebhookServer

__all__ = [
    # TradingView
    "TradingViewWebhook",
    "TradingViewAlert",
    # ChartInk
    "ChartInkWebhook",
    "ChartInkScanResult",
    "ChartInkConfig",
    # Webhook server
    "WebhookServer",
    # Flow builder
    "FlowBuilder",
    "FlowDefinition",
    "FlowNode",
    "NodeType",
    "SignalSource",
    "ConditionType",
    "ActionType",
    "ExitType",
    "ValidationResult",
    # Alerter
    "Alerter",
    "Alert",
    "AlertType",
    "AlertChannel",
]
