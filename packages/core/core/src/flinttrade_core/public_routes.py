"""Public route allowlist for the Flask backend.

Session auth is the default for every mounted route. A route stays reachable
without a session JWT or API key only when it is listed here, with the reason
beside the entry. New routes are protected until they are added explicitly.
"""

from __future__ import annotations

# (method, Flask rule). HEAD follows GET. OPTIONS is always public (CORS preflight).
_PUBLIC_ROUTE_ENTRIES: tuple[tuple[str, str], ...] = (
    # Liveness probe. Returns no operator data.
    ("GET", "/api/v1/ping"),
    # Aggregated subsystem health. Same public surface as the liveness probe.
    ("GET", "/api/v1/health"),
    # Auth status is read before a session exists, including first-run setup.
    ("GET", "/v1/auth/status"),
    # Login mints the session. It cannot require the session it creates.
    ("POST", "/v1/auth/login"),
    # First-run account creation, before any session exists.
    ("POST", "/v1/auth/setup"),
    # Vault open during first-run. The handler requires a setup-session JWT,
    # not the daily API key, so the global check must let the request through.
    ("POST", "/v1/auth/setup/vault"),
    # First-run reset. Reachable with the operator password or a setup JWT
    # before a daily session exists.
    ("POST", "/v1/auth/setup/reset"),
    # Setup-wizard authenticator regeneration. The handler checks the password.
    ("POST", "/v1/auth/setup/regenerate-2fa"),
    # Password recovery. No session exists yet.
    ("POST", "/v1/auth/forgot-password"),
    ("POST", "/v1/auth/reset-password"),
    ("POST", "/v1/auth/forgot-password-otp"),
    ("POST", "/v1/auth/reset-password-otp"),
    # Frontend error reports. Fire-and-forget; the response carries no secrets.
    ("POST", "/v1/errors"),
    ("POST", "/api/v1/errors"),
    # In-app changelog. Public documentation, no operator data.
    ("GET", "/v1/changelog"),
    # Public documentation search and document reads.
    ("GET", "/v1/docs/search"),
    ("GET", "/v1/docs/document"),
    ("GET", "/v1/docs/changelog"),
    # Setup-wizard OpenAlgo probe. After the operator account exists the
    # handler itself requires a session.
    ("GET", "/v1/config/openalgo"),
    ("POST", "/v1/config/openalgo"),
    # Setup-wizard connectivity probe. The handler is loopback-only.
    ("POST", "/v1/test-connection"),
    # Signed webhook intake. HMAC is checked inside the receiver.
    # GET /v1/webhook/log stays authenticated.
    ("POST", "/v1/webhook/<source>"),
    ("POST", "/v1/webhook/<source>/<path:webhook_id>"),
    # Browser CSP report-uri. The browser cannot attach a session.
    ("POST", "/csp-report"),
    # Broker OAuth browser redirect. The state token is the check.
    ("GET", "/v1/auth/oauth/callback"),
    ("GET", "/api/v1/native/oauth/callback"),
    # Broker server postback. The broker cannot send a FlintTrade session.
    ("POST", "/api/v1/native/postbacks/<adapter_id>"),
)

PUBLIC_ROUTES: frozenset[tuple[str, str]] = frozenset(_PUBLIC_ROUTE_ENTRIES)

# SPA shell rules. They are public only for non-API paths; unknown /v1, /api,
# and /ft-api paths that fall through to the catch-all stay authenticated.
_SPA_RULES = frozenset({"/", "/<path:path>"})
_API_PREFIXES = ("/api/", "/ft-api/", "/v1/")


def is_public_route(method: str, rule: str, *, path: str | None = None) -> bool:
    """Return whether ``method`` on ``rule`` may run without a session or API key.

    Args:
        method: HTTP method. ``HEAD`` follows ``GET``. ``OPTIONS`` is always public.
        rule: Flask rule string, such as ``/v1/auth/login``.
        path: Concrete request path. Pass it at request time so the SPA catch-all
            does not treat ``/v1/...`` as a public document. Omit it when
            classifying the route table; the shell rules are then public.

    Returns:
        True when the route is on the public allowlist or is a non-API shell path.
    """
    normalised = method.upper()
    if normalised == "OPTIONS":
        return True
    if normalised == "HEAD":
        normalised = "GET"
    if rule in _SPA_RULES:
        if path is None:
            return True
        return not any(path.startswith(prefix) for prefix in _API_PREFIXES)
    return (normalised, rule) in PUBLIC_ROUTES
