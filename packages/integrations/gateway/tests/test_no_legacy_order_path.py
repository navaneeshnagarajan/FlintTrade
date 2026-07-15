"""§8.1 grep guards: no parallel order path; only gate_order() mints (S7 + §8.1).

These keep the safety invariant from regressing:
  * BrokerRegistry / BrokerSession expose NO order-write methods — every write must go
    through gate_order() -> BrokerRouter.place_order(), which verifies a one-shot
    SafetyContext (S7 / contract §12).
  * No broker adapter constructs a SafetyContext directly — only
    flinttrade_engine.safety.gate_order() mints (contract §8.1).
"""

from __future__ import annotations

import ast
import re
from collections.abc import Callable
from pathlib import Path

import pytest

from flinttrade_gateway.registry import BrokerRegistry
from flinttrade_gateway.session import BrokerSession

_REPO_ROOT = Path(__file__).resolve().parents[4]


def _is_exact_prospective_greek(value: ast.AST, field: str, proven_admissions: set[str]) -> bool:
    return (
        isinstance(value, ast.Attribute)
        and value.attr == field
        and isinstance(value.value, ast.Name)
        and value.value.id in proven_admissions
    )


def _scope_nodes(function: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.AST]:
    """Return nodes executed in one function scope, excluding nested bodies."""
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


def _module_scope_nodes(module: ast.Module) -> list[ast.AST]:
    """Return nodes executed at module scope, including control-flow bodies."""
    nodes: list[ast.AST] = []

    def visit(node: ast.AST) -> None:
        nodes.append(node)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            return
        for child in ast.iter_child_nodes(node):
            visit(child)

    for statement in module.body:
        visit(statement)
    return nodes


