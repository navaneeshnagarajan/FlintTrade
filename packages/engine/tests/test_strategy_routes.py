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

    def test_upload_strategy_with_file_derive_name(self, client):
        import io
        data = {
            "file": (io.BytesIO(SAFE_CODE.encode("utf-8")), "my_auto_named_strat.py")
        }
        resp = client.post(
            "/ft-api/v1/strategies/upload",
            data=data,
            content_type="multipart/form-data"
        )
        assert resp.status_code == 201
        resp_data = resp.get_json()
        assert resp_data["status"] == "success"
        assert "my_auto_named_strat" in resp_data["message"]

    def test_upload_strategy_with_file_explicit_name(self, client):
        import io
        data = {
            "name": "explicit_name",
            "file": (io.BytesIO(SAFE_CODE.encode("utf-8")), "some_filename.py")
        }
        resp = client.post(
            "/ft-api/v1/strategies/upload",
            data=data,
            content_type="multipart/form-data"
        )
        assert resp.status_code == 201
        resp_data = resp.get_json()
        assert resp_data["status"] == "success"
        assert "explicit_name" in resp_data["message"]

    def test_upload_strategy_with_file_no_filename(self, client):
        import io
        data = {
            "file": (io.BytesIO(SAFE_CODE.encode("utf-8")), "")
        }
        resp = client.post(
            "/ft-api/v1/strategies/upload",
            data=data,
            content_type="multipart/form-data"
        )
        assert resp.status_code == 201
        resp_data = resp.get_json()
        assert resp_data["status"] == "success"
        assert "strategy" in resp_data["message"]

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

    def test_start_nonexistent_strategy_returns_404(self, client, app):
        with patch.object(app.config["STRATEGY_RUNNER"], "start", side_effect=FileNotFoundError("Not found")):
            resp = client.post("/ft-api/v1/strategies/nonexistent-id/start")
        assert resp.status_code == 404

    def test_start_already_running_strategy_returns_409(self, client, app):
        upload_resp = client.post(
            "/ft-api/v1/strategies/upload",
            json={"name": "startable_twice", "code": SAFE_CODE},
        )
        strategy_id = upload_resp.get_json()["strategy_id"]

        mock_proc = _make_mock_process()
        with patch("subprocess.Popen", return_value=mock_proc):
            client.post(f"/ft-api/v1/strategies/{strategy_id}/start")
            resp = client.post(f"/ft-api/v1/strategies/{strategy_id}/start")

        assert resp.status_code == 409

    def test_start_strategy_generic_error(self, client, app):
        upload_resp = client.post(
            "/ft-api/v1/strategies/upload",
            json={"name": "start_error", "code": SAFE_CODE},
        )
        strategy_id = upload_resp.get_json()["strategy_id"]

        with patch.object(app.config["STRATEGY_RUNNER"], "start", side_effect=Exception("Generic error")):
            resp = client.post(f"/ft-api/v1/strategies/{strategy_id}/start")

        assert resp.status_code == 500

    def test_stop_running_strategy_success(self, client, app):
        upload_resp = client.post(
            "/ft-api/v1/strategies/upload",
            json={"name": "stoppable_run", "code": SAFE_CODE},
        )
        strategy_id = upload_resp.get_json()["strategy_id"]

        mock_proc = _make_mock_process()
        with patch("subprocess.Popen", return_value=mock_proc):
            client.post(f"/ft-api/v1/strategies/{strategy_id}/start")

        with patch.object(mock_proc, "terminate"):
            resp = client.post(f"/ft-api/v1/strategies/{strategy_id}/stop")

        assert resp.status_code == 200
        assert resp.get_json()["status"] == "success"

    def test_stop_nonexistent_strategy_returns_404(self, client, app):
        with patch.object(app.config["STRATEGY_RUNNER"], "stop", side_effect=FileNotFoundError("Not found")):
            resp = client.post("/ft-api/v1/strategies/nonexistent-id/stop")
        assert resp.status_code == 404

    def test_stop_not_running_returns_success(self, client):
        upload_resp = client.post(
            "/ft-api/v1/strategies/upload",
            json={"name": "stoppable", "code": SAFE_CODE},
        )
        strategy_id = upload_resp.get_json()["strategy_id"]
        resp = client.post(f"/ft-api/v1/strategies/{strategy_id}/stop")
        # Not running — treated as no-op success
        assert resp.status_code == 200

    def test_stop_strategy_generic_error(self, client, app):
        upload_resp = client.post(
            "/ft-api/v1/strategies/upload",
            json={"name": "stop_error", "code": SAFE_CODE},
        )
        strategy_id = upload_resp.get_json()["strategy_id"]

        with patch.object(app.config["STRATEGY_RUNNER"], "stop", side_effect=Exception("Generic error")):
            resp = client.post(f"/ft-api/v1/strategies/{strategy_id}/stop")

        assert resp.status_code == 500

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

    def test_no_runner_returns_503(self, client_no_runner):
        resp = client_no_runner.get("/ft-api/v1/strategies")
        assert resp.status_code == 503

    def test_status_nonexistent_returns_404(self, client):
        resp = client.get("/ft-api/v1/strategies/nonexistent-id/status")
        assert resp.status_code == 404
