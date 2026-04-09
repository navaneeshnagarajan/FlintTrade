"""Bridge to n8n workflow automation platform.

n8n is a self-hosted workflow automation tool. This module allows FlintTrade to:
  - Trigger n8n webhook workflows from trading events (order fills, alerts, P&L thresholds)
  - List and manage n8n workflows via the n8n REST API
  - Enable/disable workflows based on market hours or strategy state

Prerequisites:
  - n8n running locally or on network (default: http://127.0.0.1:5678)
  - n8n API key from n8n Settings → API → Create API Key

Webhook usage (no API key needed):
  bridge = N8nBridge()
  bridge.trigger_webhook("abc123", {"symbol": "NIFTY", "action": "BUY"})

Workflow management (API key required):
  bridge = N8nBridge(api_key="your-api-key")
  bridge.list_workflows()
  bridge.activate_workflow("1")
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger("flinttrade.automation.n8n_bridge")


class N8nBridgeError(Exception):
    """Raised when an n8n API call fails."""


class N8nBridge:
    """Bridge to n8n workflow automation platform.

    Supports triggering webhook workflows and managing workflows via n8n's
    REST API. API key is only required for workflow management endpoints;
    webhook triggers are unauthenticated by design (n8n embeds the ID in
    the URL as the secret).

    Args:
        host: n8n base URL, e.g. ``"http://127.0.0.1:5678"``.
        api_key: n8n API key for workflow management. If omitted, falls back to
            the ``N8N_API_KEY`` environment variable.
        timeout: HTTP request timeout in seconds.

    Example::

        bridge = N8nBridge(host="http://127.0.0.1:5678", api_key="your-key")
        if bridge.check_health():
            bridge.trigger_webhook("abc123", {"event": "order_filled", "pnl": 1200})
    """

    def __init__(
        self,
        host: str = "http://127.0.0.1:5678",
        api_key: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.host = host.rstrip("/")
        self.api_key = api_key or os.getenv("N8N_API_KEY", "")
        self._http = httpx.Client(timeout=timeout)

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._http.close()

    def __enter__(self) -> N8nBridge:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _api_headers(self) -> dict[str, str]:
        """Build headers for n8n REST API requests."""
        if not self.api_key:
            raise N8nBridgeError(
                "n8n API key required for workflow management. "
                "Set N8N_API_KEY env var or pass api_key= to N8nBridge()."
            )
        return {"X-N8N-API-KEY": self.api_key, "Content-Type": "application/json"}

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def check_health(self) -> bool:
        """Check if n8n is running and reachable.

        Calls ``GET /healthz`` — the standard n8n health endpoint.

        Returns:
            ``True`` if n8n responds with HTTP 200, ``False`` otherwise.
        """
        url = f"{self.host}/healthz"
        try:
            resp = self._http.get(url)
            return resp.status_code == 200
        except Exception as exc:
            logger.debug("n8n health check failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Webhook trigger (no API key needed)
    # ------------------------------------------------------------------

    def trigger_webhook(self, webhook_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Trigger an n8n webhook workflow.

        Sends a POST request to ``/webhook/<webhook_id>`` with the given payload.
        The webhook ID is the UUID shown in n8n's Webhook node URL, e.g.
        ``https://your-n8n/webhook/abc123-def456-...``.

        Args:
            webhook_id: n8n webhook path ID (the UUID portion after ``/webhook/``).
            data: JSON-serialisable payload to send to the workflow.

        Returns:
            The JSON response from n8n (typically ``{"message": "Workflow was started"}``)
            or an empty dict if the response has no body.

        Raises:
            N8nBridgeError: If the HTTP request fails or n8n returns a non-2xx status.
        """
        url = f"{self.host}/webhook/{webhook_id}"
        try:
            resp = self._http.post(url, json=data)
        except Exception as exc:
            raise N8nBridgeError(f"n8n webhook request failed: {exc}") from exc

        if resp.status_code not in (200, 201):
            raise N8nBridgeError(
                f"n8n webhook {webhook_id} returned HTTP {resp.status_code}: {resp.text[:200]}"
            )

        try:
            result: dict[str, Any] = resp.json()
        except Exception:
            result = {}

        logger.info("n8n webhook triggered: %s → status %d", webhook_id, resp.status_code)
        return result

    # ------------------------------------------------------------------
    # Workflow management (API key required)
    # ------------------------------------------------------------------

    def list_workflows(self) -> list[dict[str, Any]]:
        """List all n8n workflows.

        Calls ``GET /api/v1/workflows``.

        Returns:
            List of workflow objects from n8n (each has ``id``, ``name``,
            ``active``, ``createdAt``, ``updatedAt`` fields).

        Raises:
            N8nBridgeError: If API key is missing or the request fails.
        """
        url = f"{self.host}/api/v1/workflows"
        try:
            resp = self._http.get(url, headers=self._api_headers())
        except Exception as exc:
            raise N8nBridgeError(f"n8n list_workflows request failed: {exc}") from exc

        if resp.status_code != 200:
            raise N8nBridgeError(
                f"n8n list_workflows returned HTTP {resp.status_code}: {resp.text[:200]}"
            )

        body: dict[str, Any] = resp.json()
        workflows: list[dict[str, Any]] = body.get("data", body) if isinstance(body, dict) else body
        logger.debug("n8n list_workflows: %d workflows", len(workflows))
        return workflows

    def activate_workflow(self, workflow_id: str) -> bool:
        """Activate an n8n workflow.

        Calls ``POST /api/v1/workflows/<id>/activate``.

        Args:
            workflow_id: Numeric string ID of the workflow shown in n8n UI.

        Returns:
            ``True`` if activation succeeded, ``False`` otherwise.

        Raises:
            N8nBridgeError: If API key is missing or network request fails.
        """
        url = f"{self.host}/api/v1/workflows/{workflow_id}/activate"
        try:
            resp = self._http.post(url, headers=self._api_headers())
        except Exception as exc:
            raise N8nBridgeError(f"n8n activate_workflow request failed: {exc}") from exc

        if resp.status_code == 200:
            logger.info("n8n workflow %s activated", workflow_id)
            return True

        logger.warning(
            "n8n activate_workflow %s returned HTTP %d", workflow_id, resp.status_code
        )
        return False

    def deactivate_workflow(self, workflow_id: str) -> bool:
        """Deactivate an n8n workflow.

        Calls ``POST /api/v1/workflows/<id>/deactivate``.

        Args:
            workflow_id: Numeric string ID of the workflow shown in n8n UI.

        Returns:
            ``True`` if deactivation succeeded, ``False`` otherwise.

        Raises:
            N8nBridgeError: If API key is missing or network request fails.
        """
        url = f"{self.host}/api/v1/workflows/{workflow_id}/deactivate"
        try:
            resp = self._http.post(url, headers=self._api_headers())
        except Exception as exc:
            raise N8nBridgeError(f"n8n deactivate_workflow request failed: {exc}") from exc

        if resp.status_code == 200:
            logger.info("n8n workflow %s deactivated", workflow_id)
            return True

        logger.warning(
            "n8n deactivate_workflow %s returned HTTP %d", workflow_id, resp.status_code
        )
        return False