def _constant_string(
    node: ast.AST,
    assignments: dict[str, list[ast.AST]] | None = None,
    resolving: frozenset[str] = frozenset(),
) -> str | None:
    """Fold the static string forms used by dynamic attribute lookups."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name) and assignments is not None and node.id not in resolving:
        sources = assignments.get(node.id, [])
        if len(sources) == 1:
            return _constant_string(
                sources[0],
                assignments,
                resolving | {node.id},
            )
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _constant_string(node.left, assignments, resolving)
        right = _constant_string(node.right, assignments, resolving)
        return left + right if left is not None and right is not None else None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
        left = _constant_string(node.left, assignments, resolving)
        right = node.right.value if isinstance(node.right, ast.Constant) and isinstance(node.right.value, int) else None
        if left is not None and right is not None:
            return left * right
        right_string = _constant_string(node.right, assignments, resolving)
        left_count = (
            node.left.value if isinstance(node.left, ast.Constant) and isinstance(node.left.value, int) else None
        )
        return right_string * left_count if right_string is not None and left_count is not None else None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
        template = _constant_string(node.left, assignments, resolving)
        mapping = _constant_string_mapping(node.right, assignments, resolving)
        if mapping is not None:
            replacement: str | tuple[str, ...] | dict[str, str] = mapping
        else:
            values = node.right.elts if isinstance(node.right, (ast.List, ast.Tuple)) else [node.right]
            parts = [_constant_string(value, assignments, resolving) for value in values]
            if template is None or any(part is None for part in parts):
                return None
            replacement = parts[0] if len(parts) == 1 else tuple(part for part in parts if part is not None)
        try:
            return template % replacement
        except (TypeError, ValueError):
            return None
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.FormattedValue):
                part = _constant_string(value.value, assignments, resolving)
            else:
                part = _constant_string(value, assignments, resolving)
            if part is None:
                return None
            parts.append(part)
        return "".join(parts)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "format":
        template = _constant_string(node.func.value, assignments, resolving)
        args = [_constant_string(value, assignments, resolving) for value in node.args]
        kwargs = {
            keyword.arg: _constant_string(keyword.value, assignments, resolving)
            for keyword in node.keywords
            if keyword.arg is not None
        }
        if (
            template is None
            or any(part is None for part in args)
            or len(kwargs) != len(node.keywords)
            or any(part is None for part in kwargs.values())
        ):
            return None
        try:
            return template.format(
                *(part for part in args if part is not None),
                **{key: part for key, part in kwargs.items() if part is not None},
            )
        except (IndexError, KeyError, ValueError):
            return None
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        value = _constant_string(node.func.value, assignments, resolving)
        args = [_constant_string(argument, assignments, resolving) for argument in node.args]
        if value is not None and not node.args and not node.keywords:
            if node.func.attr == "lower":
                return value.lower()
            if node.func.attr == "upper":
                return value.upper()
            if node.func.attr == "casefold":
                return value.casefold()
            if node.func.attr == "swapcase":
                return value.swapcase()
        if value is not None and node.func.attr == "replace" and len(node.args) in {2, 3}:
            if args[0] is None or args[1] is None:
                return None
            if len(node.args) == 2:
                return value.replace(args[0], args[1])
            count = node.args[2]
            if not isinstance(count, ast.Constant) or not isinstance(count.value, int):
                return None
            return value.replace(args[0], args[1], count.value)
        if value is not None and len(node.args) == 1 and args[0] is not None:
            if node.func.attr == "removeprefix":
                return value.removeprefix(args[0])
            if node.func.attr == "removesuffix":
                return value.removesuffix(args[0])
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "join"
        and not node.keywords
        and len(node.args) == 1
    ):
        separator = _constant_string(node.func.value, assignments, resolving)
        values = _constant_sequence_items(node.args[0], assignments, resolving)
        if separator is None or values is None:
            return None
        parts = [_constant_string(value, assignments, resolving) for value in values]
        if any(part is None for part in parts):
            return None
        return separator.join(part for part in parts if part is not None)
    return None


def _constant_sequence_items(
    node: ast.AST,
    assignments: dict[str, list[ast.AST]] | None = None,
    resolving: frozenset[str] = frozenset(),
) -> list[ast.AST] | None:
    if isinstance(node, ast.Name) and assignments is not None and node.id not in resolving:
        sources = assignments.get(node.id, [])
        if len(sources) == 1:
            return _constant_sequence_items(
                sources[0],
                assignments,
                resolving | {node.id},
            )
    if isinstance(node, (ast.List, ast.Tuple)):
        return list(node.elts)
    return None


def _constant_string_mapping(
    node: ast.AST,
    assignments: dict[str, list[ast.AST]] | None = None,
    resolving: frozenset[str] = frozenset(),
) -> dict[str, str] | None:
    """Fold a statically declared string-to-string mapping."""
    if isinstance(node, ast.Name) and assignments is not None and node.id not in resolving:
        sources = assignments.get(node.id, [])
        if len(sources) == 1:
            return _constant_string_mapping(
                sources[0],
                assignments,
                resolving | {node.id},
            )
    if not isinstance(node, ast.Dict) or any(key is None for key in node.keys):
        return None
    keys = [_constant_string(key, assignments, resolving) for key in node.keys if key is not None]
    values = [_constant_string(value, assignments, resolving) for value in node.values]
    if len(keys) != len(node.keys) or any(part is None for part in (*keys, *values)):
        return None
    return {key: value for key, value in zip(keys, values, strict=True) if key is not None and value is not None}


def _constant_mapping_keys(
    node: ast.AST,
    assignments: dict[str, list[ast.AST]] | None = None,
    resolving: frozenset[str] = frozenset(),
) -> set[str] | None:
    if isinstance(node, ast.Name) and assignments is not None and node.id not in resolving:
        sources = assignments.get(node.id, [])
        if len(sources) == 1:
            return _constant_mapping_keys(
                sources[0],
                assignments,
                resolving | {node.id},
            )
    if not isinstance(node, ast.Dict) or any(key is None for key in node.keys):
        return None
    keys = [_constant_string(key, assignments, resolving) for key in node.keys if key is not None]
    if len(keys) != len(node.keys) or any(key is None for key in keys):
        return None
    return {key for key in keys if key is not None}


def _dotted_name(parts: list[str]) -> ast.AST:
    value: ast.AST = ast.Name(id=parts[0], ctx=ast.Load())
    for part in parts[1:]:
        value = ast.Attribute(value=value, attr=part, ctx=ast.Load())
    return value


def _import_sources(nodes: list[ast.AST]) -> dict[str, list[ast.AST]]:
    """Represent statically provable imports as assignment sources."""
    sources: dict[str, list[ast.AST]] = {}
    for node in nodes:
        if isinstance(node, ast.Import):
            for alias in node.names:
                bound = alias.asname or alias.name.split(".")[0]
                imported = alias.name if alias.asname else alias.name.split(".")[0]
                sources.setdefault(bound, []).append(_dotted_name(imported.split(".")))
        elif isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                if alias.name == "*":
                    continue
                bound = alias.asname or alias.name
                sources.setdefault(bound, []).append(_dotted_name([*node.module.split("."), alias.name]))
    return sources


def _with_import_sources(
    assignments: dict[str, list[ast.AST]],
    nodes: list[ast.AST],
) -> dict[str, list[ast.AST]]:
    merged = {name: list(values) for name, values in assignments.items()}
    for name, values in _import_sources(nodes).items():
        merged.setdefault(name, []).extend(values)
    return merged


def _resolves_builtins_module(
    value: ast.AST,
    assignments: dict[str, list[ast.AST]] | None,
    resolving: frozenset[str] = frozenset(),
) -> bool:
    if isinstance(value, ast.Name) and value.id == "builtins":
        sources = assignments.get(value.id, []) if assignments is not None else []
        return not sources or all(isinstance(source, ast.Name) and source.id == "builtins" for source in sources)
    if isinstance(value, ast.Name) and assignments is not None and value.id not in resolving:
        sources = assignments.get(value.id, [])
        return len(sources) == 1 and _resolves_builtins_module(
            sources[0],
            assignments,
            resolving | {value.id},
        )
    return False


def _is_builtins_dict_expression(
    value: ast.AST,
    assignments: dict[str, list[ast.AST]] | None,
    resolving: frozenset[str] = frozenset(),
) -> bool:
    if (
        isinstance(value, ast.Attribute)
        and value.attr == "__dict__"
        and _resolves_builtins_module(value.value, assignments, resolving)
    ):
        return True
    if (
        isinstance(value, ast.Call)
        and _resolves_builtin_member(value.func, frozenset({"vars"}), assignments, resolving)
        and len(value.args) == 1
        and _resolves_builtins_module(value.args[0], assignments, resolving)
    ):
        return True
    if isinstance(value, ast.Name) and assignments is not None and value.id not in resolving:
        sources = assignments.get(value.id, [])
        return len(sources) == 1 and _is_builtins_dict_expression(
            sources[0],
            assignments,
            resolving | {value.id},
        )
    return False


def _resolves_builtin_member(
    value: ast.AST,
    members: frozenset[str],
    assignments: dict[str, list[ast.AST]] | None,
    resolving: frozenset[str] = frozenset(),
) -> bool:
    if isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute):
        if (
            value.func.attr in {"get", "__getitem__"}
            and _is_builtins_dict_expression(value.func.value, assignments, resolving)
            and value.args
            and _constant_string(value.args[0], assignments, resolving) in members
        ):
            return True
        if (
            value.func.attr in {"get", "__getitem__"}
            and _resolves_builtin_member(value.func.value, frozenset({"dict"}), assignments, resolving)
            and len(value.args) >= 2
            and _is_builtins_dict_expression(value.args[0], assignments, resolving)
            and _constant_string(value.args[1], assignments, resolving) in members
        ):
            return True
    if (
        isinstance(value, ast.Subscript)
        and _is_builtins_dict_expression(value.value, assignments, resolving)
        and _constant_string(value.slice, assignments, resolving) in members
    ):
        return True
    if isinstance(value, ast.Name):
        if value.id in members:
            sources = assignments.get(value.id, []) if assignments is not None else []
            if not sources:
                return True
            return (
                len(sources) == 1
                and not (isinstance(sources[0], ast.Name) and sources[0].id == value.id)
                and _resolves_builtin_member(
                    sources[0],
                    members,
                    assignments,
                    resolving | {value.id},
                )
            )
        if assignments is not None and value.id not in resolving:
            sources = assignments.get(value.id, [])
            return len(sources) == 1 and _resolves_builtin_member(
                sources[0],
                members,
                assignments,
                resolving | {value.id},
            )
        return False
    return (
        isinstance(value, ast.Attribute)
        and value.attr in members
        and _resolves_builtins_module(value.value, assignments, resolving)
    )


def _resolves_named_module(
    value: ast.AST,
    module: str,
    assignments: dict[str, list[ast.AST]] | None,
    resolving: frozenset[str] = frozenset(),
) -> bool:
    if isinstance(value, ast.Name) and value.id == module:
        sources = assignments.get(value.id, []) if assignments is not None else []
        return not sources or all(isinstance(source, ast.Name) and source.id == module for source in sources)
    if isinstance(value, ast.Name) and assignments is not None and value.id not in resolving:
        sources = assignments.get(value.id, [])
        return len(sources) == 1 and _resolves_named_module(
            sources[0],
            module,
            assignments,
            resolving | {value.id},
        )
    return False


def _resolves_operator_member(
    value: ast.AST,
    members: frozenset[str],
    assignments: dict[str, list[ast.AST]] | None,
    resolving: frozenset[str] = frozenset(),
) -> bool:
    if isinstance(value, ast.Call):
        recognised, owner, name = _dynamic_attribute_access(value, assignments)
        if (
            recognised
            and owner is not None
            and name in members
            and _resolves_named_module(owner, "operator", assignments, resolving)
        ):
            return True
    if isinstance(value, ast.Name) and assignments is not None and value.id not in resolving:
        sources = assignments.get(value.id, [])
        return len(sources) == 1 and _resolves_operator_member(
            sources[0],
            members,
            assignments,
            resolving | {value.id},
        )
    return (
        isinstance(value, ast.Attribute)
        and value.attr in members
        and _resolves_named_module(value.value, "operator", assignments, resolving)
    )


def _resolves_functools_member(
    value: ast.AST,
    members: frozenset[str],
    assignments: dict[str, list[ast.AST]] | None,
    resolving: frozenset[str] = frozenset(),
) -> bool:
    if isinstance(value, ast.Name) and assignments is not None and value.id not in resolving:
        sources = assignments.get(value.id, [])
        return len(sources) == 1 and _resolves_functools_member(
            sources[0],
            members,
            assignments,
            resolving | {value.id},
        )
    return (
        isinstance(value, ast.Attribute)
        and value.attr in members
        and _resolves_named_module(value.value, "functools", assignments, resolving)
    )


def _operator_factory_access(
    node: ast.Call,
    assignments: dict[str, list[ast.AST]] | None,
) -> tuple[str | None, ast.AST | None, str | None, list[ast.AST]]:
    """Resolve ``operator.attrgetter``/``methodcaller`` applications."""
    if not isinstance(node.func, ast.Call) or not node.args:
        return None, None, None, []
    factory = node.func
    if _resolves_operator_member(factory.func, frozenset({"attrgetter"}), assignments):
        if len(factory.args) != 1 or factory.keywords:
            return "attrgetter", node.args[0], None, []
        return "attrgetter", node.args[0], _constant_string(factory.args[0], assignments), []
    if _resolves_operator_member(factory.func, frozenset({"methodcaller"}), assignments):
        if not factory.args:
            return "methodcaller", node.args[0], None, []
        return (
            "methodcaller",
            node.args[0],
            _constant_string(factory.args[0], assignments),
            list(factory.args[1:]),
        )
    return None, None, None, []


def _dynamic_attribute_access(
    node: ast.Call,
    assignments: dict[str, list[ast.AST]] | None = None,
) -> tuple[bool, ast.AST | None, str | None]:
    """Return whether a getattr-style call is recognised, plus its owner/name."""

    def resolves_getattr(value: ast.AST, resolving: frozenset[str] = frozenset()) -> bool:
        if _resolves_builtin_member(value, frozenset({"getattr"}), assignments, resolving):
            return True
        if isinstance(value, ast.Attribute):
            if value.attr in {"__getattribute__", "__getattr__"} and _resolves_builtin_member(
                value.value,
                frozenset({"object", "type"}),
                assignments,
                resolving,
            ):
                return True
        if isinstance(value, ast.Name) and assignments is not None and value.id not in resolving:
            sources = assignments.get(value.id, [])
            return len(sources) == 1 and resolves_getattr(sources[0], resolving | {value.id})
        return False

    factory_kind, factory_owner, factory_name, _ = _operator_factory_access(node, assignments)
    if factory_kind is not None:
        return True, factory_owner, factory_name

    if resolves_getattr(node.func) and len(node.args) >= 2:
        return True, node.args[0], _constant_string(node.args[1], assignments)
    if isinstance(node.func, ast.Attribute) and node.func.attr in {"__getattribute__", "__getattr__"} and node.args:
        base = node.func.value
        unbound = _resolves_builtin_member(
            base,
            frozenset({"object", "type"}),
            assignments,
        )
        name_index = 1 if unbound else 0
        if len(node.args) > name_index:
            owner = node.args[0] if unbound else node.func.value
            return True, owner, _constant_string(node.args[name_index], assignments)
    return False, None, None


def _attribute_path(owner: ast.AST, path: str) -> ast.AST:
    value = owner
    for part in path.split("."):
        value = ast.Attribute(value=value, attr=part, ctx=ast.Load())
    return value


def _dynamic_attribute_name(
    node: ast.Call,
    assignments: dict[str, list[ast.AST]] | None = None,
) -> str | None:
    """Return the statically provable name read by getattr-style calls."""
    _, _, name = _dynamic_attribute_access(node, assignments)
    return name


def _record_argument_defaults(
    assignments: dict[str, list[ast.AST]],
    arguments: ast.arguments,
) -> None:
    positional = [*arguments.posonlyargs, *arguments.args]
    if arguments.defaults:
        for argument, default in zip(positional[-len(arguments.defaults) :], arguments.defaults, strict=True):
            assignments.setdefault(argument.arg, []).append(default)
    for argument, default in zip(arguments.kwonlyargs, arguments.kw_defaults, strict=True):
        if default is not None:
            assignments.setdefault(argument.arg, []).append(default)


def _argument_names(arguments: ast.arguments) -> set[str]:
    names = {argument.arg for argument in (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs)}
    if arguments.vararg is not None:
        names.add(arguments.vararg.arg)
    if arguments.kwarg is not None:
        names.add(arguments.kwarg.arg)
    return names


def _record_assignment_target(
    assignments: dict[str, list[ast.AST]],
    target: ast.AST,
    source: ast.AST,
) -> None:
    if isinstance(target, ast.Name):
        assignments.setdefault(target.id, []).append(source)
        return
    if isinstance(target, ast.Starred):
        _record_assignment_target(assignments, target.value, source)
        return
    if not isinstance(target, (ast.Tuple, ast.List)):
        return
    if isinstance(source, (ast.Tuple, ast.List)) and len(target.elts) == len(source.elts):
        for child_target, child_source in zip(target.elts, source.elts, strict=True):
            _record_assignment_target(assignments, child_target, child_source)
        return
    for child_target in target.elts:
        _record_assignment_target(assignments, child_target, source)


def _record_pattern_targets(
    assignments: dict[str, list[ast.AST]],
    pattern: ast.pattern,
) -> None:
    """Record every name captured by structural pattern matching."""
    if isinstance(pattern, ast.MatchAs):
        if pattern.name:
            assignments.setdefault(pattern.name, []).append(ast.Constant(value=None))
        if pattern.pattern is not None:
            _record_pattern_targets(assignments, pattern.pattern)
    elif isinstance(pattern, ast.MatchStar):
        if pattern.name:
            assignments.setdefault(pattern.name, []).append(ast.Constant(value=None))
    elif isinstance(pattern, ast.MatchMapping):
        for child in pattern.patterns:
            _record_pattern_targets(assignments, child)
        if pattern.rest:
            assignments.setdefault(pattern.rest, []).append(ast.Constant(value=None))
    elif isinstance(pattern, ast.MatchClass):
        for child in (*pattern.patterns, *pattern.kwd_patterns):
            _record_pattern_targets(assignments, child)
    elif isinstance(pattern, ast.MatchSequence):
        for child in pattern.patterns:
            _record_pattern_targets(assignments, child)
    elif isinstance(pattern, ast.MatchOr):
        for child in pattern.patterns:
            _record_pattern_targets(assignments, child)


def _assignment_sources(function: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, list[ast.AST]]:
    assignments: dict[str, list[ast.AST]] = {}
    _record_argument_defaults(assignments, function.args)
    for node in _scope_nodes(function):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                _record_assignment_target(assignments, target, node.value)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            _record_assignment_target(assignments, node.target, node.value)
        elif isinstance(node, ast.NamedExpr):
            _record_assignment_target(assignments, node.target, node.value)
        elif isinstance(node, ast.AugAssign):
            _record_assignment_target(assignments, node.target, node.value)
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            _record_assignment_target(assignments, node.target, node.iter)
        elif isinstance(node, ast.With):
            for item in node.items:
                if item.optional_vars is not None:
                    _record_assignment_target(assignments, item.optional_vars, item.context_expr)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            assignments.setdefault(node.name, []).append(ast.Constant(value=None))
        elif isinstance(node, ast.match_case):
            _record_pattern_targets(assignments, node.pattern)
        elif isinstance(node, ast.Delete):
            for target in node.targets:
                _record_assignment_target(assignments, target, ast.Constant(value=None))
    return assignments


def _lambda_assignment_sources(function: ast.Lambda) -> dict[str, list[ast.AST]]:
    assignments: dict[str, list[ast.AST]] = {}
    _record_argument_defaults(assignments, function.args)

    def visit(node: ast.AST) -> None:
        if isinstance(node, ast.Lambda) and node is not function:
            return
        if isinstance(node, ast.NamedExpr):
            _record_assignment_target(assignments, node.target, node.value)
        for child in ast.iter_child_nodes(node):
            visit(child)

    visit(function.body)
    return assignments


def _module_assignment_sources(module: ast.Module) -> dict[str, list[ast.AST]]:
    """Return module-scope assignments without descending into local scopes."""
    assignments: dict[str, list[ast.AST]] = {}
    for node in _module_scope_nodes(module):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                _record_assignment_target(assignments, target, node.value)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            _record_assignment_target(assignments, node.target, node.value)
        elif isinstance(node, ast.NamedExpr):
            _record_assignment_target(assignments, node.target, node.value)
        elif isinstance(node, ast.AugAssign):
            _record_assignment_target(assignments, node.target, node.value)
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            _record_assignment_target(assignments, node.target, node.iter)
        elif isinstance(node, ast.With):
            for item in node.items:
                if item.optional_vars is not None:
                    _record_assignment_target(assignments, item.optional_vars, item.context_expr)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            assignments.setdefault(node.name, []).append(ast.Constant(value=None))
        elif isinstance(node, ast.match_case):
            _record_pattern_targets(assignments, node.pattern)
        elif isinstance(node, ast.Delete):
            for target in node.targets:
                _record_assignment_target(assignments, target, ast.Constant(value=None))
    return assignments


def _call_name(value: ast.Call) -> str:
    if isinstance(value.func, ast.Name):
        return value.func.id
    if isinstance(value.func, ast.Attribute):
        return value.func.attr
    return ""


_DEFAULT_STATE_PROVIDERS = frozenset(
    {
        "_gather_safety_state",
        "gather_safety_state",
        "self._gather_safety_state",
        "self._portfolio_state_provider",
    }
)
_DEFAULT_STATE_WRAPPERS = frozenset(
    {
        "_call_on_owner_loop",
        "_run_on_client_loop",
        "self.run_router_call",
    }
)

_STATE_PROVIDERS_BY_FILE: dict[str, frozenset[str]] = {
    "packages/core/core/src/flinttrade_core/webhook_dispatch.py": frozenset({"self._gather_safety_state"}),
    "packages/core/core/src/flinttrade_core/smart_order_routes.py": frozenset(
        {
            "gather_safety_state",
            "self._portfolio_state_provider",
        }
    ),
    "packages/core/core/src/flinttrade_core/order_routes.py": frozenset({"_gather_safety_state"}),
    "packages/services/ditto/src/flinttrade_ditto/runtime.py": frozenset({"gather_safety_state"}),
    "packages/services/engine/src/flinttrade_engine/bracket_order.py": frozenset({"gather_safety_state"}),
    "packages/services/engine/src/flinttrade_engine/strategy_execution.py": frozenset(
        {
            "self._portfolio_state_provider",
        }
    ),
}
_STATE_WRAPPERS_BY_FILE: dict[str, frozenset[str]] = {
    "packages/core/core/src/flinttrade_core/smart_order_routes.py": frozenset({"_run_on_client_loop"}),
    "packages/services/ditto/src/flinttrade_ditto/runtime.py": frozenset({"self.run_router_call"}),
    "packages/services/engine/src/flinttrade_engine/bracket_order.py": frozenset({"_call_on_owner_loop"}),
}


def _call_token(value: ast.Call) -> str:
    if isinstance(value.func, ast.Name):
        return value.func.id
    if (
        isinstance(value.func, ast.Attribute)
        and isinstance(value.func.value, ast.Name)
        and value.func.value.id == "self"
    ):
        return f"self.{value.func.attr}"
    return ""


def _is_self_alias_name(
    name: str,
    assignments: dict[str, list[ast.AST]],
    resolving: frozenset[str] = frozenset(),
) -> bool:
    if name == "self":
        return True
    if name in resolving:
        return False
    return any(
        isinstance(source, ast.Name) and _is_self_alias_name(source.id, assignments, resolving | {name})
        for source in assignments.get(name, [])
    )


def _is_self_dict_expression(
    value: ast.AST,
    assignments: dict[str, list[ast.AST]],
    resolving: frozenset[str] = frozenset(),
) -> bool:
    if (
        isinstance(value, ast.Attribute)
        and value.attr == "__dict__"
        and isinstance(value.value, ast.Name)
        and _is_self_alias_name(value.value.id, assignments)
    ):
        return True
    if isinstance(value, ast.Call):
        recognised, owner, name = _dynamic_attribute_access(value, assignments)
        if (
            recognised
            and name == "__dict__"
            and isinstance(owner, ast.Name)
            and _is_self_alias_name(owner.id, assignments)
        ):
            return True
    if (
        isinstance(value, ast.Call)
        and _resolves_builtin_member(
            value.func,
            frozenset({"vars"}),
            assignments,
            resolving,
        )
        and len(value.args) == 1
        and isinstance(value.args[0], ast.Name)
        and _is_self_alias_name(value.args[0].id, assignments)
    ):
        return True
    if isinstance(value, ast.Name) and value.id not in resolving:
        return any(
            _is_self_dict_expression(source, assignments, resolving | {value.id})
            for source in assignments.get(value.id, [])
        )
    return False


def _is_sys_modules_entry(
    value: ast.AST,
    assignments: dict[str, list[ast.AST]],
    resolving: frozenset[str] = frozenset(),
) -> bool:
    if isinstance(value, ast.Subscript):
        modules = value.value
        return (
            isinstance(modules, ast.Attribute)
            and modules.attr == "modules"
            and _resolves_named_module(modules.value, "sys", assignments, resolving)
        )
    if (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Attribute)
        and value.func.attr in {"get", "__getitem__"}
    ):
        modules = value.func.value
        return (
            isinstance(modules, ast.Attribute)
            and modules.attr == "modules"
            and _resolves_named_module(modules.value, "sys", assignments, resolving)
        )
    if isinstance(value, ast.Name) and value.id not in resolving:
        return any(
            _is_sys_modules_entry(source, assignments, resolving | {value.id})
            for source in assignments.get(value.id, [])
        )
    return False


def _is_module_object_expression(
    value: ast.AST,
    assignments: dict[str, list[ast.AST]],
    resolving: frozenset[str] = frozenset(),
) -> bool:
    if _is_sys_modules_entry(value, assignments, resolving):
        return True
    if isinstance(value, ast.Name):
        if value.id in resolving:
            return False
        lowered = value.id.lower()
        if lowered in {"module", "mod"} or lowered.endswith(("_module", "_mod")):
            return True
        sources = assignments.get(value.id, [])
        if sources:
            return len(sources) == 1 and _is_module_object_expression(
                sources[0],
                assignments,
                resolving | {value.id},
            )
        return False
    return False


def _is_explicit_module_dict_expression(
    value: ast.AST,
    assignments: dict[str, list[ast.AST]],
    resolving: frozenset[str] = frozenset(),
) -> bool:
    if (
        isinstance(value, ast.Attribute)
        and value.attr == "__dict__"
        and _is_module_object_expression(value.value, assignments, resolving)
    ):
        return True
    if (
        isinstance(value, ast.Call)
        and _resolves_builtin_member(value.func, frozenset({"vars"}), assignments, resolving)
        and len(value.args) == 1
        and _is_module_object_expression(value.args[0], assignments, resolving)
    ):
        return True
    if isinstance(value, ast.Name) and value.id not in resolving:
        return any(
            _is_explicit_module_dict_expression(source, assignments, resolving | {value.id})
            for source in assignments.get(value.id, [])
        )
    return False


def _is_globals_dict_expression(
    value: ast.AST,
    assignments: dict[str, list[ast.AST]],
    resolving: frozenset[str] = frozenset(),
) -> bool:
    if (
        isinstance(value, ast.Call)
        and _resolves_builtin_member(
            value.func,
            frozenset({"globals"}),
            assignments,
            resolving,
        )
        and not value.args
        and not value.keywords
    ):
        return True
    if _is_explicit_module_dict_expression(value, assignments, resolving):
        return True
    if isinstance(value, ast.Name) and value.id not in resolving:
        return any(
            _is_globals_dict_expression(source, assignments, resolving | {value.id})
            for source in assignments.get(value.id, [])
        )
    return False


def _is_module_globals_dict_expression(
    value: ast.AST,
    assignments: dict[str, list[ast.AST]],
    resolving: frozenset[str] = frozenset(),
) -> bool:
    """Recognise module globals, including module-scope ``vars()``/``locals()``."""
    if _is_globals_dict_expression(value, assignments, resolving):
        return True
    if (
        isinstance(value, ast.Call)
        and _resolves_builtin_member(
            value.func,
            frozenset({"vars", "locals"}),
            assignments,
            resolving,
        )
        and not value.args
        and not value.keywords
    ):
        return True
    if isinstance(value, ast.Name) and value.id not in resolving:
        return any(
            _is_module_globals_dict_expression(source, assignments, resolving | {value.id})
            for source in assignments.get(value.id, [])
        )
    return False


def _resolved_callable_values(
    value: ast.AST,
    assignments: dict[str, list[ast.AST]],
    resolving: frozenset[str] = frozenset(),
) -> list[ast.AST]:
    """Follow statically assigned callable aliases without guessing."""
    if isinstance(value, ast.Name) and value.id not in resolving:
        sources = assignments.get(value.id, [])
        if sources:
            return [
                resolved
                for source in sources
                for resolved in _resolved_callable_values(
                    source,
                    assignments,
                    resolving | {value.id},
                )
            ]
    if isinstance(value, ast.Subscript):
        resolved_items = _resolved_subscript_values(value, assignments, resolving)
        if resolved_items:
            return [
                resolved
                for item in resolved_items
                for resolved in _resolved_callable_values(item, assignments, resolving)
            ]
    if isinstance(value, ast.Call):
        mapping_values = _resolved_mapping_call_values(value, assignments, resolving)
        if mapping_values:
            return [
                resolved
                for item in mapping_values
                for resolved in _resolved_callable_values(item, assignments, resolving)
            ]
        if _resolves_functools_member(value.func, frozenset({"partial"}), assignments, resolving) and value.args:
            return _resolved_callable_values(value.args[0], assignments, resolving)
        factory_kind, factory_owner, factory_name, _ = _operator_factory_access(value, assignments)
        if factory_kind == "attrgetter" and factory_owner is not None and factory_name is not None:
            return [_attribute_path(factory_owner, factory_name)]
        recognised, owner, name = _dynamic_attribute_access(value, assignments)
        if recognised and owner is not None and name is not None:
            return [_attribute_path(owner, name)]
    return [value]


def _constant_subscript_key(
    value: ast.AST,
    assignments: dict[str, list[ast.AST]],
) -> str | int | None:
    string = _constant_string(value, assignments)
    if string is not None:
        return string
    if isinstance(value, ast.Constant) and isinstance(value.value, int):
        return value.value
    if (
        isinstance(value, ast.UnaryOp)
        and isinstance(value.op, ast.USub)
        and isinstance(value.operand, ast.Constant)
        and isinstance(value.operand.value, int)
    ):
        return -value.operand.value
    return None


def _resolved_subscript_values(
    value: ast.Subscript,
    assignments: dict[str, list[ast.AST]],
    resolving: frozenset[str] = frozenset(),
) -> list[ast.AST]:
    """Resolve statically declared dict/list/tuple container lookups."""
    key = _constant_subscript_key(value.slice, assignments)
    if key is None:
        return []
    owners = _resolved_callable_values(value.value, assignments, resolving)
    resolved: list[ast.AST] = []
    for owner in owners:
        if isinstance(owner, ast.Dict):
            for mapping_key, mapping_value in zip(owner.keys, owner.values, strict=True):
                if mapping_key is not None and _constant_subscript_key(mapping_key, assignments) == key:
                    resolved.append(mapping_value)
        elif isinstance(owner, (ast.List, ast.Tuple)) and isinstance(key, int):
            index = key if key >= 0 else len(owner.elts) + key
            if 0 <= index < len(owner.elts):
                resolved.append(owner.elts[index])
    return resolved


def _resolved_mapping_call_values(
    value: ast.Call,
    assignments: dict[str, list[ast.AST]],
    resolving: frozenset[str] = frozenset(),
) -> list[ast.AST]:
    """Resolve a statically bound mapping ``get``/``__getitem__`` call."""
    resolved: list[ast.AST] = []
    for function in _resolved_callable_values(value.func, assignments, resolving):
        if not isinstance(function, ast.Attribute) or function.attr not in {"get", "__getitem__"}:
            continue
        if not value.args:
            continue
        lookup = ast.Subscript(
            value=function.value,
            slice=value.args[0],
            ctx=ast.Load(),
        )
        resolved.extend(_resolved_subscript_values(lookup, assignments, resolving))
    return resolved


def _mapping_mutation_keys(
    node: ast.Call,
    assignments: dict[str, list[ast.AST]],
    owner_predicate: Callable[[ast.AST, dict[str, list[ast.AST]]], bool],
) -> tuple[bool, set[str] | None]:
    """Return keys changed through bound or unbound ``dict`` mutators.

    ``None`` means the mutation is recognised but its affected keys cannot be
    proved statically, so callers must conservatively treat every protected key
    as changed.
    """

    factory_kind, factory_owner, factory_name, factory_args = _operator_factory_access(node, assignments)
    if factory_kind == "methodcaller" and factory_owner is not None and owner_predicate(factory_owner, assignments):
        if factory_name in {"__setitem__", "setdefault", "pop", "__delitem__"}:
            if not factory_args:
                return True, None
            key = _constant_string(factory_args[0], assignments)
            return True, {key} if key is not None else None
        if factory_name in {"update", "__ior__", "clear", "popitem"} or factory_name is None:
            return True, None

    def inspect_callable(function: ast.AST) -> tuple[bool, set[str] | None]:
        functional_method = (
            function.id
            if isinstance(function, ast.Name)
            else function.attr
            if isinstance(function, ast.Attribute)
            else ""
        )
        if functional_method in {"setitem", "delitem", "ior"}:
            if not node.args or not owner_predicate(node.args[0], assignments):
                return False, set()
            if functional_method == "ior":
                if len(node.args) < 2:
                    return True, None
                return True, _constant_mapping_keys(node.args[1], assignments)
            if len(node.args) < 2:
                return True, None
            key = _constant_string(node.args[1], assignments)
            return True, {key} if key is not None else None

        if not isinstance(function, ast.Attribute):
            return False, set()

        method = function.attr
        arguments = list(node.args)
        if owner_predicate(function.value, assignments):
            mutation_arguments = arguments
        elif (
            _resolves_builtin_member(
                function.value,
                frozenset({"dict"}),
                assignments,
            )
            and arguments
            and owner_predicate(arguments[0], assignments)
        ):
            mutation_arguments = arguments[1:]
        else:
            return False, set()

        if method in {"update", "__ior__"}:
            if any(keyword.arg is None for keyword in node.keywords):
                return True, None
            keys = {keyword.arg for keyword in node.keywords if keyword.arg is not None}
            if not mutation_arguments:
                return True, keys if method == "update" else None
            mapped = _constant_mapping_keys(mutation_arguments[0], assignments)
            if mapped is None:
                return True, None
            return True, keys | mapped
        if method in {"__setitem__", "setdefault", "pop", "__delitem__"}:
            if not mutation_arguments:
                return True, None
            key = _constant_string(mutation_arguments[0], assignments)
            return True, {key} if key is not None else None
        if method in {"clear", "popitem"}:
            return True, None
        return False, set()

    recognised = False
    combined: set[str] = set()
    for function in _resolved_callable_values(node.func, assignments):
        candidate_recognised, keys = inspect_callable(function)
        if not candidate_recognised:
            continue
        recognised = True
        if keys is None:
            return True, None
        combined.update(keys)
    return recognised, combined


def _mapping_lookup_accesses(
    node: ast.Call,
    assignments: dict[str, list[ast.AST]],
) -> list[tuple[ast.AST, str | None]]:
    """Return mapping owners and keys recovered through lookup APIs."""
    accesses: list[tuple[ast.AST, str | None]] = []
    for function in _resolved_callable_values(node.func, assignments):
        if isinstance(function, ast.Attribute) and function.attr in {"get", "__getitem__"}:
            if _resolves_builtin_member(
                function.value,
                frozenset({"dict"}),
                assignments,
            ):
                if node.args:
                    key = _constant_string(node.args[1], assignments) if len(node.args) >= 2 else None
                    accesses.append((node.args[0], key))
                continue
            key = _constant_string(node.args[0], assignments) if node.args else None
            accesses.append((function.value, key))
            continue
        functional_name = (
            function.id
            if isinstance(function, ast.Name)
            else function.attr
            if isinstance(function, ast.Attribute)
            else ""
        )
        if functional_name == "getitem" and len(node.args) >= 2:
            accesses.append((node.args[0], _constant_string(node.args[1], assignments)))
    return accesses


def _mapping_lookup_name(
    node: ast.Call,
    assignments: dict[str, list[ast.AST]],
) -> str | None:
    """Return a statically named key recovered through mapping lookup APIs."""
    return next((name for _, name in _mapping_lookup_accesses(node, assignments) if name is not None), None)


def _self_attribute_mutation(
    node: ast.Call,
    assignments: dict[str, list[ast.AST]],
) -> tuple[bool, str | None]:
    """Return whether a setattr variant mutates self and its static name."""
    factory_kind, factory_owner, factory_name, factory_args = _operator_factory_access(node, assignments)
    if (
        factory_kind == "methodcaller"
        and factory_owner is not None
        and isinstance(factory_owner, ast.Name)
        and _is_self_alias_name(factory_owner.id, assignments)
        and factory_name in {"__setattr__", "__delattr__"}
    ):
        return True, _constant_string(factory_args[0], assignments) if factory_args else None
    for function in _resolved_callable_values(node.func, assignments):
        if _resolves_builtin_member(
            function,
            frozenset({"setattr", "delattr"}),
            assignments,
        ):
            if (
                len(node.args) >= 2
                and isinstance(node.args[0], ast.Name)
                and _is_self_alias_name(node.args[0].id, assignments)
            ):
                return True, _constant_string(node.args[1], assignments)
            continue
        if not isinstance(function, ast.Attribute) or function.attr not in {
            "__setattr__",
            "__delattr__",
        }:
            continue
        if (
            isinstance(function.value, ast.Call)
            and isinstance(function.value.func, ast.Name)
            and function.value.func.id == "super"
        ):
            return True, _constant_string(node.args[0], assignments) if node.args else None
        if isinstance(function.value, ast.Name) and _is_self_alias_name(
            function.value.id,
            assignments,
        ):
            return True, _constant_string(node.args[0], assignments) if node.args else None
        if (
            _resolves_builtin_member(
                function.value,
                frozenset({"object", "type"}),
                assignments,
            )
            and len(node.args) >= 2
            and isinstance(node.args[0], ast.Name)
            and _is_self_alias_name(node.args[0].id, assignments)
        ):
            return True, _constant_string(node.args[1], assignments)
    return False, None


def _module_attribute_mutation(
    node: ast.Call,
    assignments: dict[str, list[ast.AST]],
) -> tuple[bool, str | None]:
    """Return whether a reflective call mutates a module and its static name."""
    factory_kind, factory_owner, factory_name, factory_args = _operator_factory_access(node, assignments)
    if (
        factory_kind == "methodcaller"
        and factory_owner is not None
        and _is_module_object_expression(factory_owner, assignments)
        and factory_name in {"__setattr__", "__delattr__"}
    ):
        return True, _constant_string(factory_args[0], assignments) if factory_args else None

    for function in _resolved_callable_values(node.func, assignments):
        if _resolves_builtin_member(function, frozenset({"setattr", "delattr"}), assignments):
            if len(node.args) >= 2 and _is_module_object_expression(node.args[0], assignments):
                return True, _constant_string(node.args[1], assignments)
            continue
        if not isinstance(function, ast.Attribute) or function.attr not in {
            "__setattr__",
            "__delattr__",
        }:
            continue
        if _is_module_object_expression(function.value, assignments):
            return True, _constant_string(node.args[0], assignments) if node.args else None
        if (
            _resolves_builtin_member(function.value, frozenset({"object", "type"}), assignments)
            and len(node.args) >= 2
            and _is_module_object_expression(node.args[0], assignments)
        ):
            return True, _constant_string(node.args[1], assignments)
    return False, None


def _function_resolution_assignments(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    inherited_assignments: dict[str, list[ast.AST]] | None = None,
) -> dict[str, list[ast.AST]]:
    nodes = _scope_nodes(function)
    assignments = _with_import_sources(_assignment_sources(function), nodes)
    for name in _rebound_names(function, assignments):
        assignments.setdefault(name, [ast.Constant(value=None)])
    for name, sources in (inherited_assignments or {}).items():
        assignments.setdefault(name, sources)
    return assignments


def _rebound_self_attributes(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    inherited_assignments: dict[str, list[ast.AST]] | None = None,
) -> set[str]:
    rebound: set[str] = set()
    nodes = _scope_nodes(function)
    assignments = _function_resolution_assignments(function, inherited_assignments)

    def is_self_alias(name: str, resolving: frozenset[str] = frozenset()) -> bool:
        if name == "self":
            return True
        if name in resolving:
            return False
        return any(
            isinstance(source, ast.Name) and is_self_alias(source.id, resolving | {name})
            for source in assignments.get(name, [])
        )

    def collect(target: ast.AST) -> None:
        if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and is_self_alias(target.value.id):
            rebound.add("*" if target.attr == "__dict__" else target.attr)
        elif isinstance(target, ast.Subscript):
            owner = target.value
            if _is_self_dict_expression(owner, assignments):
                attribute_name = _constant_string(target.slice, assignments)
                rebound.add(attribute_name if attribute_name is not None else "*")
        elif isinstance(target, ast.Starred):
            collect(target.value)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for child in target.elts:
                collect(child)

    for node in nodes:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                collect(target)
        elif isinstance(node, ast.AugAssign):
            if isinstance(node.op, ast.BitOr) and _is_self_dict_expression(node.target, assignments):
                keys = _constant_mapping_keys(node.value, assignments)
                rebound.update(keys if keys is not None else {"*"})
            else:
                collect(node.target)
        elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)):
            collect(node.target)
        elif isinstance(node, ast.Delete):
            for target in node.targets:
                collect(target)
        elif isinstance(node, ast.Call):
            recognised, keys = _mapping_mutation_keys(
                node,
                assignments,
                _is_self_dict_expression,
            )
            if recognised:
                if keys is None:
                    rebound.add("*")
                else:
                    rebound.update(keys)
                continue
            mutates_self, attribute_name = _self_attribute_mutation(node, assignments)
            if mutates_self:
                rebound.add(attribute_name if attribute_name not in {None, "__dict__"} else "*")
    return rebound


def _rebound_names(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    assignments: dict[str, list[ast.AST]],
) -> set[str]:
    rebound = set(assignments)
    rebound.update(_argument_names(function.args))
    for node in _scope_nodes(function):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            rebound.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                bound_name = alias.asname or alias.name.split(".")[0]
                canonical_import = (
                    isinstance(node, ast.ImportFrom)
                    and alias.asname is None
                    and (
                        (
                            alias.name == "gather_safety_state"
                            and node.module in {"l2_state", "flinttrade_core.l2_state"}
                        )
                        or (alias.name == "_run_on_client_loop" and node.module == "order_routes")
                    )
                )
                if not canonical_import:
                    rebound.add(bound_name)
    return rebound


def _parent_nodes(tree: ast.AST) -> dict[int, ast.AST]:
    return {id(child): parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}


def _lexical_assignment_sources(
    node: ast.AST,
    tree: ast.Module,
    parents: dict[int, ast.AST],
    cache: dict[int, dict[str, list[ast.AST]]] | None = None,
) -> dict[str, list[ast.AST]]:
    """Return local, enclosing, and module bindings visible to ``node``."""
    scope: ast.AST | None = node
    while scope is not None and not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.Module)):
        scope = parents.get(id(scope))
    cache_key = id(scope) if scope is not None else id(tree)
    if cache is not None and cache_key in cache:
        return cache[cache_key]

    visible: dict[str, list[ast.AST]] = {}
    parent: ast.AST | None = node
    while parent is not None:
        if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assignments = _with_import_sources(
                _assignment_sources(parent),
                _scope_nodes(parent),
            )
            bound_names = _rebound_names(parent, assignments)
            for name in bound_names:
                visible.setdefault(name, assignments.get(name, [ast.Constant(value=None)]))
        elif isinstance(parent, ast.Lambda):
            assignments = _lambda_assignment_sources(parent)
            for name in _argument_names(parent.args) | set(assignments):
                visible.setdefault(name, assignments.get(name, [ast.Constant(value=None)]))
        if isinstance(parent, ast.Module):
            module_assignments = _with_import_sources(
                _module_assignment_sources(tree),
                _module_scope_nodes(tree),
            )
            for name, sources in module_assignments.items():
                visible.setdefault(name, sources)
            if cache is not None:
                cache[cache_key] = visible
            return visible
        parent = parents.get(id(parent))
    return visible


def _enclosing_function_rebindings(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    parents: dict[int, ast.AST],
    *,
    relative: str = "",
) -> tuple[set[str], set[str]]:
    """Return names and ``self`` attributes rebound in enclosing closures."""
    rebound_names: set[str] = set()
    rebound_self_attributes: set[str] = set()
    parent = parents.get(id(function))
    while parent is not None:
        if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assignments = _assignment_sources(parent)
            local_rebound_names = _rebound_names(parent, assignments)
            if (
                relative == "packages/services/engine/src/flinttrade_engine/bracket_order.py"
                and "_call_on_owner_loop" not in assignments
                and any(
                    isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "_call_on_owner_loop"
                    for node in _scope_nodes(parent)
                )
            ):
                local_rebound_names.discard("_call_on_owner_loop")
            rebound_names.update(local_rebound_names)
            rebound_self_attributes.update(_rebound_self_attributes(parent))
        parent = parents.get(id(parent))
    return rebound_names, rebound_self_attributes


def _module_provider_rebindings(tree: ast.Module, relative: str) -> set[str]:
    """Return module bindings that shadow an approved bare state provider."""
    rebound: set[str] = set()
    approved_bare = {
        token
        for token in (
            *_STATE_PROVIDERS_BY_FILE.get(relative, frozenset()),
            *_STATE_WRAPPERS_BY_FILE.get(relative, frozenset()),
        )
        if not token.startswith("self.")
    }

    def record_target(
        target: ast.AST,
        assignments: dict[str, list[ast.AST]] | None = None,
        owner_predicate: Callable[[ast.AST, dict[str, list[ast.AST]]], bool] = _is_globals_dict_expression,
    ) -> None:
        if assignments is not None and isinstance(target, ast.Subscript) and owner_predicate(target.value, assignments):
            name = _constant_string(target.slice, assignments)
            rebound.update(approved_bare if name is None else {name} & approved_bare)
            return
        if (
            assignments is not None
            and isinstance(target, ast.Attribute)
            and _is_module_object_expression(target.value, assignments)
        ):
            rebound.update({target.attr} & approved_bare)
            return
        target_assignments: dict[str, list[ast.AST]] = {}
        _record_assignment_target(target_assignments, target, ast.Constant(value=None))
        rebound.update(target_assignments.keys() & approved_bare)

    def record_dynamic_call(
        node: ast.Call,
        assignments: dict[str, list[ast.AST]],
        owner_predicate: Callable[[ast.AST, dict[str, list[ast.AST]]], bool] = _is_globals_dict_expression,
    ) -> None:
        recognised, keys = _mapping_mutation_keys(
            node,
            assignments,
            owner_predicate,
        )
        if not recognised:
            mutates_module, name = _module_attribute_mutation(node, assignments)
            if mutates_module:
                rebound.update(approved_bare if name is None else {name} & approved_bare)
            return
        rebound.update(approved_bare if keys is None else keys & approved_bare)

    def record_augmented_mapping(
        node: ast.AugAssign,
        assignments: dict[str, list[ast.AST]],
        owner_predicate: Callable[[ast.AST, dict[str, list[ast.AST]]], bool] = _is_globals_dict_expression,
    ) -> bool:
        if not isinstance(node.op, ast.BitOr) or not owner_predicate(
            node.target,
            assignments,
        ):
            return False
        keys = _constant_mapping_keys(node.value, assignments)
        rebound.update(approved_bare if keys is None else keys & approved_bare)
        return True

    module_assignments = _with_import_sources(
        _module_assignment_sources(tree),
        _module_scope_nodes(tree),
    )
    for node in _module_scope_nodes(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                record_target(target, module_assignments, _is_module_globals_dict_expression)
        elif isinstance(node, ast.AugAssign):
            if not record_augmented_mapping(node, module_assignments, _is_module_globals_dict_expression):
                record_target(node.target, module_assignments, _is_module_globals_dict_expression)
        elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)):
            record_target(node.target, module_assignments, _is_module_globals_dict_expression)
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            record_target(node.target, module_assignments, _is_module_globals_dict_expression)
        elif isinstance(node, ast.With):
            for item in node.items:
                if item.optional_vars is not None:
                    record_target(item.optional_vars, module_assignments, _is_module_globals_dict_expression)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            if node.name in approved_bare:
                rebound.add(node.name)
        elif isinstance(node, ast.match_case):
            assignments: dict[str, list[ast.AST]] = {}
            _record_pattern_targets(assignments, node.pattern)
            rebound.update(assignments.keys() & approved_bare)
        elif isinstance(node, ast.Delete):
            for target in node.targets:
                record_target(target, module_assignments, _is_module_globals_dict_expression)
        elif isinstance(node, ast.Call):
            record_dynamic_call(node, module_assignments, _is_module_globals_dict_expression)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                bound_name = alias.asname or alias.name.split(".")[0]
                if bound_name not in approved_bare:
                    continue
                canonical_import = (
                    isinstance(node, ast.ImportFrom)
                    and alias.asname is None
                    and (
                        (
                            alias.name == "gather_safety_state"
                            and node.module in {"l2_state", "flinttrade_core.l2_state"}
                        )
                        or (alias.name == "_run_on_client_loop" and node.module == "order_routes")
                    )
                )
                if not canonical_import:
                    rebound.add(bound_name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name not in approved_bare:
                continue
            canonical_definition = (
                relative == "packages/core/core/src/flinttrade_core/order_routes.py"
                and node.name == "_gather_safety_state"
                and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            )
            if not canonical_definition:
                rebound.add(node.name)
    for function in (node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))):
        assignments = _function_resolution_assignments(function, module_assignments)
        for node in _scope_nodes(function):
            if isinstance(node, ast.Global):
                rebound.update(set(node.names) & approved_bare)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    record_target(target, assignments)
            elif isinstance(node, ast.AugAssign):
                if not record_augmented_mapping(node, assignments):
                    record_target(node.target, assignments)
            elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)):
                record_target(node.target, assignments)
            elif isinstance(node, ast.Delete):
                for target in node.targets:
                    record_target(target, assignments)
            elif isinstance(node, ast.Call):
                record_dynamic_call(node, assignments)
    return rebound


def _is_direct_self_attribute(target: ast.AST, attribute: str) -> bool:
    return (
        isinstance(target, ast.Attribute)
        and isinstance(target.value, ast.Name)
        and target.value.id == "self"
        and target.attr == attribute
    )


def _has_only_canonical_init_binding(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    attribute: str,
    inherited_assignments: dict[str, list[ast.AST]] | None = None,
) -> bool:
    """Accept only ``self._provider = provider`` constructor injection."""
    expected_parameter = attribute.removeprefix("_")
    parameters = {
        argument.arg for argument in (*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs)
    }
    if function.args.vararg is not None:
        parameters.add(function.args.vararg.arg)
    if function.args.kwarg is not None:
        parameters.add(function.args.kwarg.arg)
    if expected_parameter not in parameters:
        return False
    if any(isinstance(node, ast.Nonlocal) and expected_parameter in node.names for node in ast.walk(function)):
        return False
    nodes = _scope_nodes(function)
    local_assignments = _assignment_sources(function)
    parameter_sources = local_assignments.get(expected_parameter, [])
    if any(not isinstance(source, ast.Constant) or source.value is not None for source in parameter_sources):
        return False
    assignments = _function_resolution_assignments(function, inherited_assignments)

    def is_self_alias(name: str, resolving: frozenset[str] = frozenset()) -> bool:
        if name == "self":
            return True
        if name in resolving:
            return False
        return any(
            isinstance(source, ast.Name) and is_self_alias(source.id, resolving | {name})
            for source in assignments.get(name, [])
        )

    seen = False
    parents = {id(child): parent for parent in nodes for child in ast.iter_child_nodes(parent)}
    for node in nodes:
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.ctx, (ast.Store, ast.Del))
            and node.attr == "__dict__"
            and isinstance(node.value, ast.Name)
            and is_self_alias(node.value.id)
        ):
            return False
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.ctx, (ast.Store, ast.Del))
            and node.attr == attribute
            and isinstance(node.value, ast.Name)
            and node.value.id != "self"
            and is_self_alias(node.value.id)
        ):
            return False
        if _is_direct_self_attribute(node, attribute) and isinstance(node.ctx, (ast.Store, ast.Del)):
            parent = parents.get(id(node))
            if isinstance(node.ctx, ast.Del):
                return False
            if isinstance(parent, ast.Assign):
                valid = (
                    len(parent.targets) == 1
                    and parent.targets[0] is node
                    and isinstance(parent.value, ast.Name)
                    and parent.value.id == expected_parameter
                )
            elif isinstance(parent, ast.AnnAssign):
                valid = (
                    parent.target is node
                    and isinstance(parent.value, ast.Name)
                    and parent.value.id == expected_parameter
                )
            else:
                valid = False
            if not valid:
                return False
            seen = True
        elif isinstance(node, ast.Subscript) and isinstance(node.ctx, (ast.Store, ast.Del)):
            owner = node.value
            if _is_self_dict_expression(owner, assignments):
                mutated_name = _constant_string(node.slice, assignments)
                if mutated_name is None or mutated_name == attribute:
                    return False
        elif (
            isinstance(node, ast.AugAssign)
            and isinstance(node.op, ast.BitOr)
            and _is_self_dict_expression(node.target, assignments)
        ):
            keys = _constant_mapping_keys(node.value, assignments)
            if keys is None or attribute in keys:
                return False
        elif isinstance(node, ast.Call):
            recognised, keys = _mapping_mutation_keys(
                node,
                assignments,
                _is_self_dict_expression,
            )
            if recognised and (keys is None or attribute in keys):
                return False
            mutates_self, mutated_name = _self_attribute_mutation(node, assignments)
            if mutates_self and mutated_name in {None, "__dict__", attribute}:
                return False
    return seen


def _class_provider_rebindings(tree: ast.Module, relative: str) -> set[str]:
    """Return approved ``self`` providers replaced anywhere in their class."""
    approved_self = {
        token.removeprefix("self.")
        for token in (
            *_STATE_PROVIDERS_BY_FILE.get(relative, frozenset()),
            *_STATE_WRAPPERS_BY_FILE.get(relative, frozenset()),
        )
        if token.startswith("self.")
    }
    rebound: set[str] = set()
    parents = _parent_nodes(tree)

    def functions_in_class(class_node: ast.ClassDef) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
        functions: list[ast.FunctionDef | ast.AsyncFunctionDef] = []

        def visit(node: ast.AST) -> None:
            if isinstance(node, ast.ClassDef) and node is not class_node:
                return
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions.append(node)
            for child in ast.iter_child_nodes(node):
                visit(child)

        for statement in class_node.body:
            visit(statement)
        return functions

    for class_node in (node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)):
        direct_methods = {
            id(node) for node in class_node.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        for function in functions_in_class(class_node):
            lexical_assignments = _lexical_assignment_sources(function, tree, parents)
            function_changes = _rebound_self_attributes(function, lexical_assignments)
            changed = approved_self if "*" in function_changes else function_changes & approved_self
            for attribute in changed:
                if (
                    id(function) in direct_methods
                    and function.name == "__init__"
                    and _has_only_canonical_init_binding(function, attribute, lexical_assignments)
                ):
                    continue
                rebound.add(attribute)
    return rebound


def _is_canonical_portfolio_state_source(
    value: ast.AST,
    *,
    allowed_providers: frozenset[str] = _DEFAULT_STATE_PROVIDERS,
    allowed_wrappers: frozenset[str] = _DEFAULT_STATE_WRAPPERS,
    rebound_names: set[str] | None = None,
    rebound_self_attributes: set[str] | None = None,
) -> bool:
    if isinstance(value, ast.Await):
        return _is_canonical_portfolio_state_source(
            value.value,
            allowed_providers=allowed_providers,
            allowed_wrappers=allowed_wrappers,
            rebound_names=rebound_names,
            rebound_self_attributes=rebound_self_attributes,
        )
    if not isinstance(value, ast.Call):
        return False
    token = _call_token(value)
    rebound_names = rebound_names or set()
    rebound_self_attributes = rebound_self_attributes or set()
    token_is_rebound = (
        token in rebound_names
        if not token.startswith("self.")
        else "*" in rebound_self_attributes or token.removeprefix("self.") in rebound_self_attributes
    )
    if token in allowed_providers and not token_is_rebound:
        return True
    if token not in allowed_wrappers or token_is_rebound:
        return False
    return any(
        _is_canonical_portfolio_state_source(
            argument,
            allowed_providers=allowed_providers,
            allowed_wrappers=allowed_wrappers,
            rebound_names=rebound_names,
            rebound_self_attributes=rebound_self_attributes,
        )
        for argument in value.args
    )


def _is_canonical_admission_source(value: ast.AST) -> bool:
    return (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Attribute)
        and value.func.attr == "admission_for"
        and isinstance(value.func.value, ast.Name)
        and value.func.value.id == "portfolio_state"
    )


def _proven_admission_names(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    assignments: dict[str, list[ast.AST]],
    *,
    allowed_providers: frozenset[str] = _DEFAULT_STATE_PROVIDERS,
    allowed_wrappers: frozenset[str] = _DEFAULT_STATE_WRAPPERS,
    inherited_rebound_names: set[str] | None = None,
    inherited_rebound_self_attributes: set[str] | None = None,
) -> set[str]:
    rebound_names = _rebound_names(function, assignments) | (inherited_rebound_names or set())
    rebound_self_attributes = _rebound_self_attributes(function) | (inherited_rebound_self_attributes or set())
    portfolio_sources = assignments.get("portfolio_state", [])
    portfolio_state_is_proven = bool(portfolio_sources) and all(
        _is_canonical_portfolio_state_source(
            source,
            allowed_providers=allowed_providers,
            allowed_wrappers=allowed_wrappers,
            rebound_names=rebound_names,
            rebound_self_attributes=rebound_self_attributes,
        )
        for source in portfolio_sources
    )
    proven = {
        name
        for name, sources in assignments.items()
        if portfolio_state_is_proven
        and bool(sources)
        and all(_is_canonical_admission_source(source) for source in sources)
    }
    parameter_names = {
        argument.arg for argument in (*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs)
    }
    if function.name == "_check_order_with_state" and "admission" in parameter_names and "admission" not in assignments:
        proven.add("admission")
    return proven


def _unapproved_helper_references(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    inherited_rebound_names: set[str] | None = None,
) -> list[ast.AST]:
    """Return private check-helper references that are not direct calls."""
    nodes = _scope_nodes(function)
    assignments = _function_resolution_assignments(function)
    parents = {id(child): parent for parent in nodes for child in ast.iter_child_nodes(parent)}
    rebound_names = _rebound_names(function, _assignment_sources(function)) | (inherited_rebound_names or set())
    offenders: list[ast.AST] = []
    for node in nodes:
        if isinstance(node, ast.Name) and node.id == "_check_order_with_state":
            parent = parents.get(id(node))
            if (
                not isinstance(parent, ast.Call)
                or parent.func is not node
                or "_check_order_with_state" in rebound_names
            ):
                offenders.append(node)
        elif isinstance(node, ast.Attribute) and node.attr == "_check_order_with_state":
            offenders.append(node)
        elif isinstance(node, ast.Subscript) and _constant_string(node.slice, assignments) == "_check_order_with_state":
            offenders.append(node)
        elif isinstance(node, ast.Call):
            recognised, owner, name = _dynamic_attribute_access(node, assignments)
            if (
                recognised
                and owner is not None
                and (
                    name == "_check_order_with_state"
                    or (
                        name is None
                        and (
                            _call_result_is_invoked(node, parents) or _dynamic_access_executes_method(node, assignments)
                        )
                        and (
                            _is_globals_dict_expression(owner, assignments)
                            or _is_module_object_expression(owner, assignments)
                            or _expression_mentions(owner, "helper")
                        )
                    )
                )
            ):
                offenders.append(node)
                continue
            if any(
                mapping_name == "_check_order_with_state"
                or (
                    mapping_name is None
                    and _call_result_is_invoked(node, parents)
                    and (
                        _is_globals_dict_expression(mapping_owner, assignments)
                        or _is_module_object_expression(mapping_owner, assignments)
                        or _expression_mentions(mapping_owner, "helper")
                    )
                )
                for mapping_owner, mapping_name in _mapping_lookup_accesses(node, assignments)
            ):
                offenders.append(node)
    return offenders


def _is_callable_check_order_probe(
    node: ast.Call,
    parents: dict[int, ast.AST],
    assignments: dict[str, list[ast.AST]],
) -> bool:
    callable_call = parents.get(id(node))
    return (
        isinstance(callable_call, ast.Call)
        and _resolves_builtin_member(callable_call.func, frozenset({"callable"}), assignments)
        and len(callable_call.args) == 1
        and callable_call.args[0] is node
    )


def _evaluates_in_callable_body(node: ast.AST, parents: dict[int, ast.AST]) -> bool:
    current = node
    parent = parents.get(id(current))
    while parent is not None:
        if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if any(statement is current for statement in parent.body):
                return True
        elif isinstance(parent, ast.Lambda) and parent.body is current:
            return True
        elif isinstance(parent, ast.Module):
            return False
        current = parent
        parent = parents.get(id(current))
    return False


def _is_module_namespace_for_node(
    value: ast.AST,
    assignments: dict[str, list[ast.AST]],
    node: ast.AST,
    parents: dict[int, ast.AST],
) -> bool:
    if _is_globals_dict_expression(value, assignments):
        return True
    return not _evaluates_in_callable_body(node, parents) and _is_module_globals_dict_expression(value, assignments)


def _expression_mentions(value: ast.AST, fragment: str) -> bool:
    lowered = fragment.lower()
    return any(
        lowered in token.lower()
        for node in ast.walk(value)
        for token in (
            [node.id] if isinstance(node, ast.Name) else [node.attr] if isinstance(node, ast.Attribute) else []
        )
    )


def _could_resolve_private_helper(
    owner: ast.AST,
    assignments: dict[str, list[ast.AST]],
    node: ast.AST,
    parents: dict[int, ast.AST],
) -> bool:
    return (
        _is_module_namespace_for_node(owner, assignments, node, parents)
        or _is_module_object_expression(owner, assignments)
        or _expression_mentions(owner, "helper")
    )


def _could_resolve_check_order(
    owner: ast.AST,
    assignments: dict[str, list[ast.AST]],
    node: ast.AST,
    parents: dict[int, ast.AST],
) -> bool:
    return _is_module_namespace_for_node(owner, assignments, node, parents) or _expression_mentions(owner, "safety")


def _call_result_is_invoked(node: ast.Call, parents: dict[int, ast.AST]) -> bool:
    parent = parents.get(id(node))
    return isinstance(parent, ast.Call) and parent.func is node


def _dynamic_access_executes_method(
    node: ast.Call,
    assignments: dict[str, list[ast.AST]],
) -> bool:
    kind, _, _, _ = _operator_factory_access(node, assignments)
    return kind == "methodcaller"


def _unapproved_check_order_references(tree: ast.Module) -> list[ast.AST]:
    """Return aliases and dynamic lookups of ``SafetySystem.check_order``."""
    parents = _parent_nodes(tree)
    lexical_sources_cache: dict[int, dict[str, list[ast.AST]]] = {}
    offenders: list[ast.AST] = []
    for node in ast.walk(tree):
        assignments = _lexical_assignment_sources(
            node,
            tree,
            parents,
            lexical_sources_cache,
        )
        if isinstance(node, ast.Attribute) and node.attr == "check_order":
            parent = parents.get(id(node))
            if not isinstance(parent, ast.Call) or parent.func is not node:
                offenders.append(node)
        elif isinstance(node, ast.Call):
            recognised, owner, name = _dynamic_attribute_access(node, assignments)
            if recognised and owner is not None:
                if name == "check_order":
                    if not _is_callable_check_order_probe(node, parents, assignments):
                        offenders.append(node)
                elif (
                    name is None
                    and (_call_result_is_invoked(node, parents) or _dynamic_access_executes_method(node, assignments))
                    and _could_resolve_check_order(owner, assignments, node, parents)
                ):
                    offenders.append(node)
            for mapping_owner, mapping_name in _mapping_lookup_accesses(node, assignments):
                if mapping_name == "check_order" or (
                    mapping_name is None
                    and _call_result_is_invoked(node, parents)
                    and _could_resolve_check_order(mapping_owner, assignments, node, parents)
                ):
                    offenders.append(node)
                    break
        elif isinstance(node, ast.Subscript) and _constant_string(node.slice, assignments) == "check_order":
            offenders.append(node)
    return offenders


def _dynamic_helper_references_in_tree(tree: ast.Module) -> list[ast.AST]:
    """Return dynamic private-helper recovery in every lexical scope."""
    parents = _parent_nodes(tree)
    lexical_sources_cache: dict[int, dict[str, list[ast.AST]]] = {}
    offenders: list[ast.AST] = []
    for node in ast.walk(tree):
        assignments = _lexical_assignment_sources(
            node,
            tree,
            parents,
            lexical_sources_cache,
        )
        if isinstance(node, ast.Call):
            recognised, owner, name = _dynamic_attribute_access(node, assignments)
            if recognised and owner is not None:
                if name == "_check_order_with_state" or (
                    name is None
                    and (_call_result_is_invoked(node, parents) or _dynamic_access_executes_method(node, assignments))
                    and _could_resolve_private_helper(owner, assignments, node, parents)
                ):
                    offenders.append(node)
                    continue
            if any(
                mapping_name == "_check_order_with_state"
                or (
                    mapping_name is None
                    and _call_result_is_invoked(node, parents)
                    and _could_resolve_private_helper(mapping_owner, assignments, node, parents)
                )
                for mapping_owner, mapping_name in _mapping_lookup_accesses(node, assignments)
            ):
                offenders.append(node)
        elif isinstance(node, ast.Subscript) and _constant_string(node.slice, assignments) == "_check_order_with_state":
            offenders.append(node)
    return offenders


def test_every_production_order_check_supplies_l1_and_l3_market_inputs() -> None:
    """LTP and portfolio Greeks must never fall back to inert check_order defaults."""
    missing: list[str] = []
    for source_root in (_REPO_ROOT / "packages").glob("*/**/src"):
        for path in source_root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                    continue
                if node.func.attr != "check_order":
                    continue
                supplied = {keyword.arg for keyword in node.keywords if keyword.arg is not None}
                absent = {"ltp", "net_delta", "net_vega"} - supplied
                if absent:
                    relative = path.relative_to(_REPO_ROOT)
                    missing.append(f"{relative}:{node.lineno} missing {', '.join(sorted(absent))}")
    assert not missing, "Production SafetySystem checks have inert market inputs:\n" + "\n".join(missing)


@pytest.mark.timeout(300)
def test_order_checks_never_pass_current_portfolio_greeks_as_prospective_risk() -> None:
    """Layer 3 must consume ``admission_for`` outputs, including through helpers.

    The whole-repo AST sweep takes ~65s alone on the CI runner; under the
    4-way xdist load it reliably crosses CI's global ``--timeout=60``, whose
    thread method kills the entire worker (reported as "worker crashed").
    The override keeps the deep scan instead of trimming its coverage.
    """
    offenders: list[str] = []
    for source_root in (_REPO_ROOT / "packages").glob("*/**/src"):
        for path in source_root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            relative = path.relative_to(_REPO_ROOT).as_posix()
            allowed_providers = _STATE_PROVIDERS_BY_FILE.get(relative, frozenset())
            allowed_wrappers = _STATE_WRAPPERS_BY_FILE.get(relative, frozenset())
            parents = _parent_nodes(tree)
            module_rebound_names = _module_provider_rebindings(tree, relative)
            class_rebound_self_attributes = _class_provider_rebindings(tree, relative)
            audited_check_calls: set[int] = set()
            audited_helper_references: set[int] = set()
            for reference in _unapproved_check_order_references(tree):
                offenders.append(f"{relative}:{reference.lineno} aliases or dynamically references check_order")
            for function in (
                node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            ):
                assignments = _assignment_sources(function)
                closure_rebound_names, closure_rebound_self_attributes = _enclosing_function_rebindings(
                    function,
                    parents,
                    relative=relative,
                )
                inherited_rebound_names = module_rebound_names | closure_rebound_names
                rebound_names = _rebound_names(function, assignments) | inherited_rebound_names
                inherited_rebound_self_attributes = closure_rebound_self_attributes | class_rebound_self_attributes
                rebound_self_attributes = _rebound_self_attributes(function) | inherited_rebound_self_attributes
                proven_admissions = _proven_admission_names(
                    function,
                    assignments,
                    allowed_providers=allowed_providers,
                    allowed_wrappers=allowed_wrappers,
                    inherited_rebound_names=inherited_rebound_names,
                    inherited_rebound_self_attributes=inherited_rebound_self_attributes,
                )
                for reference in _unapproved_helper_references(
                    function,
                    inherited_rebound_names=inherited_rebound_names,
                ):
                    offenders.append(
                        f"{relative}:{reference.lineno} aliases, shadows or indirectly references "
                        "_check_order_with_state"
                    )
                for node in _scope_nodes(function):
                    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                        continue
                    if node.func.attr != "check_order":
                        continue
                    audited_check_calls.add(id(node))
                    for keyword in node.keywords:
                        if keyword.arg not in {"net_delta", "net_vega"}:
                            continue
                        value = keyword.value
                        if _is_exact_prospective_greek(value, keyword.arg, proven_admissions):
                            continue
                        offenders.append(
                            f"{relative}:{node.lineno} passes unproved {ast.unparse(value)} as {keyword.arg}"
                        )

                portfolio_sources = assignments.get("portfolio_state", [])
                portfolio_state_is_proven = bool(portfolio_sources) and all(
                    _is_canonical_portfolio_state_source(
                        source,
                        allowed_providers=allowed_providers,
                        allowed_wrappers=allowed_wrappers,
                        rebound_names=rebound_names,
                        rebound_self_attributes=rebound_self_attributes,
                    )
                    for source in portfolio_sources
                )
                for node in _scope_nodes(function):
                    if (
                        not isinstance(node, ast.Call)
                        or not isinstance(node.func, ast.Name)
                        or node.func.id != "_check_order_with_state"
                    ):
                        continue
                    audited_helper_references.add(id(node.func))
                    if (
                        relative != "packages/core/core/src/flinttrade_core/order_routes.py"
                        or "_check_order_with_state" in rebound_names
                    ):
                        offenders.append(
                            f"{relative}:{node.lineno} calls a shadowed or non-canonical _check_order_with_state"
                        )
                        continue
                    admission_keyword = next(
                        (keyword for keyword in node.keywords if keyword.arg == "admission"),
                        None,
                    )
                    if admission_keyword is None or not isinstance(admission_keyword.value, ast.Name):
                        offenders.append(f"{relative}:{node.lineno} does not pass a named prospective admission")
                        continue
                    admission_name = admission_keyword.value.id
                    sources = assignments.get(admission_name, [])
                    if admission_name in proven_admissions:
                        valid = True
                    elif admission_name == "conversion_admission":
                        valid = (
                            portfolio_state_is_proven
                            and function.name == "_admit_position_conversion"
                            and len(sources) == 1
                            and isinstance(sources[0], ast.Call)
                            and isinstance(sources[0].func, ast.Name)
                            and sources[0].func.id == "ProspectiveSafetyInputs"
                            and {
                                keyword.arg: ast.unparse(keyword.value)
                                for keyword in sources[0].keywords
                                if keyword.arg is not None
                            }.get("net_delta")
                            == "portfolio_state.net_delta"
                            and {
                                keyword.arg: ast.unparse(keyword.value)
                                for keyword in sources[0].keywords
                                if keyword.arg is not None
                            }.get("net_vega")
                            == "portfolio_state.net_vega"
                        )
                    else:
                        valid = False
                    if not valid:
                        offenders.append(f"{relative}:{node.lineno} passes unproved helper admission {admission_name}")

            dynamic_helper_references = {id(node) for node in _dynamic_helper_references_in_tree(tree)}
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    if node.func.attr == "check_order" and id(node) not in audited_check_calls:
                        offenders.append(
                            f"{relative}:{node.lineno} check_order call is outside an audited function scope"
                        )
                elif isinstance(node, ast.Name) and node.id == "_check_order_with_state":
                    if id(node) not in audited_helper_references:
                        offenders.append(
                            f"{relative}:{node.lineno} aliases or indirectly references _check_order_with_state"
                        )
                elif isinstance(node, ast.Attribute) and node.attr == "_check_order_with_state":
                    offenders.append(f"{relative}:{node.lineno} indirectly references _check_order_with_state")
                elif id(node) in dynamic_helper_references:
                    offenders.append(f"{relative}:{node.lineno} dynamically references _check_order_with_state")
                elif isinstance(node, ast.arg) and node.arg == "_check_order_with_state":
                    offenders.append(f"{relative}:{node.lineno} shadows private _check_order_with_state as a parameter")
                elif (
                    isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "_check_order_with_state"
                ):
                    parent = parents.get(id(node))
                    if not (
                        relative == "packages/core/core/src/flinttrade_core/order_routes.py"
                        and isinstance(parent, ast.Module)
                    ):
                        offenders.append(f"{relative}:{node.lineno} shadows private _check_order_with_state")
                elif isinstance(node, ast.ImportFrom):
                    for alias in node.names:
                        if alias.name == "_check_order_with_state":
                            offenders.append(f"{relative}:{node.lineno} imports private _check_order_with_state")
    assert not offenders, (
        "SafetySystem checks pass current-object Greeks instead of admission_for outputs:\n" + "\n".join(offenders)
    )


def test_prospective_greek_guard_rejects_wrapped_or_arithmetic_current_book_values() -> None:
    assert _is_exact_prospective_greek(
        ast.parse("admission.net_delta", mode="eval").body,
        "net_delta",
        {"admission"},
    )
    assert not _is_exact_prospective_greek(
        ast.parse("portfolio_state.net_delta + 0.0", mode="eval").body,
        "net_delta",
        {"admission"},
    )
    assert not _is_exact_prospective_greek(
        ast.parse("float(portfolio_state.net_vega)", mode="eval").body,
        "net_vega",
        {"admission"},
    )


def test_prospective_greek_guard_rejects_rebound_and_forged_admissions() -> None:
    rebound = ast.parse(
        "def check():\n    portfolio_state = _gather_safety_state()\n    admission = portfolio_state\n"
    ).body[0]
    forged = ast.parse(
        "def check():\n    portfolio_state = forged\n    admission = portfolio_state.admission_for(0)\n"
    ).body[0]
    forged_gatherer = ast.parse(
        "def check():\n    portfolio_state = forged._gather_safety_state()\n"
        "    admission = portfolio_state.admission_for(0)\n"
    ).body[0]
    shadowed_gatherer = ast.parse(
        "def check(forged):\n"
        "    _gather_safety_state = forged\n"
        "    portfolio_state = _gather_safety_state()\n"
        "    admission = portfolio_state.admission_for(0)\n"
    ).body[0]
    walrus_rebound = ast.parse(
        "def check():\n"
        "    portfolio_state = _gather_safety_state()\n"
        "    admission = portfolio_state.admission_for(0)\n"
        "    (admission := portfolio_state)\n"
    ).body[0]
    tuple_rebound = ast.parse(
        "def check():\n"
        "    portfolio_state = _gather_safety_state()\n"
        "    admission = portfolio_state.admission_for(0)\n"
        "    admission, marker = portfolio_state, None\n"
    ).body[0]
    match_rebound = ast.parse(
        "def check(payload):\n"
        "    portfolio_state = _gather_safety_state()\n"
        "    admission = portfolio_state.admission_for(0)\n"
        "    match payload:\n"
        "        case {'admission': admission}:\n"
        "            pass\n"
    ).body[0]
    canonical = ast.parse(
        "def check():\n    portfolio_state = _gather_safety_state()\n    admission = portfolio_state.admission_for(0)\n"
    ).body[0]
    assert isinstance(rebound, ast.FunctionDef)
    assert isinstance(forged, ast.FunctionDef)
    assert isinstance(forged_gatherer, ast.FunctionDef)
    assert isinstance(shadowed_gatherer, ast.FunctionDef)
    assert isinstance(walrus_rebound, ast.FunctionDef)
    assert isinstance(tuple_rebound, ast.FunctionDef)
    assert isinstance(match_rebound, ast.FunctionDef)
    assert isinstance(canonical, ast.FunctionDef)
    assert _proven_admission_names(rebound, _assignment_sources(rebound)) == set()
    assert _proven_admission_names(forged, _assignment_sources(forged)) == set()
    assert _proven_admission_names(forged_gatherer, _assignment_sources(forged_gatherer)) == set()
    assert _proven_admission_names(shadowed_gatherer, _assignment_sources(shadowed_gatherer)) == set()
    assert _proven_admission_names(walrus_rebound, _assignment_sources(walrus_rebound)) == set()
    assert _proven_admission_names(tuple_rebound, _assignment_sources(tuple_rebound)) == set()
    assert _proven_admission_names(match_rebound, _assignment_sources(match_rebound)) == set()
    assert _proven_admission_names(canonical, _assignment_sources(canonical)) == {"admission"}


def test_prospective_greek_guard_rejects_aliased_private_check_helper() -> None:
    aliased = ast.parse(
        "def check(admission):\n    helper = _check_order_with_state\n    helper(admission=admission)\n"
    ).body[0]
    direct = ast.parse("def check(admission):\n    _check_order_with_state(admission=admission)\n").body[0]
    assert isinstance(aliased, ast.FunctionDef)
    assert isinstance(direct, ast.FunctionDef)
    assert len(_unapproved_helper_references(aliased)) == 1
    assert _unapproved_helper_references(direct) == []


def test_prospective_greek_guard_rejects_dynamic_and_shadowed_private_helper() -> None:
    dynamic = ast.parse(
        "def check(admission):\n    getattr(helpers, '_check_order_with_state')(admission=admission)\n"
    ).body[0]
    parameter = ast.parse(
        "def check(_check_order_with_state, admission):\n    _check_order_with_state(admission=admission)\n"
    ).body[0]
    nested = ast.parse(
        "def check(admission):\n"
        "    def _check_order_with_state(**kwargs):\n"
        "        return kwargs\n"
        "    _check_order_with_state(admission=admission)\n"
    ).body[0]
    constant_alias = ast.parse(
        "def check(helpers, admission):\n"
        "    name = '_check_order_with_state'\n"
        "    getattr(helpers, name)(admission=admission)\n"
    ).body[0]
    formatted = ast.parse(
        "def check(helpers, admission):\n"
        "    getattr(helpers, '_check_{}_with_state'.format('order'))(admission=admission)\n"
    ).body[0]
    mapped_percent = ast.parse(
        "def check(helpers, admission):\n"
        "    getattr(helpers, '%(verb)s_order_with_state' % {'verb': '_check'})(admission=admission)\n"
    ).body[0]
    aliased_getattr = ast.parse(
        "def check(helpers, admission):\n"
        "    lookup = getattr\n"
        "    lookup(helpers, '_check_order_with_state')(admission=admission)\n"
    ).body[0]
    object_getattribute = ast.parse(
        "def check(helpers, admission):\n"
        "    object.__getattribute__(helpers, '_check_order_with_state')(admission=admission)\n"
    ).body[0]
    builtins_getattr = ast.parse(
        "import builtins\n"
        "def check(helpers, admission):\n"
        "    builtins.getattr(helpers, '_check_order_with_state')(admission=admission)\n"
    ).body[1]
    imported_getattr = ast.parse(
        "def check(helpers, admission):\n"
        "    from builtins import getattr as lookup\n"
        "    lookup(helpers, '_check_order_with_state')(admission=admission)\n"
    ).body[0]
    aliased_object_getattribute = ast.parse(
        "def check(helpers, admission):\n"
        "    lookup = object.__getattribute__\n"
        "    lookup(helpers, '_check_order_with_state')(admission=admission)\n"
    ).body[0]
    qualified_object_getattribute = ast.parse(
        "import builtins\n"
        "def check(helpers, admission):\n"
        "    builtins.object.__getattribute__(helpers, '_check_order_with_state')(admission=admission)\n"
    ).body[1]
    imported_object_getattribute = ast.parse(
        "def check(helpers, admission):\n"
        "    from builtins import object as obj\n"
        "    obj.__getattribute__(helpers, '_check_order_with_state')(admission=admission)\n"
    ).body[0]
    mapping_alias = ast.parse(
        "def check(helpers, admission):\n"
        "    parts = {'verb': '_check'}\n"
        "    getattr(helpers, '%(verb)s_order_with_state' % parts)(admission=admission)\n"
    ).body[0]
    globals_subscript = ast.parse(
        "def check(admission):\n    globals()['_check_order_with_state'](admission=admission)\n"
    ).body[0]
    type_subscript = ast.parse(
        "def check(helpers, admission):\n"
        "    type(helpers).__dict__['_check_order_with_state'](helpers, admission=admission)\n"
    ).body[0]
    mapping_get = ast.parse(
        "def check(admission):\n    globals().get('_check_order_with_state')(admission=admission)\n"
    ).body[0]
    operator_getitem = ast.parse(
        "import operator\n"
        "def check(admission):\n"
        "    operator.getitem(globals(), '_check_order_with_state')(admission=admission)\n"
    ).body[1]
    assert isinstance(dynamic, ast.FunctionDef)
    assert isinstance(parameter, ast.FunctionDef)
    assert isinstance(nested, ast.FunctionDef)
    assert isinstance(constant_alias, ast.FunctionDef)
    assert isinstance(formatted, ast.FunctionDef)
    assert isinstance(mapped_percent, ast.FunctionDef)
    assert isinstance(aliased_getattr, ast.FunctionDef)
    assert isinstance(object_getattribute, ast.FunctionDef)
    assert isinstance(builtins_getattr, ast.FunctionDef)
    assert isinstance(imported_getattr, ast.FunctionDef)
    assert isinstance(aliased_object_getattribute, ast.FunctionDef)
    assert isinstance(qualified_object_getattribute, ast.FunctionDef)
    assert isinstance(imported_object_getattribute, ast.FunctionDef)
    assert isinstance(mapping_alias, ast.FunctionDef)
    assert isinstance(globals_subscript, ast.FunctionDef)
    assert isinstance(type_subscript, ast.FunctionDef)
    assert isinstance(mapping_get, ast.FunctionDef)
    assert isinstance(operator_getitem, ast.FunctionDef)
    assert _unapproved_helper_references(dynamic)
    assert _unapproved_helper_references(parameter)
    assert _unapproved_helper_references(nested)
    assert _unapproved_helper_references(constant_alias)
    assert _unapproved_helper_references(formatted)
    assert _unapproved_helper_references(mapped_percent)
    assert _unapproved_helper_references(aliased_getattr)
    assert _unapproved_helper_references(object_getattribute)
    assert _unapproved_helper_references(builtins_getattr)
    assert _unapproved_helper_references(imported_getattr)
    assert _unapproved_helper_references(aliased_object_getattribute)
    assert _unapproved_helper_references(qualified_object_getattribute)
    assert _unapproved_helper_references(imported_object_getattribute)
    assert _unapproved_helper_references(mapping_alias)
    assert _unapproved_helper_references(globals_subscript)
    assert _unapproved_helper_references(type_subscript)
    assert _unapproved_helper_references(mapping_get)
    assert _unapproved_helper_references(operator_getitem)


def test_prospective_greek_guard_rejects_indirect_check_order_calls() -> None:
    alias_tree = ast.parse(
        "def check(safety, order, admission):\n"
        "    checker = safety.check_order\n"
        "    checker(order, ltp=1, net_delta=admission.net_delta, net_vega=admission.net_vega)\n"
    )
    dynamic_tree = ast.parse(
        "def check(safety, order, admission):\n"
        "    getattr(safety, 'check_order')(\n"
        "        order, ltp=1, net_delta=admission.net_delta, net_vega=admission.net_vega\n"
        "    )\n"
    )
    capability_tree = ast.parse("def validate(safety):\n    return callable(getattr(safety, 'check_order', None))\n")
    computed_tree = ast.parse(
        "def check(safety, order, admission):\n"
        "    getattr(safety, 'check_' + 'order')(\n"
        "        order, ltp=1, net_delta=admission.net_delta, net_vega=admission.net_vega\n"
        "    )\n"
    )
    constant_alias_tree = ast.parse(
        "def check(safety, order, admission):\n"
        "    name = 'check_order'\n"
        "    getattr(safety, name)(\n"
        "        order, ltp=1, net_delta=admission.net_delta, net_vega=admission.net_vega\n"
        "    )\n"
    )
    percent_tree = ast.parse(
        "def check(safety, order, admission):\n"
        "    getattr(safety, '%s_order' % 'check')(\n"
        "        order, ltp=1, net_delta=admission.net_delta, net_vega=admission.net_vega\n"
        "    )\n"
    )
    format_tree = ast.parse(
        "def check(safety, order, admission):\n"
        "    getattr(safety, '{}_order'.format('check'))(\n"
        "        order, ltp=1, net_delta=admission.net_delta, net_vega=admission.net_vega\n"
        "    )\n"
    )
    module_constant_tree = ast.parse(
        "NAME = 'check_order'\n"
        "def check(safety, order, admission):\n"
        "    getattr(safety, NAME)(order, ltp=1, net_delta=admission.net_delta, net_vega=admission.net_vega)\n"
    )
    mapping_percent_tree = ast.parse(
        "def check(safety, order, admission):\n"
        "    getattr(safety, '%(verb)s_order' % {'verb': 'check'})(\n"
        "        order, ltp=1, net_delta=admission.net_delta, net_vega=admission.net_vega\n"
        "    )\n"
    )
    aliased_getattr_tree = ast.parse(
        "def check(safety, order, admission):\n"
        "    lookup = getattr\n"
        "    lookup(safety, 'check_order')(\n"
        "        order, ltp=1, net_delta=admission.net_delta, net_vega=admission.net_vega\n"
        "    )\n"
    )
    object_getattribute_tree = ast.parse(
        "def check(safety, order, admission):\n"
        "    object.__getattribute__(safety, 'check_order')(\n"
        "        order, ltp=1, net_delta=admission.net_delta, net_vega=admission.net_vega\n"
        "    )\n"
    )
    builtins_getattr_tree = ast.parse(
        "import builtins\n"
        "def check(safety, order, admission):\n"
        "    builtins.getattr(safety, 'check_order')(\n"
        "        order, ltp=1, net_delta=admission.net_delta, net_vega=admission.net_vega\n"
        "    )\n"
    )
    imported_getattr_tree = ast.parse(
        "from builtins import getattr as lookup\n"
        "def check(safety, order, admission):\n"
        "    lookup(safety, 'check_order')(\n"
        "        order, ltp=1, net_delta=admission.net_delta, net_vega=admission.net_vega\n"
        "    )\n"
    )
    aliased_object_getattribute_tree = ast.parse(
        "def check(safety, order, admission):\n"
        "    lookup = object.__getattribute__\n"
        "    lookup(safety, 'check_order')(\n"
        "        order, ltp=1, net_delta=admission.net_delta, net_vega=admission.net_vega\n"
        "    )\n"
    )
    qualified_object_getattribute_tree = ast.parse(
        "import builtins\n"
        "def check(safety, order, admission):\n"
        "    builtins.object.__getattribute__(safety, 'check_order')(\n"
        "        order, ltp=1, net_delta=admission.net_delta, net_vega=admission.net_vega\n"
        "    )\n"
    )
    imported_object_getattribute_tree = ast.parse(
        "from builtins import object as obj\n"
        "def check(safety, order, admission):\n"
        "    obj.__getattribute__(safety, 'check_order')(\n"
        "        order, ltp=1, net_delta=admission.net_delta, net_vega=admission.net_vega\n"
        "    )\n"
    )
    mapping_alias_tree = ast.parse(
        "PARTS = {'verb': 'check'}\n"
        "def check(safety, order, admission):\n"
        "    getattr(safety, '%(verb)s_order' % PARTS)(\n"
        "        order, ltp=1, net_delta=admission.net_delta, net_vega=admission.net_vega\n"
        "    )\n"
    )
    globals_subscript_tree = ast.parse(
        "def check(safety, order, admission):\n"
        "    globals()['check_order'](\n"
        "        safety, order, ltp=1, net_delta=admission.net_delta, net_vega=admission.net_vega\n"
        "    )\n"
    )
    type_subscript_tree = ast.parse(
        "def check(safety, order, admission):\n"
        "    type(safety).__dict__['check_order'](\n"
        "        safety, order, ltp=1, net_delta=admission.net_delta, net_vega=admission.net_vega\n"
        "    )\n"
    )
    mapping_get_tree = ast.parse(
        "def check(safety, order, admission):\n"
        "    type(safety).__dict__.get('check_order')(\n"
        "        safety, order, ltp=1, net_delta=admission.net_delta, net_vega=admission.net_vega\n"
        "    )\n"
    )
    operator_getitem_tree = ast.parse(
        "import operator\n"
        "def check(safety, order, admission):\n"
        "    operator.getitem(type(safety).__dict__, 'check_order')(\n"
        "        safety, order, ltp=1, net_delta=admission.net_delta, net_vega=admission.net_vega\n"
        "    )\n"
    )
    assert _unapproved_check_order_references(alias_tree)
    assert _unapproved_check_order_references(dynamic_tree)
    assert _unapproved_check_order_references(computed_tree)
    assert _unapproved_check_order_references(constant_alias_tree)
    assert _unapproved_check_order_references(percent_tree)
    assert _unapproved_check_order_references(format_tree)
    assert _unapproved_check_order_references(module_constant_tree)
    assert _unapproved_check_order_references(mapping_percent_tree)
    assert _unapproved_check_order_references(aliased_getattr_tree)
    assert _unapproved_check_order_references(object_getattribute_tree)
    assert _unapproved_check_order_references(builtins_getattr_tree)
    assert _unapproved_check_order_references(imported_getattr_tree)
    assert _unapproved_check_order_references(aliased_object_getattribute_tree)
    assert _unapproved_check_order_references(qualified_object_getattribute_tree)
    assert _unapproved_check_order_references(imported_object_getattribute_tree)
    assert _unapproved_check_order_references(mapping_alias_tree)
    assert _unapproved_check_order_references(globals_subscript_tree)
    assert _unapproved_check_order_references(type_subscript_tree)
    assert _unapproved_check_order_references(mapping_get_tree)
    assert _unapproved_check_order_references(operator_getitem_tree)
    assert _unapproved_check_order_references(capability_tree) == []


def test_prospective_greek_guard_rejects_computed_private_helper_name() -> None:
    function = ast.parse(
        "def check(admission):\n    getattr(helpers, '_check_' + 'order_with_state')(admission=admission)\n"
    ).body[0]
    assert isinstance(function, ast.FunctionDef)
    assert _unapproved_helper_references(function)


def test_prospective_greek_guard_resolves_enclosing_and_module_provider_bindings() -> None:
    tree = ast.parse(
        "def outer(forged):\n"
        "    _gather_safety_state = forged\n"
        "    def check():\n"
        "        portfolio_state = _gather_safety_state()\n"
        "        admission = portfolio_state.admission_for(0)\n"
    )
    outer = tree.body[0]
    assert isinstance(outer, ast.FunctionDef)
    inner = outer.body[1]
    assert isinstance(inner, ast.FunctionDef)
    inherited, inherited_self = _enclosing_function_rebindings(inner, _parent_nodes(tree))
    assert (
        _proven_admission_names(
            inner,
            _assignment_sources(inner),
            inherited_rebound_names=inherited,
            inherited_rebound_self_attributes=inherited_self,
        )
        == set()
    )

    module_tree = ast.parse(
        "from forged import _gather_safety_state\ndef check():\n    portfolio_state = _gather_safety_state()\n"
    )
    relative = "packages/core/core/src/flinttrade_core/order_routes.py"
    assert "_gather_safety_state" in _module_provider_rebindings(module_tree, relative)

    conditional_module_tree = ast.parse(
        "if enabled:\n    _gather_safety_state = forged\ndef check():\n    portfolio_state = _gather_safety_state()\n"
    )
    assert "_gather_safety_state" in _module_provider_rebindings(
        conditional_module_tree,
        relative,
    )

    global_module_tree = ast.parse(
        "def _gather_safety_state():\n"
        "    return object()\n"
        "def replace_provider(forged):\n"
        "    global _gather_safety_state\n"
        "    _gather_safety_state = forged\n"
    )
    assert "_gather_safety_state" in _module_provider_rebindings(
        global_module_tree,
        relative,
    )


def test_prospective_greek_guard_rejects_dynamic_self_provider_rebinding() -> None:
    function = ast.parse(
        "def check(self, forged):\n"
        "    self.__dict__['_portfolio_state_provider'] = forged\n"
        "    portfolio_state = self._portfolio_state_provider()\n"
        "    admission = portfolio_state.admission_for(0)\n"
    ).body[0]
    assert isinstance(function, ast.FunctionDef)
    assert "_portfolio_state_provider" in _rebound_self_attributes(function)
    assert _proven_admission_names(function, _assignment_sources(function)) == set()

    computed = ast.parse(
        "def check(self, forged):\n"
        "    setattr(self, '_portfolio_state_' + 'provider', forged)\n"
        "    portfolio_state = self._portfolio_state_provider()\n"
        "    admission = portfolio_state.admission_for(0)\n"
    ).body[0]
    assert isinstance(computed, ast.FunctionDef)
    assert "_portfolio_state_provider" in _rebound_self_attributes(computed)
    assert _proven_admission_names(computed, _assignment_sources(computed)) == set()

    updated = ast.parse(
        "def check(self, forged):\n"
        "    self.__dict__.update({'_portfolio_state_provider': forged})\n"
        "    portfolio_state = self._portfolio_state_provider()\n"
        "    admission = portfolio_state.admission_for(0)\n"
    ).body[0]
    aliased_dict = ast.parse(
        "def check(self, forged):\n"
        "    state = self.__dict__\n"
        "    state['_portfolio_state_provider'] = forged\n"
        "    portfolio_state = self._portfolio_state_provider()\n"
        "    admission = portfolio_state.admission_for(0)\n"
    ).body[0]
    setitem_dict = ast.parse(
        "def check(self, forged):\n"
        "    self.__dict__.__setitem__('_portfolio_state_provider', forged)\n"
        "    portfolio_state = self._portfolio_state_provider()\n"
        "    admission = portfolio_state.admission_for(0)\n"
    ).body[0]
    unbound_setitem = ast.parse(
        "def check(self, forged):\n"
        "    dict.__setitem__(self.__dict__, '_portfolio_state_provider', forged)\n"
        "    portfolio_state = self._portfolio_state_provider()\n"
        "    admission = portfolio_state.admission_for(0)\n"
    ).body[0]
    unbound_update = ast.parse(
        "def check(self, forged):\n"
        "    dict.update(self.__dict__, {'_portfolio_state_provider': forged})\n"
        "    portfolio_state = self._portfolio_state_provider()\n"
        "    admission = portfolio_state.admission_for(0)\n"
    ).body[0]
    qualified_vars = ast.parse(
        "import builtins\n"
        "def check(self, forged):\n"
        "    builtins.vars(self)['_portfolio_state_provider'] = forged\n"
        "    portfolio_state = self._portfolio_state_provider()\n"
        "    admission = portfolio_state.admission_for(0)\n"
    ).body[1]
    qualified_object_setattr = ast.parse(
        "import builtins\n"
        "def check(self, forged):\n"
        "    builtins.object.__setattr__(self, '_portfolio_state_provider', forged)\n"
        "    portfolio_state = self._portfolio_state_provider()\n"
        "    admission = portfolio_state.admission_for(0)\n"
    ).body[1]
    unknown_update = ast.parse(
        "def check(self, forged):\n"
        "    payload = make_payload(forged)\n"
        "    dict.update(self.__dict__, payload)\n"
        "    portfolio_state = self._portfolio_state_provider()\n"
        "    admission = portfolio_state.admission_for(0)\n"
    ).body[0]
    augmented_union = ast.parse(
        "def check(self, forged):\n"
        "    state = self.__dict__\n"
        "    state |= {'_portfolio_state_provider': forged}\n"
        "    portfolio_state = self._portfolio_state_provider()\n"
        "    admission = portfolio_state.admission_for(0)\n"
    ).body[0]
    operator_setitem = ast.parse(
        "import operator\n"
        "def check(self, forged):\n"
        "    operator.setitem(self.__dict__, '_portfolio_state_provider', forged)\n"
        "    portfolio_state = self._portfolio_state_provider()\n"
        "    admission = portfolio_state.admission_for(0)\n"
    ).body[1]
    assert isinstance(updated, ast.FunctionDef)
    assert isinstance(aliased_dict, ast.FunctionDef)
    assert isinstance(setitem_dict, ast.FunctionDef)
    assert isinstance(unbound_setitem, ast.FunctionDef)
    assert isinstance(unbound_update, ast.FunctionDef)
    assert isinstance(qualified_vars, ast.FunctionDef)
    assert isinstance(qualified_object_setattr, ast.FunctionDef)
    assert isinstance(unknown_update, ast.FunctionDef)
    assert isinstance(augmented_union, ast.FunctionDef)
    assert isinstance(operator_setitem, ast.FunctionDef)
    assert "_portfolio_state_provider" in _rebound_self_attributes(updated)
    assert "_portfolio_state_provider" in _rebound_self_attributes(aliased_dict)
    assert "_portfolio_state_provider" in _rebound_self_attributes(setitem_dict)
    assert "_portfolio_state_provider" in _rebound_self_attributes(unbound_setitem)
    assert "_portfolio_state_provider" in _rebound_self_attributes(unbound_update)
    assert "_portfolio_state_provider" in _rebound_self_attributes(qualified_vars)
    assert "_portfolio_state_provider" in _rebound_self_attributes(qualified_object_setattr)
    assert "*" in _rebound_self_attributes(unknown_update)
    assert "_portfolio_state_provider" in _rebound_self_attributes(augmented_union)
    assert "_portfolio_state_provider" in _rebound_self_attributes(operator_setitem)
    assert _proven_admission_names(updated, _assignment_sources(updated)) == set()
    assert _proven_admission_names(aliased_dict, _assignment_sources(aliased_dict)) == set()
    assert _proven_admission_names(setitem_dict, _assignment_sources(setitem_dict)) == set()
    assert _proven_admission_names(unbound_setitem, _assignment_sources(unbound_setitem)) == set()
    assert _proven_admission_names(unbound_update, _assignment_sources(unbound_update)) == set()
    assert _proven_admission_names(qualified_vars, _assignment_sources(qualified_vars)) == set()
    assert _proven_admission_names(qualified_object_setattr, _assignment_sources(qualified_object_setattr)) == set()
    assert _proven_admission_names(unknown_update, _assignment_sources(unknown_update)) == set()
    assert _proven_admission_names(augmented_union, _assignment_sources(augmented_union)) == set()
    assert _proven_admission_names(operator_setitem, _assignment_sources(operator_setitem)) == set()


def test_prospective_greek_guard_rejects_dynamic_module_provider_rebinding() -> None:
    relative = "packages/core/core/src/flinttrade_core/order_routes.py"
    subscript_tree = ast.parse("def replace(forged):\n    globals()['_gather_safety_state'] = forged\n")
    update_tree = ast.parse("def replace(forged):\n    globals().update({'_gather_safety_state': forged})\n")
    qualified_subscript_tree = ast.parse(
        "import builtins\ndef replace(forged):\n    builtins.globals()['_gather_safety_state'] = forged\n"
    )
    qualified_update_tree = ast.parse(
        "import builtins\ndef replace(forged):\n    builtins.globals().update({'_gather_safety_state': forged})\n"
    )
    imported_setitem_tree = ast.parse(
        "from builtins import globals as global_namespace\n"
        "def replace(forged):\n"
        "    global_namespace().__setitem__('_gather_safety_state', forged)\n"
    )
    unbound_update_tree = ast.parse(
        "def replace(forged):\n    dict.update(globals(), {'_gather_safety_state': forged})\n"
    )
    in_place_or_tree = ast.parse("def replace(forged):\n    globals().__ior__({'_gather_safety_state': forged})\n")
    unknown_update_tree = ast.parse("def replace(payload):\n    dict.update(globals(), payload)\n")
    augmented_union_tree = ast.parse(
        "def replace(forged):\n    namespace = globals()\n    namespace |= {'_gather_safety_state': forged}\n"
    )
    operator_setitem_tree = ast.parse(
        "import operator\ndef replace(forged):\n    operator.setitem(globals(), '_gather_safety_state', forged)\n"
    )
    assert "_gather_safety_state" in _module_provider_rebindings(subscript_tree, relative)
    assert "_gather_safety_state" in _module_provider_rebindings(update_tree, relative)
    assert "_gather_safety_state" in _module_provider_rebindings(qualified_subscript_tree, relative)
    assert "_gather_safety_state" in _module_provider_rebindings(qualified_update_tree, relative)
    assert "_gather_safety_state" in _module_provider_rebindings(imported_setitem_tree, relative)
    assert "_gather_safety_state" in _module_provider_rebindings(unbound_update_tree, relative)
    assert "_gather_safety_state" in _module_provider_rebindings(in_place_or_tree, relative)
    assert "_gather_safety_state" in _module_provider_rebindings(unknown_update_tree, relative)
    assert "_gather_safety_state" in _module_provider_rebindings(augmented_union_tree, relative)
    assert "_gather_safety_state" in _module_provider_rebindings(operator_setitem_tree, relative)


def test_prospective_greek_guard_rejects_sibling_self_provider_rebinding() -> None:
    relative = "packages/services/engine/src/flinttrade_engine/strategy_execution.py"
    canonical_tree = ast.parse(
        "class Executor:\n"
        "    def __init__(self, portfolio_state_provider):\n"
        "        self._portfolio_state_provider = portfolio_state_provider\n"
        "    def check(self):\n"
        "        return self._portfolio_state_provider()\n"
    )
    forged_tree = ast.parse(
        "class Executor:\n"
        "    def __init__(self, portfolio_state_provider):\n"
        "        self._portfolio_state_provider = portfolio_state_provider\n"
        "    def replace(self, forged):\n"
        "        setattr(self, '_portfolio_state_' + 'provider', forged)\n"
        "    def check(self):\n"
        "        return self._portfolio_state_provider()\n"
    )
    rebound_parameter_tree = ast.parse(
        "class Executor:\n"
        "    def __init__(self, portfolio_state_provider, forged):\n"
        "        portfolio_state_provider = forged\n"
        "        self._portfolio_state_provider = portfolio_state_provider\n"
        "    def check(self):\n"
        "        return self._portfolio_state_provider()\n"
    )
    nested_rebind_tree = ast.parse(
        "class Executor:\n"
        "    def __init__(self, portfolio_state_provider):\n"
        "        self._portfolio_state_provider = portfolio_state_provider\n"
        "    def replace(self, forged):\n"
        "        def nested():\n"
        "            self._portfolio_state_provider = forged\n"
        "        nested()\n"
        "    def check(self):\n"
        "        return self._portfolio_state_provider()\n"
    )
    missing_parameter_tree = ast.parse(
        "portfolio_state_provider = forged\n"
        "class Executor:\n"
        "    def __init__(self):\n"
        "        self._portfolio_state_provider = portfolio_state_provider\n"
        "    def check(self):\n"
        "        return self._portfolio_state_provider()\n"
    )
    nonlocal_rebind_tree = ast.parse(
        "class Executor:\n"
        "    def __init__(self, portfolio_state_provider, forged):\n"
        "        self._portfolio_state_provider = portfolio_state_provider\n"
        "        def replace():\n"
        "            nonlocal portfolio_state_provider\n"
        "            portfolio_state_provider = forged\n"
        "        replace()\n"
        "    def check(self):\n"
        "        return self._portfolio_state_provider()\n"
    )
    self_alias_tree = ast.parse(
        "class Executor:\n"
        "    def __init__(self, portfolio_state_provider, forged):\n"
        "        self._portfolio_state_provider = portfolio_state_provider\n"
        "        target = self\n"
        "        target._portfolio_state_provider = forged\n"
        "    def check(self):\n"
        "        return self._portfolio_state_provider()\n"
    )
    dict_update_tree = ast.parse(
        "class Executor:\n"
        "    def __init__(self, portfolio_state_provider, forged):\n"
        "        self._portfolio_state_provider = portfolio_state_provider\n"
        "        self.__dict__.update({'_portfolio_state_provider': forged})\n"
        "    def check(self):\n"
        "        return self._portfolio_state_provider()\n"
    )
    dict_setitem_tree = ast.parse(
        "class Executor:\n"
        "    def __init__(self, portfolio_state_provider, forged):\n"
        "        self._portfolio_state_provider = portfolio_state_provider\n"
        "        self.__dict__.__setitem__('_portfolio_state_provider', forged)\n"
        "    def check(self):\n"
        "        return self._portfolio_state_provider()\n"
    )
    unbound_dict_update_tree = ast.parse(
        "class Executor:\n"
        "    def __init__(self, portfolio_state_provider, forged):\n"
        "        self._portfolio_state_provider = portfolio_state_provider\n"
        "        dict.update(self.__dict__, {'_portfolio_state_provider': forged})\n"
        "    def check(self):\n"
        "        return self._portfolio_state_provider()\n"
    )
    qualified_setattr_tree = ast.parse(
        "import builtins\n"
        "class Executor:\n"
        "    def __init__(self, portfolio_state_provider, forged):\n"
        "        self._portfolio_state_provider = portfolio_state_provider\n"
        "        builtins.object.__setattr__(self, '_portfolio_state_provider', forged)\n"
        "    def check(self):\n"
        "        return self._portfolio_state_provider()\n"
    )
    augmented_dict_tree = ast.parse(
        "class Executor:\n"
        "    def __init__(self, portfolio_state_provider, forged):\n"
        "        self._portfolio_state_provider = portfolio_state_provider\n"
        "        state = self.__dict__\n"
        "        state |= {'_portfolio_state_provider': forged}\n"
        "    def check(self):\n"
        "        return self._portfolio_state_provider()\n"
    )
    assert _class_provider_rebindings(canonical_tree, relative) == set()
    assert _class_provider_rebindings(forged_tree, relative) == {"_portfolio_state_provider"}
    assert _class_provider_rebindings(rebound_parameter_tree, relative) == {"_portfolio_state_provider"}
    assert _class_provider_rebindings(nested_rebind_tree, relative) == {"_portfolio_state_provider"}
    assert _class_provider_rebindings(missing_parameter_tree, relative) == {"_portfolio_state_provider"}
    assert _class_provider_rebindings(nonlocal_rebind_tree, relative) == {"_portfolio_state_provider"}
    assert _class_provider_rebindings(self_alias_tree, relative) == {"_portfolio_state_provider"}
    assert _class_provider_rebindings(dict_update_tree, relative) == {"_portfolio_state_provider"}
    assert _class_provider_rebindings(dict_setitem_tree, relative) == {"_portfolio_state_provider"}
    assert _class_provider_rebindings(unbound_dict_update_tree, relative) == {"_portfolio_state_provider"}
    assert _class_provider_rebindings(qualified_setattr_tree, relative) == {"_portfolio_state_provider"}
    assert _class_provider_rebindings(augmented_dict_tree, relative) == {"_portfolio_state_provider"}


def test_prospective_greek_guard_rejects_unknown_namespace_mutations() -> None:
    unknown_kwargs = ast.parse(
        "def check(self, payload):\n"
        "    self.__dict__.update(**payload)\n"
        "    portfolio_state = self._portfolio_state_provider()\n"
        "    admission = portfolio_state.admission_for(0)\n"
    ).body[0]
    dynamic_subscript = ast.parse(
        "def check(self, name, forged):\n"
        "    self.__dict__[name] = forged\n"
        "    portfolio_state = self._portfolio_state_provider()\n"
        "    admission = portfolio_state.admission_for(0)\n"
    ).body[0]
    dynamic_setattr = ast.parse(
        "def check(self, name, forged):\n"
        "    setattr(self, name, forged)\n"
        "    portfolio_state = self._portfolio_state_provider()\n"
        "    admission = portfolio_state.admission_for(0)\n"
    ).body[0]
    replace_dict = ast.parse(
        "def check(self, payload):\n"
        "    self.__dict__ = payload\n"
        "    portfolio_state = self._portfolio_state_provider()\n"
        "    admission = portfolio_state.admission_for(0)\n"
    ).body[0]

    for function in (unknown_kwargs, dynamic_subscript, dynamic_setattr, replace_dict):
        assert isinstance(function, ast.FunctionDef)
        assert "*" in _rebound_self_attributes(function)
        assert _proven_admission_names(function, _assignment_sources(function)) == set()

    relative = "packages/services/engine/src/flinttrade_engine/strategy_execution.py"
    constructor_tree = ast.parse(
        "class Executor:\n"
        "    def __init__(self, portfolio_state_provider, payload):\n"
        "        self._portfolio_state_provider = portfolio_state_provider\n"
        "        self.__dict__.update(**payload)\n"
        "    def check(self):\n"
        "        return self._portfolio_state_provider()\n"
    )
    assert _class_provider_rebindings(constructor_tree, relative) == {"_portfolio_state_provider"}

    module_relative = "packages/core/core/src/flinttrade_core/order_routes.py"
    module_tree = ast.parse("def replace(payload):\n    globals().update(**payload)\n")
    assert "_gather_safety_state" in _module_provider_rebindings(module_tree, module_relative)


def test_prospective_greek_guard_follows_callable_aliases() -> None:
    alias_sources = (
        "dict.__setitem__",
        "operator.setitem",
    )
    for source in alias_sources:
        prefix = "import operator\n" if source.startswith("operator.") else ""
        function = ast.parse(
            prefix
            + "def check(self, forged):\n"
            + f"    put = {source}\n"
            + "    put(self.__dict__, '_portfolio_state_provider', forged)\n"
            + "    portfolio_state = self._portfolio_state_provider()\n"
            + "    admission = portfolio_state.admission_for(0)\n"
        ).body[-1]
        assert isinstance(function, ast.FunctionDef)
        assert "_portfolio_state_provider" in _rebound_self_attributes(function)
        assert _proven_admission_names(function, _assignment_sources(function)) == set()

    object_setattr = ast.parse(
        "def check(self, forged):\n"
        "    put = object.__setattr__\n"
        "    put(self, '_portfolio_state_provider', forged)\n"
        "    portfolio_state = self._portfolio_state_provider()\n"
        "    admission = portfolio_state.admission_for(0)\n"
    ).body[0]
    assert isinstance(object_setattr, ast.FunctionDef)
    assert "_portfolio_state_provider" in _rebound_self_attributes(object_setattr)
    assert _proven_admission_names(object_setattr, _assignment_sources(object_setattr)) == set()

    helper_function = ast.parse(
        "def check(admission):\n"
        "    lookup = globals().__getitem__\n"
        "    lookup('_check_order_with_state')(admission=admission)\n"
    ).body[0]
    assert isinstance(helper_function, ast.FunctionDef)
    assert _unapproved_helper_references(helper_function)

    check_order_tree = ast.parse(
        "def check(safety, order, admission):\n"
        "    lookup = type(safety).__dict__.__getitem__\n"
        "    lookup('check_order')(\n"
        "        safety, order, ltp=1, net_delta=admission.net_delta, net_vega=admission.net_vega\n"
        "    )\n"
    )
    assert _unapproved_check_order_references(check_order_tree)

    module_relative = "packages/core/core/src/flinttrade_core/order_routes.py"
    module_tree = ast.parse(
        "def replace(forged):\n    put = globals().__setitem__\n    put('_gather_safety_state', forged)\n"
    )
    assert "_gather_safety_state" in _module_provider_rebindings(module_tree, module_relative)


def test_prospective_greek_guard_covers_module_lambda_and_vars_namespaces() -> None:
    tree = ast.parse(
        "globals()['_check_order_with_state'](admission=admission)\n"
        "probe = lambda admission: globals().get('_check_order_with_state')(admission=admission)\n"
    )
    references = _dynamic_helper_references_in_tree(tree)
    assert {reference.lineno for reference in references} == {1, 2}

    module_tree = ast.parse("import builtins\nbuiltins.vars()['_gather_safety_state'] = forged\n")
    relative = "packages/core/core/src/flinttrade_core/order_routes.py"
    assert "_gather_safety_state" in _module_provider_rebindings(module_tree, relative)


def test_prospective_greek_guard_follows_nonlocal_provider_mutation_aliases() -> None:
    module_relative = "packages/core/core/src/flinttrade_core/order_routes.py"
    module_alias_tree = ast.parse(
        "put = dict.__setitem__\ndef replace(forged):\n    put(globals(), '_gather_safety_state', forged)\n"
    )
    imported_alias_tree = ast.parse(
        "from operator import setitem as put\n"
        "def replace(forged):\n"
        "    put(globals(), '_gather_safety_state', forged)\n"
    )
    default_alias_tree = ast.parse(
        "def replace(forged, put=dict.__setitem__):\n    put(globals(), '_gather_safety_state', forged)\n"
    )
    bound_getattr_tree = ast.parse(
        "def replace(forged):\n    put = getattr(globals(), '__setitem__')\n    put('_gather_safety_state', forged)\n"
    )
    for tree in (module_alias_tree, imported_alias_tree, default_alias_tree, bound_getattr_tree):
        assert "_gather_safety_state" in _module_provider_rebindings(tree, module_relative)

    class_relative = "packages/services/engine/src/flinttrade_engine/strategy_execution.py"
    class_module_alias_tree = ast.parse(
        "put = dict.__setitem__\n"
        "class Executor:\n"
        "    def __init__(self, portfolio_state_provider):\n"
        "        self._portfolio_state_provider = portfolio_state_provider\n"
        "    def replace(self, forged):\n"
        "        put(self.__dict__, '_portfolio_state_provider', forged)\n"
    )
    class_import_alias_tree = ast.parse(
        "from operator import setitem as put\n"
        "class Executor:\n"
        "    def __init__(self, portfolio_state_provider):\n"
        "        self._portfolio_state_provider = portfolio_state_provider\n"
        "    def replace(self, forged):\n"
        "        put(self.__dict__, '_portfolio_state_provider', forged)\n"
    )
    class_default_alias_tree = ast.parse(
        "class Executor:\n"
        "    def __init__(self, portfolio_state_provider):\n"
        "        self._portfolio_state_provider = portfolio_state_provider\n"
        "    def replace(self, forged, put=dict.__setitem__):\n"
        "        put(self.__dict__, '_portfolio_state_provider', forged)\n"
    )
    class_bound_getattr_tree = ast.parse(
        "class Executor:\n"
        "    def __init__(self, portfolio_state_provider):\n"
        "        self._portfolio_state_provider = portfolio_state_provider\n"
        "    def replace(self, forged):\n"
        "        put = getattr(self.__dict__, '__setitem__')\n"
        "        put('_portfolio_state_provider', forged)\n"
    )
    for tree in (
        class_module_alias_tree,
        class_import_alias_tree,
        class_default_alias_tree,
        class_bound_getattr_tree,
    ):
        assert _class_provider_rebindings(tree, class_relative) == {"_portfolio_state_provider"}


def test_prospective_greek_guard_fails_closed_for_indirect_protected_call_recovery() -> None:
    helper_default_tree = ast.parse(
        "def check(helpers, admission, lookup=getattr):\n"
        "    lookup(helpers, '_check_order_with_state')(admission=admission)\n"
    )
    helper_lambda_default_tree = ast.parse(
        "probe = lambda helpers, admission, lookup=getattr: "
        "lookup(helpers, '_check_order_with_state')(admission=admission)\n"
    )
    helper_bound_mapping_tree = ast.parse(
        "def check(admission):\n"
        "    getter = getattr(globals(), 'get')\n"
        "    getter('_check_order_with_state')(admission=admission)\n"
    )
    helper_dynamic_name_tree = ast.parse(
        "def check(admission, name):\n    getter = getattr(globals(), 'get')\n    getter(name)(admission=admission)\n"
    )
    for tree in (
        helper_default_tree,
        helper_lambda_default_tree,
        helper_bound_mapping_tree,
        helper_dynamic_name_tree,
    ):
        assert _dynamic_helper_references_in_tree(tree)

    check_default_tree = ast.parse(
        "def check(safety, order, admission, lookup=getattr):\n"
        "    lookup(safety, 'check_order')(\n"
        "        order, ltp=1, net_delta=admission.net_delta, net_vega=admission.net_vega\n"
        "    )\n"
    )
    check_lambda_default_tree = ast.parse(
        "probe = lambda safety, order, admission, lookup=getattr: lookup(safety, 'check_order')(\n"
        "    order, ltp=1, net_delta=admission.net_delta, net_vega=admission.net_vega\n"
        ")\n"
    )
    check_bound_mapping_tree = ast.parse(
        "def check(safety, order, admission):\n"
        "    getter = getattr(type(safety).__dict__, 'get')\n"
        "    getter('check_order')(\n"
        "        safety, order, ltp=1, net_delta=admission.net_delta, net_vega=admission.net_vega\n"
        "    )\n"
    )
    check_dynamic_name_tree = ast.parse(
        "def check(safety, order, admission, name):\n"
        "    getattr(safety, name)(\n"
        "        order, ltp=1, net_delta=admission.net_delta, net_vega=admission.net_vega\n"
        "    )\n"
    )
    for tree in (
        check_default_tree,
        check_lambda_default_tree,
        check_bound_mapping_tree,
        check_dynamic_name_tree,
    ):
        assert _unapproved_check_order_references(tree)

    benign_trees = (
        ast.parse("def read(name):\n    return getattr(locals(), 'get')(name)()\n"),
        ast.parse("def read(name):\n    return getattr(vars(), 'get')(name)()\n"),
        ast.parse("def read(mapping, name):\n    return getattr(mapping, 'get')(name)()\n"),
        ast.parse("def read(registry, name):\n    return getattr(registry, name)()\n"),
    )
    for tree in benign_trees:
        assert _dynamic_helper_references_in_tree(tree) == []
        assert _unapproved_check_order_references(tree) == []


def test_prospective_greek_guard_treats_module_locals_as_globals_only_at_module_scope() -> None:
    relative = "packages/core/core/src/flinttrade_core/order_routes.py"
    qualified_tree = ast.parse("import builtins\nbuiltins.locals()['_gather_safety_state'] = forged\n")
    imported_tree = ast.parse(
        "from builtins import locals as module_namespace\nmodule_namespace().update({'_gather_safety_state': forged})\n"
    )
    for tree in (qualified_tree, imported_tree):
        assert "_gather_safety_state" in _module_provider_rebindings(tree, relative)

    function_local_tree = ast.parse(
        "import builtins\ndef replace(forged):\n    builtins.locals()['_gather_safety_state'] = forged\n"
    )
    assert "_gather_safety_state" not in _module_provider_rebindings(function_local_tree, relative)


def test_prospective_greek_guard_rejects_broader_provider_rebinding_bypass_matrix() -> None:
    self_functions = (
        ast.parse(
            "def replace(self, forged):\n"
            "    getattr(self, '__dict__').update(\n"
            "        {'_portfolio_state_provider': forged}\n"
            "    )\n"
        ).body[0],
        ast.parse(
            "import operator\n"
            "def replace(self, forged):\n"
            "    operator.attrgetter('__dict__')(self).update(\n"
            "        {'_portfolio_state_provider': forged}\n"
            "    )\n"
        ).body[1],
        ast.parse(
            "def replace(self, forged):\n"
            "    object.__getattribute__(self, '__dict__').update(\n"
            "        {'_portfolio_state_provider': forged}\n"
            "    )\n"
        ).body[0],
        ast.parse(
            "import operator\n"
            "def replace(self, forged):\n"
            "    operator.attrgetter('__dict__.__setitem__')(self)(\n"
            "        '_portfolio_state_provider', forged\n"
            "    )\n"
        ).body[1],
        ast.parse(
            "import operator\n"
            "def replace(self, forged):\n"
            "    operator.methodcaller(\n"
            "        '__setattr__', '_portfolio_state_provider', forged\n"
            "    )(self)\n"
        ).body[1],
        ast.parse(
            "import builtins\n"
            "def replace(self, forged):\n"
            "    builtins.__dict__['setattr'](\n"
            "        self, '_portfolio_state_provider', forged\n"
            "    )\n"
        ).body[1],
        ast.parse(
            "def replace(self, forged):\n"
            "    setattr(\n"
            "        self, '_portfolio_state_Xprovider'.replace('X', ''), forged\n"
            "    )\n"
        ).body[0],
    )
    for function in self_functions:
        assert isinstance(function, ast.FunctionDef)
        assert "_portfolio_state_provider" in _rebound_self_attributes(function)

    class_relative = "packages/services/engine/src/flinttrade_engine/strategy_execution.py"
    super_tree = ast.parse(
        "class Executor(Base):\n"
        "    def __init__(self, portfolio_state_provider):\n"
        "        self._portfolio_state_provider = portfolio_state_provider\n"
        "    def replace(self, forged):\n"
        "        super().__setattr__('_portfolio_state_provider', forged)\n"
    )
    forged_constructor_default_tree = ast.parse(
        "class Executor:\n"
        "    def __init__(self, portfolio_state_provider=forged):\n"
        "        self._portfolio_state_provider = portfolio_state_provider\n"
    )
    forged_provider_default = ast.parse(
        "def check(_gather_safety_state=forged):\n"
        "    portfolio_state = _gather_safety_state()\n"
        "    admission = portfolio_state.admission_for(0)\n"
    ).body[0]
    assert _class_provider_rebindings(super_tree, class_relative) == {"_portfolio_state_provider"}
    assert _class_provider_rebindings(forged_constructor_default_tree, class_relative) == {"_portfolio_state_provider"}
    assert isinstance(forged_provider_default, ast.FunctionDef)
    assert (
        _proven_admission_names(
            forged_provider_default,
            _assignment_sources(forged_provider_default),
        )
        == set()
    )

    module_relative = "packages/core/core/src/flinttrade_core/order_routes.py"
    module_trees = (
        ast.parse("import sys\nsys.modules[__name__].__dict__['_gather_safety_state'] = forged\n"),
        ast.parse("import sys\nsys.modules[__name__]._gather_safety_state = forged\n"),
        ast.parse("import sys\nsetattr(sys.modules[__name__], '_gather_safety_state', forged)\n"),
        ast.parse("import sys\nvars(sys.modules[__name__]).update({'_gather_safety_state': forged})\n"),
        ast.parse("def replace(module, forged):\n    vars(module).update({'_gather_safety_state': forged})\n"),
        ast.parse(
            "import builtins\nbuiltins.__dict__['globals']().__setitem__(\n    '_gather_safety_state', forged\n)\n"
        ),
        ast.parse("globals().__setitem__(\n    '_gatherXsafety_state'.replace('X', '_'), forged\n)\n"),
        ast.parse(
            "import operator\n"
            "def replace(name, forged):\n"
            "    operator.methodcaller('__setitem__', name, forged)(globals())\n"
        ),
    )
    for tree in module_trees:
        assert "_gather_safety_state" in _module_provider_rebindings(tree, module_relative)


def test_prospective_greek_guard_rejects_broader_protected_call_bypass_matrix() -> None:
    helper_trees = (
        ast.parse(
            "import operator\n"
            "def check(helpers, admission):\n"
            "    operator.attrgetter('_check_order_with_state')(helpers)(\n"
            "        admission=admission\n"
            "    )\n"
        ),
        ast.parse(
            "import operator\n"
            "def check(helpers, admission):\n"
            "    operator.methodcaller(\n"
            "        '_check_order_with_state', admission=admission\n"
            "    )(helpers)\n"
        ),
        ast.parse(
            "def check(helpers, admission):\n"
            "    getattr(\n"
            "        helpers, '_checkXorder_with_state'.replace('X', '_')\n"
            "    )(admission=admission)\n"
        ),
        ast.parse(
            "import sys\nsys.modules[__name__].__dict__.get('_check_order_with_state')(\n    admission=admission\n)\n"
        ),
        ast.parse(
            "import sys\n"
            "getattr(vars(sys.modules[__name__]), 'get')(\n"
            "    '_check_order_with_state'\n"
            ")(admission=admission)\n"
        ),
        ast.parse(
            "import builtins\n"
            "builtins.__dict__['globals']().get('_check_order_with_state')(\n"
            "    admission=admission\n"
            ")\n"
        ),
    )
    for tree in helper_trees:
        assert _dynamic_helper_references_in_tree(tree)

    check_order_trees = (
        ast.parse(
            "def check(safety, order, admission):\n"
            "    target = safety\n"
            "    getattr(target, 'CHECK_ORDER'.lower())(\n"
            "        order, ltp=1, net_delta=admission.net_delta, "
            "net_vega=admission.net_vega\n"
            "    )\n"
        ),
        ast.parse(
            "import builtins\n"
            "def check(safety, order, admission):\n"
            "    builtins.__dict__.get('getattr')(safety, 'check_order')(\n"
            "        order, ltp=1, net_delta=admission.net_delta, "
            "net_vega=admission.net_vega\n"
            "    )\n"
        ),
        ast.parse(
            "import operator\n"
            "def check(safety, order, admission):\n"
            "    getattr(operator, 'attrgetter')('check_order')(safety)(\n"
            "        order, ltp=1, net_delta=admission.net_delta, "
            "net_vega=admission.net_vega\n"
            "    )\n"
        ),
        ast.parse(
            "import operator\n"
            "def check(safety, order, admission):\n"
            "    operator.attrgetter('check_order')(safety)(\n"
            "        order, ltp=1, net_delta=admission.net_delta, "
            "net_vega=admission.net_vega\n"
            "    )\n"
        ),
        ast.parse(
            "import operator\n"
            "def check(safety, order, admission):\n"
            "    operator.methodcaller(\n"
            "        'check_order', order, ltp=1, net_delta=admission.net_delta,\n"
            "        net_vega=admission.net_vega\n"
            "    )(safety)\n"
        ),
        ast.parse(
            "import builtins\n"
            "def check(safety, order, admission):\n"
            "    builtins.__dict__['getattr'](safety, 'check_order')(\n"
            "        order, ltp=1, net_delta=admission.net_delta, "
            "net_vega=admission.net_vega\n"
            "    )\n"
        ),
        ast.parse(
            "def check(safety, order, admission):\n"
            "    getattr(safety, 'checkXorder'.replace('X', '_'))(\n"
            "        order, ltp=1, net_delta=admission.net_delta, "
            "net_vega=admission.net_vega\n"
            "    )\n"
        ),
        ast.parse("def validate(safety, callable):\n    return callable(getattr(safety, 'check_order', None))\n"),
    )
    for tree in check_order_trees:
        assert _unapproved_check_order_references(tree)

    builtin_probe_tree = ast.parse(
        "import builtins\ndef validate(safety):\n    return builtins.callable(getattr(safety, 'check_order', None))\n"
    )
    imported_builtin_probe_tree = ast.parse(
        "from builtins import callable as is_callable\n"
        "def validate(safety):\n"
        "    return is_callable(getattr(safety, 'check_order', None))\n"
    )
    assert _unapproved_check_order_references(builtin_probe_tree) == []
    assert _unapproved_check_order_references(imported_builtin_probe_tree) == []


# Modules that legitimately contain a RAW (non-router) broker order-write. This
# is the SHRINKING debt allowlist: every remaining entry is a known-dormant
# native strategy/agent path tracked in PLAN.md. L5 emergency actions are NOT an
# exemption: they traverse gate_broker_write -> BrokerRouter.execute_gated.
_RAW_ORDER_ALLOWLIST = {
    # Dormant — not wired to any live route/schedule (PLAN.md tracks the refactor):
    # (flinttrade_ai/autonomous_agent.py REMOVED 2026-06-10: its order writes now
    #  go through an injected gated executor — SafetySystem → gate_order →
    #  BrokerRouter — and it fails closed without one.)
    # (flinttrade_engine/bracket_order.py REMOVED 2026-07-07: every bracket leg
    #  now dispatches through the injected gated dispatchers — SafetySystem →
    #  gate_order → BrokerRouter — and the service holds no raw client; the pin
    #  test_bracket_order_writes_only_through_gated_router below keeps it out.)
    # (flinttrade_engine/router.py REMOVED 2026-07-09: the legacy ungated
    #  OrderRouter is deleted; the only live dispatch is gate_order → BrokerRouter.)
    # Dormant automation service, not mounted by the FlintTrade core app. It
    # accepts an arbitrary ``order_router`` object and must be folded into the
    # canonical gated router before becoming reachable.
    "packages/services/automation/src/flinttrade_automation/voice_order_bridge.py",
}

# Legacy engine/AI stacks that dispatch through their own ``route_order`` API
# instead of the canonical gate_order -> BrokerRouter surface. Keep this
# allowlist explicit and shrinking; a new ``.route_order(`` call must prove it is
# canonical before being added.
_RAW_ROUTE_ORDER_ALLOWLIST = {
    "packages/services/engine/src/flinttrade_engine/smart_router.py",
    # basket_orders.py + split_orders.py graduated 2026-07-09 (G13): each leg/
    # chunk now dispatches through the gated build_gated_leg_dispatchers place_leg
    # (gate_order -> BrokerRouter), so they carry no raw ``.route_order(`` call.
    "packages/services/ai/src/flinttrade_ai/autonomous_agent.py",
}
_ROUTE_ORDER_RE = re.compile(r"\.route_order\s*\(")

# Raw OpenAlgoClient modify/cancel calls have no exemptions. The binding-aware
# AST guard below follows receiver and bound-callable aliases rather than
# trusting a variable merely because its spelling contains ``router``.
_RAW_OPENALGO_MOD_CANCEL_ALLOWLIST: set[str] = set()


def _resolves_safety_context(
    value: ast.AST,
    assignments: dict[str, list[ast.AST]],
    resolving: frozenset[str] = frozenset(),
) -> bool:
    if isinstance(value, ast.Name):
        if value.id in resolving:
            return False
        sources = assignments.get(value.id, [])
        if value.id == "SafetyContext" and not sources:
            return True
        return len(sources) == 1 and _resolves_safety_context(
            sources[0],
            assignments,
            resolving | {value.id},
        )
    return isinstance(value, ast.Attribute) and value.attr == "SafetyContext"


def _safety_context_mint_references(tree: ast.Module) -> list[ast.Call]:
    parents = _parent_nodes(tree)
    lexical_sources_cache: dict[int, dict[str, list[ast.AST]]] = {}
    references: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        assignments = _lexical_assignment_sources(node, tree, parents, lexical_sources_cache)
        found = False
        factory_kind, factory_owner, factory_name, _factory_args = _operator_factory_access(node, assignments)
        if (
            factory_kind == "methodcaller"
            and factory_owner is not None
            and factory_name in {None, "mint"}
            and _resolves_safety_context(factory_owner, assignments)
        ):
            found = True
        for candidate in _resolved_callable_values(node.func, assignments):
            if (
                isinstance(candidate, ast.Attribute)
                and candidate.attr == "mint"
                and _resolves_safety_context(candidate.value, assignments)
            ):
                found = True
                break
            if (
                isinstance(candidate, ast.Subscript)
                and _constant_string(candidate.slice, assignments) == "mint"
                and isinstance(candidate.value, ast.Attribute)
                and candidate.value.attr == "__dict__"
                and _resolves_safety_context(candidate.value.value, assignments)
            ):
                found = True
                break
        if not found and isinstance(node.func, ast.Call):
            recognised, owner, name = _dynamic_attribute_access(node.func, assignments)
            found = bool(
                recognised
                and owner is not None
                and name in {None, "mint"}
                and _resolves_safety_context(owner, assignments)
            )
        if found:
            references.append(node)
    return references


def _safety_context_mint_offenders(tree: ast.Module, relative: str) -> list[ast.AST]:
    """Return SafetyContext mint calls outside canonical ``gate_order``."""
    parents = _parent_nodes(tree)
    offenders: list[ast.AST] = []
    for node in _safety_context_mint_references(tree):
        parent = parents.get(id(node))
        while parent is not None and not isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            parent = parents.get(id(parent))
        canonical = (
            relative == "packages/services/engine/src/flinttrade_engine/safety.py"
            and isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef))
            and parent.name == "gate_order"
        )
        if not canonical:
            offenders.append(node)
    return offenders


_GATEWAY_SRC = Path(__file__).resolve().parents[1] / "src" / "flinttrade_gateway"
_WRITE_METHODS = (
    "place_order",
    "placeorder",
    "placesmartorder",
    "modify_order",
    "cancel_order",
    "cancel_all_orders",
    "close_position",
    "closeposition",
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
    "place_reducing_order",
    "place_multi_order",
    "cancel_smart_order",
)

_CANONICAL_GATED_WRITE_CONTEXTS: dict[str, dict[str, frozenset[str]]] = {
    "packages/integrations/webhooks/src/flinttrade_webhooks/chartink.py": {
        "_place_via_router": frozenset({"place_order"}),
    },
    "packages/services/ditto/src/flinttrade_ditto/mirror.py": {
        "_place_via_router": frozenset({"place_order"}),
    },
    "packages/services/engine/src/flinttrade_engine/bracket_order.py": {
        "place_leg": frozenset({"place_order"}),
        "cancel_leg": frozenset({"cancel_order"}),
    },
    "packages/services/engine/src/flinttrade_engine/safety.py": {
        "_execute_concrete_write": frozenset({"cancel_order"}),
    },
    "packages/services/engine/src/flinttrade_engine/strategy_execution.py": {
        "dispatch_order": frozenset({"place_order"}),
    },
    "packages/core/core/src/flinttrade_core/order_routes.py": {
        "_admit_and_route_live_order": frozenset({"place_order"}),
    },
    "packages/core/core/src/flinttrade_core/smart_order_routes.py": {
        "route_order": frozenset({"place_order"}),
    },
    "packages/core/core/src/flinttrade_core/webhook_dispatch.py": {
        "place_order": frozenset({"place_order"}),
        "cancel_order": frozenset({"cancel_order"}),
    },
}


def _containing_callable(
    node: ast.AST,
    parents: dict[int, ast.AST],
) -> ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda | None:
    parent = parents.get(id(node))
    while parent is not None and not isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        parent = parents.get(id(parent))
    return parent


def _parameter_is_broker_router(
    function: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda | None,
    name: str,
    assignments: dict[str, list[ast.AST]],
) -> bool:
    if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return False

    def origin(value: ast.AST, resolving: frozenset[str] = frozenset()) -> str | None:
        if isinstance(value, ast.Name):
            if value.id in resolving:
                return None
            sources = assignments.get(value.id, [])
            if sources:
                return origin(sources[0], resolving | {value.id}) if len(sources) == 1 else None
            return value.id
        if isinstance(value, ast.Attribute):
            owner = origin(value.value, resolving)
            return f"{owner}.{value.attr}" if owner is not None else None
        return None

    for argument in (*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs):
        if argument.arg == name and argument.annotation is not None:
            return origin(argument.annotation) == "flinttrade_gateway.router.BrokerRouter"
    return False


def _binding_is_raw_broker(
    value: ast.AST,
    assignments: dict[str, list[ast.AST]],
    resolving: frozenset[str] = frozenset(),
) -> bool:
    if isinstance(value, ast.Name):
        if value.id in resolving:
            return True
        sources = assignments.get(value.id, [])
        if sources:
            return any(_binding_is_raw_broker(source, assignments, resolving | {value.id}) for source in sources)
        lowered = value.id.lower()
        return any(marker in lowered for marker in ("client", "adapter", "session"))
    if isinstance(value, ast.Attribute):
        lowered = value.attr.lower()
        if any(marker in lowered for marker in ("client", "adapter", "session")):
            return True
        return _binding_is_raw_broker(value.value, assignments, resolving)
    if isinstance(value, ast.Call):
        if isinstance(value.func, ast.Attribute) and value.func.attr == "get" and value.args:
            key = _constant_string(value.args[0], assignments)
            if key in {"CLIENT", "OPENALGO_CLIENT"}:
                return True
        return False
    return False


def _write_call_targets(
    node: ast.Call,
    assignments: dict[str, list[ast.AST]],
) -> list[tuple[ast.AST, str]]:
    targets: list[tuple[ast.AST, str]] = []
    factory_kind, factory_owner, factory_name, _factory_args = _operator_factory_access(node, assignments)
    if factory_kind == "methodcaller" and factory_owner is not None and factory_name in _WRITE_METHODS:
        targets.append((factory_owner, factory_name))
    for candidate in _resolved_callable_values(node.func, assignments):
        if isinstance(candidate, ast.Attribute) and candidate.attr in _WRITE_METHODS:
            targets.append((candidate.value, candidate.attr))
    if isinstance(node.func, ast.Call):
        recognised, owner, name = _dynamic_attribute_access(node.func, assignments)
        if recognised and owner is not None and name in _WRITE_METHODS:
            targets.append((owner, name))
    return targets


def _is_gated_dispatch_lambda(
    function: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda | None,
    method: str,
    parents: dict[int, ast.AST],
) -> bool:
    if not isinstance(function, ast.Lambda) or method not in {"modify_order", "cancel_order"}:
        return False
    parent = parents.get(id(function))
    if not isinstance(parent, ast.keyword) or parent.arg != "dispatch":
        return False
    dispatch_call = parents.get(id(parent))
    return (
        isinstance(dispatch_call, ast.Call)
        and isinstance(dispatch_call.func, ast.Name)
        and dispatch_call.func.id in {"_dispatch_gated", "_gated_write_dispatch"}
        and {argument.arg for argument in function.args.args} >= {"router", "ctx", "sctx"}
    )


def _is_proven_gated_write(
    relative: str,
    function: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda | None,
    receiver: ast.AST,
    method: str,
    assignments: dict[str, list[ast.AST]],
    parents: dict[int, ast.AST],
) -> bool:
    if _binding_is_raw_broker(receiver, assignments):
        return False
    if isinstance(receiver, ast.Name) and _parameter_is_broker_router(function, receiver.id, assignments):
        return True
    if _is_gated_dispatch_lambda(function, method, parents):
        return True
    function_name = function.name if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)) else ""
    return method in _CANONICAL_GATED_WRITE_CONTEXTS.get(relative, {}).get(function_name, frozenset())


def _is_broker_free_execution_context(
    relative: str,
    receiver: ast.AST,
    assignments: dict[str, list[ast.AST]],
) -> bool:
    if not (
        relative.startswith("packages/core/data/src/flinttrade_data/")
        or relative.startswith("packages/services/backtest/src/flinttrade_backtest/")
        or relative == "packages/core/core/src/flinttrade_core/order_routes.py"
    ):
        return False
    resolved = [receiver, *_resolved_callable_values(receiver, assignments)]
    return any(
        isinstance(value, ast.Name)
        and value.id in {"engine", "sandbox"}
        or isinstance(value, ast.Attribute)
        and value.attr in {"_engine", "sandbox"}
        for value in resolved
    )


def _raw_broker_write_details(tree: ast.Module, relative: str) -> list[tuple[ast.Call, str]]:
    """Return broker writes whose binding does not prove a gated dispatcher."""
    parents = _parent_nodes(tree)
    lexical_sources_cache: dict[int, dict[str, list[ast.AST]]] = {}
    offenders: list[tuple[ast.Call, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        assignments = _lexical_assignment_sources(node, tree, parents, lexical_sources_cache)
        function = _containing_callable(node, parents)
        for receiver, method in _write_call_targets(node, assignments):
            if _is_broker_free_execution_context(relative, receiver, assignments):
                continue
            if _is_proven_gated_write(relative, function, receiver, method, assignments, parents):
                continue
            offenders.append((node, method))
            break
    return offenders


def _raw_broker_write_offenders(tree: ast.Module, relative: str) -> list[ast.Call]:
    return [node for node, _method in _raw_broker_write_details(tree, relative)]


def test_binding_aware_raw_write_guard_rejects_alias_and_indirect_calls() -> None:
    malicious = ast.parse(
        "async def alias_receiver(raw_client, order):\n"
        "    router = raw_client\n"
        "    await router.place_order(order)\n"
        "async def bound_method(client, order):\n"
        "    send = client.place_order\n"
        "    await send(order)\n"
        "async def cancel(adapter, order_id):\n"
        "    await adapter.cancel_order(order_id)\n"
        "async def modify(adapter, order_id):\n"
        "    await adapter.modify_order(order_id)\n"
        "async def parenthesised(client, order):\n"
        "    result = (client.place_order)(order)\n"
        "    return result\n"
    )
    offenders = _raw_broker_write_offenders(malicious, "fixture.py")
    assert {node.lineno for node in offenders} == {3, 6, 8, 10, 12}

    canonical = ast.parse(
        "from flinttrade_gateway.router import BrokerRouter\n"
        "async def dispatch(router: BrokerRouter, ctx, order, safety_ctx):\n"
        "    return await router.place_order(\n"
        "        ctx, order=order, safety_ctx=safety_ctx\n"
        "    )\n"
        "def route():\n"
        "    return _dispatch_gated(\n"
        "        dispatch=lambda router, ctx, sctx: router.cancel_order(\n"
        "            ctx, order={}, order_id='1', safety_ctx=sctx\n"
        "        )\n"
        "    )\n"
    )
    assert _raw_broker_write_offenders(canonical, "fixture.py") == []


def test_binding_aware_raw_write_guard_rejects_containers_methodcaller_and_partial() -> None:
    malicious_sources = (
        "async def send(client, order):\n"
        "    writers = {'place': client.place_order}\n"
        "    return await writers['place'](order)\n",
        "async def send(client, order):\n    writers = [client.cancel_order]\n    return await writers[0](order)\n",
        "import operator\n"
        "async def send(adapter, order):\n"
        "    return await operator.methodcaller('modify_order', order)(adapter)\n",
        "import functools as ft\n"
        "async def send(client, order):\n"
        "    writer = ft.partial(client.place_order, order)\n"
        "    return await writer()\n",
        "from functools import partial as bind\n"
        "async def send(client, order):\n"
        "    writers = {'cancel': bind(client.cancel_order, order)}\n"
        "    return await writers['cancel']()\n",
    )
    for source in malicious_sources:
        assert _raw_broker_write_offenders(ast.parse(source), "fixture.py"), source


def test_binding_aware_raw_write_guard_rejects_assigned_mapping_get_callables() -> None:
    source = (
        "async def send(client, order):\n"
        "    writers = {'send': client.place_order}\n"
        "    lookup = writers.get\n"
        "    writer = lookup('send')\n"
        "    return await writer(order)\n"
    )
    assert _raw_broker_write_offenders(ast.parse(source), "fixture.py")


def test_safety_context_mint_guard_rejects_direct_and_indirect_producers() -> None:
    malicious = ast.parse(
        "def direct(order, kwargs):\n"
        "    return SafetyContext.mint(order, **kwargs)\n"
        "def class_alias(order, kwargs):\n"
        "    context_type = SafetyContext\n"
        "    return context_type.mint(order, **kwargs)\n"
        "def callable_alias(order, kwargs):\n"
        "    produce = SafetyContext.mint\n"
        "    return produce(order, **kwargs)\n"
        "def reflective(order, kwargs):\n"
        "    return getattr(SafetyContext, 'mint')(order, **kwargs)\n"
    )
    offenders = _safety_context_mint_offenders(malicious, "fixture.py")
    assert {node.lineno for node in offenders} == {2, 5, 8, 10}

    canonical = ast.parse("def gate_order(order, kwargs):\n    return SafetyContext.mint(order, **kwargs)\n")
    assert (
        _safety_context_mint_offenders(
            canonical,
            "packages/services/engine/src/flinttrade_engine/safety.py",
        )
        == []
    )


def test_safety_context_mint_guard_rejects_containers_and_methodcaller() -> None:
    malicious_sources = (
        "def mint(order, kwargs):\n"
        "    producers = {'mint': SafetyContext.mint}\n"
        "    return producers['mint'](order, **kwargs)\n",
        "def mint(order, kwargs):\n    producers = [SafetyContext.mint]\n    return producers[0](order, **kwargs)\n",
        "def mint(order, kwargs):\n    return ({'mint': SafetyContext.mint}['mint'])(order, **kwargs)\n",
        "import operator\n"
        "def mint(order, kwargs):\n"
        "    return operator.methodcaller('mint', order, **kwargs)(SafetyContext)\n",
    )
    for source in malicious_sources:
        assert _safety_context_mint_offenders(ast.parse(source), "fixture.py"), source


_ORDER_SURFACE_ROOTS = (
    _REPO_ROOT / "packages" / "services",
    _REPO_ROOT / "packages" / "integrations" / "webhooks",
    _REPO_ROOT / "packages" / "core",
)
_PRODUCTION_PYTHON_ROOTS = tuple(
    _REPO_ROOT / name for name in ("packages", "scripts", "infra", "packaging", "supply-chain", "templates")
)
_EXTENDED_WRITE_METHODS = frozenset(_WRITE_METHODS) - {
    "place_order",
    "placeorder",
    "placesmartorder",
    "modify_order",
    "cancel_order",
    "close_position",
    "closeposition",
    "place_options_order",
}


def _python_sources(roots: tuple[Path, ...]) -> list[Path]:
    paths: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            relative_parts = path.relative_to(_REPO_ROOT).parts
            if "tests" in relative_parts or path.name.startswith("test_"):
                continue
            paths.append(path)
    return sorted(set(paths))


def _parse_source(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _format_ast_offender(relative: str, node: ast.AST, *, detail: str = "") -> str:
    suffix = f" [{detail}]" if detail else ""
    return f"{relative}:{node.lineno}: {ast.unparse(node)}{suffix}"


# There are no raw extended-verb exemptions. Emergency flattening is an
# explicit exposure-reducing policy, but it still mints a one-shot context and
# dispatches through BrokerRouter to a token-guarded adapter.
_RAW_EXTENDED_VERB_ALLOWLIST: set[str] = set()


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
    assert not offenders, "Legacy order-write methods reintroduced (S7):\n" + "\n".join(offenders)


def _router_token_dominance_offenders(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[ast.Call]:
    """Return executable SDK mutations reachable before the router-token guard."""
    assignments = _function_resolution_assignments(function)

    def static_truth(value: ast.AST) -> bool | None:
        if isinstance(value, ast.Constant) and isinstance(value.value, bool):
            return value.value
        if isinstance(value, ast.UnaryOp) and isinstance(value.op, ast.Not):
            truth = static_truth(value.operand)
            return None if truth is None else not truth
        return None

    def expression_calls(value: ast.AST | None) -> list[ast.Call]:
        if value is None:
            return []
        calls: list[ast.Call] = []

        def visit(node: ast.AST) -> None:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                return
            for child in ast.iter_child_nodes(node):
                visit(child)
            if isinstance(node, ast.Call):
                calls.append(node)

        visit(value)
        return calls

    def mutation_name(name: str) -> bool:
        lowered = name.lower()
        return lowered in {"post", "put", "patch", "delete"} or lowered.startswith(
            (
                "place_",
                "placeorder",
                "modify_",
                "cancel_",
                "close_",
                "exit_",
                "convert_",
                "square_",
            )
        )

    def is_sdk_mutation(call: ast.Call) -> bool:
        if _write_call_targets(call, assignments):
            return True
        for function_value in _resolved_callable_values(call.func, assignments):
            if not isinstance(function_value, ast.Attribute):
                continue
            method = function_value.attr
            if method in {"_request", "_emergency_request"}:
                if any(
                    isinstance(argument, ast.Constant)
                    and isinstance(argument.value, str)
                    and argument.value.upper() in {"POST", "PUT", "PATCH", "DELETE"}
                    for argument in call.args[:3]
                ):
                    return True
                continue
            if method == "_call" and call.args:
                if any(
                    isinstance(target, ast.Attribute) and mutation_name(target.attr)
                    for target in _resolved_callable_values(call.args[0], assignments)
                ):
                    return True
                continue
            if mutation_name(method):
                return True
        return False

    def is_token_guard(statement: ast.stmt) -> bool:
        if not isinstance(statement, ast.Expr):
            return False
        value = statement.value.value if isinstance(statement.value, ast.Await) else statement.value
        return (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Attribute)
            and isinstance(value.func.value, ast.Name)
            and value.func.value.id == "self"
            and value.func.attr == "_require_router_token"
            and len(value.args) >= 2
            and isinstance(value.args[0], ast.Name)
            and value.args[0].id == "_router_token"
            and isinstance(value.args[1], ast.Name)
            and value.args[1].id == "_ROUTER_TOKEN"
        )

    offenders: list[ast.Call] = []

    def inspect_expression(value: ast.AST | None, states: set[bool]) -> None:
        if False not in states:
            return
        offenders.extend(call for call in expression_calls(value) if is_sdk_mutation(call))

    def process_block(statements: list[ast.stmt], states: set[bool]) -> set[bool]:
        current = set(states)
        for statement in statements:
            if not current:
                break
            current = process_statement(statement, current)
        return current

    def process_statement(statement: ast.stmt, states: set[bool]) -> set[bool]:
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
            handler_states: set[bool] = set()
            for handler in statement.handlers:
                inspect_expression(handler.type, states)
                handler_states.update(process_block(handler.body, set(states)))
            combined = normal_states | handler_states
            if statement.finalbody:
                # ``finally`` also runs when any try statement raises, including
                # the token validator itself before it can establish success.
                # Inspect that exceptional entry, but do not let it continue
                # beyond the try: an unhandled exception propagates after the
                # finalbody. Only normal/caught paths can reach later writes.
                process_block(statement.finalbody, combined | set(states))
                return process_block(statement.finalbody, combined)
            return combined

        if isinstance(statement, ast.Match):
            inspect_expression(statement.subject, states)
            outcomes: set[bool] = set(states)
            for case in statement.cases:
                inspect_expression(case.guard, states)
                outcomes.update(process_block(case.body, set(states)))
            return outcomes

        for child in ast.iter_child_nodes(statement):
            if not isinstance(child, ast.stmt):
                inspect_expression(child, states)
        if is_token_guard(statement):
            return {True} if states else set()
        if isinstance(statement, (ast.Return, ast.Raise, ast.Break, ast.Continue)):
            return set()
        return set(states)

    process_block(function.body, {False})
    return list(dict.fromkeys(offenders))


def test_router_token_guard_must_dominate_every_executable_sdk_mutation() -> None:
    malicious_sources = (
        "async def place_order(self, session, order, _router_token=None):\n"
        "    await self._client(session).place_order(order)\n"
        "    self._require_router_token(_router_token, _ROUTER_TOKEN)\n",
        "async def place_order(self, session, order, _router_token=None):\n"
        "    if False:\n"
        "        self._require_router_token(_router_token, _ROUTER_TOKEN)\n"
        "    await self._client(session).place_order(order)\n",
        "async def place_order(self, session, order, enabled, _router_token=None):\n"
        "    if enabled:\n"
        "        self._require_router_token(_router_token, _ROUTER_TOKEN)\n"
        "    await self._client(session).place_order(order)\n",
    )
    for source in malicious_sources:
        function = ast.parse(source).body[0]
        assert isinstance(function, ast.AsyncFunctionDef)
        assert _router_token_dominance_offenders(function), source

    safe_source = (
        "async def place_order(self, session, order, enabled, _router_token=None):\n"
        "    self._require_router_token(_router_token, _ROUTER_TOKEN)\n"
        "    if enabled:\n"
        "        await self._client(session).place_order(order)\n"
        "    if False:\n"
        "        await self._client(session).cancel_order(order)\n"
    )
    safe_function = ast.parse(safe_source).body[0]
    assert isinstance(safe_function, ast.AsyncFunctionDef)
    assert _router_token_dominance_offenders(safe_function) == []


def test_router_token_guard_tracks_bound_writer_aliases_and_guard_failure_finally_paths() -> None:
    malicious_sources = (
        "async def place_order(self, session, order, _router_token=None):\n"
        "    writer = self._client(session).place_order\n"
        "    await writer(order)\n"
        "    self._require_router_token(_router_token, _ROUTER_TOKEN)\n",
        "async def place_order(self, session, order, _router_token=None):\n"
        "    try:\n"
        "        self._require_router_token(_router_token, _ROUTER_TOKEN)\n"
        "    finally:\n"
        "        await self._client(session).place_order(order)\n",
        "async def place_order(self, session, order, _router_token=None):\n"
        "    writer = self._client(session).place_order\n"
        "    try:\n"
        "        self._require_router_token(_router_token, _ROUTER_TOKEN)\n"
        "    finally:\n"
        "        await writer(order)\n",
    )
    for source in malicious_sources:
        function = ast.parse(source).body[0]
        assert isinstance(function, ast.AsyncFunctionDef)
        assert _router_token_dominance_offenders(function), source

    safe_after_finally = (
        "async def place_order(self, session, order, _router_token=None):\n"
        "    writer = self._client(session).place_order\n"
        "    try:\n"
        "        self._require_router_token(_router_token, _ROUTER_TOKEN)\n"
        "    finally:\n"
        "        self._record_attempt()\n"
        "    await writer(order)\n"
    )
    safe_function = ast.parse(safe_after_finally).body[0]
    assert isinstance(safe_function, ast.AsyncFunctionDef)
    assert _router_token_dominance_offenders(safe_function) == []


def test_fake_broker_router_annotations_do_not_authorise_raw_writes() -> None:
    malicious_sources = (
        "from attacker import BrokerRouter\n"
        "async def dispatch(router: BrokerRouter, ctx, order, safety_ctx):\n"
        "    return await router.place_order(ctx, order=order, safety_ctx=safety_ctx)\n",
        "class BrokerRouter:\n"
        "    pass\n"
        "async def dispatch(router: BrokerRouter, ctx, order, safety_ctx):\n"
        "    return await router.place_order(ctx, order=order, safety_ctx=safety_ctx)\n",
        "async def dispatch(router: BrokerRouter, ctx, order, safety_ctx, BrokerRouter=FakeRouter):\n"
        "    return await router.place_order(ctx, order=order, safety_ctx=safety_ctx)\n",
    )
    for source in malicious_sources:
        assert _raw_broker_write_offenders(ast.parse(source), "fixture.py"), source


def test_openalgo_writes_all_require_router_token():
    """Every executable OpenAlgo SDK mutation is dominated by the token guard."""
    src = (_GATEWAY_SRC / "brokers" / "openalgo.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    adapter = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "OpenAlgoAdapter")
    write_methods = ("place_order", "modify_order", "cancel_order")
    methods = {node.name: node for node in adapter.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    missing = [method for method in write_methods if method not in methods]
    assert not missing, f"OpenAlgoAdapter is missing write methods: {missing}"
    ungated = [
        f"OpenAlgoAdapter.{name}:{call.lineno}"
        for name, method in methods.items()
        if "_router_token"
        in {argument.arg for argument in (*method.args.posonlyargs, *method.args.args, *method.args.kwonlyargs)}
        for call in _router_token_dominance_offenders(method)
    ]
    assert not ungated, f"OpenAlgo SDK mutations must be dominated by _require_router_token (§8); unguarded: {ungated}"


# Per-adapter expected gated write surface (the trio + every extended verb the
# adapter implements). Dropping any of these methods — or its router-token
# guard — must fail HERE, not only in a per-adapter unit test that could be
# removed alongside the method.
_NATIVE_ADAPTER_WRITE_METHODS: dict[str, tuple[str, tuple[str, ...]]] = {
    "dhan.py": (
        "DhanAdapter",
        (
            "place_order",
            "modify_order",
            "cancel_order",
            "modify_forever",
            "cancel_forever",
            "modify_super_order",
            "cancel_super_order",
            "place_conditional_trigger",
            "modify_conditional_trigger",
            "cancel_conditional_trigger",
            "convert_position",
            "exit_all_positions",
        ),
    ),
    "upstox.py": (
        "UpstoxAdapter",
        (
            "place_order",
            "modify_order",
            "cancel_order",
            "place_multi_order",
            "cancel_all_orders",
            "exit_all_positions",
            "convert_position",
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
    "groww.py": (
        "GrowwAdapter",
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
      * EVERY executable SDK mutation in a token-bearing method is dominated by
        the exact ``_require_router_token`` call on every branch.
    """
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
        methods = {node.name: node for node in cls.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        missing += [f"{clsname}.{m}" for m in write_methods if m not in methods]
        for name, node in methods.items():
            arg_names = {argument.arg for argument in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)}
            takes_token = "_router_token" in arg_names
            if name in write_methods or takes_token:
                ungated.extend(f"{clsname}.{name}:{call.lineno}" for call in _router_token_dominance_offenders(node))
    assert not missing, f"native adapters missing gated write methods: {missing}"
    assert not ungated, (
        f"native adapter write methods must call _require_router_token (§8); unguarded: {sorted(set(ungated))}"
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
        m for _cls, methods in _NATIVE_ADAPTER_WRITE_METHODS.values() for m in methods if m not in trio
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
    AND ``packages/core``. This binding-aware AST scan follows local aliases and
    bound write callables; receiver spelling is not proof of a BrokerRouter.
    The isolated sandbox engine and explicitly proven gated dispatch contexts
    remain legitimate, while the shrinking dormant-debt allowlist stays
    explicit.
    """
    offenders: list[str] = []
    for path in _python_sources(_ORDER_SURFACE_ROOTS):
        rel = path.relative_to(_REPO_ROOT).as_posix()
        if rel in _RAW_ORDER_ALLOWLIST:
            continue
        for node, method in _raw_broker_write_details(_parse_source(path), rel):
            offenders.append(_format_ast_offender(rel, node, detail=method))
    assert not offenders, (
        "Ungated broker order-write outside the gate_order -> BrokerRouter chain "
        "(contract §8.1). Route it through gate_order/BrokerRouter. Only proven-"
        "dormant debt may enter _RAW_ORDER_ALLOWLIST; emergency writes receive no "
        "exemption:\n" + "\n".join(offenders)
    )


def test_no_raw_extended_verb_calls_in_services_and_webhooks():
    """§8.1 tripwire for the EXTENDED gated verbs (forever/super/trigger/convert/
    exit-all/multi/cancel-all/smart-cancel).

    These adapter write methods are reachable ONLY through
    ``gate_broker_write -> BrokerRouter.execute_gated``. The same binding-aware
    scan used for ordinary order writes prevents aliases from hiding one.
    """
    offenders: list[str] = []
    for path in _python_sources(_ORDER_SURFACE_ROOTS):
        rel = path.relative_to(_REPO_ROOT).as_posix()
        if rel in _RAW_EXTENDED_VERB_ALLOWLIST:
            continue
        for node, method in _raw_broker_write_details(_parse_source(path), rel):
            if method in _EXTENDED_WRITE_METHODS:
                offenders.append(_format_ast_offender(rel, node, detail=method))
    assert not offenders, (
        "Raw extended-verb broker write outside the gate_broker_write -> "
        "BrokerRouter.execute_gated chain (contract §8.1). Route it through the "
        "router; emergency writes receive no exemption:\n" + "\n".join(offenders)
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
            method in _EXTENDED_WRITE_METHODS for _node, method in _raw_broker_write_details(_parse_source(path), rel)
        )
        if not has_raw:
            stale.append(f"{rel} (no raw extended-verb call left — remove from allowlist)")
    assert not stale, "Stale _RAW_EXTENDED_VERB_ALLOWLIST entries (the allowlist must shrink):\n" + "\n".join(stale)


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
            method
            in {
                "place_order",
                "placeorder",
                "placesmartorder",
                "close_position",
                "closeposition",
                "place_options_order",
            }
            for _node, method in _raw_broker_write_details(_parse_source(path), rel)
        )
        if not has_raw:
            stale.append(f"{rel} (no raw order-write left — remove from allowlist)")
    assert not stale, "Stale _RAW_ORDER_ALLOWLIST entries (the allowlist must shrink):\n" + "\n".join(stale)


def test_emergency_modules_have_no_raw_client_write_escape_hatch():
    """P0 pin: API/Safety/Telegram emergency code has no raw-client mutation."""
    modules = (
        "packages/services/engine/src/flinttrade_engine/safety.py",
        "packages/core/core/src/flinttrade_core/operations_routes.py",
        "packages/services/automation/src/flinttrade_automation/telegram_bot.py",
    )
    forbidden = re.compile(r"\b(?:self\.)?[_\w]*client\.(?:cancel_all_orders|close_position|exit_all_positions)\s*\(")
    offenders: list[str] = []
    for rel in modules:
        path = _REPO_ROOT / rel
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if forbidden.search(line) and not line.strip().startswith("#"):
                offenders.append(f"{rel}:{n}: {line.strip()}")

    assert not offenders, (
        "Emergency broker mutations must use gate_broker_write -> BrokerRouter; "
        "raw OpenAlgoClient writes are forbidden:\n" + "\n".join(offenders)
    )

    safety_src = (_REPO_ROOT / modules[0]).read_text(encoding="utf-8")
    assert "GatedEmergencyBrokerDispatcher" in safety_src
    assert "gate_broker_write(" in safety_src
    assert re.search(r"router\.execute_gated\s*\(", safety_src)


def test_no_new_raw_route_order_dispatchers():
    """G12 tripwire: no new calls into the legacy ``OrderRouter.route_order`` API.

    The canonical broker-write path is ``gate_order -> BrokerRouter``. Several
    older engine/AI modules still call their own ``route_order`` API and are
    tracked as explicit consolidation debt. A new call site must fail here
    instead of passing because ``route_order`` was absent from the older grep
    guard.
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
            if rel in _RAW_ROUTE_ORDER_ALLOWLIST:
                continue
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("#") or "def " in stripped:
                    continue
                if _ROUTE_ORDER_RE.search(line):
                    offenders.append(f"{rel}:{n}: {stripped}")
    assert not offenders, (
        "Raw route_order dispatcher outside the canonical gate_order -> BrokerRouter path "
        "(contract §8.1 / G12). Route it through BrokerRouter, or add a shrinking "
        "debt entry with justification:\n" + "\n".join(offenders)
    )


def test_raw_route_order_allowlist_has_no_stale_entries():
    """Every allowed legacy ``route_order`` module must still contain that debt."""
    stale: list[str] = []
    for rel in sorted(_RAW_ROUTE_ORDER_ALLOWLIST):
        path = _REPO_ROOT / rel
        if not path.exists():
            stale.append(f"{rel} (file gone)")
            continue
        has_raw = any(
            _ROUTE_ORDER_RE.search(line) and "def " not in line and not line.strip().startswith("#")
            for line in path.read_text(encoding="utf-8").splitlines()
        )
        if not has_raw:
            stale.append(f"{rel} (no raw route_order call left — remove from allowlist)")
    assert not stale, "Stale _RAW_ROUTE_ORDER_ALLOWLIST entries (the allowlist must shrink):\n" + "\n".join(stale)


def test_no_new_raw_openalgo_modify_cancel_calls():
    """G12 tripwire: raw OpenAlgoClient modify/cancel calls are not hidden by place-order scans."""
    offenders: list[str] = []
    for path in _python_sources(_ORDER_SURFACE_ROOTS):
        rel = path.relative_to(_REPO_ROOT).as_posix()
        if rel in _RAW_OPENALGO_MOD_CANCEL_ALLOWLIST:
            continue
        for node, method in _raw_broker_write_details(_parse_source(path), rel):
            if method in {"modify_order", "cancel_order"}:
                offenders.append(_format_ast_offender(rel, node, detail=method))
    assert not offenders, (
        "Raw OpenAlgoClient modify/cancel call outside the gated BrokerRouter path "
        "(contract §8.1 / G12):\n" + "\n".join(offenders)
    )


# The bracket service was re-architected off the raw-client debt allowlists on
# 2026-07-07: every leg write now traverses SafetySystem -> gate_order ->
# BrokerRouter via dispatchers injected by the core app. This pin keeps the
# asymmetry exact — a future raw ``client.place_order(...)`` / ``client.
# cancel_order(...)`` in bracket_order.py fails HERE even if someone also
# re-adds the module to a generic allowlist above.
_BRACKET_MODULE = "packages/services/engine/src/flinttrade_engine/bracket_order.py"


def test_bracket_order_writes_only_through_gated_router():
    """§8.1 pin: EVERY broker-write call in bracket_order.py is router-gated.

    Three assertions:
      * every ``.place_order(`` / ``.cancel_order(`` / ``.modify_order(`` (and
        the OpenAlgo spellings) attribute call sits on the canonical gated
        BrokerRouter receiver — a raw client write fails here;
      * the module still mints through ``gate_order`` (the sole SafetyContext
        producer), so the dispatchers cannot silently drop the gate; and
      * the service holds NO raw client handle (``self._client`` is gone for
        good — writes flow only through the injected dispatchers).
    """
    path = _REPO_ROOT / _BRACKET_MODULE
    src = path.read_text(encoding="utf-8")

    tree = ast.parse(src, filename=str(path))
    offenders = [
        _format_ast_offender(_BRACKET_MODULE, node, detail=method)
        for node, method in _raw_broker_write_details(tree, _BRACKET_MODULE)
    ]
    assert not offenders, (
        "Ungated broker write in the bracket service (contract §8.1) — every leg "
        "must traverse gate_order -> BrokerRouter via the injected dispatchers:\n" + "\n".join(offenders)
    )

    assert "gate_order(" in src, (
        "bracket_order.py no longer mints through gate_order — the leg "
        "dispatchers must keep using the sole SafetyContext producer (§8.1)"
    )
    assert re.search(r"self\._client\b", src) is None, (
        "bracket_order.py re-grew a raw client handle (self._client) — the "
        "service must hold only the injected gated dispatchers (§8.1)"
    )


def test_bracket_module_is_not_on_any_raw_debt_allowlist():
    """The bracket service must never quietly rejoin a raw-write debt allowlist."""
    for allowlist_name, allowlist in (
        ("_RAW_ORDER_ALLOWLIST", _RAW_ORDER_ALLOWLIST),
        ("_RAW_ROUTE_ORDER_ALLOWLIST", _RAW_ROUTE_ORDER_ALLOWLIST),
        ("_RAW_OPENALGO_MOD_CANCEL_ALLOWLIST", _RAW_OPENALGO_MOD_CANCEL_ALLOWLIST),
        ("_RAW_EXTENDED_VERB_ALLOWLIST", _RAW_EXTENDED_VERB_ALLOWLIST),
    ):
        assert _BRACKET_MODULE not in allowlist, (
            f"bracket_order.py was re-added to {allowlist_name} — its writes were "
            "gated on 2026-07-07 and must stay that way (contract §8.1)"
        )


def test_ditto_mirror_admits_complete_target_state_before_gate_and_router():
    """Ditto must run target-account SafetySystem admission before every mint."""
    mirror_path = _REPO_ROOT / "packages/services/ditto/src/flinttrade_ditto/mirror.py"
    runtime_path = _REPO_ROOT / "packages/services/ditto/src/flinttrade_ditto/runtime.py"
    mirror_tree = ast.parse(mirror_path.read_text(encoding="utf-8"), filename=str(mirror_path))
    runtime_tree = ast.parse(runtime_path.read_text(encoding="utf-8"), filename=str(runtime_path))

    mirror_class = next(
        node for node in mirror_tree.body if isinstance(node, ast.ClassDef) and node.name == "PositionMirror"
    )
    dispatch = next(
        node for node in mirror_class.body if isinstance(node, ast.FunctionDef) and node.name == "_place_via_router"
    )
    call_lines: dict[str, list[int]] = {"admit": [], "gate": [], "router": []}
    for node in ast.walk(dispatch):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Attribute) and node.func.attr == "_admit_order":
            call_lines["admit"].append(node.lineno)
        elif isinstance(node.func, ast.Name) and node.func.id == "gate_order":
            call_lines["gate"].append(node.lineno)
        elif isinstance(node.func, ast.Attribute) and node.func.attr == "place_order":
            call_lines["router"].append(node.lineno)
    assert all(len(lines) == 1 for lines in call_lines.values()), (
        f"Ditto must have exactly one admission, gate mint, and router dispatch per target: {call_lines}"
    )
    assert call_lines["admit"][0] < call_lines["gate"][0] < call_lines["router"][0], (
        "Ditto order sequence regressed: target admission must precede gate_order, "
        f"which must precede BrokerRouter.place_order ({call_lines})"
    )

    owner_class = next(
        node for node in runtime_tree.body if isinstance(node, ast.ClassDef) and node.name == "DittoRouterOwner"
    )
    admission = next(
        node for node in owner_class.body if isinstance(node, ast.FunctionDef) and node.name == "admit_order"
    )
    admission_calls = {
        node.func.id
        if isinstance(node.func, ast.Name)
        else node.func.attr
        if isinstance(node.func, ast.Attribute)
        else ""
        for node in ast.walk(admission)
        if isinstance(node, ast.Call)
    }
    assert {"gather_safety_state", "check_order"} <= admission_calls

    runtime_class = next(
        node for node in runtime_tree.body if isinstance(node, ast.ClassDef) and node.name == "DittoRuntime"
    )
    start = next(node for node in runtime_class.body if isinstance(node, ast.FunctionDef) and node.name == "start")
    mirror_build = next(
        node
        for node in ast.walk(start)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "PositionMirror"
    )
    keywords = {keyword.arg: keyword.value for keyword in mirror_build.keywords}
    injected = keywords.get("admit_order")
    assert (
        isinstance(injected, ast.Attribute)
        and isinstance(injected.value, ast.Name)
        and injected.value.id == "owner"
        and injected.attr == "admit_order"
    ), "DittoRuntime must inject DittoRouterOwner.admit_order into PositionMirror"


