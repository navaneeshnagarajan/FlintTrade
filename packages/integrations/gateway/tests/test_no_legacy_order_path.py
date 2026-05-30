"""§8.1 grep guards: no parallel order path; only gate_order() mints (S7 + §8.1).

These keep the safety invariant from regressing:
  * BrokerRegistry / BrokerSession expose NO order-write methods — every write must go
    through gate_order() -> BrokerRouter.place_order(), which verifies a one-shot
    SafetyContext (S7 / contract §12).
  * No broker adapter constructs a SafetyContext directly — only
    flinttrade_engine.safety.gate_order() mints (contract §8.1).
"""

from __future__ import annotations

import re
from pathlib import Path

from flinttrade_gateway.registry import BrokerRegistry
from flinttrade_gateway.session import BrokerSession

_GATEWAY_SRC = Path(__file__).resolve().parents[1] / "src" / "flinttrade_gateway"
_WRITE_METHODS = (
    "place_order",
    "modify_order",
    "cancel_order",
    "cancel_all_orders",
    "close_position",
    "place_options_order",
)


def test_registry_exposes_no_write_methods():
    leaked = [m for m in _WRITE_METHODS if hasattr(BrokerRegistry, m)]
    assert not leaked, f"BrokerRegistry must be a pure resolver; found write methods: {leaked}"


def test_session_exposes_no_write_methods():
    leaked = [m for m in _WRITE_METHODS if hasattr(BrokerSession, m)]
    assert not leaked, f"BrokerSession must not expose write methods; found: {leaked}"


def test_registry_and_session_source_define_no_write_methods():
    offenders: list[str] = []
    for fname in ("registry.py", "session.py"):
        text = (_GATEWAY_SRC / fname).read_text(encoding="utf-8")
        for m in _WRITE_METHODS:
            if re.search(rf"^\s*def {m}\(", text, re.MULTILINE):
                offenders.append(f"{fname}: def {m}(")
    assert not offenders, (
        "Legacy order-write methods reintroduced (S7):\n" + "\n".join(offenders)
    )


def test_only_gate_order_mints_safety_context():
    """No adapter under brokers/ may construct a SafetyContext (contract §8.1)."""
    brokers_dir = _GATEWAY_SRC / "brokers"
    offenders: list[str] = []
    for path in brokers_dir.rglob("*.py"):
        if path.name.startswith("test_"):
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "SafetyContext(" in line and "gate_order" not in line:
                offenders.append(f"{path.relative_to(_GATEWAY_SRC)}:{n}: {line.strip()}")
    assert not offenders, (
        "Only flinttrade_engine.safety.gate_order() may mint a SafetyContext (§8.1):\n"
        + "\n".join(offenders)
    )
