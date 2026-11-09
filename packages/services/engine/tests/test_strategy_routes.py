"""Tests for packages/services/engine/src/strategy_routes.py (Flask Blueprint).

Uses Flask test client with a real UserStrategyRunner backed by a temp dir.
Subprocess launch is mocked to avoid spawning real processes.
"""

from __future__ import annotations

import os
import subprocess
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
    import flinttrade_engine.strategy_runner as _runner_mod
    import flinttrade_engine.strategy_routes as _routes_mod

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
    import flinttrade_engine.strategy_routes as _routes_mod

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


@pytest.fixture(autouse=True)
def _mock_complete_process_tree(monkeypatch):
    """Model tree ownership for route tests that replace ``subprocess.Popen``."""
    import flinttrade_engine.strategy_runner as runner_module

    monkeypatch.setattr(runner_module.platform, "system", lambda: "Linux")
    monkeypatch.setattr(runner_module, "_find_bwrap_executable", lambda: None)

    def create_tree(process, _system, **_limits):
        tree = MagicMock()
        alive = True

        def is_alive() -> bool:
            return alive

        def terminate() -> None:
            nonlocal alive
            process.terminate()
            alive = False

        tree.is_alive.side_effect = is_alive
        tree.terminate.side_effect = terminate
        tree.kill.side_effect = terminate
        tree.wait_gone.side_effect = lambda _timeout: not alive
        return tree

    monkeypatch.setattr(runner_module, "_create_process_tree", create_tree)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestStrategyRoutes:
    def test_shutdown_strategy_runtime_exposes_parent_lifecycle_owner(self, app):
        from flinttrade_engine.strategy_routes import shutdown_strategy_runtime

        runner = MagicMock()
        runner.stop_all.return_value = ["one", "two"]
        app.config["STRATEGY_RUNNER"] = runner

        assert shutdown_strategy_runtime(app) == ["one", "two"]
        runner.stop_all.assert_called_once_with()

    def test_upload_safe_strategy(self, client):
        resp = client.post(
            "/api/v1/strategies/upload",
            json={"name": "safe_strat", "code": SAFE_CODE},
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["status"] == "success"
        assert "strategy_id" in data

    def test_upload_dangerous_strategy_returns_422(self, client):
        resp = client.post(
            "/api/v1/strategies/upload",
            json={"name": "bad_strat", "code": DANGEROUS_CODE},
        )
        assert resp.status_code == 422
        data = resp.get_json()
        assert data["status"] == "error"
        assert "violations" in data

    def test_upload_missing_name_returns_400(self, client):
        resp = client.post(
            "/api/v1/strategies/upload",
            json={"code": SAFE_CODE},
        )
        assert resp.status_code == 400

    def test_upload_strategy_with_file_derive_name(self, client):
        import io
        data = {
            "file": (io.BytesIO(SAFE_CODE.encode("utf-8")), "my_auto_named_strat.py")
        }
        resp = client.post(
            "/api/v1/strategies/upload",
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
            "/api/v1/strategies/upload",
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
            "/api/v1/strategies/upload",
            data=data,
            content_type="multipart/form-data"
        )
        assert resp.status_code == 201
        resp_data = resp.get_json()
        assert resp_data["status"] == "success"
        assert "strategy" in resp_data["message"]

    def test_list_strategies_empty(self, client):
        resp = client.get("/api/v1/strategies")
        assert resp.status_code == 200
        assert resp.get_json()["data"]["strategies"] == []

    def test_list_strategies_after_upload(self, client):
        client.post(
            "/api/v1/strategies/upload",
            json={"name": "listed", "code": SAFE_CODE},
        )
        resp = client.get("/api/v1/strategies")
        assert len(resp.get_json()["data"]["strategies"]) == 1

    @pytest.mark.skipif(
        os.name == "nt",
        reason="the fixture pins platform.system() to Linux, whose hard limits need the POSIX resource module",
    )
    def test_list_and_status_keep_unknown_ownership(self, client):
        upload_resp = client.post(
            "/api/v1/strategies/upload",
            json={"name": "uncertain_tree", "code": SAFE_CODE},
        )
        strategy_id = upload_resp.get_json()["strategy_id"]
        with patch("subprocess.Popen", return_value=_make_mock_process(pid=808)):
            start = client.post(f"/api/v1/strategies/{strategy_id}/start")
        assert start.status_code == 200

        runner = client.application.config["STRATEGY_RUNNER"]
        tree = MagicMock()
        tree.is_alive.side_effect = OSError("job query failed")
        runner._running[strategy_id].tree = tree

        listed = client.get("/api/v1/strategies")
        status = client.get(f"/api/v1/strategies/{strategy_id}/status")
        listed_row = next(
            row for row in listed.get_json()["data"]["strategies"] if row["strategy_id"] == strategy_id
        )
        status_row = status.get_json()["data"]["strategy"]

        assert listed.status_code == 200
        assert status.status_code == 200
        assert listed_row["state"] == "unknown"
        assert listed_row["ownership_retained"] is True
        assert status_row["state"] == "unknown"
        assert status_row["ownership_retained"] is True
        assert strategy_id in runner._running
        tree.close.assert_not_called()

    @pytest.mark.skipif(
        os.name == "nt",
        reason="the fixture pins platform.system() to Linux, whose hard limits need the POSIX resource module",
    )
    def test_start_while_tree_state_is_unknown_does_not_release_ownership(self, client):
        upload_resp = client.post(
            "/api/v1/strategies/upload",
            json={"name": "restart_blocked", "code": SAFE_CODE},
        )
        strategy_id = upload_resp.get_json()["strategy_id"]
        with patch("subprocess.Popen", return_value=_make_mock_process(pid=909)):
            first = client.post(f"/api/v1/strategies/{strategy_id}/start")
        assert first.status_code == 200

        runner = client.application.config["STRATEGY_RUNNER"]
        entry = runner._running[strategy_id]
        tree = MagicMock()
        tree.is_alive.side_effect = OSError("job query failed")
        entry.tree = tree

        with patch("subprocess.Popen") as popen:
            second = client.post(f"/api/v1/strategies/{strategy_id}/start")

        assert second.status_code != 200
        assert second.get_json()["status"] == "error"
        popen.assert_not_called()
        assert strategy_id in runner._running
        assert runner._running[strategy_id] is entry
        tree.close.assert_not_called()
        retained = client.get(f"/api/v1/strategies/{strategy_id}/status").get_json()["data"]["strategy"]
        assert retained["state"] == "unknown"
        assert retained["ownership_retained"] is True

    @pytest.mark.skipif(
        os.name == "nt",
        reason="the fixture pins platform.system() to Linux, whose hard limits need the POSIX resource module",
    )
    def test_start_strategy(self, client):
        upload_resp = client.post(
            "/api/v1/strategies/upload",
            json={"name": "startable", "code": SAFE_CODE},
        )
        strategy_id = upload_resp.get_json()["strategy_id"]

        mock_proc = _make_mock_process()
        with patch("subprocess.Popen", return_value=mock_proc):
            resp = client.post(f"/api/v1/strategies/{strategy_id}/start")

        assert resp.status_code == 200
        assert resp.get_json()["status"] == "success"

    def test_start_nonexistent_strategy_returns_404(self, client, app):
        with patch.object(app.config["STRATEGY_RUNNER"], "start", side_effect=FileNotFoundError("Not found")):
            resp = client.post("/api/v1/strategies/nonexistent-id/start")
        assert resp.status_code == 404

    def test_start_already_running_strategy_returns_409(self, client, app):
        upload_resp = client.post(
            "/api/v1/strategies/upload",
            json={"name": "startable_twice", "code": SAFE_CODE},
        )
        strategy_id = upload_resp.get_json()["strategy_id"]

        mock_proc = _make_mock_process()
        with patch("subprocess.Popen", return_value=mock_proc):
            client.post(f"/api/v1/strategies/{strategy_id}/start")
            resp = client.post(f"/api/v1/strategies/{strategy_id}/start")

        assert resp.status_code == 409

    def test_start_strategy_generic_error(self, client, app):
        upload_resp = client.post(
            "/api/v1/strategies/upload",
            json={"name": "start_error", "code": SAFE_CODE},
        )
        strategy_id = upload_resp.get_json()["strategy_id"]

        with patch.object(app.config["STRATEGY_RUNNER"], "start", side_effect=Exception("Generic error")):
            resp = client.post(f"/api/v1/strategies/{strategy_id}/start")

        assert resp.status_code == 500

    def test_stop_running_strategy_success(self, client, app):
        upload_resp = client.post(
            "/api/v1/strategies/upload",
            json={"name": "stoppable_run", "code": SAFE_CODE},
        )
        strategy_id = upload_resp.get_json()["strategy_id"]

        mock_proc = _make_mock_process()
        with patch("subprocess.Popen", return_value=mock_proc):
            client.post(f"/api/v1/strategies/{strategy_id}/start")

        with patch.object(mock_proc, "terminate"):
            resp = client.post(f"/api/v1/strategies/{strategy_id}/stop")

        assert resp.status_code == 200
        assert resp.get_json()["status"] == "success"

    def test_stop_nonexistent_strategy_returns_404(self, client):
        resp = client.post("/api/v1/strategies/nonexistent-id/stop")
        assert resp.status_code == 404

    def test_stop_not_running_returns_success(self, client):
        upload_resp = client.post(
            "/api/v1/strategies/upload",
            json={"name": "stoppable", "code": SAFE_CODE},
        )
        strategy_id = upload_resp.get_json()["strategy_id"]
        resp = client.post(f"/api/v1/strategies/{strategy_id}/stop")
        # Not running — treated as no-op success
        assert resp.status_code == 200

    def test_stop_strategy_generic_error(self, client, app):
        upload_resp = client.post(
            "/api/v1/strategies/upload",
            json={"name": "stop_error", "code": SAFE_CODE},
        )
        strategy_id = upload_resp.get_json()["strategy_id"]

        with patch.object(app.config["STRATEGY_RUNNER"], "stop", side_effect=Exception("Generic error")):
            resp = client.post(f"/api/v1/strategies/{strategy_id}/stop")

        assert resp.status_code == 500

    def test_stop_termination_failure_is_not_reported_as_already_stopped(self, client, app):
        upload_resp = client.post(
            "/api/v1/strategies/upload",
            json={"name": "stop_timeout", "code": SAFE_CODE},
        )
        strategy_id = upload_resp.get_json()["strategy_id"]

        with patch.object(
            app.config["STRATEGY_RUNNER"],
            "stop",
            side_effect=RuntimeError("could not confirm forced process termination"),
        ):
            resp = client.post(f"/api/v1/strategies/{strategy_id}/stop")

        assert resp.status_code == 500
        assert resp.get_json()["status"] == "error"

    def test_delete_strategy(self, client):
        upload_resp = client.post(
            "/api/v1/strategies/upload",
            json={"name": "deletable", "code": SAFE_CODE},
        )
        strategy_id = upload_resp.get_json()["strategy_id"]

        resp = client.delete(f"/api/v1/strategies/{strategy_id}")
        assert resp.status_code == 200

        # Verify it's gone from list
        list_resp = client.get("/api/v1/strategies")
        ids = [s["strategy_id"] for s in list_resp.get_json()["data"]["strategies"]]
        assert strategy_id not in ids

    def test_get_status_stopped(self, client):
        upload_resp = client.post(
            "/api/v1/strategies/upload",
            json={"name": "status_check", "code": SAFE_CODE},
        )
        strategy_id = upload_resp.get_json()["strategy_id"]

        resp = client.get(f"/api/v1/strategies/{strategy_id}/status")
        assert resp.status_code == 200
        assert resp.get_json()["data"]["strategy"]["state"] == "stopped"

    def test_get_logs_empty(self, client):
        upload_resp = client.post(
            "/api/v1/strategies/upload",
            json={"name": "log_check", "code": SAFE_CODE},
        )
        strategy_id = upload_resp.get_json()["strategy_id"]

        resp = client.get(f"/api/v1/strategies/{strategy_id}/logs")
        assert resp.status_code == 200
        assert resp.get_json()["data"]["lines"] == []

    def test_no_runner_returns_503(self, client_no_runner):
        resp = client_no_runner.get("/api/v1/strategies")
        assert resp.status_code == 503

    def test_status_nonexistent_returns_404(self, client):
        resp = client.get("/api/v1/strategies/nonexistent-id/status")
        assert resp.status_code == 404
