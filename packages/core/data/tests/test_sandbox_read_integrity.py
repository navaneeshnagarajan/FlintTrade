"""Installed Sandbox read failures are unavailable, never fabricated zero evidence."""
from __future__ import annotations

from unittest.mock import Mock

from flask import Flask
import pytest

from flinttrade_data.sandbox_routes import data_sandbox_bp

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("failure", ["trades", "capital", "pnl"])
def test_status_refuses_incomplete_read_evidence(failure):
    engine = Mock()
    engine.get_capital.return_value = {"initial": 100.0, "current": 110.0}
    engine.get_pnl.return_value = {"net": 10.0, "gross": 12.0, "charges": 2.0}
    engine.get_trades.return_value = []
    if failure == "trades":
        engine.get_trades.side_effect = OSError("unavailable")
    elif failure == "capital":
        engine.get_capital.return_value = {}
    else:
        engine.get_pnl.return_value = {}
    app = Flask(__name__)
    app.register_blueprint(data_sandbox_bp)
    app.config["DATA_SANDBOX_ENGINE"] = engine
    response = app.test_client().get("/v1/sandbox/status")
    assert response.status_code == 503
    assert response.get_json()["status"] == "error"
    assert "data" not in response.get_json()


def test_real_policy_and_zero_status_are_observed_not_defaults(tmp_path):
    from dataclasses import asdict
    from flinttrade_data.sandbox_engine import SandboxConfig, SandboxEngine

    path = str(tmp_path / "sandbox.sqlite")
    engine = SandboxEngine(db_path=path, config=SandboxConfig(starting_capital=1234.0, equity_leverage=2))
    engine.close()
    engine = SandboxEngine(db_path=path)
    app = Flask(__name__)
    app.register_blueprint(data_sandbox_bp)
    app.config["DATA_SANDBOX_ENGINE"] = engine
    try:
        client = app.test_client()
        config = client.get("/v1/sandbox/config")
        assert config.status_code == 200
        assert config.get_json()["data"]["config"] == asdict(engine.config)
        assert config.get_json()["data"]["config"]["equity_leverage"] == 2
        status = client.get("/v1/sandbox/status")
        assert status.status_code == 200
        assert status.get_json()["data"] == {
            "capital": 1234.0, "initial_capital": 1234.0, "pnl": 0.0,
            "gross_pnl": 0.0, "charges": 0.0, "trades_count": 0,
        }
    finally:
        engine.close()
