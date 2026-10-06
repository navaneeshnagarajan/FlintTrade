"""Every mounted route is session-authenticated unless it is on the public allowlist.

Walks ``app.url_map`` (the Flask route table, including mounted blueprints) and
rejects a new route that is neither allowlisted nor protected.
"""

from __future__ import annotations

import base64
import json
import logging
import time

import jwt
import pytest

from flinttrade_core.public_routes import PUBLIC_ROUTES, is_public_route

pytestmark = pytest.mark.unit

_BODY_METHODS = frozenset({"POST", "PUT", "PATCH"})


def _sample_values(rule) -> dict[str, object]:
    """Build converter samples so the rule can be requested."""
    values: dict[str, object] = {}
    for name, converter in rule._converters.items():
        kind = type(converter).__name__
        if kind == "IntegerConverter":
            values[name] = 1
        elif kind == "FloatConverter":
            values[name] = 1.0
        elif kind == "UUIDConverter":
            values[name] = "11111111-1111-1111-1111-111111111111"
        elif kind == "PathConverter":
            values[name] = "sample/path"
        else:
            values[name] = "sample"
    return values


def _concrete_path(rule) -> str:
    """Return the request path for ``rule``.

    Werkzeug's ``Rule.build`` returns ``(subdomain, path)``.
    """
    built = rule.build(_sample_values(rule), append_unknown=False)
    assert built is not None, rule.rule
    for part in built:
        if isinstance(part, str) and part.startswith("/"):
            return part
    raise AssertionError(f"could not build a path for {rule.rule!r}: {built!r}")


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _alg_none(payload: dict[str, object]) -> str:
    """Build an ``alg: none`` bearer. The session check must reject it."""
    header = _b64url(json.dumps({"alg": "none", "typ": "JWT"}, separators=(",", ":")).encode())
    body = _b64url(json.dumps(payload, separators=(",", ":")).encode())
    return f"{header}.{body}."


def _rejected_bearers(secret: str) -> list[str]:
    """Credentials that must not open a non-public route."""
    now = int(time.time())
    claims = {"sub": "operator", "type": "session", "jti": "route-table"}
    wrong_key = "wrong-signing-key-not-used-for-sessions"
    return [
        "not-a-valid-token",
        jwt.encode({**claims, "iat": now - 7200, "exp": now - 3600}, secret, algorithm="HS256"),
        jwt.encode({**claims, "iat": now - 7200, "exp": now - 3600}, wrong_key, algorithm="HS256"),
        jwt.encode({**claims, "iat": now, "exp": now + 3600}, wrong_key, algorithm="HS256"),
        _alg_none({**claims, "iat": now, "exp": now + 3600}),
    ]


def test_non_public_routes_reject_missing_and_invalid_credentials(monkeypatch) -> None:
    """Unauthenticated and invalid-bearer calls get 401 before validation.

    A route added without an allowlist entry fails this test.
    """
    monkeypatch.delenv("FLINTTRADE_API_KEY", raising=False)
    monkeypatch.delenv("FLINTTRADE_API_KEY", raising=False)
    logging.getLogger().setLevel(logging.WARNING)

    from flinttrade_core.app import create_flask_app

    app = create_flask_app()
    app.config["TESTING"] = True
    app.config["PROPAGATE_EXCEPTIONS"] = False
    app.config["RATELIMIT_ENABLED"] = False
    limiter = app.config.get("LIMITER")
    if limiter is not None:
        limiter.enabled = False
    monitor = app.config.get("SECURITY_MONITOR")
    previous_threshold = None
    if monitor is not None:
        previous_threshold = monitor._auth_ban_threshold
        monitor._auth_ban_threshold = 10**9
        monitor._records.pop("127.0.0.1", None)

    try:
        registered: set[tuple[str, str]] = set()
        for rule in app.url_map.iter_rules():
            for method in rule.methods or ():
                registered.add((method, rule.rule))

        missing = sorted(PUBLIC_ROUTES - registered)
        assert not missing, f"allowlist entries are not mounted: {missing}"
        assert ("GET", "/v1/sandbox/positions") in registered

        from flinttrade_core.auth_routes import _get_jwt_secret

        client = app.test_client()
        bearers = _rejected_bearers(_get_jwt_secret())
        api_key = "route-table-api-key-sentinel"
        assert all(token != api_key for token in bearers)

        healthz = client.get("/healthz")
        readyz = client.get("/readyz")
        assert healthz.status_code == 200
        assert set(healthz.get_json()) == {"status"}
        assert readyz.status_code in (200, 503)
        assert set(readyz.get_json()) == {"status"}
        ping = client.get("/api/v1/ping")
        assert ping.status_code == 200
        assert set(ping.get_json()) == {
            "status",
            "timestamp",
            "laya",
            "laya_practice",
            "laya_live_qualified",
            "laya_reason",
            "laya_port",
            "laya_download_bytes",
            "laya_download_total",
        }
        assert client.get("/api/v1/health").status_code == 401
        assert client.get("/health").status_code == 401

        for content_type, body in (
            ("application/csp-report", '{"csp-report":{"blocked-uri":"https://example.test"}}'),
            ("application/reports+json", '[{"type":"csp-violation","body":{"blocked-uri":"https://example.test"}}]'),
        ):
            report = client.post("/csp-report", data=body, content_type=content_type)
            assert report.status_code == 204, content_type
            assert report.get_data() == b""

        failures: list[str] = []

        def _probe(label: str) -> None:
            for rule in app.url_map.iter_rules():
                methods = sorted((rule.methods or set()) - {"OPTIONS"})
                probed = [method for method in methods if not is_public_route(method, rule.rule)]
                if not probed:
                    continue
                path = _concrete_path(rule)
                for method in probed:
                    kwargs: dict[str, object] = {}
                    if method in _BODY_METHODS:
                        kwargs["data"] = "{}"
                        kwargs["content_type"] = "application/json"
                    missing_auth = client.open(path, method=method, **kwargs)
                    if missing_auth.status_code != 401:
                        failures.append(f"{label} {method} {rule.rule} missing={missing_auth.status_code}")
                    for bearer in bearers:
                        rejected = client.open(
                            path,
                            method=method,
                            headers={"Authorization": f"Bearer {bearer}"},
                            **kwargs,
                        )
                        if rejected.status_code != 401:
                            failures.append(f"{label} {method} {rule.rule} bearer={rejected.status_code}")

        _probe("no-key")
        monkeypatch.setenv("FLINTTRADE_API_KEY", api_key)
        _probe("api-key")
        assert not failures, "routes answered without a session:\n" + "\n".join(failures[:40])
    finally:
        if monitor is not None:
            monitor._auth_ban_threshold = previous_threshold
            monitor._records.pop("127.0.0.1", None)
