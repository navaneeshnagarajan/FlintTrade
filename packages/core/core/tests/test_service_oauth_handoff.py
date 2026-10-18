"""External-browser launch owns a fresh cookie, not the renderer cookie."""

from urllib.parse import parse_qs, urlsplit

import pytest
from packages.core.core.tests.test_service_oauth import BASE, CALLBACK, HEADERS, create, flow as _flow

flow = _flow
pytestmark = pytest.mark.integration


def begin(flow):
    app, renderer, store, provider, who = flow
    identifier, etag = create(renderer)
    started = renderer.post(
        BASE + f"/{identifier}/oauth/start", headers={**HEADERS, "If-Match": etag}, json={"browser": "external"}
    )
    assert started.status_code == 200
    return identifier, etag, started.json


def test_external_bootstrap_cookie_and_original_completion(flow):
    app, renderer, store, provider, who = flow
    identifier, etag, attempt = begin(flow)
    external = app.test_client()
    launch = external.get(attempt["authorization_url"])
    assert launch.status_code == 302
    query = parse_qs(urlsplit(launch.headers["Location"]).query)
    provider.update(nonce=query["nonce"][0], challenge=query["code_challenge"][0])
    cookie = launch.headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie and "Path=" + BASE + "/oauth/callback" in cookie
    assert launch.headers["Referrer-Policy"] == "no-referrer"
    assert external.get(attempt["authorization_url"]).status_code == 409
    callback = {"state": query["state"][0], "code": "inert-code", "client_id": "oaiapp_test"}
    # The start/renderer cookie cannot replace the independently bound browser.
    assert renderer.get(CALLBACK, query_string=callback).status_code == 400
    assert app.test_client().get(CALLBACK, query_string=callback).status_code == 400
    result = external.get(CALLBACK, query_string=callback)
    assert result.status_code == 200
    assert provider["calls"] == []
    result = external.post(BASE + f"/{identifier}/oauth/complete", json={"transaction_id": attempt["transaction_id"]})
    assert result.status_code == 401
    result = renderer.post(
        BASE + f"/{identifier}/oauth/complete",
        headers={**HEADERS, "If-Match": etag},
        json={"transaction_id": attempt["transaction_id"]},
    )
    assert result.status_code == 200
    assert external.get(CALLBACK, query_string=callback).status_code == 409


@pytest.mark.parametrize("retirement", ["cancel", "expiry", "revision", "port"])
def test_bootstrap_refuses_retired_attempt_without_cookie_or_provider_call(flow, retirement):
    app, renderer, store, provider, who = flow
    identifier, etag, attempt = begin(flow)
    if retirement == "cancel":
        result = renderer.post(
            BASE + f"/{identifier}/oauth/cancel",
            headers={**HEADERS, "If-Match": etag},
            json={"transaction_id": attempt["transaction_id"]},
        )
        assert result.status_code == 200
    elif retirement == "expiry":
        provider["now"] += 601
    elif retirement == "revision":
        create(renderer)
    else:
        app.config["SERVICE_OAUTH_CONFIG"]["redirect_uri"] = CALLBACK.replace(":5000", ":5001")
    result = app.test_client().get(attempt["authorization_url"])
    assert result.status_code in {403, 409, 410, 412}
    assert "Set-Cookie" not in result.headers and "Location" not in result.headers
    assert provider["calls"] == []
