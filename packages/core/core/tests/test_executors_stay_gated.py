"""Guard: dormant advanced-order executors must stay UNWIRED until gated.

The basket / split / bracket order routes (engine ``order_bp`` and ``bracket_bp``)
are registered in the production app, but they delegate to executors read from
``app.config["BASKET_EXECUTOR"]`` / ``["SPLIT_EXECUTOR"]`` / ``["BRACKET_SERVICE"]``
— which ``create_flask_app`` deliberately does NOT set, so those routes fail
closed (no executor → error) rather than placing orders.

Audit finding [0] confirmed those executors place per-leg orders WITHOUT minting a
``SafetyContext`` through ``gate_order`` → ``BrokerRouter`` (they bypass the gated
execution chain). They are safe only because they are never wired. This guard
keeps it that way: wiring one of them into the app factory before it routes every
leg through ``gate_order`` would open an ungated live-order path — the exact class
the gated-execution rule (CLAUDE.md) forbids.

When you gate an executor (mint a one-shot, selector-bound ``SafetyContext`` per
leg and dispatch through ``BrokerRouter.place_order``), wire it and remove it from
``_UNGATED_EXECUTOR_KEYS`` below.
"""

from __future__ import annotations

import re
from pathlib import Path

_APP = Path(__file__).resolve().parents[1] / "src" / "flinttrade_core" / "app.py"

# Executors confirmed (audit [0]) to place ungated orders — must not be wired.
_UNGATED_EXECUTOR_KEYS = ("BASKET_EXECUTOR", "SPLIT_EXECUTOR", "BRACKET_SERVICE")


def test_advanced_executors_not_wired_until_gated() -> None:
    text = _APP.read_text(encoding="utf-8")
    wired = [
        key
        for key in _UNGATED_EXECUTOR_KEYS
        if re.search(rf"""config\[["']{key}["']\]\s*=""", text)
    ]
    assert not wired, (
        "Advanced-order executors wired into create_flask_app while still ungated: "
        f"{wired}. Route their per-leg placement through gate_order -> "
        "BrokerRouter.place_order (mint a one-shot SafetyContext per leg) BEFORE "
        "wiring them, then drop them from _UNGATED_EXECUTOR_KEYS (audit [0]; "
        "gated-execution rule)."
    )
