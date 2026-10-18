"""Mounted Settings and real separate browser contexts on an owned listener.

Run with repository Node dependencies and an explicitly acquired Playwright
browser. Only the external provider HTTP and native shell adapter are inert.
"""

import os
from pathlib import Path
import shutil
import subprocess
import threading

import pytest
from flask import g, request, send_file
from flinttrade_core.csp import inject_csp_nonce
from waitress.server import create_server
from flinttrade_core.service_oauth_routes import bind_desktop_oauth_port
from packages.core.core.tests import test_service_oauth as original
from packages.core.core.tests.test_service_oauth import create, flow as _flow

flow = _flow
pytestmark = pytest.mark.integration


def test_mounted_settings_external_browser_cookie_jar(flow, monkeypatch, tmp_path):
    if not os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        pytest.skip("explicit acquired Playwright browser required")
    app, renderer, store, provider, who = flow
    root = Path(__file__).resolve().parents[4]
    script = root / "packages/apps/terminal/e2e/service-oauth-handoff.browser.mjs"
    assets = tmp_path / "browser-assets"
    assets.mkdir()
    subprocess.run(["node", str(script), "build", str(assets)], check=True, timeout=30)
    app.add_url_rule("/_test/fixture.js", endpoint="test_script", view_func=lambda: send_file(assets / "fixture.js"))
    app.add_url_rule(
        "/_test/renderer",
        endpoint="test_renderer",
        view_func=lambda: inject_csp_nonce(
            '<!doctype html><html><body><div id="root"></div><script src="/_test/fixture.js"></script></body></html>',
            g.csp_nonce,
        ),
    )

    def provider_query():
        body = request.get_json()
        assert set(body) == {"nonce", "challenge"}
        provider.update(body)
        return "", 204

    app.add_url_rule("/_test/provider", view_func=provider_query, methods=["POST"])
    identifier, etag = create(renderer)
    socket_map = {}
    server = create_server(app, host="127.0.0.1", port=0, map=socket_map, threads=4)
    origin = f"http://127.0.0.1:{server.effective_port}"
    bind_desktop_oauth_port(app, server.effective_port)
    monkeypatch.setattr(original, "CALLBACK", origin + "/v1/services/connections/oauth/callback")
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        subprocess.run(["node", str(script), origin, str(assets), identifier], check=True, timeout=65)
        assert len(provider["calls"]) == 3
        if Path("/run/test/artifacts").exists():
            for name in ["browser.json", "browser.png"]:
                shutil.copy2(assets / name, Path("/run/test/artifacts") / name)
    finally:
        server.close()
        server.task_dispatcher.shutdown(timeout=5)
        for channel in list(socket_map.values()):
            channel.close()
        thread.join(timeout=5)
        assert not thread.is_alive()
