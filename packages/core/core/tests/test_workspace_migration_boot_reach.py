"""Saved strategy migrations remain reachable from backend boot."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture()
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated workspace + loopback auth (no API key configured)."""
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.delenv("FLINTTRADE_HOME", raising=False)
    monkeypatch.delenv("FLINTTRADE_API_KEY", raising=False)
    monkeypatch.delenv("FLINTTRADE_API_KEY", raising=False)
    master_password = tmp_path / "master_password"
    master_password.write_text("workspace-migration-boot-reach-password", encoding="utf-8")
    master_password.chmod(0o600)
    return tmp_path


def _count_calls(monkeypatch: pytest.MonkeyPatch, module: object, name: str) -> list[int]:
    """Wrap ``module.name`` with a call counter, preserving its behaviour.

    Args:
        monkeypatch: pytest monkeypatch fixture.
        module: Module holding the resolver.
        name: Attribute name of the resolver.

    Returns:
        A single-element list whose value is the call count so far.
    """
    calls = [0]
    original = getattr(module, name)

    def counted() -> Path:
        calls[0] += 1
        return original()

    monkeypatch.setattr(module, name, counted)
    return calls


def _open_the_migration_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``default_workspace_active()`` report a default install.

    Both resolvers gate their probe on it, and the test harness always exports
    ``FLINTTRADE_WORKSPACE_DIR`` (which correctly closes the gate). Forcing it
    open simulates a legacy-state boot while every path still resolves inside
    ``tmp_path``.
    """
    import flinttrade_core.workspace as workspace_mod

    monkeypatch.setattr(workspace_mod, "default_workspace_active", lambda: True)


def test_boot_calls_the_strategies_resolver(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
    backend_lease_factory,
) -> None:
    """``create_flask_app`` must wire the runner from the shared resolver."""
    import flinttrade_engine.strategy_hot_reload as hot_reload

    calls = _count_calls(monkeypatch, hot_reload, "default_strategies_dir")

    from flinttrade_core.app import create_flask_app

    app = create_flask_app(backend_lease_proof=backend_lease_factory())

    assert calls[0] >= 1, "the strategies resolver — and so its migration — never ran"
    runner = app.config["STRATEGY_RUNNER"]
    assert runner is not None
    assert runner._strategies_dir == workspace / "strategies"


def test_legacy_strategies_are_migrated_by_the_boot_itself(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
    backend_lease_factory,
) -> None:
    """A pre-workspace strategies tree lands in the workspace during boot.

    The workspace strategies directory already holds the runner's ``logs/``
    from an earlier boot — the exact state that used to block the copy.
    """
    import flinttrade_engine.strategy_hot_reload as hot_reload

    legacy = workspace / "legacy-home" / ".flinttrade" / "strategies"
    legacy.mkdir(parents=True)
    (legacy / "ema.py").write_text("class Strategy:\n    pass\n", encoding="utf-8")
    monkeypatch.setattr(hot_reload, "_legacy_strategies_dir", lambda: legacy)
    (workspace / "strategies" / "logs").mkdir(parents=True)
    _open_the_migration_gate(monkeypatch)

    from flinttrade_core.app import create_flask_app

    app = create_flask_app(backend_lease_proof=backend_lease_factory())

    runner = app.config["STRATEGY_RUNNER"]
    assert (runner._strategies_dir / "ema.py").exists(), "boot did not migrate the legacy tree"
    assert (legacy / "ema.py").exists(), "legacy tree must be retained"
