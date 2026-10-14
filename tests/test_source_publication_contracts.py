"""Publication metadata and public carrier annotations stay source-bound."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_desktop_uses_the_approved_public_attribution() -> None:
    package = json.loads((ROOT / "packages/apps/desktop/package.json").read_text())
    approved = "navaneeshnagarajan <259833042+navaneeshnagarajan@users.noreply.github.com>"
    matches = package.get("author") == approved
    # Do not print an offending personal attribution through assertion rewriting.
    assert matches, "Desktop attribution must use the approved public identity"


def test_reticle_source_retains_each_upstream_package_notice() -> None:
    carrier = ROOT / "tools/reticle"
    reconstruction = json.loads((carrier / "reconstruction.json").read_text())
    packages = {"core": "core", "engine": "engine", "browser": "adapters/realm/browser"}
    for package, directory in packages.items():
        notice = carrier / "licenses" / directory / "NOTICE"
        assert notice.is_file(), f"Missing retained NOTICE for @reticlehq/{package}"
        expected = reconstruction["pristine_files"][f"@reticlehq/{package}/NOTICE"]["sha256"]
        assert hashlib.sha256(notice.read_bytes()).hexdigest() == expected


@pytest.mark.parametrize("filename", ["csp.py", "csp_server.py"])
def test_public_csp_helpers_keep_parameter_and_return_annotations(filename: str) -> None:
    tree = ast.parse((ROOT / "tools/acceptance" / filename).read_text())
    functions = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_")
    ]
    assert functions, "The carrier must expose its existing callable boundaries"
    missing = []
    for function in functions:
        arguments = [*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs]
        arguments += [arg for arg in (function.args.vararg, function.args.kwarg) if arg is not None]
        missing.extend(f"{function.name}.{arg.arg}" for arg in arguments if arg.annotation is None)
        if function.returns is None:
            missing.append(f"{function.name}.return")
    assert not missing, f"Unannotated public boundaries: {missing}"
