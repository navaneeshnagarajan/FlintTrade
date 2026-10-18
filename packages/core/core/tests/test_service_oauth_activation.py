"""Desktop activation is explicit, durable and rebound to the owned listener."""

import pytest
from packages.core.core.tests.test_service_oauth import BASE, CALLBACK, HEADERS, create, flow as _flow

flow = _flow
pytestmark = pytest.mark.integration


def test_desktop_activation_is_explicit_and_retains_only_local_oss_choice(flow):
    app, client, store, provider, who = flow
    identifier, etag = create(client)
    app.config["SERVICE_OAUTH_CONFIG"] = {"desktop_bound": True, "redirect_uri": CALLBACK}
    assert store.oauth.capabilities()["configured"] is False
    result = client.post(
        BASE + "/oauth/configuration", headers={**HEADERS, "If-Match": etag}, json={"deployment": "local_oss"}
    )
    assert result.status_code == 200
    assert client.get(BASE, headers=HEADERS).json["oauth"]["configured"] is True
    assert provider["calls"] == []
    # Restart composition can change the actual port, never the stored opt-in.
    from flinttrade_core.service_oauth import ServiceOAuth

    app.config["SERVICE_OAUTH_CONFIG"]["redirect_uri"] = CALLBACK.replace(":5000", ":5001")
    reopened = ServiceOAuth(store, config=lambda: app.config["SERVICE_OAUTH_CONFIG"])
    assert reopened.settings() == CALLBACK.replace(":5000", ":5001")
    result = client.post(
        BASE + "/oauth/configuration", headers={**HEADERS, "If-Match": etag}, json={"deployment": "api_only"}
    )
    assert result.status_code == 200
    assert store.oauth.capabilities()["configured"] is False


@pytest.mark.parametrize("deployment", ["commercial", "partner", "xai", "anthropic", True, None])
def test_activation_refuses_unsupported_deployment(flow, deployment):
    app, client, store, provider, who = flow
    identifier, etag = create(client)
    app.config["SERVICE_OAUTH_CONFIG"] = {"desktop_bound": True, "redirect_uri": CALLBACK}
    result = client.post(
        BASE + "/oauth/configuration", headers={**HEADERS, "If-Match": etag}, json={"deployment": deployment}
    )
    assert result.status_code == 400
    assert not store.oauth.capabilities()["configured"]
    assert provider["calls"] == []


def test_activation_refuses_non_desktop_and_foreign_collection(flow):
    app, client, store, provider, who = flow
    identifier, etag = create(client)
    result = client.post(
        BASE + "/oauth/configuration", headers={**HEADERS, "If-Match": etag}, json={"deployment": "local_oss"}
    )
    assert result.status_code == 422
    app.config["SERVICE_OAUTH_CONFIG"] = {"desktop_bound": True, "redirect_uri": CALLBACK}
    create(client)
    result = client.post(
        BASE + "/oauth/configuration", headers={**HEADERS, "If-Match": etag}, json={"deployment": "local_oss"}
    )
    assert result.status_code == 412
    assert not store.oauth.capabilities()["configured"]


def test_activation_cycle_cannot_revive_inflight_refresh(flow):
    from packages.core.core.tests.test_service_oauth import connected

    app, client, store, provider, who = flow
    identifier, etag = connected(flow)
    app.config["SERVICE_OAUTH_CONFIG"] = {"desktop_bound": True, "redirect_uri": CALLBACK}
    store.oauth.configure("local_oss", etag, lambda: None)
    provider["now"] += 3600

    def retire():
        store.oauth.configure("api_only", etag, lambda: None)
        store.oauth.configure("local_oss", etag, lambda: None)

    provider["token_hook"] = retire
    result = client.post(BASE + f"/{identifier}/oauth/refresh", headers={**HEADERS, "If-Match": etag}, json={})
    assert result.status_code == 403
    with store.oauth.locked() as (_, _, state):
        assert [g["status"] for g in state["grants"].values()] == ["refresh_unknown"]
