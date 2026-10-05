"""FlintTrade integration package — signed webhooks and alerting."""

from flinttrade_core.version import APP_VERSION

__version__ = APP_VERSION

from .alert_trigger_log import AlertTriggerLog, TriggerEvent
from .alerter import Alert, AlertChannel, Alerter, AlertType
from .webhook_receiver import WebhookConfig, WebhookLogEntry, WebhookPayload, WebhookReceiver
from .webhook_routes import init_webhook_routes, webhook_bp
from .webhook_secret_store import WebhookSecretStore

__all__ = [
    # Alerter
    "Alerter",
    "Alert",
    "AlertType",
    "AlertChannel",
    # Alert trigger log
    "AlertTriggerLog",
    "TriggerEvent",
    # Webhook receiver
    "WebhookConfig",
    "WebhookLogEntry",
    "WebhookPayload",
    "WebhookReceiver",
    "WebhookSecretStore",
    "init_webhook_routes",
    "webhook_bp",
]
