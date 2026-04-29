"""Bridge to AlgoMirror for advanced multi-account position mirroring.

AlgoMirror is an external service — it is NOT bundled with FlintTrade. This
bridge makes HTTP calls to a running AlgoMirror instance and never imports
its code. For local development, contributors can clone AlgoMirror to
``.local/external/algomirror/`` via ``scripts/setup-test-deps.sh``; production
deployments install AlgoMirror separately.

Usage::

    bridge = AlgoMirrorBridge()
    if bridge.check_health():
        bridge.sync_accounts([{"id": "acc1", "api_key": "..."}])
        bridge.start_mirror("acc1", ["acc2", "acc3"], multiplier=1.5)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger("flinttrade.ditto.algomirror_bridge")

_DEFAULT_TIMEOUT = 10.0


@dataclass
class AlgoMirrorStatus:
    """Snapshot of AlgoMirror mirroring status."""

    active: bool = False
    source: str = ""
    targets: list[str] = field(default_factory=list)
    multiplier: float = 1.0
    mirrored_positions: int = 0
    errors: list[str] = field(default_factory=list)


class AlgoMirrorBridge:
    """Bridge to AlgoMirror for advanced multi-account position mirroring.

    All methods are synchronous HTTP calls via ``httpx``.  Connection errors
    are caught and returned as error dicts so callers never see raw exceptions.

    Args:
        host: Base URL of the running AlgoMirror instance.
        timeout: HTTP timeout in seconds.
    """

    def __init__(
        self,
        host: str = "http://127.0.0.1:5200",
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self.host = host.rstrip("/")
        self._timeout = timeout
        self._connected = False

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def check_health(self) -> bool:
        """Check if AlgoMirror is running and reachable.

        Returns:
            ``True`` if the service responds with HTTP 200, else ``False``.
        """
        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.get(f"{self.host}/health")
                self._connected = resp.status_code == 200
                return self._connected
        except (httpx.ConnectError, httpx.TimeoutException, OSError) as exc:
            logger.debug("AlgoMirror health check failed: %s", exc)
            self._connected = False
            return False

    # ------------------------------------------------------------------
    # Account sync
    # ------------------------------------------------------------------

    def sync_accounts(self, accounts: list[dict]) -> dict:
        """Sync account configurations to AlgoMirror.

        Args:
            accounts: List of account dicts, each containing at minimum
                ``id`` and ``api_key``.

        Returns:
            Response dict with ``status`` and optional ``synced_count``.
        """
        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.post(
                    f"{self.host}/api/accounts/sync",
                    json={"accounts": accounts},
                )
                if resp.status_code == 200:
                    return resp.json()
                return {
                    "status": "error",
                    "message": f"HTTP {resp.status_code}",
                }
        except (httpx.ConnectError, httpx.TimeoutException, OSError) as exc:
            logger.warning("AlgoMirror sync_accounts failed: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ------------------------------------------------------------------
    # Mirror control
    # ------------------------------------------------------------------

    def start_mirror(
        self,
        source: str,
        targets: list[str],
        multiplier: float = 1.0,
    ) -> dict:
        """Start position mirroring via AlgoMirror.

        Args:
            source: Account ID of the master account.
            targets: List of slave account IDs.
            multiplier: Quantity multiplier applied to mirrored orders.

        Returns:
            Response dict with ``status`` and mirror session details.
        """
        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.post(
                    f"{self.host}/api/mirror/start",
                    json={
                        "source": source,
                        "targets": targets,
                        "multiplier": multiplier,
                    },
                )
                if resp.status_code == 200:
                    return resp.json()
                return {
                    "status": "error",
                    "message": f"HTTP {resp.status_code}",
                }
        except (httpx.ConnectError, httpx.TimeoutException, OSError) as exc:
            logger.warning("AlgoMirror start_mirror failed: %s", exc)
            return {"status": "error", "message": str(exc)}

    def stop_mirror(self) -> dict:
        """Stop all active mirroring sessions.

        Returns:
            Response dict with ``status`` and stop timestamp.
        """
        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.post(f"{self.host}/api/mirror/stop")
                if resp.status_code == 200:
                    return resp.json()
                return {
                    "status": "error",
                    "message": f"HTTP {resp.status_code}",
                }
        except (httpx.ConnectError, httpx.TimeoutException, OSError) as exc:
            logger.warning("AlgoMirror stop_mirror failed: %s", exc)
            return {"status": "error", "message": str(exc)}

    def get_status(self) -> dict:
        """Get current mirror status from AlgoMirror.

        Returns:
            Response dict with ``status``, ``active``, ``source``,
            ``targets``, ``multiplier``, ``mirrored_positions``, and
            ``errors`` fields.
        """
        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.get(f"{self.host}/api/mirror/status")
                if resp.status_code == 200:
                    return resp.json()
                return {
                    "status": "error",
                    "message": f"HTTP {resp.status_code}",
                }
        except (httpx.ConnectError, httpx.TimeoutException, OSError) as exc:
            logger.debug("AlgoMirror get_status failed: %s", exc)
            return {
                "status": "error",
                "message": str(exc),
                "active": False,
            }

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        """Whether the last health check succeeded."""
        return self._connected
