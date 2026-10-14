"""Opt-in adapters borrow configured secret/service owners; no secret store here."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from flask import Flask

TITLE = "FlintTrade critical incident"
BODY = "Open System for retained evidence. Root cause unconfirmed."


def binding_digest(values: Sequence[str | int]) -> str:
    return hashlib.sha256(json.dumps(values, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


class IncidentSender(Protocol):
    def incident_binding(self, provider: str, recipient: str) -> str: ...

    def send_incident(self, provider: str, recipient: str, expected: str, title: str, body: str) -> str: ...


@dataclass(frozen=True)
class ConfiguredAlertBinding:
    app: Flask
    channel: str
    provider: str
    recipient: str
    owner: IncidentSender

    def fingerprint(self) -> str | None:
        from . import auth_routes
        current = self.app.config.get("TELEGRAM_BOT") if self.channel == "telegram" else auth_routes._email_transport
        if current is not self.owner:
            return None
        try:
            return self.owner.incident_binding(self.provider, self.recipient)
        except (ValueError, TypeError):
            return None

    def send(self, expected: str) -> str:
        if self.fingerprint() != expected:
            return "revoked"
        return self.owner.send_incident(self.provider, self.recipient, expected, TITLE, BODY)


def configured_binding(app: Flask, channel: str, provider: str, recipient: str) -> ConfiguredAlertBinding:
    from . import auth_routes
    if channel not in ("telegram", "email") or type(recipient) is not str or not 1 <= len(recipient) <= 254:
        raise ValueError("explicit configured destination required")
    if any(c in recipient for c in "\r\n\t"):
        raise ValueError("invalid recipient")
    owner = app.config.get("TELEGRAM_BOT") if channel == "telegram" else auth_routes._get_email_transport()
    if owner is None:
        raise ValueError("existing configured service owner required")
    result = ConfiguredAlertBinding(app, channel, provider, recipient, owner)
    if not result.fingerprint():
        raise ValueError("exact configured destination required")
    return result
