"""No raw credential hashes in incident identity; real HTTP and durable owners."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from uuid import uuid4

import pytest
from flask import Flask

pytestmark = pytest.mark.integration
KEY = "synthetic-weak-api-key"


@pytest.fixture
def incidents(tmp_path, monkeypatch):
    from flinttrade_core import auth_routes
    from flinttrade_core.incident_routes import incident_bp
    from flinttrade_core.system_incidents import IncidentTimeline

    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path / "workspace"))
    (tmp_path / "workspace").mkdir()
    monkeypatch.setenv("FLINTTRADE_API_KEY", KEY)
    monkeypatch.delenv("FLINTTRADE_DESKTOP", raising=False)
    monkeypatch.setattr(auth_routes, "_JWT_SECRET_KEY", "")
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(incident_bp)
    path = tmp_path / "incidents.sqlite"
    owner = IncidentTimeline(path)
    owners = [owner]
    app.config["SYSTEM_INCIDENTS"] = owner
    try:
        yield app, app.test_client(), owner, path, owners
    finally:
        for retained in reversed(owners):
            retained.close()


def new_delivery(owner):
    incident = owner.observe_http(str(uuid4()), 503, 1.0)
    return next(row["id"] for row in owner.snapshot()["incidents"] if row["id"] == incident["id"]
                for row in row["deliveries"] if row["channel"] == "desktop")


def test_email_binding_is_not_an_offline_password_verifier(incidents, monkeypatch):
    from flinttrade_core import auth_routes

    app, client, owner, path, _ = incidents
    fields = {"SMTP_HOST": "synthetic.invalid", "SMTP_PORT": "587", "SMTP_FROM": "from@example.invalid",
              "SMTP_USER": "synthetic-user", "SMTP_PASSWORD": "synthetic-weak-password"}
    for name, value in fields.items():
        monkeypatch.setenv(name, value)
    transport = auth_routes.EmailTransport()
    monkeypatch.setattr(auth_routes, "_email_transport", transport)
    recipient = "to@example.invalid"
    response = client.put("/api/v1/system/incidents/channels/email", headers={"X-API-Key": KEY},
                          json={"enabled": True, "provider": "smtp", "recipient": recipient})
    assert response.status_code == 200
    fingerprint = response.json["binding"]
    values = ("smtp", fields["SMTP_HOST"], 587, fields["SMTP_FROM"], fields["SMTP_USER"],
              fields["SMTP_PASSWORD"], recipient)
    guess = hashlib.sha256(json.dumps(values, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
    assert fingerprint != guess, "public/durable fingerprint is an offline SMTP password verifier"
    assert len(fingerprint) == 64
    assert client.get("/api/v1/system/incidents/channels/email", headers={"X-API-Key": KEY}).json["binding"] == fingerprint
    assert transport.incident_binding("smtp", recipient) == fingerprint
    # Official key owner reload retains identity; no extra durable key/custody.
    monkeypatch.setattr(auth_routes, "_JWT_SECRET_KEY", "")
    assert transport.incident_binding("smtp", recipient) == fingerprint
    original_password = transport._smtp_password
    transport._smtp_password = "changed-synthetic-password"
    assert transport.incident_binding("smtp", recipient) != fingerprint
    assert transport.send_incident("smtp", recipient, fingerprint, "inert", "inert") == "revoked"
    transport._smtp_password = original_password
    with sqlite3.connect(path) as db:
        persisted = db.execute("SELECT binding FROM channels WHERE channel='email'").fetchone()[0]
    assert persisted == fingerprint
    assert original_password not in path.read_bytes().decode("latin1")


@pytest.mark.parametrize("carrier", ["api_key", "api_key_bearer", "session"])
def test_browser_reader_binding_is_keyed_and_exact(incidents, monkeypatch, carrier):
    from flinttrade_core import auth_routes
    from flinttrade_core.system_incidents import IncidentTimeline

    app, client, owner, path, owners = incidents
    token = KEY
    if carrier == "session":
        with app.app_context():
            token = auth_routes._create_token("synthetic-operator")
            replacement = auth_routes._create_token("synthetic-operator")
    else:
        replacement = "another-synthetic-weak-api-key"
    header = "X-API-Key" if carrier == "api_key" else "Authorization"
    prefix = "" if carrier == "api_key" else "Bearer "
    headers = {header: prefix + token}
    delivery = new_delivery(owner)
    base = "/api/v1/system/incidents/deliveries/" + delivery
    claimed = client.post(base + "/claim", headers=headers)
    assert claimed.status_code == 200
    with sqlite3.connect(path) as db:
        reader = db.execute("SELECT reader FROM deliveries WHERE id=?", (delivery,)).fetchone()[0]
    assert reader != hashlib.sha256(token.encode()).hexdigest(), "retained reader is an unkeyed credential verifier"
    assert token not in path.read_bytes().decode("latin1")
    payload = {"claim": claimed.json["claim"], "state": "submitted_unobserved"}
    if carrier != "session":
        monkeypatch.setenv("FLINTTRADE_API_KEY", replacement)
    refused = client.post(base + "/receipt", headers={header: prefix + replacement}, json=payload)
    assert refused.status_code == 409
    assert owner.delivery(delivery)["state"] == "sending"
    monkeypatch.setenv("FLINTTRADE_API_KEY", KEY)
    accepted = client.post(base + "/receipt", headers=headers, json=payload)
    assert accepted.status_code == 200
    assert accepted.json["state"] == "submitted_unobserved"
    assert client.post(base + "/receipt", headers=headers, json=payload).status_code == 200
    assert client.post(base + "/claim", headers=headers).status_code == 409
    owner.close()
    restored = IncidentTimeline(path)
    owners.append(restored)
    app.config["SYSTEM_INCIDENTS"] = restored
    monkeypatch.setattr(auth_routes, "_JWT_SECRET_KEY", "")
    assert client.post(base + "/receipt", headers=headers, json=payload).status_code == 200
    assert restored.delivery(delivery)["attempts"] == 1


def test_unauthenticated_claim_never_creates_reader(incidents):
    _, client, owner, path, _ = incidents
    delivery = new_delivery(owner)
    response = client.post("/api/v1/system/incidents/deliveries/" + delivery + "/claim")
    assert response.status_code == 401
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT state,reader,claim,attempts FROM deliveries WHERE id=?", (delivery,)).fetchone() == (
            "browser_pending", None, None, 0)


def test_binding_domain_is_distinct_from_operator_identity(incidents):
    from flinttrade_core import auth_routes
    from flinttrade_core.incident_delivery import binding_digest

    app, _, _, _, _ = incidents
    with app.app_context():
        token = auth_routes._create_token("synthetic-operator")
        verified = auth_routes.verify_operator_session_token(token)
    binding = binding_digest(("browser-reader", token))
    assert binding != verified.session_binding.removeprefix("session:")
    assert binding != binding_digest(("smtp", token))
    assert binding != binding_digest(("browser-reader", token + "changed"))


def test_binding_depends_on_existing_authentication_key(incidents, monkeypatch):
    import secrets

    from flinttrade_core import auth_routes
    from flinttrade_core.incident_delivery import binding_digest

    values = ("smtp", "synthetic.invalid", 587, "from@example.invalid", "user", "weak", "to@example.invalid")
    first = binding_digest(values)
    monkeypatch.setattr(auth_routes, "_JWT_SECRET_KEY", secrets.token_urlsafe(64))
    assert binding_digest(values) != first, "fingerprint does not depend on the authentication key"


def test_legacy_unkeyed_reader_is_retained_but_not_accepted(incidents):
    app, client, owner, path, _ = incidents
    delivery = new_delivery(owner)
    # Seed exactly what the old public claim route persisted, via the public owner.
    legacy = hashlib.sha256(KEY.encode()).hexdigest()
    claimed = owner.claim_browser(delivery, legacy)
    before = owner.delivery(delivery)
    response = client.post("/api/v1/system/incidents/deliveries/" + delivery + "/receipt",
                           headers={"X-API-Key": KEY},
                           json={"claim": claimed["claim"], "state": "submitted_unobserved"})
    assert response.status_code == 409
    assert response.json == {"error": "browser_delivery_reader_retired"}
    assert owner.delivery(delivery) == before
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT reader FROM deliveries WHERE id=?", (delivery,)).fetchone()[0] == legacy
