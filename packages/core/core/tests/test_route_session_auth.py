"""Every mounted route is session-authenticated unless it is on the public allowlist.

Walks ``app.url_map`` (the Flask route table, including mounted blueprints) and
rejects a new route that is neither allowlisted nor protected.
"""

from __future__ import annotations

import logging

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


def test_non_public_routes_reject_missing_and_invalid_credentials(monkeypatch) -> None:
    """Unauthenticated and invalid-bearer calls get 401 before validation.

    A route added without an allowlist entry fails this test.
    """
    monkeypatch.delenv("FLINTTRADE_API_KEY", raising=False)
    monkeypatch.delenv("OPENALGO_API_KEY", raising=False)
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

        client = app.test_client()
        failures: list[str] = []
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
                invalid = client.open(
                    path,
                    method=method,
                    headers={"Authorization": "Bearer not-a-valid-token"},
                    **kwargs,
                )
                if missing_auth.status_code != 401 or invalid.status_code != 401:
                    failures.append(
                        f"{method} {rule.rule} -> missing={missing_auth.status_code} "
                        f"invalid={invalid.status_code}"
                    )
        assert not failures, "routes answered without a session:\n" + "\n".join(failures)
    finally:
        if monitor is not None:
            monitor._auth_ban_threshold = previous_threshold
            monitor._records.pop("127.0.0.1", None)
