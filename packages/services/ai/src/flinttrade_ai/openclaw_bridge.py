"""Bridge to the OpenClaw AI agent gateway.

OpenClaw is an external service — it is NOT bundled with FlintTrade. This
bridge makes HTTP calls to a running OpenClaw instance and never imports
its code. For local development, contributors can clone OpenClaw to
``.local/external/openclaw/`` via ``scripts/setup-test-deps.sh``; production
deployments install OpenClaw separately.

Usage::

    bridge = OpenClawBridge()
    if bridge.check_health():
        result = bridge.deploy_agent({
            "name": "scalper-nifty",
            "strategy": "momentum",
            "symbols": ["NIFTY"],
        })
        print(result)

    agents = bridge.list_agents()
    bridge.stop_agent(agents[0]["id"])
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger("flinttrade.ai.openclaw_bridge")

_DEFAULT_TIMEOUT = 10.0
_AGENT_CONTROL_UNSUPPORTED_CODE = "openclaw_agent_control_unsupported"
_AGENT_CONTROL_UNSUPPORTED_MESSAGE = (
    "This bridge does not use OpenClaw's removed /api/agents HTTP lifecycle "
    "contract. Use the OpenClaw CLI or gateway session controls for agent runs."
)


@dataclass
class OpenClawAgent:
    """Snapshot of an OpenClaw agent."""

    agent_id: str = ""
    name: str = ""
    status: str = "stopped"
    strategy: str = ""
    symbols: list[str] = field(default_factory=list)
    created_at: str = ""
    last_action: str = ""


class OpenClawBridge:
    """Bridge to OpenClaw AI agent sessions.

    All methods are synchronous HTTP calls via ``httpx``.  Connection errors
    are caught and returned as error dicts so callers never see raw exceptions.

    Args:
        host: Base URL of the running OpenClaw instance.
        timeout: HTTP timeout in seconds.
    """

    def __init__(
        self,
        host: str = "http://127.0.0.1:18789",
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self.host = host.rstrip("/")
        self._timeout = timeout
        self._connected = False
        self.agent_control_supported = False
        self.agent_control_message = _AGENT_CONTROL_UNSUPPORTED_MESSAGE

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def check_health(self) -> bool:
        """Check if OpenClaw is running and reachable.

        Returns:
            ``True`` if the service responds with HTTP 200, else ``False``.
        """
        try:
            with httpx.Client(timeout=self._timeout) as client:
                for endpoint in ("/healthz", "/health"):
                    resp = client.get(f"{self.host}{endpoint}")
                    if resp.status_code == 200:
                        self._connected = True
                        return True
                    if endpoint == "/healthz" and resp.status_code == 404:
                        continue
                    break
                self._connected = False
                return False
        except (httpx.ConnectError, httpx.TimeoutException, OSError) as exc:
            logger.debug("OpenClaw health check failed: %s", exc)
            self._connected = False
            return False

    # ------------------------------------------------------------------
    # Agent management
    # ------------------------------------------------------------------

    def deploy_agent(self, agent_config: dict) -> dict:
        """Deploy a trading agent via OpenClaw.

        Args:
            agent_config: Dict with agent configuration.  Expected keys:
                ``name`` (str), ``strategy`` (str), ``symbols`` (list[str]).
                Additional provider-specific keys are passed through.

        Returns:
            Response dict with ``status`` and ``agent_id`` on success.
        """
        return {
            "status": "error",
            "code": _AGENT_CONTROL_UNSUPPORTED_CODE,
            "message": _AGENT_CONTROL_UNSUPPORTED_MESSAGE,
        }

    def list_agents(self) -> list[dict]:
        """List all running agents on OpenClaw.

        Returns:
            List of agent dicts, each containing ``id``, ``name``,
            ``status``, ``strategy``, ``symbols``, ``created_at``.
            Returns an empty list on connection failure.
        """
        return []

    def stop_agent(self, agent_id: str) -> dict:
        """Stop a running agent.

        Args:
            agent_id: The agent ID returned by ``deploy_agent``.

        Returns:
            Response dict with ``status`` and stop details.
        """
        return {
            "status": "error",
            "code": _AGENT_CONTROL_UNSUPPORTED_CODE,
            "message": _AGENT_CONTROL_UNSUPPORTED_MESSAGE,
        }

    def get_agent_logs(self, agent_id: str) -> list[str]:
        """Get logs for a specific agent.

        Args:
            agent_id: The agent ID to fetch logs for.

        Returns:
            List of log line strings.  Returns empty list on failure.
        """
        return []

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        """Whether the last health check succeeded."""
        return self._connected
