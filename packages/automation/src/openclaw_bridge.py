"""Bridge between FlintTrade and OpenClaw AI agent gateway.

OpenClaw runs on port 18789 (loopback only). This module registers FlintTrade
capabilities as OpenClaw skills, handles heartbeat integration, and forwards
OpenClaw messages to FlintTrade command handlers.

Skills registered:
  /trade    — place orders via natural language
  /analyze  — run screener analysis
  /backtest — run backtest on a strategy
  /status   — system status
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import httpx

logger = logging.getLogger("flinttrade.automation.openclaw")

IST = timezone(timedelta(hours=5, minutes=30))


@dataclass
class OpenClawConfig:
    """OpenClaw connection configuration."""

    host: str = "http://127.0.0.1"
    port: int = 18789
    auth_token: str = ""
    model: str = ""

    @classmethod
    def from_env(cls) -> OpenClawConfig:
        return cls(
            host="http://127.0.0.1",
            port=int(os.getenv("OPENCLAW_PORT", "18789")),
            auth_token=os.getenv("OPENCLAW_AUTH_TOKEN", ""),
            model=os.getenv("OPENCLAW_MODEL", ""),
        )

    @property
    def base_url(self) -> str:
        return f"{self.host}:{self.port}"


@dataclass
class Skill:
    """A FlintTrade skill registered with OpenClaw."""

    name: str
    description: str
    handler: Callable[[str], str] | None = None
    examples: list[str] = field(default_factory=list)


@dataclass
class SkillResult:
    """Result from executing a skill."""

    skill_name: str
    input_text: str = ""
    output: str = ""
    success: bool = False
    error: str = ""


# Default skill definitions
DEFAULT_SKILLS: dict[str, dict[str, Any]] = {
    "trade": {
        "description": "Place trading orders via natural language. Example: 'Buy 100 RELIANCE at market'",
        "examples": [
            "Buy 100 RELIANCE",
            "Sell NIFTY 25000 CE 2 lots",
            "Close all positions",
        ],
    },
    "analyze": {
        "description": "Run market analysis: PCR, max pain, OI spurt, support/resistance.",
        "examples": [
            "Analyze NIFTY option chain",
            "What is the PCR for BANKNIFTY?",
            "Show max pain for NIFTY",
        ],
    },
    "backtest": {
        "description": "Run a backtest on a trading strategy with historical data.",
        "examples": [
            "Backtest EMA crossover on RELIANCE last 1 year",
            "Run Supertrend strategy on NIFTY 5m data",
        ],
    },
    "status": {
        "description": "Get system status: positions, P&L, health, strategies.",
        "examples": [
            "Show my positions",
            "What is today's P&L?",
            "System health check",
        ],
    },
}


class OpenClawBridge:
    """Bridge between FlintTrade and OpenClaw AI agent.

    Usage::

        bridge = OpenClawBridge()
        bridge.register_skill("trade", handler=my_trade_handler)
        bridge.register_skill("status", handler=my_status_handler)
        bridge.sync_skills()  # Register with OpenClaw
        bridge.check_heartbeat()
    """

    def __init__(self, config: OpenClawConfig | None = None) -> None:
        self.config = config or OpenClawConfig.from_env()
        self._skills: dict[str, Skill] = {}
        self._http = httpx.Client(timeout=15.0)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> OpenClawBridge:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Skill registration
    # ------------------------------------------------------------------

    def register_skill(
        self,
        name: str,
        handler: Callable[[str], str],
        description: str = "",
        examples: list[str] | None = None,
    ) -> None:
        """Register a FlintTrade skill."""
        defaults = DEFAULT_SKILLS.get(name, {})
        self._skills[name] = Skill(
            name=name,
            description=description or defaults.get("description", ""),
            handler=handler,
            examples=examples or defaults.get("examples", []),
        )
        logger.info("Registered OpenClaw skill: /%s", name)

    def unregister_skill(self, name: str) -> None:
        self._skills.pop(name, None)

    @property
    def registered_skills(self) -> list[str]:
        return list(self._skills.keys())

    # ------------------------------------------------------------------
    # Skill execution
    # ------------------------------------------------------------------

    def execute_skill(self, name: str, input_text: str) -> SkillResult:
        """Execute a registered skill."""
        skill = self._skills.get(name)
        if not skill or not skill.handler:
            return SkillResult(
                skill_name=name,
                input_text=input_text,
                error=f"Skill '/{name}' not registered",
            )

        try:
            output = skill.handler(input_text)
            return SkillResult(
                skill_name=name,
                input_text=input_text,
                output=output,
                success=True,
            )
        except Exception as exc:
            logger.error("Skill /%s error: %s", name, exc)
            return SkillResult(
                skill_name=name,
                input_text=input_text,
                error=str(exc),
            )

    def handle_message(self, text: str) -> SkillResult:
        """Route an incoming message to the appropriate skill.

        Messages starting with / are routed by command name.
        Other messages are routed to 'trade' skill (natural language).
        """
        text = text.strip()

        if text.startswith("/"):
            parts = text.split(maxsplit=1)
            cmd = parts[0].lstrip("/").lower()
            input_text = parts[1] if len(parts) > 1 else ""
            return self.execute_skill(cmd, input_text)

        # Default to trade skill for free-form text
        return self.execute_skill("trade", text)

    # ------------------------------------------------------------------
    # OpenClaw API interaction
    # ------------------------------------------------------------------

    def sync_skills(self) -> bool:
        """Register all skills with OpenClaw server."""
        url = f"{self.config.base_url}/api/skills"
        skills_payload = [
            {
                "name": s.name,
                "description": s.description,
                "examples": s.examples,
            }
            for s in self._skills.values()
        ]

        try:
            headers = {}
            if self.config.auth_token:
                headers["Authorization"] = f"Bearer {self.config.auth_token}"

            resp = self._http.post(url, json={"skills": skills_payload}, headers=headers)
            if resp.status_code == 200:
                logger.info("Synced %d skills with OpenClaw", len(skills_payload))
                return True
            logger.warning("OpenClaw skill sync failed: HTTP %d", resp.status_code)
            return False
        except Exception as exc:
            logger.error("OpenClaw skill sync error: %s", exc)
            return False

    def check_heartbeat(self) -> bool:
        """Check OpenClaw health via its heartbeat endpoint."""
        url = f"{self.config.base_url}/api/health"
        try:
            headers = {}
            if self.config.auth_token:
                headers["Authorization"] = f"Bearer {self.config.auth_token}"
            resp = self._http.get(url, headers=headers)
            return resp.status_code == 200
        except Exception:
            return False

    def send_status(self, status: dict[str, Any]) -> bool:
        """Push FlintTrade status to OpenClaw for heartbeat monitoring."""
        url = f"{self.config.base_url}/api/status"
        try:
            headers = {"Content-Type": "application/json"}
            if self.config.auth_token:
                headers["Authorization"] = f"Bearer {self.config.auth_token}"

            payload = {
                "service": "flinttrade",
                "timestamp": datetime.now(IST).isoformat(),
                **status,
            }
            resp = self._http.post(url, json=payload, headers=headers)
            return resp.status_code == 200
        except Exception as exc:
            logger.debug("Status push to OpenClaw failed: %s", exc)
            return False
