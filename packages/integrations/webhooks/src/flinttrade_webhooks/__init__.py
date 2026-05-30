"""FlintTrade integration package — webhooks, flow builder, alerting, Excel."""

from flinttrade_core.version import APP_VERSION

__version__ = APP_VERSION

from .alert_trigger_log import AlertTriggerLog, TriggerEvent
from .alerter import Alert, AlertChannel, Alerter, AlertType
from .chartink import (
    ChartInkConfig,
    ChartInkPlacementResult,
    ChartInkScanResult,
    ChartInkWebhook,
)
from .excel_bridge import ExcelBridge, ExcelBridgeError
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
from .voice_orders import VoiceCommand, VoiceOrderParser, voice_bp
from .webhook_server import WebhookServer
from .webhook_receiver import WebhookConfig, WebhookLogEntry, WebhookPayload, WebhookReceiver
from .webhook_routes import init_webhook_routes, webhook_bp

__all__ = [
    # TradingView
    "TradingViewWebhook",
    "TradingViewAlert",
    # ChartInk
    "ChartInkWebhook",
    "ChartInkScanResult",
    "ChartInkConfig",
    "ChartInkPlacementResult",
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
    # Alert trigger log
    "AlertTriggerLog",
    "TriggerEvent",
    # Voice orders
    "VoiceOrderParser",
    "VoiceCommand",
    "voice_bp",
    # Excel
    "ExcelBridge",
    "ExcelBridgeError",
    # Webhook receiver
    "WebhookConfig",
    "WebhookLogEntry",
    "WebhookPayload",
    "WebhookReceiver",
    "init_webhook_routes",
    "webhook_bp",
]
