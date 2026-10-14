"""Request custody follows the actual WSGI iterator, including send_file."""
from io import BytesIO

from flask import Flask, Response, send_file
import pytest

from flinttrade_core.app import _install_runtime_request_tracking

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("kind", ["file", "stream", "passthrough"])
@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_response_close_releases_real_request_custody(kind, method):
    app = Flask(__name__)
    tracker = _install_runtime_request_tracking(app)
    closed = []

    def chunks():
        try:
            yield b"first"
            yield b"second"
        finally:
            closed.append(True)

    @app.get("/body")
    def body():
        if kind == "file":
            return send_file(BytesIO(b"synthetic asset"), mimetype="application/octet-stream")
        return Response(chunks(), direct_passthrough=kind == "passthrough")

    response = app.test_client().open("/body", method=method)
    try:
        if method == "GET":
            assert tracker.wait_for_idle(0) is False
    finally:
        response.close()
    assert tracker.wait_for_idle(0) is True
    if method == "GET" and kind != "file":
        assert closed == [True]
    response.close()
    assert tracker.wait_for_idle(0) is True
