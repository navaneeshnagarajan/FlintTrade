"""Retired gateway writes cannot reconnect an external broker bridge."""

import pytest
from flask import Flask

from flinttrade_gateway.auth import gateway_bp


@pytest.mark.parametrize("path,method", [
    ("/v1/accounts", "POST"),
    ("/v1/accounts/default/reconnect", "POST"),
    ("/v1/oauth/start", "POST"),
    ("/v1/credentials", "POST"),
    ("/v1/otp/request", "POST"),
])
def test_gateway_account_writes_are_retired(path, method):
    app = Flask(__name__)
    app.register_blueprint(gateway_bp)
    assert app.test_client().open(path, method=method).status_code in (404, 405)
