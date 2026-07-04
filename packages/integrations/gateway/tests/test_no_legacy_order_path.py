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

_REPO_ROOT = Path(__file__).resolve().parents[4]

# Order-write call patterns that must traverse the gated chain.
_ORDER_WRITE_RE = re.compile(
    r"\.(place_order|placeorder|placesmartorder|close_position|closeposition)\s*\("
)
# A call is GATED/legitimate when it delegates to a *_router (the gating
# chokepoint — gate_order -> BrokerRouter) or to the isolated sandbox engine
# (Practice mode, never a live broker).
_GATED_RECEIVER_RE = re.compile(
    r"(\w*router\.(place_order|close_position)"
    r"|sandbox\w*\.\w*\.?place_order"
    r"|\.engine\.place_order)"
)

# Modules that legitimately contain a RAW (non-router) broker order-write. This
# is the SHRINKING debt allowlist: every entry is either a known-dormant native
# strategy/agent path (tracked in PLAN.md, not wired live) or an L5 emergency
# close. A NEW raw order-write in any OTHER services/webhooks module fails the
# guard below — it must be gated through gate_order -> BrokerRouter instead.
_RAW_ORDER_ALLOWLIST = {
    # Dormant — not wired to any live route/schedule (PLAN.md tracks the refactor):
    # (flinttrade_ai/autonomous_agent.py REMOVED 2026-06-10: its order writes now
    #  go through an injected gated executor — SafetySystem → gate_order →
    #  BrokerRouter — and it fails closed without one.)
    "packages/services/engine/src/flinttrade_engine/bracket_order.py",
    "packages/services/engine/src/flinttrade_engine/router.py",
    "packages/services/engine/src/flinttrade_engine/strategies/wheel_live.py",
    # L5 emergency close (acceptable un-gated — gating an emergency exit could
    # deadlock the very safety action it protects):
    "packages/services/automation/src/flinttrade_automation/telegram_bot.py",
    "packages/services/engine/src/flinttrade_engine/safety.py",
}

_GATEWAY_SRC = Path(__file__).resolve().parents[1] / "src" / "flinttrade_gateway"
_WRITE_METHODS = (
    "place_order",
    "modify_order",
    "cancel_order",
    "cancel_all_orders",
    "close_position",
    "place_options_order",
    # Extended gated verbs (BrokerRouter.execute_gated) — must never leak onto
    # the registry/session surfaces either.
    "modify_forever",
    "cancel_forever",
    "modify_super_order",
    "cancel_super_order",
    "place_conditional_trigger",
    "modify_conditional_trigger",
    "cancel_conditional_trigger",
    "convert_position",
    "exit_all_positions",
    "place_multi_order",
    "cancel_smart_order",
)

# Extended adapter write verbs (contract §8.1) and the raw-call tripwire for
# them. Any `.modify_forever(` etc. outside the BrokerRouter is a bypass —
# routes/services must go through gate_broker_write -> BrokerRouter.execute_gated
# (whose call sites carry the verb only as a STRING argument, so they never
# match this attribute-call regex).
_EXTENDED_VERB_WRITE_RE = re.compile(
    r"\.(modify_forever|cancel_forever|modify_super_order|cancel_super_order"
    r"|place_conditional_trigger|modify_conditional_trigger|cancel_conditional_trigger"
    r"|convert_position|exit_all_positions|place_multi_order|cancel_all_orders"
    r"|cancel_smart_order)\s*\("
)

# Modules that legitimately contain a raw extended-verb call. BOTH are the L5
# emergency-close path calling OpenAlgoClient.cancel_all_orders (never a broker
# adapter): gating an emergency flatten could deadlock the very safety action
# it protects. Same shrinking-allowlist rule as _RAW_ORDER_ALLOWLIST.
_RAW_EXTENDED_VERB_ALLOWLIST = {
    "packages/services/engine/src/flinttrade_engine/safety.py",
    "packages/services/automation/src/flinttrade_automation/telegram_bot.py",
}


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


