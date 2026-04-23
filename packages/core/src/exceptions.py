"""FlintTrade exception hierarchy."""


class FlintTradeError(Exception):
    """Base exception for all FlintTrade errors."""


class ConfigError(FlintTradeError):
    """Missing or invalid configuration."""


class APIError(FlintTradeError):
    """OpenAlgo API returned an error."""

    def __init__(self, status_code: int, message: str, endpoint: str) -> None:
        self.status_code = status_code
        self.message = message
        self.endpoint = endpoint
        super().__init__(f"[{status_code}] {endpoint}: {message}")


class RateLimitError(APIError):
    """Rate limit exceeded (HTTP 429)."""

    def __init__(self, endpoint: str, retry_after: float | None = None) -> None:
        self.retry_after = retry_after
        super().__init__(429, "Rate limit exceeded", endpoint)


class AuthError(APIError):
    """Authentication failed (HTTP 401/403)."""

    def __init__(
        self,
        endpoint: str,
        message: str = "Authentication failed",
        status_code: int = 401,
    ) -> None:
        super().__init__(status_code, message, endpoint)
