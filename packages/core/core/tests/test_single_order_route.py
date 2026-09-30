"""Only one mounted route can create or fill an order.

Walks the Flask route table and each view's call graph. A route counts when a
reachable function calls the sandbox engine's place or fill methods. The only
allowed route is ``POST /api/v1/orders/place``.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
from collections.abc import Iterator
from types import FunctionType

import pytest

pytestmark = pytest.mark.unit

_ALLOWED_ORDER_ROUTE = ("POST", "/api/v1/orders/place")

# Historical sandbox writers. Remounting any of them fails this test.
_REMOVED_ORDER_ROUTES = frozenset({
    ("POST", "/v1/sandbox/order"),
    ("POST", "/v1/sandbox/square-off"),
})

_SANDBOX_FILL_METHODS = frozenset({
    "check_pending_fills",
    "square_off_all",
})
_SANDBOX_PLACE_METHODS = frozenset({"place_order"})
# ``process_tick`` fills resting Practice orders. Other packages use the same
# method name for signals and order-flow, so only the sandbox receivers count.
_SANDBOX_TICK_RECEIVERS = frozenset({"sandbox", "engine"})
_NON_SANDBOX_PLACE_RECEIVERS = frozenset({"router"})


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


def _is_sandbox_order_call(node: ast.Call) -> bool:
    """True when ``node`` calls a sandbox place or fill method."""
    func = node.func
    if not isinstance(func, ast.Attribute):
        return False
    receiver = _receiver_name(func.value)
    if func.attr in _SANDBOX_FILL_METHODS:
        return True
    if func.attr in _SANDBOX_PLACE_METHODS:
        return receiver not in _NON_SANDBOX_PLACE_RECEIVERS
    if func.attr == "process_tick":
        return receiver in _SANDBOX_TICK_RECEIVERS
    return False


def _called_functions(func: FunctionType) -> list[FunctionType]:
    """Return flinttrade functions this function calls by name."""
    try:
        source = inspect.getsource(func)
    except (OSError, TypeError) as exc:
        raise AssertionError(f"cannot inspect {func.__module__}.{func.__qualname__}") from exc
    tree = ast.parse(textwrap.dedent(source))
    found: list[FunctionType] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        target = func.__globals__.get(node.func.id)
        if isinstance(target, FunctionType) and (target.__module__ or "").startswith("flinttrade"):
            found.append(target)
    return found


def _function_places_or_fills(func: FunctionType) -> bool:
    """True when ``func`` itself calls a sandbox place or fill method."""
    try:
        source = inspect.getsource(func)
    except (OSError, TypeError) as exc:
        raise AssertionError(f"cannot inspect {func.__module__}.{func.__qualname__}") from exc
    tree = ast.parse(textwrap.dedent(source))
    return any(isinstance(node, ast.Call) and _is_sandbox_order_call(node) for node in ast.walk(tree))


def _reaches_sandbox_order_write(func: object) -> bool:
    """True when ``func``'s call graph can place or fill via the sandbox engine."""
    seen: set[int] = set()
    stack: list[object] = [func]
    while stack:
        current = _unwrap(stack.pop())
        if not isinstance(current, FunctionType) or id(current) in seen:
            continue
        seen.add(id(current))
        module = current.__module__ or ""
        if not module.startswith("flinttrade") or module.endswith(".sandbox_engine"):
            continue
        if _function_places_or_fills(current):
            return True
        stack.extend(_called_functions(current))
    return False


def _mounted_rules(app: object) -> Iterator[tuple[str, str, object]]:
    """Yield ``(method, rule, view)`` for every mounted route except OPTIONS."""
    view_functions = app.view_functions  # type: ignore[attr-defined]
    for rule in app.url_map.iter_rules():  # type: ignore[attr-defined]
        view = view_functions.get(rule.endpoint)
        for method in rule.methods or ():
            if method == "OPTIONS":
                continue
            yield method, rule.rule, view


def test_only_place_route_can_create_or_fill_an_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """No mounted route except POST /api/v1/orders/place can create or fill an order.

    A new handler that calls the sandbox engine's place or fill methods fails
    this test, as does remounting a removed sandbox writer.
    """
    monkeypatch.setenv("FLINTTRADE_API_KEY", "single-order-route-test")
    from flinttrade_core.app import create_flask_app

    app = create_flask_app()
    mounted = {(method, rule) for method, rule, _view in _mounted_rules(app)}
    assert _REMOVED_ORDER_ROUTES.isdisjoint(mounted)

    writers = {
        (method, rule)
        for method, rule, view in _mounted_rules(app)
        if view is not None and _reaches_sandbox_order_write(view)
    }
    assert writers == {_ALLOWED_ORDER_ROUTE}
