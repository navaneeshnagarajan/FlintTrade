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

import ast
import re
from pathlib import Path

_APP = Path(__file__).resolve().parents[1] / "src" / "flinttrade_core" / "app.py"
_CORE_SRC = _APP.parent
_REPO_ROOT = Path(__file__).resolve().parents[4]
_SAFETY = _REPO_ROOT / "packages" / "services" / "engine" / "src" / "flinttrade_engine" / "safety.py"
_TELEGRAM = _REPO_ROOT / "packages" / "services" / "automation" / "src" / "flinttrade_automation" / "telegram_bot.py"
_STRATEGY_EXECUTION = (
    _REPO_ROOT / "packages" / "services" / "engine" / "src" / "flinttrade_engine" / "strategy_execution.py"
)
_BRACKET_ORDER = _REPO_ROOT / "packages" / "services" / "engine" / "src" / "flinttrade_engine" / "bracket_order.py"

# Executors that have graduated to the gated chain and must stay wired.
_GATED_EXECUTOR_KEYS = ("BASKET_EXECUTOR", "SPLIT_EXECUTOR", "BRACKET_SERVICE")

_CANONICAL_EXECUTOR_SYMBOLS = {
    "factory": "flinttrade_engine.bracket_order.build_gated_leg_dispatchers",
    "BRACKET_SERVICE": "flinttrade_engine.bracket_order.BracketOrderService",
    "BASKET_EXECUTOR": "flinttrade_engine.basket_orders.BasketOrderExecutor",
    "SPLIT_EXECUTOR": "flinttrade_engine.split_orders.SplitOrderExecutor",
}


def _import_origins(tree: ast.Module) -> dict[str, list[str]]:
    origins: dict[str, list[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                if alias.name != "*":
                    origins.setdefault(alias.asname or alias.name, []).append(f"{node.module}.{alias.name}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                bound = alias.asname or alias.name.split(".")[0]
                origin = alias.name if alias.asname else alias.name.split(".")[0]
                origins.setdefault(bound, []).append(origin)
    return origins


def _imported_origin(value: ast.AST, origins: dict[str, list[str]]) -> str | None:
    if isinstance(value, ast.Name):
        candidates = origins.get(value.id, [])
        return candidates[0] if len(candidates) == 1 else None
    if isinstance(value, ast.Attribute):
        owner = _imported_origin(value.value, origins)
        return f"{owner}.{value.attr}" if owner is not None else None
    return None


def _root_name(value: ast.AST) -> str | None:
    while isinstance(value, ast.Attribute):
        value = value.value
    return value.id if isinstance(value, ast.Name) else None


def _name_rebindings(tree: ast.Module, name: str) -> list[ast.AST]:
    rebound: list[ast.AST] = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and node.id == name and isinstance(node.ctx, (ast.Store, ast.Del))
    ]
    rebound.extend(
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == name
    )
    return rebound


def _executor_wiring_errors(source: str) -> list[str]:
    tree = ast.parse(source)
    origins = _import_origins(tree)
    errors: list[str] = []
    dispatcher_assignments = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], (ast.Tuple, ast.List))
        and isinstance(node.value, ast.Call)
        and _imported_origin(node.value.func, origins) == _CANONICAL_EXECUTOR_SYMBOLS["factory"]
    ]
    if len(dispatcher_assignments) != 1:
        return [f"expected one build_gated_leg_dispatchers binding, found {len(dispatcher_assignments)}"]
    dispatcher_assignment = dispatcher_assignments[0]
    target = dispatcher_assignment.targets[0]
    assert isinstance(target, (ast.Tuple, ast.List))
    if len(target.elts) != 2 or not all(isinstance(element, ast.Name) for element in target.elts):
        return ["gated dispatcher result must bind exactly two named callables"]
    if (
        len(dispatcher_assignment.value.args) != 1
        or not isinstance(dispatcher_assignment.value.args[0], ast.Name)
        or dispatcher_assignment.value.args[0].id != "app"
    ):
        errors.append("build_gated_leg_dispatchers must be called with the configured app")
    place_name, cancel_name = (element.id for element in target.elts if isinstance(element, ast.Name))
    factory_name = _root_name(dispatcher_assignment.value.func)
    if factory_name is None:
        errors.append("gated dispatcher factory must resolve through one imported symbol")
    elif _name_rebindings(tree, factory_name):
        errors.append(f"canonical dispatcher factory {factory_name} is rebound")
    for dispatcher_name in (place_name, cancel_name):
        stores = _name_rebindings(tree, dispatcher_name)
        if len(stores) != 1 or stores[0] not in target.elts:
            errors.append(f"dispatcher {dispatcher_name} is rebound after canonical construction")

    expected = {
        "BRACKET_SERVICE": ({"place_leg": place_name, "cancel_leg": cancel_name}),
        "BASKET_EXECUTOR": ({"place_leg": place_name}),
        "SPLIT_EXECUTOR": ({"place_leg": place_name}),
    }
    configured: dict[str, list[ast.AST]] = {key: [] for key in expected}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        config_target = node.targets[0]
        if not (
            isinstance(config_target, ast.Subscript)
            and isinstance(config_target.value, ast.Attribute)
            and config_target.value.attr == "config"
            and isinstance(config_target.value.value, ast.Name)
            and config_target.value.value.id == "app"
            and isinstance(config_target.slice, ast.Constant)
            and isinstance(config_target.slice.value, str)
            and config_target.slice.value in expected
        ):
            continue
        configured[config_target.slice.value].append(node.value)

    for key, expected_keywords in expected.items():
        values = configured[key]
        if len(values) != 1:
            errors.append(f"{key} must have exactly one assignment, found {len(values)}")
            continue
        value = values[0]
        expected_origin = _CANONICAL_EXECUTOR_SYMBOLS[key]
        if not isinstance(value, ast.Call) or _imported_origin(value.func, origins) != expected_origin:
            actual = ast.unparse(value.func) if isinstance(value, ast.Call) else ast.unparse(value)
            errors.append(f"{key} must instantiate {expected_origin}, got {actual}")
            continue
        constructor_name = _root_name(value.func) if isinstance(value, ast.Call) else None
        if constructor_name is not None and _name_rebindings(tree, constructor_name):
            errors.append(f"{key} constructor {constructor_name} is rebound")
        keywords = {keyword.arg: keyword.value for keyword in value.keywords if keyword.arg is not None}
        for keyword, expected_name in expected_keywords.items():
            actual = keywords.get(keyword)
            if not isinstance(actual, ast.Name) or actual.id != expected_name:
                errors.append(f"{key}.{keyword} must be the {expected_name} dispatcher")
    return errors


