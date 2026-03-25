"""Tests for packages/engine/src/strategy_routes.py (Flask Blueprint).

Uses Flask test client with a real UserStrategyRunner backed by a temp dir.
Subprocess launch is mocked to avoid spawning real processes.
"""

from __future__ import annotations

import io
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


SAFE_CODE = """\
# Simple safe strategy
def on_tick(ltp):
    pass
"""

DANGEROUS_CODE = """\
import os
os.system("rm -rf /")
"""


@pytest.fixture()
def app(tmp_path):
    import packages.engine.src.strategy_runner as _runner_mod
    import packages.engine.src.strategy_routes as _routes_mod

    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True

    runner = _runner_mod.UserStrategyRunner(strategies_dir=tmp_path / "strategies")
    flask_app.config["STRATEGY_RUNNER"] = runner

    flask_app.register_blueprint(_routes_mod.strategy_bp)
    return flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def app_no_runner():
    import packages.engine.src.strategy_routes as _routes_mod

    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(_routes_mod.strategy_bp)
    return flask_app


@pytest.fixture()
def client_no_runner(app_no_runner):
    return app_no_runner.test_client()


def _make_mock_process(pid: int = 9999, returncode=None):
    proc = MagicMock(spec=subprocess.Popen)
    proc.pid = pid
    proc.poll.return_value = returncode
    proc.wait.return_value = returncode
    return proc


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestStrategyRoutes:
    def test_upload_safe_strategy(self, client):
        resp = client.post(
            "/ft-api/v1/strategies/upload",
            json={"name": "safe_strat", "code": SAFE_CODE},
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["status"] == "success"
        assert "strategy_id" in data

    def test_upload_dangerous_strategy_returns_422(self, client):
        resp = client.post(
            "/ft-api/v1/strategies/upload",
            json={"name": "bad_strat", "code": DANGEROUS_CODE},
        )
        assert resp.status_code == 422
        data = resp.get_json()
        assert data["status"] == "error"
        assert "violations" in data

    def test_upload_missing_name_returns_400(self, client):
        resp = client.post(
            "/ft-api/v1/strategies/upload",
            json={"code": SAFE_CODE},
        )
        assert resp.status_code == 400

    def test_upload_missing_code_returns_400(self, client):
        resp = client.post(
            "/ft-api/v1/strategies/upload",
            json={"name": "missing_code_strat"},
        )
        assert resp.status_code == 400

    def test_upload_value_error(self, client, app):
        runner = app.config["STRATEGY_RUNNER"]
        with patch.object(runner, 'upload', side_effect=ValueError("Invalid code")):
            resp = client.post(
                "/ft-api/v1/strategies/upload",
                json={"name": "value_err_strat", "code": SAFE_CODE},
            )
            assert resp.status_code == 422
            assert resp.get_json()["message"] == "Invalid code"

    def test_upload_exception(self, client, app):
        runner = app.config["STRATEGY_RUNNER"]
        with patch.object(runner, 'upload', side_effect=Exception("Database down")):
            resp = client.post(
                "/ft-api/v1/strategies/upload",
                json={"name": "exc_strat", "code": SAFE_CODE},
            )
            assert resp.status_code == 500
            assert "Upload failed: Database down" in resp.get_json()["message"]

    def test_upload_multipart(self, client):
        data = {
            "name": "multipart_strat",
            "file": (io.BytesIO(SAFE_CODE.encode("utf-8")), "strategy.py")
        }
        resp = client.post(
            "/ft-api/v1/strategies/upload",
            data=data,
            content_type="multipart/form-data"
        )
        assert resp.status_code == 201
        data_resp = resp.get_json()
        assert data_resp["status"] == "success"
        assert "strategy_id" in data_resp

    def test_upload_multipart_no_name(self, client):
        data = {
            "file": (io.BytesIO(SAFE_CODE.encode("utf-8")), "my_strategy.py")
        }
        resp = client.post(
            "/ft-api/v1/strategies/upload",
            data=data,
            content_type="multipart/form-data"
        )
        assert resp.status_code == 201
        data_resp = resp.get_json()
        assert data_resp["status"] == "success"
        assert "strategy_id" in data_resp

        # Check name was derived
        list_resp = client.get("/ft-api/v1/strategies")
        strategies = list_resp.get_json()["strategies"]
        assert len(strategies) == 1
        assert strategies[0]["name"] == "my_strategy"

    def test_list_strategies_empty(self, client):
        resp = client.get("/ft-api/v1/strategies")
        assert resp.status_code == 200
        assert resp.get_json()["strategies"] == []

    def test_list_strategies_after_upload(self, client):
        client.post(
            "/ft-api/v1/strategies/upload",
            json={"name": "listed", "code": SAFE_CODE},
        )
        resp = client.get("/ft-api/v1/strategies")
        assert len(resp.get_json()["strategies"]) == 1

    def test_start_strategy(self, client):
        upload_resp = client.post(
            "/ft-api/v1/strategies/upload",
            json={"name": "startable", "code": SAFE_CODE},
        )
        strategy_id = upload_resp.get_json()["strategy_id"]

        mock_proc = _make_mock_process()
        with patch("subprocess.Popen", return_value=mock_proc):
            resp = client.post(f"/ft-api/v1/strategies/{strategy_id}/start")

        assert resp.status_code == 200
        assert resp.get_json()["status"] == "success"

    def test_start_strategy_not_found(self, client):
        resp = client.post("/ft-api/v1/strategies/nonexistent/start")
        assert resp.status_code == 404
        assert "not found" in resp.get_json()["message"].lower()

    def test_start_strategy_conflict(self, client, app):
        upload_resp = client.post(
            "/ft-api/v1/strategies/upload",
            json={"name": "conflict_strat", "code": SAFE_CODE},
        )
        strategy_id = upload_resp.get_json()["strategy_id"]

        runner = app.config["STRATEGY_RUNNER"]
        with patch.object(runner, 'start', side_effect=RuntimeError("Already running")):
            resp = client.post(f"/ft-api/v1/strategies/{strategy_id}/start")
            assert resp.status_code == 409
            assert resp.get_json()["message"] == "Already running"

    def test_start_strategy_exception(self, client, app):
        upload_resp = client.post(
            "/ft-api/v1/strategies/upload",
            json={"name": "exc_start_strat", "code": SAFE_CODE},
        )
        strategy_id = upload_resp.get_json()["strategy_id"]

        runner = app.config["STRATEGY_RUNNER"]
        with patch.object(runner, 'start', side_effect=Exception("Failed to launch")):
            resp = client.post(f"/ft-api/v1/strategies/{strategy_id}/start")
            assert resp.status_code == 500
            assert "Start failed: Failed to launch" in resp.get_json()["message"]

    def test_stop_not_running_returns_success(self, client):
        upload_resp = client.post(
            "/ft-api/v1/strategies/upload",
            json={"name": "stoppable", "code": SAFE_CODE},
        )
        strategy_id = upload_resp.get_json()["strategy_id"]
        resp = client.post(f"/ft-api/v1/strategies/{strategy_id}/stop")
        # Not running — treated as no-op success
        assert resp.status_code == 200

    def test_stop_strategy_not_found(self, client, app):
        runner = app.config["STRATEGY_RUNNER"]
        with patch.object(runner, 'stop', side_effect=FileNotFoundError("Strategy not found")):
            resp = client.post("/ft-api/v1/strategies/nonexistent/stop")
            assert resp.status_code == 404
            assert "not found" in resp.get_json()["message"].lower()

    def test_stop_strategy_success(self, client, app):
        upload_resp = client.post(
            "/ft-api/v1/strategies/upload",
            json={"name": "stop_success", "code": SAFE_CODE},
        )
        strategy_id = upload_resp.get_json()["strategy_id"]

        runner = app.config["STRATEGY_RUNNER"]
        # Mock stop to succeed and do nothing
        with patch.object(runner, 'stop', return_value=None):
            resp = client.post(f"/ft-api/v1/strategies/{strategy_id}/stop")
            assert resp.status_code == 200
            assert resp.get_json()["message"] == "Strategy stopped"

    def test_stop_strategy_exception(self, client, app):
        upload_resp = client.post(
            "/ft-api/v1/strategies/upload",
            json={"name": "exc_stop_strat", "code": SAFE_CODE},
        )
        strategy_id = upload_resp.get_json()["strategy_id"]

        runner = app.config["STRATEGY_RUNNER"]
        with patch.object(runner, 'stop', side_effect=Exception("Failed to kill")):
            resp = client.post(f"/ft-api/v1/strategies/{strategy_id}/stop")
            assert resp.status_code == 500
            assert "Stop failed: Failed to kill" in resp.get_json()["message"]

    def test_delete_strategy(self, client):
        upload_resp = client.post(
            "/ft-api/v1/strategies/upload",
            json={"name": "deletable", "code": SAFE_CODE},
        )
        strategy_id = upload_resp.get_json()["strategy_id"]

        resp = client.delete(f"/ft-api/v1/strategies/{strategy_id}")
        assert resp.status_code == 200

        # Verify it's gone from list
        list_resp = client.get("/ft-api/v1/strategies")
        ids = [s["strategy_id"] for s in list_resp.get_json()["strategies"]]
        assert strategy_id not in ids

    def test_delete_strategy_not_found(self, client, app):
        runner = app.config["STRATEGY_RUNNER"]
        with patch.object(runner, 'delete', side_effect=FileNotFoundError("Strategy not found")):
            resp = client.delete("/ft-api/v1/strategies/nonexistent")
            assert resp.status_code == 404
            assert "not found" in resp.get_json()["message"].lower()

    def test_delete_strategy_exception(self, client, app):
        upload_resp = client.post(
            "/ft-api/v1/strategies/upload",
            json={"name": "exc_del_strat", "code": SAFE_CODE},
        )
        strategy_id = upload_resp.get_json()["strategy_id"]

        runner = app.config["STRATEGY_RUNNER"]
        with patch.object(runner, 'delete', side_effect=Exception("Failed to delete files")):
            resp = client.delete(f"/ft-api/v1/strategies/{strategy_id}")
            assert resp.status_code == 500
            assert "Delete failed: Failed to delete files" in resp.get_json()["message"]

    def test_get_status_stopped(self, client):
        upload_resp = client.post(
            "/ft-api/v1/strategies/upload",
            json={"name": "status_check", "code": SAFE_CODE},
        )
        strategy_id = upload_resp.get_json()["strategy_id"]

        resp = client.get(f"/ft-api/v1/strategies/{strategy_id}/status")
        assert resp.status_code == 200
        assert resp.get_json()["strategy"]["state"] == "stopped"

    def test_get_logs_empty(self, client):
        upload_resp = client.post(
            "/ft-api/v1/strategies/upload",
            json={"name": "log_check", "code": SAFE_CODE},
        )
        strategy_id = upload_resp.get_json()["strategy_id"]

        resp = client.get(f"/ft-api/v1/strategies/{strategy_id}/logs")
        assert resp.status_code == 200
        assert resp.get_json()["lines"] == []

    def test_get_logs_invalid_lines(self, client):
        upload_resp = client.post(
            "/ft-api/v1/strategies/upload",
            json={"name": "log_lines_strat", "code": SAFE_CODE},
        )
        strategy_id = upload_resp.get_json()["strategy_id"]

        # Sending invalid 'lines' should fallback to default (100)
        resp = client.get(f"/ft-api/v1/strategies/{strategy_id}/logs?lines=invalid")
        assert resp.status_code == 200
        assert resp.get_json()["lines"] == []

    def test_get_logs_not_found(self, client, app):
        runner = app.config["STRATEGY_RUNNER"]
        with patch.object(runner, 'get_logs', side_effect=FileNotFoundError("Strategy not found")):
            resp = client.get("/ft-api/v1/strategies/nonexistent/logs")
            assert resp.status_code == 404
            assert "not found" in resp.get_json()["message"].lower()

    def test_no_runner_returns_503(self, client_no_runner):
        # List
        resp = client_no_runner.get("/ft-api/v1/strategies")
        assert resp.status_code == 503

        # Upload
        resp = client_no_runner.post(
            "/ft-api/v1/strategies/upload",
            json={"name": "no_runner", "code": SAFE_CODE},
        )
        assert resp.status_code == 503

        # Start
        resp = client_no_runner.post("/ft-api/v1/strategies/some-id/start")
        assert resp.status_code == 503

        # Stop
        resp = client_no_runner.post("/ft-api/v1/strategies/some-id/stop")
        assert resp.status_code == 503

        # Delete
        resp = client_no_runner.delete("/ft-api/v1/strategies/some-id")
        assert resp.status_code == 503

        # Status
        resp = client_no_runner.get("/ft-api/v1/strategies/some-id/status")
        assert resp.status_code == 503

        # Logs
        resp = client_no_runner.get("/ft-api/v1/strategies/some-id/logs")
        assert resp.status_code == 503

    def test_status_nonexistent_returns_404(self, client):
        resp = client.get("/ft-api/v1/strategies/nonexistent-id/status")
        assert resp.status_code == 404
