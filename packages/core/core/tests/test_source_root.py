"""Source-checkout root discovery across editable and managed installs."""

from __future__ import annotations

from pathlib import Path

import pytest

from flinttrade_core.source_root import SOURCE_ROOT_ENV, SourceRootError, discover_source_root


pytestmark = pytest.mark.unit

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]


def _source_checkout(root: Path) -> Path:
    """Create only the marker files required by the source-root contract."""
    for relative in (
        "VERSION",
        "pyproject.toml",
        "pnpm-workspace.yaml",
        "packages/core/core/pyproject.toml",
        "packages/apps/terminal/package.json",
    ):
        marker = root / relative
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("marker\n", encoding="utf-8")
    return root


def _module_file(root: Path, relative: str) -> Path:
    module = root / relative
    module.parent.mkdir(parents=True, exist_ok=True)
    module.write_text("# synthetic module\n", encoding="utf-8")
    return module


def test_discovers_source_checkout_module_layout(tmp_path: Path) -> None:
    root = _source_checkout(tmp_path / "FlintTrade")
    module = _module_file(root, "packages/core/core/src/flinttrade_core/app.py")
    outside = tmp_path / "outside"
    outside.mkdir()

    assert discover_source_root(module_file=module, environ={}, working_directory=outside) == root.resolve()


def test_discovers_windows_non_editable_venv_layout(tmp_path: Path) -> None:
    root = _source_checkout(tmp_path / "FlintTrade")
    module = _module_file(root, ".venv/Lib/site-packages/flinttrade_core/app.py")
    outside = tmp_path / "outside"
    outside.mkdir()

    # The retired fixed-depth lookup resolves one directory above this checkout.
    assert module.resolve().parents[5] != root.resolve()
    assert discover_source_root(module_file=module, environ={}, working_directory=outside) == root.resolve()


def test_explicit_source_root_wins_after_validation(tmp_path: Path) -> None:
    root = _source_checkout(tmp_path / "FlintTrade")
    module = _module_file(tmp_path, "external/site-packages/flinttrade_core/app.py")
    outside = tmp_path / "outside"
    outside.mkdir()

    assert (
        discover_source_root(
            module_file=module,
            environ={SOURCE_ROOT_ENV: str(root)},
            working_directory=outside,
        )
        == root.resolve()
    )


def test_invalid_explicit_source_root_fails_closed_without_fallback(tmp_path: Path) -> None:
    root = _source_checkout(tmp_path / "FlintTrade")
    module = _module_file(root, "packages/core/core/src/flinttrade_core/app.py")

    with pytest.raises(SourceRootError, match=SOURCE_ROOT_ENV):
        discover_source_root(
            module_file=module,
            environ={SOURCE_ROOT_ENV: str(tmp_path / "foreign")},
            working_directory=root,
        )


def test_working_directory_is_a_validated_fallback(tmp_path: Path) -> None:
    root = _source_checkout(tmp_path / "FlintTrade")
    nested = root / "packages" / "core"
    module = _module_file(tmp_path, "external/site-packages/flinttrade_core/app.py")

    assert discover_source_root(module_file=module, environ={}, working_directory=nested) == root.resolve()


def test_discovery_fails_when_no_source_contract_is_present(tmp_path: Path) -> None:
    module = _module_file(tmp_path, "external/site-packages/flinttrade_core/app.py")
    outside = tmp_path / "outside"
    outside.mkdir()

    with pytest.raises(SourceRootError, match="source checkout"):
        discover_source_root(module_file=module, environ={}, working_directory=outside)


def test_production_consumers_do_not_use_fixed_parent_depths() -> None:
    consumers = (
        "packages/core/core/src/flinttrade_core/app.py",
        "packages/core/core/src/flinttrade_core/admin_routes.py",
        "packages/core/core/src/flinttrade_core/backtest_routes.py",
        "packages/core/core/src/flinttrade_core/broker_sdk_attest.py",
        "packages/core/core/src/flinttrade_core/config.py",
        "packages/core/core/src/flinttrade_core/docs_search_routes.py",
        "packages/core/core/src/flinttrade_core/frontend_error_routes.py",
        "packages/integrations/gateway/src/flinttrade_gateway/adapter.py",
        "packages/services/ai/src/flinttrade_ai/skill_system.py",
        "packages/services/screener/src/flinttrade_screener/ipo_routes.py",
    )

    offenders = [
        relative for relative in consumers if ".parents[" in (REPOSITORY_ROOT / relative).read_text(encoding="utf-8")
    ]
    assert offenders == []
