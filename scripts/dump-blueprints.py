#!/usr/bin/env python3
"""Enumerate Flask blueprints registered in packages/core/core/src/app.py.

Emits the 7-column commit-0 baseline schema:
blueprint_name,current_url_prefix,line_number,target_url_prefix,methods,
owner_package,duplicate_flag
"""

from __future__ import annotations

import ast
import csv
from pathlib import Path
import sys

APP_PY = Path("packages/core/core/src/app.py")
DUPLICATE_PREFIXES: set[str] = {
    "/api/v1/health",
    "/api/v1/errors",
}
FIELDNAMES = [
    "blueprint_name",
    "current_url_prefix",
    "line_number",
    "target_url_prefix",
    "methods",
    "owner_package",
    "duplicate_flag",
]


def _parent_map(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    return parents


def _imports(tree: ast.AST) -> dict[str, str]:
    imports: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            module = node.module
            if node.level:
                module = "." * node.level + module
            for alias in node.names:
                imports[alias.asname or alias.name] = module
    return imports


def _owner_package(bp_name: str, imports: dict[str, str]) -> str:
    module = imports.get(bp_name, "")
    parts = module.lstrip(".").split(".")
    if module.startswith("."):
        return "core"
    if len(parts) >= 2 and parts[0] == "packages":
        return parts[1]
    return parts[0] if parts and parts[0] else "?"


def _module_path(module: str) -> Path | None:
    if module.startswith("."):
        return Path("packages/core/core/src") / f"{module.lstrip('.').replace('.', '/')}.py"
    parts = module.split(".")
    if len(parts) >= 3 and parts[0] == "packages":
        return Path(*parts).with_suffix(".py")
    return None


def _blueprint_prefix(bp_name: str, module: str) -> str:
    module_path = _module_path(module)
    if module_path is None or not module_path.exists():
        return ""
    try:
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
    except SyntaxError:
        return ""
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(isinstance(target, ast.Name) and target.id == bp_name for target in targets):
            continue
        value = node.value
        if not isinstance(value, ast.Call):
            continue
        func = value.func
        func_name = ast.unparse(func)
        if "Blueprint" not in func_name:
            continue
        for keyword in value.keywords:
            if keyword.arg == "url_prefix":
                if isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
                    return keyword.value.value
                return ast.unparse(keyword.value).strip("'\"")
    return ""


def _blueprint_routes(bp_name: str, module: str) -> list[str]:
    module_path = _module_path(module)
    if module_path is None or not module_path.exists():
        return []
    try:
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
    except SyntaxError:
        return []

    routes: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            func = decorator.func
            if not (
                isinstance(func, ast.Attribute)
                and func.attr in {"route", "get", "post", "put", "delete", "patch"}
                and isinstance(func.value, ast.Name)
                and func.value.id == bp_name
            ):
                continue
            if decorator.args and isinstance(decorator.args[0], ast.Constant):
                value = decorator.args[0].value
                if isinstance(value, str):
                    routes.append(value)
    return routes


def _route_prefix_from_routes(routes: list[str]) -> str:
    if not routes:
        return ""
    split_routes = [route.strip("/").split("/") for route in routes if route.startswith("/")]
    if not split_routes:
        return ""
    common: list[str] = []
    for parts in zip(*split_routes):
        if len(set(parts)) != 1:
            break
        common.append(parts[0])
    if not common:
        return ""
    return "/" + "/".join(common)


def _full_routes(prefix: str, routes: list[str]) -> set[str]:
    out: set[str] = set()
    for route in routes:
        if not route.startswith("/"):
            continue
        if prefix and route.startswith(prefix):
            out.add(route.rstrip("/") or "/")
        else:
            out.add(f"{prefix.rstrip('/')}{route}".rstrip("/") or "/")
    return out


def _conditional_methods(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str:
    labels: list[str] = []
    current = parents.get(node)
    while current is not None:
        if isinstance(current, ast.If):
            test = ast.unparse(current.test)
            if "apply_csp_middleware" in test:
                labels.append("ANY (csp-gated)")
            if "FLINTTRADE_DEV" in test or "app.debug" in test:
                labels.append("GET (dev-only)")
        current = parents.get(current)
    return "; ".join(dict.fromkeys(labels))


def main() -> int:
    source = APP_PY.read_text(encoding="utf-8")
    tree = ast.parse(source)
    parents = _parent_map(tree)
    imports = _imports(tree)
    rows: list[dict[str, object]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "register_blueprint"):
            continue

        kwargs = {kw.arg: kw.value for kw in node.keywords if kw.arg}
        bp_name = ast.unparse(node.args[0]) if node.args else "?"
        module = imports.get(bp_name, "")
        prefix_raw = ast.unparse(kwargs["url_prefix"]) if "url_prefix" in kwargs else ""
        prefix = prefix_raw.strip("'\"") if prefix_raw else ""
        routes = _blueprint_routes(bp_name, module)
        if not prefix:
            prefix = _blueprint_prefix(bp_name, module)
        if not prefix:
            prefix = _route_prefix_from_routes(routes)
        full_routes = _full_routes(prefix, routes)
        rows.append(
            {
                "blueprint_name": bp_name,
                "current_url_prefix": prefix,
                "line_number": node.lineno,
                "target_url_prefix": prefix,
                "methods": _conditional_methods(node, parents),
                "owner_package": _owner_package(bp_name, imports),
                "duplicate_flag": "YES" if full_routes & DUPLICATE_PREFIXES else "",
            }
        )

    writer = csv.DictWriter(sys.stdout, fieldnames=FIELDNAMES)
    writer.writeheader()
    for row in sorted(rows, key=lambda item: int(item["line_number"])):
        writer.writerow(row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
