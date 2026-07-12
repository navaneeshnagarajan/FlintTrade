"""Guard: the advanced-order executors are wired ONLY after they were gated.

The basket / split / bracket order routes (core ``orders_bp`` and engine
``bracket_bp``) delegate to executors read from ``app.config["BASKET_EXECUTOR"]`` /
``["SPLIT_EXECUTOR"]`` / ``["BRACKET_SERVICE"]``.

Audit finding [0] originally confirmed the basket/split executors placed per-leg
orders WITHOUT minting a ``SafetyContext`` through ``gate_order`` ->
``BrokerRouter`` (they bypassed the gated chain), so they were kept UNWIRED
(routes fail closed with 503) until gated.

All three have now graduated: each routes every leg/chunk through the injected
``build_gated_leg_dispatchers`` place_leg (SafetySystem L1-L5 -> ``gate_order``
one-shot HMAC ``SafetyContext`` -> ``BrokerRouter``), hold no broker client, and
are wired in ``create_flask_app``:

- ``BRACKET_SERVICE`` graduated 2026-07-07.
- ``BASKET_EXECUTOR`` / ``SPLIT_EXECUTOR`` graduated 2026-07-09 (G13).

This guard now pins the graduation: they MUST stay wired (a regression that
drops the wiring would silently 503 every advanced order), while the actual
no-raw-route enforcement lives in
``gateway/tests/test_no_legacy_order_path.py`` (basket_orders.py and
split_orders.py were removed from its allowlist in the same change).
"""

from __future__ import annotations

import re
from pathlib import Path

_APP = Path(__file__).resolve().parents[1] / "src" / "flinttrade_core" / "app.py"
_CORE_SRC = _APP.parent
_REPO_ROOT = Path(__file__).resolve().parents[4]
_SAFETY = (
    _REPO_ROOT
    / "packages"
    / "services"
    / "engine"
    / "src"
    / "flinttrade_engine"
    / "safety.py"
)
_TELEGRAM = (
    _REPO_ROOT
    / "packages"
    / "services"
    / "automation"
    / "src"
    / "flinttrade_automation"
    / "telegram_bot.py"
)

# Executors that have graduated to the gated chain and must stay wired.
_GATED_EXECUTOR_KEYS = ("BASKET_EXECUTOR", "SPLIT_EXECUTOR", "BRACKET_SERVICE")


def test_gated_executors_are_wired() -> None:
    text = _APP.read_text(encoding="utf-8")
    unwired = [
        key
        for key in _GATED_EXECUTOR_KEYS
        if not re.search(rf"""config\[["']{key}["']\]\s*=""", text)
    ]
    assert not unwired, (
        "Gated advanced-order executors missing from create_flask_app: "
        f"{unwired}. Each must be constructed with the gated place_leg dispatcher "
        "(build_gated_leg_dispatchers) and injected, or its route silently 503s. "
        "Un-wiring one is a regression."
    )


def test_emergency_executors_expose_parent_injection_contract() -> None:
    """P0 pin: emergency writers require injected current-router ownership.

    ``app.py`` is intentionally not coupled to the engine dispatcher here. The
    parent contract lives on SafetySystem/TelegramBot; the API builds a
    request-bound dispatcher from ``current_app`` so each verb resolves the
    currently published router generation and never retains a stale client.
    """
    safety = _SAFETY.read_text(encoding="utf-8")
    operations = (_CORE_SRC / "operations_routes.py").read_text(encoding="utf-8")
    telegram = _TELEGRAM.read_text(encoding="utf-8")

    assert "class GatedEmergencyBrokerDispatcher" in safety
    assert "emergency_dispatcher" in safety
    assert "router_provider" in safety
    assert "target_provider" in safety
    assert "gate_broker_write(" in safety
    assert re.search(r"router\.execute_gated\s*\(", safety)

    assert "GatedEmergencyBrokerDispatcher(" in operations
    assert 'current_app.config.get("BROKER_ROUTER")' in operations
    assert "EmergencyBrokerTarget(" in operations

    assert "emergency_dispatcher" in telegram
    assert "emergency_dispatcher=self.emergency_dispatcher" in telegram
    assert ".cancel_all_orders(" not in telegram
    assert ".close_position(" not in telegram
