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


def test_openalgo_writes_all_require_router_token():
    """Every OpenAlgo write method must call _require_router_token in its body (§8).

    A refactor that drops the guard from modify_order or cancel_order (while
    leaving it on place_order) would not fail the per-method unit tests in
    isolation if those were ever removed, so this grep gate pins the invariant
    at the source level: the literal must appear in each write method's body.
    """
    import ast

    src = (_GATEWAY_SRC / "brokers" / "openalgo.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    adapter = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "OpenAlgoAdapter"
    )
    write_methods = ("place_order", "modify_order", "cancel_order")
    bodies = {
        node.name: ast.get_source_segment(src, node)
        for node in adapter.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in write_methods
    }
    missing = [m for m in write_methods if m not in bodies]
    assert not missing, f"OpenAlgoAdapter is missing write methods: {missing}"
    ungated = [
        m for m, body in bodies.items() if "_require_router_token" not in (body or "")
    ]
    assert not ungated, (
        "OpenAlgo write methods must call _require_router_token (§8); "
        f"unguarded: {ungated}"
    )


def test_native_adapter_writes_all_require_router_token():
    """Every write method of every direct broker adapter must call
    ``_require_router_token`` in its body (§8) — the same source-level pin as
    OpenAlgo, extended to the native SDK adapters (Dhan / Upstox / Kotak Neo).

    These are real write surfaces (dispatched by BrokerRouter with the shared
    per-process token), so a refactor that silently drops the guard from any of
    their place/modify/cancel methods must fail here, not only in a unit test
    that could be removed.
    """
    import ast

    adapters = {
        "dhan.py": "DhanAdapter",
        "upstox.py": "UpstoxAdapter",
        "kotakneo.py": "KotakNeoAdapter",
    }
    write_methods = ("place_order", "modify_order", "cancel_order")
    ungated: list[str] = []
    missing: list[str] = []
    for fname, clsname in adapters.items():
        src = (_GATEWAY_SRC / "brokers" / fname).read_text(encoding="utf-8")
        tree = ast.parse(src)
        cls = next(
            (n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == clsname),
            None,
        )
        assert cls is not None, f"{fname}: class {clsname} not found"
        bodies = {
            node.name: ast.get_source_segment(src, node)
            for node in cls.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in write_methods
        }
        missing += [f"{clsname}.{m}" for m in write_methods if m not in bodies]
        ungated += [
            f"{clsname}.{m}" for m, body in bodies.items()
            if "_require_router_token" not in (body or "")
        ]
    assert not missing, f"native adapters missing write methods: {missing}"
    assert not ungated, (
        "native adapter write methods must call _require_router_token (§8); "
        f"unguarded: {ungated}"
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