def test_chartink_requires_admission_before_gate_and_router() -> None:
    """ChartInk's optional placement helper cannot mint from parser output alone."""
    path = _REPO_ROOT / "packages/integrations/webhooks/src/flinttrade_webhooks/chartink.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    handler = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "ChartInkWebhook")
    dispatch = next(
        node for node in handler.body if isinstance(node, ast.FunctionDef) and node.name == "_place_via_router"
    )
    call_lines: dict[str, list[int]] = {"admit": [], "gate": [], "router": []}
    for node in ast.walk(dispatch):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Attribute) and node.func.attr == "_admit_order":
            call_lines["admit"].append(node.lineno)
        elif isinstance(node.func, ast.Name) and node.func.id == "gate_order":
            call_lines["gate"].append(node.lineno)
        elif isinstance(node.func, ast.Attribute) and node.func.attr == "place_order":
            call_lines["router"].append(node.lineno)

    assert all(len(lines) == 1 for lines in call_lines.values()), (
        f"ChartInk must have exactly one admission, gate mint, and router dispatch per order: {call_lines}"
    )
    assert call_lines["admit"][0] < call_lines["gate"][0] < call_lines["router"][0], (
        "ChartInk order sequence regressed: complete admission must precede gate_order, "
        f"which must precede BrokerRouter.place_order ({call_lines})"
    )


