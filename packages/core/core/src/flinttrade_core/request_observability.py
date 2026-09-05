"""Fixed request summaries for enumerated secret-envelope route families."""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import asdict, dataclass

MAX_OBSERVED_CONTENT_LENGTH = 64 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class SafeRequestSummary:
    """The complete request projection allowed on a secret-envelope surface."""

    route_template: str
    method: str
    content_length: int | None
    has_credentials: bool

    def to_dict(self) -> dict[str, object]:
        """Return a detached fixed-field representation."""
        return asdict(self)


_CURRENT_SAFE_REQUEST: ContextVar[SafeRequestSummary | None] = ContextVar(
    "flinttrade_safe_secret_request", default=None
)


def _normalise_path(path: object) -> str | None:
    if type(path) is not str:
        return None
    clean = path.split("?", 1)[0]
    if clean == "/ft-api":
        return "/"
    if clean.startswith("/ft-api/"):
        return clean[len("/ft-api") :]
    return clean


def _exact_or_descendant(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix + "/")


def classify_secret_envelope(method: object, path: object) -> str | None:
    """Return a fixed template for an enumerated secret route, else ``None``."""
    if type(method) is not str:
        return None
    clean = _normalise_path(path)
    if clean is None:
        return None
    if _exact_or_descendant(clean, "/v1/services/connections"):
        return (
            "/v1/services/connections"
            if clean == "/v1/services/connections"
            else "/v1/services/connections/{connection_id}"
        )
    if _exact_or_descendant(clean, "/v1/accounts"):
        return "/v1/accounts" if clean == "/v1/accounts" else "/v1/accounts/{account_id}/reconnect"
    if _exact_or_descendant(clean, "/api/v1/native/accounts"):
        return (
            "/api/v1/native/accounts"
            if clean == "/api/v1/native/accounts"
            else "/api/v1/native/accounts/{adapter_id}/{account_id}/login"
        )
    for prefix, template in (
        ("/api/v1/native/oauth/start", "/api/v1/native/oauth/start"),
        ("/api/v1/native/oauth/callback", "/api/v1/native/oauth/callback"),
        ("/v1/auth/credentials", "/v1/auth/credentials"),
        ("/v1/auth/oauth/start", "/v1/auth/oauth/start"),
        ("/v1/auth/oauth/callback", "/v1/auth/oauth/callback"),
        ("/v1/auth/otp/request", "/v1/auth/otp/request"),
        ("/v1/auth/otp/verify", "/v1/auth/otp/verify"),
        ("/v1/auth/setup/regenerate-2fa", "/v1/auth/setup/regenerate-2fa"),
        ("/v1/auth/setup/reset", "/v1/auth/setup/reset"),
        ("/v1/auth/setup", "/v1/auth/setup"),
        ("/v1/auth/login", "/v1/auth/login"),
        ("/v1/auth/pin/set", "/v1/auth/pin/set"),
        ("/v1/auth/pin", "/v1/auth/pin"),
        ("/v1/auth/reset-password-otp", "/v1/auth/reset-password-otp"),
        ("/v1/auth/reset-password", "/v1/auth/reset-password"),
        ("/v1/config/llm", "/v1/config/llm"),
        ("/v1/config/openalgo", "/v1/config/openalgo"),
        ("/v1/test-connection", "/v1/test-connection"),
    ):
        if _exact_or_descendant(clean, prefix):
            return template
    return None


def project_safe_request(method: object, path: object, content_length: object) -> SafeRequestSummary | None:
    """Project a request without parsing or retaining any envelope content."""
    template = classify_secret_envelope(method, path)
    if template is None:
        return None
    length = content_length if type(content_length) is int and content_length >= 0 else None
    if length is not None:
        length = min(length, MAX_OBSERVED_CONTENT_LENGTH)
    return SafeRequestSummary(template, str(method), length, True)


def set_safe_request_summary(summary: SafeRequestSummary | None) -> Token[SafeRequestSummary | None]:
    """Set the synchronous request-lifetime sensitivity marker."""
    return _CURRENT_SAFE_REQUEST.set(summary)


def reset_safe_request_summary(token: Token[SafeRequestSummary | None]) -> None:
    """Restore the preceding synchronous request-lifetime marker."""
    _CURRENT_SAFE_REQUEST.reset(token)


def current_safe_request_summary() -> SafeRequestSummary | None:
    """Return the current synchronous secret-request projection."""
    return _CURRENT_SAFE_REQUEST.get()
