"""Tests for packages/engine/src/strategy_routes.py (Flask Blueprint).

Uses Flask test client with a real UserStrategyRunner backed by a temp dir.
Subprocess launch is mocked to avoid spawning real processes.
"""

from __future__ import annotations

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
            json={"name": "no_code_strat"},
        )
        assert resp.status_code == 400

    @patch("packages.engine.src.strategy_runner.UserStrategyRunner.upload")
    def test_upload_value_error_returns_422(self, mock_upload, client):
        mock_upload.side_effect = ValueError("Invalid code")
        resp = client.post(
            "/ft-api/v1/strategies/upload",
            json={"name": "value_err_strat", "code": SAFE_CODE},
        )
        assert resp.status_code == 422
        assert resp.get_json()["status"] == "error"

    def test_upload_multipart_file(self, client):
        from io import BytesIO
        data = {
            "name": "multipart_strat",
            "file": (BytesIO(SAFE_CODE.encode("utf-8")), "strategy.py")
        }
        resp = client.post(
            "/ft-api/v1/strategies/upload",
            data=data,
            content_type="multipart/form-data"
        )
        assert resp.status_code == 201
        assert resp.get_json()["status"] == "success"

    def test_upload_multipart_file_no_name(self, client):
        from io import BytesIO
        data = {
            "file": (BytesIO(SAFE_CODE.encode("utf-8")), "auto_name_strat.py")
        }
        resp = client.post(
            "/ft-api/v1/strategies/upload",
            data=data,
            content_type="multipart/form-data"
        )
        assert resp.status_code == 201
        assert resp.get_json()["status"] == "success"

    @patch("packages.engine.src.strategy_runner.UserStrategyRunner.upload")
    def test_upload_exception_returns_500(self, mock_upload, client):
        mock_upload.side_effect = Exception("DB connection failed")
        resp = client.post(
            "/ft-api/v1/strategies/upload",
            json={"name": "fail_strat", "code": SAFE_CODE},
        )
        assert resp.status_code == 500
        assert resp.get_json()["status"] == "error"

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

    def test_start_strategy_not_found_returns_404(self, client):
        resp = client.post("/ft-api/v1/strategies/nonexistent-id/start")
        assert resp.status_code == 404
        assert resp.get_json()["status"] == "error"

    def test_start_strategy_already_running_returns_409(self, client):
        upload_resp = client.post(
            "/ft-api/v1/strategies/upload",
            json={"name": "double_start", "code": SAFE_CODE},
        )
        strategy_id = upload_resp.get_json()["strategy_id"]

        mock_proc = _make_mock_process()
        with patch("subprocess.Popen", return_value=mock_proc):
            client.post(f"/ft-api/v1/strategies/{strategy_id}/start")
            resp = client.post(f"/ft-api/v1/strategies/{strategy_id}/start")

        assert resp.status_code == 409
        assert resp.get_json()["status"] == "error"

    @patch("packages.engine.src.strategy_runner.UserStrategyRunner.start")
    def test_start_strategy_exception_returns_500(self, mock_start, client):
        mock_start.side_effect = Exception("System error")
        upload_resp = client.post(
            "/ft-api/v1/strategies/upload",
            json={"name": "fail_start", "code": SAFE_CODE},
        )
        strategy_id = upload_resp.get_json()["strategy_id"]

        resp = client.post(f"/ft-api/v1/strategies/{strategy_id}/start")
        assert resp.status_code == 500
        assert resp.get_json()["status"] == "error"

    def test_stop_not_running_returns_success(self, client):
        upload_resp = client.post(
            "/ft-api/v1/strategies/upload",
            json={"name": "stoppable", "code": SAFE_CODE},
        )
        strategy_id = upload_resp.get_json()["strategy_id"]
        resp = client.post(f"/ft-api/v1/strategies/{strategy_id}/stop")
        # Not running — treated as no-op success
        assert resp.status_code == 200

    def test_stop_strategy_running(self, client):
        upload_resp = client.post(
            "/ft-api/v1/strategies/upload",
            json={"name": "stoppable_run", "code": SAFE_CODE},
        )
        strategy_id = upload_resp.get_json()["strategy_id"]

        mock_proc = _make_mock_process()
        with patch("subprocess.Popen", return_value=mock_proc):
            client.post(f"/ft-api/v1/strategies/{strategy_id}/start")
            resp = client.post(f"/ft-api/v1/strategies/{strategy_id}/stop")

        assert resp.status_code == 200
        assert resp.get_json()["status"] == "success"

    @patch("packages.engine.src.strategy_runner.UserStrategyRunner.stop")
    def test_stop_strategy_not_found_returns_404(self, mock_stop, client):
        mock_stop.side_effect = FileNotFoundError("Not found")
        resp = client.post("/ft-api/v1/strategies/nonexistent-id/stop")
        assert resp.status_code == 404
        assert resp.get_json()["status"] == "error"

    @patch("packages.engine.src.strategy_runner.UserStrategyRunner.stop")
    def test_stop_strategy_exception_returns_500(self, mock_stop, client):
        mock_stop.side_effect = Exception("System error")
        upload_resp = client.post(
            "/ft-api/v1/strategies/upload",
            json={"name": "fail_stop", "code": SAFE_CODE},
        )
        strategy_id = upload_resp.get_json()["strategy_id"]

        resp = client.post(f"/ft-api/v1/strategies/{strategy_id}/stop")
        assert resp.status_code == 500
        assert resp.get_json()["status"] == "error"

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

    def test_delete_strategy_not_found_returns_404(self, client):
        resp = client.delete("/ft-api/v1/strategies/nonexistent-id")
        assert resp.status_code == 404
        assert resp.get_json()["status"] == "error"

    @patch("packages.engine.src.strategy_runner.UserStrategyRunner.delete")
    def test_delete_strategy_exception_returns_500(self, mock_delete, client):
        mock_delete.side_effect = Exception("System error")
        upload_resp = client.post(
            "/ft-api/v1/strategies/upload",
            json={"name": "fail_delete", "code": SAFE_CODE},
        )
        strategy_id = upload_resp.get_json()["strategy_id"]

        resp = client.delete(f"/ft-api/v1/strategies/{strategy_id}")
        assert resp.status_code == 500
        assert resp.get_json()["status"] == "error"

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

    def test_get_logs_invalid_lines_param(self, client):
        upload_resp = client.post(
            "/ft-api/v1/strategies/upload",
            json={"name": "log_check_invalid", "code": SAFE_CODE},
        )
        strategy_id = upload_resp.get_json()["strategy_id"]

        resp = client.get(f"/ft-api/v1/strategies/{strategy_id}/logs?lines=abc")
        assert resp.status_code == 200
        assert resp.get_json()["lines"] == []

    def test_get_logs_not_found(self, client):
        resp = client.get("/ft-api/v1/strategies/nonexistent-id/logs")
        assert resp.status_code == 404
        assert resp.get_json()["status"] == "error"

    def test_no_runner_returns_503(self, client_no_runner):
        resp = client_no_runner.get("/ft-api/v1/strategies")
        assert resp.status_code == 503

        resp = client_no_runner.post("/ft-api/v1/strategies/upload", json={"name": "x", "code": "y"})
        assert resp.status_code == 503

        resp = client_no_runner.post("/ft-api/v1/strategies/123/start")
        assert resp.status_code == 503

        resp = client_no_runner.post("/ft-api/v1/strategies/123/stop")
        assert resp.status_code == 503

        resp = client_no_runner.delete("/ft-api/v1/strategies/123")
        assert resp.status_code == 503

        resp = client_no_runner.get("/ft-api/v1/strategies/123/status")
        assert resp.status_code == 503

        resp = client_no_runner.get("/ft-api/v1/strategies/123/logs")
        assert resp.status_code == 503

    def test_status_nonexistent_returns_404(self, client):
        resp = client.get("/ft-api/v1/strategies/nonexistent-id/status")
        assert resp.status_code == 404