def test_raw_openalgo_modify_cancel_allowlist_has_no_stale_entries():
    """Every raw OpenAlgo modify/cancel debt entry must stay justified by code."""
    stale: list[str] = []
    for rel in sorted(_RAW_OPENALGO_MOD_CANCEL_ALLOWLIST):
        path = _REPO_ROOT / rel
        if not path.exists():
            stale.append(f"{rel} (file gone)")
            continue
        has_raw = any(
            method in {"modify_order", "cancel_order"}
            for _node, method in _raw_broker_write_details(_parse_source(path), rel)
        )
        if not has_raw:
            stale.append(f"{rel} (no raw OpenAlgo modify/cancel call left — remove from allowlist)")
    assert not stale, "Stale _RAW_OPENALGO_MOD_CANCEL_ALLOWLIST entries (the allowlist must shrink):\n" + "\n".join(
        stale
    )


def test_only_gate_order_mints_safety_context():
    """Only the canonical gate_order implementation may mint SafetyContext."""
    offenders: list[str] = []
    canonical_calls: list[str] = []
    canonical_path = "packages/services/engine/src/flinttrade_engine/safety.py"
    for path in _python_sources(_PRODUCTION_PYTHON_ROOTS):
        relative = path.relative_to(_REPO_ROOT).as_posix()
        tree = _parse_source(path)
        references = _safety_context_mint_references(tree)
        offender_ids = {id(node) for node in _safety_context_mint_offenders(tree, relative)}
        for node in references:
            rendered = _format_ast_offender(relative, node)
            if id(node) in offender_ids:
                offenders.append(rendered)
            else:
                canonical_calls.append(rendered)
    assert not offenders, "Only flinttrade_engine.safety.gate_order() may mint a SafetyContext (§8.1):\n" + "\n".join(
        offenders
    )
    assert len(canonical_calls) == 1 and canonical_calls[0].startswith(f"{canonical_path}:"), (
        "Expected exactly one canonical SafetyContext.mint call inside "
        f"flinttrade_engine.safety.gate_order; found {canonical_calls}"
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


def _forward_to_openalgo_references(tree: ast.Module) -> list[ast.AST]:
    protected = "_forward_to_openalgo"
    parents = _parent_nodes(tree)
    lexical_sources_cache: dict[int, dict[str, list[ast.AST]]] = {}
    offenders: list[ast.AST] = []
    for node in ast.walk(tree):
        assignments = _lexical_assignment_sources(node, tree, parents, lexical_sources_cache)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id == protected:
            offenders.append(node)
            continue
        if isinstance(node, ast.Attribute) and node.attr == protected:
            offenders.append(node)
            continue
        if isinstance(node, ast.ImportFrom):
            if any(alias.name == protected for alias in node.names) or (
                any(alias.name == "*" for alias in node.names)
                and node.module is not None
                and node.module.endswith("order_routes")
            ):
                offenders.append(node)
            continue
        if isinstance(node, ast.Subscript):
            name = _constant_string(node.slice, assignments)
            if name == protected:
                offenders.append(node)
            elif (
                name is None
                and isinstance(parents.get(id(node)), ast.Call)
                and parents[id(node)].func is node
                and _is_module_namespace_for_node(node.value, assignments, node, parents)
            ):
                offenders.append(node)
            continue
        if not isinstance(node, ast.Call):
            continue
        recognised, owner, name = _dynamic_attribute_access(node, assignments)
        if recognised and owner is not None:
            if name == protected or (
                name is None
                and (_call_result_is_invoked(node, parents) or _dynamic_access_executes_method(node, assignments))
                and (
                    _is_module_namespace_for_node(owner, assignments, node, parents)
                    or _is_module_object_expression(owner, assignments)
                )
            ):
                offenders.append(node)
                continue
        for mapping_owner, mapping_name in _mapping_lookup_accesses(node, assignments):
            if mapping_name == protected or (
                mapping_name is None
                and _call_result_is_invoked(node, parents)
                and _is_module_namespace_for_node(mapping_owner, assignments, node, parents)
            ):
                offenders.append(node)
                break
    return list({id(node): node for node in offenders}.values())


def _raw_order_write_url_references(tree: ast.Module) -> list[ast.AST]:
    parents = _parent_nodes(tree)
    lexical_sources_cache: dict[int, dict[str, list[ast.AST]]] = {}
    offenders: list[ast.AST] = []

    def string_parts(
        value: ast.AST,
        assignments: dict[str, list[ast.AST]],
        resolving: frozenset[str] = frozenset(),
    ) -> list[str | None]:
        static = _constant_string(value, assignments, resolving)
        if static is not None:
            return [static]
        if isinstance(value, ast.Name) and value.id not in resolving:
            sources = assignments.get(value.id, [])
            if len(sources) == 1:
                return string_parts(sources[0], assignments, resolving | {value.id})
        if isinstance(value, ast.BinOp) and isinstance(value.op, ast.Add):
            return [
                *string_parts(value.left, assignments, resolving),
                *string_parts(value.right, assignments, resolving),
            ]
        if isinstance(value, ast.JoinedStr):
            parts: list[str | None] = []
            for item in value.values:
                expression = item.value if isinstance(item, ast.FormattedValue) else item
                parts.extend(string_parts(expression, assignments, resolving))
            return parts
        return [None]

    def fragments(value: ast.AST, assignments: dict[str, list[ast.AST]]) -> list[str]:
        combined: list[str] = []
        current = ""
        for part in string_parts(value, assignments):
            if part is None:
                if current:
                    combined.append(current)
                    current = ""
                continue
            current += part
        if current:
            combined.append(current)
        return combined

    for node in ast.walk(tree):
        if not isinstance(node, ast.expr):
            continue
        assignments = _lexical_assignment_sources(node, tree, parents, lexical_sources_cache)
        if any(_ORDER_WRITE_URL_RE.search(fragment) for fragment in fragments(node, assignments)):
            offenders.append(node)
    return list({id(node): node for node in offenders}.values())


def test_forward_to_openalgo_caller_guard_rejects_direct_aliased_and_dynamic_reactivation() -> None:
    malicious_sources = (
        "def reactivate(body):\n    return _forward_to_openalgo('placeorder', body)\n",
        "def reactivate(body, forward=_forward_to_openalgo):\n    return forward('cancelorder', body)\n",
        "def reactivate(body):\n"
        "    helpers = {'forward': _forward_to_openalgo}\n"
        "    return helpers['forward']('modifyorder', body)\n",
        "import sys\n"
        "def reactivate(body):\n"
        "    return getattr(sys.modules[__name__], '_forward_to_' + 'openalgo')('placeorder', body)\n",
        "def reactivate(body):\n    return globals()['_forwardXto_openalgo'.replace('X', '_')]('placeorder', body)\n",
        "import operator\n"
        "def reactivate(body):\n"
        "    return operator.attrgetter('_forward_to_openalgo')(module)('placeorder', body)\n",
    )
    for source in malicious_sources:
        assert _forward_to_openalgo_references(ast.parse(source)), source

    benign = ast.parse("def read(mapping, name):\n    return mapping[name]\n")
    assert _forward_to_openalgo_references(benign) == []


def test_raw_order_url_guard_rejects_computed_urls_and_retired_helper_calls() -> None:
    computed_url = ast.parse(
        "def send(client, host, body):\n"
        "    url = host + '/api/v1/' + 'place'.replace('x', 'x') + 'order'\n"
        "    return client.post(url, json=body)\n"
    )
    helper_call = ast.parse("def send(body):\n    return _forward_to_openalgo('cancelorder', body)\n")
    assert _raw_order_write_url_references(computed_url)
    assert _forward_to_openalgo_references(helper_call)


def test_static_get_and_join_indirection_cannot_reactivate_retired_writes() -> None:
    globals_get = ast.parse(
        "def send(body):\n"
        "    separator = ''\n"
        "    name_parts = ('_forward', '_to_', 'openalgo')\n"
        "    lookup = globals().get\n"
        "    helper = lookup(separator.join(name_parts))\n"
        "    return helper('placeorder', body)\n"
    )
    mapping_get = ast.parse(
        "async def send(client, order):\n"
        "    writers = {'place': client.place_order}\n"
        "    lookup = writers.get\n"
        "    writer = lookup('place')\n"
        "    return await writer(order)\n"
    )
    joined_url = ast.parse(
        "def send(client, host, body):\n"
        "    pieces = ['/api/v1/', 'modify', 'order']\n"
        "    url = host + ''.join(pieces)\n"
        "    return client.post(url, json=body)\n"
    )
    assert _forward_to_openalgo_references(globals_get)
    assert _raw_broker_write_offenders(mapping_get, "fixture.py")
    assert _raw_order_write_url_references(joined_url)


def test_forward_to_openalgo_has_zero_non_test_callable_references() -> None:
    canonical_path = "packages/core/core/src/flinttrade_core/order_routes.py"
    definitions: list[str] = []
    offenders: list[str] = []
    for path in _python_sources(_PRODUCTION_PYTHON_ROOTS):
        relative = path.relative_to(_REPO_ROOT).as_posix()
        tree = _parse_source(path)
        definitions.extend(
            f"{relative}:{node.lineno}"
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "_forward_to_openalgo"
        )
        offenders.extend(_format_ast_offender(relative, node) for node in _forward_to_openalgo_references(tree))
    assert len(definitions) == 1 and definitions[0].startswith(f"{canonical_path}:"), (
        f"The retired forwarding helper must remain one identifiable definition; found {definitions}"
    )
    assert not offenders, (
        "_forward_to_openalgo must have zero non-test callable references; any "
        "direct, aliased or reflective recovery can reactivate an ungated write:\n" + "\n".join(offenders)
    )


def test_no_raw_order_write_urls_in_services_and_webhooks():
    """G12 blind-spot tripwire: no hand-built OpenAlgo order-write URL anywhere.

    A raw ``httpx.post(f"{host}/api/v1/placeorder", ...)`` never matches the
    attribute-call regexes above, so it would bypass every guard in this file.
    This scans services/webhooks/core for order-write ENDPOINT strings outside
    the canonical client and the v1 compat route table. Comments are skipped;
    docstrings outside the allowlist still fail (they advertise a raw path).
    """
    offenders: list[str] = []
    for path in _python_sources(_ORDER_SURFACE_ROOTS):
        relative = path.relative_to(_REPO_ROOT).as_posix()
        if relative in _ORDER_WRITE_URL_ALLOWLIST:
            continue
        offenders.extend(
            _format_ast_offender(relative, node) for node in _raw_order_write_url_references(_parse_source(path))
        )
    assert not offenders, (
        "Raw OpenAlgo order-write endpoint URL outside the canonical client "
        "(contract §8.1 / G12). Order writes must traverse gate_order -> "
        "BrokerRouter — never a hand-built endpoint POST:\n" + "\n".join(offenders)
    )


def test_broker_mcp_surface_is_metadata_only():
    """Broker-hosted MCP support must stay setup metadata, not an order proxy.

    Dhan and Groww MCP servers may expose trade tools externally, but FlintTrade
    must not add a local POST/PATCH/DELETE route that forwards MCP tool calls
    around ``gate_order`` / ``gate_broker_write`` -> ``BrokerRouter``. The local
    route is therefore GET-only catalogue metadata.
    """
    from flask import Flask

    from flinttrade_gateway.capabilities_routes import capabilities_bp

    app = Flask(__name__)
    app.register_blueprint(capabilities_bp)
    mcp_rules = sorted(
        (rule.rule, sorted(rule.methods - {"HEAD", "OPTIONS"}))
        for rule in app.url_map.iter_rules()
        if "mcp" in rule.rule
    )
    assert mcp_rules == [("/api/v1/broker/mcp", ["GET"])]