def _function_scope_nodes(function: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.AST]:
    nodes: list[ast.AST] = []

    def visit(node: ast.AST) -> None:
        nodes.append(node)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            return
        for child in ast.iter_child_nodes(node):
            visit(child)

    for statement in function.body:
        visit(statement)
    return nodes


def _function_import_origins(function: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, list[str]]:
    origins: dict[str, list[str]] = {}
    for node in _function_scope_nodes(function):
        if isinstance(node, ast.ImportFrom) and node.module:
            module = node.module
            if node.level == 1 and module == "safety":
                module = "flinttrade_engine.safety"
            for alias in node.names:
                if alias.name != "*":
                    origins.setdefault(alias.asname or alias.name, []).append(f"{module}.{alias.name}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                bound = alias.asname or alias.name.split(".")[0]
                origin = alias.name if alias.asname else alias.name.split(".")[0]
                origins.setdefault(bound, []).append(origin)
    return origins


def _function_non_import_bindings(function: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    bindings = {
        argument.arg
        for argument in (
            *function.args.posonlyargs,
            *function.args.args,
            *function.args.kwonlyargs,
        )
    }
    if function.args.vararg is not None:
        bindings.add(function.args.vararg.arg)
    if function.args.kwarg is not None:
        bindings.add(function.args.kwarg.arg)
    for node in _function_scope_nodes(function):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            bindings.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bindings.add(node.name)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bindings.add(node.name)
    return bindings


def _function_symbol_origin(
    value: ast.AST,
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> str | None:
    origins = _function_import_origins(function)
    bindings = _function_non_import_bindings(function)

    def resolve(node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            if node.id in bindings:
                return None
            candidates = origins.get(node.id, [])
            return candidates[0] if len(candidates) == 1 else None
        if isinstance(node, ast.Attribute):
            owner = resolve(node.value)
            return f"{owner}.{node.attr}" if owner is not None else None
        return None

    return resolve(value)


def _canonical_router_helper(factory: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    helpers = [
        node
        for node in factory.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "_require_router"
    ]
    if len(helpers) != 1:
        return False
    helper = helpers[0]
    if helper.args.posonlyargs or helper.args.args or helper.args.kwonlyargs or helper.args.vararg or helper.args.kwarg:
        return False
    router_bindings = [
        node
        for node in helper.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "router"
    ]
    if len(router_bindings) != 1:
        return False
    value = router_bindings[0].value
    canonical_lookup = (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Attribute)
        and value.func.attr == "get"
        and isinstance(value.func.value, ast.Attribute)
        and value.func.value.attr == "config"
        and isinstance(value.func.value.value, ast.Name)
        and value.func.value.value.id == "app"
        and len(value.args) == 1
        and isinstance(value.args[0], ast.Constant)
        and value.args[0].value == "BROKER_ROUTER"
    )
    returns_router = bool(
        helper.body
        and isinstance(helper.body[-1], ast.Return)
        and isinstance(helper.body[-1].value, ast.Name)
        and helper.body[-1].value.id == "router"
    )
    stores = [
        node
        for node in ast.walk(helper)
        if isinstance(node, ast.Name) and node.id == "router" and isinstance(node.ctx, (ast.Store, ast.Del))
    ]
    return canonical_lookup and returns_router and len(stores) == 1


def _dispatcher_dominance_errors(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    factory: ast.FunctionDef | ast.AsyncFunctionDef,
    sink_method: str,
    require_check: bool,
) -> list[str]:
    errors: list[str] = []
    sink_count = 0
    function_bindings = _function_non_import_bindings(function)
    router_helper_is_canonical = _canonical_router_helper(factory)

    def static_truth(value: ast.AST) -> bool | None:
        if isinstance(value, ast.Constant) and isinstance(value.value, bool):
            return value.value
        if isinstance(value, ast.UnaryOp) and isinstance(value.op, ast.Not):
            truth = static_truth(value.operand)
            return None if truth is None else not truth
        return None

    def expression_calls(value: ast.AST | None) -> list[ast.Call]:
        calls: list[ast.Call] = []

        def visit(node: ast.AST) -> None:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                return
            for child in ast.iter_child_nodes(node):
                visit(child)
            if isinstance(node, ast.Call):
                calls.append(node)

        if value is not None:
            visit(value)
        return calls

    def statement_marker(statement: ast.stmt) -> str | None:
        target: ast.AST | None = None
        value: ast.AST | None = None
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
            target, value = statement.targets[0], statement.value
        elif isinstance(statement, ast.AnnAssign):
            target, value = statement.target, statement.value
        elif isinstance(statement, ast.Expr):
            value = statement.value
        if isinstance(value, ast.Await):
            value = value.value
        if (
            isinstance(target, ast.Name)
            and target.id == "router"
            and isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id == "_require_router"
            and "_require_router" not in function_bindings
            and router_helper_is_canonical
        ):
            return "router"
        if (
            isinstance(target, ast.Name)
            and target.id == "safety"
            and isinstance(value, ast.Call)
            and _function_symbol_origin(value.func, function) == "flinttrade_core.safety_config.require_ready_safety"
        ):
            return "safety"
        if (
            isinstance(target, ast.Name)
            and target.id == "safety_ctx"
            and isinstance(value, ast.Call)
            and _function_symbol_origin(value.func, function) == "flinttrade_engine.safety.gate_order"
        ):
            return "gate"
        if (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Attribute)
            and isinstance(value.func.value, ast.Name)
            and value.func.value.id == "safety"
            and value.func.attr == "check_order"
        ):
            return "check"
        return None

    def target_roots(target: ast.AST) -> set[str]:
        if isinstance(target, ast.Name):
            return {target.id}
        if isinstance(target, (ast.Tuple, ast.List)):
            return {name for element in target.elts for name in target_roots(element)}
        if isinstance(target, ast.Starred):
            return target_roots(target.value)
        if isinstance(target, (ast.Attribute, ast.Subscript)):
            return target_roots(target.value)
        return set()

    def statement_bindings(statement: ast.stmt) -> set[str]:
        targets: list[ast.AST] = []
        if isinstance(statement, ast.Assign):
            targets.extend(statement.targets)
        elif isinstance(statement, (ast.AnnAssign, ast.AugAssign)):
            targets.append(statement.target)
        elif isinstance(statement, ast.Delete):
            targets.extend(statement.targets)
        targets.extend(node.target for node in ast.walk(statement) if isinstance(node, ast.NamedExpr))
        return {name for target in targets for name in target_roots(target)}

    def inspect_expression(value: ast.AST | None, states: set[frozenset[str]]) -> None:
        nonlocal sink_count
        required = {"router", "gate"} | ({"safety", "check"} if require_check else set())
        for call in expression_calls(value):
            if not (
                isinstance(call.func, ast.Attribute)
                and isinstance(call.func.value, ast.Name)
                and call.func.value.id == "router"
                and call.func.attr == sink_method
            ):
                continue
            sink_count += 1
            if any(not required <= state for state in states):
                errors.append(f"{function.name}:{call.lineno} {sink_method} is not dominated by {sorted(required)}")
            keywords = {keyword.arg: keyword.value for keyword in call.keywords if keyword.arg is not None}
            safety_ctx = keywords.get("safety_ctx")
            if not isinstance(safety_ctx, ast.Name) or safety_ctx.id != "safety_ctx":
                errors.append(f"{function.name}:{call.lineno} must receive the freshly gated safety_ctx")

    def process_block(statements: list[ast.stmt], states: set[frozenset[str]]) -> set[frozenset[str]]:
        current = set(states)
        for statement in statements:
            if not current:
                break
            current = process_statement(statement, current)
        return current

    def process_statement(statement: ast.stmt, states: set[frozenset[str]]) -> set[frozenset[str]]:
        if isinstance(statement, ast.If):
            inspect_expression(statement.test, states)
            truth = static_truth(statement.test)
            if truth is True:
                return process_block(statement.body, states)
            if truth is False:
                return process_block(statement.orelse, states)
            body_states = process_block(statement.body, set(states))
            else_states = process_block(statement.orelse, set(states)) if statement.orelse else set(states)
            return body_states | else_states
        if isinstance(statement, ast.While):
            inspect_expression(statement.test, states)
            truth = static_truth(statement.test)
            if truth is False:
                return process_block(statement.orelse, states)
            body_states = process_block(statement.body, set(states))
            continuation = body_states if truth is True else set(states) | body_states
            return process_block(statement.orelse, continuation)
        if isinstance(statement, (ast.For, ast.AsyncFor)):
            inspect_expression(statement.iter, states)
            body_states = process_block(statement.body, set(states))
            return process_block(statement.orelse, set(states) | body_states)
        if isinstance(statement, (ast.With, ast.AsyncWith)):
            for item in statement.items:
                inspect_expression(item.context_expr, states)
            return process_block(statement.body, states)
        if isinstance(statement, (ast.Try, ast.TryStar)):
            body_states = process_block(statement.body, set(states))
            normal_states = process_block(statement.orelse, body_states)
            handler_states: set[frozenset[str]] = set()
            for handler in statement.handlers:
                inspect_expression(handler.type, states)
                handler_states.update(process_block(handler.body, set(states)))
            combined = normal_states | handler_states
            return process_block(statement.finalbody, combined) if statement.finalbody else combined
        if isinstance(statement, ast.Match):
            inspect_expression(statement.subject, states)
            outcomes = set(states)
            for case in statement.cases:
                inspect_expression(case.guard, states)
                outcomes.update(process_block(case.body, set(states)))
            return outcomes

        for child in ast.iter_child_nodes(statement):
            if not isinstance(child, ast.stmt):
                inspect_expression(child, states)
        marker = statement_marker(statement)
        bindings = statement_bindings(statement)
        if bindings & {"router", "safety", "safety_ctx"}:
            updated_states: set[frozenset[str]] = set()
            for state in states:
                updated = set(state)
                if "router" in bindings:
                    updated.discard("router")
                if "safety" in bindings:
                    updated.discard("safety")
                    updated.discard("check")
                if "safety_ctx" in bindings:
                    updated.discard("gate")
                updated_states.add(frozenset(updated))
            states = updated_states
        if marker is not None:
            states = {state | {marker} for state in states}
        if isinstance(statement, (ast.Return, ast.Raise, ast.Break, ast.Continue)):
            return set()
        return states

    process_block(function.body, {frozenset()})
    if sink_count != 1:
        errors.append(f"{function.name} must contain exactly one executable router.{sink_method}, found {sink_count}")
    return errors


def _gated_dispatcher_shape_errors(source: str) -> list[str]:
    tree = ast.parse(source)
    factory = next(
        (
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "build_gated_leg_dispatchers"
        ),
        None,
    )
    if factory is None:
        return ["build_gated_leg_dispatchers is missing"]
    nested = {node.name: node for node in factory.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    errors: list[str] = []
    for function_name, sink_method, require_check in (
        ("place_leg", "place_order", True),
        ("cancel_leg", "cancel_order", False),
    ):
        function = nested.get(function_name)
        if function is None:
            errors.append(f"{function_name} dispatcher is missing")
            continue
        errors.extend(
            _dispatcher_dominance_errors(
                function,
                factory=factory,
                sink_method=sink_method,
                require_check=require_check,
            )
        )
    returns_dispatchers = any(
        isinstance(node, ast.Return)
        and isinstance(node.value, ast.Tuple)
        and [element.id for element in node.value.elts if isinstance(element, ast.Name)] == ["place_leg", "cancel_leg"]
        for node in factory.body
    )
    if not returns_dispatchers:
        errors.append("factory must return the exact place_leg/cancel_leg callables")
    return errors


def test_executor_wiring_guard_rejects_ungated_lookalike() -> None:
    source = (
        "from flinttrade_engine.bracket_order import (\n"
        "    BracketOrderService, build_gated_leg_dispatchers,\n"
        ")\n"
        "from flinttrade_engine.basket_orders import BasketOrderExecutor\n"
        "from flinttrade_engine.split_orders import SplitOrderExecutor\n"
        "place_leg, cancel_leg = build_gated_leg_dispatchers(app)\n"
        "app.config['BRACKET_SERVICE'] = BracketOrderService(\n"
        "    place_leg=place_leg, cancel_leg=cancel_leg\n"
        ")\n"
        "app.config['BASKET_EXECUTOR'] = UngatedExecutor(place_leg=place_leg)\n"
        "app.config['SPLIT_EXECUTOR'] = SplitOrderExecutor(place_leg=place_leg)\n"
    )
    assert _executor_wiring_errors(source)

    wrong_dispatcher = source.replace(
        "UngatedExecutor(place_leg=place_leg)",
        "BasketOrderExecutor(place_leg=raw_place_leg)",
    )
    assert _executor_wiring_errors(wrong_dispatcher)

    raw_factory = (
        "def build_gated_leg_dispatchers(app):\n"
        "    def place_leg(order, principal):\n"
        "        return raw_client.place_order(order)\n"
        "    def cancel_leg(order_id, principal):\n"
        "        return raw_client.cancel_order(order_id)\n"
        "    return place_leg, cancel_leg\n"
    )
    assert _gated_dispatcher_shape_errors(raw_factory)


def test_executor_wiring_guard_proves_import_identity_and_rejects_rebinding() -> None:
    valid_source = (
        "from flinttrade_engine.bracket_order import (\n"
        "    BracketOrderService as Bracket,\n"
        "    build_gated_leg_dispatchers as build_dispatchers,\n"
        ")\n"
        "from flinttrade_engine.basket_orders import BasketOrderExecutor as Basket\n"
        "from flinttrade_engine.split_orders import SplitOrderExecutor as Split\n"
        "place_leg, cancel_leg = build_dispatchers(app)\n"
        "app.config['BRACKET_SERVICE'] = Bracket(\n"
        "    place_leg=place_leg, cancel_leg=cancel_leg\n"
        ")\n"
        "app.config['BASKET_EXECUTOR'] = Basket(place_leg=place_leg)\n"
        "app.config['SPLIT_EXECUTOR'] = Split(place_leg=place_leg)\n"
    )
    assert _executor_wiring_errors(valid_source) == []

    forged_origin = valid_source.replace(
        "from flinttrade_engine.basket_orders import BasketOrderExecutor as Basket",
        "from attacker import BasketOrderExecutor as Basket",
    )
    assert _executor_wiring_errors(forged_origin)

    rebound_factory = valid_source.replace(
        "place_leg, cancel_leg = build_dispatchers(app)",
        "build_dispatchers = raw_factory\nplace_leg, cancel_leg = build_dispatchers(app)",
    )
    assert _executor_wiring_errors(rebound_factory)

    rebound_dispatcher = valid_source + "place_leg = raw_client.place_order\n"
    assert _executor_wiring_errors(rebound_dispatcher)


def test_dispatcher_shape_guard_rejects_unreachable_or_non_dominating_gates() -> None:
    unreachable_gate = (
        "def build_gated_leg_dispatchers(app):\n"
        "    def _require_router():\n"
        "        return app.config['BROKER_ROUTER']\n"
        "    def place_leg(order, principal):\n"
        "        router = _require_router()\n"
        "        if False:\n"
        "            safety.check_order(order)\n"
        "            safety_ctx = gate_order(order, principal)\n"
        "        return router.place_order(order, safety_ctx=safety_ctx)\n"
        "    def cancel_leg(order_id, principal):\n"
        "        router = _require_router()\n"
        "        if False:\n"
        "            safety_ctx = gate_order({'_op': 'cancel'}, principal)\n"
        "        return router.cancel_order(order_id, safety_ctx=safety_ctx)\n"
        "    return place_leg, cancel_leg\n"
    )
    assert _gated_dispatcher_shape_errors(unreachable_gate)

    conditional_gate = unreachable_gate.replace("if False:", "if enabled:")
    assert _gated_dispatcher_shape_errors(conditional_gate)


def test_dispatcher_shape_guard_rejects_spoofed_origins_and_argument_shadowing() -> None:
    spoofed_imports = (
        "def build_gated_leg_dispatchers(app):\n"
        "    def _require_router():\n"
        "        router = app.config.get('BROKER_ROUTER')\n"
        "        if router is None:\n"
        "            raise RuntimeError('missing router')\n"
        "        return router\n"
        "    def place_leg(order, principal):\n"
        "        from attacker import gate_order, require_ready_safety\n"
        "        router = _require_router()\n"
        "        safety = require_ready_safety(app.config)\n"
        "        results = safety.check_order(order)\n"
        "        safety_ctx = gate_order(order, principal)\n"
        "        return router.place_order(order, safety_ctx=safety_ctx)\n"
        "    def cancel_leg(order_id, principal):\n"
        "        from attacker import gate_order\n"
        "        router = _require_router()\n"
        "        safety_ctx = gate_order({'_op': 'cancel'}, principal)\n"
        "        return router.cancel_order(order_id, safety_ctx=safety_ctx)\n"
        "    return place_leg, cancel_leg\n"
    )
    shadowed_defaults = (
        "def build_gated_leg_dispatchers(app):\n"
        "    def _require_router():\n"
        "        router = app.config.get('BROKER_ROUTER')\n"
        "        if router is None:\n"
        "            raise RuntimeError('missing router')\n"
        "        return router\n"
        "    def place_leg(\n"
        "        order, principal, gate_order=fake_gate,\n"
        "        _require_router=raw_provider, require_ready_safety=fake_safety_factory,\n"
        "    ):\n"
        "        router = _require_router()\n"
        "        safety = require_ready_safety(app.config)\n"
        "        results = safety.check_order(order)\n"
        "        safety_ctx = gate_order(order, principal)\n"
        "        return router.place_order(order, safety_ctx=safety_ctx)\n"
        "    def cancel_leg(\n"
        "        order_id, principal, gate_order=fake_gate, _require_router=raw_provider\n"
        "    ):\n"
        "        router = _require_router()\n"
        "        safety_ctx = gate_order({'_op': 'cancel'}, principal)\n"
        "        return router.cancel_order(order_id, safety_ctx=safety_ctx)\n"
        "    return place_leg, cancel_leg\n"
    )
    forged_router_helper = (
        "def build_gated_leg_dispatchers(app):\n"
        "    def _require_router():\n"
        "        return raw_client\n"
        "    def place_leg(order, principal):\n"
        "        from flinttrade_core.safety_config import require_ready_safety\n"
        "        from .safety import gate_order\n"
        "        router = _require_router()\n"
        "        safety = require_ready_safety(app.config)\n"
        "        results = safety.check_order(order)\n"
        "        safety_ctx = gate_order(order, principal)\n"
        "        return router.place_order(order, safety_ctx=safety_ctx)\n"
        "    def cancel_leg(order_id, principal):\n"
        "        from .safety import gate_order\n"
        "        router = _require_router()\n"
        "        safety_ctx = gate_order({'_op': 'cancel'}, principal)\n"
        "        return router.cancel_order(order_id, safety_ctx=safety_ctx)\n"
        "    return place_leg, cancel_leg\n"
    )
    rebound_check_order = (
        "def build_gated_leg_dispatchers(app):\n"
        "    def _require_router():\n"
        "        router = app.config.get('BROKER_ROUTER')\n"
        "        if router is None:\n"
        "            raise RuntimeError('missing router')\n"
        "        return router\n"
        "    def place_leg(order, principal):\n"
        "        from flinttrade_core.safety_config import require_ready_safety\n"
        "        from .safety import gate_order\n"
        "        router = _require_router()\n"
        "        safety = require_ready_safety(app.config)\n"
        "        safety.check_order = fake_check_order\n"
        "        results = safety.check_order(order)\n"
        "        safety_ctx = gate_order(order, principal)\n"
        "        return router.place_order(order, safety_ctx=safety_ctx)\n"
        "    def cancel_leg(order_id, principal):\n"
        "        from .safety import gate_order\n"
        "        router = _require_router()\n"
        "        safety_ctx = gate_order({'_op': 'cancel'}, principal)\n"
        "        return router.cancel_order(order_id, safety_ctx=safety_ctx)\n"
        "    return place_leg, cancel_leg\n"
    )
    assert _gated_dispatcher_shape_errors(spoofed_imports)
    assert _gated_dispatcher_shape_errors(shadowed_defaults)
    assert _gated_dispatcher_shape_errors(forged_router_helper)
    assert _gated_dispatcher_shape_errors(rebound_check_order)


def test_gated_executors_are_wired() -> None:
    wiring_errors = _executor_wiring_errors(_APP.read_text(encoding="utf-8"))
    shape_errors = _gated_dispatcher_shape_errors(_BRACKET_ORDER.read_text(encoding="utf-8"))
    assert not wiring_errors and not shape_errors, (
        "Advanced-order executors must use their exact production classes and "
        "the exact callables returned by build_gated_leg_dispatchers; those "
        "dispatchers must retain gate_order -> BrokerRouter writes. "
        f"Wiring errors: {wiring_errors}; dispatcher errors: {shape_errors}"
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

    assert "emergency_authority" in telegram
    assert "emergency_dispatcher = self.emergency_dispatcher" in telegram
    assert '"emergency_dispatcher": emergency_dispatcher' in telegram
    assert "l5_kill is not None and not callable(emergency_authority)" in telegram
    assert 'activation_kwargs["prepared_targets"] = prepared_targets' in telegram
    assert ".cancel_all_orders(" not in telegram
    assert ".close_position(" not in telegram


def test_scheduled_live_strategy_dispatcher_stays_on_canonical_gate() -> None:
    """A scheduler contract must never become a raw OpenAlgo write capability."""
    source = _STRATEGY_EXECUTION.read_text(encoding="utf-8")

    assert "class GatedStrategyDispatcher" in source
    assert "gate_order(" in source
    assert re.search(r"router\.place_order\s*\(", source)
    assert re.search(r"\b(?:self\.)?[_\w]*client\.place_order\s*\(", source) is None
