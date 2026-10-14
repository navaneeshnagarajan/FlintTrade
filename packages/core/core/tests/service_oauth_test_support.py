"""Acquire an inert, signed grant through mounted HTTP for protocol fixtures."""

import base64
import hashlib
import json
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa


def acquire_chatgpt(client, identifier, headers, now):
    app = client.application
    base = "/v1/services/connections"
    origin = "http://127.0.0.1:5000"
    callback = origin + base + "/oauth/callback"
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    jwk["kid"] = "inert-test"
    query = {}

    def external(req):
        if req.url.path == "/.well-known/openid-configuration":
            return httpx.Response(
                200, json={"issuer": "https://auth.openai.com", "jwks_uri": "https://auth.openai.com/jwks"}
            )
        if req.url.path == "/jwks":
            return httpx.Response(200, json={"keys": [jwk]})
        assert req.url.path == "/api/accounts/oauth/token"
        body = parse_qs(req.content.decode())
        digest = (
            base64.urlsafe_b64encode(hashlib.sha256(body["code_verifier"][0].encode()).digest()).decode().rstrip("=")
        )
        assert digest == query["code_challenge"][0] and body["redirect_uri"] == [callback]
        claims = {
            "iss": "https://auth.openai.com",
            "aud": "oaiapp_fixture",
            "sub": "inert-user",
            "exp": int(now.timestamp()) + 3600,
            "iat": int(now.timestamp()),
            "nonce": query["nonce"][0],
        }
        return httpx.Response(
            200,
            json={
                "access_token": "synthetic-destination-secret",
                "refresh_token": "inert-refresh",
                "id_token": jwt.encode(claims, key, algorithm="RS256", headers={"kid": "inert-test"}),
                "token_type": "Bearer",
                "expires_in": 3600,
                "scope": "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct",
            },
        )

    app.config.update(
        SERVICE_OAUTH_CONFIG={"deployment": "local_oss", "redirect_uri": callback},
        SERVICE_OAUTH_CLOCK=lambda: now.timestamp(),
        SERVICE_OAUTH_TRANSPORT=httpx.MockTransport(external),
    )
    revision = client.get(base, headers=headers).headers["ETag"]
    start = client.post(
        base + f"/{identifier}/oauth/start",
        base_url=origin,
        headers={**headers, "If-Match": revision},
        json={},
        buffered=True,
    )
    assert start.status_code == 200
    data = start.get_json()
    query.update(parse_qs(urlsplit(data["authorization_url"]).query))
    received = client.get(
        callback,
        query_string={"state": query["state"][0], "code": "inert-code", "client_id": "oaiapp_fixture"},
        buffered=True,
    )
    assert received.status_code == 200
    result = client.post(
        base + f"/{identifier}/oauth/complete",
        headers={**headers, "If-Match": revision},
        json={"transaction_id": data["transaction_id"]},
        buffered=True,
    )
    assert result.status_code == 200 and result.get_json() == {"status": "connected"}
