"""Every mounted order submit goes through Laya admit or a reduce-only proof.

Walks the Flask route table. A route counts when its handler can reach an
order submit: a sandbox or broker place/fill call, or a place verb on the
gated order service. The only allowed routes are the canonical place
endpoints and the square-off that records a server-side reduce-only proof.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import textwrap
from collections.abc import Iterator
from types import FunctionType

import pytest

pytestmark = pytest.mark.unit

_ALLOWED_SUBMIT_ROUTES = frozenset({
    ("POST", "/api/v1/orders/place"),
    ("POST", "/api/v1/orders/<broker>/place"),
    ("POST", "/api/v1/positions/exit-all"),
})

_RESTORE_ROUTE = ("POST", "/v1/sandbox/import")

_REMOVED_DIRECT_PLACE_ROUTES = frozenset({
    ("POST", "/api/v1/orders/place-smart"),
    ("POST", "/api/v1/orders/open-position"),
    ("POST", "/api/v1/orders/close-position"),
})

_SUBMIT_ATTRS = frozenset({
    "place_order",
    "place_smart_order",
    "open_position",
    "close_position",
    "square_off_all",
    "check_pending_fills",
    "exit_all_positions",
    "place_basket_order",
    "place_split_order",
    "place_reducing_order",
    "place_conditional_trigger",
    "place_multi_order",
    "place_leg",
    "_place_leg",
})
_SANDBOX_TICK_RECEIVERS = frozenset({"sandbox", "engine"})
_PLACE_VERBS = frozenset({
    "exit_all_positions",
    "place_conditional_trigger",
    "place_multi_order",
    "place_reducing_order",
})
_VERB_CALLEES = frozenset({"_gated_verb_write", "execute_gated"})
_ADMIT_NAMES = frozenset({
    "_admit_place",
    "_laya_place_response",
    "_record_reduce_only",
    "_prepare_live_reduce_only",
    "_prove_exit_all_reduce_only",
    "_laya_automate_block",
})
_ADMIT_ATTRS = frozenset({"admit", "admit_reduce_only"})
_DB_RECEIVERS = frozenset({
    "conn",
    "_conn",
    "_db",
    "db",
    "cursor",
    "session",
    "connection",
})

# Attribute calls the route table resolves onto a real order helper.
_FOLLOW_ATTR: dict[tuple[str, str], tuple[str, str, str]] = {
    ("executor", "execute"): (
        "flinttrade_engine.basket_orders",
        "BasketOrderExecutor",
        "execute",
    ),
    ("executor", "execute_split"): (
        "flinttrade_engine.split_orders",
        "SplitOrderExecutor",
        "execute_split",
    ),
    ("bridge", "execute"): (
        "flinttrade_automation.voice_order_bridge",
        "VoiceOrderBridge",
        "execute",
    ),
    ("svc", "place_bracket"): (
        "flinttrade_engine.bracket_order",
        "BracketOrderService",
        "place_bracket",
    ),
    ("service", "place_bracket"): (
        "flinttrade_engine.bracket_order",
        "BracketOrderService",
        "place_bracket",
    ),
    ("receiver", "dispatch"): (
        "flinttrade_webhooks.webhook_receiver",
        "WebhookReceiver",
        "dispatch",
    ),
    ("smart_router", "route"): (
        "flinttrade_engine.smart_router",
        "SmartOrderRouter",
        "route",
    ),
}
_SELF_FOLLOW_ATTRS = frozenset({
    "execute",
    "execute_split",
    "dispatch",
    "route",
    "route_order",
    "_handle_place_order",
    "_handle_order",
    "_handle_exit",
    "_handle_cancel",
    "_handle_modify",
    "_handle_status",
    "_call_dispatcher",
})


def _unwrap(func: object) -> object:
    """Return the function under ``functools.wraps`` decorators."""
    seen: set[int] = set()
    current = func
    while hasattr(current, "__wrapped__") and id(current) not in seen:
        seen.add(id(current))
        current = current.__wrapped__  # type: ignore[attr-defined]
    return current


def _receiver_name(node: ast.AST) -> str | None:
    """Return the closest name or attribute on a call receiver."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _parse(func: FunctionType) -> ast.AST:
    try:
        source = inspect.getsource(func)
    except (OSError, TypeError) as exc:
        raise AssertionError(f"cannot inspect {func.__module__}.{func.__qualname__}") from exc
    return ast.parse(textwrap.dedent(source))


def _decorator_call_ids(tree: ast.AST) -> set[int]:
    """Calls that only register a route, so they are not order dispatch."""
    found: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for deco in node.decorator_list:
                if isinstance(deco, ast.Call):
                    found.add(id(deco))
    return found


def _local_names(func: FunctionType, tree: ast.AST) -> dict[str, object]:
    """Resolve imports that exist only inside ``func``."""
    module_name = func.__module__ or ""
    found: dict[str, object] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        package = module_name
        if node.level:
            parts = module_name.split(".")
            keep = len(parts) - node.level
            package = ".".join(parts[:keep]) if keep > 0 else ""
        try:
            imported = importlib.import_module(node.module or "", package or None)
        except (ImportError, TypeError, ValueError):
            continue
        for alias in node.names:
            value = getattr(imported, alias.name, None)
            found[alias.asname or alias.name] = value
    return found


def _lookup_method(module: str, class_name: str, method_name: str) -> FunctionType | None:
    try:
        imported = importlib.import_module(module)
    except ImportError:
        return None
    owner = getattr(imported, class_name, None)
    method = getattr(owner, method_name, None)
    unwrapped = _unwrap(method)
    if isinstance(unwrapped, FunctionType):
        return unwrapped
    return None


