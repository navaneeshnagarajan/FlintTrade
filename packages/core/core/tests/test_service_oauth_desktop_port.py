"""The real desktop listener publishes its kernel-selected OAuth callback."""

import socket
from flask import Flask
import pytest
from flinttrade_core import desktop

pytestmark = pytest.mark.integration


def test_owned_desktop_rebinds_oauth_before_each_ready(monkeypatch, backend_lease_proof):
    from packages.core.core.tests.test_desktop import _stub_desktop_shutdown_dependencies

    _stub_desktop_shutdown_dependencies(monkeypatch)
    observations = []
    for _ in range(2):
        app = Flask("oauth-port")
        app.config["SERVICE_OAUTH_CONFIG"] = {"deployment": "local_oss", "redirect_uri": "http://127.0.0.1:1/wrong"}
        monkeypatch.setattr(desktop, "_build_app", lambda proof, app=app: app)

        def ready(message, app=app):
            port = int(message.split("port=")[1])
            with socket.create_connection(("127.0.0.1", port), timeout=2):
                observations.append((port, dict(app.config["SERVICE_OAUTH_CONFIG"])))
            raise KeyboardInterrupt

        desktop._serve_owned(0, backend_lease_proof=backend_lease_proof, ready_writer=ready)
    assert len(observations) == 2
    for port, config in observations:
        assert config == {
            "desktop_bound": True,
            "redirect_uri": f"http://127.0.0.1:{port}/v1/services/connections/oauth/callback",
        }
