"""Account action headers use the existing exact-origin CORS policy."""

from __future__ import annotations


def test_account_action_preflights_preserve_exact_origin_policy(monkeypatch, tmp_path):
    from flinttrade_core.app import create_flask_app

    origins = ("http://127.0.0.1:5173", "http://localhost:5173")
    monkeypatch.setenv("FLINTTRADE_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("CORS_ORIGINS", ",".join(origins))
    app = create_flask_app()
    paths = (
        ("/api/v1/native/accounts", "POST"),
        ("/api/v1/native/oauth/start", "POST"),
        ("/api/v1/native/accounts/dhan/fixture/login", "POST"),
        ("/api/v1/native/accounts/dhan/fixture/set-primary", "POST"),
        ("/api/v1/native/accounts/dhan/fixture", "DELETE"),
        ("/v1/accounts/fixture/reconnect", "POST"),
        ("/v1/accounts/fixture/set-primary", "POST"),
        ("/v1/accounts/fixture", "DELETE"),
        ("/v1/auth/oauth/start", "POST"),
        ("/v1/auth/otp/verify", "POST"),
        ("/v1/services/connections/fixture", "PATCH"),
    )
    with app.test_client() as client:
        for path, method in paths:
            for origin in origins:
                response = client.options(path, headers={
                    "Origin": origin,
                    "Access-Control-Request-Method": method,
                    "Access-Control-Request-Headers": "Content-Type,Authorization,If-Match,Idempotency-Key",
                })
                assert response.headers["Access-Control-Allow-Origin"] == origin
                assert method in response.headers["Access-Control-Allow-Methods"].split(", ")
                assert {"Content-Type", "Authorization", "If-Match", "Idempotency-Key"} <= set(
                    response.headers["Access-Control-Allow-Headers"].split(", ")
                )
            foreign = client.options(path, headers={
                "Origin": "https://foreign.invalid", "Access-Control-Request-Method": method,
                "Access-Control-Request-Headers": "Idempotency-Key",
            })
            assert "Access-Control-Allow-Origin" not in foreign.headers