# Per-adapter expected gated write surface (the trio + every extended verb the
# adapter implements). Dropping any of these methods — or its router-token
# guard — must fail HERE, not only in a per-adapter unit test that could be
# removed alongside the method.
_NATIVE_ADAPTER_WRITE_METHODS: dict[str, tuple[str, tuple[str, ...]]] = {
    "dhan.py": (
        "DhanAdapter",
        (
            "place_order", "modify_order", "cancel_order",
            "modify_forever", "cancel_forever",
            "modify_super_order", "cancel_super_order",
            "place_conditional_trigger", "modify_conditional_trigger",
            "cancel_conditional_trigger",
            "convert_position", "exit_all_positions",
        ),
    ),
    "upstox.py": (
        "UpstoxAdapter",
        (
            "place_order", "modify_order", "cancel_order",
            "place_multi_order", "cancel_all_orders",
            "exit_all_positions", "convert_position",
        ),
    ),
    "kotakneo.py": (
        "KotakNeoAdapter",
        ("place_order", "modify_order", "cancel_order"),
    ),
    "indmoney.py": (
        "IndMoneyAdapter",
        ("place_order", "modify_order", "cancel_order", "cancel_smart_order"),
    ),
}


def test_native_adapter_writes_all_require_router_token():
    """Every write method of every direct broker adapter must call
    ``_require_router_token`` in its body (§8) — the same source-level pin as
    OpenAlgo, extended to the native SDK adapters (Dhan / Upstox / Kotak Neo /
    IndMoney) and to EVERY extended gated verb, not just the trio.

    Two assertions per adapter:
      * the pinned expected write surface exists (a silently dropped gated verb
        fails here), and
      * EVERY method that takes a ``_router_token`` parameter calls
        ``_require_router_token`` in its body — so a brand-new gated verb cannot
        ship with the parameter but without the guard.
    """
    import ast

    ungated: list[str] = []
    missing: list[str] = []
    for fname, (clsname, write_methods) in _NATIVE_ADAPTER_WRITE_METHODS.items():
        src = (_GATEWAY_SRC / "brokers" / fname).read_text(encoding="utf-8")
        tree = ast.parse(src)
        cls = next(
            (n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == clsname),
            None,
        )
        assert cls is not None, f"{fname}: class {clsname} not found"
        methods = {
            node.name: node
            for node in cls.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        missing += [f"{clsname}.{m}" for m in write_methods if m not in methods]
        for name, node in methods.items():
            arg_names = {a.arg for a in node.args.args} | {a.arg for a in node.args.kwonlyargs}
            takes_token = "_router_token" in arg_names
            if name in write_methods or takes_token:
                body = ast.get_source_segment(src, node) or ""
                if "_require_router_token" not in body:
                    ungated.append(f"{clsname}.{name}")
    assert not missing, f"native adapters missing gated write methods: {missing}"
    assert not ungated, (
        "native adapter write methods must call _require_router_token (§8); "
        f"unguarded: {sorted(set(ungated))}"
    )


def test_native_adapter_write_surface_matches_router_verb_table():
    """Every extended adapter verb pinned above must be dispatchable through
    ``BrokerRouter.execute_gated`` — i.e. present in the router's verb table and
    the engine's ``GATED_WRITE_VERBS`` registry. An adapter write method that is
    NOT in the table would be unreachable except by bypassing the router, so the
    surface and the table must stay in lock-step (contract §8.1)."""
    from flinttrade_engine.safety import GATED_WRITE_VERBS
    from flinttrade_gateway.router import _GATED_VERB_DISPATCH

    trio = {"place_order", "modify_order", "cancel_order"}
    extended_adapter_verbs = {
        m
        for _cls, methods in _NATIVE_ADAPTER_WRITE_METHODS.values()
        for m in methods
        if m not in trio
    }
    not_dispatchable = sorted(extended_adapter_verbs - set(_GATED_VERB_DISPATCH))
    assert not not_dispatchable, (
        "extended adapter write verbs missing from BrokerRouter._GATED_VERB_DISPATCH "
        f"(unreachable without a bypass): {not_dispatchable}"
    )
    assert set(_GATED_VERB_DISPATCH) == GATED_WRITE_VERBS, (
        "router verb table and engine GATED_WRITE_VERBS registry drifted apart"
    )


def test_no_new_ungated_order_paths_in_services_and_webhooks():
    """Repo-wide §8.1 tripwire: no NEW raw broker order-write outside the gate.

    The gateway package self-guards (the tests above), but the order-placing
    surfaces live in ``packages/services/*``, ``packages/integrations/webhooks``,
    AND ``packages/core`` (the Flask route layer — order_routes,
    smart_order_routes, agent_routes — plus the data sandbox). This scans them
    for ``.place_order``/``.close_position`` (and the OpenAlgo spellings) and
    asserts every occurrence either delegates to a ``*_router`` (the
    gate_order -> BrokerRouter chokepoint), targets the isolated sandbox
    engine, or sits in a module on the explicit SHRINKING debt allowlist
    (``_RAW_ORDER_ALLOWLIST``). A new raw order call in any other module fails
    here — forcing it through the gate before it can ever go live.
    """
    # The data sandbox's paper engine is order-shaped but broker-free: routes
    # call ``engine.place_order`` on the SandboxEngine pulled from app config.
    sandbox_receiver_re = re.compile(
        r"((?<![\w.])engine\.place_order|SandboxEngine\.place_order)"
    )
    scan_dirs = [
        _REPO_ROOT / "packages" / "services",
        _REPO_ROOT / "packages" / "integrations" / "webhooks",
        _REPO_ROOT / "packages" / "core",
    ]
    offenders: list[str] = []
    for root in scan_dirs:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            parts = path.parts
            if "tests" in parts or path.name.startswith("test_"):
                continue
            rel = path.relative_to(_REPO_ROOT).as_posix()
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("#") or "def " in stripped:
                    continue
                if not _ORDER_WRITE_RE.search(line):
                    continue
                if _GATED_RECEIVER_RE.search(line):
                    continue  # delegates to the router / sandbox — legitimate
                if sandbox_receiver_re.search(line):
                    continue  # the broker-free paper engine
                if rel in _RAW_ORDER_ALLOWLIST:
                    continue  # known dormant/emergency debt
                offenders.append(f"{rel}:{n}: {stripped}")
    assert not offenders, (
        "Ungated broker order-write outside the gate_order -> BrokerRouter chain "
        "(contract §8.1). Route it through gate_order/BrokerRouter, or — if it is a "
        "deliberate dormant/emergency path — add the module to _RAW_ORDER_ALLOWLIST "
        "with a justification:\n" + "\n".join(offenders)
    )


def test_no_raw_extended_verb_calls_in_services_and_webhooks():
    """§8.1 tripwire for the EXTENDED gated verbs (forever/super/trigger/convert/
    exit-all/multi/cancel-all/smart-cancel).

    These adapter write methods are reachable ONLY through
    ``gate_broker_write -> BrokerRouter.execute_gated`` (whose call sites carry
    the verb as a string argument, never as an attribute call, so they cannot
    match here). Any raw ``.modify_forever(`` / ``.exit_all_positions(`` /…
    attribute call in ``packages/services/*``, ``packages/integrations/webhooks``
    or ``packages/core`` is a bypass of the single gated path — unless the
    module is on the explicit shrinking allowlist (the L5 emergency close via
    OpenAlgoClient, never a broker adapter).
    """
    scan_dirs = [
        _REPO_ROOT / "packages" / "services",
        _REPO_ROOT / "packages" / "integrations" / "webhooks",
        _REPO_ROOT / "packages" / "core",
    ]
    offenders: list[str] = []
    for root in scan_dirs:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            parts = path.parts
            if "tests" in parts or path.name.startswith("test_"):
                continue
            rel = path.relative_to(_REPO_ROOT).as_posix()
            if rel in _RAW_EXTENDED_VERB_ALLOWLIST:
                continue  # L5 emergency close (OpenAlgoClient, not an adapter)
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("#") or "def " in stripped:
                    continue
                if _EXTENDED_VERB_WRITE_RE.search(line):
                    offenders.append(f"{rel}:{n}: {stripped}")
    assert not offenders, (
        "Raw extended-verb broker write outside the gate_broker_write -> "
        "BrokerRouter.execute_gated chain (contract §8.1). Route it through the "
        "router, or — if it is a deliberate emergency path — add the module to "
        "_RAW_EXTENDED_VERB_ALLOWLIST with a justification:\n" + "\n".join(offenders)
    )


def test_raw_extended_verb_allowlist_has_no_stale_entries():
    """The extended-verb allowlist must shrink, never rot (same rule as
    ``_RAW_ORDER_ALLOWLIST``): every entry must still exist and still contain a
    raw extended-verb call."""
    stale: list[str] = []
    for rel in sorted(_RAW_EXTENDED_VERB_ALLOWLIST):
        path = _REPO_ROOT / rel
        if not path.exists():
            stale.append(f"{rel} (file gone)")
            continue
        has_raw = any(
            _EXTENDED_VERB_WRITE_RE.search(line)
            and "def " not in line and not line.strip().startswith("#")
            for line in path.read_text(encoding="utf-8").splitlines()
        )
        if not has_raw:
            stale.append(f"{rel} (no raw extended-verb call left — remove from allowlist)")
    assert not stale, (
        "Stale _RAW_EXTENDED_VERB_ALLOWLIST entries (the allowlist must shrink):\n"
        + "\n".join(stale)
    )


def test_raw_order_allowlist_has_no_stale_entries():
    """The debt allowlist must shrink, never rot: every allowlisted module must
    still exist and still contain a raw order-write (otherwise remove it)."""
    stale: list[str] = []
    for rel in sorted(_RAW_ORDER_ALLOWLIST):
        path = _REPO_ROOT / rel
        if not path.exists():
            stale.append(f"{rel} (file gone)")
            continue
        has_raw = any(
            _ORDER_WRITE_RE.search(line) and not _GATED_RECEIVER_RE.search(line)
            and "def " not in line and not line.strip().startswith("#")
            for line in path.read_text(encoding="utf-8").splitlines()
        )
        if not has_raw:
            stale.append(f"{rel} (no raw order-write left — remove from allowlist)")
    assert not stale, "Stale _RAW_ORDER_ALLOWLIST entries (the allowlist must shrink):\n" + "\n".join(stale)


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


# Raw OpenAlgo order-write ENDPOINT strings (URL builds POSTed via httpx/requests
# rather than attribute calls) — the G12 blind spot the attribute-call regex
# above cannot see. The ditto mirror's retired ungated fallback built exactly
# such a URL (f"{host}/api/v1/placeorder") and passed the guard for months.
_ORDER_WRITE_URL_RE = re.compile(
    r"api/v1/(placeorder|placesmartorder|basketorder|splitorder"
    r"|modifyorder|cancelorder|cancelallorder|closeposition)"
)

# Modules that legitimately mention order-write endpoint paths: the canonical
# OpenAlgo client (docstrings on the single sanctioned path in) and the v1
# compatibility route TABLE (inbound route mapping, not an outbound POST).
_ORDER_WRITE_URL_ALLOWLIST = {
    "packages/core/core/src/flinttrade_core/openalgo_client.py",
    "packages/core/core/src/flinttrade_core/v1_compat.py",
}


def test_no_raw_order_write_urls_in_services_and_webhooks():
    """G12 blind-spot tripwire: no hand-built OpenAlgo order-write URL anywhere.

    A raw ``httpx.post(f"{host}/api/v1/placeorder", ...)`` never matches the
    attribute-call regexes above, so it would bypass every guard in this file.
    This scans services/webhooks/core for order-write ENDPOINT strings outside
    the canonical client and the v1 compat route table. Comments are skipped;
    docstrings outside the allowlist still fail (they advertise a raw path).
    """
    scan_dirs = [
        _REPO_ROOT / "packages" / "services",
        _REPO_ROOT / "packages" / "integrations" / "webhooks",
        _REPO_ROOT / "packages" / "core",
    ]
    offenders: list[str] = []
    for root in scan_dirs:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            parts = path.parts
            if "tests" in parts or path.name.startswith("test_"):
                continue
            rel = path.relative_to(_REPO_ROOT).as_posix()
            if rel in _ORDER_WRITE_URL_ALLOWLIST:
                continue
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if _ORDER_WRITE_URL_RE.search(line):
                    offenders.append(f"{rel}:{n}: {stripped}")
    assert not offenders, (
        "Raw OpenAlgo order-write endpoint URL outside the canonical client "
        "(contract §8.1 / G12). Order writes must traverse gate_order -> "
        "BrokerRouter — never a hand-built endpoint POST:\n" + "\n".join(offenders)
    )