def _enclosing_method(func: FunctionType, attr: str) -> FunctionType | None:
    """Return ``attr`` on the class that defines ``func``, when that is a method."""
    qualname = func.__qualname__
    if "." not in qualname:
        return None
    class_name = qualname.split(".", 1)[0]
    module_name = func.__module__ or ""
    try:
        imported = importlib.import_module(module_name)
    except ImportError:
        return None
    owner = getattr(imported, class_name, None)
    method = getattr(owner, attr, None)
    unwrapped = _unwrap(method)
    if isinstance(unwrapped, FunctionType):
        return unwrapped
    return None


def _is_submit_call(node: ast.Call) -> bool:
    """True when ``node`` itself submits an order."""
    func = node.func
    if isinstance(func, ast.Attribute):
        if func.attr == "process_tick":
            return _receiver_name(func.value) in _SANDBOX_TICK_RECEIVERS
        if func.attr in _SUBMIT_ATTRS:
            return True
        callee = func.attr
    elif isinstance(func, ast.Name):
        callee = func.id
    else:
        return False
    if callee not in _VERB_CALLEES:
        return False
    if node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value in _PLACE_VERBS:
        return True
    for keyword in node.keywords:
        if (
            keyword.arg == "verb"
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value in _PLACE_VERBS
        ):
            return True
    return False


def _has_admit(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in _ADMIT_NAMES:
            return True
        if isinstance(node, ast.Attribute) and node.attr in _ADMIT_ATTRS:
            return True
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _ADMIT_NAMES:
            return True
    return False


def _called_targets(
    func: FunctionType,
    tree: ast.AST,
    decorator_ids: set[int],
) -> list[FunctionType]:
    """Return flinttrade functions this function can call."""
    local = _local_names(func, tree)
    found: list[FunctionType] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or id(node) in decorator_ids:
            continue
        target: object | None = None
        if isinstance(node.func, ast.Name):
            target = local.get(node.func.id, func.__globals__.get(node.func.id))
        elif isinstance(node.func, ast.Attribute):
            receiver = _receiver_name(node.func.value)
            if receiver in _DB_RECEIVERS:
                continue
            spec = _FOLLOW_ATTR.get((receiver or "", node.func.attr))
            if spec is not None:
                target = _lookup_method(*spec)
            elif receiver in {"self", "cls"} and node.func.attr in _SELF_FOLLOW_ATTRS:
                target = _enclosing_method(func, node.func.attr)
        unwrapped = _unwrap(target)
        if isinstance(unwrapped, FunctionType) and (unwrapped.__module__ or "").startswith("flinttrade"):
            found.append(unwrapped)
    return found


def _graph(func: object) -> list[FunctionType]:
    """Return the flinttrade functions reachable from ``func``, including itself."""
    seen: set[int] = set()
    found: list[FunctionType] = []
    stack: list[object] = [func]
    while stack:
        current = _unwrap(stack.pop())
        if not isinstance(current, FunctionType) or id(current) in seen:
            continue
        seen.add(id(current))
        module = current.__module__ or ""
        if not module.startswith("flinttrade"):
            continue
        found.append(current)
        tree = _parse(current)
        stack.extend(_called_targets(current, tree, _decorator_call_ids(tree)))
    return found


def _reaches_submit(func: object) -> bool:
    for current in _graph(func):
        tree = _parse(current)
        decorator_ids = _decorator_call_ids(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and id(node) not in decorator_ids and _is_submit_call(node):
                return True
    return False


def _reaches_admit(func: object) -> bool:
    return any(_has_admit(_parse(current)) for current in _graph(func))


def _mounted_rules(app: object) -> Iterator[tuple[str, str, object]]:
    """Yield ``(method, rule, view)`` for every mounted route except OPTIONS."""
    view_functions = app.view_functions  # type: ignore[attr-defined]
    for rule in app.url_map.iter_rules():  # type: ignore[attr-defined]
        view = view_functions.get(rule.endpoint)
        for method in rule.methods or ():
            if method == "OPTIONS":
                continue
            yield method, rule.rule, view


def test_only_admitted_routes_can_submit_an_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """The route table's order submits are place, plus the reduce-only square-off.

    Restore is mounted and cannot submit. Direct place-smart, open-position,
    and close-position routes stay unmounted.
    """
    monkeypatch.setenv("FLINTTRADE_API_KEY", "order-submit-route-test")
    from flinttrade_core.app import create_flask_app

    app = create_flask_app()
    mounted = {(method, rule) for method, rule, _view in _mounted_rules(app)}
    assert _REMOVED_DIRECT_PLACE_ROUTES.isdisjoint(mounted)
    assert _RESTORE_ROUTE in mounted

    submitters: dict[tuple[str, str], object] = {}
    for method, rule, view in _mounted_rules(app):
        if view is not None and _reaches_submit(view):
            submitters[(method, rule)] = view

    assert set(submitters) == _ALLOWED_SUBMIT_ROUTES
    missing_admit = sorted(
        f"{method} {rule}"
        for (method, rule), view in submitters.items()
        if not _reaches_admit(view)
    )
    assert missing_admit == []
    restore_view = next(
        view
        for method, rule, view in _mounted_rules(app)
        if (method, rule) == _RESTORE_ROUTE
    )
    assert restore_view is not None
    assert not _reaches_submit(restore_view)
