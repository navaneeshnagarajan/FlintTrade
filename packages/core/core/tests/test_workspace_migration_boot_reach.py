"""The flows and strategies legacy migrations must run on a real backend boot.

Both migrations live in a directory resolver rather than in ``app.py``, so they
only ever fire if ``create_flask_app`` actually calls the resolver. An earlier
wave open-coded ``_workspace_dir() / "flows"`` and ``_workspace_dir() /
"strategies"`` at the construction sites, which bypassed both resolvers and left
the migrations dead in the only production path there is.

These tests boot the app and assert the migrations happen — the resolvers are
counted, and a planted legacy tree is checked for having arrived in the
workspace. The environment override stays in force throughout (so
``workspace_dir()`` resolves to ``tmp_path``); the default-workspace gate is
monkeypatched open instead, which is what makes a legacy-state boot reproducible
without going anywhere near the developer's real home directory.
"""

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
    monkeypatch.delenv("OPENALGO_API_KEY", raising=False)
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


def test_boot_calls_the_flow_store_resolver(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``create_flask_app`` must construct the store with no ``base_dir``."""
    import flinttrade_webhooks.flow_store as flow_store

    calls = _count_calls(monkeypatch, flow_store, "_default_flows_dir")

    from flinttrade_core.app import create_flask_app

    app = create_flask_app()

    assert calls[0] >= 1, "the flows resolver — and so its migration — never ran"
    assert app.config["FLOW_STORE"] is not None
    assert app.config["FLOW_STORE"].base_dir == workspace / "flows"


def test_boot_calls_the_strategies_resolver(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``create_flask_app`` must wire the runner from the shared resolver."""
    import flinttrade_engine.strategy_hot_reload as hot_reload

    calls = _count_calls(monkeypatch, hot_reload, "default_strategies_dir")

    from flinttrade_core.app import create_flask_app

    app = create_flask_app()

    assert calls[0] >= 1, "the strategies resolver — and so its migration — never ran"
    runner = app.config["STRATEGY_RUNNER"]
    assert runner is not None
    assert runner._strategies_dir == workspace / "strategies"


def test_legacy_flows_are_migrated_by_the_boot_itself(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pre-workspace flows tree lands in the workspace during boot."""
    import flinttrade_webhooks.flow_store as flow_store

    legacy = workspace / "legacy-home" / ".flinttrade" / "flows"
    legacy.mkdir(parents=True)
    (legacy / "flow_1.json").write_text('{"id": "flow_1", "name": "Legacy"}', encoding="utf-8")
    monkeypatch.setattr(flow_store, "_legacy_flows_dir", lambda: legacy)
    _open_the_migration_gate(monkeypatch)

    from flinttrade_core.app import create_flask_app

    app = create_flask_app()

    migrated = workspace / "flows" / "flow_1.json"
    assert migrated.exists(), "boot did not migrate the legacy flows tree"
    assert (legacy / "flow_1.json").exists(), "legacy tree must be retained"
    assert [f["id"] for f in app.config["FLOW_STORE"].list_flows()] == ["flow_1"]


def test_legacy_strategies_are_migrated_by_the_boot_itself(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
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

    app = create_flask_app()

    runner = app.config["STRATEGY_RUNNER"]
    assert (runner._strategies_dir / "ema.py").exists(), "boot did not migrate the legacy tree"
    assert (legacy / "ema.py").exists(), "legacy tree must be retained"


def test_failed_flow_store_construction_still_degrades_to_503(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Moving the resolver into the constructor must not change boot honesty.

    A resolver that raises (an unwritable workspace, a failed migration) has to
    leave ``FLOW_STORE`` at ``None`` with the blueprint still registered, so the
    routes answer their own 503 rather than a bare 404.
    """
    import flinttrade_webhooks.flow_routes as flow_routes
    import flinttrade_webhooks.flow_store as flow_store

    monkeypatch.setattr(flow_routes, "_store", None)

    def _boom() -> Path:
        raise OSError("workspace unwritable (simulated)")

    monkeypatch.setattr(flow_store, "_default_flows_dir", _boom)

    from flinttrade_core.app import create_flask_app

    app = create_flask_app()

    assert app.config["FLOW_STORE"] is None
    assert "flows" in app.blueprints
    with app.test_client() as client:
        resp = client.get("/api/v1/flows")
        assert resp.status_code == 503
        assert resp.get_json()["status"] == "error"
