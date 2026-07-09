"""Guard: the advanced-order executors are wired ONLY after they were gated.

The basket / split / bracket order routes (engine ``order_bp`` and ``bracket_bp``)
delegate to executors read from ``app.config["BASKET_EXECUTOR"]`` /
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
