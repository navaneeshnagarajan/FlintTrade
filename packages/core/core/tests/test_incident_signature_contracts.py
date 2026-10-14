"""Public incident boundary annotations, independent of private review artifacts."""

from __future__ import annotations

import inspect

import pytest

pytestmark = pytest.mark.unit


def test_public_incident_signatures_are_annotated():
    from flinttrade_automation.telegram_bot import TelegramBot
    from flinttrade_core import incident_delivery, incident_routes, system_incidents
    from flinttrade_core.auth_routes import EmailTransport

    missing = []
    functions = [TelegramBot.send_incident, EmailTransport.send_incident]
    for module in (incident_delivery, incident_routes, system_incidents):
        for name, value in vars(module).items():
            if name.startswith("_") or getattr(value, "__module__", None) != module.__name__:
                continue
            if inspect.isfunction(value):
                functions.append(value)
            if inspect.isclass(value):
                functions.extend(
                    member
                    for name, member in vars(value).items()
                    if (not name.startswith("_") or name == "__init__")
                    and inspect.isfunction(member)
                    and member.__module__ == module.__name__
                )
    for function in functions:
        signature = inspect.signature(function)
        absent = [
            p.name
            for p in signature.parameters.values()
            if p.name not in ("self", "cls") and p.annotation is inspect.Parameter.empty
        ]
        if signature.return_annotation is inspect.Signature.empty:
            absent.append("return")
        if absent:
            missing.append((function.__qualname__, absent))
    assert missing == []
